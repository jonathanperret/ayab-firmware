/*!
 * \file main.cpp
 * \brief Main entry point for AYAB firmware.
 *
 * This file is part of AYAB.
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
 *
 *    Original Work Copyright 2013 Christian Obersteiner, Andreas Müller
 *    Modified Work Copyright 2020 Sturla Lange, Tom Price
 *    http://ayab-knitting.com
 */

#include <Arduino.h>

#include "beeper.h"
#include "com.h"
#include "encoders.h"
#include "fsm.h"
#include "knitter.h"
#include "solenoids.h"
#include "tester.h"

// Global objects
Beeper beeper;
Encoders encoders;
Solenoids solenoids;
Com com;
Knitter knitter;
Tester tester;
Fsm fsm;

/*!
 * Setup - do once before going to the main loop.
 */
#if ENABLE_STACK_CANARY

#define STACK_CANARY_VALUE 0x55aa

uint16_t *stackCanary = nullptr;

void stackCanarySetup() {
  // Allocate a word on the top of the heap. If the stack, which grows
  // downward from the top of memory, overflows, this value will likely
  // be overwritten.
  stackCanary = new uint16_t(STACK_CANARY_VALUE);
}

void stackCanaryCheck() {
  if (*stackCanary != STACK_CANARY_VALUE) {
    // Memory has been corrupted. Enter "panic" mode: flash LEDs rapidly,
    // and output "PANIC" on the serial port repeatedly.
    while(true) {
      Serial.print("PANIC");
      pinMode(LED_BUILTIN, OUTPUT);
      pinMode(LED_PIN_B, OUTPUT);
      digitalWrite(LED_PIN_B, LOW);
      digitalWrite(LED_BUILTIN, LOW);
      delay(200);
      digitalWrite(LED_PIN_B, HIGH);
      digitalWrite(LED_BUILTIN, HIGH);
      delay(200);
    }
  } 
}

#else // ENABLE_STACK_CANARY

#define stackCanarySetup()
#define stackCanaryCheck()

#endif // ENABLE_STACK_CANARY

void setup() {
  stackCanarySetup();

  // inject collaborators
  com.inject(&beeper, &encoders, &fsm, &knitter, &tester);
  knitter.inject(&beeper, &encoders, &solenoids, &com, &fsm);
  tester.inject(&beeper, &solenoids, &com, &knitter, &fsm);
  fsm.inject(&com, &knitter, &tester);

  beeper.init(false);
  solenoids.init();
  com.init();
  fsm.init();
  knitter.init();
}

/*!
 * Main Loop - repeat forever.
 */
void loop() {
  stackCanaryCheck();

  fsm.dispatch();
  if (beeper.enabled()) {
    beeper.schedule();
  }
}
