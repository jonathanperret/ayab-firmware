// I2C bus diagnostic: are SDA and SCL pulled up by the board, and which
// addresses answer?
//
// Purpose
//   A one-shot check of the I2C wiring between the controller and the
//   interface board, run before any of the other test sketches. It answers
//   three questions: which controller chip is this, do the two bus lines
//   have external pull-up resistors, and which I2C addresses acknowledge.
//
// How it is used
//   There are no serial commands. The sketch runs once after reset and
//   prints its report at 115200 baud:
//     BUSDIAG chip signature SSSSSS serial NNNNNNNNNNNNNNNNNNNN
//         SSSSSS is the three-byte device signature in hex (1E950F for an
//         ATmega328P). The serial field is ten bytes of the signature row
//         in hex, used to tell individual boards apart.
//     SDA (A4): after being driven low and released, reads HIGH|LOW at
//         0.2 ms, HIGH|LOW at 20 ms, about V mV -> verdict
//     SCL (A5): the same line for the clock pin
//     Addresses that acknowledge: 0xAA 0xBB ...   (or "none")
//     DONE
//   The voltage is in millivolts and assumes a 5.000 V supply.
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) with SDA on A4 and SCL on A5.
//   With the interface board connected, the two PCF8574 expanders should
//   answer at 0x20 and 0x21. The sketch is also meaningful with nothing
//   connected: it then reports that there are no pull-ups and no devices.
#include <Arduino.h>
#include <Wire.h>
#include <avr/boot.h>

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Tests one bus line for a pull-up and prints one line of report.
//   name  label printed at the start of the line (stored in flash)
//   pin   Arduino pin number of the line (A4 or A5)
// The pin is discharged by driving it low, then released with the
// controller's internal pull-up switched off, so only an external resistor
// (or leakage) can bring it back up. It is read twice: a real pull-up of a
// few kilohms has the line high again well within 0.2 ms; a line that is
// only high after 20 ms is being raised by something much weaker.
// Call this before Wire.begin(), because Wire.begin() switches on the
// internal pull-ups and takes over the pins.
static void line(const __FlashStringHelper *name, uint8_t pin) {
  // Discharge the line: drive it low for 2 ms.
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delay(2);
  // Release it and sample after 0.2 ms and again 20 ms later.
  pinMode(pin, INPUT); // released, internal pull-up off
  delayMicroseconds(200);
  bool fast = digitalRead(pin);
  delay(20);
  bool slow = digitalRead(pin);
  // Measure the settled level. analogRead() returns 0..1023 for 0..supply;
  // the conversion to millivolts takes the supply as 5000 mV.
  uint16_t mv = (uint32_t)analogRead(pin) * 5000 / 1023;
  // Report. The verdict depends only on the two digital reads:
  //   high at 0.2 ms           -> pulled up externally
  //   low at 0.2 ms, high later -> only a weak pull-up or leakage
  //   low both times           -> no pull-up
  Serial.print(name);
  Serial.print(F(": after being driven low and released, reads "));
  Serial.print(fast ? F("HIGH") : F("LOW"));
  Serial.print(F(" at 0.2 ms, "));
  Serial.print(slow ? F("HIGH") : F("LOW"));
  Serial.print(F(" at 20 ms, about "));
  Serial.print(mv);
  Serial.print(F(" mV -> "));
  Serial.println(fast ? F("pulled up externally")
                      : (slow ? F("only a weak pull-up or leakage")
                              : F("NO pull-up on this line")));
}

// Runs the whole diagnostic once and prints the report.
void setup() {
  Serial.begin(115200);
  // Step 1: identify the controller chip. Bytes 0, 2 and 4 of the signature
  // row are the device signature; bytes 0x0E to 0x17 are printed as a
  // serial number that differs from chip to chip.
  Serial.print(F("\nBUSDIAG chip signature "));
  hx(boot_signature_byte_get(0));
  hx(boot_signature_byte_get(2));
  hx(boot_signature_byte_get(4));
  Serial.print(F(" serial "));
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx(boot_signature_byte_get(a));
  Serial.println();
  // Step 2: pull-up test on each bus line, before the I2C hardware is
  // enabled.
  line(F("SDA (A4)"), A4);
  line(F("SCL (A5)"), A5);
  // Step 3: address scan. Each address from 0x03 to 0x77 (the usable 7-bit
  // range) is sent with no data; endTransmission() returns 0 when a device
  // acknowledged it.
  Wire.begin();
  Serial.print(F("Addresses that acknowledge:"));
  uint8_t found = 0;
  for (uint8_t a = 0x03; a <= 0x77; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print(F(" 0x"));
      hx(a);
      found++;
    }
  }
  if (!found)
    Serial.print(F(" none"));
  Serial.println();
  Serial.println(F("DONE"));
}

// Nothing to do after the report; press reset to run it again.
void loop() {
}
