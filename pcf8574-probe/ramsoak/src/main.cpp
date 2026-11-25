// RAM soak test for a UNO with nothing connected.
//
// All RAM between the end of the program's own variables and a margin below
// the stack is filled with an address-dependent pattern, the I2C hardware is
// exercised against the (dead) bus through the Wire library, and the area is
// read back. Any byte that changed is reported with its address.
//
// Purpose
//   One of the UNO boards used in this investigation crashed at random
//   while running the I2C tests. This sketch looks for RAM being corrupted
//   on the controller itself, with the interface board out of the picture.
//
// Build flags:
//   -DREFBIT   select the AVCC reference (the setting that stops UNO A
//              crashing)
//   -DNOTWI    do the same fill / wait / verify with no I2C activity at all
//   -DNOIRQ    keep interrupts disabled during fill, wait and verify
//   -DSTACKMID move the stack to the middle of RAM (0x5FF) and also test the
//              top of RAM (0x600-0x8FF), where the stack normally lives
// The Wire library needs interrupts to complete a transfer, so NOIRQ only
// makes sense together with NOTWI.
//
// How it is used
//   There are no serial commands. The sketch prints at 115200 baud:
//     RAMSOAK serial N..N refbit=SET|default twi=on|off
//         once at start; N..N is the chip's ten-byte serial number in hex
//     PREVIOUS RUN ENDED WITHOUT RESET after cycles=C errors=E
//         at start, only if the counters of an earlier run are still in RAM
//         (see setup)
//     RAMERR cycle C c=K addr 0xAAAA expected EE read RR reread R2
//            recomputed E2
//         one line per corrupted byte, for the first 12 errors only
//         (shown wrapped here; it is one line on the wire)
//     progress: cycles C errors E area 0xLLLL-0xHHHH
//         every 5 s (every 500 cycles with NOIRQ); the area is the address
//         range under test, upper bound not included
//   One cycle is one fill, one burst of I2C activity (or a 3 ms wait) and
//   one verify.
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) with nothing connected to it.
//   The RAM of this chip runs from 0x100 to 0x8FF.
#include <Arduino.h>
#include <Wire.h>
#include <avr/boot.h>

extern char __heap_start; // first address after .data, .bss and .noinit

// These three variables live in the .noinit section, which the C start-up
// code does not clear, so they keep their values across a restart as long
// as the chip stays powered.
//   magic       0xBEEF once a run has started
//   cyclesDone  number of fill / verify cycles completed in this run
//   errorsSeen  number of corrupted bytes found in this run
uint16_t magic __attribute__((section(".noinit")));
uint32_t cyclesDone __attribute__((section(".noinit")));
uint32_t errorsSeen __attribute__((section(".noinit")));

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Returns the test pattern byte for RAM address a in cycle number c.
// The value depends on both bytes of the address, so neighbouring cells and
// cells 256 bytes apart hold different values, and it changes every cycle.
// On odd cycles the whole byte is additionally inverted. The code does not
// say why the particular multipliers (31, 7, 0x5B) were chosen.
static inline uint8_t pat(uint16_t a, uint8_t c) {
  return (uint8_t)(a * 31 + (a >> 8) * 7 + c * 0x5B) ^ ((c & 1) ? 0xFF : 0x00);
}

#ifdef STACKMID
// Moves the stack pointer to 0x5FF, the middle of RAM, so that the top of
// RAM is free to be tested. The function is placed in the .init3 start-up
// section, which runs after the C runtime has set the stack pointer to the
// top of RAM and before main() is called. It is "naked" (no entry or return
// code), so execution simply runs on into the next start-up section.
void moveStack(void) __attribute__((naked, used, section(".init3")));
void moveStack(void) {
  SP = 0x05FF;
}
#endif

// Compares the RAM from address lo up to (not including) hi with the pattern
// of cycle c. Every byte that differs is counted in errorsSeen; the first 12
// of a run are also printed. The report line gives the expected value, the
// value read, a second read of the same cell (to show whether the cell
// really holds the wrong value or was only misread) and the expected value
// worked out a second time (to show whether the calculation itself went
// wrong).
static void verify(uint8_t *lo, uint8_t *hi, uint8_t c) {
  for (uint8_t *p = lo; p < hi; p++) {
    uint8_t want = pat((uint16_t)p, c), got = *p;
    if (got != want) {
      errorsSeen++;
      if (errorsSeen <= 12) {
        Serial.print(F("RAMERR cycle "));
        Serial.print(cyclesDone);
        Serial.print(F(" c="));
        Serial.print(c);
        Serial.print(F(" addr 0x"));
        Serial.print((uint16_t)p, HEX);
        Serial.print(F(" expected "));
        hx(want);
        Serial.print(F(" read "));
        hx(got);
        Serial.print(F(" reread "));
        hx(*p);
        Serial.print(F(" recomputed "));
        hx(pat((uint16_t)p, c));
        Serial.println();
      }
    }
  }
}

