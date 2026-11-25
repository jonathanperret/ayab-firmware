#!/bin/sh
# usage: variants.sh <seconds> <variant flags>...   (each arg is a comma-separated list of -D names)
#
# Builds the mcp-readback sketch once per variant, uploads it, listens to the board for
# <seconds> and prints one summary line per variant.
#
#   <seconds>        how long to listen after each upload
#   <variant flags>  names of build-time switches without the -D, joined by commas; for
#                    example "CLKDIV,PEPU" builds with -DOLD -DNOREAD -DCLKDIV -DPEPU.
#                    -DOLD and -DNOREAD are always added. An empty argument ("") builds
#                    with those two only. What a switch does is defined in the sketch.
#
# Environment: PORT, the board's serial device (a fixed default is used when it is not set).
# readserial_ts.py also reads BAUD (default 115200).
# Needs: PlatformIO (pio) on the PATH; ../mcp-readback; ../.venv with pyserial.
# Unlike battery.sh, this builds in ../mcp-readback itself, not in a private copy.
#
# Each summary line gives: the time of day, the variant, the number of start banners seen
# and so of restarts, the number of phase lines, when each banner was seen (seconds since
# listening started) and the start of the last TOTAL or DONE line.
#
# Paths are relative to this script: P is the probe folder that holds the sketches, tools and .venv.
P="$(cd "$(dirname "$0")/.." && pwd)"

# Take <seconds>; what is left in "$@" is the list of variants.
secs=$1; shift
cd "$P/mcp-readback"
for v in "$@"; do
  # Turn "A,B" into "-DA -DB ": one name per line, -D in front of each, back to one line.
  flags="-DOLD -DNOREAD $(echo "$v" | tr ',' '\n' | sed 's/^/-D/' | tr '\n' ' ')"
  # Build and upload. Only lines that report an error or a failure are shown.
  PLATFORMIO_BUILD_FLAGS="$flags" pio run -t upload --upload-port ${PORT:-/dev/cu.usbmodemFX2348N1} 2>&1 | grep -E ' error|FAILED' 
  # Listen for $secs seconds. Each line comes back preceded by the time since listening
  # started; listening stops early at a line containing DONE.
  out=$("$P/.venv/bin/python" -I "$P/tools/readserial_ts.py" ${PORT:-/dev/cu.usbmodemFX2348N1} $secs 2>&1)
  # n: number of start banners ("read-back test"); one is printed each time the sketch
  # starts, so n-1 is the number of restarts (-1 if no banner was seen at all).
  n=$(echo "$out" | grep -c 'read-back test')
  # times: the time (first field of the line) of each banner.
  times=$(echo "$out" | grep 'read-back test' | awk '{printf "%s ", $1}')
  # last: first 60 characters of the last line containing TOTAL or DONE.
  last=$(echo "$out" | grep -E 'TOTAL|DONE' | tail -1 | cut -c1-60)
  # ph: number of lines naming a test phase, a measure of how far the sketch got.
  # Only this grep has -a (treat output as text even if it contains non-text bytes).
  ph=$(echo "$out" | grep -a -c -E 'walking single|cumulative|bank patterns|toggle 0|random single|random words')
  echo "$(date +%H:%M) variant [$v]: banners=$n (restarts=$((n-1))) phase-lines=$ph at: $times | $last"
done
