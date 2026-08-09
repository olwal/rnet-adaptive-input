// R-Net Omni joystick bring-up sketch
//
// Target: Teensy 3.0 (3.3 V). Its analog pins are NOT 5 V tolerant -- the
// dividers below are sized for a 3.3 V rail, not the 100k/100k pair that
// would suit a 5 V UNO.
//
// Reads the joystick's X, Y and Vref analog outputs through 100k/68k
// dividers and the MODE switch (3.5mm jack tip) on a digital pin.
//
// Wiring (see README.md):
//   joystick pin 1 (Y / SPEED) -> 100k/68k divider -> A7 (pad 21)
//   joystick pin 2 (X / DIR)   -> 100k/68k divider -> A8 (pad 22)
//   joystick pin 3 (Vref)      -> 100k/68k divider -> A9 (pad 23)
//   divider bottom legs                            -> GND (AGND preferred)
//   3.5mm jack tip / D-sub pin 6                   -> D2 (INPUT_PULLUP)
//   3.5mm jack sleeve                              -> GND
//
// Bench supply GND, joystick pin 8 and board GND must share one node.
//
// Expected at ~11 V joystick supply, 10-bit reads:
//   Vref ~700, X/Y ~695 at rest, dx/dy swing +/-143 at full deflection.

const uint8_t PIN_Y    = A7;   // pad 21 - joystick pin 1 (SPEED) via 100k/68k divider
const uint8_t PIN_X    = A8;   // pad 22 - joystick pin 2 (DIR)   via 100k/68k divider
const uint8_t PIN_VREF = A9;   // pad 23 - joystick pin 3 (REF)   via 100k/68k divider
const uint8_t PIN_SW   = 2;    // pad 2  - 3.5mm jack tip = D-sub pin 6 (MODE)

int x_center = 0, y_center = 0;

// The 100k/68k dividers present ~40.5 kOhm to the ADC, well above the ~10 kOhm
// the Teensy 3.0 sample-and-hold wants. Without help, each conversion retains
// part of the previous channel's voltage, so moving the stick visibly drags
// the Vref reading. Discarding one read per channel lets the S/H settle on the
// new input before the reading that counts.
static int readSettled(uint8_t pin) {
  analogRead(pin);
  return analogRead(pin);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SW, INPUT_PULLUP);
  analogReference(DEFAULT);   // Teensy 3.0: 3.3 V
  analogReadAveraging(32);    // hardware averaging; also re-samples each pass

  // Optional 4x resolution (Teensy only). Voltages are unchanged, only the
  // scale: Vref ~2800, swing ~+/-572. Update README expectations if enabled.
  // analogReadResolution(12);

  delay(500);
  long xs = 0, ys = 0, rs = 0;
  for (int i = 0; i < 64; i++) {
    xs += readSettled(PIN_X);
    ys += readSettled(PIN_Y);
    rs += readSettled(PIN_VREF);
    delay(2);
  }
  int x0 = xs / 64, y0 = ys / 64, r0 = rs / 64;
  x_center = x0 - r0;
  y_center = y0 - r0;

  Serial.println(F("=== R-Net joystick bring-up ==="));
  Serial.print(F("calibration: X0=")); Serial.print(x0);
  Serial.print(F(" Y0="));             Serial.print(y0);
  Serial.print(F(" Vref="));           Serial.print(r0);
  Serial.print(F(" -> dx0="));         Serial.print(x_center);
  Serial.print(F(" dy0="));            Serial.println(y_center);
}

void loop() {
  int x    = readSettled(PIN_X);
  int y    = readSettled(PIN_Y);
  int vref = readSettled(PIN_VREF);
  int sw   = digitalRead(PIN_SW) == LOW;

  int dx = (x - vref) - x_center;
  int dy = (y - vref) - y_center;

  Serial.print(F("X="));    Serial.print(x);
  Serial.print(F("\tY="));  Serial.print(y);
  Serial.print(F("\tR="));  Serial.print(vref);
  Serial.print(F("\tdx=")); Serial.print(dx);
  Serial.print(F("\tdy=")); Serial.print(dy);
  Serial.print(F("\tsw=")); Serial.println(sw);

  delay(10);   // ~100 Hz - smooth enough for the crosshair demo to track
}
