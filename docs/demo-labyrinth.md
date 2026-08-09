# Demo: tilt labyrinth

A worked example of the joystick driving something real. Not central to the repo - the interface is the point - but it exercises the whole chain, and it is the thing worth handing someone.

One demo, done properly. The wooden ball-in-a-maze toy: the stick tilts the
board and gravity does the rest. It needs no explanation to anyone who has ever
held one, which makes it the right thing to hand someone cold.

```powershell
.\rnet.cmd demo labyrinth                          # fullscreen
.\rnet.cmd demo labyrinth --level 6 --timer        # start on 6, clock running
```

| Key | |
|---|---|
| `1`–`8` | jump straight to a level |
| `[` `]` | previous / next level |
| `T` | timer on/off |
| `R` | restart the level |
| `H` | text HUD on/off |
| `Esc` | quit |

The level bar top-right is clickable, as is the timer toggle under it. A red dot
marks the levels that have holes, so the difficulty ramp is visible at a glance.
Navigation stays on screen when `H` hides the HUD — it is how you move around,
not decoration.

## Levels

Eight levels in `levels.py`. **The first four have no holes at all.** Metering a
tilt is already the hard part, and resetting someone before they have the feel
for it only teaches them the game is unfair — so difficulty comes from geometry
first (a single wall, a switchback, a pen, a staircase), and holes arrive small,
few, and well clear of the line before growing. Reach the green cup to advance.

## Timer and best times

Off by default; `--timer` or `T`. The clock **starts on the first real stick
input rather than on level load**, so the transition banner and a moment to read
the board are free. Falling in a hole resets the ball but *not* the clock — the
time already spent is the penalty.

Best times are per level, written to `tools/demos/scores.json` and keyed by
level *name* rather than index, so reordering or inserting a level doesn't
silently reassign someone's records to the wrong course. Beating one shows
`NEW BEST` on the transition banner.

**Runs without the joystick** — arrow keys or WASD — so it can be shown on any
machine. `--keyboard` forces that even when the rig is attached.

Flags: `--windowed`, `--no-hud`, `--deadzone`, `--expo`, `--port`,
`--fast-textures` (512px maps, ~1.7 s quicker to start), and
`--screenshot PATH --frames N` to render a PNG and exit.

## Rendering

`pbr.py` is a small physically-based renderer: Cook-Torrance GGX, normal mapping
derived from screen-space derivatives (so no mesh tangents are needed),
hemispheric ambient, ACES tonemapping and correct sRGB handling.

- **Procedural beech** (`texgen.py`, numpy + scipy): growth rings from a warped
  radial coordinate with the centre pushed off-canvas, so the board shows the
  long shallow arcs of flat-sawn stock rather than bullseyes, with ring
  *spacing* varying because no tree grows evenly year to year. Fibre stretched
  along the grain, sparse open pores, and ray fleck — the pale lenticular marks
  running across the grain that read as real timber rather than a wood-coloured
  gradient. Roughness is mottled rather than constant; an even sheen is one of
  the strongest CG tells. No image assets ship with the project.
- **Real holes.** The surface is genuinely punched — hole cutouts live in the
  albedo's alpha channel and the shader discards them — backed by a hand-built
  tube mesh with inward-facing normals, a chamfered lip, and a floor panel below.
  A cylinder under a solid plane just reads as a painted black disc, which is
  exactly what the first version looked like.
- **Baked wall shadows and contact AO.** The walls never move relative to the
  board, so their shadows are computed once by shifting the wall footprint along
  the light direction and blurring. On a planar receiver that is exact, not an
  approximation — no shadow map required. Only this layer is recomputed on a
  level change; the wood underneath is cached.
- **Marble ball**: procedural white marble — the classic turbulent-sine
  construction, where an fbm-displaced sine field's zero crossings become veins,
  cut deliberately coarse because the ball is only ~55 px on screen and fine
  veining just averages to grey. Dielectric with a clearcoat sheen and a wrapped
  diffuse term so light bleeds past the terminator the way stone does. It also
  **rolls** — worth doing now the surface has texture; on chrome the spin was
  literally invisible.
- **Two lights.** A directional key *behind* the board and lower than you would
  expect, plus a positioned lamp on the camera side. Both choices are about
  shadows and highlights being visible rather than correct in the abstract —
  see below.
- **Planar reflection**: the board is ray-traced against its own plane in the
  fragment shader and sampled from its albedo, so the polished marble picks up
  a faint image of what it is sitting on.
- **Clearcoat**: a second, much sharper specular lobe over the wood, which is
  what makes varnished timber look varnished rather than raw.
- **Ball shadow**: analytic ray-sphere soft shadow *and* analytic sphere ambient
  occlusion (both Quilez). Blocking direct light is only half a contact shadow —
  without occluding the ambient too, the ball hovers no matter how good the cast
  shadow is.
- **Physics**: the ball rolls rather than slides, so it accelerates at
  5/7 g sin θ — a solid sphere puts two sevenths of its energy into spin.

## Lessons, each of which cost a debugging round

1. **A near-overhead key light makes a shadow you cannot see.** At ~53°
   elevation the ball's shadow was short and tucked directly behind it from this
   camera. Moving the key *behind* the board and lowering it throws the shadow
   toward the viewer. Physically fine either way; only one of them reads.
2. **With every light behind the board, every face you can see goes black.**
   Hence the lamp on the camera side. Lighting has to be composed for the
   camera, not just placed plausibly.
3. **A directional light pins a highlight to the same spot on a sphere
   forever**, however the sphere moves. Only a *positioned* light gives a
   highlight that travels — that was most of why the metal ball looked dead.
4. **AO belongs on ambient, cast shadows belong on direct light.** Folding baked
   wall shadows into the AO channel made them invisible.
5. **`F0 + F*0.5` on the ambient term is an energy gain**, and it makes a
   surface uniformly pale no matter how dark the environment. Use a
   roughness-aware Fresnel for IBL.
6. **Hand-built meshes are easy to wind backwards**, and a back-facing well
   floor is indistinguishable from a bug in the material. The wells draw with
   backface culling off.
7. **Normal-map strength is per-texel**, so a scale factor that reads as
   reasonable turns wood into tree bark.

A note on the analytic environment: it survives from the chrome version and
still drives reflections and the studio softboxes, but with a dielectric ball it
matters far less. A mirror reflecting a smooth gradient reads as pearl rather
than chrome — the fix there was contrast between small hot sources and a dark
surround, which is why the softboxes have hard edges.

Screenshots of levels 1, 3, 6 and 8 are in `shots/`.

Requires `pyserial`, `pygame` (for `crosshair.py`), `raylib`, `numpy`, `scipy`:

```powershell
python -m pip install pyserial pygame raylib numpy scipy
```

---

[← Back to the README](../README.md)
