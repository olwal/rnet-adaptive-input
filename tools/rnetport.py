"""Board configuration and serial port discovery, shared by every host tool.

There were four near-identical copies of this, and all four had the same bug:
a pinned port from `board.json` was returned without checking it still exists.
A config written on Windows names `COM34`, which does not exist on macOS or
Linux, so the tools failed instead of falling back to the scan that would have
found the board immediately.
"""

import json
from pathlib import Path

PJRC_VID = 0x16C0
CONFIG = Path(__file__).resolve().parent / "board.json"


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
