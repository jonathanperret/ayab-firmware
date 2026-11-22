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
 * \brief Start a probe of both port expanders.
 *
 * The probe writes patterns to the two expanders in several ways (the
 * PCF8574's native single-byte write, and two-byte writes with different
 * first bytes, 0x09 being what the MCP23008 driver sends), reads both
 * ports back after every write, and sends a short report as `testRes`
 * messages for the user to copy from the hardware test window. It also
 * replays how the fault was first seen: solenoids enabled one by one from
 * 0 to 15, counting wrong read-backs per solenoid.
 *
 * Last, it switches seven solenoids off and back on with the second write
 * clocked by hand instead of by the I2C hardware, holding the bus lines in
 * a different state around the acknowledge bit each time, to see whether
 * the state of the bus matters when an expander resets.
 *
 * This only arms the probe. The work is done by pcfProbeStep().
 */
void pcfProbeStart();

/*!
 * \brief Advance the probe by one stage. Call repeatedly from the test loop.
 *
 * Does nothing unless a probe has been started. Each call takes from a few
 * milliseconds to about two seconds, so that the firmware keeps handling
 * serial messages between calls; the whole probe takes about twenty-five
 * seconds. Solenoids are energised in short bursts and left off at the end.
 */
void pcfProbeStep();

#endif // PCFPROBE_H_
