// MCP23008-style writes to two PCF8574s (exactly what the AYAB firmware
// does), with every write followed by a read-back of both ports.
//
// Purpose
//   The AYAB firmware drives its expanders with a library written for the
//   MCP23008, which sends two bytes per write: the register number 0x09
//   (GPIO) and then the data. A PCF8574 has no registers and puts both
//   bytes on its port, one after the other. This sketch runs a fixed series
//   of switching patterns through that same library and checks, before and
//   after every write, that both ports read back what was last written.
//
//   The sketch also carries a set of crash diagnostics. On one of the UNO
//   boards used, this program restarted at random, so it records where it
//   is and what the processor was doing in RAM that survives a restart, and
//   prints that record at the start of the next run.
//
// The 16-bit state
//   A state is sixteen bits. The low byte goes to the expander at 0x20 and
//   the high byte to the one at 0x21. A 1 bit switches that solenoid on.
//
// How it is used
//   There are no serial commands. The sketch runs its sequence once after
//   reset and prints at 115200 baud (38400 baud if CLKDIV is defined):
//     MCP-style write / read-back test
//     reset cause r2=0x.. (...) MCUSR=0x..
//     at entry: TWBR=.. TWCR=0x.. TCCR0B=.. UCSR0B=0x.. SP=0x....
//         hardware registers exactly as the previous program left them
//     PCTRACE a a a ...
//     ... PREVIOUS RUN DID NOT FINISH: phase P step S writes W state 0x....
//         badISR 0x..
//         only if the previous run was cut short; see setup()
//     <phase name>: writes W, mismatches M, UNO supply min V mV, max V mV
//         one line as each phase of the sequence ends, with the number of
//         writes and failed read-backs in that phase and the lowest and
//         highest controller supply voltage seen during it
//       MISMATCH before|after write #W: want XXXX got YYYY
//         one line for each of the first 12 failed read-backs (hex states)
//     TOTAL writes W, mismatches M
//     DONE
//
// Build flags (all optional; none are set in platformio.ini, they are
// passed on the command line, for example by tools/variants.sh and
// tools/battery.sh, to find out which ingredient of the test matters):
//   What is sent for each write
//     (none)          MCP23008 library write: [0x09][data] to each chip
//     FORCE0          MCP23008 library write of data 0 whatever the state
//     PREFIX=n        [n][data] sent directly through the Wire library
//     DATA_THEN_ZERO  [data][0x00]
//     ZERO_THEN_DATA  [0x00][data]
//     NATIVE1         [data] alone (native single-byte write)
//     HOLDALL         both ports are set to FF once at the start; each
//                     "write" is then only a 620 us wait
//     NO_I2C          no I2C at all: each write is replaced by a 620 us
//                     wait, or, if TB is also defined, by 54 pulses on a
//                     GPIO pin. TB is the bit number, TP the PORT register
//                     and TD the DDR register of that pin.
//     MCPFIRST        the extra "bank patterns" phase uses MCP-style
//                     writes instead of native ones
//   What is checked
//     NOREAD          no read-back. Each check is replaced by a 450 us
//                     wait whose real duration is measured.
//   Controller set-up
//     OLD             leave out the supply monitor and the phases "idle"
//                     and the first "bank patterns". The code does not say
//                     what the name refers to.
//     ADC_OFF         switch the ADC off completely
//     ADC_FREE_NOIRQ  ADC free-running but without its interrupt
//     REF_ONLY        only select the AVCC reference, ADC idle
//     CLKDIV=n        divide the CPU clock by 2^n
//     PEPU=mask       ATmega328PB only: pull-ups on port E pins
//   The write variants replace the MCP-style write only. The first "bank
//   patterns" phase still sends native writes (except with NO_I2C or
//   MCPFIRST).
//   Without NOREAD, the read-back always uses the Wire library, even when
//   NO_I2C has left it uninitialised, and it compares the ports with the
//   state that was asked for, which the variants FORCE0, DATA_THEN_ZERO,
//   HOLDALL and NO_I2C do not actually put on the ports.
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) with the optiboot bootloader,
//   connected by I2C (SDA = A4, SCL = A5) to the interface board with its
//   two PCF8574 expanders at 0x20 and 0x21, each driving a ULN2803 and
//   eight solenoids. The NO_I2C variants also run with nothing connected.
#include <Adafruit_MCP23008.h>
#include <Arduino.h>
#include <Wire.h>

