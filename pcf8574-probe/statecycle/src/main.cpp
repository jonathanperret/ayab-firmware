// Hold each of four static output states for 700 ms, announcing each one on
// serial, so a scope can measure steady levels in each state.
//   0: both chips 0x00
//   1: chip 0x21 = 0xFF
//   2: both 0x00
//   3: chip 0x20 = 0xFF
//
// Purpose
//   Gives an oscilloscope (or a meter) long, steady periods with one whole
//   bank of eight solenoids switched on and the other bank off, separated by
//   periods with everything off. A set bit in the byte written to a PCF8574
//   switches the matching solenoid on, so 0xFF is a whole bank on.
//
// How it is used
//   There are no serial commands. The sketch cycles through the four states
//   for ever. Just after it has written a state it prints, at 115200 baud:
//     STATE n        (n = 0, 1, 2 or 3, as listed above)
//   so a capture script can label what the scope sees. Each state lasts
//   700 ms; a full cycle takes 2.8 s. The writes are not checked: the
//   sketch does not look at acknowledges and never reads the ports back.
//
// Hardware expected
//   An ATmega328P board (UNO or compatible) connected by I2C (SDA = A4,
//   SCL = A5) to the interface board with its two PCF8574 expanders at 0x20
//   and 0x21, each driving a ULN2803 and eight solenoids.
#include <Arduino.h>
#include <Wire.h>

// Writes one byte to a PCF8574 as a plain ("native") single-byte write.
//   addr  7-bit I2C address of the expander (0x20 or 0x21)
//   v     new output byte; each 1 bit switches one solenoid on
static void wr(uint8_t addr, uint8_t v) {
  Wire.beginTransmission(addr);
  Wire.write(v);
  Wire.endTransmission();
}

// Starts serial and I2C and switches every solenoid off.
void setup() {
  // Select AVCC as the ADC voltage reference. This sketch never uses the
  // ADC, and this file does not say why the line is here. The same line in
  // ../../src/main.cpp is commented as the setting that stops one UNO clone
  // from crashing at random.
  ADMUX = _BV(REFS0);
  Serial.begin(115200);
  Wire.begin();
  wr(0x20, 0);
  wr(0x21, 0);
}

// One pass sets and announces one state, holds it for 700 ms, then moves on
// to the next state. Expander 0x20 is always written before 0x21.
void loop() {
  static uint8_t s = 0; // current state number, 0 to 3
  wr(0x20, s == 3 ? 0xFF : 0x00);
  wr(0x21, s == 1 ? 0xFF : 0x00);
  Serial.print(F("STATE "));
  Serial.println(s);
  delay(700);
  s = (s + 1) & 3; // 0, 1, 2, 3, 0, ...
}
