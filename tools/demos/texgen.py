"""Procedural texture generation for the labyrinth board.

Everything is numpy, uploaded straight into raylib textures - no image assets.

The expensive part (the wood itself) is cached, because only the level geometry
changes between levels. Baking wall shadows, hole cutouts and contact occlusion
on top of a cached base costs a few hundred milliseconds instead of seconds.
"""

import numpy as np
import pyray as rl
from scipy import ndimage


# ------------------------------------------------------------- upload -------

def texture_from_rgba(arr):
    """HxWx4 uint8 -> Texture2D, mipmapped and trilinear filtered."""
    h, w, _ = arr.shape
    img = rl.gen_image_color(w, h, rl.BLANK)
    buf = np.ascontiguousarray(arr, dtype=np.uint8).tobytes()
    rl.ffi.memmove(img.data, buf, len(buf))
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.gen_texture_mipmaps(tex)
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    return tex


def _pack(r, g, b, a=None):
    chans = [np.clip(c, 0.0, 1.0) for c in (r, g, b)]
    chans.append(np.ones_like(chans[0]) if a is None else np.clip(a, 0.0, 1.0))
    return (np.stack(chans, axis=-1) * 255.0 + 0.5).astype(np.uint8)


# -------------------------------------------------------------- noise -------

def value_noise(size, freq, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((freq + 1, freq + 1))
    return ndimage.zoom(g, size / (freq + 1), order=3,
                        mode="grid-wrap")[:size, :size]


def fbm(size, base_freq, octaves, seed, gain=0.5, lacunarity=2.0):
    total = np.zeros((size, size))
    amp, freq, norm = 1.0, base_freq, 0.0
    for i in range(octaves):
        total += value_noise(size, max(2, int(freq)), seed + i * 101) * amp
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def _norm01(a):
    return (a - a.min()) / (np.ptp(a) + 1e-9)


# --------------------------------------------------------------- wood -------

_BASE_CACHE = {}


def wood_base(size=1024, seed=3):
    """Beech-like flat-sawn board: rings, fibre, pores, ray fleck.

    Cached - the wood is identical from level to level, only the geometry
    baked on top of it changes.
    """
    key = (size, seed)
    if key in _BASE_CACHE:
        return _BASE_CACHE[key]

    y, x = np.mgrid[0:size, 0:size].astype(np.float64) / size

    # Growth rings. The centre sits well off-canvas so the board shows the long
    # shallow arcs of flat-sawn stock rather than concentric bullseyes, and the
    # ring *spacing* varies because no tree grows evenly year to year.
    warp = fbm(size, 5, 3, seed) - 0.5
    r = np.hypot((x + 0.58) * 0.28, (y - 1.62)) + warp * 0.011
    spacing = 1.0 + 0.14 * (fbm(size, 3, 2, seed + 5) - 0.5)
    phase = r * 44.0 * spacing * 2.0 * np.pi

    ring = np.sin(phase)
    # Latewood is a narrow hard dark band; earlywood is the wide pale part.
    latewood = np.clip(ring, 0.0, 1.0) ** 3.0

    # Fibre: fine, very stretched along the grain, mostly a colour effect.
    fibre = ndimage.gaussian_filter(fbm(size, 150, 2, seed + 41),
                                    sigma=(0.30, 13.0))
    fibre = _norm01(fibre)

    # Open pores: short dark ticks following the grain.
    pore_n = ndimage.gaussian_filter(fbm(size, 240, 1, seed + 77),
                                     sigma=(0.4, 3.2))
    pores = np.clip((pore_n - 0.79) * 8.0, 0.0, 1.0)

    # Ray fleck: pale lenticular marks running *across* the grain. This is the
    # detail that reads as real timber rather than a wood-coloured gradient.
    fleck_n = ndimage.gaussian_filter(fbm(size, 170, 1, seed + 131),
                                      sigma=(11.0, 0.5))
    fleck = np.clip((_norm01(fleck_n) - 0.80) * 5.0, 0.0, 1.0)

    figure = fbm(size, 7, 3, seed + 9)
    tone = np.clip(0.56 * latewood + 0.32 * fibre + 0.12 * figure, 0.0, 1.0)

    pale = np.array([0.816, 0.678, 0.512])      # earlywood, beech
    deep = np.array([0.404, 0.302, 0.212])      # latewood, kept neutral
    albedo = (pale[None, None, :] * (1.0 - tone[..., None])
              + deep[None, None, :] * tone[..., None])
    albedo *= (1.0 - 0.22 * pores)[..., None]
    albedo += (0.042 * fleck)[..., None]

    # Relief: pores are pits, latewood stands a hair proud, rays are flush.
    height = latewood * 0.13 + fibre * 0.07 - pores * 0.30
    height = ndimage.gaussian_filter(height, 0.9)

    # Roughness. The mottling matters more than the average: a constant
    # roughness gives a flat, even sheen that instantly reads as CG.
    mottle = ndimage.gaussian_filter(fbm(size, 26, 3, seed + 211), 1.5)
    scratches = ndimage.gaussian_filter(fbm(size, 300, 1, seed + 313),
                                        sigma=(0.35, 22.0))
    rough = (0.34
             - 0.07 * latewood
             + 0.26 * pores
             + 0.10 * (mottle - 0.5)
             + 0.05 * (_norm01(scratches) - 0.5))
    rough = np.clip(rough, 0.10, 0.92)

    out = dict(albedo=albedo, height=height, rough=rough,
               latewood=latewood, pores=pores, fleck=fleck)
    _BASE_CACHE[key] = out
    return out


def normal_from_height(height, strength=1.0):
    # The gradient is per-texel, so the scale factor has to stay small or the
    # surface turns into bark.
    gy, gx = np.gradient(height.astype(np.float64))
    nx, ny, nz = -gx * strength * 6.0, -gy * strength * 6.0, np.ones_like(gx)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + nz * nz)
    return _pack(nx * inv * 0.5 + 0.5, ny * inv * 0.5 + 0.5, nz * inv * 0.5 + 0.5)


