#!/bin/sh
# Print what this Mac's USB-C port controllers report for each port they power:
# port index, measured current (mA), bus voltage (mV), power (mW).
# Apple-silicon MacBooks expose this under AppleSmartBattery / PowerOutDetails.
#
# usage: usbpower.sh        (no arguments, no environment variables)
#
# Needs macOS (ioreg). It only reads; it does not switch anything on or off.
# Prints one line per port, for example:
#   port 1: 120 mA at 5000 mV = 600 mW (limit 3000 mA)
# where "limit" is the value reported as ConfiguredCurrent. Prints nothing when the
# machine reports no PowerOutDetails.

# ioreg prints the AppleSmartBattery entry (-w0: lines not cut to the terminal width).
# The "PowerOutDetails" line holds one {...} group per port; tr puts each group on a line
# of its own, and only the lines that have a PortIndex are kept. The loop reads them one
# at a time into l.
ioreg -rn AppleSmartBattery -w0 | grep '"PowerOutDetails"' | tr '{' '\n' | grep PortIndex | while read -r l; do
  # f <key>: print the whole number that follows "<key>"= in the current line.
  f() { echo "$l" | sed -n "s/.*\"$1\"=\([0-9]*\).*/\1/p"; }
  # The units in the text (mA, mV, mW) are this script's labels for the raw numbers.
  echo "port $(f PortIndex): $(f Current) mA at $(f AdapterVoltage) mV = $(f Watts) mW (limit $(f ConfiguredCurrent) mA)"
done
