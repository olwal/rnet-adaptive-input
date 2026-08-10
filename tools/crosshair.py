#!/usr/bin/env python3
"""Fullscreen crosshair driven by the R-Net joystick.

Absolute mapping: stick centre = screen centre, full deflection = screen edge.
The stick self-centres, so the crosshair returns home when released - which
makes the mapping feel direct rather than like driving a cursor.

  python tools/crosshair.py
  python tools/crosshair.py --windowed --deadzone 0.06 --expo 0.4

Keys:  Esc quit   D debug overlay   T trail   C recentre   [ ] expo
       - + sensitivity   F / F11 fullscreen   M next monitor
"""

import argparse
import math
import re
import sys
import threading
import rnetport

try:
    import serial
except ImportError:
    sys.exit("pyserial is required:  python -m pip install pyserial")

try:
    import pygame
except ImportError:
    sys.exit("pygame is required:  python -m pip install pygame")

LINE_RE = re.compile(
    r"X=(?P<x>-?\d+)\s+Y=(?P<y>-?\d+)\s+R=(?P<r>-?\d+)\s+"
    r"dx=(?P<dx>-?\d+)\s+dy=(?P<dy>-?\d+)\s+sw=(?P<sw>\d+)"
)

FULL_SCALE = 143.0          # |dx|,|dy| at full deflection

BG       = (12, 14, 18)
RING     = (38, 44, 54)
CROSS    = (235, 240, 248)
CROSS_HL = (120, 220, 160)   # while the switch is pressed
TRAIL    = (60, 110, 90)
TEXT     = (130, 140, 155)


class Reader(threading.Thread):
    """Serial reader. Rendering must never block on the port."""

    daemon = True

    def __init__(self, port, baud):
        super().__init__()
        self.ser = serial.Serial(port, baud, timeout=1)
        self.lock = threading.Lock()
        self.sample = {"dx": 0, "dy": 0, "sw": 0, "r": 0}
        self.count = 0
        self.running = True

    def run(self):
        while self.running:
            try:
                raw = self.ser.readline().decode("utf-8", "replace")
            except serial.SerialException:
                break
            m = LINE_RE.search(raw)
            if not m:
                continue
            s = {k: int(v) for k, v in m.groupdict().items()}
            with self.lock:
                self.sample = s
                self.count += 1

    def latest(self):
        with self.lock:
            return dict(self.sample), self.count

    def stop(self):
        self.running = False
        try:
            self.ser.close()
        except Exception:
            pass


def find_port():
    return rnetport.find_port()


