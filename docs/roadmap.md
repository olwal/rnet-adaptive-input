# Open questions and roadmap

What is unresolved on the hardware, and where this should go next.

## Cross-platform support

The Python side (`scope.py`, `crosshair.py`, `hid.py` and the demo) is already
portable and has no Windows-specific code in it. The gap is the build wrapper.

- [ ] **Replace `rnet.ps1` with something portable.** It is PowerShell and it
      hardcodes a Windows install path for the `arduino-cli` bundled inside
      Arduino IDE 2.x. A Python rewrite would run everywhere and drop the
      `rnet.cmd` shim; the logic is only board detection, FQBN selection and a
      few `arduino-cli` invocations.
- [ ] **Find the bundled `arduino-cli` per platform.** macOS keeps it inside
      `Arduino IDE.app/Contents/Resources/app/lib/backend/resources/`, Linux
      under the AppImage extract or `~/.arduinoIDE`. Falling back to
      `arduino-cli` on `PATH` covers people who installed it standalone.
- [ ] **Serial port naming.** `board.json` pins a `COMn` port. On macOS and
      Linux these are `/dev/tty.usbmodem*` and `/dev/ttyACM*`; the auto-detect
      path already handles them via `pyserial`, but the pinned-config path
      assumes Windows naming.
- [ ] **Verify Teensy upload off Windows.** `teensy_loader_cli` behaves
      differently, and on Linux it needs the PJRC udev rules installed.
- [ ] **Documentation currently shows PowerShell invocations throughout.** Once
      the wrapper is portable, show plain `python tools/...` commands as the
      primary form.

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
