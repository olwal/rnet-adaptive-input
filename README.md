# R-net Adaptive Input: Interface to use Permobil joystick from microcontroller and computer. 

Reading a Permobil R-Net specialty joystick (an Omni-compatible SID) from a
Teensy, and presenting it to a host as an ordinary USB input device.

https://github.com/user-attachments/assets/6f5dde21-41e2-4d8e-a4ac-a26c28fd4ac4

![The bench build: R-Net joystick on a D-sub breakout, dividers, and a Teensy 3.0](docs/diagram.jpg)

These joysticks are proportional, well built and widely available secondhand,
but they use a proprietary analogue interface and are designed to talk only to
their own controller. This project documents the connector, gets the signals
into a microcontroller safely, and exposes the result as a gamepad, mouse or
keyboard.

> ### Disclaimer
>
> A personal experiment with a salvaged joystick on a bench supply, published
> as-is and used entirely at your own risk.
>
> **This is not intended for use with a real wheelchair or any live mobility
> system.** It is not a product, it is not certified, and it has not been tested
> for safety. Nothing here should be connected to equipment anyone depends on.
>
> No warranty of any kind. See [LICENSE](LICENSE).

## Status

Working end to end. The pinout is verified on physical hardware against three
independent sources, the dividers are on a breadboard, a Teensy 3.0 reads all
three analogue channels at about 100 Hz, and a multi-HID firmware presents as a
gamepad, mouse and keyboard simultaneously.

Measured Vref was about 698 counts against 700 predicted. The reconstructed
joystick voltage came out at 5.58 to 5.67 V against the meter's 5.6 V.

## Circuit

```
   joystick pin 7  ── [33 Ω] ─────────────  +12 V (bench supply)
   joystick pin 8  ───────────────────────  GND  (tied to Teensy GND)

   joystick pin 1 (Y) ──┬── 100 kΩ ──┬──►  A7  (pad 21)
                        │            │
                        │           68 kΩ
                        │            │
                        │           GND

   joystick pin 2 (X) ──┬── 100 kΩ ──┬──►  A8  (pad 22)
                        │            │
                        │           68 kΩ
                        │            │
                        │           GND

   joystick pin 3 (Vref) ┬── 100 kΩ ──┬──► A9  (pad 23)
                         │            │
                         │           68 kΩ
                         │            │
                         │           GND

   3.5 mm jack tip     ───────────────────► D2 (INPUT_PULLUP, pad 2)
   3.5 mm jack sleeve  ───────────────────► GND
```

The joystick outputs swing between 4.5 and 6.8 V, centred on a 5.6 V reference
it generates itself. The Teensy 3.0 runs at 3.3 V and its pins are not 5 V
tolerant, so each output is divided down before it reaches an ADC input. The
33 Ω resistor in the supply leg acts as a soft fuse. Full derivation and the
expected ADC values are in [wiring](docs/wiring.md).

## Documentation

| Page | Contents |
|---|---|
| [Hardware and pinout](docs/hardware.md) | Identifying the joystick, the verified 9-pin D-sub pinout, supporting measurements, bring-up |
| [Wiring the Teensy](docs/wiring.md) | Divider design for a 3.3 V ADC, pad map, expected readings, known issues |
| [Firmware](docs/firmware.md) | The bring-up sketch, the multi-HID build, and the serial protocol |
| [Host tooling](docs/tooling.md) | Build, flash, monitor and tune without installing a toolchain |
| [Demo: tilt labyrinth](docs/demo-labyrinth.md) | A test application driving the full chain |
| [Single-stick game design](docs/joystick-only-games-brief.md) | Notes on interaction design for one axis pair with no buttons |
| [Open questions and roadmap](docs/roadmap.md) | Unresolved items and planned work |

## Quick start

Requires a Teensy 3.0, six resistors and a bench supply.

1. Build the circuit above. See [wiring](docs/wiring.md) for the pad map.
2. Flash the bring-up firmware and watch the values:

   ```
   ./rnet.cmd flash          # Windows
   python tools/scope.py     # any platform
   ```

3. For USB HID output, flash the multi-HID build. See
   [firmware](docs/firmware.md).

The Python tools (`scope.py`, `crosshair.py`, `hid.py` and the demo) run on any
platform. The `rnet` build wrapper is currently PowerShell only; see
[roadmap](docs/roadmap.md).

## Requirements

**Firmware.** Arduino IDE 2.x with Teensyduino. No separate toolchain install is
needed; the tooling drives the `arduino-cli` bundled inside the IDE.

**Host tools.** Python 3.9 or later with `pyserial`. The demo additionally
requires `raylib`, `numpy` and `scipy`. `crosshair.py` requires `pygame`.

```
python -m pip install pyserial pygame raylib numpy scipy
```

## References

- **CustomSID by Bob Paradiso.** A custom SID emulator, driving an Omni from
  alternative inputs. This project does the inverse, reading the real joystick,
  but the connector pinout is the same and the KiCad schematic was used for
  pin-by-pin verification.
  [Write-up](https://bobparadiso.com/2018/10/09/custom-proportional-power-wheelchair-drive-controls/),
  including voltage specifications (Vref at 50 % of 12 V, ±1.2 V deflection).
- **PG Drives R-Net Omni Technical Manual**, document `SK78813-07`. The SID port
  section documents the 9-way D-type connector. Not redistributed here, as it is
  PG Drives / Curtiss-Wright copyright.
- **Teensy 3.0 pinout cards.** <https://www.pjrc.com/teensy/pinout.html>
  (`card5a` and `card5b`).

## License

MIT. See [LICENSE](LICENSE).
