// Pin health check for an ATmega328P/PB UNO with NOTHING connected.
//
// 1. Identity (signature row serial), so boards can be told apart.
// 2. Hold test: every pin is driven to a level for 2 ms, then released to a
//    plain input, and watched for 3 s. A healthy floating pin keeps its
//    charge for a while; a pin with leakage to the opposite rail flips fast.
//    Digital reads are used because they do not disturb the pin.
// 3. Analog levels on A0-A5: driven low, driven high, and input with the
//    internal pull-up. Leakage to ground of the order of the pull-up
//    (20-50 k) or less shows as a pull-up level well below the supply.
//
// D0/D1 (serial) and the crystal pins are skipped. D13 feeds the L LED
// buffer on this board, so it is listed but not a pure floating pin.
//
// How it is used
//   There are no serial commands. The sketch runs once after reset and
//   prints its report at 115200 baud:
//     PINHEALTH signature SSSSSS serial N..N
//         device signature and ten-byte chip serial number, in hex
//     As found at start-up: PINB=xx PINC=xx PIND=xx PINE=xx ...
//         the input registers in hex, read before the sketch touched any pin
//     --- pass 1          (then pass 2 and pass 3, each with the following)
//     HOLD after driven LOW, then floating. Per pin: ...
//       D8-D13 (PB0-5): t t t t t t
//       A0-A5  (PC0-5): t t t t t t
//       D2-D7  (PD2-7): t t t t t t
//       PE2-PE3       : t t
//     HOLD after driven HIGH, then floating. ...   (same four rows)
//         one entry per pin, lowest bit first: "held" if the pin still read
//         the driven level 3 s after release, otherwise the sample time in
//         milliseconds (0, 1, 3, 10, 30, 100, 300, 1000 or 3000) at which
//         it was first seen at the opposite level
//     ANALOG levels on A0-A5, mV ...
//       An: low / high / pull-up     (millivolts, taking the supply as
//                                     exactly 5000 mV)
//       internal 1.1 V reference reads raw R -> supply about V mV
//     DONE
//
// Hardware expected
//   An ATmega328P or ATmega328PB board with nothing connected to its pins.
//   Port E exists only on the 328PB; on a 328P the PE2-PE3 row and the PINE
//   value carry no meaning.
#include <Arduino.h>
#include <avr/boot.h>

// Port E registers of the ATmega328PB, given by I/O address because the
// headers for the 328P (the build target) do not define them.
#define PINE_ _SFR_IO8(0x0C)
#define DDRE_ _SFR_IO8(0x0D)
#define PORTE_ _SFR_IO8(0x0E)

// Bit masks of the pins under test in each port:
//   MB  PB0-PB5 = D8-D13   (PB6 and PB7 are the crystal pins)
//   MC  PC0-PC5 = A0-A5    (PC6 is the reset pin)
//   MD  PD2-PD7 = D2-D7    (PD0 and PD1 are the serial port)
//   ME  PE2-PE3            (328PB only)
static const uint8_t MB = 0x3F, MC = 0x3F, MD = 0xFC, ME = 0x0C;
// Times after release, in milliseconds, at which the hold test samples the
// pins. NT is the number of sample times.
static const uint16_t T_MS[] = {0, 1, 3, 10, 30, 100, 300, 1000, 3000};
#define NT (sizeof(T_MS) / sizeof(T_MS[0]))

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Returns one ADC reading, 0 to 1023, with AVCC (the supply) as full scale.
//   ch  ADC multiplexer channel: 0 to 5 for A0 to A5, 0x0E for the chip's
//       internal 1.1 V reference
// After the channel is selected the input is given 200 us to settle. Two
// conversions are run and only the second is returned; the first one after
// a channel change is discarded.
static uint16_t adc(uint8_t ch) {
  ADMUX = _BV(REFS0) | ch;
  delayMicroseconds(200);
  ADCSRA |= _BV(ADSC);
  while (ADCSRA & _BV(ADSC)) {
  }
  ADCSRA |= _BV(ADSC);
  while (ADCSRA & _BV(ADSC)) {
  }
  return ADC;
}

