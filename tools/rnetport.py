"""Board configuration and serial port discovery, shared by every host tool.

There were four near-identical copies of this, and all four had the same bug:
a pinned port from `board.json` was returned without checking it still exists.
A config written on Windows names `COM34`, which does not exist on macOS or
Linux, so the tools failed instead of falling back to the scan that would have
found the board immediately.
"""

import json
import os
import sys
from pathlib import Path

PJRC_VID = 0x16C0
FROZEN = getattr(sys, "frozen", False)

# Markers that identify a checkout of this project.
_MARKERS = ("tools", "r-net_test")


def find_checkout(start=None):
    """Walk upward looking for a project checkout, or None."""
    if start is None:
        start = Path(sys.executable).resolve().parent if FROZEN else \
            Path(__file__).resolve().parent
    for base in (Path.cwd(), Path(start)):
        for d in (base, *base.parents):
            if all((d / m).exists() for m in _MARKERS):
                return d
    return None


def user_config_dir():
    """Per-user config location, for a released binary run outside a checkout."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "rnet"


def config_path():
    """Where board.json lives.

    In a checkout it sits in tools/ next to this file. A frozen build cannot
    use __file__ for this: PyInstaller unpacks to a temporary directory, so
    the path would resolve inside %TEMP% and the config would vanish between
    runs. Prefer a checkout if the binary is being run inside one, otherwise
    fall back to the user's config directory.
    """
    if not FROZEN:
        return Path(__file__).resolve().parent / "board.json"
    root = find_checkout()
    if root:
        return root / "tools" / "board.json"
    d = user_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "board.json"


CONFIG = config_path()


def load_config(path=CONFIG):
    """Read board.json, tolerating a BOM from older PowerShell-written files."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_config(cfg, path=CONFIG):
    Path(path).write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")


def available_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return list(list_ports.comports())


def find_port(explicit=None, config_key="monitorPort", path=CONFIG):
    """Resolve a serial port.

    Order: explicit argument, then the pinned value in board.json *if it is
    actually present*, then the first PJRC device, then a lone serial port.
    Returns None if nothing looks right.
    """
    if explicit:
        return explicit

    ports = available_ports()
    names = {p.device for p in ports}

    pinned = load_config(path).get(config_key)
    if pinned and pinned in names:
        return pinned
    # A pinned port that is not present is stale rather than fatal: fall
    # through and scan, which is what makes a config portable between hosts.

    for p in ports:
        if p.vid == PJRC_VID:
            return p.device

    if len(ports) == 1:
        return ports[0].device
    return None


def describe_ports():
    """Human-readable list, for error messages and `doctor`."""
    ports = available_ports()
    if not ports:
        return "  (no serial ports found)"
    out = []
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid else "----"
        pid = f"{p.pid:04X}" if p.pid else "----"
        tag = "  <- PJRC" if p.vid == PJRC_VID else ""
        out.append(f"  {p.device:<24} VID:PID {vid}:{pid}  "
                   f"{(p.description or '').strip()}{tag}")
    return "\n".join(out)
