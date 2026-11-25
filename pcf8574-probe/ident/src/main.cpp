// Print the chip's own identity from its signature row.
//
// Purpose
//   Tells one controller board from another. Several look-alike UNO boards
//   were used in this investigation; this sketch prints everything the
//   microcontroller can report about itself, so that a test log can be
//   tied to a particular chip.
//
// How it is used
//   There are no serial commands. The sketch runs once after reset and
//   prints two lines at 115200 baud (all values in hexadecimal):
//     IDENT signature SSSSSS osccal CC serial N..N row R..R
//           fuses L/H/E/lock LL/HH/EE/KK
//     DONE
//   (the first line is shown wrapped here; it is one line on the wire)
//     signature  three-byte device signature (1E950F for an ATmega328P)
//     osccal     factory calibration byte of the internal RC oscillator
//     serial     ten bytes at signature row addresses 0x0E to 0x17, which
//                differ from chip to chip
//     row        the first 32 bytes of the signature row, unprocessed
//     fuses      low, high and extended fuse bytes and the lock bits
//
// Hardware expected
//   Any ATmega328P board (UNO or compatible). Nothing needs to be connected.
#include <Arduino.h>
#include <avr/boot.h>

// Prints one byte as exactly two hexadecimal digits (with a leading zero).
static void hx(uint8_t v) {
  if (v < 16)
    Serial.print('0');
  Serial.print(v, HEX);
}

// Reads and prints the identity once.
void setup() {
  // Select AVCC as the ADC voltage reference. This sketch never uses the
  // ADC, and this file does not say why the line is here. The same line in
  // ../../src/main.cpp is commented as the setting that stops one UNO clone
  // from crashing at random.
  ADMUX = _BV(REFS0);
  Serial.begin(115200);
  // Device signature: bytes 0, 2 and 4 of the signature row.
  Serial.print(F("\nIDENT signature "));
  hx(boot_signature_byte_get(0));
  hx(boot_signature_byte_get(2));
  hx(boot_signature_byte_get(4));
  // RC oscillator calibration: byte 1 of the signature row.
  Serial.print(F(" osccal "));
  hx(boot_signature_byte_get(1));
  // Per-chip serial number: bytes 0x0E to 0x17.
  Serial.print(F(" serial "));
  for (uint8_t a = 0x0E; a <= 0x17; a++)
    hx(boot_signature_byte_get(a));
  // Raw dump of signature row bytes 0x00 to 0x1F.
  Serial.print(F(" row "));
  for (uint8_t a = 0; a < 0x20; a++)
    hx(boot_signature_byte_get(a));
  // Fuse bytes and lock bits, as the chip itself reads them.
  Serial.print(F(" fuses L/H/E/lock "));
  hx(boot_lock_fuse_bits_get(GET_LOW_FUSE_BITS));
  Serial.print('/');
  hx(boot_lock_fuse_bits_get(GET_HIGH_FUSE_BITS));
  Serial.print('/');
  hx(boot_lock_fuse_bits_get(GET_EXTENDED_FUSE_BITS));
  Serial.print('/');
  hx(boot_lock_fuse_bits_get(GET_LOCK_BITS));
  Serial.println();
  Serial.println(F("DONE"));
}

// Nothing to do after the report; press reset to print it again.
void loop() {
}
