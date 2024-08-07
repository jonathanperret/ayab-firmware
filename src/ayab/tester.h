/*!
 * \file tester.h
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

#ifndef TESTER_H_
#define TESTER_H_

#include <Arduino.h>

#include "beeper.h"
#include "com.h"

constexpr uint8_t BUFFER_LEN = 40;
constexpr unsigned int TEST_LOOP_DELAY = 500; // ms

class FsmInterface;

class TesterInterface {
public:
  virtual ~TesterInterface() = default;

  // any methods that need to be mocked should go here
  virtual Err_t startTest(Machine_t machineType) = 0;
  virtual void loop() = 0;
  virtual void helpCmd() = 0;
  virtual void sendCmd() = 0;
  virtual void beepCmd() = 0;
  virtual void setSingleCmd(const uint8_t *buffer, size_t size) = 0;
  virtual void setAllCmd(const uint8_t *buffer, size_t size) = 0;
  virtual void readEOLsensorsCmd() = 0;
  virtual void readEncodersCmd() = 0;
  virtual void autoReadCmd() = 0;
  virtual void autoTestCmd() = 0;
  virtual void stopCmd() = 0;
  virtual void quitCmd() = 0;
  virtual void encoderAChange() = 0;
};

class BeeperInterface;
class SolenoidsInterface;
class KnitterInterface;

class Tester : public TesterInterface {
public:
  Err_t startTest(Machine_t machineType) final;
  void loop() final;
  void helpCmd() final;
  void sendCmd() final;
  void beepCmd() final;
  void setSingleCmd(const uint8_t *buffer, size_t size) final;
  void setAllCmd(const uint8_t *buffer, size_t size) final;
  void readEOLsensorsCmd() final;
  void readEncodersCmd() final;
  void autoReadCmd() final;
  void autoTestCmd() final;
  void stopCmd() final;
  void quitCmd() final;
  void encoderAChange() final;

private:
  void setUp();
  void beep() const;
  void readEOLsensors();
  void readEncoders() const;
  void autoRead();
  void autoTestEven() const;
  void autoTestOdd() const;
  void handleTimerEvent();

  // ISR static wrapper
  static TesterInterface *s_instance;
  static void _encoderAChange();

  bool m_autoReadOn = false;
  bool m_autoTestOn = false;
  unsigned long m_lastTime = 0U;
  bool m_timerEventOdd = false;

  char buf[BUFFER_LEN] = {0};
};

extern TesterInterface *g_tester;

#endif // TESTER_H_