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

constexpr uint8_t PROBE_VERSION = 3U;
constexpr uint8_t ADDR_LO = 0x20U; ///< expander for solenoids 0-7
constexpr uint8_t ADDR_HI = 0x21U; ///< expander for solenoids 8-15
constexpr uint8_t WRITES_PER_CELL = 100U;
constexpr uint16_t SOAK_WRITES = 2000U;
constexpr uint16_t SOAK_CHUNK = 200U; ///< soak writes done per call of pcfProbeStep()
constexpr uint8_t MAX_DETAILS = 4U;

/// One line of the report. Com's message buffer holds 64 bytes including
/// the message id, so lines must stay under 62 characters.
/// The firmware has little RAM to spare, so all text is kept in flash.
char line[62];

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

struct Detail {
  uint8_t style;
  uint8_t on;
  uint16_t index;
  uint16_t want;
  uint16_t got;
  uint16_t again;
};

Detail details[MAX_DETAILS];
uint8_t numDetails = 0;
uint16_t vccRawMin = 1023U; // raw ADC reading; a higher reading is a lower supply
uint16_t vccRawMax = 0U;

void say() {
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

/// `count` writes alternating between `a` and `a` with solenoid 0
/// toggled, each followed by a read-back of both ports. `firstIndex`
/// numbers the writes when a long run is done in several calls.
void burst(uint8_t styleIndex, uint8_t style, uint8_t prefix, uint16_t a, uint16_t firstIndex, uint16_t count,
           Totals &t) {
  for (uint16_t i = firstIndex; i < (firstIndex + count); i++) {
    uint16_t want = ((i & 1U) != 0U) ? static_cast<uint16_t>(a ^ 0x0001U) : a;
    uint8_t naks = 0;
    if (writeBoth(style, prefix, want) != 0U) {
      t.writeNak++;
    }
    uint16_t got = readBoth(&naks);
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
      }
      if ((highByte(got) == 0xFFU) && (highByte(want) != 0xFFU)) {
        t.portFF++;
      }
      uint16_t again = readBoth(nullptr);
      if (again == got) {
        t.stuck++;
      }
      if (numDetails < MAX_DETAILS) {
        details[numDetails++] = {styleIndex, bitsSet(a), i, want, got, again};
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
/// Steps shown to the user as "[n/total]": one per table row, the soak,
/// and the summary.
constexpr uint8_t NUM_STEPS = NUM_PATTERNS + 2U;

// Progress of the probe. 0 is idle; the probe then advances by one stage
// per call of pcfProbeStep().
enum : uint8_t { IDLE = 0, HEADER = 1, TABLE = 2, SOAK = 3, SUMMARY = 4 };
uint8_t stage = IDLE;
uint8_t cell = 0;       ///< next table cell to run
uint8_t rowPos = 0;     ///< write position in `line` while a table row is being built
uint16_t soakDone = 0;  ///< soak writes done so far
Totals all = {0, 0, 0, 0, 0};
Totals soak = {0, 0, 0, 0, 0};

void reportHeader() {
  snprintf_P(line, sizeof(line), PSTR("\n=== PCF probe %u: %u steps, about 15 seconds ===\n"), PROBE_VERSION,
             NUM_STEPS);
  say();
  snprintf_P(line, sizeof(line), PSTR("Please wait for TEST FINISHED before doing anything.\n"));
  say();

  // Controller identity: device signature and serial number.
  snprintf_P(line, sizeof(line), PSTR("chip %02X%02X%02X "), boot_signature_byte_get(0), boot_signature_byte_get(2),
             boot_signature_byte_get(4));
  for (uint8_t i = 0; i < 10U; i++) {
    snprintf_P(&line[12U + 2U * i], 3, PSTR("%02X"), boot_signature_byte_get(0x0EU + i));
  }
  snprintf_P(&line[32], sizeof(line) - 32U, PSTR(" boot %u\n"), bootCount);
  say();

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
  say();

  writeBoth(0U, 0U, 0x0000U);
  snprintf_P(line, sizeof(line), PSTR("all off reads %04X\n"), readBoth(nullptr));
  say();

  snprintf_P(line, sizeof(line), PSTR("step, bad/portFF of %u: nat p00 p09 p11 pFF\n"), WRITES_PER_CELL);
  say();
}

/// One cell of the table: one number of solenoids energised, one write
/// style. A row is sent when its last cell is done.
void runCell() {
  uint8_t p = cell / NUM_STYLES;
  uint8_t s = cell % NUM_STYLES;
  uint16_t pattern = pgm_read_word(&patterns[p]);
  if (s == 0U) {
    rowPos = static_cast<uint8_t>(
        snprintf_P(line, sizeof(line), PSTR("[%u/%u] %2u on"), p + 1U, NUM_STEPS, bitsSet(pattern)));
  }
  Totals t = {0, 0, 0, 0, 0};
  burst(s, s, pgm_read_byte(&prefixes[s]), pattern, 0U, WRITES_PER_CELL, t);
  writeBoth(0U, 0U, 0x0000U);
  rowPos += static_cast<uint8_t>(snprintf_P(&line[rowPos], sizeof(line) - rowPos, PSTR(" %u/%u"), t.bad, t.portFF));
  all.bad += t.bad;
  all.portFF += t.portFF;
  all.stuck += t.stuck;
  all.writeNak += t.writeNak;
  all.readNak += t.readNak;
  if (s == (NUM_STYLES - 1U)) {
    snprintf_P(&line[rowPos], sizeof(line) - rowPos, PSTR("\n"));
    say();
  }
}

void reportSummary() {
  snprintf_P(line, sizeof(line), PSTR("[%u/%u] soak p09 11 on n %u bad %u ff %u\n"), NUM_STEPS - 1U, NUM_STEPS,
             SOAK_WRITES, soak.bad, soak.portFF);
  say();
  snprintf_P(line, sizeof(line), PSTR("[%u/%u] stuck %u nak w %u r %u\n"), NUM_STEPS, NUM_STEPS, all.stuck + soak.stuck,
             all.writeNak + soak.writeNak, all.readNak + soak.readNak);
  say();
  snprintf_P(line, sizeof(line), PSTR("vcc min %u max %u ram %u\n"), vccMillivolts(vccRawMax),
             vccMillivolts(vccRawMin), untouchedRam());
  say();

  for (uint8_t d = 0; d < numDetails; d++) {
    // style 0 is the native write, shown as "nat"; the others show their first byte
    if (details[d].style == 0U) {
      snprintf_P(line, sizeof(line), PSTR("bad nat %u on #%u want %04X got %04X re %04X\n"), details[d].on,
                 details[d].index, details[d].want, details[d].got, details[d].again);
    } else {
      snprintf_P(line, sizeof(line), PSTR("bad p%02X %u on #%u want %04X got %04X re %04X\n"),
                 pgm_read_byte(&prefixes[details[d].style]), details[d].on, details[d].index, details[d].want,
                 details[d].got, details[d].again);
    }
    say();
  }

  snprintf_P(line, sizeof(line), PSTR("PCF probe %u end, total bad %u\n"), PROBE_VERSION, all.bad + soak.bad);
  say();
  snprintf_P(line, sizeof(line), PSTR("=== TEST FINISHED: copy all the text above and send it ===\n\n"));
  say();
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
      stage = SOAK;
    }
    break;

  case SOAK:
    // In the style the MCP23008 driver uses, with 11 solenoids on.
    burst(2U, 2U, 0x09U, 0xF676U, soakDone, SOAK_CHUNK, soak);
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