# ------------------------------------------- board: shadows and occlusion ---

def board_maps(size, half_extent, walls, holes, hole_r, goal, goal_r,
               light_dir, wall_h, seed=3):
    """Wood maps for the play surface.

    Alpha carries the hole cutouts - the shader discards below 0.5, so the
    surface is genuinely punched and you can see down the wells.
    """
    base = wood_base(size, seed)
    albedo = base["albedo"].copy()

    lin = (np.arange(size) + 0.5) / size * (2 * half_extent) - half_extent
    bz, bx = np.meshgrid(lin, lin, indexing="ij")

    wall_mask = np.zeros((size, size), dtype=bool)
    for cx, cz, hw, hd in walls:
        wall_mask |= ((np.abs(bx - cx) <= hw) & (np.abs(bz - cz) <= hd))

    px_per_unit = size / (2 * half_extent)

    # Hard shadow = wall footprint pushed along the light's ground direction.
    lx, ly, lz = light_dir
    off_x = -(lx / max(ly, 1e-3)) * wall_h * px_per_unit
    off_z = -(lz / max(ly, 1e-3)) * wall_h * px_per_unit
    shadow = ndimage.shift(wall_mask.astype(np.float64), (off_z, off_x),
                           order=1, mode="constant", cval=0.0)
    shadow = ndimage.gaussian_filter(shadow, size / 230.0)
    shadow = np.clip(shadow, 0.0, 1.0) * 0.62

    # Contact occlusion where the surface meets a wall.
    dist = ndimage.distance_transform_edt(~wall_mask) / px_per_unit
    ao = np.clip(dist / 1.2, 0.0, 1.0) ** 0.65
    ao = 0.28 + 0.72 * ao

    # Holes: cut the surface, wear a bright chamfer, darken just inside it.
    cut = np.ones((size, size))
    rim = np.zeros((size, size))
    near = np.ones((size, size))
    all_holes = [(h[0], h[1], hole_r) for h in holes] + \
                [(goal[0], goal[1], goal_r)]
    for hx, hz, hr in all_holes:
        d = np.hypot(bx - hx, bz - hz)
        cut = np.minimum(cut, np.clip((d - hr) * px_per_unit * 0.9 + 0.5,
                                      0.0, 1.0))
        rim = np.maximum(rim, np.clip(1.0 - np.abs(d - hr - 0.10) * 9.0, 0, 1))
        near = np.minimum(near, np.clip((d - hr) * 1.5, 0.35, 1.0))

    occl = np.clip(ao * near, 0.0, 1.0)
    lit = np.clip(1.0 - shadow, 0.0, 1.0)

    # Polished, slightly paler chamfer where thousands of balls have passed.
    albedo *= (1.0 + 0.20 * rim)[..., None]
    rough = np.clip(base["rough"] - 0.16 * rim, 0.06, 0.95)
    height = base["height"] + rim * 0.10
    height = ndimage.gaussian_filter(height, 0.6)

    return (_pack(albedo[..., 0], albedo[..., 1], albedo[..., 2], cut),
            normal_from_height(height),
            _pack(rough, occl, lit))