// MCP23008 driver objects for the expanders at 0x20 (mcp_0) and 0x21
// (mcp_1).
static Adafruit_MCP23008 mcp_0, mcp_1;

// All the variables below marked ".noinit" are left alone by the C start-up
// code, so they keep their values across a restart as long as the chip
// stays powered. That is how one run can report on the run before it.

// Reset cause: optiboot hands the original MCUSR to the sketch in r2.
uint8_t resetCause __attribute__((section(".noinit")));
void saveResetCause(void) __attribute__((naked, used, section(".init0")));
// Crash breadcrumbs, kept across a restart (not cleared by the C runtime).
//   savedTWBR, savedTWCR  I2C bit-rate and control registers at entry
//   savedTCCR0B           Timer0 prescaler register at entry
//   savedUCSR0B           serial port control register at entry
//   savedSP               stack pointer at entry
//   crumbMagic            0xC0DE while a run is in progress
//   crumbPhase            number of phases completed so far
//   crumbStep             last step reached inside wr(), see CRUMB below
//   crumbBad              0xBD if an unused interrupt vector was reached
//   crumbWrites           write counter at the last write started
//   crumbState            state requested by the last write started
uint8_t savedTWBR __attribute__((section(".noinit")));
uint8_t savedTWCR __attribute__((section(".noinit")));
uint8_t savedTCCR0B __attribute__((section(".noinit")));
uint8_t savedUCSR0B __attribute__((section(".noinit")));
uint16_t savedSP __attribute__((section(".noinit")));
uint16_t crumbMagic __attribute__((section(".noinit")));
uint8_t crumbPhase __attribute__((section(".noinit")));
uint8_t crumbStep __attribute__((section(".noinit")));
uint8_t crumbBad __attribute__((section(".noinit")));
uint32_t crumbWrites __attribute__((section(".noinit")));
uint16_t crumbState __attribute__((section(".noinit")));
// Program-counter trace: Timer2 at 2 kHz stores the interrupted address.
// pcRing holds the last 64 addresses, two bytes each with the high byte
// first, as word addresses (multiply by 2 for the byte address shown in a
// listing). pcIdx is the offset of the next entry to be written, always
// even, 0 to 126.
uint8_t pcRing[128] __attribute__((section(".noinit")));
uint8_t pcIdx __attribute__((section(".noinit")));

// Timer2 compare interrupt, every 0.5 ms: stores the address at which the
// main program was interrupted into pcRing. Written in assembly, with no
// compiler-generated entry code, so that the position of the return address
// on the stack is known. Step by step:
//   - save r24, the status register (I/O 0x3F), r30, r31 and r25;
//   - copy the stack pointer (I/O 0x3D, 0x3E) into Z. After the five bytes
//     just pushed, the return address is at Z+6 (high byte) and Z+7 (low);
//   - store those two bytes at pcRing[pcIdx] and pcRing[pcIdx + 1];
//   - advance pcIdx by 2, wrapping at 128;
//   - restore the registers and return.
ISR(TIMER2_COMPA_vect, ISR_NAKED) {
  __asm__ __volatile__(
      "push r24\n in r24, 0x3f\n push r24\n push r30\n push r31\n push r25\n"
      "in r30, 0x3d\n in r31, 0x3e\n"
      "ldd r24, Z+6\n ldd r25, Z+7\n"
      "lds r30, pcIdx\n andi r30, 0x7E\n ldi r31, 0\n"
      "subi r30, lo8(-(pcRing))\n sbci r31, hi8(-(pcRing))\n"
      "st Z+, r24\n st Z, r25\n"
      "lds r30, pcIdx\n subi r30, -2\n andi r30, 0x7E\n sts pcIdx, r30\n"
      "pop r25\n pop r31\n pop r30\n pop r24\n out 0x3f, r24\n pop r24\n "
      "reti\n");
}

