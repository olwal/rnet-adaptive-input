"""A small physically-based renderer for the labyrinth demo.

Cook-Torrance GGX, normal mapping derived in the fragment shader (so no mesh
tangents are required), a hemispheric ambient term, and an *analytic*
environment used for metal reflections. The analytic environment is the trick
that makes a convincing chrome ball without any cubemap: a sky gradient, a
ground colour and a sun disc, evaluated straight from the reflection vector.

The ball's shadow is an analytic ray-sphere soft shadow rather than a shadow
map - exact for a single sphere, and it costs nothing.
"""

import pyray as rl

VS = """
#version 330

in vec3 vertexPosition;
in vec2 vertexTexCoord;
in vec3 vertexNormal;
in vec4 vertexColor;

uniform mat4 mvp;
uniform mat4 matModel;
uniform mat4 matNormal;

out vec3 fragPosition;
out vec2 fragTexCoord;
out vec3 fragNormal;
out vec4 fragColor;

void main()
{
    fragPosition = vec3(matModel * vec4(vertexPosition, 1.0));
    fragTexCoord = vertexTexCoord;
    fragNormal   = normalize(vec3(matNormal * vec4(vertexNormal, 1.0)));
    fragColor    = vertexColor;
    gl_Position  = mvp * vec4(vertexPosition, 1.0);
}
"""

