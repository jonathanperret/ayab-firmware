// Machine-session sketch: everything needed to hunt the PCF8574 fault on the
// knitting machine with only a laptop on the controller's USB port.
//
// At start-up it checks the I2C lines for pull-ups, scans the bus, writes both
// PCF8574s to 0x00 (all solenoids off) and prints one READY line with the
// chip's identity, a boot counter (so a controller restart is noticed) and its
// own supply voltage.
//
// The 16-bit state
//   A state is sixteen bits, written as four hex digits. The low byte goes
//   to the expander at 0x20 and the high byte to the one at 0x21. A 1 bit
//   switches that solenoid on. Read-backs use the same layout.
//
// The READY line (one line on the wire):
//   READY boot B mcusr MM sig SSSSSS serial N..N vcc V pullups sda=0|1
//         scl=0|1 acks AA AA ... init ok|ERR state XXXX
//     boot     number of times the sketch has started since power was
//              applied (decimal)
//     mcusr    the chip's reset-cause register as the sketch found it, hex
//     sig      three-byte device signature, hex
//     serial   ten-byte chip serial number, hex
//     vcc      controller supply voltage, millivolts
//     pullups  1 if the line rose within 0.2 ms of being released
//     acks     every I2C address that acknowledged, hex (20 and 21 expected)
//     init     whether the all-off write at start-up was acknowledged
//     state    both ports read back, hex
//
// Commands, one per line at 115200 baud, each answered by one line:
//   n XXXX            native write of the 16-bit state (hex)
//   p PP XXXX         two-byte write per chip: [PP][data]
//                     (PP=09 is what the AYAB firmware sends)
//   r                 read both ports back
//   b N AAAA BBBB D S PP
//        burst: N writes alternating between states AAAA and BBBB, D ms apart.
//        S=0 native, S=1 two-byte with prefix PP. Both ports are read back
//        after every write. Reports mismatches, missing acknowledges, the first
//        three mismatches in detail and the controller's supply range. Ends all
//        off.
//        (N and D are decimal; AAAA, BBBB and PP are hex. The first write is
//        AAAA.)
//   v                 controller supply voltage (mV), measured against the
//                     internal reference
//
// Replies:
//   OK n XXXX readback YYYY        written, acknowledged, read back the same
//   MISMATCH n XXXX readback YYYY  acknowledged, but the ports read YYYY
//   ERR i2c n XXXX readback YYYY   a write or a read was not acknowledged
//       (the same three forms with "p" for the p command; PP is not echoed)
//   OK r YYYY     or     ERR i2c r YYYY
//   OK v V
//   OK b writes N mismatches M portAllHigh H stillWrongOnReread S writeNak W
//        readNak R vccMin V1 vccMax V2 [| #I want XXXX got YYYY reread ZZZZ]
//       M   writes after which the read-back differed from what was written
//       H   times one expander read FF although its byte was not FF (both
//           expanders are counted separately, so H can exceed M)
//       S   mismatches where a second read gave the same wrong value
//       W   writes where at least one expander did not acknowledge
//       R   read-backs where at least one expander did not answer
//       V1, V2  lowest and highest controller supply during the burst, mV
//       The part after "|" is repeated for each of the first three
//       mismatches: write index I (from 0), state written, state read,
//       state read a second time.
//   ERR unknown command
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) connected by I2C (SDA = A4,
//   SCL = A5) to the interface board with its two PCF8574 expanders at 0x20
//   and 0x21, each driving a ULN2803 and eight solenoids.
#include <Arduino.h>
#include <Wire.h>
#include <avr/boot.h>

// Boot counter. Both variables live in the .noinit section, which the C
// start-up code does not clear, so they survive a reset as long as the chip
// stays powered. bootMagic holds 0xB007 once bootCount is valid.
uint16_t bootMagic __attribute__((section(".noinit")));
uint16_t bootCount __attribute__((section(".noinit")));

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx2(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Prints a 16-bit value as exactly four hexadecimal digits.
static void hx4(uint16_t v) {
  hx2(v >> 8);
  hx2(v & 0xFF);
}

// Runs one ADC conversion and returns the raw result, 0 to 1023.
// setup() leaves the ADC permanently set to measure the chip's internal
// 1.1 V reference with the supply (AVCC) as full scale, so the reading is
// 1.1 V / supply * 1023: the lower the supply, the higher the reading.
// One conversion takes about 0.1 ms.
static uint16_t vccRaw() {
  ADCSRA |= _BV(ADSC);
  while (ADCSRA & _BV(ADSC)) {
  }
  return ADC;
}

// Converts a raw reading from vccRaw() to the supply voltage in millivolts:
// 1100 mV * 1023 / raw = 1125300 / raw. A raw value of 0 gives 0 rather
// than a division by zero.
static uint16_t vccMv(uint16_t raw) {
  return raw ? 1125300L / raw : 0;
}

// Native write: sends the single byte v to the expander at address a.
// Returns the Wire library's status: 0 if acknowledged, non-zero on error.
static uint8_t wr1(uint8_t a, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(v);
  return Wire.endTransmission();
}

// Two-byte write: sends pfx and then v to the expander at address a in one
// transaction. With pfx = 0x09 this is the write the AYAB firmware sends
// (0x09 is the GPIO register number of an MCP23008). A PCF8574 treats both
// bytes as output data, so its port briefly shows pfx before it shows v.
// Returns the Wire library's status: 0 if acknowledged, non-zero on error.
static uint8_t wr2(uint8_t a, uint8_t pfx, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(pfx);
  Wire.write(v);
  return Wire.endTransmission();
}

// Reads one byte from each expander and returns them as a 16-bit state
// (0x20 in the low byte, 0x21 in the high byte).
//   nak  optional; if given, receives the number of expanders (0, 1 or 2)
//        that did not deliver their byte. The byte of an expander that did
//        not answer comes back as FF.
static uint16_t rd(uint8_t *nak = 0) {
  uint8_t n0 = Wire.requestFrom((uint8_t)0x20, (uint8_t)1);
  uint8_t lo = Wire.read();
  uint8_t n1 = Wire.requestFrom((uint8_t)0x21, (uint8_t)1);
  uint8_t hi = Wire.read();
  if (nak)
    *nak = (n0 != 1) + (n1 != 1);
  return ((uint16_t)hi << 8) | lo;
}

// Writes the 16-bit state s to the two expanders, 0x20 first.
//   two  true for two-byte writes with the prefix pfx, false for native
//        single-byte writes (pfx is then ignored)
// Returns 0 if both writes were acknowledged, non-zero otherwise.
static uint8_t put(uint16_t s, bool two, uint8_t pfx) {
  uint8_t e = two ? wr2(0x20, pfx, lowByte(s)) : wr1(0x20, lowByte(s));
  return e | (two ? wr2(0x21, pfx, highByte(s)) : wr1(0x21, highByte(s)));
}

// Returns true if the given pin (A4 or A5) has an external pull-up.
// The pin is driven low for 2 ms, then released with the internal pull-up
// off and read 0.2 ms later; only an external resistor brings it high that
// quickly. This must be called before Wire.begin().
static bool pulledUp(uint8_t pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delay(2);
  pinMode(pin, INPUT);
  delayMicroseconds(200);
  return digitalRead(pin);
}

// Start-up checks, all outputs off, then the READY line.
void setup() {
  // Step 1: save and clear the reset-cause register. (A comment in
  // ../../mcp-readback/src/main.cpp notes that the optiboot bootloader
  // passes the original MCUSR value in register r2; this sketch prints
  // what it finds in MCUSR itself.)
  uint8_t mcusr = MCUSR;
  MCUSR = 0;
  // Step 2: count this start. If the marker is missing, RAM has lost power
  // since the last start, so the count begins again from 1.
  if (bootMagic != 0xB007) {
    bootMagic = 0xB007;
    bootCount = 0;
  }
  bootCount++;
  // Step 3: test both I2C lines for pull-ups before enabling I2C.
  bool sda = pulledUp(A4), scl = pulledUp(A5);
  // Step 4: set up the ADC to measure the supply: AVCC as reference,
  // channel 0x0E (internal 1.1 V reference), ADC on, clock prescaler 128.
  // The 10 ms wait and the discarded first conversion let the reading
  // settle.
  ADMUX = _BV(REFS0) | 0x0E;
  ADCSRA = _BV(ADEN) | 7;
  delay(10);
  vccRaw();
  // Step 5: start I2C and switch every solenoid off (native write).
  Wire.begin();
  uint8_t e = put(0, false, 0);
  // Step 6: print the READY line. Signature row bytes 0, 2, 4 are the
  // device signature; bytes 0x0E to 0x17 the chip serial number.
  Serial.begin(115200);
  Serial.print(F("READY boot "));
  Serial.print(bootCount);
  Serial.print(F(" mcusr "));
  hx2(mcusr);
  Serial.print(F(" sig "));
  hx2(boot_signature_byte_get(0));
  hx2(boot_signature_byte_get(2));
  hx2(boot_signature_byte_get(4));
  Serial.print(F(" serial "));
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx2(boot_signature_byte_get(a));
  Serial.print(F(" vcc "));
  Serial.print(vccMv(vccRaw()));
  Serial.print(F(" pullups sda="));
  Serial.print(sda);
  Serial.print(F(" scl="));
  Serial.print(scl);
  // Bus scan: every address from 0x03 to 0x77 is sent with no data; the
  // ones that acknowledge are listed.
  Serial.print(F(" acks"));
  for (uint8_t a = 0x03; a <= 0x77; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print(' ');
      hx2(a);
    }
  }
  Serial.print(F(" init "));
  Serial.print(e ? F("ERR") : F("ok"));
  Serial.print(F(" state "));
  hx4(rd());
  Serial.println();
}

// Collects characters into a line and executes the line when it ends.
void loop() {
  static char buf[48];  // the command line being received
  static uint8_t n = 0; // number of characters in buf so far
  while (Serial.available()) {
    // Gather characters until a line end (CR or LF). Characters beyond 47
    // are dropped. Empty lines are ignored.
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
    // The first character selects the command; p walks along its fields.
    char cmd = buf[0];
    char *p = buf + 1;
    if (cmd == 'n' || cmd == 'p') {
      // n / p: one write (native, or two-byte with a prefix), followed by
      // a read-back that is compared with what was written.
      uint8_t pfx = 0;
      if (cmd == 'p')
        pfx = strtoul(p, &p, 16);
      uint16_t s = strtoul(p, &p, 16);
      uint8_t e = put(s, cmd == 'p', pfx), nak;
      uint16_t g = rd(&nak);
      Serial.print(e || nak ? F("ERR i2c ")
                            : (g == s ? F("OK ") : F("MISMATCH ")));
      Serial.print(cmd);
      Serial.print(' ');
      hx4(s);
      Serial.print(F(" readback "));
      hx4(g);
      Serial.println();
    } else if (cmd == 'r') {
      // r: read both ports.
      uint8_t nak;
      uint16_t g = rd(&nak);
      Serial.print(nak ? F("ERR i2c r ") : F("OK r "));
      hx4(g);
      Serial.println();
    } else if (cmd == 'v') {
      // v: controller supply voltage.
      Serial.print(F("OK v "));
      Serial.println(vccMv(vccRaw()));
    } else if (cmd == 'b') {
      // b: burst of alternating writes.
      // Step 1: parse N (count), a and b (the two states), d (delay in
      // ms), two (0 = native, otherwise two-byte) and pfx (prefix byte).
      uint16_t N = strtoul(p, &p, 10), a = strtoul(p, &p, 16),
               b = strtoul(p, &p, 16), d = strtoul(p, &p, 10);
      uint8_t two = strtoul(p, &p, 10), pfx = strtoul(p, &p, 16);
      // Counters: bad = mismatches, wErr / rErr = writes / reads not
      // acknowledged, rawMin / rawMax = extreme supply readings, allHigh =
      // ports that read FF unasked, stuck = mismatches confirmed by a
      // second read.
      uint16_t bad = 0, wErr = 0, rErr = 0, rawMin = 1023, rawMax = 0,
               allHigh = 0, stuck = 0;
      // Details of the first three mismatches; nd is how many are stored.
      uint16_t dIdx[3], dWant[3], dGot[3], dAgain[3];
      uint8_t nd = 0;
      for (uint16_t i = 0; i < N; i++) {
        // Step 2: write the next state (a on even i, b on odd i) and read
        // both ports back straight away.
        uint16_t s = (i & 1) ? b : a;
        uint8_t nak;
        if (put(s, two, pfx))
          wErr++;
        uint16_t g = rd(&nak);
        if (nak)
          rErr++;
        // Step 3: take one supply reading and keep the extremes.
        uint16_t raw = vccRaw();
        if (raw < rawMin)
          rawMin = raw;
        if (raw > rawMax)
          rawMax = raw;
        // Step 4: on a mismatch, note whether either expander shows FF
        // although FF was not written to it, read once more to see whether
        // the wrong value persists, and store the details of the first
        // three.
        if (g != s) {
          bad++;
          if (lowByte(g) == 0xFF && lowByte(s) != 0xFF)
            allHigh++;
          if (highByte(g) == 0xFF && highByte(s) != 0xFF)
            allHigh++;
          uint16_t again = rd();
          if (again == g)
            stuck++;
          if (nd < 3) {
            dIdx[nd] = i;
            dWant[nd] = s;
            dGot[nd] = g;
            dAgain[nd] = again;
            nd++;
          }
        }
        if (d)
          delay(d);
      }
      // Step 5: leave everything off (native write) and report. The
      // highest raw reading is the lowest supply voltage, which is why
      // vccMin is computed from rawMax and vccMax from rawMin.
      put(0, false, 0);
      Serial.print(F("OK b writes "));
      Serial.print(N);
      Serial.print(F(" mismatches "));
      Serial.print(bad);
      Serial.print(F(" portAllHigh "));
      Serial.print(allHigh);
      Serial.print(F(" stillWrongOnReread "));
      Serial.print(stuck);
      Serial.print(F(" writeNak "));
      Serial.print(wErr);
      Serial.print(F(" readNak "));
      Serial.print(rErr);
      Serial.print(F(" vccMin "));
      Serial.print(vccMv(rawMax));
      Serial.print(F(" vccMax "));
      Serial.print(vccMv(rawMin));
      for (uint8_t k = 0; k < nd; k++) {
        Serial.print(F(" | #"));
        Serial.print(dIdx[k]);
        Serial.print(F(" want "));
        hx4(dWant[k]);
        Serial.print(F(" got "));
        hx4(dGot[k]);
        Serial.print(F(" reread "));
        hx4(dAgain[k]);
      }
      Serial.println();
    } else
      Serial.println(F("ERR unknown command"));
  }
}
