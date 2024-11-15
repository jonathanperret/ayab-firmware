/*!
 * \file test_knitting_machine.cpp
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
 *    http://ayab-knitting.com
 */

/**
 * This test suite is meant to validate that the KnittingMachine class
 * faithfully reproduces the behavior of a real knitting machine.
 */

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <limits.h>

#include "knitting_machine.h"

using namespace ::testing;

TEST(KnittingMachine, EncoderOutputsMovingRight) {
  KnittingMachine km;

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());

  km.moveBeltRight();

  ASSERT_EQ(true, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());

  km.moveBeltRight();

  ASSERT_EQ(true, km.getEncoderOutput1());
  ASSERT_EQ(false, km.getEncoderOutput2());

  km.moveBeltRight();

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(false, km.getEncoderOutput2());

  km.moveBeltRight();

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());
}

TEST(KnittingMachine, EncoderOutputsMovingLeft) {
  KnittingMachine km;

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());

  km.moveBeltLeft();

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(false, km.getEncoderOutput2());

  km.moveBeltLeft();

  ASSERT_EQ(true, km.getEncoderOutput1());
  ASSERT_EQ(false, km.getEncoderOutput2());

  km.moveBeltLeft();

  ASSERT_EQ(true, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());

  km.moveBeltLeft();

  ASSERT_EQ(false, km.getEncoderOutput1());
  ASSERT_EQ(true, km.getEncoderOutput2());
}

TEST(KnittingMachine, KCarriageDetectionOnTheLeft) {
  KnittingMachine km;

  km.putCarriageCenterInFrontOfNeedle(-100);
  km.addCarriageMagnet(0, true);

  ASSERT_THAT(km.getLeftPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));

  km.putCarriageCenterInFrontOfNeedle(0);

  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Gt(3.4));

  km.putCarriageCenterInFrontOfNeedle(5);

  ASSERT_THAT(km.getLeftPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));
}

TEST(KnittingMachine, LCarriageDetectionOnTheLeft) {
  KnittingMachine km;

  km.addCarriageMagnet(0, false);

  km.putCarriageCenterInFrontOfNeedle(0);

  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Lt(0.4));

  km.putCarriageCenterInFrontOfNeedle(5);

  ASSERT_THAT(km.getLeftPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));
}

TEST(KnittingMachine, GCarriageDetectionOnTheLeft) {
  KnittingMachine km;

  km.addGCarriageMagnets();

  km.putCarriageCenterInFrontOfNeedle(-12);
  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Lt(0.4));

  km.putCarriageCenterInFrontOfNeedle(-11);
  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Gt(3.4));

  km.putCarriageCenterInFrontOfNeedle(0);
  ASSERT_THAT(km.getLeftPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));

  km.putCarriageCenterInFrontOfNeedle(10);
  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Gt(3.4));

  km.putCarriageCenterInFrontOfNeedle(11);
  ASSERT_THAT(km.getLeftPositionSensorVoltage(), Lt(0.4));
}

TEST(KnittingMachine, KCarriageDetectionOnTheRight) {
  KnittingMachine km;

  km.putCarriageCenterInFrontOfNeedle(-100);
  km.addCarriageMagnet(0, true);

  ASSERT_THAT(km.getRightPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));
  ASSERT_THAT(km.getRightPositionSensorKSignal(), AllOf(Gt(1), Lt(4)));

  km.putCarriageCenterInFrontOfNeedle(200);

  ASSERT_THAT(km.getRightPositionSensorVoltage(), Gt(3.4));
  ASSERT_THAT(km.getRightPositionSensorKSignal(), Lt(0.4));

  km.putCarriageCenterInFrontOfNeedle(190);

  ASSERT_THAT(km.getRightPositionSensorVoltage(), AllOf(Gt(0.4), Lt(3.4)));
  ASSERT_THAT(km.getRightPositionSensorKSignal(), AllOf(Gt(1), Lt(4)));
}

TEST(KnittingMachine, MoveCarriageIncrementally) {
  KnittingMachine km;

  km.putCarriageCenterInFrontOfNeedle(-1);
  ASSERT_EQ(km.getCarriageCenterNeedle(), -1);

  // One step to the right isn't enough to change needle
  km.moveCarriageRight();
  ASSERT_EQ(km.getCarriageCenterNeedle(), -1);

  // Three more will do the trick
  km.moveCarriageRight();
  km.moveCarriageRight();
  km.moveCarriageRight();
  ASSERT_EQ(km.getCarriageCenterNeedle(), 0);

  // There's a helper to move until a position is reached
  int stepCount = 0;
  while (km.moveCarriageCenterTowardsNeedle(5)) {
    stepCount++;
  }

  ASSERT_EQ(km.getCarriageCenterNeedle(), 5);
  ASSERT_EQ(stepCount, 20);

  // You can go to the left as well
  while (km.moveCarriageCenterTowardsNeedle(0))
    ;
  ASSERT_EQ(km.getCarriageCenterNeedle(), 0);
}

