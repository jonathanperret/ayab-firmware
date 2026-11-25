// PCF8574 "high-speed code" probe.
//
// Bit-banged I2C on A4 (SDA) / A5 (SCL) so that a deliberately short glitch
// can be injected on SCL or SDA in the middle of a data byte. The port is
// then read back over I2C to see whether the chip ignored the glitch
// (filtered) or acted on it. The question: does the minimum pulse width the
// chip reacts to get shorter after a 0x09 byte (0000 1xxx = Hs-mode master
// code pattern) than after a neutral byte such as 0x11?
//
// Background
//   The I2C specification has fast-mode devices suppress spikes of up to
//   50 ns on SDA and SCL. The I2C high-speed (Hs) mode is entered by
//   sending a "master code" byte of the form 0000 1xxx, after which a
//   device that supports it only suppresses spikes of up to 10 ns. The
//   MCP23008-style write used by the AYAB
//   firmware sends 0x09 (the MCP23008 GPIO register number) as the first
//   data byte, and 0x09 has that same bit pattern. This sketch tests
//   whether a PCF8574 becomes more sensitive to glitches after seeing it.
//
// How it is used
//   There are no serial commands. The sketch runs once after reset and
//   prints a report at 115200 baud, in this order:
//     PCF8574 high-speed-code probe
//     == presence / acknowledge checks ==          see presence()
//     == read-back sanity (written -> read) ==     see readback()
//     == cross-address: ... ==                     see crossAddress()
//     == chip 0x20, glitch on SCL (extra clock) ==          see glitchSweep()
//     == chip 0x20, glitch on SDA (false START/STOP) ==
//     == chip 0x21, glitch on SCL (extra clock) ==
//     == chip 0x21, glitch on SDA (false START/STOP) ==
//     DONE
//   Each glitch table has one row per bus condition (see enum Cond) and one
//   column per glitch width, 62 ns to 1000 ns. A cell shows how the 20
//   trials came out, for example "I20" or "I3A17":
//     I  the chip ignored the glitch (the port holds the byte sent)
//     A  the chip acted on the glitch (the port holds the value expected
//        if the glitch was taken as a real edge)
//     ?  anything else, followed by the last such port value in hex
//   Both expanders are written to 00 (all solenoids off) at the end.
//
// Hardware expected
//   A 16 MHz ATmega328P board (UNO or compatible); the glitch widths are
//   counted in CPU cycles of 62.5 ns. SDA = A4 (PC4), SCL = A5 (PC5),
//   connected to the interface board with its two PCF8574 expanders at 0x20
//   and 0x21. The bus must have external pull-up resistors: the sketch
//   keeps the controller's internal pull-ups off. During the test the
//   expander outputs take the values 3C, A5 and others, so solenoids
//   connected through the ULN2803 drivers will switch.

#include <Arduino.h>
#include <avr/interrupt.h>

// Port C bit masks of the two bus lines.
#define SDA_M _BV(PC4)
#define SCL_M _BV(PC5)

// ADDR       the two expander addresses
// PRESET     value both ports are set to before each trial
// DATA       the data byte that carries the glitch
// SCL_GLITCH_BIT, SDA_GLITCH_BIT
//            bit of DATA (7 = first sent) during whose clock-high time the
//            glitch is injected. The SCL glitch is put on a 0 bit and the
//            SDA glitch on a 1 bit.
// DATA_IF_EXTRA_CLOCK
//            what the port shows if the chip counts the SCL glitch as one
//            more clock pulse: bit 4 is taken twice, the rest of the byte
//            shifts down by one place and bit 0 falls off the end.
// TRIALS     number of repeats of every test
static const uint8_t ADDR[2] = {0x20, 0x21};
static const uint8_t PRESET = 0x3C;
static const uint8_t DATA = 0xA5;        // 1010 0101
static const uint8_t SCL_GLITCH_BIT = 4; // bit value 0
static const uint8_t SDA_GLITCH_BIT = 5; // bit value 1 (SDA released high)
static const uint8_t DATA_IF_EXTRA_CLOCK = 0xA2; // b7 b6 b5 b4 b4 b3 b2 b1
static const uint8_t TRIALS = 20;

