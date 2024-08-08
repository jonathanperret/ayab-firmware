/*!
 * \file tester.cpp
 * \brief Class containing methods for hardware testing.
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
 *    Modified Work Copyright 2020-3 Sturla Lange, Tom Price
 *    http://ayab-knitting.com
 */

#include <Arduino.h>

#include "beeper.h"
#include "com.h"
#include "fsm.h"
#include "knitter.h"
#include "tester.h"

// public methods

/*!
 * \brief Help command handler.
 */
void Tester::helpCmd() {
  m_com->sendMsg(AYAB_API::testRes, "The following commands are available:\n");
  m_com->sendMsg(AYAB_API::testRes, "setSingle [0..15] [1/0]\n");
  m_com->sendMsg(AYAB_API::testRes, "setAll [0..FFFF]\n");
  m_com->sendMsg(AYAB_API::testRes, "readEOLsensors\n");
  m_com->sendMsg(AYAB_API::testRes, "readEncoders\n");
  m_com->sendMsg(AYAB_API::testRes, "beep\n");
  m_com->sendMsg(AYAB_API::testRes, "autoRead\n");
  m_com->sendMsg(AYAB_API::testRes, "autoTest\n");
  m_com->sendMsg(AYAB_API::testRes, "send\n");
  m_com->sendMsg(AYAB_API::testRes, "stop\n");
  m_com->sendMsg(AYAB_API::testRes, "quit\n");
  m_com->sendMsg(AYAB_API::testRes, "help\n");
}

/*!
 * \brief Send command handler.
 */
void Tester::sendCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called send\n");
  uint8_t p[] = {0x31, 0x32, 0x33};
  m_com->send(p, 3);
  m_com->sendMsg(AYAB_API::testRes, "\n");
}

/*!
 * \brief Beep command handler.
 */
void Tester::beepCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called beep\n");
  beep();
}

/*!
 * \brief Set single solenoid command handler.
 * \param buffer Pointer to a data buffer.
 * \param size Number of bytes of data in the buffer.
 */
void Tester::setSingleCmd(const uint8_t *buffer, size_t size) {
  m_com->sendMsg(AYAB_API::testRes, "Called setSingle\n");
  if (size < 3U) {
    m_com->sendMsg(AYAB_API::testRes, "Error: invalid arguments\n");
    return;
  }
  uint8_t solenoidNumber = buffer[1];
  if (solenoidNumber > 15) {
    snprintf(buf, BUFFER_LEN, "Error: invalid solenoid index %i\n", solenoidNumber);
    m_com->sendMsg(AYAB_API::testRes, buf);
    return;
  }
  uint8_t solenoidState = buffer[2];
  if (solenoidState > 1) {
    snprintf(buf, BUFFER_LEN, "Error: invalid solenoid value %i\n", solenoidState);
    m_com->sendMsg(AYAB_API::testRes, buf);
    return;
  }
  m_solenoids->setSolenoid(solenoidNumber, solenoidState);
}

/*!
 * \brief Set all solenoids command handler.
 * \param buffer Pointer to a data buffer.
 * \param size Number of bytes of data in the buffer.
 */
void Tester::setAllCmd(const uint8_t *buffer, size_t size) {
  m_com->sendMsg(AYAB_API::testRes, "Called setAll\n");
  if (size < 3U) {
    m_com->sendMsg(AYAB_API::testRes, "Error: invalid arguments\n");
    return;
  }
  uint16_t solenoidState = (buffer[1] << 8) + buffer[2];
  m_solenoids->setSolenoids(solenoidState);
}

/*!
 * \brief Read EOL sensors command handler.
 */
void Tester::readEOLsensorsCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called readEOLsensors\n");
  readEOLsensors();
  m_com->sendMsg(AYAB_API::testRes, "\n");
}

/*!
 * \brief Read encoders command handler.
 */
void Tester::readEncodersCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called readEncoders\n");
  readEncoders();
  m_com->sendMsg(AYAB_API::testRes, "\n");
}

/*!
 * \brief Auto read command handler.
 */
void Tester::autoReadCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called autoRead, send stop to quit\n");
  m_autoReadOn = true;
}

/*!
 * \brief Auto test command handler.
 */
void Tester::autoTestCmd() {
  m_com->sendMsg(AYAB_API::testRes, "Called autoTest, send stop to quit\n");
  m_autoTestOn = true;
}

/*!
 * \brief Stop command handler.
 */
void Tester::stopCmd() {
  m_autoReadOn = false;
  m_autoTestOn = false;
}

/*!
 * \brief Quit command handler.
 */
void Tester::quitCmd() {
  detachInterrupt(digitalPinToInterrupt(ENC_PIN_A));
  detachInterrupt(digitalPinToInterrupt(ENC_PIN_B));

  m_fsm->setState(OpState::init);
  m_knitter->setUpInterrupt();
}

/*!
 * \brief Start hardware test.
 * \param machineType Machine type.
 * \return Error code (0 = success, other values = error).
 */