TEST(KnittingMachine, BeltPhaseSignal) {
  KnittingMachine km;

  ASSERT_FALSE(km.getBeltPhase());

  for (int i = 0; i < 8 * 4; i++) {
    km.moveBeltLeft();
  }
  ASSERT_TRUE(km.getBeltPhase());

  for (int i = 0; i < 8 * 4; i++) {
    km.moveBeltRight();
  }
  ASSERT_FALSE(km.getBeltPhase());
}

TEST(KnittingMachine, CarriageMovesBeltOnlyWhenInSync) {
  KnittingMachine km;

  ASSERT_FALSE(km.getBeltPhase());

  // Setting the carriage in a position where its belt hooks don't engage belt
  // holes (because they are offset).
  km.putCarriageCenterInFrontOfNeedle(1);

  // So when it moves to the left, the belt doesn't move, its phase doesn't
  // change.
  while (km.moveCarriageCenterTowardsNeedle(0)) {
    ASSERT_FALSE(km.getBeltPhase());
  }

  // Now that the carriage is at a belt position divisible by 8, it's engaged
  // and the belt moves.
  while (km.moveCarriageCenterTowardsNeedle(-4)) {
  }
  ASSERT_TRUE(km.getBeltPhase());
}

/**
 * Helper to print the value of all signals while moving a carriage
 * across the bed.
 * The output can be extracted and compared with a similar scan
 * recorded on an actual machine.
 * Sample `ctest` invocation to extract data:
 *
 *   ctest --test-dir test/build -V -R KCarriageScanBed|grep SCAN=|cut -d= -f2
 */
void doBedScan(KnittingMachine &km) {
  float centerNeedle = -32;
  km.putCarriageCenterInFrontOfNeedle(centerNeedle);

  while (km.moveCarriageCenterTowardsNeedle(231)) {
    centerNeedle += 1.0 / 4;
    printf("SCAN=%g\t%g\t%g\t%g\t%d\n", centerNeedle,
           km.getLeftPositionSensorVoltage(),
           km.getRightPositionSensorVoltage(),
           km.getRightPositionSensorKSignal(), km.getBeltPhase() ? 5 : 0);
  }
}

TEST(KnittingMachine, GCarriageScanBed) {
  KnittingMachine km;

  km.addGCarriageMagnets();
  doBedScan(km);
}

TEST(KnittingMachine, KCarriageScanBed) {
  KnittingMachine km;

  km.addCarriageMagnet(0, true);
  doBedScan(km);
}

TEST(KnittingMachine, NeedleSelectionTurningSolenoidsOn) {
  KnittingMachine km;

  km.setSolenoidCount(16);
  km.setNeedleCount(200);
  km.setCarriageNeedleTestDistance(24);

  km.setNeedlePositions(0, "BBBBBBBBBBBBBBBB"
                           "BBBBBBBBBBBBBBBB");

  // insert carriage at left of left turn mark
  km.putCarriageCenterInFrontOfNeedle(-32);

  // slide carriage until its left edge is on the left turn mark
  while (km.moveCarriageCenterTowardsNeedle(32))
    ;

  // now turn some solenoids on
  for (int i = 0; i < 16; i += 2)
    km.setSolenoid(i, true);

  // slide carriage some more
  while (km.moveCarriageCenterTowardsNeedle(100))
    ;

  // Needles that the selector passed before solenoid activation
  // move to D as if the solenoids were never powered.
  // Machine test (KH910, K carriage) shows 14/15 first needles remain in D
  // (same result on the right side).
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("DDDDDDDDDDDDDDBD"
                                                  "BDBDBDBDBDBDBDBD"));

  // move carriage back to outside at left
  while (km.moveCarriageCenterTowardsNeedle(-32))
    ;

  // everything now selected
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("BDBDBDBDBDBDBDBD"
                                                  "BDBDBDBDBDBDBDBD"));
}

