// Edge test for the PCF8574 reset seen on the machine: which switching event
// resets the expander? Each trial works on ONE expander, with the other all
// off.
//
// Purpose
//   A "reset" here means that the expander's port reads FF (all eight
//   solenoids on) although something else was written to it. Each trial
//   switches a chosen pattern of solenoids on, leaves it on for a chosen
//   time, performs one chosen switching event, and reads the
//   port back 2 ms later to see whether the expander survived. Running many
//   trials gives a reset rate for that event.
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) connected by I2C (SDA = A4,
//   SCL = A5) to the interface board with its two PCF8574 expanders at 0x20
//   and 0x21, each driving a ULN2803 and eight solenoids. A 1 bit in the
//   byte written to an expander switches that solenoid on.
//
// At start-up both expanders are written to 00 and one line is printed:
//   READY edgetest serial N..N vcc V state HHLL
//     N..N  the controller chip's ten-byte serial number, hex
//     V     controller supply voltage, millivolts
//     HHLL  ports read back, hex: HH from 0x21, LL from 0x20
//
// Command (115200 baud), all numbers decimal except the three hex bytes:
//   t AA PP OO M G U N C [BB]
//     AA  expander address, hex (20 = solenoids 0-7, 21 = solenoids 8-15)
//     PP  pattern switched on first, hex
//     OO  byte written to switch off, hex (00 = everything)
//     M   mode: 0 = switch off and leave off
//               1 = one two-byte write [OO][PP]: off, then back on about
//                   90 us later
//               2 = switch off, wait G us, switch the pattern back on (two
//                   writes)
//               3 = switch the pattern's solenoids off one at a time, G us
//                   apart
//               4 = one three-byte write [OO][BB][PP]: off, back on in two
//                   stages about 90 us apart
//               5 = as mode 1, but bit-banged through the pins instead of
//                   sent by the I2C hardware
//               6 = as mode 5, with the expander first put in its high-speed
//                   mode (start, the code 0000 1000, repeated start): its bus
//                   input filters are then at their fast setting until the
//                   stop that ends the write
//               7 = as mode 4, bit-banged
//               8 = as mode 7, in high-speed mode
//     G   gap in microseconds (modes 2 and 3)
//     U   time the pattern is left on before the event, microseconds
//     N   number of trials
//     C   rest between trials, milliseconds, everything off
//     BB  optional, hex: for mode 2, the byte written after the gap instead
//         of PP; for mode 4, the first stage. Defaults to PP.
// Reply: OK t resets R other X wnak W dirty D
//   resets  trials after which the port read FF although something else was
//           written
//   other   trials with any other wrong read-back
//   wnak    writes not acknowledged
//   dirty   trials that did not start from a clean all-off state
//   " hung 1" is added to the end of the reply if any I2C operation has
//   timed out (bus stuck for more than 25 ms) since this was last reported,
//   whether during this command or an earlier one.
// Also: r = read both ports, z = write 00 to both, v = controller supply in mV.
//   w AA VV = write byte VV (hex) to the expander at address AA (hex) and
//   leave it there.
// Replies: "OK r HHLL", "OK z", "OK v V", "OK w HHLL" (ports read back
// after the write, HH from 0x21 and LL from 0x20). Anything else gets
// "ERR unknown command".
//
// About the 90 us in modes 1 and 4: a PCF8574 puts every data byte of a
// write on its port as soon as that byte has been received, so a multi-byte
// write is a quick succession of port states one byte time apart. At the
// Wire library's default 100 kHz, one byte and its acknowledge take 90 us.
//
// The script tools/edge_session.py drives this sketch.
#include <Arduino.h>
#include <Wire.h>
#include <avr/boot.h>

// Number of I2C writes that were not acknowledged. It is cleared at the
// start of each t command and reported in its reply.
static uint16_t wnak;

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx2(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Writes the single byte v to the expander at I2C address a.
// A write that fails for any reason is counted in wnak.
static void wr1(uint8_t a, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(v);
  if (Wire.endTransmission())
    wnak++;
}

// Writes two bytes, first and then v, to the expander at address a in one
// I2C transaction. The port shows "first" for one byte time (about 90 us)
// and then v. A failed write is counted in wnak.
static void wr2(uint8_t a, uint8_t first, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(first);
  Wire.write(v);
  if (Wire.endTransmission())
    wnak++;
}

// Writes three bytes, first, second and then v, to the expander at address
// a in one I2C transaction. The port steps through the three values about
// 90 us apart. A failed write is counted in wnak.
static void wr3(uint8_t a, uint8_t first, uint8_t second, uint8_t v) {
  Wire.beginTransmission(a);
  Wire.write(first);
  Wire.write(second);
  Wire.write(v);
  if (Wire.endTransmission())
    wnak++;
}

// Reads and returns the port of the expander at address a. If the chip does
// not answer, the result is FF and no error is recorded.
// ---- Bit-banged writes (modes 5 to 8) --------------------------------
// The two bus lines as plain port C pins. A line is driven low by making
// its pin an output (the port bit is kept at 0) and released by making it
// an input, leaving the board's pull-up to raise it.
static const uint8_t BB_SDA = _BV(PC4);
static const uint8_t BB_SCL = _BV(PC5);
static const uint8_t BB_HALF_US = 4; // half a clock period: about 100 kHz
static inline void bbScl(bool released) {
  if (released)
    DDRC &= (uint8_t)~BB_SCL;
  else
    DDRC |= BB_SCL;
}
static inline void bbSda(bool released) {
  if (released)
    DDRC &= (uint8_t)~BB_SDA;
  else
    DDRC |= BB_SDA;
}
// Clock one byte out, most significant bit first, then read the
// acknowledge bit. Returns true if the byte was acknowledged. On entry and
// on exit the clock is low.
static bool bbByte(uint8_t value) {
  for (uint8_t mask = 0x80; mask != 0; mask >>= 1) {
    bbSda((value & mask) != 0);
    delayMicroseconds(BB_HALF_US);
    bbScl(true);
    delayMicroseconds(BB_HALF_US);
    bbScl(false);
  }
  bbSda(true);
  delayMicroseconds(BB_HALF_US);
  bbScl(true);
  delayMicroseconds(BB_HALF_US);
  bool ack = (PINC & BB_SDA) == 0;
  bbScl(false);
  return ack;
}
// Write up to three data bytes to expander "a" by bit-banging. With
// "fast" set, the write is preceded by the high-speed code, which the
// expander does not acknowledge and which switches its input filters to
// their fast setting until the stop. Every data or address byte that is
// not acknowledged adds one to wnak.
static void bbWrite(uint8_t a, const uint8_t *data, uint8_t count, bool fast) {
  // Take the pins from the I2C hardware. Wire switches on the internal
  // pull-ups by setting the port bits; clear them before driving.
  TWCR = 0;
  PORTC &= (uint8_t)~(BB_SDA | BB_SCL);
  // Start: data falls while the clock is high.
  bbSda(false);
  delayMicroseconds(BB_HALF_US);
  bbScl(false);
  if (fast) {
    bbByte(0x08); // the high-speed code; no acknowledge is expected
    // Repeated start.
    bbSda(true);
    delayMicroseconds(BB_HALF_US);
    bbScl(true);
    delayMicroseconds(BB_HALF_US);
    bbSda(false);
    delayMicroseconds(BB_HALF_US);
    bbScl(false);
  }
  if (!bbByte((uint8_t)(a << 1)))
    wnak++;
  for (uint8_t k = 0; k < count; k++) {
    if (!bbByte(data[k]))
      wnak++;
  }
  // Stop: data rises while the clock is high. Then hand the pins back.
  bbSda(false);
  delayMicroseconds(BB_HALF_US);
  bbScl(true);
  delayMicroseconds(BB_HALF_US);
  bbSda(true);
  delayMicroseconds(BB_HALF_US);
  Wire.begin();
  Wire.setWireTimeout(25000, true);
}

static uint8_t rd1(uint8_t a) {
  Wire.requestFrom(a, (uint8_t)1);
  return Wire.read();
}

// Waits for the given number of microseconds.
// The Arduino delayMicroseconds() is only accurate up to 16383 us, so waits
// of 16 ms or more are split into whole milliseconds, done with delay(),
// and a remainder of less than 1 ms.
static void waitUs(uint32_t us) {
  if (us >= 16000UL) {
    delay(us / 1000UL);
    us %= 1000UL;
  }
  if (us)
    delayMicroseconds((unsigned int)us);
}

// Returns the controller's own supply voltage in millivolts.
// The ADC measures the chip's internal 1.1 V reference (channel 0x0E) with
// the supply (AVCC) as full scale. The reading is 1.1 V / supply * 1023,
// so supply in mV = 1100 * 1023 / reading = 1125300 / reading. The input
// is given 300 us to settle after the channel is selected, and of the two
// conversions only the second is used.
static uint16_t vccMv() {
  ADMUX = _BV(REFS0) | 0x0E;
  delayMicroseconds(300);
  ADCSRA |= _BV(ADSC);
  while (ADCSRA & _BV(ADSC)) {
  }
  ADCSRA |= _BV(ADSC);
  while (ADCSRA & _BV(ADSC)) {
  }
  return 1125300L / ADC;
}

// Switches everything off, then opens the serial port and prints READY.
void setup() {
  // ADC on, clock prescaler 128 (125 kHz ADC clock from the 16 MHz crystal).
  ADCSRA = _BV(ADEN) | 7;
  Wire.begin();
  // I2C timeout of 25000 us; the second argument makes the library reset
  // the I2C hardware when the timeout strikes.
  Wire.setWireTimeout(
      25000,
      true); // a stuck bus is reported ("hung") instead of freezing the sketch
  wr1(0x20, 0);
  wr1(0x21, 0);
  Serial.begin(115200);
  Serial.print(F("READY edgetest serial "));
  // Chip serial number: signature row bytes 0x0E to 0x17.
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx2(boot_signature_byte_get(a));
  Serial.print(F(" vcc "));
  Serial.print(vccMv());
  Serial.print(F(" state "));
  hx2(rd1(0x21));
  hx2(rd1(0x20));
  Serial.println();
}

// Collects characters into a line and executes the line when it ends.
void loop() {
  static char buf[64];  // the command line being received
  static uint8_t n = 0; // number of characters in buf so far
  while (Serial.available()) {
    // Gather characters until a line end (CR or LF). Characters beyond 63
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
    char *p = buf + 1;
    if (buf[0] == 'r') {
      // r: read both ports.
      Serial.print(F("OK r "));
      hx2(rd1(0x21));
      hx2(rd1(0x20));
      Serial.println();
    } else if (buf[0] == 'z') {
      // z: everything off.
      wr1(0x20, 0);
      wr1(0x21, 0);
      Serial.println(F("OK z"));
    } else if (buf[0] == 'w') {
      uint8_t a = strtoul(p, &p, 16), v = strtoul(p, &p, 16);
      wr1(a, v);
      Serial.print(F("OK w "));
      hx2(rd1(0x21));
      hx2(rd1(0x20));
      Serial.println();
    } // w AA VV: write and leave
    else if (buf[0] == 'v') {
      // v: controller supply voltage.
      Serial.print(F("OK v "));
      Serial.println(vccMv());
    } else if (buf[0] == 't') {
      // t: run N trials of one switching event.
      // Step 1: parse the fields (see the top of the file).
      uint8_t addr = strtoul(p, &p, 16), pat = strtoul(p, &p, 16),
              off = strtoul(p, &p, 16), mode = strtoul(p, &p, 10);
      uint32_t gap = strtoul(p, &p, 10), onUs = strtoul(p, &p, 10);
      uint16_t N = strtoul(p, &p, 10), cool = strtoul(p, &p, 10);
      char *q;
      uint8_t back = strtoul(p, &q, 16);
      if (q == p)
        back = pat; // optional 9th field: what mode 2 switches on, default the
                    // starting pattern
      // Step 2: switch the other expander fully off and clear the counters.
      uint8_t other = (addr == 0x20) ? 0x21 : 0x20;
      uint16_t resets = 0, wrong = 0, dirty = 0;
      wnak = 0;
      wr1(other, 0);
      for (uint16_t i = 0; i < N; i++) {
        // Step 3: make sure the trial starts with everything off. If the
        // port does not read 00, count the trial as dirty, write 00 and
        // rest; if it still does not read 00, write 00 and rest once more.
        if (rd1(addr) != 0) {
          dirty++;
          wr1(addr, 0);
          delay(cool);
          if (rd1(addr) != 0) {
            wr1(addr, 0);
            delay(cool);
          }
        }
        // Step 4: switch the pattern on and leave it on for onUs.
        wr1(addr, pat);
        waitUs(onUs);
        // Step 5: the switching event. "expect" is what the port should
        // read afterwards.
        uint8_t expect = pat;
        if (mode == 0) {
          // Off, and stay off.
          wr1(addr, off);
          expect = off;
        } else if (mode == 1) {
          // Off and back on within one transaction.
          wr2(addr, off, pat);
        } else if (mode == 2) {
          // Off, wait, on again (pattern "back"), as two transactions.
          wr1(addr, off);
          waitUs(gap);
          wr1(addr, back);
          expect = back;
        } else if (mode == 4) {
          // Off, intermediate stage "back", full pattern, in one
          // transaction.
          wr3(addr, off, back, pat);
        } else if (mode == 5 || mode == 6) {
          // As mode 1, bit-banged; mode 6 in high-speed mode.
          const uint8_t bytes[2] = {off, pat};
          bbWrite(addr, bytes, 2, mode == 6);
        } else if (mode == 7 || mode == 8) {
          // As mode 4, bit-banged; mode 8 in high-speed mode.
          const uint8_t bytes[3] = {off, back, pat};
          bbWrite(addr, bytes, 3, mode == 8);
        } else {
          // Mode 3 (and any other number): switch off, one solenoid per
          // write starting from bit 0, each solenoid that is on in the
          // pattern and off in the "off" byte, waiting "gap" after each
          // write.
          uint8_t cur = pat;
          for (uint8_t b = 0; b < 8; b++) {
            uint8_t m = _BV(b);
            if ((pat & m) && !(off & m)) {
              cur &= ~m;
              wr1(addr, cur);
              waitUs(gap);
            }
          }
          expect = cur;
        }
        // Step 6: 2 ms after the event, read the port and classify the
        // result. FF where something else was expected counts as a reset;
        // any other difference counts as "other".
        delay(2);
        uint8_t got = rd1(addr);
        if (got != expect) {
          if (got == 0xFF)
            resets++;
          else
            wrong++;
        }
        // Step 7: everything off, and rest before the next trial.
        wr1(addr, 0);
        delay(cool);
      }
      // Step 8: report the totals.
      Serial.print(F("OK t resets "));
      Serial.print(resets);
      Serial.print(F(" other "));
      Serial.print(wrong);
      Serial.print(F(" wnak "));
      Serial.print(wnak);
      Serial.print(F(" dirty "));
      Serial.print(dirty);
      if (Wire.getWireTimeoutFlag()) {
        Serial.print(F(" hung 1"));
        Wire.clearWireTimeoutFlag();
      }
      Serial.println();
    } else
      Serial.println(F("ERR unknown command"));
  }
}
