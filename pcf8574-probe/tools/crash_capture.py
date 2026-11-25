"""Stream the scope into a ring buffer while the test runs; freeze it when the UNO reports a
restart.

usage: crash_capture.py <folder containing scope.py> <outdir> <gain ch1> <gain ch2>
                        <rate MS/s> <tag> [max wait in seconds, default 90]

  gain ch1, gain ch2  scope input ranges: 1V, 500mV, 250mV or 100mV
  rate MS/s           scope sample rate: 48, 30, 24, 16, 8, 4 or 1
  tag                 name used in the output file names

The serial port is fixed in the script (/dev/cu.usbmodemFX2348N1, 115200 baud).

Firmware needed on the board: one that prints a banner containing "read-back test" when
it starts; the mcp-readback sketch (../mcp-readback/src/main.cpp) does. The first banner
is the normal start after the port is opened. A second banner means the controller has
restarted during the test, and that stops the capture.

Meanwhile the scope samples continuously and only the last 48 chunks of 1 MB are kept.
Prints the last 14 serial lines with their times. If a restart was seen, also writes
  <outdir>/crash_<tag>.npy    the raw bytes kept (channels 1 and 2 interleaved)
  <outdir>/crash_<tag>_t.npy  the time each chunk finished arriving, followed by the time
                              of the restart banner, in seconds since the script started"""

import sys, time, threading, collections, numpy as np, serial

# The scope driver (scope.py) is imported from the folder given as first argument.
sys.path.insert(0, sys.argv[1])
from scope import Scope

outdir, g1, g2, rate, tag = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6]
maxwait = float(sys.argv[7]) if len(sys.argv) > 7 else 90
# Scope: 'rate' MS/s, ranges g1 and g2, 2 channels.
sc = Scope()
sc.setup(rate, g1, g2, 2)
# Only the newest 48 chunks are kept. With two interleaved channels a 1 MB chunk holds
# 524288 samples per channel, so the ring covers about 25 million samples per channel.
ring = collections.deque(maxlen=48)  # 48 x 1 MB
p = serial.Serial("/dev/cu.usbmodemFX2348N1", 115200, timeout=0.02)
# t0: time origin for all time stamps. crash_t: time of the restart banner, in seconds
# since t0, or None. lines: the serial lines received, each with its time.
t0 = time.time()
crash_t = None
lines = []


def reader():
    """Serial reader thread: record the lines and spot the restart banner.

    Takes no argument and returns nothing. Every non-empty line is stored in 'lines',
    cut to 120 characters. The first line containing "read-back test" is the normal start
    banner; a later one sets the global crash_t (seconds since t0). The loop ends then,
    or after 'maxwait' seconds; lines arriving in the following 0.4 s are still stored."""
    global crash_t
    buf = b""
    first = True
    while time.time() - t0 < maxwait and crash_t is None:
        buf += p.read(4096)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            s = line.decode("ascii", "replace").rstrip()
            now = time.time() - t0
            if s:
                lines.append("%7.3f  %s" % (now, s[:120]))
            if "read-back test" in s:
                if first:
                    first = False
                else:
                    crash_t = now
    # collect the follow-up lines
    end = time.time() + 0.4
    while time.time() < end:
        buf += p.read(4096)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            s = line.decode("ascii", "replace").rstrip()
            if s:
                lines.append("%7.3f  %s" % (time.time() - t0, s[:120]))


# Main thread: start sampling (register 0xE3 = 1), discard the first 64 KB of start-up
# junk, then read 1 MB chunks from USB endpoint 0x86 (2 s timeout) into the ring until
# the reader thread has seen a restart or has given up. Each chunk is stored with the
# time at which it finished arriving.
th = threading.Thread(target=reader)
th.start()
sc.reg(0xE3, 1)
sc.d.read(0x86, 1 << 16, 1000)
while th.is_alive() and crash_t is None:
    a = np.frombuffer(sc.d.read(0x86, 1 << 20, 2000), dtype=np.uint8)
    ring.append((time.time() - t0, a))
sc.reg(0xE3, 0)
th.join()
# Report, and save the ring only if a restart was seen.
print("\n".join(lines[-14:]))
if crash_t is None:
    print("no restart seen in %.0f s" % maxwait)
else:
    np.save("%s/crash_%s.npy" % (outdir, tag), np.concatenate([a for _, a in ring]))
    np.save("%s/crash_%s_t.npy" % (outdir, tag), np.array([t for t, _ in ring] + [crash_t]))
    print(
        "restart banner at %.3f s; ring holds %d chunks ending at %.3f s"
        % (crash_t, len(ring), ring[-1][0])
    )
