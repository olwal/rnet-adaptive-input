# Open questions and roadmap

What is unresolved on the hardware, and where this should go next.

## Platform support

|  | Windows | macOS | Linux | iPadOS / iOS |
|---|---|---|---|---|
| Mouse | yes | yes | yes | yes |
| Keyboard | yes | yes | yes | yes |
| Gamepad | yes (DirectInput) | yes | yes | **no** |
| Serial telemetry and control | yes | yes | yes | **no** |
| Build and flash | yes | untested | untested | n/a |

USB HID is class-compliant, so the firmware needs no per-platform work. The
host tools are plain Python.

- [x] **Replace `rnet.ps1` with something portable.** Done. `tools/rnet.py`
      runs anywhere and finds the bundled `arduino-cli` on Windows, macOS and
      Linux, falling back to one on `PATH`. Thin `rnet` and `rnet.cmd` shims
      call it.
- [x] **Serial port naming.** Done. A pinned port in `board.json` is now
      ignored if it is not actually present, so a config written on Windows
      naming `COM34` falls through to the scan on macOS instead of failing.
      Port discovery lives in `tools/rnetport.py` rather than in four copies.
- [x] **Usable without a serial host.** Done. `boot` plus `save` persists a
      mode to EEPROM, so the device arms itself. See below for why iPadOS
      needs this.
- [ ] **Verify build and flash on macOS and Linux.** The CLI discovery paths
      are written but untested on real machines. On Linux the PJRC udev rules
      have to be installed before `teensy_loader_cli` can talk to the board.
- [ ] **A native iPad path for gamepad mode.** Generic USB HID gamepads are not
      recognised by the Game Controller framework, which only accepts MFi and a
      few known controllers. Mouse and keyboard modes are unaffected. There is
      no cheap workaround.

### iPadOS specifics

Mouse and keyboard work over USB with no setup, and combine well with
AssistiveTouch and Switch Control.

The constraint is that iPadOS claims any standard CDC-ACM interface before a
third-party driver can match it, and there is no entitlement exposing serial
properties to an app. So nothing running on the iPad can send a `MODE` command,
and the joystick has no button to do it with either.

The workaround is to configure the device from a computer first:

```
rnet hid mode mouse
rnet hid boot mouse
rnet hid save
```

It then comes up in mouse mode wherever it is plugged in. `boot park` and
`save` puts it back to arming nothing.

### Wireless

Bluetooth HID would remove the cable and the USB-C adapter, and iOS supports BLE
keyboards and mice natively. The Teensy 3.0 has no radio, so this means a
different board: an ESP32-S3 gives USB HID and BLE HID, an nRF52840 gives good
BLE. The divider design is unchanged, since both are 3.3 V parts. The gamepad
limitation is identical over BLE, so this buys wireless rather than gamepad
support.

The Teensy 3.0 is discontinued, so a board change is coming eventually anyway.

## Hardware questions

- [x] **Wire dividers and verify Teensy readings.** Done 2026-08-08. Measured
      Vref ~698, X/Y ~698, reconstructed 5.58–5.67 V against the DMM's 5.6 V.
- [ ] **Identify the two 3.5 mm sockets on the joystick underside** (one red, one
      white) and what the male pigtail on the D-sub cable patches into. Likely
      the R-Net convention of separate *Mode* and *On-Off / Profile* switch
      jacks. Test by patching pin 6 into each in turn and watching `sw` in
      `scope.py` while pressing the stick down and any other control. **This may
      also answer whether a stick push is detectable at all.** It is not exposed
      on the D-sub.
- [ ] **Test the 3.5 mm switch.** Short tip to sleeve (a TS plug with jumpered
      leads, or a plug and a paperclip). Verify `sw` toggles 0 → 1. Watch the
      joystick LED, which may change colour or pattern on a mode switch.
- [ ] **Check for a "no plug inserted" detect contact.** Pin 6 might already read
      shorted to GND with nothing plugged in. If so, inserting an unshorted plug
      *opens* the contact and shorting the plug closes it, the inverse of the
      expected behaviour.
- [ ] **Open the housing** (optional) to confirm the sensor type, almost
      certainly Hall-effect, and that pin 6 does route to the 3.5 mm jack.

## Software

- [x] **USB HID.** Done. Gamepad, mouse and keyboard enumerate together; see
      [firmware](firmware.md).
- [ ] **A switch-free way to change mode.** Everything currently needs a keyboard
      or the serial link. With no button on the stick, the established
      alternatives are dwell-in-a-direction, a flick-and-release gesture, or a
      magnitude threshold. Until pin 6 is resolved this is the main gap in
      making the rig usable by the person holding the stick.
- [ ] **Per-user calibration profiles.** Deadzone, expo and slew are tunable live
      but not persisted; they should be saved per user and reloaded on boot.

---

[Back to the README](../README.md)
