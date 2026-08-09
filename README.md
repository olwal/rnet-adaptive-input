# R-net Adaptive Input

### Use a wheelchair joystick as a mouse, keyboard or game controller

https://github.com/user-attachments/assets/6f5dde21-41e2-4d8e-a4ac-a26c28fd4ac4

![The bench build: R-Net joystick on a D-sub breakout, dividers, and a Teensy 3.0](docs/diagram.jpg)

Wheelchair joysticks are excellent input devices. They are proportional, they
are built to be used all day, and someone who drives one already has years of
muscle memory in it. But they only speak to their own wheelchair controller,
over a private analogue interface, so that skill stops at the edge of the chair.

This project bridges that gap. A small microcontroller sits between the joystick
and a computer, and the computer sees an ordinary USB device — no drivers, no
software to install on the host.

**What you can do with it**

- **Move the mouse.** Drive a cursor and click, with an adjustable dead zone and
  response curve so small hand movements stay usable.
- **Send keystrokes.** Arrow keys for anything menu- or key-driven.
- **Be a game controller.** A standard USB gamepad, so games, flight and driving
  sims, and RC simulators see it as a normal stick.
- **Feed your own software.** Raw and shaped values stream over a serial link
  the whole time, whatever mode it is in.

All four run at once and you switch between them from a small command-line tool,
because these joysticks have no spare button to switch with.

The hardware here is a Permobil R-Net *specialty joystick* — the kind sold as an
alternative input for an R-Net Omni controller. They turn up secondhand
regularly and cheaply. The connector is undocumented publicly, so this repo also
writes down the pinout, verified against real hardware.

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

The measurements agree with the design: the joystick's reference reads about 698
ADC counts against 700 predicted from the divider values, and works back out to
5.58 to 5.67 V against the meter's 5.6 V. Derivation in [wiring](docs/wiring.md).

## Documentation

| Page | Contents |
|---|---|
| [Hardware and pinout](docs/hardware.md) | Identifying the joystick, the verified 9-pin D-sub pinout, supporting measurements, bring-up |
| [Wiring the Teensy](docs/wiring.md) | Divider design for a 3.3 V ADC, pad map, expected readings, known issues |
| [Firmware](docs/firmware.md) | The bring-up sketch, the multi-HID build, and the serial protocol |
| [Host tooling](docs/tooling.md) | Build, flash, monitor and tune without installing a toolchain |
| [Marble game](docs/demo-labyrinth.md) | The tilt labyrinth demo: controls, levels, how it is rendered |
| [Single-stick game design](docs/joystick-only-games-brief.md) | Notes on interaction design for one axis pair with no buttons |
| [Open questions and roadmap](docs/roadmap.md) | Unresolved items and planned work |

## Quick start

**You need** a Teensy 3.0, six resistors, a 12 V bench supply, and an R-Net
specialty joystick. Plus:

- **Arduino IDE 2.x with Teensyduino.** No separate toolchain install; the
  tooling drives the `arduino-cli` bundled inside the IDE.
- **Python 3.9+** with `pyserial`. The marble game also wants `raylib`, `numpy`
  and `scipy`; `crosshair.py` wants `pygame`.

  ```
  python -m pip install pyserial pygame raylib numpy scipy
  ```

### 1. Build and flash

1. Wire the dividers. The circuit, the pad map and the derivation are in
   [wiring](docs/wiring.md). Nothing goes straight to a Teensy pin: the
   joystick swings to 6.8 V and the Teensy is a 3.3 V part that is not 5 V
   tolerant.

2. Flash the multi-HID firmware:

   ```
   ./rnet.cmd flash -Hid
   ```

3. The USB descriptor set changes, so the board comes back on a **new COM
   port**. Re-pin it once:

   ```
   ./rnet.cmd config
   ```

It boots **parked**, driving nothing. That is deliberate: a stick that can move
the cursor and type is a device that can do damage to the host if it drifts, so
nothing happens until you ask for it.

To check the raw signals instead, flash the bring-up sketch with
`./rnet.cmd flash` and watch them with `python tools/scope.py`. More in
[firmware](docs/firmware.md).

### 2. Use it

All the interfaces are live at once; you pick which one the stick drives.

**a) As a mouse**

```
./rnet.cmd hid mode mouse
./rnet.cmd hid set mousegain 900     # cursor speed, 40 to 3000
```

Velocity mapping, so the stick steers the cursor and lets it stop, rather than
snapping it back to the middle on release. The switch on the 3.5 mm jack is
left-click.

**b) As a keyboard**

```
./rnet.cmd hid mode keyboard
```

Arrow keys, with separate press and release thresholds so it does not chatter at
the boundary.

**c) Playing the marble game**

```
./rnet.cmd hid mode park             # so it is not also moving the cursor
./rnet.cmd demo labyrinth
```

Tilt a wooden board to roll a marble to the green cup. The game reads the serial
stream directly, which runs in every mode, so **park it first** — otherwise the
stick plays the game and drives your mouse at the same time. Only one program
can hold the port, so set the mode before launching the game.

**Everything else:** `./rnet.cmd hid` on its own opens an interactive session
for live tuning, and `./rnet.cmd hid --help` lists every mode and setting with
its range. Gamepad mode is `./rnet.cmd hid mode gamepad`, and it is DirectInput
rather than XInput — see [firmware](docs/firmware.md) if a game cannot see it.

Details: [firmware and the serial protocol](docs/firmware.md) ·
[host tooling](docs/tooling.md) · [the marble game](docs/demo-labyrinth.md)

The Python tools run on any platform. The `rnet` wrapper is PowerShell only for
now; see [roadmap](docs/roadmap.md).

## References

- **CustomSID by Bob Paradiso.** A custom SID emulator, driving an Omni from
  alternative inputs. This project does the inverse, reading the real joystick,
  but the connector pinout is the same and the KiCad schematic was used for
  pin-by-pin verification.
  [Repository](https://github.com/bobparadiso/CustomSID) ·
  [write-up](https://bobparadiso.com/2018/10/09/custom-proportional-power-wheelchair-drive-controls/),
  including voltage specifications (Vref at 50 % of 12 V, ±1.2 V deflection).
- **PG Drives R-Net Omni Technical Manual**, document `SK78813-07`. The SID port
  section documents the 9-way D-type connector. Not redistributed here, as it is
  PG Drives / Curtiss-Wright copyright.
- **Teensy 3.0 pinout cards.** <https://www.pjrc.com/teensy/pinout.html>
  (`card5a` and `card5b`).

## License

MIT. See [LICENSE](LICENSE).
