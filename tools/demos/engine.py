"""Shared scaffolding for the R-Net joystick 3D demos.

Provides:
  Input     - joystick over serial with deadzone/expo shaping, keyboard fallback
  Demo      - window + loop + HUD + screenshot plumbing
  Terrain   - heightfield with baked directional shading

Every demo runs without the joystick attached (arrow keys / WASD), so they can
be developed and shown on any machine.
"""

import math
import re
import sys
import threading
from pathlib import Path

import pyray as rl
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rnetport

# --------------------------------------------------------------- input ------

LINE_RE = re.compile(
    r"X=(?P<x>-?\d+)\s+Y=(?P<y>-?\d+)\s+R=(?P<r>-?\d+)\s+"
    r"dx=(?P<dx>-?\d+)\s+dy=(?P<dy>-?\d+)\s+sw=(?P<sw>\d+)"
)
FULL_SCALE = 143.0


def _find_port():
    return rnetport.find_port()


def shape(v, deadzone, expo):
    """Normalised stick value -> shaped output. Deadzone is rescaled rather
    than clipped, so motion just outside it starts from zero instead of
    jumping. Expo keeps the centre soft while preserving full authority."""
    mag = abs(v)
    if mag <= deadzone:
        return 0.0
    mag = (mag - deadzone) / (1.0 - deadzone)
    mag = (1.0 - expo) * mag + expo * mag ** 3
    return math.copysign(min(mag, 1.0), v)


class _SerialReader(threading.Thread):
    daemon = True

    def __init__(self, ser):
        super().__init__()
        self.ser = ser
        self.lock = threading.Lock()
        self.raw = {"dx": 0, "dy": 0, "sw": 0}
        self.running = True

    def run(self):
        while self.running:
            try:
                line = self.ser.readline().decode("utf-8", "replace")
            except Exception:
                break
            m = LINE_RE.search(line)
            if m:
                with self.lock:
                    self.raw = {k: int(m.group(k)) for k in ("dx", "dy", "sw")}

    def latest(self):
        with self.lock:
            return dict(self.raw)

    def stop(self):
        self.running = False
        try:
            self.ser.close()
        except Exception:
            pass


class Input:
    """Unified stick input in -1..1, whichever source is available."""

    def __init__(self, port=None, baud=115200, deadzone=0.05, expo=0.35,
                 smooth=0.25, force_keyboard=False):
        self.deadzone, self.expo, self.smooth = deadzone, expo, smooth
        self.x = self.y = 0.0
        self.sw = False
        self.reader = None
        self.source = "keyboard"

        if force_keyboard:
            return
        try:
            import serial
        except ImportError:
            return
        port = port or _find_port()
        if not port:
            return
        try:
            ser = serial.Serial(port, baud, timeout=1)
        except Exception:
            return
        self.reader = _SerialReader(ser)
        self.reader.start()
        self.source = port

    def poll(self):
        if self.reader:
            r = self.reader.latest()
            tx = shape(max(-1.5, min(1.5, r["dx"] / FULL_SCALE)),
                       self.deadzone, self.expo)
            ty = shape(max(-1.5, min(1.5, r["dy"] / FULL_SCALE)),
                       self.deadzone, self.expo)
            self.sw = bool(r["sw"])
        else:
            tx = ty = 0.0
            if rl.is_key_down(rl.KEY_LEFT) or rl.is_key_down(rl.KEY_A):
                tx -= 1.0
            if rl.is_key_down(rl.KEY_RIGHT) or rl.is_key_down(rl.KEY_D):
                tx += 1.0
            if rl.is_key_down(rl.KEY_DOWN) or rl.is_key_down(rl.KEY_S):
                ty -= 1.0
            if rl.is_key_down(rl.KEY_UP) or rl.is_key_down(rl.KEY_W):
                ty += 1.0
            self.sw = rl.is_key_down(rl.KEY_SPACE)

        k = 1.0 - self.smooth
        self.x += (tx - self.x) * k
        self.y += (ty - self.y) * k
        return self.x, self.y

    def close(self):
        if self.reader:
            self.reader.stop()


# ------------------------------------------------------------- terrain ------