// Runs first thing after any restart, before the C runtime sets anything
// up (start-up section .init0). It stops the trace interrupt so that the
// trace of the previous run is not overwritten, saves r2 (the reset cause
// handed over by the bootloader) and takes a copy of a few hardware
// registers as they were found. Being "naked", it has no return: execution
// runs on into the rest of the start-up code.
void saveResetCause(void) {
  TIMSK2 = 0; // freeze the trace first
  __asm__ __volatile__("sts resetCause, r2\n");
  savedTWBR = TWBR;
  savedTWCR = TWCR;
  savedTCCR0B = TCCR0B;
  savedUCSR0B = UCSR0B;
  savedSP = SP;
}

// More records kept across a restart:
//   badPCH, badPCL  address (word address, high and low byte) at which the
//                   program was interrupted by an unused interrupt vector
//   badRegs         interrupt enable and flag registers at that moment, in
//                   the order written by saveIrqState()
//   entryStack      declared but not used anywhere in this file
//   slowCount       number of 450 us waits that took more than 700 us
//   slowMax         the longest such wait, microseconds
//   slowTWSR, slowTWCR  I2C status and control registers just after the
//                   longest wait
uint8_t badPCH __attribute__((section(".noinit")));
uint8_t badPCL __attribute__((section(".noinit")));
uint8_t badRegs[16] __attribute__((section(".noinit")));
uint8_t entryStack[8] __attribute__((section(".noinit")));
uint16_t slowCount __attribute__((section(".noinit")));
uint32_t slowMax __attribute__((section(".noinit")));
uint8_t slowTWSR __attribute__((section(".noinit")));
uint8_t slowTWCR __attribute__((section(".noinit")));

// Copies into badRegs every register that enables an interrupt source, plus
// two interrupt flag registers, so that it can be worked out afterwards
// which interrupt fired. The order is the order in which the "irq regs"
// line prints them: external interrupts (EIMSK), pin change (PCICR), the
// three timers (TIMSK0-2), SPI (SPCR), serial (UCSR0B), ADC (ADCSRA),
// analog comparator (ACSR), I2C (TWCR, TWSR), EEPROM (EECR), watchdog
// (WDTCSR), flash self-programming (SPMCSR), then the external interrupt
// flags (EIFR) and Timer0 flags (TIFR0).
static void saveIrqState(void) __attribute__((noinline, used));
static void saveIrqState(void) {
  badRegs[0] = EIMSK;
  badRegs[1] = PCICR;
  badRegs[2] = TIMSK0;
  badRegs[3] = TIMSK1;
  badRegs[4] = TIMSK2;
  badRegs[5] = SPCR;
  badRegs[6] = UCSR0B;
  badRegs[7] = ADCSRA;
  badRegs[8] = ACSR;
  badRegs[9] = TWCR;
  badRegs[10] = TWSR;
  badRegs[11] = EECR;
  badRegs[12] = WDTCSR;
  badRegs[13] = SPMCSR;
  badRegs[14] = EIFR;
  badRegs[15] = TIFR0;
}
// Unused interrupt vector reached: note the interrupted address and all
// interrupt enables, then restart.
// This handler catches every interrupt that has no handler of its own. In
// assembly: copy the stack pointer into Z; the return address pushed by the
// interrupt is at Z+1 (high byte) and Z+2 (low byte); store it in badPCH and
// badPCL; set crumbBad to 0xBD as a marker; clear r1, which compiled code
// expects to be zero; call saveIrqState(); then jump to address 0, which
// restarts the program without a hardware reset.
ISR(BADISR_vect, ISR_NAKED) {
  __asm__ __volatile__("in r30, 0x3d\n in r31, 0x3e\n"
                       "ldd r24, Z+1\n sts badPCH, r24\n"
                       "ldd r24, Z+2\n sts badPCL, r24\n"
                       "ldi r24, 0xBD\n sts crumbBad, r24\n"
                       "clr r1\n");
  saveIrqState();
  __asm__ __volatile__("jmp 0\n");
}

