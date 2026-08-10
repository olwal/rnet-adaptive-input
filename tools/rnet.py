#!/usr/bin/env python3
"""Build, flash, monitor and launch, on any platform.

Wraps the `arduino-cli` that ships inside Arduino IDE 2.x so there is no
separate toolchain to install. Replaces the earlier PowerShell version, which
worked but hardcoded a Windows install path and could only run under
PowerShell.

  python tools/rnet.py doctor
  python tools/rnet.py flash --hid
  python tools/rnet.py hid mode mouse

or via the shim in the project root: `./rnet flash --hid` (macOS, Linux) and
`rnet.cmd flash --hid` (Windows).
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rnetport

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
BUILD_ROOT = ROOT / "build"
CONFIG = TOOLS / "board.json"

TEST_SKETCH = ROOT / "r-net_test"
HID_SKETCH = ROOT / "r-net_hid"
# The multi-HID sketch only works under a different USB descriptor set, and
# that lives in the FQBN. Building it under the plain FQBN silently produces a
# serial-only binary.
DEFAULT_FQBN = "teensy:avr:teensy30"
HID_FQBN = "teensy:avr:teensy30:usb=serialhid"

GREEN, CYAN, GREY, RED, OFF = "\033[32m", "\033[36m", "\033[90m", "\033[31m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    # Piped or captured output should not carry escape codes.
    GREEN = CYAN = GREY = RED = OFF = ""
elif os.name == "nt":
    try:                                    # enable ANSI on older consoles
        import ctypes
        k = ctypes.windll.kernel32
        k.SetConsoleMode(k.GetStdHandle(-11), 7)
    except Exception:
        GREEN = CYAN = GREY = RED = OFF = ""


def say(msg, colour=""):
    # Flushed because subprocesses write straight to the same terminal; without
    # this, buffered output arrives after the child's and the log reads
    # out of order.
    print(f"{colour}{msg}{OFF}" if colour else msg, flush=True)


class Fail(Exception):
    pass


# ------------------------------------------------------ arduino-cli ---------

def _ide_candidates():
    """Where Arduino IDE 2.x keeps its bundled arduino-cli, per platform."""
    system = platform.system()
    home = Path.home()
    inner = Path("lib") / "backend" / "resources"
    exe = "arduino-cli.exe" if system == "Windows" else "arduino-cli"

    roots = []
    if system == "Darwin":
        roots += [Path("/Applications/Arduino IDE.app/Contents/Resources/app"),
                  home / "Applications/Arduino IDE.app/Contents/Resources/app"]
    elif system == "Windows":
        for env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env)
            if base:
                roots += [Path(base) / "Programs" / "Arduino IDE" / "resources" / "app",
                          Path(base) / "Arduino IDE" / "resources" / "app"]
        roots += [Path(r"C:\Z\apps\dev\arduino-ide_2.3.4_Windows_64bit\resources\app")]
    else:
        roots += [home / ".arduinoIDE", Path("/opt/arduino-ide/resources/app"),
                  Path("/usr/local/share/arduino-ide/resources/app")]
    return [r / inner / exe for r in roots]


def find_cli():
    if os.environ.get("ARDUINO_CLI"):
        p = Path(os.environ["ARDUINO_CLI"])
        if p.exists():
            return str(p)
    for c in _ide_candidates():
        if c.exists():
            return str(c)
    on_path = shutil.which("arduino-cli")
    if on_path:
        return on_path
    raise Fail(
        "arduino-cli not found.\n"
        "  Install Arduino IDE 2.x (the CLI is bundled inside it), install\n"
        "  arduino-cli standalone, or set ARDUINO_CLI to its full path.")


def cli(*args, capture=False, check=True):
    cmd = [find_cli(), *[str(a) for a in args]]
    sys.stdout.flush()
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise Fail(f"arduino-cli {args[0]} failed:\n{r.stderr.strip()}")
        return r.stdout
    r = subprocess.run(cmd)
    if check and r.returncode != 0:
        raise Fail(f"arduino-cli {args[0]} failed (exit {r.returncode})")
    return ""


# ------------------------------------------------------ detection ----------

def detected_boards():
    """[(address, protocol, name, fqbn)] from `arduino-cli board list`."""
    parsed = json.loads(cli("board", "list", "--format", "json", capture=True)
                        or "{}")
    ports = parsed.get("detected_ports", parsed) if isinstance(parsed, dict) \
        else parsed
    out = []
    for p in ports or []:
        port = p.get("port", {})
        match = (p.get("matching_boards") or [{}])[0]
        out.append((port.get("address", "?"), port.get("protocol", "?"),
                    match.get("name", "Unknown"), match.get("fqbn", "")))
    return out


def resolve_fqbn(a):
    if a.fqbn:
        return a.fqbn
    if a.hid:
        return HID_FQBN
    cfg = rnetport.load_config(CONFIG)
    if cfg.get("fqbn"):
        return cfg["fqbn"]
    if os.environ.get("RNET_FQBN"):
        return os.environ["RNET_FQBN"]
    for addr, proto, name, fqbn in detected_boards():
        if fqbn:
            say(f"auto-detected board: {name} [{fqbn}]", GREY)
            return fqbn
    raise Fail("No board detected and no FQBN configured. "
               "Try `rnet boards`, then `rnet config`.")


def resolve_upload_port(a):
    """For Teensy this is a `teensy` pseudo-port, not the serial device, so
    prefer whichever entry actually identified a board."""
    if a.port:
        return a.port
    cfg = rnetport.load_config(CONFIG)
    boards = detected_boards()
    addresses = {addr for addr, *_ in boards}
    if cfg.get("port") and cfg["port"] in addresses:
        return cfg["port"]
    if os.environ.get("RNET_PORT"):
        return os.environ["RNET_PORT"]
    for addr, proto, name, fqbn in boards:
        if fqbn:
            return addr
    for addr, proto, name, fqbn in boards:
        if proto == "serial":
            return addr
    raise Fail("No upload port detected. Plug the board in, or pass --port.")


def resolve_serial_port(a):
    port = rnetport.find_port(a.port, "monitorPort", CONFIG)
    if not port:
        raise Fail("No serial port found. Ports visible now:\n"
                   + rnetport.describe_ports())
    return port


def resolve_sketch(a):
    if a.sketch:
        p = Path(a.sketch)
    elif a.hid:
        p = HID_SKETCH
    else:
        p = TEST_SKETCH
    if not p.exists():
        raise Fail(f"Sketch not found: {p}")
    return p.resolve()


def build_path(sketch, fqbn):
    return BUILD_ROOT / f"{sketch.name}.{fqbn.replace(':', '_').replace('/', '_')}"


FROZEN = getattr(sys, "frozen", False)


def python_exe():
    return sys.executable or "python3"


def run_tool(script, extra, port=None, port_flag="--port"):
    """Hand off to one of the sibling tools.

    Frozen builds cannot shell out: `sys.executable` is the bundled
    executable, not a Python interpreter, and the .py files are not on disk.
    So a packaged build imports the module and calls its `main()` in-process
    instead. Unfrozen, a subprocess keeps the tools isolated, which matters
    because several of them install signal handlers or open windows.
    """
    argv = list(extra) + ([port_flag, port] if port else [])
    module = Path(script).with_suffix("").as_posix().replace("/", ".")

    if FROZEN:
        import importlib
        try:
            mod = importlib.import_module(module)
        except ImportError as e:
            raise Fail(f"{module} is not bundled in this build ({e}).")
        saved = sys.argv
        sys.argv = [module] + argv
        try:
            return mod.main() or 0
        except SystemExit as e:
            return e.code or 0
        finally:
            sys.argv = saved

    path = TOOLS / script
    if not path.exists():
        raise Fail(f"{script} not found at {path}")
    sys.stdout.flush()
    return subprocess.call([python_exe(), str(path), *argv])


# ------------------------------------------------------ commands -----------

def cmd_boards(a):
    boards = detected_boards()
    if not boards:
        say("No boards detected.", RED)
        say("Serial ports visible:")
        print(rnetport.describe_ports())
        return 0
    print(f"{'Address':<26} {'Protocol':<9} {'Name':<22} FQBN")
    for addr, proto, name, fqbn in boards:
        print(f"{addr:<26} {proto:<9} {name:<22} {fqbn}")
    return 0


def cmd_build(a):
    sketch = resolve_sketch(a)
    fqbn = resolve_fqbn(a)
    out = build_path(sketch, fqbn)
    if a.clean and out.exists():
        say(f"cleaning {out}", GREY)
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    say(f"building {sketch.name} for {fqbn}", CYAN)
    cli("compile", "--fqbn", fqbn, "--build-path", out, *a.rest, sketch)
    say(f"build ok -> {out}", GREEN)
    return 0


def cmd_upload(a):
    sketch = resolve_sketch(a)
    fqbn = resolve_fqbn(a)
    out = build_path(sketch, fqbn)
    if not out.exists():
        raise Fail(f"No build at {out}. Run `build` or `flash` first.")
    port = resolve_upload_port(a)
    say(f"uploading to {port} [{fqbn}]", CYAN)
    cli("upload", "--fqbn", fqbn, "--port", port, "--input-dir", out,
        *a.rest, sketch)
    say("upload ok", GREEN)
    if a.hid:
        say("USB descriptor set changed, so the board will come back on a "
            "different serial port. Run `rnet config` to re-pin it.", GREY)
    return 0


def cmd_flash(a):
    cmd_build(a)
    return cmd_upload(a)


def cmd_monitor(a):
    port = resolve_serial_port(a)
    baud = a.baud or rnetport.load_config(CONFIG).get("baud", 115200)
    say(f"monitor {port} @ {baud}   (Ctrl+C to exit)", CYAN)
    cli("monitor", "--port", port, "--config", f"baudrate={baud}", check=False)
    return 0


def cmd_run(a):
    cmd_build(a)
    cmd_upload(a)
    return cmd_monitor(a)


def cmd_scope(a):
    return run_tool("scope.py", a.rest, a.port)


def cmd_hid(a):
    return run_tool("hid.py", a.rest, a.port)


def cmd_demo(a):
    return run_tool(str(Path("demos") / "run.py"), a.rest, a.port)


def cmd_cores(a):
    cli("core", "list")
    return 0


def cmd_cli(a):
    cli(*a.rest, check=False)
    return 0


def cmd_config(a):
    cfg = rnetport.load_config(CONFIG)
    changed = False
    if a.fqbn:
        cfg["fqbn"] = a.fqbn
        changed = True
    if a.port:
        cfg["port"] = cfg["monitorPort"] = a.port
        changed = True
    if a.baud:
        cfg["baud"] = a.baud
        changed = True

    if not changed:
        boards = detected_boards()
        for addr, proto, name, fqbn in boards:
            if fqbn:
                cfg["fqbn"], cfg["port"] = fqbn, addr
                break
        serial = rnetport.find_port(None, "___none___", CONFIG)
        if serial:
            cfg["monitorPort"] = serial
        cfg.setdefault("baud", 115200)

    rnetport.save_config(cfg, CONFIG)
    say(f"wrote {CONFIG}", GREEN)
    print(json.dumps(cfg, indent=2, sort_keys=True))
    return 0


def cmd_doctor(a):
    say(f"platform    : {platform.system()} {platform.release()} "
        f"({platform.machine()})")
    say(f"python      : {sys.version.split()[0]}  {sys.executable}")
    try:
        found = find_cli()
        say(f"arduino-cli : {found}")
        print(cli("version", capture=True).strip())
    except Fail as e:
        say(f"arduino-cli : NOT FOUND", RED)
        say(str(e), GREY)
    print()
    say(f"project     : {ROOT}")
    say(f"build root  : {BUILD_ROOT}")
    say(f"config      : {CONFIG}"
        f"{'' if CONFIG.exists() else '   (not created yet)'}")
    cfg = rnetport.load_config(CONFIG)
    if cfg:
        print(f"              {json.dumps(cfg, sort_keys=True)}")
    print()
    try:
        import serial  # noqa: F401
        say("pyserial    : ok")
    except ImportError:
        say("pyserial    : MISSING  (python -m pip install pyserial)", RED)
    print()
    say("--- serial ports ---")
    print(rnetport.describe_ports())
    resolved = rnetport.find_port(None, "monitorPort", CONFIG)
    say(f"resolved port: {resolved or 'none'}")
    print()
    try:
        say("--- installed cores ---")
        cli("core", "list")
        print()
        say("--- detected boards ---")
        cmd_boards(a)
    except Fail as e:
        say(str(e), GREY)
    return 0


COMMANDS = {
    "boards": (cmd_boards, "list attached boards and ports"),
    "build": (cmd_build, "compile the sketch"),
    "upload": (cmd_upload, "upload the last build"),
    "flash": (cmd_flash, "build then upload"),
    "run": (cmd_run, "build, upload, then monitor"),
    "monitor": (cmd_monitor, "raw serial monitor"),
    "scope": (cmd_scope, "live ASCII scope (extra flags pass through)"),
    "hid": (cmd_hid, "multi-HID mode switcher and tuner; no args = interactive"),
    "demo": (cmd_demo, "launch a demo; no name lists them"),
    "cores": (cmd_cores, "list installed board cores"),
    "config": (cmd_config, "pin board and port to tools/board.json"),
    "doctor": (cmd_doctor, "toolchain, ports, cores and detected boards"),
    "cli": (cmd_cli, "pass arguments straight to arduino-cli"),
}


def main(argv=None):
    epilog = ["commands:"]
    for name, (_, blurb) in COMMANDS.items():
        epilog.append(f"  {name:<9} {blurb}")
    epilog += [
        "",
        "examples:",
        "  rnet doctor                    check the toolchain and ports",
        "  rnet flash --hid               build and upload the multi-HID sketch",
        "  rnet config                    pin whatever is plugged in",
        "  rnet hid mode mouse            switch the active interface",
        "  rnet demo labyrinth            run the marble game",
        "  rnet build --warnings all      unknown flags go to arduino-cli",
        "",
        "resolution order for board and port:",
        "  --fqbn / --port  >  tools/board.json  >  $RNET_FQBN / $RNET_PORT",
        "  >  auto-detect. A pinned port that is not present is ignored, so a",
        "  config written on one machine still works on another.",
    ]
    p = argparse.ArgumentParser(
        prog="rnet", description=__doc__.split("\n\n")[0],
        epilog="\n".join(epilog),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="help",
                   help="one of: " + ", ".join(COMMANDS))
    p.add_argument("--sketch")
    p.add_argument("--fqbn")
    p.add_argument("--port")
    p.add_argument("--baud", type=int, default=0)
    p.add_argument("--clean", action="store_true")
    p.add_argument("--hid", action="store_true",
                   help="target r-net_hid and the serialhid descriptor set")
    a, rest = p.parse_known_args(argv)
    a.rest = rest

    if a.command in ("help", "-h", "--help"):
        p.print_help()
        return 0
    if a.command not in COMMANDS:
        say(f"unknown command: {a.command}\n", RED)
        p.print_help()
        return 2
    try:
        return COMMANDS[a.command][0](a) or 0
    except Fail as e:
        say(str(e), RED)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
