/*!
 * \file pcfprobe.cpp
 * \brief Diagnostic for the I2C port expanders, run when hardware test
 *        mode starts. Temporary investigation code, not for release.
 *
 *    This file is part of AYAB.
 *
 *    AYAB is free software: you can redistribute it and/or modify
 *    it under the terms of the GNU General Public License as published by
 *    the Free Software Foundation, either version 3 of the License, or
 *    (at your option) any later version.
 *
 *    AYAB is distributed in the hope that it will be useful,
 *    but WITHOUT ANY WARRANTY; without even the implied warranty of
 *    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *    GNU General Public License for more details.
 *
 *    You should have received a copy of the GNU General Public License
 *    along with AYAB.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <Arduino.h>
#include <Wire.h>
#include <avr/boot.h>
#include <avr/pgmspace.h>

#include "beeper.h"
#include "com.h"
#include "pcfprobe.h"

namespace {

constexpr uint8_t PROBE_VERSION = 8U;
constexpr uint8_t ADDR_LO = 0x20U; ///< expander for solenoids 0-7
constexpr uint8_t ADDR_HI = 0x21U; ///< expander for solenoids 8-15
constexpr uint8_t WRITES_PER_CELL = 100U;
constexpr uint16_t SOAK_WRITES = 2000U;
constexpr uint16_t SOAK_CHUNK = 200U; ///< soak writes done per call of pcfProbeStep()
constexpr uint8_t MAX_DETAILS = 4U;
constexpr uint8_t REPLAY_REPEATS = 10U;  ///< times each replay sequence is run
constexpr uint8_t REPLAY_SETTLE_MS = 4U; ///< wait after each replay write, so that coil current builds up

// Bit-banged write test (see bitbangTest() below).
constexpr uint8_t BITBANG_TRIALS = 10U;    ///< trials per variant
constexpr uint8_t BITBANG_PATTERN = 0x7FU; ///< solenoids 8 to 14, on the expander that resets
constexpr uint8_t BITBANG_ON_MS = 5U;      ///< time the solenoids are on before being switched off
constexpr uint16_t BITBANG_HOLD_US = 300U; ///< how long a bus state is held when a variant holds it
constexpr uint8_t BITBANG_HALF_US = 4U;    ///< half a clock period: about 100 kHz, like the I2C hardware
constexpr uint8_t BITBANG_REST_MS = 30U;   ///< rest between trials, everything off
constexpr uint8_t BITBANG_SDA = _BV(PC4);  ///< the I2C pins as plain port C pins
constexpr uint8_t BITBANG_SCL = _BV(PC5);
// What a variant does differently from an ordinary write.
constexpr uint8_t BITBANG_WIRE = 0x01U; ///< not bit-banged at all: the I2C hardware, as a reference
constexpr uint8_t BITBANG_LOW = 0x02U;  ///< clock held low for BITBANG_HOLD_US before the acknowledge pulse
constexpr uint8_t BITBANG_HIGH = 0x04U; ///< clock left high for BITBANG_HOLD_US during the acknowledge pulse
constexpr uint8_t BITBANG_DATA = 0x08U; ///< data line also held low by the controller from the last data bit on

/// Size of the buffer for one line of the report. Com's message buffer
/// holds 64 bytes including the message id, so lines must stay under 62
/// characters.
///
/// The firmware has little RAM to spare, and whatever this file keeps in
/// static variables is taken from the stack for good, during knitting too.
/// So lines are built in a buffer on the stack, all text is kept in flash,
/// and the static state below is held to a few dozen bytes.
constexpr uint8_t LINE_LEN = 62U;

// Survives a restart of the sketch that is not a power-on, so that a
// controller which restarts by itself can be told from one that was reset
// once by opening the serial port.
uint16_t bootMagic __attribute__((section(".noinit")));
uint16_t bootCount __attribute__((section(".noinit")));

struct Totals {
  uint16_t bad;      ///< writes that read back wrong
  uint16_t portFF;   ///< ports found at 0xFF when something else was written
  uint16_t stuck;    ///< wrong value still there on a second read
  uint16_t writeNak; ///< writes not acknowledged
  uint16_t readNak;  ///< reads not acknowledged
};

uint8_t numDetails = 0; ///< wrong read-backs reported in detail so far
uint16_t ffLowBank = 0;  ///< times the port for solenoids 0-7 was found at FF without having been written so
uint16_t ffHighBank = 0; ///< the same for the port for solenoids 8-15
uint16_t vccRawMin = 1023U; // raw ADC reading; a higher reading is a lower supply
uint16_t vccRawMax = 0U;

void say(const char *line) {
  GlobalCom::sendMsg(AYAB_API::testRes, line);
}

/// Raw reading of the internal 1.1 V reference against the supply.
uint16_t vccRaw() {
  ADMUX = _BV(REFS0) | 0x0EU;
  delayMicroseconds(250);
  ADCSRA |= _BV(ADSC);
  while ((ADCSRA & _BV(ADSC)) != 0U) {
  }
  return ADC;
}

uint16_t vccMillivolts(uint16_t raw) {
  return (raw != 0U) ? static_cast<uint16_t>(1125300UL / raw) : 0U;
}

/// Write one port. `style` 0 is the PCF8574's native single byte; any
/// other value sends two bytes, `prefix` first.
uint8_t writePort(uint8_t address, uint8_t style, uint8_t prefix, uint8_t value) {
  Wire.beginTransmission(address);
  if (style != 0U) {
    Wire.write(prefix);
  }
  Wire.write(value);
  return Wire.endTransmission();
}

uint8_t writeBoth(uint8_t style, uint8_t prefix, uint16_t state) {
  uint8_t err = writePort(ADDR_LO, style, prefix, lowByte(state));
  err |= writePort(ADDR_HI, style, prefix, highByte(state));
  return err;
}

uint16_t readBoth(uint8_t *naks) {
  uint8_t n0 = Wire.requestFrom(ADDR_LO, static_cast<uint8_t>(1U));
  uint8_t lo = Wire.read();
  uint8_t n1 = Wire.requestFrom(ADDR_HI, static_cast<uint8_t>(1U));
  uint8_t hi = Wire.read();
  if (naks != nullptr) {
    *naks = ((n0 != 1U) ? 1U : 0U) + ((n1 != 1U) ? 1U : 0U);
  }
  return (static_cast<uint16_t>(hi) << 8) | lo;
}

uint8_t bitsSet(uint16_t v) {
  uint8_t n = 0;
  for (; v != 0U; v >>= 1) {
    n += static_cast<uint8_t>(v & 1U);
  }
  return n;
}

/// Report one wrong read-back in full, as soon as it happens.
/// Style 0 is the native write, shown as "nat"; the others show their
/// first byte.
void reportDetail(uint8_t style, uint8_t prefix, uint16_t a, uint16_t index, uint16_t want, uint16_t got,
                  uint16_t again) {
  char line[LINE_LEN];
  if (style == 0U) {
    snprintf_P(line, sizeof(line), PSTR("bad nat %u on #%u want %04X got %04X re %04X\n"), bitsSet(a), index, want, got,
               again);
  } else {
    snprintf_P(line, sizeof(line), PSTR("bad p%02X %u on #%u want %04X got %04X re %04X\n"), prefix, bitsSet(a), index,
               want, got, again);
  }
  say(line);
}

/// `count` writes alternating between `a` and `a` with solenoid 0
/// toggled, each followed by a read-back of both ports. `firstIndex`
/// numbers the writes when a long run is done in several calls.
void burst(uint8_t style, uint8_t prefix, uint16_t a, uint16_t firstIndex, uint16_t count, Totals &t) {
  for (uint16_t i = firstIndex; i < (firstIndex + count); i++) {
    uint16_t want = ((i & 1U) != 0U) ? static_cast<uint16_t>(a ^ 0x0001U) : a;
    uint8_t naks = 0;
    if (writeBoth(style, prefix, want) != 0U) {
      t.writeNak++;
    }
    uint16_t got = readBoth(&naks);
#ifdef PCFPROBE_INJECT_FAULT
    // Bench check of the reporting path, which a healthy board never
    // exercises: pretend one read-back in every burst found the upper port
    // at FF. Never define this in a build that leaves the bench.
    if (i == 7U) {
      got |= 0xFF00U;
    }
#endif // PCFPROBE_INJECT_FAULT
    if (naks != 0U) {
      t.readNak++;
    }
    uint16_t raw = vccRaw();
    if (raw < vccRawMin) {
      vccRawMin = raw;
    }
    if (raw > vccRawMax) {
      vccRawMax = raw;
    }
    if (got != want) {
      t.bad++;
      if ((lowByte(got) == 0xFFU) && (lowByte(want) != 0xFFU)) {
        t.portFF++;
        ffLowBank++;
      }
      if ((highByte(got) == 0xFFU) && (highByte(want) != 0xFFU)) {
        t.portFF++;
        ffHighBank++;
      }
      uint16_t again = readBoth(nullptr);
      if (again == got) {
        t.stuck++;
      }
      if (numDetails < MAX_DETAILS) {
        numDetails++;
        reportDetail(style, prefix, a, i, want, got, again);
      }
    }
    delay(1);
  }
}

/// A line is driven low, released, and read 0.2 ms later: it only comes
/// back high that fast if there is a pull-up resistor on it.
bool pulledUp(uint8_t pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delay(2);
  pinMode(pin, INPUT);
  delayMicroseconds(200);
  return digitalRead(pin) != LOW;
}

extern "C" char __heap_start;

/// Fill the unused RAM below the stack with a marker...
void paintFreeRam() {
  for (char *p = &__heap_start; p < (reinterpret_cast<char *>(SP) - 16); p++) {
    *p = static_cast<char>(0xA5);
  }
}

/// ...and count how much of it was never touched: the least free RAM
/// there has been since it was painted.
uint16_t untouchedRam() {
  uint16_t n = 0;
  for (const char *p = &__heap_start; (p < reinterpret_cast<char *>(SP)) && (*p == static_cast<char>(0xA5)); p++) {
    n++;
  }
  return n;
}

const uint16_t patterns[] PROGMEM = {0x8000U, 0x8002U, 0x8606U, 0xB636U, 0xF676U, 0xFFFFU};
// style 0 is native; the others are two-byte writes with this first byte
const uint8_t prefixes[] PROGMEM = {0x00U, 0x00U, 0x09U, 0x11U, 0xFFU};
constexpr uint8_t NUM_PATTERNS = sizeof(patterns) / sizeof(patterns[0]);
constexpr uint8_t NUM_STYLES = sizeof(prefixes);
constexpr uint8_t NUM_CELLS = NUM_PATTERNS * NUM_STYLES;
/// Steps shown to the user as "[n/total]": one per table row, one per
/// replay, one per bit-banged variant, the soak, and the summary.
/// The replay runs four times: one solenoid at a time and adding up, each
/// with the native write and with the two-byte write starting 0x09.
constexpr uint8_t NUM_REPLAYS = 4U;
const uint8_t bitbangVariants[] PROGMEM = {BITBANG_WIRE,
                                        0U,
                                        BITBANG_LOW,
                                        BITBANG_HIGH,
                                        BITBANG_LOW | BITBANG_HIGH,
                                        BITBANG_DATA,
                                        BITBANG_HIGH | BITBANG_DATA};
constexpr uint8_t NUM_BITBANG = sizeof(bitbangVariants);
constexpr uint8_t NUM_STEPS = NUM_PATTERNS + NUM_REPLAYS + NUM_BITBANG + 2U;

// Progress of the probe. 0 is idle; the probe then advances by one stage
// per call of pcfProbeStep().
enum : uint8_t { IDLE = 0, HEADER = 1, TABLE = 2, REPLAY = 3, BITBANG = 4, SOAK = 5, SUMMARY = 6 };
uint8_t stage = IDLE;
uint8_t cell = 0;              ///< next table cell to run, then next replay, then next bit-banged variant
uint8_t rowBad[NUM_STYLES];    ///< results of the row in progress: wrong read-backs per style
uint8_t rowPortFF[NUM_STYLES]; ///< and ports found at FF
uint16_t soakDone = 0;         ///< soak writes done so far
Totals all = {0, 0, 0, 0, 0};
Totals soak = {0, 0, 0, 0, 0};

void reportHeader() {
  char line[LINE_LEN];
  snprintf_P(line, sizeof(line), PSTR("\n=== PCF probe %u: %u steps, about 25 seconds ===\n"), PROBE_VERSION,
             NUM_STEPS);
  say(line);
  snprintf_P(line, sizeof(line), PSTR("Please wait for TEST FINISHED before doing anything.\n"));
  say(line);

  // Controller identity: device signature and serial number.
  snprintf_P(line, sizeof(line), PSTR("chip %02X%02X%02X "), boot_signature_byte_get(0), boot_signature_byte_get(2),
             boot_signature_byte_get(4));
  for (uint8_t i = 0; i < 10U; i++) {
    snprintf_P(&line[12U + 2U * i], 3, PSTR("%02X"), boot_signature_byte_get(0x0EU + i));
  }
  snprintf_P(&line[32], sizeof(line) - 32U, PSTR(" boot %u\n"), bootCount);
  say(line);

  // Bus check: pull-ups, then which addresses answer.
  TWCR = 0; // release the pins from the I2C hardware for the pull-up test
  bool sda = pulledUp(SDA);
  bool scl = pulledUp(SCL);
  Wire.begin();
  uint8_t pos = static_cast<uint8_t>(snprintf_P(line, sizeof(line), PSTR("vcc %u sda %u scl %u ack"),
                                                vccMillivolts(vccRaw()), sda ? 1U : 0U, scl ? 1U : 0U));
  for (uint8_t a = 0x03U; a <= 0x77U; a++) {
    Wire.beginTransmission(a);
    if ((Wire.endTransmission() == 0U) && (pos < (sizeof(line) - 5U))) {
      pos += static_cast<uint8_t>(snprintf_P(&line[pos], sizeof(line) - pos, PSTR(" %02X"), a));
    }
  }
  snprintf_P(&line[pos], sizeof(line) - pos, PSTR("\n"));
  say(line);

  writeBoth(0U, 0U, 0x0000U);
  snprintf_P(line, sizeof(line), PSTR("all off reads %04X\n"), readBoth(nullptr));
  say(line);

  snprintf_P(line, sizeof(line), PSTR("step, bad/portFF of %u: nat p00 p09 p11 pFF\n"), WRITES_PER_CELL);
  say(line);
}

/// One cell of the table: one number of solenoids energised, one write
/// style. A row is sent when its last cell is done.
void runCell() {
  uint8_t p = cell / NUM_STYLES;
  uint8_t s = cell % NUM_STYLES;
  uint16_t pattern = pgm_read_word(&patterns[p]);
  Totals t = {0, 0, 0, 0, 0};
  burst(s, pgm_read_byte(&prefixes[s]), pattern, 0U, WRITES_PER_CELL, t);
  writeBoth(0U, 0U, 0x0000U);
  // At most WRITES_PER_CELL wrong read-backs, and two ports each: both fit a byte.
  rowBad[s] = static_cast<uint8_t>(t.bad);
  rowPortFF[s] = static_cast<uint8_t>(t.portFF);
  all.bad += t.bad;
  all.portFF += t.portFF;
  all.stuck += t.stuck;
  all.writeNak += t.writeNak;
  all.readNak += t.readNak;
  if (s == (NUM_STYLES - 1U)) {
    char line[LINE_LEN];
    uint8_t pos =
        static_cast<uint8_t>(snprintf_P(line, sizeof(line), PSTR("[%u/%u] %2u on"), p + 1U, NUM_STEPS, bitsSet(pattern)));
    for (uint8_t k = 0; k < NUM_STYLES; k++) {
      pos += static_cast<uint8_t>(snprintf_P(&line[pos], sizeof(line) - pos, PSTR(" %u/%u"), rowBad[k], rowPortFF[k]));
    }
    snprintf_P(&line[pos], sizeof(line) - pos, PSTR("\n"));
    say(line);
  }
}

/// One check of the replay: read both ports back and count a wrong value
/// against solenoid `n`.
void replayCheck(uint8_t style, uint8_t prefix, uint8_t n, uint8_t repeat, uint16_t want, uint8_t *counts) {
  uint8_t naks = 0;
  uint16_t got = readBoth(&naks);
#ifdef PCFPROBE_INJECT_FAULT
  // Bench check of the reporting path (see burst()): in the first run of
  // each sequence, pretend the read-back after enabling solenoid 13 found
  // the upper port at FF.
  if ((n == 13U) && (repeat == 0U) && (want != 0U)) {
    got |= 0xFF00U;
  }
#else
  (void)repeat;
#endif // PCFPROBE_INJECT_FAULT
  if (naks != 0U) {
    all.readNak++;
  }
  if (got != want) {
    all.bad++;
    if (counts[n] < 9U) {
      counts[n]++;
    }
    if ((lowByte(got) == 0xFFU) && (lowByte(want) != 0xFFU)) {
      all.portFF++;
      ffLowBank++;
    }
    if ((highByte(got) == 0xFFU) && (highByte(want) != 0xFFU)) {
      all.portFF++;
      ffHighBank++;
    }
    uint16_t again = readBoth(nullptr);
    if (again == got) {
      all.stuck++;
    }
    if (numDetails < MAX_DETAILS) {
      numDetails++;
      reportDetail(style, prefix, want, n, want, got, again);
    }
  }
}

/// Replay of how the fault was first seen, by hand, in hardware test mode:
/// solenoids enabled one by one from 0 to 15, with trouble starting at the
/// last four.
///
/// `cumulative` false: each solenoid is switched on, checked, switched off
/// and checked again. `cumulative` true: each is switched on in addition to
/// those before it, and checked. The sequence is run REPLAY_REPEATS times.
/// The report line holds one digit per solenoid, 0 to 15: how many checks
/// went wrong at that solenoid (9 means nine or more).
void replay(uint8_t which) {
  bool cumulative = (which >= 2U);
  uint8_t style = ((which & 1U) != 0U) ? 2U : 0U; // index into prefixes: native, or two bytes starting 0x09
  uint8_t prefix = pgm_read_byte(&prefixes[style]);
  uint8_t counts[16] = {0};

  for (uint8_t r = 0; r < REPLAY_REPEATS; r++) {
    uint16_t state = 0x0000U;
    if (writeBoth(style, prefix, state) != 0U) {
      all.writeNak++;
    }
    for (uint8_t n = 0; n < 16U; n++) {
      uint16_t bit = static_cast<uint16_t>(1U) << n;
      state = cumulative ? static_cast<uint16_t>(state | bit) : bit;
      if (writeBoth(style, prefix, state) != 0U) {
        all.writeNak++;
      }
      delay(REPLAY_SETTLE_MS);
      replayCheck(style, prefix, n, r, state, counts);
      if (!cumulative) {
        state = 0x0000U;
        if (writeBoth(style, prefix, state) != 0U) {
          all.writeNak++;
        }
        delay(REPLAY_SETTLE_MS);
        replayCheck(style, prefix, n, r, state, counts);
      }
    }
  }
  writeBoth(0U, 0U, 0x0000U);

  char line[LINE_LEN];
  uint8_t pos = static_cast<uint8_t>(snprintf_P(line, sizeof(line), cumulative ? PSTR("[%u/%u] add %S ") : PSTR("[%u/%u] one %S "),
                                                NUM_PATTERNS + 1U + which, NUM_STEPS, (style == 0U) ? PSTR("nat") : PSTR("p09")));
  for (uint8_t n = 0; n < 16U; n++) {
    line[pos++] = static_cast<char>('0' + counts[n]);
  }
  line[pos++] = '\n';
  line[pos] = '\0';
  say(line);
}

// The I2C lines driven as plain open-drain pins: a line is either pulled
// low by the controller or released to the pull-up resistor.
inline void bitbangScl(bool released) {
  if (released) {
    DDRC &= static_cast<uint8_t>(~BITBANG_SCL);
  } else {
    DDRC |= BITBANG_SCL;
  }
}

inline void bitbangSda(bool released) {
  if (released) {
    DDRC &= static_cast<uint8_t>(~BITBANG_SDA);
  } else {
    DDRC |= BITBANG_SDA;
  }
}

/// True when the data line is low, which during an acknowledge bit means
/// the expander is acknowledging.
inline bool bitbangSdaLow() {
  return (PINC & BITBANG_SDA) == 0U;
}

void bitbangBits(uint8_t value) {
  for (uint8_t mask = 0x80U; mask != 0U; mask >>= 1) {
    bitbangSda((value & mask) != 0U);
    delayMicroseconds(BITBANG_HALF_US);
    bitbangScl(true);
    delayMicroseconds(BITBANG_HALF_US);
    bitbangScl(false);
  }
}

/// Write BITBANG_PATTERN to the expander for solenoids 8-15 without the I2C
/// hardware, so that what the two bus lines do around the moment the
/// outputs switch is chosen by `flags`. Notes in `acks` whether the
/// expander was acknowledging at three moments of the acknowledge bit:
/// [0] at the end of the clock's low time, [1] just after the clock rose,
/// [2] at the end of its high time.
void bitbangWrite(uint8_t flags, uint8_t *acks) {
  // Take the pins from the I2C hardware. Wire switches on the internal
  // pull-ups by setting the port bits; these must be cleared before the
  // pins are made outputs, or the lines would be driven high.
  TWCR = 0;
  PORTC &= static_cast<uint8_t>(~(BITBANG_SDA | BITBANG_SCL));

  // Start, then the address with the write bit and its acknowledge.
  bitbangSda(false);
  delayMicroseconds(BITBANG_HALF_US);
  bitbangScl(false);
  bitbangBits(static_cast<uint8_t>(ADDR_HI << 1));
  bitbangSda(true);
  delayMicroseconds(BITBANG_HALF_US);
  bitbangScl(true);
  delayMicroseconds(BITBANG_HALF_US);
  if (!bitbangSdaLow()) {
    all.writeNak++;
  }
  bitbangScl(false);

  // The data byte, then its acknowledge bit, which is where the expander
  // applies the byte to its outputs.
  bitbangBits(BITBANG_PATTERN);
  bitbangSda((flags & BITBANG_DATA) == 0U);
  delayMicroseconds(((flags & BITBANG_LOW) != 0U) ? BITBANG_HOLD_US : BITBANG_HALF_US);
  if (bitbangSdaLow()) {
    acks[0]++;
  }
  bitbangScl(true);
  delayMicroseconds(BITBANG_HALF_US);
  if (bitbangSdaLow()) {
    acks[1]++;
  }
  if ((flags & BITBANG_HIGH) != 0U) {
    delayMicroseconds(BITBANG_HOLD_US);
  }
  if (bitbangSdaLow()) {
    acks[2]++;
  }
  bitbangScl(false);
  delayMicroseconds(BITBANG_HALF_US);

  // Stop, and hand the pins back.
  bitbangSda(false);
  delayMicroseconds(BITBANG_HALF_US);
  bitbangScl(true);
  delayMicroseconds(BITBANG_HALF_US);
  bitbangSda(true);
  delayMicroseconds(BITBANG_HALF_US);
  Wire.begin();
}

/// Does the state of the bus lines matter when the expander resets?
///
/// On the affected machines the expander for solenoids 8-15 ends up with
/// its whole port on when several solenoids are switched off and back on
/// within a millisecond or so. Each trial does that to seven solenoids;
/// the write that switches them back on is bit-banged, with the bus
/// lines held in a different state around the acknowledge bit in each
/// variant. The time from switching off to the acknowledge pulse is the
/// same in all of them.
///
/// The report line gives the number of trials that ended with the port at
/// FF, then in how many trials the expander was acknowledging at each of
/// the three moments noted by bitbangWrite().
void bitbangTest(uint8_t which) {
  uint8_t flags = pgm_read_byte(&bitbangVariants[which]);
  uint16_t on = static_cast<uint16_t>(BITBANG_PATTERN) << 8;
  uint8_t resets = 0;
  uint8_t acks[3] = {0, 0, 0};

  for (uint8_t i = 0; i < BITBANG_TRIALS; i++) {
    if (writeBoth(0U, 0U, on) != 0U) {
      all.writeNak++;
    }
    delay(BITBANG_ON_MS);
    if (writePort(ADDR_HI, 0U, 0U, 0x00U) != 0U) {
      all.writeNak++;
    }
    if ((flags & BITBANG_LOW) == 0U) {
      delayMicroseconds(BITBANG_HOLD_US);
    }
    if ((flags & BITBANG_WIRE) != 0U) {
      if (writePort(ADDR_HI, 0U, 0U, BITBANG_PATTERN) != 0U) {
        all.writeNak++;
      }
    } else {
      bitbangWrite(flags, acks);
    }
    delay(2);
    uint16_t got = readBoth(nullptr);
    if (got != on) {
      all.bad++;
      if (highByte(got) == 0xFFU) {
        resets++;
        all.portFF++;
        ffHighBank++;
      }
    }
    writeBoth(0U, 0U, 0x0000U);
    delay(BITBANG_REST_MS);
  }

  char line[LINE_LEN];
  uint8_t step = NUM_PATTERNS + NUM_REPLAYS + 1U + which;
  if ((flags & BITBANG_WIRE) != 0U) {
    snprintf_P(line, sizeof(line), PSTR("[%u/%u] wire        ff %u\n"), step, NUM_STEPS, resets);
  } else {
    snprintf_P(line, sizeof(line), PSTR("[%u/%u] bitbang %c%c%c ff %u ack %u %u %u\n"), step, NUM_STEPS,
               ((flags & BITBANG_LOW) != 0U) ? 'L' : '-', ((flags & BITBANG_HIGH) != 0U) ? 'H' : '-',
               ((flags & BITBANG_DATA) != 0U) ? 'D' : '-', resets, acks[0], acks[1], acks[2]);
  }
  say(line);
}

void reportSummary() {
  char line[LINE_LEN];
  snprintf_P(line, sizeof(line), PSTR("[%u/%u] soak p09 11 on n %u bad %u ff %u\n"), NUM_STEPS - 1U, NUM_STEPS,
             SOAK_WRITES, soak.bad, soak.portFF);
  say(line);
  snprintf_P(line, sizeof(line), PSTR("[%u/%u] stuck %u nak w %u r %u\n"), NUM_STEPS, NUM_STEPS, all.stuck + soak.stuck,
             all.writeNak + soak.writeNak, all.readNak + soak.readNak);
  say(line);
  // A whole bank found on when it was not asked for: what was seen on the machine.
  snprintf_P(line, sizeof(line), PSTR("whole bank on by itself: 0-7 %u times, 8-15 %u times\n"), ffLowBank, ffHighBank);
  say(line);
  snprintf_P(line, sizeof(line), PSTR("vcc min %u max %u ram %u\n"), vccMillivolts(vccRawMax),
             vccMillivolts(vccRawMin), untouchedRam());
  say(line);

  snprintf_P(line, sizeof(line), PSTR("PCF probe %u end, total bad %u\n"), PROBE_VERSION, all.bad + soak.bad);
  say(line);
  snprintf_P(line, sizeof(line), PSTR("=== TEST FINISHED: copy all the text above and send it ===\n\n"));
  say(line);
  // An audible sign that it is over, for a user who is not watching the screen.
  GlobalBeeper::endWork();
}

} // namespace

void pcfProbeStart() {
  paintFreeRam();

  if (bootMagic != 0xB007U) {
    bootMagic = 0xB007U;
    bootCount = 0U;
  }
  bootCount++;

  cell = 0U;
  soakDone = 0U;
  numDetails = 0U;
  ffLowBank = 0U;
  ffHighBank = 0U;
  vccRawMin = 1023U;
  vccRawMax = 0U;
  all = {0, 0, 0, 0, 0};
  soak = {0, 0, 0, 0, 0};
  stage = HEADER;
}

void pcfProbeStep() {
  switch (stage) {
  case HEADER:
    reportHeader();
    stage = TABLE;
    break;

  case TABLE:
    runCell();
    cell++;
    if (cell >= NUM_CELLS) {
      char line[LINE_LEN];
      snprintf_P(line, sizeof(line), PSTR("one by one / adding up: bad per solenoid 0..15\n"));
      say(line);
      cell = 0U;
      stage = REPLAY;
    }
    break;

  case REPLAY:
    replay(cell);
    cell++;
    if (cell >= NUM_REPLAYS) {
      char line[LINE_LEN];
      snprintf_P(line, sizeof(line), PSTR("7 off, back on by bit-banged write: ff and acks of %u\n"), BITBANG_TRIALS);
      say(line);
      snprintf_P(line, sizeof(line), PSTR("L/H: clock held low/high 0.3 ms; D: data held low\n"));
      say(line);
      cell = 0U;
      stage = BITBANG;
    }
    break;

  case BITBANG:
    bitbangTest(cell);
    cell++;
    if (cell >= NUM_BITBANG) {
      stage = SOAK;
    }
    break;

  case SOAK:
    // In the style the MCP23008 driver uses, with 11 solenoids on.
    burst(2U, 0x09U, 0xF676U, soakDone, SOAK_CHUNK, soak);
    soakDone += SOAK_CHUNK;
    if (soakDone >= SOAK_WRITES) {
      writeBoth(0U, 0U, 0x0000U);
      stage = SUMMARY;
    }
    break;

  case SUMMARY:
    reportSummary();
    stage = IDLE;
    break;

  default:
    break;
  }
}