// Which line, if any, gets the glitch during a byte.
enum Glitch : uint8_t { G_NONE, G_SCL, G_SDA };

// The bus primitives. Both lines are used open-drain: the port output bit
// stays 0, and a line is pulled low by making its pin an output and
// released by making it an input, leaving the external pull-up to raise it.

// Quarter-bit delay of 5 us. A bit takes four of these plus the time the
// code itself needs, which puts the bit rate below 50 kHz.
static inline void hd() {
  delayMicroseconds(5);
}
// Pulls SDA low.
static inline void sdaLow() {
  DDRC |= SDA_M;
}
// Releases SDA (it goes high unless a device holds it low).
static inline void sdaRel() {
  DDRC &= ~SDA_M;
}
// Pulls SCL low.
static inline void sclLow() {
  DDRC |= SCL_M;
}
// Releases SCL. The code does not wait for a device that holds SCL low
// (clock stretching).
static inline void sclRel() {
  DDRC &= ~SCL_M;
}
// Returns the present level of SDA.
static inline bool sdaRead() {
  return PINC & SDA_M;
}

// Building blocks for the glitch pulse. N1, N2, N4 and N8 are 1, 2, 4 and 8
// "nop" instructions, each lasting one CPU cycle. PULSE(m, NOPS) writes the
// mask m to the PINC register twice with the given nops in between. On this
// processor, writing a 1 to a bit of PINC toggles the matching output bit,
// so the first write takes the line low and the second takes it high again.
// Each write takes one cycle, so the low time is (number of nops + 1)
// cycles.
#define N1 "nop\n"
#define N2 N1 N1
#define N4 N2 N2
#define N8 N4 N4
#define PULSE(m, NOPS)                                                         \
  asm volatile("out %[p], %[r]\n" NOPS                                         \
               "out %[p], %[r]\n" ::[p] "I"(_SFR_IO_ADDR(PINC)),               \
               [r] "r"(m))

// Low pulse of n CPU cycles (62.5 ns each) on a line that is currently
// released and high. The line is driven push-pull for the duration so that
// both edges are sharp, then returned to open-drain.
//   m  port C mask of the line (SDA_M or SCL_M)
//   n  pulse width in CPU cycles; only 1, 2, 3, 4, 6, 8 and 16 are
//      implemented. Any other value produces no pulse, although the line is
//      still driven high for a moment.
// Interrupts are off for the duration, so no interrupt can stretch the
// pulse.
static void pulseLow(uint8_t m, uint8_t n) {
  uint8_t s = SREG;
  cli();
  PORTC |= m; // pull-up on, line still high
  DDRC |= m;  // actively driven high
  switch (n) {
  case 1:
    PULSE(m, "");
    break;
  case 2:
    PULSE(m, N1);
    break;
  case 3:
    PULSE(m, N2);
    break;
  case 4:
    PULSE(m, N2 N1);
    break;
  case 6:
    PULSE(m, N4 N1);
    break;
  case 8:
    PULSE(m, N4 N2 N1);
    break;
  case 16:
    PULSE(m, N8 N4 N2 N1);
    break;
  default:
    break;
  }
  // Back to a released open-drain line: input first, then pull-up off.
  DDRC &= ~m;
  PORTC &= ~m;
  SREG = s;
}

// Sends an I2C START: SDA falls while SCL is high. Leaves both lines low.
static void i2cStart() {
  sdaRel();
  sclRel();
  hd();
  sdaLow();
  hd();
  sclLow();
  hd();
}

