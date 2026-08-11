# Host tooling

Building and flashing without a separate toolchain, plus the scope, the shaping harness, and window/monitor control.

## Command-line toolchain

No separate toolchain install is needed. `tools/rnet.py` wraps the `arduino-cli`
that ships inside Arduino IDE 2.x, locating it per platform and falling back to
one on `PATH`. Set `ARDUINO_CLI` to override.

```
python tools/rnet.py doctor    # toolchain, paths, ports, cores, boards
python tools/rnet.py boards    # what is plugged in right now
python tools/rnet.py build     # compile
python tools/rnet.py flash     # compile and upload
python tools/rnet.py monitor   # serial monitor at 115200 (Ctrl+C to exit)
python tools/rnet.py run       # compile, upload, monitor
```

Shims in the project root shorten that to `./rnet doctor` on macOS and Linux
and `rnet.cmd doctor` on Windows. The rest of this page uses the long form,
which works everywhere.

`doctor` is the one to run first on a new machine: it reports the platform, the
Python and `arduino-cli` it found, whether `pyserial` is installed, every serial
port it can see, and which one it would pick.

Board and port auto-detect from whatever is attached. To pin them:

```
python tools/rnet.py config                                # save what is detected
python tools/rnet.py config --fqbn arduino:avr:uno --port COM5
```

Resolution order is `--fqbn`/`--port`, then `tools/board.json`, then
`RNET_FQBN`/`RNET_PORT`, then auto-detect. **A pinned port that is not present
is ignored rather than fatal**, so a `board.json` written on Windows naming
`COM34` still works on a Mac, where the same board appears as
`/dev/cu.usbmodem*`.

Unrecognised trailing arguments pass through to `arduino-cli`
(`python tools/rnet.py build --warnings all`), and
`python tools/rnet.py cli <args>` is a raw passthrough.

Sketch lives in `r-net_test/r-net_test.ino` (Arduino requires the folder name to
match). Build artifacts go to `build/<sketch>.<fqbn>/`, one directory per target.
Verified compiling for both `teensy:avr:teensy30` and `arduino:avr:uno`.

### Standalone binaries

`rnet` can be packaged into a single ~8 MB executable that runs without a
Python installation, and CI builds one per platform on a tagged release. How
that works, what the binary can and cannot do outside a checkout, and how to
publish one: [builds and releases](releases.md).

### Host-side tools

Python 3 with `pyserial` and `pygame` (`python -m pip install pyserial pygame`).

**`tools/scope.py`**: live ASCII scope. Raw counts, ADC volts, reconstructed
joystick volts, and two centre-zero bargraphs.

```
rnet scope                 # live display, Ctrl+C to exit
rnet scope --once          # one frame, scriptable snapshot
rnet scope --sample 10     # N parsed lines, non-interactive
rnet scope --analyze 20    # capture + crosstalk statistics
```

`--analyze` is the diagnostic: sweep **one** axis fully, leave the other centred,
and it reports the leak into the idle axis plus `dR/d(swept)`. Under 2 % leak means
the axes are independent and any Vref movement is common-mode that cancels in
`dx`/`dy`.

**`tools/crosshair.py`**: fullscreen crosshair demo, absolute mapping (stick centre
= screen centre, full deflection = screen edge). The stick self-centres so the
crosshair springs home on release.

```
python tools/crosshair.py
python tools/crosshair.py --windowed --deadzone 0.06 --expo 0.4
```

Keys: `Esc` quit, `D` debug overlay, `T` trail, `C` recentre, `[` `]` expo,
`-` `+` sensitivity, `F` fullscreen toggle. Serial runs on its own thread so
rendering never stalls on the port; samples are interpolated between frames.

**Only one process can hold the COM port.** Leaving `scope.py` running blocks
uploads. The Teensy reboot request fails with `Access is denied` and the upload
then reports success anyway. If a flash seems not to have taken, check for a
stray viewer first.

## Display: windowed, fullscreen, and which monitor

Shared by every demo (they all sit on `engine.py`), and by `crosshair.py`.

| Key | |
|---|---|
| `F11` or `F` | toggle fullscreen / windowed |
| `M` | next monitor (`Shift+M` for previous) |

```
rnet demo labyrinth --list-monitors        # what's attached
rnet demo labyrinth --monitor 1            # fullscreen on the second screen
rnet demo labyrinth --windowed             # windowed on the current screen
rnet demo labyrinth --windowed --width 1600 --height 900
rnet demo labyrinth --exclusive            # true fullscreen, not borderless
```

Fullscreen defaults to **borderless**, which is far more reliable across two
screens and alt-tabs instantly; `--exclusive` gives a real mode switch if you
want one. Windows are resizable, and the demos re-read their size every frame,
so dragging an edge works too.

**Order matters in the implementation.** raylib's fullscreen and borderless
modes both act on whichever monitor the window is currently *on*, so the window
has to be moved to the target monitor first and switched second. Doing it the
other way round leaves the window fullscreen on the wrong screen.

Screenshots force windowed mode: a display switch mid-capture is a reliable way
to get a black frame.

---

[Back to the README](../README.md)
