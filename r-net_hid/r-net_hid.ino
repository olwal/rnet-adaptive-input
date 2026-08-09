// R-Net joystick -> multi-HID bridge
//
// Build with USB Type = "Serial + Keyboard + Mouse + Joystick"
//   FQBN teensy:avr:teensy30:usb=serialhid
//
// All four USB interfaces enumerate at once and stay enumerated; USB type is
// a compile-time choice, not a runtime one. "Mode" therefore selects which
// interface we actively drive, not which exists.
//
// Modes:
//   0 PARKED    drives nothing. The power-on default, deliberately.
//   1 GAMEPAD   absolute axes, DirectInput
//   2 MOUSE     velocity mapping with a fractional accumulator
//   3 KEYBOARD  arrow keys with hysteresis
//
// Serial carries telemetry in every mode, in the same format the host tools
// already parse, and accepts commands. Type HELP into any terminal.

// ----------------------------------------------------------------- pins ----

const uint8_t PIN_Y    = A7;   // pad 21 - joystick pin 1 (SPEED)
const uint8_t PIN_X    = A8;   // pad 22 - joystick pin 2 (DIR)
const uint8_t PIN_VREF = A9;   // pad 23 - joystick pin 3 (REF)
const uint8_t PIN_SW   = 2;    // pad 2  - 3.5mm jack tip / D-sub pin 6
const uint8_t PIN_LED  = 13;

const float FULL_SCALE = 143.0f;   // counts at full deflection

// ---------------------------------------------------------------- state ----

enum Mode { MODE_PARKED = 0, MODE_GAMEPAD = 1, MODE_MOUSE = 2,
            MODE_KEYBOARD = 3, MODE_COUNT = 4 };

uint8_t mode = MODE_PARKED;

// Shaping, shared by every mode so there is one thing to tune rather than
// three that drift apart.
float cfg_deadzone   = 0.06f;
float cfg_expo       = 0.35f;
float cfg_slew       = 6.0f;    // max units/s of change, tames spasm spikes
float cfg_mousegain  = 620.0f;  // pixels/s at full deflection
float cfg_keyon      = 0.55f;
float cfg_keyoff     = 0.40f;
bool  cfg_inverty    = false;

int x_center = 0, y_center = 0;
float sx = 0.0f, sy = 0.0f;         // shaped, slew-limited, -1..1

// Mouse sub-pixel remainder. Mouse.move takes integers: without carrying the
// fraction, anything under one pixel per tick truncates to zero and slow
// precise movement becomes impossible.
float mouse_rx = 0.0f, mouse_ry = 0.0f;

// Latched key state, so hysteresis has something to be hysteretic about.
bool k_up = false, k_dn = false, k_lf = false, k_rt = false;

char cmd[64];
uint8_t cmd_len = 0;

elapsedMillis since_tel;
elapsedMillis since_blink;

// ----------------------------------------------------------------- adc -----

// The 100k/68k dividers present ~40 kOhm, well above what the Teensy 3.0
// sample-and-hold wants. Discarding one read per channel lets it settle.
static int readSettled(uint8_t pin) {
  analogRead(pin);
  return analogRead(pin);
}

static void calibrate() {
  long xs = 0, ys = 0, rs = 0;
  for (int i = 0; i < 64; i++) {
    xs += readSettled(PIN_X);
    ys += readSettled(PIN_Y);
    rs += readSettled(PIN_VREF);
    delay(2);
  }
  int r0 = rs / 64;
  x_center = (xs / 64) - r0;
  y_center = (ys / 64) - r0;
  Serial.print(F("# calibrated dx0=")); Serial.print(x_center);
  Serial.print(F(" dy0=")); Serial.println(y_center);
}

// --------------------------------------------------------------- shaping ---

static float shape(float v) {
  // Deadzone is rescaled rather than clipped, so travel just outside it
  // starts from zero instead of jumping.
  float mag = fabsf(v);
  if (mag <= cfg_deadzone) return 0.0f;
  mag = (mag - cfg_deadzone) / (1.0f - cfg_deadzone);
  mag = (1.0f - cfg_expo) * mag + cfg_expo * mag * mag * mag;
  if (mag > 1.0f) mag = 1.0f;
  return (v < 0.0f) ? -mag : mag;
}

static float slew(float cur, float target, float dt) {
  float lim = cfg_slew * dt;
  float d = target - cur;
  if (d > lim) d = lim;
  if (d < -lim) d = -lim;
  return cur + d;
}

// ------------------------------------------------------------- interfaces --

static int axis(float v) {                  // -1..1 -> 0..1023
  int a = (int)(512.0f + v * 511.0f);
  return a < 0 ? 0 : (a > 1023 ? 1023 : a);
}

