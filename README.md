# rnet-adaptive-input

Reading a Permobil R-Net specialty joystick — an Omni-compatible SID — from a
Teensy, and turning it into an ordinary USB input device.

These joysticks are proportional, well built, and easy to find secondhand, but
they speak a proprietary analogue interface and only to their own controller.
This project documents the connector, gets the signals into a microcontroller
safely, and presents the result to a host as a gamepad, mouse or keyboard.

> ### Disclaimer
>
> A personal experiment with a salvaged joystick on a bench supply, published
> as-is and used entirely at your own risk.
>
> **This is not intended for use with a real wheelchair or any live mobility
> system.** It is not a product, it is not certified, and it has not been tested
> for safety. Nothing here should be connected to equipment anyone depends on.
>
> No warranty of any kind — see [LICENSE](LICENSE).

![The bench build: R-Net joystick on a D-sub breakout, dividers, and a Teensy 3.0](docs/diagram.jpg)

## Status

Working end to end. Pinout verified on physical hardware against three
independent sources, dividers on a breadboard, a Teensy 3.0 reading all three
analogue channels at ~100 Hz, and a multi-HID firmware presenting as a gamepad,
mouse and keyboard simultaneously.

Measured Vref sat at ~698 counts against ~700 predicted; the reconstructed
joystick voltage came out at 5.58–5.67 V against the meter's 5.6 V.

## Documentation

| | |
|---|---|
| [Hardware and pinout](docs/hardware.md) | Identifying the joystick, the verified 9-pin D-sub pinout, the measurements behind it, and bring-up |
| [Wiring the Teensy](docs/wiring.md) | Divider design for a 3.3 V ADC, pad map, expected readings, field notes |
| [Firmware](docs/firmware.md) | The bring-up sketch and the multi-HID build, plus the serial protocol |
| [Host tooling](docs/tooling.md) | Build, flash, monitor and tune without installing a toolchain |
| [Demo: tilt labyrinth](docs/demo-labyrinth.md) | A worked example driving something real |
| [Single-stick game design](docs/joystick-only-games-brief.md) | Design notes on what works with one axis pair and no buttons |
| [Open questions and roadmap](docs/roadmap.md) | What is unresolved, and what comes next |

## Quick start

You need a Teensy 3.0, six resistors, and a bench supply.

1. Wire it up — [wiring](docs/wiring.md). The dividers matter: the joystick
   swings to 6.8 V and the Teensy's pins are not 5 V tolerant.
2. Flash and watch the values:

   ```
   ./rnet.cmd flash          # Windows
   python tools/scope.py     # any platform
   ```

3. For USB HID, flash the multi-HID build — [firmware](docs/firmware.md).

The Python tools (`scope.py`, `crosshair.py`, `hid.py`, the demo) run anywhere.
The `rnet` build wrapper is currently PowerShell only; see
[roadmap](docs/roadmap.md).

## Requirements

- **Firmware** — Arduino IDE 2.x with Teensyduino. No separate toolchain
  install; the tooling drives the `arduino-cli` bundled inside the IDE.
- **Host tools** — Python 3.9+ with `pyserial`. The demo additionally needs
  `raylib`, `numpy` and `scipy`; `crosshair.py` needs `pygame`.

  ```
  python -m pip install pyserial pygame raylib numpy scipy
  ```

## Key references

- **CustomSID by Bob Paradiso** — a custom SID *emulator* (drives an Omni from
  alternative inputs). This project does the inverse, reading the real joystick,
  but the connector pinout is the same and his KiCad schematic was the source of
  truth for pin-by-pin verification.
  [Write-up](https://bobparadiso.com/2018/10/09/custom-proportional-power-wheelchair-drive-controls/),
  with the voltage specs (Vref = 50 % of 12 V, ±1.2 V deflection).
- **PG Drives R-Net Omni Technical Manual**, document `SK78813-07`. The SID port
  section documents the 9-way D-type connector. Not redistributed here — it is
  PG Drives / Curtiss-Wright copyright; source your own copy.
- **Teensy 3.0 pinout cards** — <https://www.pjrc.com/teensy/pinout.html>
  (`card5a` / `card5b`).

## License

MIT — see [LICENSE](LICENSE).