// Sends a repeated START (written "Sr" below): with SCL low, SDA is
// released first, then SCL, and then SDA falls while SCL is high. Leaves
// both lines low.
static void i2cRestart() {
  sdaRel();
  hd();
  sclRel();
  hd();
  sdaLow();
  hd();
  sclLow();
  hd();
}

// Sends an I2C STOP: SDA rises while SCL is high. Leaves both lines
// released.
static void i2cStop() {
  sdaLow();
  hd();
  sclRel();
  hd();
  sdaRel();
  hd();
}

// Sends one byte, most significant bit first, optionally with a glitch.
//   b      the byte
//   g      which line to glitch, or G_NONE
//   width  glitch width in CPU cycles, as for pulseLow()
// The glitch is placed in the middle of the clock-high time of one bit:
// bit SCL_GLITCH_BIT for a glitch on SCL, bit SDA_GLITCH_BIT for a glitch
// on SDA. A low pulse on SCL at that point looks like an extra clock pulse.
// A low pulse on SDA while SCL is high looks like a START followed by a
// STOP.
// Returns true if the byte was acknowledged.
static bool i2cWrite(uint8_t b, Glitch g = G_NONE, uint8_t width = 0) {
  // The eight data bits: set SDA while SCL is low, then clock high and low.
  for (int8_t i = 7; i >= 0; i--) {
    if (b & _BV(i))
      sdaRel();
    else
      sdaLow();
    hd();
    sclRel();
    hd();
    if (g == G_SCL && i == SCL_GLITCH_BIT)
      pulseLow(SCL_M, width);
    if (g == G_SDA && i == SDA_GLITCH_BIT)
      pulseLow(SDA_M, width);
    hd();
    sclLow();
    hd();
  }
  // Ninth clock: release SDA and see whether the device pulls it low.
  sdaRel();
  hd();
  sclRel();
  hd();
  bool ack = !sdaRead();
  hd();
  sclLow();
  hd();
  return ack;
}

// Receives one byte, most significant bit first, and returns it.
//   ack  true to acknowledge the byte (more bytes wanted), false to send no
//        acknowledge (last byte)
static uint8_t i2cRead(bool ack) {
  uint8_t v = 0;
  sdaRel();
  // The eight data bits, sampled while SCL is high.
  for (int8_t i = 7; i >= 0; i--) {
    hd();
    sclRel();
    hd();
    if (sdaRead())
      v |= _BV(i);
    hd();
    sclLow();
    hd();
  }
  // Ninth clock: the acknowledge bit, sent by this end.
  if (ack)
    sdaLow();
  else
    sdaRel();
  hd();
  sclRel();
  hd();
  hd();
  sclLow();
  hd();
  sdaRel();
  return v;
}

// Plain single-byte write of v to the expander at 7-bit address addr.
// Returns true if both the address and the data byte were acknowledged.
static bool writePort(uint8_t addr, uint8_t v) {
  i2cStart();
  bool a = i2cWrite(addr << 1);
  a &= i2cWrite(v);
  i2cStop();
  return a;
}