// Leaving a mode does not neutralise it: the interfaces stay live, so a key
// held at the moment of a switch stays held at the OS level, and gamepad axes
// hold their last value forever. Every transition has to tear down explicitly.
static void neutralise() {
  Keyboard.releaseAll();
  k_up = k_dn = k_lf = k_rt = false;

  mouse_rx = mouse_ry = 0.0f;

  Joystick.X(512); Joystick.Y(512); Joystick.Z(512);
  Joystick.Zrotate(512); Joystick.sliderLeft(512); Joystick.sliderRight(512);
  for (int b = 1; b <= 32; b++) Joystick.button(b, false);
  Joystick.hat(-1);
  Joystick.send_now();
}

static void set_mode(int m) {
  if (m < 0 || m >= MODE_COUNT) {
    Serial.println(F("# bad mode"));
    return;
  }
  neutralise();
  mode = (uint8_t)m;
  Serial.print(F("# mode=")); Serial.println(mode);
}

static void drive_gamepad(bool sw) {
  Joystick.X(axis(sx));
  Joystick.Y(axis(cfg_inverty ? sy : -sy));   // HID Y is screen-down positive
  Joystick.button(1, sw);
  Joystick.send_now();
}

static void drive_mouse(float dt, bool sw) {
  mouse_rx += sx * cfg_mousegain * dt;
  mouse_ry += (cfg_inverty ? sy : -sy) * cfg_mousegain * dt;
  int mx = (int)mouse_rx;
  int my = (int)mouse_ry;
  mouse_rx -= mx;
  mouse_ry -= my;
  if (mx > 127) mx = 127; if (mx < -127) mx = -127;
  if (my > 127) my = 127; if (my < -127) my = -127;
  if (mx || my) Mouse.move(mx, my);
  if (sw != Mouse.isPressed(MOUSE_LEFT)) {
    if (sw) Mouse.press(MOUSE_LEFT); else Mouse.release(MOUSE_LEFT);
  }
}

// Separate on/off thresholds. With one threshold the key chatters at the
// boundary, machine-gunning keydown/keyup at loop rate.
static bool latch(bool cur, float v) {
  return cur ? (v > cfg_keyoff) : (v > cfg_keyon);
}

static void drive_keyboard() {
  bool up = latch(k_up, sy);
  bool dn = latch(k_dn, -sy);
  bool lf = latch(k_lf, -sx);
  bool rt = latch(k_rt, sx);

  if (up != k_up) { up ? Keyboard.press(KEY_UP)    : Keyboard.release(KEY_UP);    k_up = up; }
  if (dn != k_dn) { dn ? Keyboard.press(KEY_DOWN)  : Keyboard.release(KEY_DOWN);  k_dn = dn; }
  if (lf != k_lf) { lf ? Keyboard.press(KEY_LEFT)  : Keyboard.release(KEY_LEFT);  k_lf = lf; }
  if (rt != k_rt) { rt ? Keyboard.press(KEY_RIGHT) : Keyboard.release(KEY_RIGHT); k_rt = rt; }
}

// -------------------------------------------------------------- commands ---

static void report_config() {
  Serial.print(F("# cfg deadzone=")); Serial.print(cfg_deadzone, 3);
  Serial.print(F(" expo="));          Serial.print(cfg_expo, 3);
  Serial.print(F(" slew="));          Serial.print(cfg_slew, 2);
  Serial.print(F(" mousegain="));     Serial.print(cfg_mousegain, 0);
  Serial.print(F(" keyon="));         Serial.print(cfg_keyon, 2);
  Serial.print(F(" keyoff="));        Serial.print(cfg_keyoff, 2);
  Serial.print(F(" inverty="));       Serial.print(cfg_inverty ? 1 : 0);
  Serial.print(F(" mode="));          Serial.println(mode);
}

static bool assign(const char *name, const char *want, float *dst, float v,
                   float lo, float hi) {
  if (strcmp(name, want) != 0) return false;
  if (v < lo) v = lo;
  if (v > hi) v = hi;
  *dst = v;
  return true;
}

