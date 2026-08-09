#!/usr/bin/env python3
"""Launcher for the R-Net joystick 3D demos.

  python tools/demos/run.py                 # list them
  python tools/demos/run.py labyrinth       # fullscreen, joystick if present
  python tools/demos/run.py labyrinth --windowed --keyboard --monitor 1

Every demo falls back to arrow keys / WASD when no joystick is found, so they
can be shown on any machine.
"""

import importlib
import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEMOS = {
    "labyrinth": "tilt a board, roll the ball, avoid the holes",
}

# Other prototypes live in _archive/ and are not published: a perspective
# puzzle, a rally stage, and four earlier vehicle demos. They run, but none of
# them are finished enough to put in front of anyone, and a half-polished demo
# is worse than no demo.


def usage():
    print(__doc__)
    print("Demos:")
    for name, blurb in DEMOS.items():
        print(f"  {name:<11} {blurb}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        usage()
        return 0
    name = sys.argv[1]
    if name not in DEMOS:
        print(f"Unknown demo: {name}\n")
        usage()
        return 1

    module = importlib.import_module(name)
    from engine import Demo, base_parser

    cls = next(
        (obj for _, obj in inspect.getmembers(module, inspect.isclass)
         if issubclass(obj, Demo) and obj is not Demo
         and obj.__module__ == module.__name__),
        None)
    if cls is None:
        print(f"No Demo subclass found in {name}.py")
        return 1

    args = base_parser(module.__doc__).parse_args(sys.argv[2:])
    cls(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