FS = """
#version 330

in vec3 fragPosition;
in vec2 fragTexCoord;
in vec3 fragNormal;
in vec4 fragColor;

uniform sampler2D texture0;     // albedo   (MATERIAL_MAP_DIFFUSE)
uniform sampler2D texture1;     // r=rough g=ao  (MATERIAL_MAP_SPECULAR)
uniform sampler2D texture2;     // normal   (MATERIAL_MAP_NORMAL)
uniform vec4 colDiffuse;

uniform vec3 viewPos;
uniform vec3 lightDir;          // points *from* the surface toward the light
uniform vec3 lightColor;
uniform vec3 skyColor;
uniform vec3 groundColor;

uniform float uMetallic;
uniform float uRoughness;       // multiplies the roughness map
uniform float uUseMaps;         // 1 = sample textures, 0 = flat material
uniform float uUseNormalMap;
uniform vec3  uAlbedo;          // used when uUseMaps == 0

uniform vec4  uShadowSphere;    // xyz centre, w radius (w <= 0 disables)
uniform float uTexScale;
uniform float uAlphaCut;        // 1 = discard where albedo alpha < 0.5
uniform float uClearcoat;       // varnish lobe strength
uniform float uWrap;            // diffuse wrap, for translucent stone

// A real lamp at a position, not a direction. As the ball travels the vector
// to the lamp changes, so its highlight slides across the surface - which a
// directional light can never do.
uniform vec3  uPointPos;
uniform vec3  uPointCol;
uniform float uPointRange;

// An oriented elliptical shadow, for bodies a sphere does not approximate -
// a car being the obvious one. xyz = centre, w = half length (<=0 disables).
uniform vec4 uBodyShadow;
uniform vec3 uBodyFwd;      // xz forward, y unused
uniform float uBodyHalfW;

// Planar reflection of the board, for the ball. A chrome sphere sitting on a
// wooden board should show that board; an analytic sky alone never will.
uniform sampler2D texture3;     // board albedo  (MATERIAL_MAP_ROUGHNESS slot)
uniform float uPlanarRefl;
uniform vec3  uBoardC;          // board centre, world
uniform vec3  uBoardN;          // board normal, world
uniform vec3  uBoardT;          // board local +X, world
uniform vec3  uBoardB;          // board local +Z, world
uniform float uBoardHalf;

out vec4 finalColor;

const float PI = 3.14159265359;

mat3 cotangentFrame(vec3 N, vec3 p, vec2 uv)
{
    vec3 dp1 = dFdx(p);
    vec3 dp2 = dFdy(p);
    vec2 duv1 = dFdx(uv);
    vec2 duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, N);
    vec3 dp1perp = cross(N, dp1);
    vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;
    float invmax = inversesqrt(max(dot(T, T), dot(B, B)) + 1e-8);
    return mat3(T * invmax, B * invmax, N);
}

// Sky gradient + ground + sun disc, sampled by direction. Stands in for a
// cubemap: cheap, and for a lone chrome ball it is indistinguishable.
// A rectangular area light in direction space, with crisp edges. Hard edges
// are the whole point: a mirror reflecting a smooth gradient reads as pearl,
// and only sharp-edged sources make the eye call it chrome.
float softbox(vec3 d, vec3 dir, vec2 half_size, float soft)
{
    vec3 f = normalize(dir);
    vec3 r = normalize(cross(vec3(0.0, 1.0, 0.0), f) + vec3(1e-5));
    vec3 u = cross(f, r);
    float dp = dot(d, f);
    if (dp <= 0.02) return 0.0;
    vec2 p = vec2(dot(d, r), dot(d, u)) / dp;
    vec2 e = smoothstep(half_size + soft, half_size - soft, abs(p));
    return e.x * e.y;
}

vec3 envColor(vec3 d, float rough)
{
    float up = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 sky = mix(skyColor * 0.30, skyColor * 0.95, pow(up, 0.5));
    // A crisp horizon: the sphere shows a hard line between cool sky above and
    // a dark floor below, and that line bends with the curvature.
    float g = smoothstep(-0.02, 0.02, d.y);
    vec3 c = mix(groundColor, sky, g);

    // Small and hot rather than large and bright - big sources just blow the
    // whole upper hemisphere to white and the mirror stops reading as one.
    float blur = 0.03 + rough * 1.6;
    c += vec3(1.00, 0.99, 0.97) * softbox(d, vec3(-0.55, 0.95, -0.30),
                                          vec2(0.34, 0.19), blur) * 9.0;
    c += vec3(0.88, 0.94, 1.00) * softbox(d, vec3(0.90, 0.55, 0.35),
                                          vec2(0.16, 0.38), blur) * 4.5;
    c += vec3(1.00, 0.93, 0.80) * softbox(d, vec3(0.05, 0.35, -1.00),
                                          vec2(0.28, 0.11), blur) * 2.6;

    // Sun, tightened up as roughness falls so polished metal gets a hot spot.
    float sharp = mix(24.0, 2200.0, pow(1.0 - rough, 3.0));
    c += lightColor * pow(max(dot(d, lightDir), 0.0), sharp)
         * mix(1.0, 14.0, 1.0 - rough);

    // Rough surfaces see an increasingly averaged environment.
    vec3 avg = mix(groundColor, skyColor, 0.55);
    return mix(c, avg, rough * rough);
}

float distributionGGX(float NdotH, float a)
{
    float a2 = a * a;
    float d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    return a2 / max(PI * d * d, 1e-7);
}

float geometrySmith(float NdotV, float NdotL, float rough)
{
    float k = (rough + 1.0) * (rough + 1.0) / 8.0;
    float gv = NdotV / (NdotV * (1.0 - k) + k);
    float gl = NdotL / (NdotL * (1.0 - k) + k);
    return gv * gl;
}

vec3 fresnelSchlick(float c, vec3 F0)
{
    return F0 + (1.0 - F0) * pow(clamp(1.0 - c, 0.0, 1.0), 5.0);
}

// Roughness-aware Fresnel for the ambient/IBL term. Using plain Schlick here
// (or worse, F0 + F*0.5) hands the surface more energy than it received, and
// a mirror ball comes out uniformly pale no matter how dark the environment.
vec3 fresnelSchlickRoughness(float c, vec3 F0, float rough)
{
    vec3 Fr = max(vec3(1.0 - rough), F0);
    return F0 + (Fr - F0) * pow(clamp(1.0 - c, 0.0, 1.0), 5.0);
}

// Soft shadow from a single sphere (Quilez). The penumbra widens with
// distance from the occluder, which is the part a blob decal never gets right.
float sphereShadow(vec3 ro, vec3 rd, vec4 sph, float k)
{
    if (sph.w <= 0.0) return 1.0;
    vec3 oc = sph.xyz - ro;
    float b = dot(oc, rd);
    if (b < 0.0) return 1.0;
    float h = sqrt(max(dot(oc, oc) - b * b, 0.0)) - sph.w;
    float res = clamp(k * h / b, 0.0, 1.0);
    return res * res * (3.0 - 2.0 * res);
}

// Analytic ambient occlusion from a sphere (Quilez). Blocking direct light is
// only half of a contact shadow - without occluding the ambient too, the ball
// reads as hovering no matter how good the cast shadow is.
float sphereOcclusion(vec3 pos, vec3 nor, vec4 sph)
{
    if (sph.w <= 0.0) return 0.0;
    vec3 di = sph.xyz - pos;
    float l = length(di);
    float nl = dot(nor, di / l);
    float h = l / sph.w;
    if (h <= 1.0) return 0.0;
    float h2 = h * h;
    float k2 = 1.0 - h2 * nl * nl;
    float res = max(0.0, nl) / h2;
    if (k2 > 0.001) {
        res = nl * acos(-nl * sqrt((h2 - 1.0) / (1.0 - nl * nl)))
              - sqrt(k2 * (h2 - 1.0));
        res = res / h2 + atan(sqrt(k2 / (h2 - 1.0)));
        res /= 3.141593;
    }
    return clamp(res, 0.0, 1.0);
}

// Ground shading under an oriented box. Cheap stand-in for a shadow map:
// exact enough for one moving body on open terrain, and it costs nothing.
float bodyShadow(vec3 p)
{
    if (uBodyShadow.w <= 0.0) return 1.0;
    vec2 d = p.xz - uBodyShadow.xz;
    vec2 f = normalize(uBodyFwd.xz + vec2(1e-5, 0.0));
    vec2 r = vec2(f.y, -f.x);
    float a = dot(d, f) / uBodyShadow.w;
    float b = dot(d, r) / max(uBodyHalfW, 1e-3);
    float e = sqrt(a * a + b * b);
    // Fades out as the body lifts away from the surface.
    float lift = clamp(1.0 - abs(p.y - uBodyShadow.y) / 4.0, 0.0, 1.0);
    return 1.0 - 0.78 * smoothstep(1.25, 0.45, e) * lift;
}

// One light's contribution. Factored out because there are now two, and the
// clearcoat lobe has to follow each of them.
vec3 directLight(vec3 N, vec3 V, vec3 L, vec3 radiance, vec3 albedo,
                 float rough, vec3 F0, float metallic, float wrap, float cc)
{
    vec3 H = normalize(V + L);
    float NdotV = max(dot(N, V), 1e-4);
    float raw = dot(N, L);
    float NdotL = max(raw, 0.0);
    float NdotLs = max(NdotL, 1e-4);
    // Wrapped diffuse: light bleeds past the terminator, which is most of what
    // makes stone read as stone rather than painted plaster.
    float diff = max((raw + wrap) / (1.0 + wrap), 0.0);
    float NdotH = max(dot(N, H), 0.0);

    float a = rough * rough;
    float D = distributionGGX(NdotH, a);
    float G = geometrySmith(NdotV, NdotLs, rough);
    vec3  F = fresnelSchlick(max(dot(H, V), 0.0), F0);
    vec3 spec = (D * G * F) / max(4.0 * NdotV * NdotLs, 1e-5);
    vec3 kD = (vec3(1.0) - F) * (1.0 - metallic);

    vec3 outc = (kD * albedo / PI) * diff * radiance + spec * NdotL * radiance;

    if (cc > 0.01) {
        float ccR = 0.09;
        float ccD = distributionGGX(NdotH, ccR * ccR);
        float ccG = geometrySmith(NdotV, NdotLs, ccR);
        float ccF = 0.04 + 0.96 * pow(clamp(1.0 - max(dot(H, V), 0.0),
                                            0.0, 1.0), 5.0);
        outc += vec3(ccD * ccG * ccF / max(4.0 * NdotV * NdotLs, 1e-5))
                * NdotL * radiance * cc;
    }
    return outc;
}

// Trace the reflection ray onto the board plane and sample its albedo. Only
// valid for rays that actually hit the board, so the caller blends on hit.
bool boardHit(vec3 p, vec3 d, out vec3 col)
{
    float denom = dot(d, uBoardN);
    if (denom > -1e-4) return false;                 // going away from it
    float t = dot(uBoardC - p, uBoardN) / denom;
    if (t <= 0.0 || t > 60.0) return false;
    vec3 local = (p + d * t) - uBoardC;
    vec2 st = vec2(dot(local, uBoardT), dot(local, uBoardB))
              / (2.0 * uBoardHalf) + 0.5;
    if (any(lessThan(st, vec2(0.0))) || any(greaterThan(st, vec2(1.0))))
        return false;
    col = pow(texture(texture3, st).rgb, vec3(2.2));
    return true;
}

vec3 acesFilm(vec3 x)
{
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14),
                 0.0, 1.0);
}

void main()
{
    vec2 uv = fragTexCoord * uTexScale;

    vec3 albedo;
    float rough, ao, baked;
    if (uUseMaps > 0.5) {
        vec4 t4 = texture(texture0, uv);
        if (uAlphaCut > 0.5 && t4.a < 0.5) discard;  // punched holes
        vec3 t = t4.rgb;
        albedo = pow(t, vec3(2.2));                 // sRGB -> linear
        vec3 ral = texture(texture1, uv).rgb;
        rough = clamp(ral.r * uRoughness, 0.035, 1.0);
        ao = ral.g;                                 // ambient occlusion
        baked = ral.b;                              // baked cast shadow
    } else {
        albedo = pow(uAlbedo, vec3(2.2));
        rough = clamp(uRoughness, 0.035, 1.0);
        ao = 1.0;
        baked = 1.0;
    }
    albedo *= pow(colDiffuse.rgb, vec3(2.2));

    vec3 N = normalize(fragNormal);
    if (uUseNormalMap > 0.5) {
        vec3 nt = texture(texture2, uv).rgb * 2.0 - 1.0;
        N = normalize(cotangentFrame(N, fragPosition, uv) * nt);
    }

    vec3 V = normalize(viewPos - fragPosition);
    vec3 L = normalize(lightDir);
    vec3 R = reflect(-V, N);

    float NdotV = max(dot(N, V), 1e-4);
    vec3 F0 = mix(vec3(0.04), albedo, uMetallic);
    vec3 origin = fragPosition + N * 0.02;

    // Key: the sun. Also the light the wall shadows were baked against.
    float shadow = sphereShadow(origin, L, uShadowSphere, 5.0) * baked
                   * bodyShadow(fragPosition);
    vec3 direct = directLight(N, V, L, lightColor * shadow, albedo, rough,
                              F0, uMetallic, uWrap, uClearcoat);

    // Lamp: a positioned light, so its highlight travels with the ball.
    vec3 Lp = uPointPos - fragPosition;
    float pdist = max(length(Lp), 1e-3);
    Lp /= pdist;
    float atten = 1.0 / (1.0 + (pdist / uPointRange) * (pdist / uPointRange));
    float pshadow = sphereShadow(origin, Lp, uShadowSphere, 4.0);
    direct += directLight(N, V, Lp, uPointCol * atten * pshadow, albedo,
                          rough, F0, uMetallic, uWrap, uClearcoat);

    // Ambient: hemispheric diffuse plus an environment-sampled specular lobe.
    float hemi = N.y * 0.5 + 0.5;
    vec3 kDamb = (vec3(1.0) - fresnelSchlickRoughness(NdotV, F0, rough))
                 * (1.0 - uMetallic);
    vec3 ambDiff = mix(groundColor, skyColor, hemi) * albedo * kDamb * 0.55;
    vec3 env = envColor(R, rough);
    if (uPlanarRefl > 0.5) {
        vec3 hit;
        if (boardHit(fragPosition, R, hit)) {
            // Board reflections sit under the studio, dimmed and roughened.
            env = mix(env, hit * 1.15 + env * 0.25, 0.80);
        }
    }
    vec3 envSpec = env * fresnelSchlickRoughness(NdotV, F0, rough);
    vec3 ambient = (ambDiff + envSpec * mix(0.25, 1.0, uMetallic)) * ao;
    if (uClearcoat > 0.01) {
        ambient += envColor(R, 0.09)
                   * (0.04 + 0.30 * pow(1.0 - NdotV, 5.0)) * ao * uClearcoat;
    }

    // The ball occludes the sky as well as the sun. This is what plants it on
    // the board.
    ambient *= 1.0 - 0.92 * sphereOcclusion(fragPosition, N, uShadowSphere);

    vec3 color = direct + ambient;
    color = acesFilm(color * 0.95);
    finalColor = vec4(pow(color, vec3(1.0 / 2.2)), 1.0);
}
"""