// Hold test: drives every pin under test to one level, lets them all float,
// and reports how long each one kept the level.
//   high  true to drive the pins high first, false to drive them low
// The function takes a little over 3 s.
static void holdTest(bool high) {
  // snap[i][p] = input register of port p (B, C, D, E) at sample time i.
  uint8_t snap[NT][4];
  // Step 1: drive all the pins to the chosen level for 2 ms. The output
  // value is set before the pin is made an output.
  // drive
  PORTB = (PORTB & ~MB) | (high ? MB : 0);
  DDRB |= MB;
  PORTC = (PORTC & ~MC) | (high ? MC : 0);
  DDRC |= MC;
  PORTD = (PORTD & ~MD) | (high ? MD : 0);
  DDRD |= MD;
  PORTE_ = (PORTE_ & ~ME) | (high ? ME : 0);
  DDRE_ |= ME;
  delay(2);
  // Step 2: let go, with interrupts off so the ports are released within a
  // few microseconds of each other. (When a pin that was driven high is
  // made an input, its internal pull-up stays on until the port bit is
  // cleared on the next line.)
  // release: direction to input first, then pull-ups off, as close together as
  // possible
  uint8_t s = SREG;
  cli();
  DDRB &= ~MB;
  PORTB &= ~MB;
  DDRC &= ~MC;
  PORTC &= ~MC;
  DDRD &= ~MD;
  PORTD &= ~MD;
  DDRE_ &= ~ME;
  PORTE_ &= ~ME;
  SREG = s;
  // Step 3: take a snapshot of all four ports at each time in T_MS,
  // measured from the release. Nothing is printed while sampling.
  uint32_t t0 = millis();
  for (uint8_t i = 0; i < NT; i++) {
    while (millis() - t0 < T_MS[i]) {
    }
    snap[i][0] = PINB & MB;
    snap[i][1] = PINC & MC;
    snap[i][2] = PIND & MD;
    snap[i][3] = PINE_ & ME;
  }
  // Step 4: report, one row per port and one entry per tested pin.
  Serial.print(high ? F("HOLD after driven HIGH, then floating. ")
                    : F("HOLD after driven LOW, then floating.  "));
  Serial.println(
      F("Per pin: time (ms) at which it was first seen flipped, or 'held'"));
  static const char *const names[4] = {"D8-D13 (PB0-5)", "A0-A5  (PC0-5)",
                                       "D2-D7  (PD2-7)", "PE2-PE3       "};
  static const uint8_t masks[4] = {MB, MC, MD, ME};
  for (uint8_t p = 0; p < 4; p++) {
    Serial.print(F("  "));
    Serial.print(names[p]);
    Serial.print(':');
    for (uint8_t b = 0; b < 8; b++) {
      if (!(masks[p] & _BV(b)))
        continue;
      // Find the first snapshot in which this pin no longer shows the
      // driven level; -1 means it never changed.
      int16_t when = -1;
      for (uint8_t i = 0; i < NT; i++) {
        bool lvl = snap[i][p] & _BV(b);
        if (lvl != high) {
          when = T_MS[i];
          break;
        }
      }
      Serial.print(' ');
      if (when < 0)
        Serial.print(F("held"));
      else {
        Serial.print(when);
        Serial.print(F("ms"));
      }
    }
    Serial.println();
  }
}

// Analog test: measures each of A0-A5 with its own ADC channel in three
// conditions and prints the three voltages in millivolts, then measures the
// supply voltage. Each pin is left as a plain input afterwards.
static void analogLevels() {
  Serial.println(F("ANALOG levels on A0-A5, mV (supply taken as 5000): driven "
                   "low / driven high / input with pull-up"));
  for (uint8_t ch = 0; ch < 6; ch++) {
    uint8_t m = _BV(ch);
    // Output, driven low; measure after 2 ms.
    DDRC |= m;
    PORTC &= ~m;
    delay(2);
    uint16_t lo = adc(ch);
    // Output, driven high; measure after 2 ms.
    PORTC |= m;
    delay(2);
    uint16_t hi = adc(ch);
    // Input. The port bit is still 1, which keeps the internal pull-up on;
    // measure after 5 ms.
    DDRC &= ~m;
    delay(5);
    uint16_t pu = adc(ch); // input, pull-up still on
    // Pull-up off again.
    PORTC &= ~m;
    // Convert the readings (0..1023 of the supply) to millivolts, taking
    // the supply as 5000 mV.
    Serial.print(F("  A"));
    Serial.print(ch);
    Serial.print(F(": "));
    Serial.print((uint32_t)lo * 5000 / 1023);
    Serial.print(F(" / "));
    Serial.print((uint32_t)hi * 5000 / 1023);
    Serial.print(F(" / "));
    Serial.println((uint32_t)pu * 5000 / 1023);
  }
  // Supply voltage: measure the internal 1.1 V reference (channel 0x0E)
  // with the supply as full scale. The reading is 1.1 V / supply * 1023, so
  // supply in mV = 1100 * 1023 / reading = 1125300 / reading. The result is
  // only as accurate as the internal reference.
  uint16_t bg = adc(0x0E);
  Serial.print(F("  internal 1.1 V reference reads raw "));
  Serial.print(bg);
  Serial.print(F(" -> supply about "));
  Serial.print(1125300L / bg);
  Serial.println(F(" mV"));
}

// Runs the whole check once: identity, pins as found, then three passes of
// the hold test (low, then high) and the analog test.
void setup() {
  // Read the input registers first, before this sketch changes any pin.
  uint8_t b0 = PINB, c0 = PINC, d0 = PIND, e0 = PINE_;
  ADMUX = _BV(REFS0); // AVCC reference (also the stable setting for UNO A)
  // ADC on, clock prescaler 128 (125 kHz ADC clock from the 16 MHz crystal).
  ADCSRA = _BV(ADEN) | 7;
  Serial.begin(115200);
  // Identity: device signature (signature row bytes 0, 2, 4) and the chip
  // serial number (bytes 0x0E to 0x17).
  Serial.print(F("\nPINHEALTH signature "));
  hx(boot_signature_byte_get(0));
  hx(boot_signature_byte_get(2));
  hx(boot_signature_byte_get(4));
  Serial.print(F(" serial "));
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx(boot_signature_byte_get(a));
  Serial.println();
  Serial.print(F("As found at start-up: PINB="));
  hx(b0);
  Serial.print(F(" PINC="));
  hx(c0);
  Serial.print(F(" PIND="));
  hx(d0);
  Serial.print(F(" PINE="));
  hx(e0);
  Serial.println(
      F("  (PE0 is the old GND pin, PE1 the old VCC pin on a 328P layout)"));
  // Three identical passes of the tests.
  for (uint8_t r = 0; r < 3; r++) {
    Serial.print(F("--- pass "));
    Serial.println(r + 1);
    holdTest(false);
    holdTest(true);
    analogLevels();
  }
  Serial.println(F("DONE"));
}

// Nothing to do after the report; press reset to run it again.
void loop() {
}