// Records how far wr() has got, for the report after a crash:
//   1 = entered, about to do the "before" check
//   2 = about to send the write
//   3 = first expander written, second one not yet
//   4 = write sent, about to do the "after" check
//   5 = finished
#define CRUMB(n) (crumbStep = (n))

// state   the 16-bit state most recently requested
// writes  number of writes done so far
// bad     number of failed read-backs so far
// shown   number of MISMATCH lines printed so far (at most 12)
static uint16_t state = 0;
static uint32_t writes = 0, bad = 0;
static uint8_t shown = 0;

// Supply monitor: free-running ADC on the internal 1.1 V reference,
// measured against AVCC. A higher reading means a lower supply.
// The interrupt runs after every conversion and keeps the lowest and
// highest raw readings (0 to 1023) seen since phase() last reset them.
static volatile uint16_t adcMin = 1023, adcMax = 0;
ISR(ADC_vect) {
  uint16_t v = ADC;
  if (v > adcMax)
    adcMax = v;
  if (v < adcMin)
    adcMin = v;
}

// true while wr() should use native single-byte writes instead of the
// variant selected at build time.
static bool native = false;

// Reads and returns the port of the expander at I2C address a. If the chip
// does not answer, the result is 0xFF.
static uint8_t rd(uint8_t a) {
  Wire.requestFrom(a, (uint8_t)1);
  return Wire.read();
}

// Checks that both ports read back the current state.
//   when  label for the MISMATCH line ("before", "after", "after init")
// A failed check is counted in "bad"; the first 12 are also printed, with
// the write number and the wanted and actual states in hex.
//
// With NOREAD nothing is read. Instead the function waits 450 us and
// measures with micros() how long the wait really took. A wait of more
// than 700 us is counted in slowCount, and for the longest one the I2C
// status and control registers are saved. The code does not say what this
// was meant to catch; what it detects is the wait being stretched, for
// example by interrupts.
static void check(const __FlashStringHelper *when) {
#ifdef NOREAD
  (void)when;
  uint32_t t = micros();
  delayMicroseconds(450);
  t = micros() - t;
  if (t > 700) {
    slowCount++;
    if (t > slowMax) {
      slowMax = t;
      slowTWSR = TWSR;
      slowTWCR = TWCR;
    }
  }
  return;
#endif
  uint8_t lo = rd(0x20), hi = rd(0x21);
  if (lo == lowByte(state) && hi == highByte(state))
    return;
  bad++;
  if (shown < 12) {
    shown++;
    Serial.print(F("  MISMATCH "));
    Serial.print(when);
    Serial.print(F(" write #"));
    Serial.print(writes);
    Serial.print(F(": want "));
    Serial.print(state, HEX);
    Serial.print(F(" got "));
    Serial.println(((uint16_t)hi << 8) | lo, HEX);
  }
}

