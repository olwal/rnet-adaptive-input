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
//
// Settings persist to EEPROM with SAVE, which matters for hosts that cannot
// talk to the serial port at all. iPadOS claims any CDC-ACM interface before a
// third-party app can reach it, so an iPad can use the keyboard and mouse
// interfaces but can never send a MODE command. Configure it from a computer,
// SAVE, then plug it into the tablet.

#include <EEPROM.h>

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

// Which key each direction sends. Remappable at runtime; see the KEYS command.
uint16_t key_up = KEY_UP, key_dn = KEY_DOWN;
uint16_t key_lf = KEY_LEFT, key_rt = KEY_RIGHT;

// Mode entered at power-on. Defaults to PARKED and stays there unless someone
// deliberately changes it: a stick that types and moves the cursor the instant
// it is plugged in is not something to opt people into by accident. Setting it
// is what makes the device usable on a host with no serial access.
uint8_t cfg_boot = MODE_PARKED;

// Only the keys that need a name. Letters and digits are contiguous in the
// HID usage table, so they are decoded arithmetically rather than listed.
struct KeyName { const char *name; uint16_t code; };
static const KeyName KEY_NAMES[] = {
  {"UP", KEY_UP}, {"DOWN", KEY_DOWN}, {"LEFT", KEY_LEFT}, {"RIGHT", KEY_RIGHT},
  {"SPACE", KEY_SPACE}, {"ENTER", KEY_ENTER}, {"ESC", KEY_ESC},
  {"TAB", KEY_TAB}, {"BACKSPACE", KEY_BACKSPACE}, {"DELETE", KEY_DELETE},
  {"HOME", KEY_HOME}, {"END", KEY_END},
  {"PAGEUP", KEY_PAGE_UP}, {"PAGEDOWN", KEY_PAGE_DOWN},
  {"VOLUP", KEY_MEDIA_VOLUME_INC}, {"VOLDOWN", KEY_MEDIA_VOLUME_DEC},
  {"NEXT", KEY_MEDIA_NEXT_TRACK}, {"PREV", KEY_MEDIA_PREV_TRACK},
  {"PLAY", KEY_MEDIA_PLAY_PAUSE},
};
static const uint8_t KEY_NAME_COUNT = sizeof(KEY_NAMES) / sizeof(KEY_NAMES[0]);

// Returns 0 for an unrecognised name; no real key maps to 0.
static uint16_t key_from_name(const char *s) {
  if (!s || !s[0]) return 0;
  if (!s[1]) {                                   // single character
    char c = s[0];
    if (c >= 'A' && c <= 'Z') return KEY_A + (c - 'A');
    if (c >= '1' && c <= '9') return KEY_1 + (c - '1');
    if (c == '0') return KEY_0;
    return 0;
  }
  for (uint8_t i = 0; i < KEY_NAME_COUNT; i++)
    if (!strcmp(s, KEY_NAMES[i].name)) return KEY_NAMES[i].code;
  return 0;
}

static void key_to_name(uint16_t code, char *out, size_t n) {
  for (uint8_t i = 0; i < KEY_NAME_COUNT; i++) {
    if (KEY_NAMES[i].code == code) {
      strncpy(out, KEY_NAMES[i].name, n - 1);
      out[n - 1] = 0;
      return;
    }
  }
  uint16_t usage = code & 0x00FF;
  if (usage >= 4 && usage <= 29)  { out[0] = 'A' + (usage - 4);  out[1] = 0; return; }
  if (usage >= 30 && usage <= 38) { out[0] = '1' + (usage - 30); out[1] = 0; return; }
  if (usage == 39)                { out[0] = '0';                out[1] = 0; return; }
  snprintf(out, n, "0x%04X", code);
}

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

  if (up != k_up) { up ? Keyboard.press(key_up) : Keyboard.release(key_up); k_up = up; }
  if (dn != k_dn) { dn ? Keyboard.press(key_dn) : Keyboard.release(key_dn); k_dn = dn; }
  if (lf != k_lf) { lf ? Keyboard.press(key_lf) : Keyboard.release(key_lf); k_lf = lf; }
  if (rt != k_rt) { rt ? Keyboard.press(key_rt) : Keyboard.release(key_rt); k_rt = rt; }
}

// -------------------------------------------------------------- commands ---