def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class Terrain:
    """Heightfield mesh with directional shading baked into its texture.

    Baking beats a custom shader here: no GLSL to keep in step with raylib's
    uniform conventions, and it lets each demo pick a palette as a plain
    Python function of height and slope.
    """

    def __init__(self, heights, world_w, world_d, y_scale, palette,
                 sun=(-0.55, 0.72, 0.42)):
        self.h = heights
        self.nz = len(heights)
        self.nx = len(heights[0])
        self.w, self.d, self.y_scale = world_w, world_d, y_scale

        nx, nz = self.nx, self.nz
        img = rl.gen_image_color(nx, nz, rl.BLACK)
        tex_img = rl.gen_image_color(nx, nz, rl.BLACK)

        # World-space spacing between samples, needed for correct slope.
        sx = world_w / (nx - 1)
        sz = world_d / (nz - 1)
        slen = math.sqrt(sum(c * c for c in sun))
        sun = tuple(c / slen for c in sun)

        for z in range(nz):
            for x in range(nx):
                hv = _clamp01(heights[z][x])
                g = int(hv * 255)
                rl.image_draw_pixel(img, x, z, rl.Color(g, g, g, 255))

                xl = heights[z][max(0, x - 1)] * y_scale
                xr = heights[z][min(nx - 1, x + 1)] * y_scale
                zl = heights[max(0, z - 1)][x] * y_scale
                zr = heights[min(nz - 1, z + 1)][x] * y_scale
                gx, gy, gz = -(xr - xl) / (2 * sx), 1.0, -(zr - zl) / (2 * sz)
                inv = 1.0 / math.sqrt(gx * gx + gy * gy + gz * gz)
                gx, gy, gz = gx * inv, gy * inv, gz * inv

                lam = max(0.0, gx * sun[0] + gy * sun[1] + gz * sun[2])
                light = 0.34 + 0.66 * lam
                slope = 1.0 - gy

                r, g2, b = palette(hv, slope, x / (nx - 1), z / (nz - 1))
                rl.image_draw_pixel(tex_img, x, z, rl.Color(
                    min(255, int(r * light)),
                    min(255, int(g2 * light)),
                    min(255, int(b * light)), 255))

        mesh = rl.gen_mesh_heightmap(img, rl.Vector3(world_w, y_scale, world_d))
        self.model = rl.load_model_from_mesh(mesh)
        self.texture = rl.load_texture_from_image(tex_img)
        rl.set_material_texture(self.model.materials[0],
                                rl.MATERIAL_MAP_DIFFUSE, self.texture)
        rl.unload_image(img)
        rl.unload_image(tex_img)

    def height_at(self, x, z):
        """Bilinear world-space height. Mesh spans 0..w, 0..d from the origin."""
        fx = _clamp01(x / self.w) * (self.nx - 1)
        fz = _clamp01(z / self.d) * (self.nz - 1)
        x0, z0 = int(fx), int(fz)
        x1, z1 = min(self.nx - 1, x0 + 1), min(self.nz - 1, z0 + 1)
        tx, tz = fx - x0, fz - z0
        a = self.h[z0][x0] * (1 - tx) + self.h[z0][x1] * tx
        b = self.h[z1][x0] * (1 - tx) + self.h[z1][x1] * tx
        return (a * (1 - tz) + b * tz) * self.y_scale

    def draw(self):
        rl.draw_model(self.model, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)

    def draw_at(self, x, y, z, tint=None):
        rl.draw_model(self.model, rl.Vector3(x, y, z), 1.0, tint or rl.WHITE)


# ---------------------------------------------------------------- demo ------

