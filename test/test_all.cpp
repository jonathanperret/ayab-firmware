/*!`
 * \file test_all.cpp
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

#include "gtest/gtest.h"

#include <fsm.h>
#include <knitter.h>

#include <beeper_mock.h>
#include <com_mock.h>
#include <encoders_mock.h>
#include <solenoids_mock.h>
#include <tester_mock.h>

// global definitions
// references everywhere else must use `extern`

BeeperMock *beeper = new BeeperMock();
EncodersMock *encoders = new EncodersMock();
ComMock *com = new ComMock();
Fsm *fsm = new Fsm(com);
Knitter *knitter = new Knitter(beeper, com, encoders);
SolenoidsMock *solenoids = new SolenoidsMock();
TesterMock *tester = new TesterMock();

// instantiate singleton classes with mock objects
FsmInterface *GlobalFsm::m_instance = fsm;
KnitterInterface *GlobalKnitter::m_instance = knitter;

SolenoidsInterface *GlobalSolenoids::m_instance = solenoids;
TesterInterface *GlobalTester::m_instance = tester;

int main(int argc, char *argv[]) {
  ::testing::InitGoogleMock(&argc, argv);
	return RUN_ALL_TESTS();
}
