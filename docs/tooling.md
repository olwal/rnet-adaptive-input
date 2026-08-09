# Host tooling

Building and flashing without a separate toolchain, plus the scope, the shaping harness, and window/monitor control.

## Command-line toolchain

No separate toolchain install needed — `tools/rnet.ps1` wraps the `arduino-cli`
that ships inside Arduino IDE 2.x at
`C:/Z/apps/dev/arduino-ide_2.3.4_Windows_64bit/resources/app/lib/backend/resources/arduino-cli.exe`.

```powershell
.\rnet.cmd doctor      # toolchain, paths, installed cores, detected boards
.\rnet.cmd boards      # what's plugged in right now
.\rnet.cmd build       # compile
.\rnet.cmd flash       # compile + upload
.\rnet.cmd monitor     # serial monitor @ 115200 (Ctrl+C to exit)
.\rnet.cmd run         # compile + upload + monitor
```

`rnet.cmd` is a shim for cmd/Git Bash; call `tools\rnet.ps1` directly from PowerShell.

Board and port auto-detect from whatever is attached. To pin them:

```powershell
.\rnet.cmd config                          # save currently-detected board/port
.\rnet.cmd config -Fqbn arduino:avr:uno -Port COM5
```

Resolution order is `-Fqbn`/`-Port` → `tools/board.json` → `$env:RNET_FQBN`/`$env:RNET_PORT` → auto-detect.
Unrecognised trailing arguments pass through to `arduino-cli` (`.\rnet.cmd build --warnings all`),
and `.\rnet.cmd cli <args>` is a raw passthrough for anything not wrapped.

Sketch lives in `r-net_test/r-net_test.ino` (Arduino requires the folder name to
match). Build artifacts go to `build/<sketch>.<fqbn>/`, one directory per target.
Verified compiling for both `teensy:avr:teensy30` and `arduino:avr:uno`.

### Host-side tools

Python 3 with `pyserial` and `pygame` (`python -m pip install pyserial pygame`).

**`tools/scope.py`** — live ASCII scope. Raw counts, ADC volts, reconstructed
joystick volts, and two centre-zero bargraphs.

```powershell
.\rnet.cmd scope                 # live display, Ctrl+C to exit
.\rnet.cmd scope --once          # one frame, scriptable snapshot
.\rnet.cmd scope --sample 10     # N parsed lines, non-interactive
.\rnet.cmd scope --analyze 20    # capture + crosstalk statistics
```

`--analyze` is the diagnostic: sweep **one** axis fully, leave the other centred,
and it reports the leak into the idle axis plus `dR/d(swept)`. Under 2 % leak means
the axes are independent and any Vref movement is common-mode that cancels in
`dx`/`dy`.

**`tools/crosshair.py`** — fullscreen crosshair demo, absolute mapping (stick centre
= screen centre, full deflection = screen edge). The stick self-centres so the
crosshair springs home on release.

```powershell
python tools\crosshair.py
python tools\crosshair.py --windowed --deadzone 0.06 --expo 0.4
```

Keys: `Esc` quit, `D` debug overlay, `T` trail, `C` recentre, `[` `]` expo,
`-` `+` sensitivity, `F` fullscreen toggle. Serial runs on its own thread so
rendering never stalls on the port; samples are interpolated between frames.

**Only one process can hold the COM port.** Leaving `scope.py` running blocks
uploads — the Teensy reboot request fails with `Access is denied` and the upload
then *reports success anyway*. If a flash seems not to have taken, check for a
stray viewer first.

## Display: windowed, fullscreen, and which monitor

Shared by every demo (they all sit on `engine.py`), and by `crosshair.py`.

| Key | |
|---|---|
| `F11` or `F` | toggle fullscreen / windowed |
| `M` | next monitor (`Shift+M` for previous) |

```powershell
.\rnet.cmd demo rally --list-monitors        # what's attached
.\rnet.cmd demo rally --monitor 1            # fullscreen on the second screen
.\rnet.cmd demo rally --windowed             # windowed on the current screen
.\rnet.cmd demo rally --windowed --width 1600 --height 900
.\rnet.cmd demo rally --exclusive            # true fullscreen, not borderless
```

Fullscreen defaults to **borderless**, which is far more reliable across two
screens and alt-tabs instantly; `--exclusive` gives a real mode switch if you
want one. Windows are resizable, and the demos re-read their size every frame,
so dragging an edge works too.

**Order matters in the implementation.** raylib's fullscreen and borderless
modes both act on whichever monitor the window is currently *on*, so the window
has to be moved to the target monitor first and switched second — doing it the
other way round leaves you fullscreen on the wrong screen.

Screenshots force windowed mode: a display switch mid-capture is a reliable way
to get a black frame.

---

[← Back to the README](../README.md)