Err_t Tester::startTest(Machine_t machineType) {
  OpState_t currentState = m_fsm->getState();
  if (OpState::wait_for_machine == currentState || OpState::init == currentState || OpState::ready == currentState) {
    m_fsm->setState(OpState::test);
    m_knitter->setMachineType(machineType);
    setUp();
    return ErrorCode::success;
  }
  return ErrorCode::wrong_machine_state;
}

/*!
 * \brief Main loop for hardware tests.
 */
void Tester::loop() {
  unsigned long now = millis();
  if (now - m_lastTime >= TEST_LOOP_DELAY) {
    m_lastTime = now;
    handleTimerEvent();
  }
}

/*!
 * \brief Interrupt service routine for encoder A.
 */
void Tester::encoderChange() {
  digitalWrite(LED_PIN_A, digitalRead(ENC_PIN_A));
  digitalWrite(LED_PIN_B, digitalRead(ENC_PIN_B));
}

// Private member functions

/*!
 * \brief Setup for hardware tests.
 */
void Tester::setUp() {
  // Print welcome message
  m_com->sendMsg(AYAB_API::testRes, "AYAB Hardware Test, ");
  snprintf(buf, BUFFER_LEN, "Firmware v%hhu.%hhu.%hhu", FW_VERSION_MAJ, FW_VERSION_MIN, FW_VERSION_PATCH);
  m_com->sendMsg(AYAB_API::testRes, buf);
  m_com->sendMsg(AYAB_API::testRes, FW_VERSION_SUFFIX);
  snprintf(buf, BUFFER_LEN, " API v%hhu\n\n", API_VERSION);
  m_com->sendMsg(AYAB_API::testRes, buf);
  helpCmd();

#ifndef AYAB_TESTS
  // Attach interrupts for both encoder pins
  s_instance = this;
  attachInterrupt(digitalPinToInterrupt(ENC_PIN_A), _encoderChange, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_PIN_B), _encoderChange, CHANGE);
#endif // AYAB_TESTS

  m_autoReadOn = false;
  m_autoTestOn = false;
  m_lastTime = millis();
  m_timerEventOdd = false;

  // Enable beeper so that it can be tested
  m_beeper->init(true);
}

/*!
 * \brief Make a beep.
 */
void Tester::beep() const {
  m_beeper->ready();
}

/*!
 * \brief Read the Hall sensors that determine which carriage is in use.
 */
void Tester::readEncoders() const {
  m_com->sendMsg(AYAB_API::testRes, "  ENC_A: ");
  bool state = digitalRead(ENC_PIN_A);
  m_com->sendMsg(AYAB_API::testRes, state ? "HIGH" : "LOW");
  m_com->sendMsg(AYAB_API::testRes, "  ENC_B: ");
  state = digitalRead(ENC_PIN_B);
  m_com->sendMsg(AYAB_API::testRes, state ? "HIGH" : "LOW");
  m_com->sendMsg(AYAB_API::testRes, "  ENC_C: ");
  state = digitalRead(ENC_PIN_C);
  m_com->sendMsg(AYAB_API::testRes, state ? "HIGH" : "LOW");
}

/*!
 * \brief Read the End of Line sensors.
 */
void Tester::readEOLsensors() {
  auto hallSensor = static_cast<uint16_t>(analogRead(EOL_PIN_L));
  snprintf(buf, BUFFER_LEN, "  EOL_L: %hu", hallSensor);
  m_com->sendMsg(AYAB_API::testRes, buf);
  hallSensor = static_cast<uint16_t>(analogRead(EOL_PIN_R));
  snprintf(buf, BUFFER_LEN, "  EOL_R: %hu", hallSensor);
  m_com->sendMsg(AYAB_API::testRes, buf);
}

/*!
 * \brief Read both carriage sensors and End of Line sensors.
 */
void Tester::autoRead() {
  m_com->sendMsg(AYAB_API::testRes, "\n");
  readEOLsensors();
  readEncoders();
  m_com->sendMsg(AYAB_API::testRes, "\n");
}

/*!
 * \brief Set even-numbered solenoids.
 */
void Tester::autoTestEven() const {
  m_com->sendMsg(AYAB_API::testRes, "Set even solenoids\n");
  digitalWrite(LED_PIN_A, HIGH);
  digitalWrite(LED_PIN_B, HIGH);
  m_solenoids->setSolenoids(0xAAAA);
}

/*!
 * \brief Set odd-numbered solenoids.
 */
void Tester::autoTestOdd() const {
  m_com->sendMsg(AYAB_API::testRes, "Set odd solenoids\n");
  digitalWrite(LED_PIN_A, LOW);
  digitalWrite(LED_PIN_B, LOW);
  m_solenoids->setSolenoids(0x5555);
}

/*!
 * \brief Timer event every 500ms to handle auto functions.
 */
void Tester::handleTimerEvent() {
  if (m_autoReadOn && m_timerEventOdd) {
    autoRead();
  }
  if (m_autoTestOn) {
    if (m_timerEventOdd) {
      autoTestOdd();
    } else {
      autoTestEven();
    }
  }
  m_timerEventOdd = !m_timerEventOdd;
}

TesterInterface *Tester::s_instance;
void Tester::_encoderChange() {
  s_instance->encoderChange();
}