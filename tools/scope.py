#!/usr/bin/env python3
"""Live ASCII scope for the R-Net joystick bring-up sketch.

Reads the serial stream produced by r-net_test.ino and renders raw counts,
reconstructed voltages and two centre-zero bargraphs that track the stick.

  python tools/scope.py                 # auto-detect port, live display
  python tools/scope.py --raw           # passthrough, no rendering
  python tools/scope.py --sample 20     # print 20 lines and exit
"""

import argparse
import os
import re
import sys
import time
import rnetport

try:
    import serial
except ImportError:
    sys.exit("pyserial is required:  python -m pip install pyserial")

# --- divider / ADC model -----------------------------------------------------
# Must match the hardware described in README.md. If you change resistors,
# change these.

ADC_MAX   = 1023.0      # 10-bit analogRead
ADC_VREF  = 3.3         # Teensy 3.0 analogReference(DEFAULT)

R_TOP     = 100_000.0   # series resistor, joystick output -> ADC pad
R_BOT     = 68_000.0    # ADC pad -> GND
R_SER_XY  = 1_800.0     # joystick's internal series R on X/Y outputs
R_SER_REF = 470.0       # joystick's internal series R on Vref

RATIO_XY   = R_BOT / (R_TOP + R_SER_XY + R_BOT)
RATIO_VREF = R_BOT / (R_TOP + R_SER_REF + R_BOT)

FULL_SCALE = 143        # expected |dx|,|dy| at full deflection

LINE_RE = re.compile(
    r"X=(?P<x>-?\d+)\s+Y=(?P<y>-?\d+)\s+R=(?P<r>-?\d+)\s+"
    r"dx=(?P<dx>-?\d+)\s+dy=(?P<dy>-?\d+)\s+sw=(?P<sw>\d+)"
)
CAL_RE = re.compile(r"calibration:.*")


def counts_to_adc_volts(counts):
    return counts / ADC_MAX * ADC_VREF


def counts_to_joystick_volts(counts, ratio):
    return counts_to_adc_volts(counts) / ratio


def enable_ansi():
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL | ENABLE_VT_PROCESSING
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def find_port():
    """Resolve a serial port. See tools/rnetport.py for the order."""
    return rnetport.find_port()


def bar(value, full_scale, half=30):
    """Centre-zero bargraph. Fill grows left for negative, right for positive."""
    frac = max(-1.0, min(1.0, value / full_scale))
    n = int(round(abs(frac) * half))
    if frac < 0:
        left, right = "." * (half - n) + "#" * n, "." * half
    else:
        left, right = "." * half, "#" * n + "." * (half - n)
    return "[" + left + "|" + right + "]"


def render(port, baud, s, peaks, cal):
    x, y, r = s["x"], s["y"], s["r"]
    dx, dy, sw = s["dx"], s["dy"], s["sw"]

    sw_txt = "PRESSED" if sw else "open   "
    lines = [
        f"  R-Net joystick scope - {port} @ {baud}            MODE sw: {sw_txt}",
        "",
        "  signal    counts     ADC V   joystick V",
        f"  Vref      {r:6d}    {counts_to_adc_volts(r):6.3f}       {counts_to_joystick_volts(r, RATIO_VREF):6.3f}",
        f"  X         {x:6d}    {counts_to_adc_volts(x):6.3f}       {counts_to_joystick_volts(x, RATIO_XY):6.3f}",
        f"  Y         {y:6d}    {counts_to_adc_volts(y):6.3f}       {counts_to_joystick_volts(y, RATIO_XY):6.3f}",
        "",
        f"  X {bar(dx, FULL_SCALE)} {dx:+5d}  "
        f"{counts_to_joystick_volts(dx, RATIO_XY):+6.2f} V   peak {peaks['dxmin']:+d}/{peaks['dxmax']:+d}",
        f"  Y {bar(dy, FULL_SCALE)} {dy:+5d}  "
        f"{counts_to_joystick_volts(dy, RATIO_XY):+6.2f} V   peak {peaks['dymin']:+d}/{peaks['dymax']:+d}",
        "",
        f"  full scale +/-{FULL_SCALE} counts (+/-1.15 V at joystick)     Ctrl+C to exit",
        f"  {cal}",
    ]
    return lines


def pearson(a, b):
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((v - ma) ** 2 for v in a)
    vb = sum((v - mb) ** 2 for v in b)
    if va == 0 or vb == 0:
        return 0.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (va * vb) ** 0.5


