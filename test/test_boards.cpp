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

#include <beeper.h>
#include <com.h>
#include <encoders.h>
#include <solenoids.h>
#include <tester.h>

#include <fsm_mock.h>
#include <knitter_mock.h>

// global definitions
// references everywhere else must use `extern`
Beeper *beeper = new Beeper();
Encoders *encoders = new Encoders();
Solenoids *solenoids = new Solenoids();
Com *com = new Com();

Tester *tester = new Tester();

KnitterMock *knitter = new KnitterMock();
FsmMock *fsm = new FsmMock();

BeeperInterface *g_beeper = beeper;
EncodersInterface *g_encoders = encoders;
SolenoidsInterface *g_solenoids = solenoids;
ComInterface *g_com = com;
KnitterInterface *g_knitter = knitter;
TesterInterface *g_tester = tester;
FsmInterface *g_fsm = fsm;

int main(int argc, char *argv[]) {
  ::testing::InitGoogleMock(&argc, argv);
  return RUN_ALL_TESTS();
}
