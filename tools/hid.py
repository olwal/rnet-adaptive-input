#!/usr/bin/env python3
"""Mode switcher and live tuner for the multi-HID firmware.

The joystick has no button, so mode changes come from here over the serial
link that is present in every mode. Same tool tunes the shaping, because the
shaping is shared across modes and tuning it in three places would guarantee
they drift apart.

  python tools/hid.py                     # interactive
  python tools/hid.py mode gamepad
  python tools/hid.py set expo 0.45
  python tools/hid.py get
  python tools/hid.py watch

Note the port is exclusive: leave this running and uploads will fail with
"Access is denied", and the Teensy loader will then report success anyway.
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is required:  python -m pip install pyserial")

# Modes and settings live in one table each, and both the validation and the
# --help text are generated from them. Hand-written help drifts out of date the
# first time a range changes.
MODE_TABLE = {
    0: ("park", ("parked", "off"),
        "drives nothing - the power-on default"),
    1: ("gamepad", ("pad", "joystick"),
        "absolute axes, DirectInput"),
    2: ("mouse", ("cursor",),
        "velocity mapping with sub-pixel carry"),
    3: ("keyboard", ("keys", "kbd"),
        "arrow keys with hysteresis"),
}
MODES = {}
for _n, (_primary, _aliases, _) in MODE_TABLE.items():
    MODES[_primary] = _n
    for _a in _aliases:
        MODES[_a] = _n
MODE_NAMES = {n: p for n, (p, _, _) in MODE_TABLE.items()}

# name -> (low, high, unit, applies-to, what it does). Ranges mirror the
# clamps in r-net_hid.ino; the firmware is authoritative and will clip anyway.
SETTINGS = {
    "deadzone":  (0.0, 0.45, "", "all",
                  "centre dead zone, rescaled rather than clipped"),
    "expo":      (0.0, 0.95, "", "all",
                  "soft near centre, full authority at the edge"),
    "slew":      (0.5, 60.0, "units/s", "all",
                  "max rate of change; damps spasm spikes"),
    "mousegain": (40.0, 3000.0, "px/s", "mouse",
                  "cursor speed at full deflection"),
    "keyon":     (0.1, 0.95, "", "keyboard",
                  "press threshold"),
    "keyoff":    (0.05, 0.90, "", "keyboard",
                  "release threshold; forced below keyon"),
    "inverty":   (0.0, 1.0, "0/1", "all",
                  "flip the Y axis in every mode"),
}


def _fmt(v):
    return f"{v:g}"


def build_epilog():
    lines = ["commands:",
             "  mode <name|0-3>       switch the active interface",
             "  set <name> <value>    change a shaping parameter",
             "  get                   print the firmware's current config",
             "  cal                   recentre - hold the stick still",
             "  park                  shorthand for: mode park",
             "  watch                 live telemetry, Ctrl+C to stop",
             "  <anything else>       passed verbatim to the firmware "
             "(try HELP)",
             "",
             "modes:"]
    for n, (primary, aliases, blurb) in MODE_TABLE.items():
        alias = f"  aliases: {', '.join(aliases)}" if aliases else ""
        lines.append(f"  {n}  {primary:<9} {blurb:<38}{alias}")

    lines += ["", "settings:"]
    for name, (lo, hi, unit, scope, blurb) in SETTINGS.items():
        rng = f"{_fmt(lo)} .. {_fmt(hi)}"
        u = f" {unit}" if unit else ""
        lines.append(f"  {name:<10} {rng:<14}{u:<9} [{scope}] {blurb}")

    lines += [
        "",
        "examples:",
        "  hid.py                        interactive; live tuning while he drives",
        "  hid.py mode gamepad           switch to the gamepad interface",
        "  hid.py mode 0                 park it - drives nothing",
        "  hid.py set expo 0.45          more travel before it bites",
        "  hid.py set mousegain 900      faster cursor",
        "  hid.py set deadzone 0.09      wider centre if the stick drifts",
        "  hid.py cal                    recentre at rest",
        "  hid.py get                    read back everything",
        "  hid.py watch                  see shaped output live",
        "",
        "note: the port is exclusive. Leave this running and an upload fails",
        "with 'Access is denied', and the Teensy loader then reports success",
        "anyway.",
    ]
    return "\n".join(lines)


def check_setting(name, value):
    """Range-check locally so the error names the limit, rather than the
    firmware silently clamping and the caller wondering why nothing moved."""
    lo, hi, unit, _scope, _blurb = SETTINGS[name]
    try:
        v = float(value)
    except ValueError:
        return f"'{value}' is not a number"
    if v < lo or v > hi:
        u = f" {unit}" if unit else ""
        return f"{name} must be {_fmt(lo)} .. {_fmt(hi)}{u} (got {_fmt(v)})"
    return None


def find_port():
    cfg = Path(__file__).with_name("board.json")
    if cfg.exists():
        try:
            port = json.loads(cfg.read_text(encoding="utf-8-sig")).get(
                "monitorPort")
            if port:
                return port
        except (json.JSONDecodeError, OSError):
            pass
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid == 0x16C0:
            return p.device
    return ports[0].device if len(ports) == 1 else None


def open_port(name, baud=115200):
    try:
        return serial.Serial(name, baud, timeout=0.3)
    except serial.SerialException as e:
        sys.exit(f"Could not open {name}: {e}\n"
                 "Something else may be holding it (scope.py, a demo, a "
                 "terminal).")


def send(ser, line, settle=0.35):
    """Send a command and print whatever the firmware says back.

    Replies are prefixed '#'; telemetry is not, so the two are easy to
    separate on one wire.
    """
    ser.reset_input_buffer()
    ser.write((line.strip() + "\n").encode())
    ser.flush()
    out, deadline = [], time.time() + settle
    while time.time() < deadline:
        raw = ser.readline().decode("utf-8", "replace").strip()
        if raw.startswith("#") or raw.startswith("==="):
            out.append(raw.lstrip("# ").rstrip())
    for line_ in out:
        print(line_)
    return out


def parse_telemetry(raw):
    fields = {}
    for tok in raw.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            fields[k] = v
    return fields


def cmd_watch(ser):
    print("watching - Ctrl+C to stop")
    try:
        while True:
            raw = ser.readline().decode("utf-8", "replace").strip()
            if raw.startswith("#"):
                print("\n" + raw)
                continue
            f = parse_telemetry(raw)
            if "mode" not in f:
                continue
            m = MODE_NAMES.get(int(f.get("mode", 0)), "?")
            print(f"\r  mode {m:<9} sx {float(f.get('sx', 0)):+.3f}  "
                  f"sy {float(f.get('sy', 0)):+.3f}  "
                  f"sw {'DOWN' if f.get('sw') == '1' else 'up  '}  "
                  f"raw dx {int(f.get('dx', 0)):+5d} dy {int(f.get('dy', 0)):+5d}",
                  end="", flush=True)
    except KeyboardInterrupt:
        print("\nstopped.")


def repl(ser):
    print("R-Net multi-HID console.  '?' for the full syntax, 'quit' to leave.")
    print("modes: " + "  ".join(f"{n}={p}" for n, p in MODE_NAMES.items()) + "\n")

    stop = threading.Event()

    def reader():
        # Only surface replies; telemetry would scroll the prompt away.
        while not stop.is_set():
            try:
                raw = ser.readline().decode("utf-8", "replace").strip()
            except Exception:
                break
            if raw.startswith("#") or raw.startswith("==="):
                print("\r" + raw.lstrip("# ").rstrip() + "\n> ", end="",
                      flush=True)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    send(ser, "GET", 0.5)
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            low = line.lower()
            if low in ("quit", "exit", "q"):
                break
            if low in ("?", "help", "h"):
                # '?' is the local reference; 'HELP' still reaches the
                # firmware for its own terse list.
                print(build_epilog())
                continue
            parts = low.split()
            if parts[0] == "set" and len(parts) > 2 and parts[1] in SETTINGS:
                bad = check_setting(parts[1], parts[2])
                if bad:
                    print(bad)
                    continue
            if low == "watch":
                stop.set()
                time.sleep(0.35)
                cmd_watch(ser)
                stop.clear()
                t = threading.Thread(target=reader, daemon=True)
                t.start()
                continue
            ser.write((translate(line) + "\n").encode())
            ser.flush()
            time.sleep(0.15)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop.set()
    print("\nbye. (firmware keeps its current mode)")


def translate(line):
    """Let the friendly names through to the terse firmware protocol."""
    parts = line.split()
    if not parts:
        return line
    head = parts[0].lower()
    if head == "mode" and len(parts) > 1:
        key = parts[1].lower()
        if key in MODES:
            return f"MODE {MODES[key]}"
        return f"MODE {parts[1]}"
    return line


def main():
    ap = argparse.ArgumentParser(
        prog="hid.py",
        description=(
            "Mode switcher and live tuner for the R-Net multi-HID firmware.\n"
            "The joystick has no button, so mode changes come from here over "
            "the serial\nlink that stays live in every mode. Run with no "
            "arguments for an interactive\nsession."),
        epilog=build_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", metavar="COMn",
                    help="serial port (default: tools/board.json, then "
                         "auto-detect)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("args", nargs="*", metavar="COMMAND",
                    help="see the command list below")
    a = ap.parse_args()

    # Validate before touching the port. A typo should not need the port to be
    # free, and it frequently is not - a demo or scope.py will be holding it.
    head = a.args[0].lower() if a.args else ""
    if head == "mode":
        if len(a.args) < 2:
            sys.exit("usage: mode <name|0-3>\n  " +
                     "\n  ".join(f"{n}  {p}" for n, p in MODE_NAMES.items()))
        key = a.args[1].lower()
        if key not in MODES and not key.isdigit():
            sys.exit(f"unknown mode '{key}'\n  one of: "
                     f"{', '.join(sorted(MODES))}   (or 0-3)")
    elif head == "set":
        if len(a.args) < 3:
            sys.exit("usage: set <name> <value>\n  " +
                     "\n  ".join(f"{k:<10} {_fmt(v[0])} .. {_fmt(v[1])}"
                                 for k, v in SETTINGS.items()))
        name = a.args[1].lower()
        if name not in SETTINGS:
            sys.exit(f"unknown setting '{a.args[1]}'\n  one of: "
                     f"{', '.join(SETTINGS)}")
        bad = check_setting(name, a.args[2])
        if bad:
            sys.exit(bad)

    port = a.port or find_port()
    if not port:
        sys.exit("No serial port found. Pass --port COMn.")
    ser = open_port(port, a.baud)

    try:
        if not a.args:
            repl(ser)
        elif head == "watch":
            cmd_watch(ser)
        else:
            send(ser, translate(" ".join(a.args)))
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