static void report_keys() {
  char u[12], d[12], l[12], r[12];
  key_to_name(key_up, u, sizeof(u));
  key_to_name(key_dn, d, sizeof(d));
  key_to_name(key_lf, l, sizeof(l));
  key_to_name(key_rt, r, sizeof(r));
  Serial.print(F("# keys up=")); Serial.print(u);
  Serial.print(F(" down="));     Serial.print(d);
  Serial.print(F(" left="));     Serial.print(l);
  Serial.print(F(" right="));    Serial.println(r);
}

// Remapping while a key is held would strand it down at the OS level, so
// everything is released first.
static void set_keys(uint16_t u, uint16_t d, uint16_t l, uint16_t r) {
  Keyboard.releaseAll();
  k_up = k_dn = k_lf = k_rt = false;
  key_up = u; key_dn = d; key_lf = l; key_rt = r;
}

// ------------------------------------------------------------- storage -----

// Magic and version guard against reading a blank or stale EEPROM as settings.
// Bump VERSION whenever the struct changes and old saves are ignored rather
// than misinterpreted field by field.
const uint16_t EE_MAGIC = 0x524E;      // 'RN'
const uint8_t  EE_VERSION = 1;
const int      EE_ADDR = 0;

struct Settings {
  uint16_t magic;
  uint8_t  version;
  uint8_t  boot_mode;
  float    deadzone, expo, slew, mousegain, keyon, keyoff;
  uint8_t  inverty;
  uint16_t k_up, k_dn, k_lf, k_rt;
};

static void settings_save() {
  Settings s;
  s.magic = EE_MAGIC;
  s.version = EE_VERSION;
  s.boot_mode = cfg_boot;
  s.deadzone = cfg_deadzone;
  s.expo = cfg_expo;
  s.slew = cfg_slew;
  s.mousegain = cfg_mousegain;
  s.keyon = cfg_keyon;
  s.keyoff = cfg_keyoff;
  s.inverty = cfg_inverty ? 1 : 0;
  s.k_up = key_up; s.k_dn = key_dn; s.k_lf = key_lf; s.k_rt = key_rt;
  EEPROM.put(EE_ADDR, s);
  Serial.println(F("# saved"));
}

static bool settings_load() {
  Settings s;
  EEPROM.get(EE_ADDR, s);
  if (s.magic != EE_MAGIC || s.version != EE_VERSION) return false;

  // Clamp on the way in. A corrupt or hand-edited EEPROM should not be able
  // to produce a deadzone of NaN and a stick that never reports centre.
  cfg_boot      = s.boot_mode < MODE_COUNT ? s.boot_mode : MODE_PARKED;
  cfg_deadzone  = constrain(s.deadzone,  0.0f,  0.45f);
  cfg_expo      = constrain(s.expo,      0.0f,  0.95f);
  cfg_slew      = constrain(s.slew,      0.5f,  60.0f);
  cfg_mousegain = constrain(s.mousegain, 40.0f, 3000.0f);
  cfg_keyon     = constrain(s.keyon,     0.1f,  0.95f);
  cfg_keyoff    = constrain(s.keyoff,    0.05f, 0.90f);
  if (cfg_keyoff >= cfg_keyon) cfg_keyoff = cfg_keyon * 0.72f;
  cfg_inverty   = s.inverty != 0;
  key_up = s.k_up; key_dn = s.k_dn; key_lf = s.k_lf; key_rt = s.k_rt;
  return true;
}

static void settings_defaults() {
  cfg_boot = MODE_PARKED;
  cfg_deadzone = 0.06f; cfg_expo = 0.35f; cfg_slew = 6.0f;
  cfg_mousegain = 620.0f; cfg_keyon = 0.55f; cfg_keyoff = 0.40f;
  cfg_inverty = false;
  key_up = KEY_UP; key_dn = KEY_DOWN; key_lf = KEY_LEFT; key_rt = KEY_RIGHT;
}