// Changes the outputs to the 16-bit state s.
// The sequence is: check that the ports still hold the previous state; if s
// is the same as the current state, stop there; otherwise send the new
// state to both expanders (0x20 first) in the way selected by the build
// flags, count the write, and check the ports again. Breadcrumbs are left
// at each step.
static void wr(uint16_t s) {
  CRUMB(1);
  check(F("before"));
  if (s == state)
    return;
  state = s;
  crumbState = s;
  crumbWrites = writes;
  CRUMB(2);
#ifdef NO_I2C
#ifdef TB
  // Toggle one GPIO pin as a push-pull output: 54 pulses at about 100 kHz,
  // the same number of clock pulses as the two I2C transactions.
  // (Each two-byte I2C write is three bytes on the wire, 27 clock pulses.)
  // The pin is made an output only for the burst, then returned to an
  // input, and a 100 us wait follows.
  TD |= _BV(TB);
  for (uint8_t k = 0; k < 54; k++) {
    TP |= _BV(TB);
    delayMicroseconds(4);
    TP &= ~_BV(TB);
    delayMicroseconds(4);
  }
  TD &= ~_BV(TB);
  delayMicroseconds(100);
#else
  delayMicroseconds(
      620); // stands in for the two transactions; no Wire calls at all
#endif
  // The "if (true)" below makes every I2C branch that follows unreachable
  // in a NO_I2C build, while keeping the braces balanced.
  if (true) {
  } else if (native) {
#else
  if (native) {
#endif
    // Native write: one data byte to each expander.
    Wire.beginTransmission(0x20);
    Wire.write(lowByte(s));
    Wire.endTransmission();
    Wire.beginTransmission(0x21);
    Wire.write(highByte(s));
    Wire.endTransmission();
  } else {
#if defined(FORCE0)
    // MCP23008 library write, [0x09][0x00], whatever state was asked for.
    mcp_0.writeGPIO(0);
    CRUMB(3);
    mcp_1.writeGPIO(0);
#elif defined(PREFIX)
    // generic two-byte write straight through Wire: [address][PREFIX][data]
    Wire.beginTransmission(0x20);
    Wire.write((uint8_t)(PREFIX));
    Wire.write(lowByte(s));
    Wire.endTransmission();
    CRUMB(3);
    Wire.beginTransmission(0x21);
    Wire.write((uint8_t)(PREFIX));
    Wire.write(highByte(s));
    Wire.endTransmission();
#elif defined(DATA_THEN_ZERO)
  // same ones on the bus as an MCP-style write, but outputs end up off
  // (two-byte write [data][0x00]: the data appears on the port for one
  // byte time and is then replaced by 00)
  Wire.beginTransmission(0x20);
  Wire.write(lowByte(s));
  Wire.write((uint8_t)0);
  Wire.endTransmission();
  CRUMB(3);
  Wire.beginTransmission(0x21);
  Wire.write(highByte(s));
  Wire.write((uint8_t)0);
  Wire.endTransmission();
#elif defined(ZERO_THEN_DATA)
  // native-style order with a zero prefix: outputs end up on
  // (two-byte write [0x00][data])
  Wire.beginTransmission(0x20);
  Wire.write((uint8_t)0);
  Wire.write(lowByte(s));
  Wire.endTransmission();
  CRUMB(3);
  Wire.beginTransmission(0x21);
  Wire.write((uint8_t)0);
  Wire.write(highByte(s));
  Wire.endTransmission();
#elif defined(NATIVE1)
  // Native single-byte write to each expander.
  Wire.beginTransmission(0x20);
  Wire.write(lowByte(s));
  Wire.endTransmission();
  CRUMB(3);
  Wire.beginTransmission(0x21);
  Wire.write(highByte(s));
  Wire.endTransmission();
#elif defined(HOLDALL)
  // No write at all: only a wait of about the length of the two
  // transactions. The ports keep the FF written once in setup().
  delayMicroseconds(620);
#else
  // Default: the MCP23008 library write, [0x09][data] to each expander.
  mcp_0.writeGPIO(lowByte(s));
  CRUMB(3);
  mcp_1.writeGPIO(highByte(s));
#endif
  }
  writes++;
  CRUMB(4);
  check(F("after"));
  CRUMB(5);
}

// Closes one phase of the test and prints its summary line.
//   name  the phase name to print
// The line gives the writes and mismatches since the previous call and the
// supply voltage range since the previous call. The ADC readings are of the
// 1.1 V reference against the supply, so supply in mV = 1100 * 1023 /
// reading = 1125300 / reading; the highest reading gives the minimum
// voltage. If no reading was taken (ADC not running), the minimum prints as
// 0 and the maximum as 1100. The min/max are then reset, the phase
// breadcrumb is advanced, and with NOREAD the running total of slow waits
// is printed if there were any.
static void phase(const __FlashStringHelper *name) {
  static uint32_t w0 = 0, b0 = 0; // totals at the end of the previous phase
  Serial.print(name);
  Serial.print(F(": writes "));
  Serial.print(writes - w0);
  Serial.print(F(", mismatches "));
  Serial.print(bad - b0);
  // Take and reset the supply extremes with interrupts off, because the ADC
  // interrupt updates these two-byte values.
  noInterrupts();
  uint16_t hi = adcMax, lo = adcMin;
  adcMax = 0;
  adcMin = 1023;
  interrupts();
  Serial.print(F(", UNO supply min "));
  Serial.print(hi ? 1125300L / hi : 0);
  Serial.print(F(" mV, max "));
  Serial.print(lo ? 1125300L / lo : 0);
  Serial.println(F(" mV"));
  w0 = writes;
  b0 = bad;
  crumbPhase++;
  if (slowCount) {
    Serial.print(F("   slow delays so far: "));
    Serial.print(slowCount);
    Serial.print(F(" max us "));
    Serial.println(slowMax);
  }
}

// The whole test runs here, once.
void setup() {
#ifdef CLKDIV
  // Run the CPU slower than the crystal: 1 = half speed (8 MHz), 2 = quarter (4
  // MHz).
  // Writing 0x80 to CLKPR unlocks the clock prescaler; the new division
  // setting must follow immediately.
  CLKPR = 0x80;
  CLKPR = (CLKDIV);
#endif
#ifdef PEPU
  // ATmega328PB only: port E (PE0-PE3, chip pins 3, 6, 19, 22) does not exist
  // on the 328P, so 328P firmware leaves these pins as floating inputs.
  // PEPU is a bit mask of the pins to give an internal pull-up.
  _SFR_IO8(0x0E) |= (PEPU); // PORTE
#endif
#ifdef CLKDIV
  // The Arduino library still believes the clock is 16 MHz, so the
  // requested rate is scaled up by the same factor as the clock is scaled
  // down.
  Serial.begin(38400UL << (CLKDIV)); // real baud rate 38400, which divides
                                     // cleanly at 8 and 4 MHz
#else
  Serial.begin(115200);
#endif
  // Step 1: banner and reset cause. resetCause is what the bootloader
  // passed in r2; MCUSR is printed as found and then cleared.
  Serial.println(F("\nMCP-style write / read-back test"));
  Serial.print(F("reset cause r2=0x"));
  Serial.print(resetCause, HEX);
  Serial.print(F(" (1=power-on 2=external/DTR 4=brown-out 8=watchdog/via "
                 "bootloader) MCUSR=0x"));
  Serial.println(MCUSR, HEX);
  MCUSR = 0;
  // Step 2: the hardware registers as saveResetCause() found them. After a
  // normal reset these hold their reset values (or whatever the bootloader
  // left); after a jump to address 0 they hold what the previous run of
  // this program had set.
  Serial.print(F("at entry: TWBR="));
  Serial.print(savedTWBR);
  Serial.print(F(" TWCR=0x"));
  Serial.print(savedTWCR, HEX);
  Serial.print(F(" TCCR0B="));
  Serial.print(savedTCCR0B);
  Serial.print(F(" UCSR0B=0x"));
  Serial.print(savedUCSR0B, HEX);
  Serial.print(F(" SP=0x"));
  Serial.println(savedSP, HEX);
  // Step 3: if the marker of an unfinished run is still in RAM, print what
  // that run left behind. (The marker is cleared at the very end of a run
  // that completes.)
  if (crumbMagic == 0xC0DE) {
    // The last 64 sampled program addresses, oldest first, 0.5 ms apart,
    // as byte addresses in hex (the stored word address times 2).
    Serial.print(F("PCTRACE"));
    for (uint8_t i = 0; i < 64; i++) {
      uint8_t k = (pcIdx + 2 * i) & 0x7E;
      Serial.print(' ');
      Serial.print((((uint16_t)pcRing[k] << 8) | pcRing[k + 1]) * 2, HEX);
    }
    Serial.println();
    // Where an unused interrupt struck (0 if none did) and the interrupt
    // registers at that moment, in the order listed at saveIrqState().
    Serial.print(F("  unused-vector hit from word address 0x"));
    Serial.print(((uint16_t)badPCH << 8) | badPCL, HEX);
    Serial.print(F("  irq regs:"));
    for (uint8_t i = 0; i < 16; i++) {
      Serial.print(' ');
      Serial.print(badRegs[i], HEX);
    }
    Serial.println();
    // Slow waits recorded by check() in a NOREAD build.
    Serial.print(F("  slow delays: "));
    Serial.print(slowCount);
    Serial.print(F(" max us "));
    Serial.print(slowMax);
    Serial.print(F(" TWSR=0x"));
    Serial.print(slowTWSR, HEX);
    Serial.print(F(" TWCR=0x"));
    Serial.println(slowTWCR, HEX);
    // How far the run had got: phases completed, step inside wr(), write
    // count and state of the last write started, and the unused-vector
    // marker (BD if one was hit, 0 otherwise).
    Serial.print(F("PREVIOUS RUN DID NOT FINISH: phase "));
    Serial.print(crumbPhase);
    Serial.print(F(" step "));
    Serial.print(crumbStep);
    Serial.print(F(" writes "));
    Serial.print(crumbWrites);
    Serial.print(F(" state 0x"));
    Serial.print(crumbState, HEX);
    Serial.print(F(" badISR 0x"));
    Serial.println(crumbBad, HEX);
  }
  // Step 4: clear the records and start the program-counter trace.
  // Timer2 in clear-on-compare mode, prescaler 64: 16 MHz / 64 / (124 + 1)
  // = 2 kHz compare interrupts.
  slowCount = 0;
  slowMax = 0;
  badPCH = badPCL = 0;
  pcIdx = 0;
  TCCR2A = _BV(WGM21);
  TCCR2B = _BV(CS22);
  OCR2A = 124;
  TCNT2 = 0;
  TIMSK2 = _BV(OCIE2A);
  crumbMagic = 0xC0DE;
  crumbPhase = 0;
  crumbStep = 0;
  crumbBad = 0;
  crumbWrites = 0;
#ifndef OLD
  // Step 5: start the supply monitor. AVCC as reference, channel 0x0E (the
  // internal 1.1 V reference), free-running with an interrupt after each
  // conversion, clock prescaler 32. A 20 ms wait follows, after which
  // the extremes recorded so far are discarded just below.
  ADMUX = _BV(REFS0) | 0x0E;
  ADCSRB = 0;
  ADCSRA =
      _BV(ADEN) | _BV(ADSC) | _BV(ADATE) | _BV(ADIE) | _BV(ADPS2) | _BV(ADPS0);
  delay(20);
#endif
  noInterrupts();
  adcMax = 0;
  adcMin = 1023;
  interrupts();
  // Optional variants of the ADC set-up, each replacing the one above.
#if defined(ADC_OFF)
  ADCSRA = 0; // ADC fully disabled
#elif defined(ADC_FREE_NOIRQ)
  ADMUX = _BV(REFS0) | 0x0E;
  ADCSRB = 0; // free-running, no interrupt
  ADCSRA = _BV(ADEN) | _BV(ADSC) | _BV(ADATE) | _BV(ADPS2) | _BV(ADPS0);
// (A variant that drove AREF from the internal 1.1 V reference was removed:
// it must never be used while AREF is jumpered to 5 V.)
#elif defined(REF_ONLY)
  ADMUX = _BV(REFS0) | 0x0E; // only select AVCC reference, ADC idle
#endif
#ifndef NO_I2C
  // Step 6: initialise the expanders through the MCP23008 library, as if
  // they were MCP23008s: begin(0) and begin(1) select addresses
  // 0x20 and 0x21, and every pin is declared an output. The library does
  // this with MCP23008 register reads and writes; a PCF8574 takes every
  // byte written to it as port data.
  mcp_0.begin(0);
  mcp_1.begin(1);
  for (uint8_t i = 0; i < 8; i++) {
    mcp_0.pinMode(i, OUTPUT);
    mcp_1.pinMode(i, OUTPUT);
  }
#endif
#ifdef HOLDALL
  // All sixteen outputs on, and left on for the whole run.
  mcp_0.writeGPIO(0xFF);
  mcp_1.writeGPIO(0xFF);
#endif
  check(F("after init"));
  phase(F("init"));

  // Phase "walking single": 20 rounds over the 16 outputs, each one
  // switched on alone for 2 ms and off for 2 ms.
  for (uint8_t r = 0; r < 20; r++)
    for (uint8_t n = 0; n < 16; n++) {
      wr(1u << n);
      delay(2);
      wr(0);
      delay(2);
    }
  phase(F("walking single"));

  // Phase "cumulative": 20 rounds of switching the outputs on one after
  // another, 2 ms apart, until all 16 are on, then off again one after
  // another.
  for (uint8_t r = 0; r < 20; r++) {
    for (uint8_t n = 0; n < 16; n++) {
      wr(state | (1u << n));
      delay(2);
    }
    for (uint8_t n = 0; n < 16; n++) {
      wr(state & ~(1u << n));
      delay(2);
    }
  }
  phase(F("cumulative"));

  // Whole-bank test patterns: alternate outputs, all on, all off, each
  // bank on by itself.
  static const uint16_t pat[] = {0xAAAA, 0x5555, 0xFFFF,
                                 0x0000, 0xFF00, 0x00FF};
#ifndef OLD
  // Phase "idle, all off": half a second with no writes. Its summary line
  // shows the supply range with everything off.
  delay(500);
  phase(F("idle, all off"));
  // Phase "bank patterns NATIVE" (or "MCP (first)" with MCPFIRST): 100
  // rounds of the six patterns, 2 ms apart, using native writes unless
  // MCPFIRST is defined.
#ifdef MCPFIRST
  native = false;
#else
  native = true;
#endif
  for (uint8_t r = 0; r < 100; r++)
    for (uint8_t i = 0; i < 6; i++) {
      wr(pat[i]);
      delay(2);
    }
  wr(0);
  phase(native ? F("bank patterns NATIVE") : F("bank patterns MCP (first)"));
  native = false;
#endif
  // Phase "bank patterns MCP": the same 100 rounds with the write style
  // selected at build time.
  for (uint8_t r = 0; r < 100; r++)
    for (uint8_t i = 0; i < 6; i++) {
      wr(pat[i]);
      delay(2);
    }
  phase(F("bank patterns MCP"));

  // Phase "toggle 0 with 12 held on": state F6F6 keeps six outputs of each
  // bank on; output 0 is then switched on and off 5000 times, 1 ms apart.
  wr(0xF6F6);
  for (uint16_t i = 0; i < 5000; i++) {
    wr(state ^ 0x0001);
    delay(1);
  }
  phase(F("toggle 0 with 12 held on"));

  // Phase "random single toggles": 5000 times, 1 ms apart, flip one output
  // chosen by a pseudo-random number generator (a linear congruential
  // generator with a fixed seed, so every run uses the same sequence; its
  // top four bits select the output).
  uint32_t x = 12345;
  for (uint16_t i = 0; i < 5000; i++) {
    x = x * 1664525UL + 1013904223UL;
    wr(state ^ (1u << (x >> 28)));
    delay(1);
  }
  phase(F("random single toggles"));

  // Phase "random words, no delay": 5000 writes of a pseudo-random 16-bit
  // state (the top half of the generator's value), as fast as they will go.
  for (uint16_t i = 0; i < 5000; i++) {
    x = x * 1664525UL + 1013904223UL;
    wr((uint16_t)(x >> 16));
  }
  phase(F("random words, no delay"));

  // Finish: everything off, totals, and clear the "run in progress" marker
  // so that the next start does not report an unfinished run.
  wr(0);
  Serial.print(F("TOTAL writes "));
  Serial.print(writes);
  Serial.print(F(", mismatches "));
  Serial.println(bad);
  crumbMagic = 0;
  Serial.println(F("DONE"));
}

// Nothing to do once the sequence has run; press reset to run it again.
void loop() {
}
