"""Best times per level, persisted next to the demo.

Keyed by level *name* rather than index, so reordering or inserting levels
doesn't silently reassign somebody's records to the wrong course.
"""

import json
from pathlib import Path

PATH = Path(__file__).with_name("scores.json")


def load():
    if PATH.exists():
        try:
            return json.loads(PATH.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save(data):
    try:
        PATH.write_text(json.dumps(data, indent=2, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        pass          # a read-only disk shouldn't take the game down


def best(data, name):
    return data.get(name)


def record(data, name, seconds):
    """Store the time if it beats the record. True if it's a new best."""
    current = data.get(name)
    if current is None or seconds < current:
        data[name] = round(seconds, 3)
        save(data)
        return True
    return False


def clear(data):
    data.clear()
    save(data)


def fmt(seconds):
    if seconds is None:
        return "--"
    if seconds >= 60:
        return f"{int(seconds // 60)}:{seconds % 60:05.2f}"
    return f"{seconds:.2f}"