class PBR:
    """Owns the shader and the per-draw uniform plumbing."""

    def __init__(self, light_dir, light_color, sky, ground):
        self.shader = rl.load_shader_from_memory(VS, FS)
        self.loc = {n: rl.get_shader_location(self.shader, n) for n in (
            "viewPos", "lightDir", "lightColor", "skyColor", "groundColor",
            "uMetallic", "uRoughness", "uUseMaps", "uUseNormalMap",
            "uAlbedo", "uShadowSphere", "uTexScale", "uAlphaCut",
            "uClearcoat", "uPlanarRefl", "uBoardC", "uBoardN", "uBoardT",
            "uBoardB", "uBoardHalf", "uWrap", "uPointPos", "uPointCol",
            "uPointRange", "uBodyShadow", "uBodyFwd", "uBodyHalfW")}
        self.shader.locs[rl.SHADER_LOC_VECTOR_VIEW] = self.loc["viewPos"]

        self._v3("lightDir", light_dir)
        self._v3("lightColor", light_color)
        self._v3("skyColor", sky)
        self._v3("groundColor", ground)
        self.set_shadow_sphere(0, 0, 0, -1)
        self.set_body_shadow(0, 0, 0, -1, (0, 0, 1), 1.0)

    # -- uniform helpers -----------------------------------------------------
    def _v3(self, name, v):
        rl.set_shader_value(self.shader, self.loc[name],
                            rl.ffi.new("float[3]", list(v)),
                            rl.SHADER_UNIFORM_VEC3)

    def _f(self, name, v):
        rl.set_shader_value(self.shader, self.loc[name],
                            rl.ffi.new("float[1]", [float(v)]),
                            rl.SHADER_UNIFORM_FLOAT)

    def set_view_pos(self, p):
        self._v3("viewPos", (p.x, p.y, p.z))

    def set_shadow_sphere(self, x, y, z, r):
        rl.set_shader_value(self.shader, self.loc["uShadowSphere"],
                            rl.ffi.new("float[4]", [x, y, z, r]),
                            rl.SHADER_UNIFORM_VEC4)

    def set_body_shadow(self, x, y, z, half_len, fwd, half_wid):
        rl.set_shader_value(self.shader, self.loc["uBodyShadow"],
                            rl.ffi.new("float[4]", [x, y, z, half_len]),
                            rl.SHADER_UNIFORM_VEC4)
        self._v3("uBodyFwd", (fwd[0], 0.0, fwd[1] if len(fwd) == 2 else fwd[2]))
        self._f("uBodyHalfW", half_wid)

    def set_point_light(self, pos, colour, rng):
        self._v3("uPointPos", pos)
        self._v3("uPointCol", colour)
        self._f("uPointRange", rng)

    def set_board_plane(self, centre, normal, tangent, bitangent, half):
        self._v3("uBoardC", centre)
        self._v3("uBoardN", normal)
        self._v3("uBoardT", tangent)
        self._v3("uBoardB", bitangent)
        self._f("uBoardHalf", half)

    def material(self, metallic=0.0, roughness=0.5, albedo=(1, 1, 1),
                 use_maps=False, normal_map=False, tex_scale=1.0,
                 alpha_cut=False, clearcoat=0.0, planar=False, wrap=0.0):
        """Set the material state for the draws that follow."""
        self._f("uWrap", wrap)
        self._f("uMetallic", metallic)
        self._f("uRoughness", roughness)
        self._f("uUseMaps", 1.0 if use_maps else 0.0)
        self._f("uUseNormalMap", 1.0 if normal_map else 0.0)
        self._f("uTexScale", tex_scale)
        self._f("uAlphaCut", 1.0 if alpha_cut else 0.0)
        self._f("uClearcoat", clearcoat)
        self._f("uPlanarRefl", 1.0 if planar else 0.0)
        self._v3("uAlbedo", albedo)

    def attach(self, model, albedo_tex=None, mra_tex=None, normal_tex=None,
               board_tex=None):
        model.materials[0].shader = self.shader
        if albedo_tex is not None:
            rl.set_material_texture(model.materials[0],
                                    rl.MATERIAL_MAP_DIFFUSE, albedo_tex)
        if mra_tex is not None:
            rl.set_material_texture(model.materials[0],
                                    rl.MATERIAL_MAP_SPECULAR, mra_tex)
        if normal_tex is not None:
            rl.set_material_texture(model.materials[0],
                                    rl.MATERIAL_MAP_NORMAL, normal_tex)
        if board_tex is not None:
            # texture3 in the shader - what the ball reflects.
            rl.set_material_texture(model.materials[0],
                                    rl.MATERIAL_MAP_ROUGHNESS, board_tex)
        return model