static void handle(char *line) {
  for (char *p = line; *p; p++) if (*p >= 'a' && *p <= 'z') *p -= 32;

  if (!strncmp(line, "MODE", 4)) {
    set_mode(atoi(line + 4));
  } else if (!strcmp(line, "PARK")) {
    set_mode(MODE_PARKED);
  } else if (!strcmp(line, "CAL")) {
    calibrate();
  } else if (!strcmp(line, "GET")) {
    report_config();
  } else if (!strncmp(line, "SET", 3)) {
    // Hand-rolled rather than sscanf("%f"): newlib-nano, which the Teensy
    // toolchain links by default, ships without float support in scanf and
    // silently parses nothing.
    char *p = line + 3;
    while (*p == ' ') p++;
    char *name = p;
    while (*p && *p != ' ') p++;
    bool have = (*p != 0);
    if (have) *p++ = 0;
    while (*p == ' ') p++;
    if (have && *p) {
      float v = atof(p);
      bool ok =
          assign(name, "DEADZONE",  &cfg_deadzone,  v, 0.0f, 0.45f) ||
          assign(name, "EXPO",      &cfg_expo,      v, 0.0f, 0.95f) ||
          assign(name, "SLEW",      &cfg_slew,      v, 0.5f, 60.0f) ||
          assign(name, "MOUSEGAIN", &cfg_mousegain, v, 40.0f, 3000.0f) ||
          assign(name, "KEYON",     &cfg_keyon,     v, 0.1f, 0.95f) ||
          assign(name, "KEYOFF",    &cfg_keyoff,    v, 0.05f, 0.90f);
      if (!ok && !strcmp(name, "INVERTY")) { cfg_inverty = v > 0.5f; ok = true; }
      if (cfg_keyoff >= cfg_keyon) cfg_keyoff = cfg_keyon * 0.72f;
      Serial.println(ok ? F("# ok") : F("# unknown setting"));
    } else {
      Serial.println(F("# usage: SET <name> <value>"));
    }
  } else if (!strcmp(line, "HELP") || !strcmp(line, "?")) {
    Serial.println(F("# MODE 0..3  (0 parked, 1 gamepad, 2 mouse, 3 keyboard)"));
    Serial.println(F("# PARK | CAL | GET | HELP"));
    Serial.println(F("# SET deadzone|expo|slew|mousegain|keyon|keyoff|inverty <v>"));
  } else if (line[0]) {
    Serial.println(F("# ? try HELP"));
  }
}

static void poll_serial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      cmd[cmd_len] = 0;
      handle(cmd);
      cmd_len = 0;
    } else if (cmd_len < sizeof(cmd) - 1) {
      cmd[cmd_len++] = c;
    }
  }
}

// ------------------------------------------------------------------ main ---

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SW, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  analogReference(DEFAULT);
  analogReadAveraging(32);

  Joystick.useManualSend(true);   // one coherent report per tick

  delay(400);
  calibrate();
  neutralise();

  Serial.println(F("=== R-Net multi-HID bridge ==="));
  Serial.println(F("# parked. MODE 1 gamepad, 2 mouse, 3 keyboard. HELP for more."));
}

void loop() {
  static uint32_t last_us = micros();
  uint32_t now_us = micros();
  float dt = (now_us - last_us) * 1e-6f;
  last_us = now_us;
  if (dt <= 0.0f || dt > 0.25f) dt = 0.01f;

  poll_serial();

  int x    = readSettled(PIN_X);
  int y    = readSettled(PIN_Y);
  int vref = readSettled(PIN_VREF);
  bool sw  = digitalRead(PIN_SW) == LOW;

  int dx = (x - vref) - x_center;
  int dy = (y - vref) - y_center;

  float tx = shape(constrain(dx / FULL_SCALE, -1.5f, 1.5f));
  float ty = shape(constrain(dy / FULL_SCALE, -1.5f, 1.5f));
  sx = slew(sx, tx, dt);
  sy = slew(sy, ty, dt);

  switch (mode) {
    case MODE_GAMEPAD:  drive_gamepad(sw);   break;
    case MODE_MOUSE:    drive_mouse(dt, sw); break;
    case MODE_KEYBOARD: drive_keyboard();    break;
    default:            break;               // PARKED drives nothing
  }

  // Telemetry, in the format tools/scope.py and tools/crosshair.py parse.
  // Trailing fields are additive; their regexes use search, not match.
  if (since_tel >= 10) {
    since_tel = 0;
    Serial.print(F("X="));     Serial.print(x);
    Serial.print(F("\tY="));   Serial.print(y);
    Serial.print(F("\tR="));   Serial.print(vref);
    Serial.print(F("\tdx="));  Serial.print(dx);
    Serial.print(F("\tdy="));  Serial.print(dy);
    Serial.print(F("\tsw="));  Serial.print(sw ? 1 : 0);
    Serial.print(F("\tmode=")); Serial.print(mode);
    Serial.print(F("\tsx="));  Serial.print(sx, 3);
    Serial.print(F("\tsy="));  Serial.println(sy, 3);
  }

  // Mode feedback with no screen: parked is dark, otherwise blink the number.
  uint32_t phase = since_blink;
  if (phase > 2000) since_blink = 0;
  bool lit = false;
  if (mode != MODE_PARKED) {
    uint32_t slot = phase / 180;
    lit = (slot < (uint32_t)mode * 2) && (slot % 2 == 0);
  }
  digitalWrite(PIN_LED, lit);
}