def shape(v, deadzone, expo):
    """Normalised stick value -> shaped output, both in -1..1.

    Deadzone is rescaled (not just clipped) so travel just outside it starts
    from zero rather than jumping. Expo keeps the centre soft while leaving
    full authority at the edges - the standard RC trick, and the parameter
    that matters most for fine control.
    """
    mag = abs(v)
    if mag <= deadzone:
        return 0.0
    mag = (mag - deadzone) / (1.0 - deadzone)
    mag = (1.0 - expo) * mag + expo * mag ** 3
    return math.copysign(min(mag, 1.0), v)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--deadzone", type=float, default=0.05)
    ap.add_argument("--expo", type=float, default=0.35)
    ap.add_argument("--sensitivity", type=float, default=1.0)
    ap.add_argument("--smooth", type=float, default=0.35,
                    help="0=none, ->1 heavier. Interpolates between samples.")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--monitor", type=int, default=0, metavar="N",
                    help="0-based monitor to open on")
    ap.add_argument("--list-monitors", action="store_true")
    ap.add_argument("--invert-y", action="store_true")
    args = ap.parse_args()

    if args.list_monitors:
        pygame.init()
        sizes = pygame.display.get_desktop_sizes()
        print(f"{len(sizes)} monitor(s):")
        for i, (w, h) in enumerate(sizes):
            print(f"   {i}  {w}x{h}")
        return

    port = args.port or find_port()
    if not port:
        sys.exit("No serial port found. Pass --port COMn.")
    try:
        reader = Reader(port, args.baud)
    except serial.SerialException as e:
        sys.exit(f"Could not open {port}: {e}")
    reader.start()

    pygame.init()
    pygame.display.set_caption("R-Net joystick - crosshair")
    n_screens = max(1, len(pygame.display.get_desktop_sizes()))
    monitor = max(0, min(args.monitor, n_screens - 1))

    def open_window(full, mon):
        # SDL picks the monitor from the display index passed to set_mode; a
        # size of (0, 0) means "match that display".
        flags = pygame.FULLSCREEN if full else 0
        size = (0, 0) if full else (1280, 800)
        return pygame.display.set_mode(size, flags, display=mon)

    fullscreen = not args.windowed
    screen = open_window(fullscreen, monitor)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 18)

    deadzone, expo, sens = args.deadzone, args.expo, args.sensitivity
    show_debug, show_trail, fullscreen = True, True, not args.windowed
    trail = []
    cx = cy = 0.0            # smoothed, normalised -1..1
    offx = offy = 0          # recentre offset, in counts

    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif e.key == pygame.K_d:
                    show_debug = not show_debug
                elif e.key == pygame.K_t:
                    show_trail = not show_trail
                    trail.clear()
                elif e.key == pygame.K_c:
                    s, _ = reader.latest()
                    offx, offy = s["dx"], s["dy"]
                elif e.key == pygame.K_LEFTBRACKET:
                    expo = max(0.0, expo - 0.05)
                elif e.key == pygame.K_RIGHTBRACKET:
                    expo = min(0.95, expo + 0.05)
                elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    sens = max(0.2, sens - 0.05)
                elif e.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    sens = min(3.0, sens + 0.05)
                elif e.key in (pygame.K_f, pygame.K_F11):
                    fullscreen = not fullscreen
                    screen = open_window(fullscreen, monitor)
                elif e.key == pygame.K_m and n_screens > 1:
                    monitor = (monitor + 1) % n_screens
                    screen = open_window(fullscreen, monitor)

        w, h = screen.get_size()
        mid_x, mid_y = w // 2, h // 2
        radius = int(min(w, h) * 0.42)

        s, count = reader.latest()
        nx = (s["dx"] - offx) / FULL_SCALE
        ny = (s["dy"] - offy) / FULL_SCALE
        tx = shape(max(-1.5, min(1.5, nx)), deadzone, expo) * sens
        ty = shape(max(-1.5, min(1.5, ny)), deadzone, expo) * sens
        if not args.invert_y:
            ty = -ty          # stick forward should move the crosshair up

        # Samples arrive at ~100 Hz, frames at 60 - interpolate so motion
        # never looks stepped.
        k = 1.0 - args.smooth
        cx += (tx - cx) * k
        cy += (ty - cy) * k

        px = mid_x + int(cx * radius)
        py = mid_y + int(cy * radius)

        screen.fill(BG)
        pygame.draw.circle(screen, RING, (mid_x, mid_y), radius, 1)
        pygame.draw.line(screen, RING, (mid_x - 12, mid_y), (mid_x + 12, mid_y))
        pygame.draw.line(screen, RING, (mid_x, mid_y - 12), (mid_x, mid_y + 12))

        if show_trail:
            trail.append((px, py))
            if len(trail) > 90:
                trail.pop(0)
            if len(trail) > 1:
                pygame.draw.lines(screen, TRAIL, False, trail, 2)

        colour = CROSS_HL if s["sw"] else CROSS
        arm, gap = 46, 12
        pygame.draw.line(screen, colour, (px - arm, py), (px - gap, py), 3)
        pygame.draw.line(screen, colour, (px + gap, py), (px + arm, py), 3)
        pygame.draw.line(screen, colour, (px, py - arm), (px, py - gap), 3)
        pygame.draw.line(screen, colour, (px, py + gap), (px, py + arm), 3)
        pygame.draw.circle(screen, colour, (px, py), 5, 0 if s["sw"] else 2)

        if show_debug:
            lines = [
                f"{port}  {count} samples   {clock.get_fps():4.0f} fps",
                f"dx {s['dx']:+5d}   dy {s['dy']:+5d}   R {s['r']:5d}   "
                f"sw {'DOWN' if s['sw'] else 'up'}",
                f"deadzone {deadzone:.2f}   expo {expo:.2f} [ ]   "
                f"sens {sens:.2f} - +",
                "Esc quit   D debug   T trail   C recentre   "
                f"F fullscreen   M monitor {monitor + 1}/{n_screens}",
            ]
            for i, t in enumerate(lines):
                screen.blit(font.render(t, True, TEXT), (24, 20 + i * 22))

        pygame.display.flip()
        clock.tick(60)

    reader.stop()
    pygame.quit()


if __name__ == "__main__":
    main()
