# Button-Free Games for a 2-Axis Analog Joystick

**Design frame:** accessibility. One spring-loaded analog stick, no buttons. The stick gives **angle + magnitude (polar input)** and, because it's spring-loaded, a clean **return-to-center event**. That snap-back is the closest thing to a real button we get, so the whole design language is built around it.

**The one primitive everything leans on:** *flick-and-release*: push out, let it snap back. It has a crisp onset and offset, it's physically self-limiting, and it's self-teaching (the hand learns the boundary without a tutorial).

---

## Part 1: straightforward to implement

Existing games (or thin variants) that map cleanly onto the stick with little or no mechanic invention. Roughly ordered easiest-first.

### Tier A: already button-free by nature

| Game | Input mapping | Why it's easy |
|---|---|---|
| **Snake / Slither.io** | Stick sets heading; motion is automatic | The canonical steer-only game. Boost/split are optional and can be dropped. |
| **Pong / Breakout** | Paddle on one axis (ignore the second) | Trivial mapping; magnitude can add paddle speed if wanted. |
| **Marble / tilt (Monkey Ball, Marble Madness, labyrinth)** | Stick tilt → gravity direction | Gravity supplies the "action"; you only supply tilt. |
| **flOw / Flower** | Steer; magnitude = speed | Built to feel expressive with no discrete input. Good reference for *feel*. |
| **Super Hexagon** | Rotate L / rotate R | Proof that minimal input ≠ shallow. High skill ceiling from almost nothing. |
| **Pure-dodge bullet-hell** | Move only; no shooting | Removing the gun turns the whole game into movement. |

### Tier B: one small synthesis needed

| Game | Input mapping | The one adaptation |
|---|---|---|
| **Tetris** | Move = stick L/R; soft/hard drop = down; **rotate = flick** | Rotate is the only discrete verb, so bind it to flick-up (or a quick rim gesture). The rest is continuous. |
| **Breakout+ / Arkanoid** | Paddle on X; **launch = flick** | Only the ball-launch and power-ups need an event. |
| **WipEout / Race the Sun** | Steer + magnitude = throttle | Auto-forward racers; steering is the game. Weapons (if any) go auto-fire. |
| **Geometry Wars / Robotron** | Move on stick; **auto-fire in direction of travel** | Collapses twin-stick to one stick by firing where you move. |
| **Angry Birds** | Aim = angle, power = magnitude, **fire = release** | The slingshot *is* flick-and-release. Feels designed for the stick. |
| **Worms / artillery / golf / pool** | Angle + power in one gesture, snap-back fires | Whole "aim + power + commit" genre fits the spring return natively. |

**Implementation note for Tier B:** the only real work is the button-synthesis layer. In priority order: **flick-and-release** (best, with a real onset and offset) → **magnitude threshold** (hard push = act, soft = move) → **dwell-in-direction** (hold a heading N ms) → **rim/rotation gesture** (reload, cycle, confirm) → **center-hold as an explicit state** (cancel / safe / commit-release).

---

## Part 2: proposed original dynamics

These lean into the stick instead of adapting to it. The richest vein: **the input transforms the space and an automatic process resolves the result**, as in the echochrome / Katamari / Fez family, where there's no "do the thing" button because *the thing does itself*.

### 2.1 Recoil-blob
Flick launches a chunk of your mass in that direction; you shrink and get shoved the opposite way; the ejected mass persists and interacts with the world. (Osmos × slingshot × Angry Birds.)

**Pros**
- Fuses flick-release + magnitude-as-spend + physical recoil into a single, legible verb.
- Every input is a real decision (mass is a resource), so it naturally resists button-mashing.
- Pulls toward slow, tense pacing, which suits accessibility.

**Cons / risks**
- **False-activation is expensive.** A stray flick doesn't just misfire, it costs mass. *Mitigation:* require a genuine out-and-back (cross ~85% radius **and** return through center within a short window); reject drifts and leans.
- **Fatigue.** Repeated full-radius flicks tire the hand. *Mitigation:* keep the loop low-frequency (design density so a skilled player flicks every few seconds, not constantly); make the neutral state productive (rest near center regenerates mass / lets you observe) so **rest is a move**, not downtime.
- **Magnitude legibility.** Players can't reliably feel 60% vs 80% on a spring stick under pressure. *Mitigation:* **quantize into 2–3 bands** (tap / medium / hard) with distinct recoil kick, sound, and chunk size per band. Reserve true analog subtlety for low-stakes steering.

**Through-line:** *make the expensive gesture rare, legible and self-limiting, and make rest a move.*

### 2.2 Gravity-flip
Flick reorients gravity 90° in the flicked direction; the whole world re-falls. A four-directional VVVVVV: echochrome's "reframe the space" made kinetic.

**Pros**
- **Magnitude is irrelevant.** The flick only picks a quadrant, so legibility is a non-issue (the hardest constraint from 2.1 just disappears).
- Flicks are cheap and frequent, so false-activation is far less punishing.
- Deep puzzle/timing space from a single trivial verb.

**Cons / risks**
- Fatigue shifts from *force* to *rhythm*. Rapid repeated flips can still tire and can induce error under time pressure. *Mitigation:* puzzle-pacing over twitch-pacing; allow a beat between meaningful flips.
- Disorientation. Re-framing the world repeatedly can be visually taxing. *Mitigation:* smooth (not instant) reorientation, persistent up-indicator, generous camera.

### 2.3 Space-transformers (echochrome / Fez / Monument Valley family)
Flick rotates or reconfigures the world in snaps; an auto-walking figure resolves the path. The verb is "reframe," never "act."

**Pros**
- Button-free by design rather than by adaptation.
- Flick-to-rotate-90° is a perfect match for snap-based world rotation.
- Contemplative pacing suits accessibility; no reflex demands.

**Cons / risks**
- Design-heavy: the *content* (levels, illusions) is the expensive part, not the input.
- Discoverability. Players need to learn that they shape conditions rather than move an avatar. *Mitigation:* early levels that teach "you rotate, it walks."

### 2.4 Pen-with-momentum (weaving / trajectory)
Flicks lay down persistent lines/paths (Flight Control × Crayon Physics); past flicks stay on the board and shape what the automatic elements do next.

**Pros**
- The stick becomes an expressive tool, not just a controller.
- Emergent difficulty from your own accumulated marks, giving high replay value from simple rules.

**Cons / risks**
- Board can get cluttered/unreadable. *Mitigation:* line decay, or a cap on active strokes.
- Precision of placement vs. the coarseness of flick aiming. *Mitigation:* snap-to-grid or magnetized anchor points.

---

## Quick recommendation

- **Fastest to a playable prototype:** Snake variant or Tetris-with-flick-rotate (Part 1), which validates the flick-synthesis layer with almost no new design.
- **Most original but low-risk on input:** Gravity-flip (2.2), which sidesteps the magnitude-legibility problem entirely.
- **Most distinctive / highest ceiling:** Recoil-blob (2.1). Best payoff, but only if the three mitigations above are respected.

## Cross-cutting accessibility checklist
- [ ] Flick gesture is self-limiting (out-and-back required) to prevent false activation.
- [ ] Rest / center is a legitimate strategic state, not punished downtime.
- [ ] Any life-or-death dependence on fine magnitude is quantized into legible bands.
- [ ] Core loop frequency is tuned to hand fatigue, not to genre convention.
- [ ] Dwell times (if used) shrink as confidence rises; tune against false-activation vs. fatigue.
