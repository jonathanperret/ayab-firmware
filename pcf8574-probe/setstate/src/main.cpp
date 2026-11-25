// Command-driven output control for the AYAB interface board.
//
// Purpose
//   Lets a script on the host set the sixteen solenoid outputs to any state,
//   read them back, and run a burst of alternating writes, to find out which
//   states and which style of I2C write upset the PCF8574 expanders.
//
// The 16-bit state
//   Throughout, a state is sixteen bits, written as four hex digits. The low
//   byte goes to the expander at 0x20 and the high byte to the one at 0x21.
//   A 1 bit switches that solenoid on. Read-backs use the same layout.
//
// At start-up both PCF8574s are written to 0x00 (all outputs off) at once,
// before the serial port is even opened. The sketch then prints
//     READY state XXXX          (XXXX = state read back from the chips)
//
// Serial commands, one per line, 115200 baud:
//   n XXXX   native write: one data byte per chip (XXXX = 16-bit state in
//            hex)
//   m XXXX   MCP23008-style write: [0x09][data] per chip, as the AYAB
//            firmware does
//   r        read both ports back
//   b N XXXX YYYY D   burst: N times alternate between states XXXX and YYYY,
//                     MCP-style, D milliseconds apart, reading back after
//                     each write
//            (N and D are decimal, XXXX and YYYY are hex. The first write is
//            XXXX. The burst ends with a native write of 0000, all off.)
// Every command is answered with one line starting "OK" or "ERR".
//
// Replies:
//   OK n XXXX readback YYYY       the write was acknowledged by both chips
//   ERR i2c n XXXX readback YYYY  at least one chip did not acknowledge
//       (the same two forms with "m" for the m command; YYYY is what the
//       ports read immediately afterwards, and is not compared with XXXX)
//   OK r YYYY
//   OK b writes N mismatches M i2cErrors E [first at I got YYYY]
//       M  number of writes after which the read-back differed from the
//          state just written
//       E  number of writes that at least one chip did not acknowledge
//       I  index (counting from 0) of the first mismatching write, and
//          YYYY what was read back then; printed only if M is not zero
//   ERR unknown command
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) connected by I2C (SDA = A4,
//   SCL = A5) to the interface board with its two PCF8574 expanders at 0x20
//   and 0x21, each driving a ULN2803 and eight solenoids.
#include <Arduino.h>
#include <Wire.h>

// The state most recently requested through put(). It is recorded but
// nothing in this file reads it.
static uint16_t state = 0;

// Prints a 16-bit value as exactly four hexadecimal digits.
static void hx4(uint16_t v) {
  for (int8_t s = 12; s >= 0; s -= 4)
    Serial.print((v >> s) & 0xF, HEX);
}

// Native write: sends the single data byte v to the expander at address a.
// Returns the Wire library's status: 0 if acknowledged, non-zero on error.
static uint8_t wrN(uint8_t a, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(v);
  return Wire.endTransmission();
}

// MCP23008-style write: sends two bytes to the expander at address a, first
// 0x09 and then the data byte v. On an MCP23008, 0x09 is the number of the
// GPIO register. A PCF8574 has no registers and treats both bytes as output
// data, so its port briefly shows 0x09 before it shows v.
// Returns the Wire library's status: 0 if acknowledged, non-zero on error.
static uint8_t wrM(uint8_t a, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write((uint8_t)0x09);
  Wire.write(v);
  return Wire.endTransmission();
}

// Reads one byte from each expander and returns them as a 16-bit state
// (0x20 in the low byte, 0x21 in the high byte). A chip that does not
// answer is not detected here: its byte comes back as 0xFF.
static uint16_t rd() {
  Wire.requestFrom((uint8_t)0x20, (uint8_t)1);
  uint8_t lo = Wire.read();
  Wire.requestFrom((uint8_t)0x21, (uint8_t)1);
  uint8_t hi = Wire.read();
  return ((uint16_t)hi << 8) | lo;
}

// Writes the 16-bit state s to the two expanders, 0x20 first.
//   mcp  true for MCP23008-style two-byte writes, false for native writes
// Returns 0 if both writes were acknowledged, non-zero otherwise (the two
// status codes OR-ed together).
static uint8_t put(uint16_t s, bool mcp) {
  state = s;
  uint8_t e = mcp ? wrM(0x20, lowByte(s)) : wrN(0x20, lowByte(s));
  e |= mcp ? wrM(0x21, highByte(s)) : wrN(0x21, highByte(s));
  return e;
}

// Switches everything off first, then opens the serial port and reports.
void setup() {
  // Select AVCC as the ADC voltage reference. This sketch never uses the
  // ADC, and this file does not say why the line is here. The same line in
  // ../../src/main.cpp is commented as the setting that stops one UNO clone
  // from crashing at random.
  ADMUX = _BV(REFS0);
  Wire.begin();
  put(0, false);
  Serial.begin(115200);
  Serial.print(F("READY state "));
  hx4(rd());
  Serial.println();
}

// Collects characters into a line and executes the line when it ends.
void loop() {
  static char buf[40];  // the command line being received
  static uint8_t n = 0; // number of characters in buf so far
  while (Serial.available()) {
    // Step 1: gather characters until a line end (CR or LF). Characters
    // beyond 39 are dropped. Empty lines are ignored.
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (n < sizeof(buf) - 1)
        buf[n++] = c;
      continue;
    }
    if (!n)
      continue;
    buf[n] = 0;
    n = 0;
    // Step 2: the first character selects the command.
    char cmd = buf[0];
    if (cmd == 'n' || cmd == 'm') {
      // Single write, native (n) or MCP23008-style (m), then a read-back.
      uint16_t s = strtoul(buf + 1, NULL, 16);
      uint8_t e = put(s, cmd == 'm');
      Serial.print(e ? F("ERR i2c ") : F("OK "));
      Serial.print(cmd);
      Serial.print(' ');
      hx4(s);
      Serial.print(F(" readback "));
      hx4(rd());
      Serial.println();
    } else if (cmd == 'r') {
      // Read both ports.
      Serial.print(F("OK r "));
      hx4(rd());
      Serial.println();
    } else if (cmd == 'b') {
      // Burst. Fields: N (decimal count), a and b (hex states), d (decimal
      // delay in milliseconds).
      char *p = buf + 1;
      uint16_t N = strtoul(p, &p, 10), a = strtoul(p, &p, 16),
               b = strtoul(p, &p, 16), d = strtoul(p, &p, 10);
      // bad = mismatching read-backs, firstBad / firstGot = index and
      // read-back of the first one, i2cErr = writes not acknowledged.
      uint16_t bad = 0, firstBad = 0, firstGot = 0, i2cErr = 0;
      for (uint16_t i = 0; i < N; i++) {
        // Even-numbered writes use state a, odd-numbered ones state b.
        uint16_t s = (i & 1) ? b : a;
        if (put(s, true))
          i2cErr++;
        // Read back straight away and compare with what was written.
        uint16_t g = rd();
        if (g != s) {
          if (!bad) {
            firstBad = i;
            firstGot = g;
          }
          bad++;
        }
        delay(d);
      }
      // Leave everything off, using a native write.
      put(0, false);
      Serial.print(F("OK b writes "));
      Serial.print(N);
      Serial.print(F(" mismatches "));
      Serial.print(bad);
      Serial.print(F(" i2cErrors "));
      Serial.print(i2cErr);
      if (bad) {
        Serial.print(F(" first at "));
        Serial.print(firstBad);
        Serial.print(F(" got "));
        hx4(firstGot);
      }
      Serial.println();
    } else {
      Serial.println(F("ERR unknown command"));
    }
  }
}
