/*!
 * \file pcfprobe.h
 * \brief Diagnostic for the I2C port expanders, run when hardware test
 *        mode starts. Temporary investigation code, not for release.
 *
 *    This file is part of AYAB.
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
 */

#ifndef PCFPROBE_H_
#define PCFPROBE_H_

/*!
 * \brief Exercise both port expanders and report the result as text.
 *
 * Writes patterns to the two expanders in several ways (the PCF8574's
 * native single-byte write, and two-byte writes with different first
 * bytes, 0x09 being what the MCP23008 driver sends), reads both ports
 * back after every write, and sends a short report as `testRes` messages
 * for the user to copy from the hardware test window.
 *
 * Blocks for about fifteen seconds and energises solenoids in short bursts.
 * Leaves all solenoids off.
 */
void pcfProbeRun();

#endif // PCFPROBE_H_
