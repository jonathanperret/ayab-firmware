#!/bin/sh
# usage: battery.sh <serial port> <tag>
# Runs the tests that break UNO A on the board at <port>, using private
# copies of the projects so that two boards can be tested at once.
#
#   <serial port>  serial device of the board to flash and listen to
#   <tag>          a short name for the board; every line printed starts with [<tag>], so
#                  that the output of two runs going on at once can be told apart
#
# What it does, in order:
#   1. flashes the "ident" sketch and prints the IDENT line the board sends;
#   2. three times: flashes "mcp-readback" built with -DOLD -DNOREAD, listens for 48 s and
#      prints how many times the sketch restarted and how many progress lines it got out;
#   3. flashes "ramsoak" built with -DNOTWI, then again with no flag, listens for 45 s each
#      time and prints how many times it started, how many RAMERR lines it sent and its
#      last progress line.
# What the -D flags change is defined in the sketches' sources, not here.
#
# Needs: PlatformIO (pio) and rsync on the PATH; the sketches in ../ident, ../mcp-readback
# and ../ramsoak; ../.venv with what readserial_ts.py needs (pyserial).
# Environment: none read here. readserial_ts.py reads BAUD (default 115200).
# The copies are made in a new temporary folder, which is not removed afterwards.
#
# Paths are relative to this script: P is the probe folder that holds the sketches, tools and .venv.
P="$(cd "$(dirname "$0")/.." && pwd)"

# W: the private work folder for this run.
PORT=$1; TAG=$2; W="$(mktemp -d)/work_$TAG"
mkdir -p "$W"

# Copy the three projects without their build folders (.pio), so each run compiles its own.
# Note that mcp-readback is copied under the name mcp_readback.
rsync -a --exclude .pio "$P/ident/" "$W/ident/"
rsync -a --exclude .pio "$P/mcp-readback/" "$W/mcp_readback/"
rsync -a --exclude .pio "$P/ramsoak/" "$W/ramsoak/"

# rd <seconds>: listen to the board for that long and print what it sends, each line
# preceded by the time since the start in seconds (9 characters wide, text from column 10).
# readserial_ts.py stops early at a line containing DONE.
rd() { "$P/.venv/bin/python" -I "$P/tools/readserial_ts.py" "$PORT" "$1" 2>&1; }

# up <project> <build flags>: build the project in the work folder with those -D flags and
# upload it to the board. Only lines that report an error or a failure are shown.
up() { ( cd "$W/$1" && PLATFORMIO_BUILD_FLAGS="$2" pio run -t upload --upload-port "$PORT" 2>&1 | grep -E ' error|FAILED' ); }
echo "[$TAG] port $PORT"

# 1. Identification: 6 s of output; print the IDENT line without its time (columns 10-140).
up ident ""; echo "[$TAG] $(rd 6 | grep -a IDENT | cut -c10-140)"

# 2. The program that crashes, three times over.
for i in 1 2 3; do
  up mcp_readback "-DOLD -DNOREAD"
  # n: number of start banners ("read-back test"); the sketch prints one each time it starts,
  # so n-1 is the number of restarts (this gives -1 if no banner was seen at all).
  # grep -a treats the output as text even if it contains bytes that are not text.
  out=$(rd 48); n=$(echo "$out" | grep -a -c 'read-back test')
  # ph: number of lines naming a test phase, a measure of how far the sketch got.
  ph=$(echo "$out" | grep -a -c -E 'walking single|cumulative|bank patterns|toggle 0|random single|random words')
  # One summary line, ending with the first 20 characters of the last DONE line, if any.
  echo "[$TAG] $(date +%H:%M) crashing program run $i: restarts=$((n-1)) progress-lines=$ph $(echo "$out" | grep -a -E 'DONE' | tail -1 | cut -c1-20)"
done

# 3. The RAM soak test, first with -DNOTWI, then with no extra flag.
for v in "-DNOTWI" ""; do
  up ramsoak "$v"
  out=$(rd 45)
  # starts: number of RAMSOAK lines; RAMERR: number of lines reporting a RAM error; then the
  # last "progress" line without its time (columns 10-70).
  echo "[$TAG] $(date +%H:%M) ramsoak [$v]: starts=$(echo "$out" | grep -a -c RAMSOAK) RAMERR=$(echo "$out" | grep -a -c RAMERR) | $(echo "$out" | grep -a progress | tail -1 | cut -c10-70)"
done
echo "[$TAG] finished"