TEST(KnittingMachine, NeedleSelectionTurningSolenoidsOn_LCarriage) {
  KnittingMachine km;

  km.setSolenoidCount(16);
  km.setNeedleCount(200);
  km.setCarriageNeedleTestDistance(12);
  km.setCarriageHookDistance(20);

  km.setNeedlePositions(0, "BBBBBBBBBBBBBBBB"
                           "BBBBBBBBBBBBBBBB");

  // insert carriage at left of left turn mark
  km.putCarriageCenterInFrontOfNeedle(-24);

  // slide carriage until its left edge is on the left turn mark
  while (km.moveCarriageCenterTowardsNeedle(24))
    ;

  // now turn some solenoids on
  for (int i = 0; i < 16; i += 2)
    km.setSolenoid(i, true);

  // slide carriage some more
  while (km.moveCarriageCenterTowardsNeedle(100))
    ;

  // Needles that the selector passed before solenoid activation
  // move to D as if the solenoids were never powered.
  // Machine test (KH910, L carriage) shows 18/19 first needles remain in D
  // (same result on the right side).
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("DDDDDDDDDDDDDDDD"
                                                  "DDBDBDBDBDBDBDBD"));

  // move carriage back to outside at left
  while (km.moveCarriageCenterTowardsNeedle(-32))
    ;

  // everything now selected
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("BDBDBDBDBDBDBDBD"
                                                  "BDBDBDBDBDBDBDBD"));
}

TEST(KnittingMachine, NeedleSelectionTurningSolenoidsOn_GCarriage) {
  KnittingMachine km;

  km.setSolenoidCount(16);
  km.setNeedleCount(200);
  km.setCarriageNeedleTestDistance(0);
  km.setCarriageHookDistance(24);

  km.setNeedlePositions(0, "BBBBBBBBBBBBBBBB"
                           "BBBBBBBBBBBBBBBB");

  // insert carriage at left of left turn mark
  km.putCarriageCenterInFrontOfNeedle(-28);

  // slide carriage until its center is on the left turn mark
  while (km.moveCarriageCenterTowardsNeedle(0))
    ;

  // now turn some solenoids on
  for (int i = 0; i < 16; i += 2)
    km.setSolenoid(i, true);

  // slide carriage some more
  while (km.moveCarriageCenterTowardsNeedle(32))
    ;

  // Needles that the selector passed before solenoid activation
  // move to D as if the solenoids were never powered.
  // Machine test (KH910, G carriage) shows 5/6 first needles
  // are knit as if unselected.
  // Note that for simplicity, we simulate the G carriage "selecting"
  // needles to B or D when in reality it always leaves needles in B
  // position and just does a different stitch based on what their
  // selection would have been.
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("DDDDDDBDBDBDBDBD"
                                                  "BDBDBDBDBDBDBDBD"));

  // move carriage back to outside at left
  while (km.moveCarriageCenterTowardsNeedle(-32))
    ;

  // everything now selected
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("BDBDBDBDBDBDBDBD"
                                                  "BDBDBDBDBDBDBDBD"));
}

TEST(KnittingMachine, NeedleSelectionBeltPhaseNormal) {
  KnittingMachine km;

  km.setSolenoidCount(16);
  km.setNeedleCount(200);

  km.setNeedlePositions(0, "BBBBBBBBBBBBBBBB"
                           "BBBBBBBBBBBBBBBB");

  // insert carriage at left of left turn mark, with normal belt engagement
  km.putCarriageCenterInFrontOfNeedle(-32);

  // turn solenoid 0 on
  km.setSolenoid(0, true);

  // slide carriage over
  while (km.moveCarriageCenterTowardsNeedle(64))
    ;

  // only needles 0+16*n are affected
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("BDDDDDDDDDDDDDDD"
                                                  "BDDDDDDDDDDDDDDD"));
}

TEST(KnittingMachine, NeedleSelectionBeltPhaseShifted) {
  KnittingMachine km;

  km.setSolenoidCount(16);
  km.setNeedleCount(200);

  km.setNeedlePositions(0, "BBBBBBBBBBBBBBBB"
                           "BBBBBBBBBBBBBBBB");

  // insert carriage at left of left turn mark, with shifted belt engagement
  km.putCarriageCenterInFrontOfNeedle(-32 + 8);

  // turn solenoid 0 on
  km.setSolenoid(0, true);

  // slide carriage over
  while (km.moveCarriageCenterTowardsNeedle(64))
    ;

  // only needles 8+16*n are affected
  EXPECT_THAT(km.getNeedlePositions(), StartsWith("DDDDDDDDBDDDDDDD"
                                                  "DDDDDDDDBDDDDDDD"));
}
