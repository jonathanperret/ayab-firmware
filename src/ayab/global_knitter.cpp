/*!
 * \file global_knitter.cpp
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

#include "knitter.h"

// static member functions

void GlobalKnitter::init() {
  m_instance->init();
}

void GlobalKnitter::fsm() {
  m_instance->fsm();
}

void GlobalKnitter::setUpInterrupt() {
  m_instance->setUpInterrupt();
}

#ifndef AYAB_TESTS
void GlobalKnitter::isr() {
  m_instance->isr();
}
#endif

bool GlobalKnitter::startOperation(Machine_t machineType, uint8_t startNeedle,
                                   uint8_t stopNeedle, uint8_t *pattern_start,
                                   bool continuousReportingEnabled) {
  return m_instance->startOperation(machineType, startNeedle, stopNeedle,
                                    pattern_start, continuousReportingEnabled);
}

bool GlobalKnitter::startTest(Machine_t machineType) {
  return m_instance->startTest(machineType);
}

uint8_t GlobalKnitter::getStartOffset(const Direction_t direction) {
  return m_instance->getStartOffset(direction);
}

Machine_t GlobalKnitter::getMachineType() {
  return m_instance->getMachineType();
}

void GlobalKnitter::setSolenoids(uint16_t state) {
  m_instance->setSolenoids(state);
}

bool GlobalKnitter::setNextLine(uint8_t lineNumber) {
  return m_instance->setNextLine(lineNumber);
}

void GlobalKnitter::setLastLine() {
  m_instance->setLastLine();
}

void GlobalKnitter::setMachineType(Machine_t machineType) {
  m_instance->setMachineType(machineType);
}

void GlobalKnitter::setState(OpState_t state) {
  m_instance->setState(state);
}