// Prints the banner, reports a previous run whose counters survived, and
// resets the counters.
void setup() {
#ifdef REFBIT
  // Select AVCC as the ADC voltage reference (the ADC itself is not used).
  ADMUX = _BV(REFS0);
#endif
  Serial.begin(115200);
  // Banner: chip serial number (signature row bytes 0x0E to 0x17) and the
  // build options in effect.
  Serial.print(F("\nRAMSOAK serial "));
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx(boot_signature_byte_get(a));
#ifdef REFBIT
  Serial.print(F(" refbit=SET"));
#else
  Serial.print(F(" refbit=default"));
#endif
#ifdef NOTWI
  Serial.println(F(" twi=off"));
#else
  Serial.println(F(" twi=on"));
#endif
  // If the marker from an earlier run is still in RAM, the chip has
  // restarted without losing power since that run began. Print how far that
  // run had got. Any restart does this, whether it was a crash, the reset
  // button, or the host opening the serial port.
  if (magic == 0xBEEF) {
    Serial.print(F("PREVIOUS RUN ENDED WITHOUT RESET after cycles="));
    Serial.print(cyclesDone);
    Serial.print(F(" errors="));
    Serial.println(errorsSeen);
  }
  magic = 0xBEEF;
  cyclesDone = 0;
  errorsSeen = 0;
#ifndef NOTWI
  Wire.begin();
#endif
}

// One test cycle: fill, disturb, verify, and now and then a progress line.
void loop() {
  static uint8_t c = 0;           // cycle number used for the pattern
  static uint32_t lastReport = 0; // when the last progress line was printed
  // The area under test starts 4 bytes above the end of the program's own
  // variables and stops 96 bytes below the current stack pointer. The 96
  // bytes leave room for the stack to grow during the calls and interrupts
  // that follow. The code does not say what the 4-byte gap is for.
  uint8_t *lo = (uint8_t *)&__heap_start + 4;
  uint8_t *hi = (uint8_t *)SP - 96;
#ifdef NOIRQ
  cli();
#endif
  // Step 1: fill the area with this cycle's pattern.
  for (uint8_t *p = lo; p < hi; p++)
    *p = pat((uint16_t)p, c);
#ifdef STACKMID
  for (uint8_t *p = (uint8_t *)0x600; p < (uint8_t *)0x900; p++)
    *p = pat((uint16_t)p, c);
#endif
  // Step 2: exercise the I2C hardware. Eight two-byte writes, [0x09][k],
  // alternately to addresses 0x20 and 0x21: the same form of write the AYAB
  // firmware sends to its expanders. Nothing is connected, so no address is
  // acknowledged and each attempt ends early. Without I2C, wait 3 ms
  // instead so that the pattern sits in RAM for a comparable time.
#ifndef NOTWI
  for (uint8_t k = 0; k < 8; k++) {
    Wire.beginTransmission(0x20 + (k & 1));
    Wire.write((uint8_t)0x09);
    Wire.write(k);
    Wire.endTransmission();
  }
#else
  delayMicroseconds(3000);
#endif
  // Step 3: read the area back and report any byte that changed.
  verify(lo, hi, c);
#ifdef STACKMID
  verify((uint8_t *)0x600, (uint8_t *)0x900, c);
#endif
#ifdef NOIRQ
  sei();
#endif
  c++;
  cyclesDone++;
  // Step 4: progress line. With interrupts off for most of the time the
  // millisecond clock is not reliable, so NOIRQ counts cycles instead.
#ifdef NOIRQ
  if (cyclesDone - lastReport >= 500) {
    lastReport = cyclesDone;
#else
  if (millis() - lastReport >= 5000) {
    lastReport = millis();
#endif
    Serial.print(F("progress: cycles "));
    Serial.print(cyclesDone);
    Serial.print(F(" errors "));
    Serial.print(errorsSeen);
    Serial.print(F(" area 0x"));
    Serial.print((uint16_t)lo, HEX);
    Serial.print(F("-0x"));
    Serial.println((uint16_t)hi, HEX);
  }
}