class Demo:
    """Window, loop, HUD and screenshot plumbing. Subclasses implement
    setup / update / draw_3d, and optionally draw_hud."""

    title = "demo"
    help_text = ""
    sky_top = rl.Color(24, 34, 56, 255)
    sky_bottom = rl.Color(96, 116, 148, 255)

    def __init__(self, args):
        self.args = args
        self.win_w = args.width
        self.win_h = args.height
        self.show_hud = not args.no_hud

        rl.set_config_flags(rl.FLAG_MSAA_4X_HINT | rl.FLAG_VSYNC_HINT
                            | rl.FLAG_WINDOW_RESIZABLE)
        rl.init_window(self.win_w, self.win_h, f"R-Net - {self.title}")
        rl.set_target_fps(60)

        if args.list_monitors:
            self.print_monitors()
            rl.close_window()
            raise SystemExit(0)

        # Screenshots stay windowed - a mode switch mid-capture is a good way
        # to get a black frame.
        self.monitor = args.monitor
        self.fullscreen = not (args.windowed or args.screenshot)
        self.borderless = not args.exclusive
        self._borderless_on = False
        self.apply_display()

        self.width = rl.get_screen_width()
        self.height = rl.get_screen_height()

        self.input = Input(port=args.port, deadzone=args.deadzone,
                           expo=args.expo, force_keyboard=args.keyboard)
        self.camera = rl.Camera3D(rl.Vector3(0, 10, 10), rl.Vector3(0, 0, 0),
                                  rl.Vector3(0, 1, 0), 50.0,
                                  rl.CAMERA_PERSPECTIVE)
        self.t = 0.0
        self.notice = ""
        self.notice_t = 0.0
        self.setup()

    # -- display -------------------------------------------------------------
    @staticmethod
    def monitor_info(m):
        p = rl.get_monitor_position(m)
        return (int(p.x), int(p.y), rl.get_monitor_width(m),
                rl.get_monitor_height(m),
                rl.get_monitor_refresh_rate(m),
                rl.get_monitor_name(m).decode("utf-8", "replace")
                if isinstance(rl.get_monitor_name(m), bytes)
                else str(rl.get_monitor_name(m)))

    @classmethod
    def print_monitors(cls):
        n = rl.get_monitor_count()
        cur = rl.get_current_monitor()
        print(f"{n} monitor(s):")
        for m in range(n):
            x, y, w, h, hz, name = cls.monitor_info(m)
            mark = "*" if m == cur else " "
            print(f" {mark} {m}  {w}x{h} @{hz}Hz  at ({x},{y})  {name}")
        print("\n * = current.  Pass --monitor N to choose one.")

    def _leave_fullscreen(self):
        if self._borderless_on:
            rl.toggle_borderless_windowed()
            self._borderless_on = False
        if rl.is_window_fullscreen():
            rl.toggle_fullscreen()

    def apply_display(self):
        """Put the window on the requested monitor, in the requested mode.

        Order matters: raylib's fullscreen and borderless modes both act on
        whichever monitor the window is currently *on*, so the window has to be
        moved first and then switched, never the other way round.
        """
        count = max(1, rl.get_monitor_count())
        self._leave_fullscreen()
        if self.monitor is None or self.monitor < 0 or self.monitor >= count:
            self.monitor = rl.get_current_monitor()

        mx, my, mw, mh, _, _ = self.monitor_info(self.monitor)
        w = min(self.win_w, mw - 80)
        h = min(self.win_h, mh - 120)
        rl.set_window_size(w, h)
        rl.set_window_position(mx + (mw - w) // 2, my + (mh - h) // 2)

        if self.fullscreen:
            if self.borderless:
                rl.toggle_borderless_windowed()
                self._borderless_on = True
            else:
                rl.set_window_size(mw, mh)
                rl.toggle_fullscreen()

        self.width = rl.get_screen_width()
        self.height = rl.get_screen_height()

    def toggle_fullscreen(self):
        if not self.fullscreen:
            # Remember the windowed size so returning to it is not a surprise.
            self.win_w = max(640, rl.get_screen_width())
            self.win_h = max(480, rl.get_screen_height())
        self.fullscreen = not self.fullscreen
        self.apply_display()

    def cycle_monitor(self, step=1):
        count = rl.get_monitor_count()
        if count < 2:
            return False
        self.monitor = (self.monitor + step) % count
        self.apply_display()
        return True

    # -- to override ---------------------------------------------------------
    def setup(self):
        pass

    def update(self, dt, sx, sy):
        pass

    def draw_3d(self):
        pass

    def draw_hud(self):
        pass

    def draw_overlay(self):
        """2D drawn after the haze but before the HUD text."""
        pass

    # -- driver --------------------------------------------------------------
    horizon = 0.46          # screen fraction where the haze band sits
    haze_strength = 88

    def draw_sky(self):
        rl.draw_rectangle_gradient_v(0, 0, self.width, self.height,
                                     self.sky_top, self.sky_bottom)

    def draw_haze(self):
        """Aerial perspective, faked in 2D after the 3D pass.

        Cheaper and more controllable than a fog shader: a band of sky colour
        centred on the horizon, fading out above and below. Distant geometry
        sits behind more of it than near geometry, which is most of what fog
        buys visually.
        """
        c = self.sky_bottom
        hy = int(self.height * self.horizon)
        a = self.haze_strength
        rl.draw_rectangle_gradient_v(
            0, max(0, hy - int(self.height * 0.18)), self.width,
            int(self.height * 0.18),
            rl.Color(c.r, c.g, c.b, 0), rl.Color(c.r, c.g, c.b, a))
        rl.draw_rectangle_gradient_v(
            0, hy, self.width, int(self.height * 0.13),
            rl.Color(c.r, c.g, c.b, a), rl.Color(c.r, c.g, c.b, 0))

    def run(self):
        frames = 0
        # A screenshot needs a few frames of warm-up so timing-based motion has
        # somewhere to be; default to 60 if the caller didn't say.
        target = self.args.frames or (60 if self.args.screenshot else 0)
        while not rl.window_should_close():
            dt = min(rl.get_frame_time(), 1 / 30.0)
            self.t += dt
            sx, sy = self.input.poll()

            # Re-read every frame so a mode switch, a monitor change or the
            # user dragging the window edge all just work.
            self.width = rl.get_screen_width()
            self.height = rl.get_screen_height()

            if rl.is_key_pressed(rl.KEY_H):
                self.show_hud = not self.show_hud
            if rl.is_key_pressed(rl.KEY_F11) or rl.is_key_pressed(rl.KEY_F):
                self.toggle_fullscreen()
            if rl.is_key_pressed(rl.KEY_M):
                back = (rl.is_key_down(rl.KEY_LEFT_SHIFT)
                        or rl.is_key_down(rl.KEY_RIGHT_SHIFT))
                if self.cycle_monitor(-1 if back else 1):
                    self.notice = f"monitor {self.monitor}"
                    self.notice_t = 1.6

            self.update(dt, sx, sy)

            rl.begin_drawing()
            rl.clear_background(self.sky_bottom)
            self.draw_sky()
            rl.begin_mode_3d(self.camera)
            self.draw_3d()
            rl.end_mode_3d()
            self.draw_haze()
            self.draw_overlay()

            self.notice_t = max(0.0, self.notice_t - dt)
            if self.show_hud:
                rl.draw_text(self.title, 28, 24, 30, rl.Color(240, 244, 250, 255))
                mode = "fullscreen" if self.fullscreen else "windowed"
                screens = rl.get_monitor_count()
                disp = (f"F11 {mode}" if screens < 2
                        else f"F11 {mode}   M monitor {self.monitor + 1}/{screens}")
                sub = f"{self.input.source}   {self.help_text}   {disp}"
                rl.draw_text(sub, 28, 60, 18, rl.Color(150, 165, 185, 255))
                self.draw_hud()
            if self.notice_t > 0:
                a = int(255 * min(1.0, self.notice_t))
                w = rl.measure_text(self.notice, 30)
                rl.draw_text(self.notice, self.width // 2 - w // 2,
                             self.height - 90, 30,
                             rl.Color(236, 230, 208, a))
            rl.end_drawing()

            frames += 1
            if target and frames >= target:
                if self.args.screenshot:
                    rl.take_screenshot(self.args.screenshot)
                break

        self.input.close()
        rl.close_window()


def base_parser(description):
    import argparse
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--port")
    p.add_argument("--keyboard", action="store_true",
                   help="ignore the joystick, use arrow keys / WASD")
    p.add_argument("--windowed", action="store_true",
                   help="start windowed instead of fullscreen")
    p.add_argument("--monitor", type=int, default=None, metavar="N",
                   help="0-based monitor to open on (default: current)")
    p.add_argument("--list-monitors", action="store_true",
                   help="print the attached monitors and exit")
    p.add_argument("--exclusive", action="store_true",
                   help="true fullscreen instead of borderless")
    p.add_argument("--width", type=int, default=1280,
                   help="windowed width (default 1280)")
    p.add_argument("--height", type=int, default=720,
                   help="windowed height (default 720)")
    p.add_argument("--no-hud", action="store_true")
    p.add_argument("--deadzone", type=float, default=0.05)
    p.add_argument("--expo", type=float, default=0.35)
    p.add_argument("--screenshot", metavar="PATH",
                   help="save a PNG after --frames frames and exit")
    p.add_argument("--frames", type=int, default=0,
                   help="exit after N frames (0 = run until closed)")
    p.add_argument("--fast-textures", action="store_true",
                   help="half-resolution procedural maps - quicker startup")
    p.add_argument("--level", type=int, default=0,
                   help="start on this level (1-based)")
    p.add_argument("--timer", action="store_true",
                   help="run the per-level timer and track best times")
    return p
