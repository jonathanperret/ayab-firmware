"""Take scope captures at planned times while logging what the board prints on its serial port.
usage: run_capture.py <folder holding scope.py> <out dir> <range1> <range2> <rate MS/s>
                      <seconds>:<name> [<seconds>:<name> ...]
  range1/2   scope ranges for CH1 / CH2: 100mV, 250mV, 500mV or 1V
  rate       sample rate in million samples per second (see scope.py)
  seconds    when to start a capture, in seconds after the script started (may be fractional)
  name       the capture is saved as <out dir>/cap_<name>.npy

Needs: the scope plugged into this computer (scope.py's Scope class is used directly, not
scope_daemon.py), and the board on the serial port hard-coded below, at 115200 baud.
The script sends nothing to the board; it only listens.
Writes: one 16 MiB two-channel capture per plan entry (interleaved CH1, CH2 bytes).
Prints: every line received from the board and one line per capture, each prefixed with the time
in seconds since the start, so that captures can be placed against the board's messages.
"""

import sys, time, threading, numpy as np, serial

# The first argument is the folder to import scope.py from.
sys.path.insert(0, sys.argv[1])
from scope import Scope

# g1, g2 = range names for CH1 and CH2. plan = list of (start time in s, capture name), in the
# order given; the times are expected to increase.
outdir, g1, g2, rate = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
plan = [(float(t), name) for t, name in (x.split(":") for x in sys.argv[6:])]
sc = Scope()
sc.setup(rate, g1, g2, 2)
# p = the board's serial port. The 50 ms read timeout lets the reader thread notice "stop".
p = serial.Serial("/dev/cu.usbmodemFX2348N1", 115200, timeout=0.05)
# t0 = time origin for every printed timestamp. stop = flag that ends the reader thread.
t0 = time.time()
stop = False


def reader():
    """Thread body: print each line the board sends, with its time since t0, until stop is set.

    Lines containing "reset cause" are not shown. Each shown line is cut at ", UNO" if that
    text is present, and limited to 100 characters.
    """
    buf = b""
    while not stop:
        buf += p.read(4096)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            s = line.decode("ascii", "replace").rstrip()
            if s and "reset cause" not in s:
                print("%7.2f  %s" % (time.time() - t0, s.split(", UNO")[0][:100]), flush=True)


# Start listening, then work through the plan.
th = threading.Thread(target=reader)
th.start()
for t, name in plan:
    # Wait for this capture's start time, checking every 5 ms.
    while time.time() - t0 < t:
        time.sleep(0.005)
    # ts = when the capture actually started. 16 << 20 bytes = 16 MiB = 8 MiB of samples per
    # channel (about half a second at 16 MS/s).
    ts = time.time() - t0
    ch = sc.capture(16 << 20)
    np.save("%s/cap_%s.npy" % (outdir, name), np.concatenate(ch))
    print('%7.2f  [scope] captured "%s" until %.2f' % (ts, name, time.time() - t0), flush=True)
# Keep listening for one more second, then stop the reader thread and wait for it.
time.sleep(1.0)
stop = True
th.join()