// Reads and returns the port of the expander at 7-bit address addr. The
// acknowledge of the address is not checked; an absent chip reads as 0xFF.
static uint8_t readPort(uint8_t addr) {
  i2cStart();
  i2cWrite((addr << 1) | 1);
  uint8_t v = i2cRead(false);
  i2cStop();
  return v;
}

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hex2(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// ---------------------------------------------------------------------------

// The bus conditions under which the glitched data byte is sent. In the
// notation below S is a START, Sr a repeated START, P a STOP, [T] the write
// address of the chip under test, [O] the write address of the other chip,
// and data* the data byte (DATA) that carries the glitch.
enum Cond : uint8_t {
  C_NONE,    // S [T][data*] P
  C_P11,     // S [T][0x11][data*] P
  C_P09,     // S [T][0x09][data*] P           <- what MCP-style writes do
  C_P0E,     // S [T][0x0E][data*] P
  C_HS,      // S [0x08] Sr [T][data*] P       <- legitimate Hs-mode entry
  C_OTHER11, // S [O][0x11] Sr [T][data*] P
  C_OTHER09, // S [O][0x09] Sr [T][data*] P    <- T saw 0x09 while not addressed
  C_COUNT
};

// Row labels for the glitch tables, in the order of enum Cond.
static const char *const COND_NAME[C_COUNT] = {
    "no-prefix",    "prefix-11",     "prefix-09",    "prefix-0E",
    "real-HS-code", "other-chip-11", "other-chip-09"};

// The glitch widths tried, in CPU cycles of 62.5 ns: 62.5 ns to 1 us.
static const uint8_t WIDTHS[] = {1, 2, 3, 4, 6, 8, 16};

// Runs one glitched write; returns the port value read back afterwards.
//   c          bus condition (what precedes the glitched byte)
//   t          index into ADDR of the chip under test (0 or 1)
//   g          line to glitch (G_SCL or G_SDA)
//   width      glitch width in CPU cycles
//   ifStopped  receives the value the port is expected to hold if the chip
//              abandoned the transfer at the glitch: the last complete byte
//              it had been given, which is the prefix byte when one was
//              sent to this chip and PRESET otherwise
static uint8_t trial(Cond c, uint8_t t, Glitch g, uint8_t width,
                     uint8_t *ifStopped) {
  const uint8_t T = ADDR[t], O = ADDR[1 - t];
  // Step 1: put both ports in a known state.
  writePort(T, PRESET);
  writePort(O, PRESET);
  *ifStopped = PRESET;
  // Step 2: START, then whatever the condition calls for, up to and
  // including the address of the chip under test.
  i2cStart();
  switch (c) {
  case C_NONE:
    i2cWrite(T << 1);
    break;
  case C_P11:
    i2cWrite(T << 1);
    i2cWrite(0x11);
    *ifStopped = 0x11;
    break;
  case C_P09:
    i2cWrite(T << 1);
    i2cWrite(0x09);
    *ifStopped = 0x09;
    break;
  case C_P0E:
    i2cWrite(T << 1);
    i2cWrite(0x0E);
    *ifStopped = 0x0E;
    break;
  case C_HS:
    i2cWrite(0x08);
    i2cRestart();
    i2cWrite(T << 1);
    break;
  case C_OTHER11:
    i2cWrite(O << 1);
    i2cWrite(0x11);
    i2cRestart();
    i2cWrite(T << 1);
    break;
  case C_OTHER09:
    i2cWrite(O << 1);
    i2cWrite(0x09);
    i2cRestart();
    i2cWrite(T << 1);
    break;
  default:
    break;
  }
  // Step 3: the data byte with the glitch in it, STOP, and a read-back.
  i2cWrite(DATA, g, width);
  i2cStop();
  return readPort(T);
}

// Prints one glitch table: every bus condition against every glitch width,
// TRIALS trials per cell.
//   t  index into ADDR of the chip under test (0 or 1)
//   g  line to glitch (G_SCL or G_SDA)
// Each trial is classified by the port value read back afterwards:
//   DATA                      the glitch was ignored (I)
//   DATA_IF_EXTRA_CLOCK       an SCL glitch was taken as a clock pulse (A)
//   the trial's "ifStopped"   an SDA glitch was taken as START/STOP (A)
//   anything else             counted as "?"; the last such value is shown
static void glitchSweep(uint8_t t, Glitch g) {
  Serial.print(F("\n== chip 0x"));
  hex2(ADDR[t]);
  Serial.print(g == G_SCL ? F(", glitch on SCL (extra clock)")
                          : F(", glitch on SDA (false START/STOP)"));
  Serial.println(F(" =="));
  Serial.println(
      F("   per width: I=ignored  A=acted on  ?=other (last odd value shown)"));
  for (uint8_t c = 0; c < C_COUNT; c++) {
    // Row label, padded to 15 characters.
    Serial.print(F("  "));
    Serial.print(COND_NAME[c]);
    for (uint8_t pad = strlen(COND_NAME[c]); pad < 15; pad++)
      Serial.print(' ');
    for (uint8_t wi = 0; wi < sizeof(WIDTHS); wi++) {
      // Run the trials for this cell and count the outcomes.
      uint8_t ign = 0, act = 0, oth = 0, odd = 0;
      for (uint8_t k = 0; k < TRIALS; k++) {
        uint8_t ifStopped;
        uint8_t v = trial((Cond)c, t, g, WIDTHS[wi], &ifStopped);
        uint8_t acted = (g == G_SCL) ? DATA_IF_EXTRA_CLOCK : ifStopped;
        if (v == DATA)
          ign++;
        else if (v == acted)
          act++;
        else {
          oth++;
          odd = v;
        }
      }
      // Print the cell: the width in nanoseconds (cycles * 62.5, rounded
      // down), then each non-zero count with its letter.
      Serial.print(F(" | "));
      Serial.print((uint16_t)WIDTHS[wi] * 125 / 2);
      Serial.print(F("ns "));
      if (ign) {
        Serial.print('I');
        Serial.print(ign);
      }
      if (act) {
        Serial.print('A');
        Serial.print(act);
      }
      if (oth) {
        Serial.print('?');
        Serial.print(oth);
        Serial.print('(');
        hex2(odd);
        Serial.print(')');
      }
    }
    Serial.println();
  }
}

// Prints the basic acknowledge behaviour of the two chips, without any
// glitch:
//   1. whether each expander acknowledges its own address;
//   2. whether anything acknowledges the bytes 0x00, 0x08, 0x09 and 0x0F
//      sent as the first byte after a START, where an address would
//      normally be (0x00 is the I2C general call; the other three have the
//      high-speed master code pattern 0000 1xxx);
//   3. for each expander, the three acknowledge bits (1 = acknowledged) of
//      an MCP-style write [address][0x09][DATA], and what the port reads
//      afterwards.
static void presence() {
  Serial.println(F("\n== presence / acknowledge checks =="));
  for (uint8_t t = 0; t < 2; t++) {
    i2cStart();
    bool a = i2cWrite(ADDR[t] << 1);
    i2cStop();
    Serial.print(F("  address 0x"));
    hex2(ADDR[t]);
    Serial.println(a ? F(": ACK") : F(": no answer"));
  }
  static const uint8_t first[] = {0x00, 0x08, 0x09, 0x0F};
  for (uint8_t i = 0; i < sizeof(first); i++) {
    i2cStart();
    bool a = i2cWrite(first[i]);
    i2cStop();
    Serial.print(F("  first byte 0x"));
    hex2(first[i]);
    Serial.println(a ? F(": ACK") : F(": NACK"));
  }
  for (uint8_t t = 0; t < 2; t++) {
    i2cStart();
    bool a0 = i2cWrite(ADDR[t] << 1);
    bool a1 = i2cWrite(0x09);
    bool a2 = i2cWrite(DATA);
    i2cStop();
    Serial.print(F("  MCP-style write to 0x"));
    hex2(ADDR[t]);
    Serial.print(F(": acks addr/0x09/data = "));
    Serial.print(a0);
    Serial.print('/');
    Serial.print(a1);
    Serial.print('/');
    Serial.print(a2);
    Serial.print(F(", port reads 0x"));
    hex2(readPort(ADDR[t]));
    Serial.println();
  }
}

// Checks that plain writes and reads work with this bit-banged bus: writes
// ten different values to each expander and reads each one back 2 ms later.
// Prints every "written->read" pair and OK or MISMATCH per chip.
static void readback() {
  Serial.println(F("\n== read-back sanity (written -> read) =="));
  static const uint8_t vals[] = {0x00, 0xFF, 0x55, 0xAA, 0xA5,
                                 0xA2, 0x3C, 0x09, 0x11, 0x0E};
  for (uint8_t t = 0; t < 2; t++) {
    Serial.print(F("  0x"));
    hex2(ADDR[t]);
    Serial.print(':');
    bool ok = true;
    for (uint8_t i = 0; i < sizeof(vals); i++) {
      writePort(ADDR[t], vals[i]);
      delay(2);
      uint8_t v = readPort(ADDR[t]);
      Serial.print(' ');
      hex2(vals[i]);
      Serial.print(F("->"));
      hex2(v);
      if (v != vals[i])
        ok = false;
    }
    Serial.println(ok ? F("  OK") : F("  MISMATCH"));
  }
}

// Does a chip that was not addressed react to later bytes that look like
// its own address?
// One transaction is sent to chip A whose data bytes are, in order, an
// optional prefix (none, 0x11 or 0x09), the write address of the other
// chip B, and 0x5A. If the chips behave properly, A ends up showing 0x5A
// (the last data byte) and B still shows PRESET (0x3C). Each case is
// repeated TRIALS times; the line printed gives the values read in the
// last trial and the number of trials in which either value was wrong.
static void crossAddress() {
  Serial.println(
      F("\n== cross-address: S [A][prefix][B's write address][0x5A] P =="));
  static const uint8_t prefixes[] = {0xFF /* = none */, 0x11, 0x09};
  for (uint8_t a = 0; a < 2; a++) {
    const uint8_t A = ADDR[a], B = ADDR[1 - a];
    for (uint8_t p = 0; p < sizeof(prefixes); p++) {
      uint8_t bad = 0, lastB = 0, lastA = 0;
      for (uint8_t k = 0; k < TRIALS; k++) {
        // Known starting state on both ports.
        writePort(A, PRESET);
        writePort(B, PRESET);
        // The transaction under test.
        i2cStart();
        i2cWrite(A << 1);
        if (prefixes[p] != 0xFF)
          i2cWrite(prefixes[p]);
        i2cWrite(B << 1);
        i2cWrite(0x5A);
        i2cStop();
        // Read both ports and compare with the expected values.
        lastB = readPort(B);
        lastA = readPort(A);
        if (lastB != PRESET || lastA != 0x5A)
          bad++;
      }
      Serial.print(F("  A=0x"));
      hex2(A);
      Serial.print(F(" prefix="));
      if (prefixes[p] == 0xFF)
        Serial.print(F("none"));
      else {
        Serial.print(F("0x"));
        hex2(prefixes[p]);
      }
      Serial.print(F(": A reads 0x"));
      hex2(lastA);
      Serial.print(F(" (want 5A), B reads 0x"));
      hex2(lastB);
      Serial.print(F(" (want 3C), bad trials "));
      Serial.print(bad);
      Serial.print('/');
      Serial.println(TRIALS);
    }
  }
}

// Runs the whole probe once and prints the report.
void setup() {
  // Select AVCC as the ADC reference. On the UNO clone used for this work the
  // program crashes at random with the default setting (see JOURNAL.md,
  // entries 9 to 15); this ties the AREF capacitor to AVCC and stops it.
  ADMUX = _BV(REFS0);
  // Release both bus lines with the internal pull-ups off: output bits 0,
  // pins as inputs.
  PORTC &= ~(SDA_M | SCL_M);
  DDRC &= ~(SDA_M | SCL_M);
  Serial.begin(115200);
  delay(200);
  Serial.println(F("\nPCF8574 high-speed-code probe"));
  // The checks without glitches first, then the four glitch tables.
  presence();
  readback();
  crossAddress();
  for (uint8_t t = 0; t < 2; t++) {
    glitchSweep(t, G_SCL);
    glitchSweep(t, G_SDA);
  }
  // Leave every solenoid off.
  writePort(ADDR[0], 0x00);
  writePort(ADDR[1], 0x00);
  Serial.println(F("\nDONE"));
}

// Nothing to do after the report; press reset to run it again.
void loop() {
}