static void report_config() {
  Serial.print(F("# cfg deadzone=")); Serial.print(cfg_deadzone, 3);
  Serial.print(F(" expo="));          Serial.print(cfg_expo, 3);
  Serial.print(F(" slew="));          Serial.print(cfg_slew, 2);
  Serial.print(F(" mousegain="));     Serial.print(cfg_mousegain, 0);
  Serial.print(F(" keyon="));         Serial.print(cfg_keyon, 2);
  Serial.print(F(" keyoff="));        Serial.print(cfg_keyoff, 2);
  Serial.print(F(" inverty="));       Serial.print(cfg_inverty ? 1 : 0);
  Serial.print(F(" mode="));          Serial.print(mode);
  Serial.print(F(" boot="));          Serial.println(cfg_boot);
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
    report_keys();
  } else if (!strcmp(line, "SAVE")) {
    settings_save();
  } else if (!strcmp(line, "LOAD")) {
    Serial.println(settings_load() ? F("# loaded") : F("# nothing saved"));
    report_config();
  } else if (!strcmp(line, "DEFAULTS")) {
    settings_defaults();
    Serial.println(F("# defaults restored (SAVE to persist)"));
    report_config();
  } else if (!strncmp(line, "BOOT", 4)) {
    char *p = line + 4;
    while (*p == ' ') p++;
    if (*p) {
      int m = atoi(p);
      if (m >= 0 && m < MODE_COUNT) {
        cfg_boot = (uint8_t)m;
        Serial.println(F("# boot mode set (SAVE to persist)"));
      } else {
        Serial.println(F("# boot mode must be 0..3"));
      }
    }
    Serial.print(F("# boot=")); Serial.println(cfg_boot);
  } else if (!strncmp(line, "KEYS", 4)) {
    char *p = line + 4;
    while (*p == ' ') p++;
    if (!*p) {                                   // KEYS -> report
      report_keys();
    } else if (!strcmp(p, "ARROWS")) {
      set_keys(KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT);
      report_keys();
    } else if (!strcmp(p, "WASD")) {
      set_keys(KEY_W, KEY_S, KEY_A, KEY_D);
      report_keys();
    } else if (!strcmp(p, "IJKL")) {
      set_keys(KEY_I, KEY_K, KEY_J, KEY_L);
      report_keys();
    } else if (!strcmp(p, "MEDIA")) {
      set_keys(KEY_MEDIA_VOLUME_INC, KEY_MEDIA_VOLUME_DEC,
               KEY_MEDIA_PREV_TRACK, KEY_MEDIA_NEXT_TRACK);
      report_keys();
    } else {
      // KEYS <direction> <keyname>
      char *dir = p;
      while (*p && *p != ' ') p++;
      bool have = (*p != 0);
      if (have) *p++ = 0;
      while (*p == ' ') p++;
      uint16_t code = have ? key_from_name(p) : 0;
      if (!code) {
        Serial.println(F("# usage: KEYS [arrows|wasd|ijkl|media] "
                         "| KEYS <up|down|left|right> <key>"));
      } else if (!strcmp(dir, "UP")) {
        set_keys(code, key_dn, key_lf, key_rt); report_keys();
      } else if (!strcmp(dir, "DOWN")) {
        set_keys(key_up, code, key_lf, key_rt); report_keys();
      } else if (!strcmp(dir, "LEFT")) {
        set_keys(key_up, key_dn, code, key_rt); report_keys();
      } else if (!strcmp(dir, "RIGHT")) {
        set_keys(key_up, key_dn, key_lf, code); report_keys();
      } else {
        Serial.println(F("# direction must be up, down, left or right"));
      }
    }
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
    Serial.println(F("# SAVE | LOAD | DEFAULTS | BOOT 0..3   (BOOT then SAVE"));
    Serial.println(F("#   to come up in that mode with no serial host)"));
    Serial.println(F("# SET deadzone|expo|slew|mousegain|keyon|keyoff|inverty <v>"));
    Serial.println(F("# KEYS [arrows|wasd|ijkl|media]"));
    Serial.println(F("# KEYS <up|down|left|right> <A-Z|0-9|space|enter|esc|"
                     "tab|home|end|pageup|pagedown|volup|voldown|play|next|prev>"));
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

  bool restored = settings_load();

  delay(400);
  calibrate();
  neutralise();

  // Arm the saved mode only after calibrate() has a centre to work from,
  // otherwise the first frames drive the host from an uncalibrated stick.
  if (cfg_boot != MODE_PARKED) set_mode(cfg_boot);

  Serial.println(F("=== R-Net multi-HID bridge ==="));
  if (restored) Serial.println(F("# settings restored from EEPROM"));
  if (mode == MODE_PARKED) {
    Serial.println(F("# parked. MODE 1 gamepad, 2 mouse, 3 keyboard. "
                     "HELP for more."));
  } else {
    Serial.print(F("# armed at boot in mode ")); Serial.print(mode);
    Serial.println(F(". PARK to stop it. BOOT 0 then SAVE to undo."));
  }
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