def wall_maps(size=512, seed=11):
    """Straight-grained stock for the walls - no ring arcs to get squashed."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float64) / size
    fibre = _norm01(ndimage.gaussian_filter(fbm(size, 80, 4, seed),
                                            sigma=(0.5, 16.0)))
    streak = 0.5 + 0.5 * np.sin(y * 52.0 + fibre * 5.0)
    tone = np.clip(0.60 * fibre + 0.40 * streak, 0.0, 1.0)

    pale = np.array([0.836, 0.699, 0.516])
    deep = np.array([0.522, 0.365, 0.224])
    albedo = (pale[None, None, :] * (1.0 - tone[..., None])
              + deep[None, None, :] * tone[..., None])

    mottle = ndimage.gaussian_filter(fbm(size, 22, 3, seed + 5), 1.5)
    rough = np.clip(0.34 + 0.14 * tone + 0.10 * (mottle - 0.5), 0.10, 0.92)
    height = ndimage.gaussian_filter(tone, 1.2) * 0.16
    ao = np.ones_like(tone)
    return (_pack(albedo[..., 0], albedo[..., 1], albedo[..., 2]),
            normal_from_height(height, strength=0.7),
            _pack(rough, ao, ao))


def marble_maps(size=768, seed=17):
    """Polished white marble with veining, for the ball.

    The classic turbulent-sine construction: displace a sine field by fbm and
    the zero crossings become veins. Horizontal frequencies are whole numbers
    so the pattern meets itself where the sphere's UVs wrap.
    """
    y, x = np.mgrid[0:size, 0:size].astype(np.float64) / size

    turb = fbm(size, 6, 5, seed) - 0.5
    turb2 = fbm(size, 15, 4, seed + 7) - 0.5

    # Coarse on purpose: the ball is only ~55px on screen, so fine veining
    # just averages out to grey.
    v = np.sin((x * 2.0 + y * 0.8 + turb * 2.6 + turb2 * 0.8) * 2.0 * np.pi)
    vein = np.clip(1.0 - np.abs(v) * 2.1, 0.0, 1.0) ** 1.4

    v2 = np.sin((x * 5.0 - y * 2.0 + turb * 4.4) * 2.0 * np.pi)
    hairline = np.clip(1.0 - np.abs(v2) * 5.5, 0.0, 1.0) ** 2.0 * 0.55

    cloud = fbm(size, 4, 3, seed + 21)
    t = np.clip(vein + hairline * 0.65, 0.0, 1.0)

    base = np.array([0.858, 0.845, 0.820])       # warm white
    dark = np.array([0.212, 0.212, 0.244])       # cool grey vein
    albedo = (base[None, None, :] * (1.0 - t[..., None])
              + dark[None, None, :] * t[..., None])
    albedo *= (0.90 + 0.16 * cloud)[..., None]

    # Veins are slightly softer than the polished ground surface, and the
    # variation is what keeps the highlight from looking like plastic.
    rough = np.clip(0.13 + 0.20 * t + 0.06 * (cloud - 0.5), 0.06, 0.62)
    height = -vein * 0.05 + 0.02 * (cloud - 0.5)
    height = ndimage.gaussian_filter(height, 1.0)
    ao = np.ones_like(t)
    return (_pack(albedo[..., 0], albedo[..., 1], albedo[..., 2]),
            normal_from_height(height, strength=0.35),
            _pack(rough, ao, ao))


def well_maps(size=256, seed=23):
    """End-grain-ish stock for the inside of a drilled hole."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float64) / size
    rings = _norm01(ndimage.gaussian_filter(fbm(size, 40, 3, seed),
                                            sigma=(6.0, 0.6)))
    tone = np.clip(0.7 * rings + 0.3 * fbm(size, 12, 2, seed + 3), 0.0, 1.0)
    pale = np.array([0.402, 0.300, 0.206])
    deep = np.array([0.150, 0.104, 0.070])
    albedo = (pale[None, None, :] * (1.0 - tone[..., None])
              + deep[None, None, :] * tone[..., None])
    # Darken with depth: v runs 0 at the rim to 1 at the bottom.
    albedo *= (1.0 - 0.72 * y)[..., None]
    rough = np.clip(0.62 + 0.16 * tone, 0.2, 0.98)
    ao = np.clip(1.0 - 0.85 * y, 0.05, 1.0)
    height = ndimage.gaussian_filter(tone, 1.0) * 0.10
    return (_pack(albedo[..., 0], albedo[..., 1], albedo[..., 2]),
            normal_from_height(height, strength=0.5),
            _pack(rough, ao, ao))
