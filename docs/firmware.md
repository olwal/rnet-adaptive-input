# Firmware

Two sketches: a bring-up build that streams telemetry, and a multi-HID build that presents as a gamepad, mouse and keyboard at once.

## Test sketch

The source of truth is **`r-net_test/r-net_test.ino`**. Read it there rather than
maintaining a second copy here. Pin assignments only:

```cpp
const uint8_t PIN_X    = A7;   // pad 21 - joystick pin 2 (DIR)   via 100k/68k divider
const uint8_t PIN_Y    = A8;   // pad 22 - joystick pin 1 (SPEED) via 100k/68k divider
const uint8_t PIN_VREF = A9;   // pad 23 - joystick pin 3 (REF)   via 100k/68k divider
const uint8_t PIN_SW   = 2;    // pad 2  - 3.5mm jack tip = D-sub pin 6 (MODE)
```

What it does: averages 64 samples of X, Y and Vref at startup to establish
`x_center`/`y_center` (which absorbs the small static offset from the joystick's
mismatched internal series resistors), then streams
`X / Y / R / dx / dy / sw` over USB serial at 115200, 20 times a second.

## Multi-HID mode

`r-net_hid/r-net_hid.ino` turns the joystick into a USB **gamepad, mouse and
keyboard at once**, with the serial link still live underneath as telemetry and
control.

```
rnet flash --hid           # r-net_hid + the serialhid descriptor set
rnet hid                  # interactive switcher / tuner
rnet hid mode gamepad
rnet hid set expo 0.45
rnet hid watch
```

USB type is a **compile-time** choice, so all five interfaces (CDC status, CDC
data, keyboard, mouse, joystick) enumerate together and stay enumerated. "Mode"
selects which one is actively driven, not which exists. Verified against the
core: the gamepad is the 12-byte report, with 6 axes at 10-bit, 32 buttons and one hat.

| Mode | | |
|---|---|---|
| 0 | `parked` | drives nothing; the power-on default |
| 1 | `gamepad` | absolute axes, DirectInput |
| 2 | `mouse` | velocity mapping |
| 3 | `keyboard` | arrow keys |

### Design notes

**It boots parked.** A stick that can move the cursor and type is a device that
can do arbitrary damage to the host. This one drifts a few counts at rest, and a
loose connection could park it at full deflection. Booting inert costs nothing
and is the difference between a rig you can leave plugged in and one you can't.

**Every mode change tears down explicitly.** The interfaces stay live when you
leave a mode, so a key held at the moment of a switch stays held at the OS level
forever, and gamepad axes hold their last value. `neutralise()` releases all
keys, zeroes the mouse, centres all six axes and clears all 32 buttons.

**Mouse mode carries a sub-pixel accumulator.** `Mouse.move` takes `int8_t`.
Without carrying the fractional remainder between ticks, anything under one
pixel per tick truncates to zero and slow, precise movement becomes impossible:
the cursor does not move until it is pushed hard.

**Keyboard mode has separate on/off thresholds** (0.55 / 0.40). One threshold
gives you key chatter at the boundary, machine-gunning keydown/keyup at loop
rate.

**One shaping layer, before the dispatch.** Deadzone, expo and slew limit
produce a clean −1..1 pair that all three consumers share, so there is one thing
to tune rather than three that drift apart. Tunable live over serial while the
user is actually driving.

### Serial protocol

Telemetry keeps the exact format `scope.py` and `crosshair.py` already parse and
appends `mode=`, `sx=`, `sy=`. Their regexes use `search`, so trailing fields are
free. Commands are line-based ASCII, typable from any terminal:

```
MODE 0..3 | PARK | CAL | GET | HELP
SET deadzone|expo|slew|mousegain|keyon|keyoff|inverty <value>
KEYS [arrows|wasd|ijkl|media] | KEYS <up|down|left|right> <key>
SAVE | LOAD | DEFAULTS | BOOT 0..3
```

### Persisting settings

`SAVE` writes the mode, the shaping parameters and the key mapping to EEPROM,
guarded by a magic number and a version so a blank EEPROM is not read as
settings, and clamped on load so a corrupt one cannot produce a stick that
never reports centre.

`BOOT <mode>` sets which mode the board enters at power-on. It defaults to
`parked` and only changes if asked, which preserves the property above: nothing
drives the host until someone opts in.

```
rnet hid boot mouse
rnet hid save
```

That combination is what makes the device usable on a host that cannot talk to
the serial port. iPadOS claims the CDC interface before any app can reach it,
so nothing on an iPad can send a `MODE` command; configure it from a computer
first and it arms itself. `rnet hid boot park` and `save` undoes it.

### Gamepad mode is DirectInput, not XInput

Teensy's gamepad is a generic HID device, so Windows sees it through
**DirectInput**. A lot of modern games only support **XInput** and will simply
not see the controller. It appears in Windows' own game-controller panel and
then appears to do nothing.

Cheapest workaround is to launch the game through **Steam**, which remaps any
generic pad to a virtual Xbox controller with no code at all. Otherwise ViGEmBus
with a feeder, or vJoy. Nothing to fix on the firmware side; the report
descriptor is correct.

### Build note

The HID sketch needs `teensy:avr:teensy30:usb=serialhid`. Building it under the
plain `teensy:avr:teensy30` FQBN succeeds and produces a serial-only binary,
which is a confusing way to find out. `--hid` selects both the sketch and the
descriptor set together; build outputs are keyed by FQBN so the two variants
don't collide.

**Switching USB type changes the COM port.** A different descriptor set is a
different USB device, so Windows enumerates it fresh and assigns a new port.
COM28 became COM34 here. Everything that reads `tools/board.json` (the demos,
`scope.py`, `crosshair.py`, `hid.py`) then points at a port that no longer
exists. Run `rnet config` after the first HID flash to re-pin it.

To confirm the flash actually landed, check the **PID** rather than trusting the
uploader, which reports success even when it fell back to waiting for the
button:

Windows:

```
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.DeviceID -like "*VID_16C0*" } |
  Select-Object Name, DeviceID
```

macOS:

```
system_profiler SPUSBDataType | grep -A6 -i teensy
```

Linux:

```
lsusb -d 16c0:
```

`PID_0483` is the serial-only build. **`PID_0487` is serialhid**, and you should
see a composite device with an HID Keyboard, an HID mouse, and an
*HID-compliant game controller* alongside the COM port.

Verified on hardware: telemetry runs at 100 Hz and every line still matches the
regex `scope.py` and `crosshair.py` already use, so the new `mode=`, `sx=`, `sy=`
fields cost no compatibility.

---

[Back to the README](../README.md)