def slope(xs, ys):
    """Least-squares d(ys)/d(xs)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((v - mx) ** 2 for v in xs)
    if vx == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / vx


def analyze(rows, seconds):
    cols = {k: [r[k] for r in rows] for k in ("x", "y", "r", "dx", "dy")}

    print(f"\n{len(rows)} samples over {seconds:.1f} s\n")
    print("  channel      min      max   spread     mean")
    for k in ("r", "x", "y", "dx", "dy"):
        c = cols[k]
        print(f"  {k:<8} {min(c):8d} {max(c):8d} {max(c) - min(c):8d} "
              f"{sum(c) / len(c):8.1f}")

    dx, dy, r = cols["dx"], cols["dy"], cols["r"]
    swing_x = max(dx) - min(dx)
    swing_y = max(dy) - min(dy)
    moved, still = ("dx", "dy") if swing_x >= swing_y else ("dy", "dx")
    m_vals, s_vals = cols[moved], cols[still]

    print(f"\n  axis swept: {moved}  (spread {max(m_vals) - min(m_vals)}), "
          f"idle axis: {still} (spread {max(s_vals) - min(s_vals)})")
    print("\n  coupling")
    print(f"    corr({moved}, {still})   = {pearson(m_vals, s_vals):+.3f}"
          "     want ~0")
    print(f"    slope d{still}/d{moved}  = {slope(m_vals, s_vals):+.4f}"
          "    counts of idle axis per count of swept axis")
    print(f"    corr({moved}, R)    = {pearson(m_vals, r):+.3f}")
    print(f"    slope dR/d{moved}   = {slope(m_vals, r):+.4f}")

    leak = abs(slope(m_vals, s_vals))
    print()
    if max(m_vals) - min(m_vals) < 40:
        print("  VERDICT: not enough deflection to judge - sweep one axis fully.")
    elif leak < 0.02:
        print(f"  VERDICT: axes independent (leak {leak * 100:.1f}%). "
              "R movement is common-mode and cancels in dx/dy. Nothing to fix.")
    elif leak < 0.06:
        print(f"  VERDICT: mild leak {leak * 100:.1f}%. Usable; "
              "100 nF caps on the taps would clean it up.")
    else:
        print(f"  VERDICT: real crosstalk {leak * 100:.1f}%. "
              "Add 100 nF from each tap to GND at the Teensy pads.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: auto-detect)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--raw", action="store_true", help="passthrough, no rendering")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="print N parsed lines and exit (non-interactive)")
    ap.add_argument("--once", action="store_true",
                    help="render a single frame and exit (no cursor control)")
    ap.add_argument("--analyze", type=float, metavar="SECONDS",
                    help="capture for SECONDS, then report crosstalk statistics")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        sys.exit("No serial port found. Pass --port COMn.")

    try:
        ser = serial.Serial(port, args.baud, timeout=2)
    except serial.SerialException as e:
        sys.exit(f"Could not open {port}: {e}")

    # When no PJRC board is attached, port discovery falls back to whatever
    # single serial device is present, which may be something unrelated. Say
    # which port was opened, and give up rather than blocking forever if
    # nothing that parses as telemetry arrives.
    print(f"reading {port} at {args.baud}", file=sys.stderr)
    started = time.time()
    got_any = got_parsed = False

    def check_alive(raw, parsed=False):
        """Two separate failure modes, two separate messages: silence usually
        means the wrong port, whereas traffic that never parses means the
        right port but the wrong firmware."""
        nonlocal got_any, got_parsed
        got_any = got_any or bool(raw)
        got_parsed = got_parsed or parsed
        if got_parsed:
            return
        elapsed = time.time() - started
        if not got_any and elapsed > 6.0:
            ser.close()
            sys.exit(f"\nNothing received on {port} after 6 s. Wrong port, or "
                     f"no firmware running?\nPorts visible:\n"
                     f"{rnetport.describe_ports()}")
        if got_any and elapsed > 10.0:
            ser.close()
            sys.exit(f"\n{port} is sending data, but none of it is joystick "
                     f"telemetry.\nThis is probably a different board. Last "
                     f"line seen:\n  {raw[:120]!r}\nPorts visible:\n"
                     f"{rnetport.describe_ports()}")

    peaks = {"dxmin": 0, "dxmax": 0, "dymin": 0, "dymax": 0}
    cal = "calibration: (not captured - reset the board to see it)"
    drawn = 0
    seen = 0

    if args.analyze:
        print(f"Capturing {args.analyze:.0f} s - sweep ONE axis through its "
              "full travel, leave the other centred.")
        rows = []
        t0 = time.time()
        while time.time() - t0 < args.analyze:
            raw = ser.readline().decode("utf-8", "replace").strip()
            m = LINE_RE.search(raw)
            if m:
                rows.append({k: int(v) for k, v in m.groupdict().items()})
        ser.close()
        if not rows:
            sys.exit("No data captured.")
        analyze(rows, args.analyze)
        return

    if not args.raw and args.sample is None and not args.once:
        enable_ansi()
        print("\x1b[2J\x1b[H", end="")

    try:
        while True:
            raw = ser.readline().decode("utf-8", "replace").strip()
            check_alive(raw, bool(raw) and LINE_RE.search(raw) is not None)
            if not raw:
                continue

            if args.raw:
                print(raw)
                continue

            if CAL_RE.match(raw):
                cal = raw
                continue

            m = LINE_RE.search(raw)
            if not m:
                continue
            s = {k: int(v) for k, v in m.groupdict().items()}

            peaks["dxmin"] = min(peaks["dxmin"], s["dx"])
            peaks["dxmax"] = max(peaks["dxmax"], s["dx"])
            peaks["dymin"] = min(peaks["dymin"], s["dy"])
            peaks["dymax"] = max(peaks["dymax"], s["dy"])

            if args.sample is not None:
                print(" | ".join(
                    f"{k}={s[k]}" for k in ("x", "y", "r", "dx", "dy", "sw")))
                seen += 1
                if seen >= args.sample:
                    break
                continue

            lines = render(port, args.baud, s, peaks, cal)
            if args.once:
                print("\n".join(lines))
                break
            if drawn:
                print(f"\x1b[{drawn}A", end="")
            print("\n".join(f"{ln}\x1b[K" for ln in lines))
            drawn = len(lines) + 1
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
