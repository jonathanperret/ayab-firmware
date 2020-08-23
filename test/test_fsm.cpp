/*!`
 * \file test_fsm.cpp
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

#include <gtest/gtest.h>

#include <fsm.h>
#include <knitter.h>

#include <beeper_mock.h>
#include <com_mock.h>
#include <solenoids_mock.h>
#include <tester_mock.h>

using ::testing::Mock;
using ::testing::Return;
using ::testing::Test;

extern Fsm *fsm;
extern Knitter *knitter;

extern BeeperMock *beeper;
extern ComMock *com;
extern SolenoidsMock *solenoids;
extern TesterMock *tester;

class FsmTest : public ::testing::Test {
protected:
  void SetUp() override {
    arduinoMock = arduinoMockInstance();

    // pointers to global instances
    beeperMock = beeper;
    comMock = com;
    solenoidsMock = solenoids;
    testerMock = tester;

    // The global instance does not get destroyed at the end of each test.
    // Ordinarily the mock instance would be local and such behaviour would
    // cause a memory leak. We must notify the test that this is not the case.
    Mock::AllowLeak(beeperMock);
    Mock::AllowLeak(comMock);
    Mock::AllowLeak(solenoidsMock);
    Mock::AllowLeak(testerMock);
  }

  void TearDown() override {
    releaseArduinoMock();
  }

  ArduinoMock *arduinoMock;
  BeeperMock *beeperMock;
  ComMock *comMock;
  SolenoidsMock *solenoidsMock;
  TesterMock *testerMock;

  void expect_init() {
    EXPECT_CALL(*arduinoMock, pinMode(ENC_PIN_A, INPUT));
    EXPECT_CALL(*arduinoMock, pinMode(ENC_PIN_B, INPUT));
    EXPECT_CALL(*arduinoMock, pinMode(ENC_PIN_C, INPUT));

    EXPECT_CALL(*arduinoMock, pinMode(LED_PIN_A, OUTPUT));
    EXPECT_CALL(*arduinoMock, pinMode(LED_PIN_B, OUTPUT));

    EXPECT_CALL(*arduinoMock, digitalWrite(LED_PIN_A, 1)); // green LED on
    EXPECT_CALL(*arduinoMock, digitalWrite(LED_PIN_B, 1)); // yellow LED on

    EXPECT_CALL(*solenoidsMock, init);
  }
};

TEST_F(FsmTest, test_init) {
  fsm->init();
  ASSERT_EQ(fsm->getState(), s_init);
}

TEST_F(FsmTest, test_setState) {
  fsm->setState(s_ready);
  ASSERT_EQ(fsm->getState(), s_ready);
}

TEST_F(FsmTest, test_dispatch_init) {
  // Knitter::isReady() == false
  fsm->init();
  EXPECT_CALL(*comMock, update);
  fsm->dispatch();
  ASSERT_EQ(fsm->getState(), s_init);

  // Knitter::isReady() == true
  knitter->m_direction = Right;
  knitter->m_hallActive = Left;
  EXPECT_CALL(*solenoidsMock, setSolenoids(0xFFFF));
  EXPECT_CALL(*comMock, send_indState);
  EXPECT_CALL(*comMock, update);
  fsm->dispatch();
  ASSERT_EQ(fsm->getState(), s_ready);

  // test expectations without destroying instance
  ASSERT_TRUE(Mock::VerifyAndClear(comMock));
  ASSERT_TRUE(Mock::VerifyAndClear(solenoidsMock));
}

TEST_F(FsmTest, test_dispatch_ready) {
  fsm->setState(s_ready);
  EXPECT_CALL(*arduinoMock, digitalWrite(LED_PIN_A, 0));
  EXPECT_CALL(*comMock, update);
  fsm->dispatch();

  // test expectations without destroying instance
  ASSERT_TRUE(Mock::VerifyAndClear(comMock));
}

TEST_F(FsmTest, test_dispatch_test) {
  fsm->setState(s_test);

  // tester->getQuitFlag() == false
  EXPECT_CALL(*testerMock, loop);
  EXPECT_CALL(*testerMock, getQuitFlag).WillOnce(Return(false));
  EXPECT_CALL(*comMock, update);
  fsm->dispatch();

  // tester->getQuitFlag() == true
  EXPECT_CALL(*testerMock, loop);
  EXPECT_CALL(*testerMock, getQuitFlag).WillOnce(Return(true));
  EXPECT_CALL(*comMock, update);
  expect_init();
  fsm->dispatch();

  // test expectations without destroying instance
  ASSERT_TRUE(Mock::VerifyAndClear(testerMock));
  ASSERT_TRUE(Mock::VerifyAndClear(comMock));
  ASSERT_TRUE(Mock::VerifyAndClear(solenoidsMock));
}

TEST_F(FsmTest, test_dispatch_knit) {
  fsm->setState(s_knit);
  EXPECT_CALL(*arduinoMock, digitalWrite(LED_PIN_A, 1));
  EXPECT_CALL(*comMock, update);
  EXPECT_CALL(*comMock, send_reqLine);
  EXPECT_CALL(*beeperMock, finishedLine);
  fsm->dispatch();

  // test expectations without destroying instance
  ASSERT_TRUE(Mock::VerifyAndClear(beeperMock));
  ASSERT_TRUE(Mock::VerifyAndClear(comMock));
}

TEST_F(FsmTest, test_dispatch_default) {
  fsm->setState(static_cast<OpState_t>(4));
  EXPECT_CALL(*comMock, update);
  fsm->dispatch();

  // test expectations without destroying instance
  ASSERT_TRUE(Mock::VerifyAndClear(comMock));
}
