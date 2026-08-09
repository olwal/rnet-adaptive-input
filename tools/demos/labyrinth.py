"""Tilt labyrinth - the wooden ball-in-a-maze toy.

Stick tilts the board, gravity does the rest. Reach the green cup to advance.

The first four levels have no holes: metering a tilt is hard enough on its own,
and resetting someone before they have the feel for it only teaches them the
game is unfair. Difficulty comes from geometry first, then small holes.

Rendered with the PBR path in pbr.py - procedural beech, a punched surface with
lined wells, a polished steel ball reflecting both an analytic studio and the
board itself, and baked wall shadows.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyray as rl
from engine import Demo, base_parser
from pbr import PBR
import levels
import meshbuild
import scores
import texgen

HALF = levels.BOARD_HALF
BOARD_T = 1.1
BALL_R = 0.95
WALL_H = 1.45
WELL_D = 1.5                 # how deep a hole looks
GOAL_D = 0.62                # the goal is a shallow cup, not a pit
MAX_TILT = math.radians(12.5)
G = 26.0
ROLL = 5.0 / 7.0             # solid sphere rolling without slipping

# Key light sits behind the board and lower than you would expect. Overhead
# light makes a short shadow that hides behind the ball from this camera; from
# behind, the shadow is longer and falls toward the viewer where it can be seen.
LIGHT_DIR = (0.36, 0.64, -0.68)
LIGHT_COL = (2.7, 2.55, 2.30)
# The lamp sits on the camera side as fill - with both lights behind, every
# face you can actually see goes black. Its own shadow falls away from the
# camera, so the key light's shadow stays the one you read. Being a *position*
# rather than a direction is the point: the vector to it swings as the ball
# travels, so its highlight slides across the surface.
LAMP_POS = (11.0, 18.0, 17.0)
LAMP_COL = (3.4, 3.05, 2.50)
LAMP_RANGE = 30.0
SKY = (0.225, 0.265, 0.355)
GROUND = (0.072, 0.052, 0.034)

LIP = [(0, -HALF, HALF + 0.6, 0.6), (0, HALF, HALF + 0.6, 0.6),
       (-HALF, 0, 0.6, HALF), (HALF, 0, 0.6, HALF)]


class Labyrinth(Demo):
    title = "tilt labyrinth"
    help_text = ("stick tilts the board   1-8 / [ ] level   T timer   "
                 "R restart   H hud   Esc quit")
    sky_top = rl.Color(15, 17, 24, 255)
    sky_bottom = rl.Color(41, 47, 60, 255)
    haze_strength = 0

    # -- setup ---------------------------------------------------------------
    def setup(self):
        self.pbr = PBR(LIGHT_DIR, LIGHT_COL, SKY, GROUND)
        self.pbr.set_point_light(LAMP_POS, LAMP_COL, LAMP_RANGE)
        self.res = 512 if self.args.fast_textures else 1024

        w_alb, w_nrm, w_mra = texgen.wall_maps(512)
        self.wall_tex = (texgen.texture_from_rgba(w_alb),
                         texgen.texture_from_rgba(w_nrm),
                         texgen.texture_from_rgba(w_mra))
        k_alb, k_nrm, k_mra = texgen.well_maps(256)
        self.well_tex = (texgen.texture_from_rgba(k_alb),
                         texgen.texture_from_rgba(k_nrm),
                         texgen.texture_from_rgba(k_mra))
        m_alb, m_nrm, m_mra = texgen.marble_maps(768)
        self.marble_tex = (texgen.texture_from_rgba(m_alb),
                           texgen.texture_from_rgba(m_nrm),
                           texgen.texture_from_rgba(m_mra))

        # Enough subdivision that the punched edges get proper interpolation.
        self.surface_mesh = meshbuild.plane(HALF * 2, 24)
        self.surface = rl.load_model_from_mesh(self.surface_mesh)
        self.wall = self.pbr.attach(
            rl.load_model_from_mesh(rl.gen_mesh_cube(1, 1, 1)),
            self.wall_tex[0], self.wall_tex[2], self.wall_tex[1])
        self.ball = self.pbr.attach(
            rl.load_model_from_mesh(rl.gen_mesh_sphere(BALL_R, 64, 64)),
            self.marble_tex[0], self.marble_tex[2], self.marble_tex[1])
        self.ball_rot = rl.matrix_identity()
        self.floor = self.pbr.attach(
            rl.load_model_from_mesh(rl.gen_mesh_cube(HALF * 2, 0.5, HALF * 2)))
        self.frame = self.pbr.attach(
            rl.load_model_from_mesh(rl.gen_mesh_cube(1, 1, 1)),
            self.wall_tex[0], self.wall_tex[2], self.wall_tex[1])

        self.board_tex = None
        self.wells = {}
        self.level_index = 0
        self.total_falls = 0

        self.timer_on = self.args.timer
        self.scores = scores.load()
        self.elapsed = 0.0
        self.timing = False
        self.last_time = None
        self.last_was_best = False

        self.load_level(max(0, self.args.level - 1))

        self.camera.position = rl.Vector3(0, 24.5, 22.0)
        self.camera.target = rl.Vector3(0, -1.6, 0.0)
        self.camera.fovy = 42

    def _well_meshes(self, r, depth=WELL_D):
        """Tube + chamfer + floor per hole radius, built once and reused."""
        key = (round(r, 3), round(depth, 3))
        if key not in self.wells:
            self.wells[key] = (
                self.pbr.attach(rl.load_model_from_mesh(
                    meshbuild.tube(r, depth, 44)),
                    self.well_tex[0], self.well_tex[2], self.well_tex[1]),
                self.pbr.attach(rl.load_model_from_mesh(
                    meshbuild.ring(r, r + 0.13, 44, 0.0, 0.09)),
                    self.wall_tex[0], self.wall_tex[2], self.wall_tex[1]),
                self.pbr.attach(rl.load_model_from_mesh(
                    meshbuild.disc(r * 0.99, 44))),
            )
        return self.wells[key]

    def load_level(self, index):
        self.level_index = max(0, min(len(levels.LEVELS) - 1, index))
        lv = levels.get(self.level_index)
        self.level = lv
        self.hole_r = lv["hole_r"]
        self.goal_r = lv["hole_r"] * 1.25

        if self.board_tex:
            for t in self.board_tex:
                rl.unload_texture(t)
        alb, nrm, mra = texgen.board_maps(
            self.res, HALF, lv["walls"] + LIP, lv["holes"], self.hole_r,
            lv["goal"], self.goal_r, LIGHT_DIR, WALL_H)
        self.board_tex = (texgen.texture_from_rgba(alb),
                          texgen.texture_from_rgba(nrm),
                          texgen.texture_from_rgba(mra))
        self.pbr.attach(self.surface, self.board_tex[0], self.board_tex[2],
                        self.board_tex[1])
        # The ball reflects the board, so it needs the same albedo bound.
        self.pbr.attach(self.ball, board_tex=self.board_tex[0])
        self._well_meshes(self.hole_r)
        self._well_meshes(self.goal_r, GOAL_D)
        self.reset()

    def reset(self, keep_clock=False):
        self.bx, self.bz = self.level["start"]
        self.vx = self.vz = 0.0
        self.tilt_x = self.tilt_z = 0.0
        self.drop = 0.0
        self.dropping = None
        self.flash = 0.0
        self.flash_col = (240, 90, 70)
        self.banner = ""
        self.banner_t = 0.0
        if not keep_clock:
            self.elapsed = 0.0
            self.timing = False

    def jump(self, index):
        index = max(0, min(len(levels.LEVELS) - 1, index))
        if index == self.level_index:
            self.reset()
        else:
            self.load_level(index)
            self.banner = self.level["name"]
            self.banner_t = 1.8

    # -- simulation ----------------------------------------------------------
    def update(self, dt, sx, sy):
        self.flash = max(0.0, self.flash - dt * 1.6)
        self.banner_t = max(0.0, self.banner_t - dt)
        self._handle_ui()

        self.tilt_x += (sx * MAX_TILT - self.tilt_x) * min(1.0, 10.0 * dt)
        self.tilt_z += (sy * MAX_TILT - self.tilt_z) * min(1.0, 10.0 * dt)

        # The clock starts on the first real input, not on level load, so the
        # transition banner and a moment to look at the board are free.
        if self.timer_on and self.dropping is None:
            if not self.timing and max(abs(sx), abs(sy)) > 0.12:
                self.timing = True
            if self.timing:
                self.elapsed += dt

        if self.dropping is not None:
            self.drop += dt * 7.0
            if self.drop > 1.6:
                if self.dropping == "goal":
                    self.load_level(self.level_index + 1)
                    name = self.level["name"]
                    if self.last_time is not None:
                        tail = "   NEW BEST" if self.last_was_best else ""
                        self.banner = (f"{scores.fmt(self.last_time)}{tail}"
                                       f"     next: {name}")
                    else:
                        self.banner = name
                    self.banner_t = 2.6
                else:
                    self.reset()
            return

        self.vx += ROLL * G * math.sin(self.tilt_x) * dt
        self.vz -= ROLL * G * math.sin(self.tilt_z) * dt
        damp = math.exp(-0.55 * dt)
        self.vx *= damp
        self.vz *= damp

        self.bx += self.vx * dt
        self.bz += self.vz * dt
        self._collide()

        # Rolling without slipping: omega = v / r about the axis perpendicular
        # to travel. Worth doing now the ball has a texture - on chrome the
        # spin was literally invisible.
        speed = math.hypot(self.vx, self.vz)
        if speed > 1e-4:
            axis = rl.Vector3(self.vz / speed, 0.0, -self.vx / speed)
            self.ball_rot = rl.matrix_multiply(
                self.ball_rot, rl.matrix_rotate(axis, speed / BALL_R * dt))

        # A ball tips in once its contact patch clears the rim, not when its
        # centre reaches it.
        cap = max(0.25, self.hole_r - BALL_R * 0.45)
        for hx, hz in self.level["holes"]:
            if (self.bx - hx) ** 2 + (self.bz - hz) ** 2 < cap * cap:
                self.total_falls += 1
                self.flash, self.flash_col = 1.0, (230, 96, 74)
                self.dropping = "hole"
                self.bx, self.bz = hx, hz
                return
        gx, gz = self.level["goal"]
        gcap = max(0.3, self.goal_r - BALL_R * 0.45)
        if (self.bx - gx) ** 2 + (self.bz - gz) ** 2 < gcap * gcap:
            self.flash, self.flash_col = 1.0, (96, 210, 150)
            self.dropping = "goal"
            self.bx, self.bz = gx, gz
            if self.timer_on and self.timing:
                self.timing = False
                self.last_time = self.elapsed
                self.last_was_best = scores.record(
                    self.scores, self.level["name"], self.elapsed)
            else:
                self.last_time = None

    def _collide(self):
        r = BALL_R
        lim = HALF - r
        if self.bx < -lim or self.bx > lim:
            self.bx = max(-lim, min(lim, self.bx))
            self.vx = -self.vx * 0.32
        if self.bz < -lim or self.bz > lim:
            self.bz = max(-lim, min(lim, self.bz))
            self.vz = -self.vz * 0.32

        for cx, cz, hw, hd in self.level["walls"]:
            nx_ = max(cx - hw, min(self.bx, cx + hw))
            nz_ = max(cz - hd, min(self.bz, cz + hd))
            dx, dz = self.bx - nx_, self.bz - nz_
            d2 = dx * dx + dz * dz
            if d2 >= r * r or d2 == 0:
                continue
            d = math.sqrt(d2)
            nxn, nzn = dx / d, dz / d
            self.bx += nxn * (r - d)
            self.bz += nzn * (r - d)
            dot = self.vx * nxn + self.vz * nzn
            self.vx -= 1.32 * dot * nxn
            self.vz -= 1.32 * dot * nzn

    # -- level bar and timer -------------------------------------------------
    BTN_W, BTN_H, BTN_GAP = 46, 38, 8

    def _bar_origin(self):
        n = len(levels.LEVELS)
        total = n * self.BTN_W + (n - 1) * self.BTN_GAP
        return self.width - total - 30, 28

    def _level_rects(self):
        x0, y0 = self._bar_origin()
        step = self.BTN_W + self.BTN_GAP
        return [(rl.Rectangle(x0 + i * step, y0, self.BTN_W, self.BTN_H), i)
                for i in range(len(levels.LEVELS))]

    def _timer_rect(self):
        x0, y0 = self._bar_origin()
        return rl.Rectangle(x0, y0 + self.BTN_H + 10, 142, 32)

    def _toggle_timer(self):
        self.timer_on = not self.timer_on
        self.elapsed = 0.0
        self.timing = False

    def _handle_ui(self):
        if rl.is_key_pressed(rl.KEY_R):
            self.reset()
        if rl.is_key_pressed(rl.KEY_T):
            self._toggle_timer()
        if rl.is_key_pressed(rl.KEY_LEFT_BRACKET):
            self.jump(self.level_index - 1)
        if rl.is_key_pressed(rl.KEY_RIGHT_BRACKET):
            self.jump(self.level_index + 1)
        for i in range(min(9, len(levels.LEVELS))):
            if rl.is_key_pressed(rl.KEY_ONE + i):
                self.jump(i)

        if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            mp = rl.get_mouse_position()
            for rec, i in self._level_rects():
                if rl.check_collision_point_rec(mp, rec):
                    self.jump(i)
                    return
            if rl.check_collision_point_rec(mp, self._timer_rect()):
                self._toggle_timer()

    def _draw_bar(self):
        mp = rl.get_mouse_position()
        for rec, i in self._level_rects():
            cur = (i == self.level_index)
            hov = rl.check_collision_point_rec(mp, rec)
            if cur:
                bg = rl.Color(228, 216, 182, 240)
                fg = rl.Color(26, 28, 34, 255)
            else:
                bg = (rl.Color(62, 68, 84, 215) if hov
                      else rl.Color(30, 34, 44, 180))
                fg = rl.Color(198, 206, 222, 255)
            rl.draw_rectangle_rounded(rec, 0.30, 6, bg)
            rl.draw_rectangle_lines_ex(rec, 1.0, rl.Color(0, 0, 0, 90))
            txt = str(i + 1)
            w = rl.measure_text(txt, 22)
            rl.draw_text(txt, int(rec.x + rec.width / 2 - w / 2),
                         int(rec.y + 9), 22, fg)
            # A dot marks the levels that have holes, so the ramp is visible.
            if levels.LEVELS[i]["holes"]:
                rl.draw_circle(int(rec.x + rec.width - 9), int(rec.y + 8), 3,
                               rl.Color(150, 62, 44, 255) if cur
                               else rl.Color(224, 118, 94, 255))

        tr = self._timer_rect()
        hov = rl.check_collision_point_rec(mp, tr)
        if self.timer_on:
            bg = rl.Color(96, 186, 138, 235) if not hov else rl.Color(118, 208, 158, 245)
            fg = rl.Color(16, 32, 24, 255)
        else:
            bg = rl.Color(62, 68, 84, 210) if hov else rl.Color(30, 34, 44, 180)
            fg = rl.Color(184, 192, 208, 255)
        rl.draw_rectangle_rounded(tr, 0.35, 6, bg)
        rl.draw_rectangle_lines_ex(tr, 1.0, rl.Color(0, 0, 0, 90))
        label = "TIMER ON" if self.timer_on else "TIMER OFF"
        w = rl.measure_text(label, 18)
        rl.draw_text(label, int(tr.x + tr.width / 2 - w / 2),
                     int(tr.y + 7), 18, fg)

    def _draw_clock(self):
        if not self.timer_on:
            return
        live = rl.Color(238, 232, 214, 255) if self.timing \
            else rl.Color(168, 176, 192, 255)
        rl.draw_text(scores.fmt(self.elapsed), 28, 96, 42, live)
        best = scores.best(self.scores, self.level["name"])
        rl.draw_text(f"best  {scores.fmt(best)}", 28, 146, 20,
                     rl.Color(140, 152, 172, 255))
        if self.last_time is not None:
            tag = "  new best" if self.last_was_best else ""
            rl.draw_text(f"last  {scores.fmt(self.last_time)}{tag}", 28, 170,
                         20, rl.Color(120, 200, 152, 255) if self.last_was_best
                         else rl.Color(126, 136, 156, 255))

    # -- drawing -------------------------------------------------------------
    def _basis(self):
        """Board axes in world space. rlRotatef post-multiplies, so the draw
        order Rz then Rx composes as Rz * Rx - Rx applies to the point first."""
        cx, sx = math.cos(-self.tilt_z), math.sin(-self.tilt_z)
        cz, sz = math.cos(-self.tilt_x), math.sin(-self.tilt_x)

        def rot(x, y, z):
            y1, z1 = y * cx - z * sx, y * sx + z * cx
            return (x * cz - y1 * sz, x * sz + y1 * cz, z1)

        return rot

    def draw_3d(self):
        r2d = 180.0 / math.pi
        rot = self._basis()
        self.pbr.set_view_pos(self.camera.position)
        self.pbr.set_board_plane((0, 0, 0), rot(0, 1, 0), rot(1, 0, 0),
                                 rot(0, 0, 1), HALF)

        ball_y = BALL_R - self.drop * 1.9
        wx, wy, wz = rot(self.bx, ball_y, self.bz)
        self.pbr.set_shadow_sphere(wx, wy, wz, BALL_R)

        rl.rl_push_matrix()
        rl.rl_rotatef(-self.tilt_x * r2d, 0, 0, 1)
        rl.rl_rotatef(-self.tilt_z * r2d, 1, 0, 0)

        # Bottom panel, seen through every hole.
        self.pbr.material(metallic=0.0, roughness=0.80,
                          albedo=(0.055, 0.040, 0.030))
        rl.draw_model(self.floor, rl.Vector3(0, -WELL_D - 0.25, 0), 1.0,
                      rl.WHITE)

        # Play surface: alpha-cut so the holes are genuinely punched.
        self.pbr.material(use_maps=True, normal_map=True, roughness=1.0,
                          metallic=0.0, alpha_cut=True, clearcoat=0.55)
        rl.draw_model(self.surface, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)

        # Wells: lined tube plus a chamfered lip.
        for hx, hz in self.level["holes"]:
            self._draw_well(hx, hz, self.hole_r)
        gx, gz = self.level["goal"]
        self._draw_well(gx, gz, self.goal_r, goal=True)

        # Walls and the outer frame.
        self.pbr.material(use_maps=True, normal_map=True, roughness=1.0,
                          metallic=0.0, clearcoat=0.45)
        for cx, cz, hw, hd in self.level["walls"]:
            rl.draw_model_ex(self.wall, rl.Vector3(cx, WALL_H / 2, cz),
                             rl.Vector3(0, 1, 0), 0.0,
                             rl.Vector3(hw * 2, WALL_H, hd * 2), rl.WHITE)
        for cx, cz, hw, hd in LIP:
            rl.draw_model_ex(self.frame, rl.Vector3(cx, WALL_H * 0.30, cz),
                             rl.Vector3(0, 1, 0), 0.0,
                             rl.Vector3(hw * 2, WALL_H * 1.6 + BOARD_T,
                                        hd * 2), rl.WHITE)

        # Polished marble. Dielectric, so the lamp gives it a tight travelling
        # highlight over a soft body rather than a mirror image; the wrap term
        # lets light bleed past the terminator the way stone does.
        self.pbr.set_shadow_sphere(0, 0, 0, -1)      # no self-shadowing
        self.pbr.material(use_maps=True, normal_map=True, roughness=1.0,
                          metallic=0.0, clearcoat=0.55, wrap=0.38, planar=True)
        self.ball.transform = self.ball_rot
        rl.draw_model(self.ball, rl.Vector3(self.bx, ball_y, self.bz), 1.0,
                      rl.WHITE)
        rl.rl_pop_matrix()

    def _draw_well(self, hx, hz, r, goal=False):
        """A hole is a lined tube with a chamfered lip. The goal gets a
        shallow well with a lit green baize floor so it reads as a target
        rather than one more thing to fall into."""
        depth = GOAL_D if goal else WELL_D
        tube, lip, floor = self._well_meshes(r, depth)

        # These are open shells viewed from the inside, and hand-built winding
        # is easy to get backwards - just draw both faces.
        rl.rl_disable_backface_culling()

        self.pbr.material(use_maps=True, normal_map=True, roughness=1.0,
                          metallic=0.0)
        tint = rl.Color(150, 226, 176, 255) if goal else rl.WHITE
        rl.draw_model(tube, rl.Vector3(hx, -0.001, hz), 1.0, tint)

        if goal:
            self.pbr.material(metallic=0.0, roughness=0.48,
                              albedo=(0.16, 0.70, 0.38))
            rl.draw_model(floor, rl.Vector3(hx, -depth + 0.02, hz), 1.0,
                          rl.WHITE)

        self.pbr.material(use_maps=True, normal_map=True, roughness=1.0,
                          metallic=0.0, clearcoat=0.5)
        rl.draw_model(lip, rl.Vector3(hx, 0.004, hz), 1.0,
                      rl.Color(198, 238, 208, 255) if goal else rl.WHITE)

        rl.rl_enable_backface_culling()

    def draw_overlay(self):
        for i in range(7):
            t = i / 6.0
            a = int(56 * t * t)
            m = int(self.width * 0.055 * (1.0 - t) + 4)
            rl.draw_rectangle_lines_ex(
                rl.Rectangle(-m, -m, self.width + 2 * m, self.height + 2 * m),
                m, rl.Color(0, 0, 0, a))
        if self.flash > 0:
            r, g, b = self.flash_col
            rl.draw_rectangle(0, 0, self.width, self.height,
                              rl.Color(r, g, b, int(46 * self.flash)))
        if self.banner_t > 0:
            txt = self.banner
            a = int(255 * min(1.0, self.banner_t))
            col = rl.Color(150, 226, 176, a) if self.last_was_best \
                else rl.Color(236, 226, 200, a)
            w = rl.measure_text(txt, 44)
            rl.draw_text(txt, self.width // 2 - w // 2, int(self.height * 0.16),
                         44, col)

        # Navigation stays visible with the HUD hidden - it is how you move
        # around, not decoration.
        self._draw_bar()
        self._draw_clock()

    def draw_hud(self):
        lv = self.level
        n = len(levels.LEVELS)
        y = self.height - 92
        rl.draw_text(f"level {min(self.level_index + 1, n)}/{n}   {lv['name']}",
                     28, y, 24, rl.Color(214, 220, 232, 255))
        holes = len(lv["holes"])
        sub = "no holes" if holes == 0 else f"{holes} holes"
        rl.draw_text(f"{sub}   in the hole {self.total_falls}",
                     28, y + 32, 20, rl.Color(146, 158, 178, 255))


if __name__ == "__main__":
    Labyrinth(base_parser(__doc__).parse_args()).run()
