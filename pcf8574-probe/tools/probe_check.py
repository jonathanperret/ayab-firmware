"""Measure both scope channels in each of the four states of the statecycle sketch.

usage: probe_check.py <folder containing scope.py> <serial port>

Firmware needed on the board: statecycle (../statecycle/src/main.cpp). It holds four
static states for 700 ms each and prints "STATE n" as it enters each one:
  0 and 2: both expanders 00;  1: expander 0x21 = FF;  3: expander 0x20 = FF.

Scope: 16 MS/s, channel 1 on the 100 mV range (read here at x1, reported in mV), channel 2
on the 1 V range (reported in V for a x10 probe). What each probe is connected to is not
recorded in this script.

For 36 seconds, each "STATE n" line triggers one capture of 4 MB (125 ms) taken 0.15 s
after the line. At the end one line is printed per state: number of captures, channel 1
mean relative to the mean of the two all-low states, its spread between captures
(standard deviation), the lowest and highest single sample, and the channel 2 mean."""

import sys, time, numpy as np, serial

# The scope driver (scope.py) is imported from the folder given as first argument.
sys.path.insert(0, sys.argv[1])
from scope import Scope

port = sys.argv[2]
sc = Scope()
# 16 MS/s, channel 1 on the 100 mV range, channel 2 on the 1 V range, 2 channels.
sc.setup(16, "100mV", "1V", 2)
p = serial.Serial(port, 115200, timeout=0.05)
# res[state] = list of (CH1 mean, CH1 min, CH1 max, CH2 mean), in raw counts, per capture.
res = {0: [], 1: [], 2: [], 3: []}
buf = b""
# Run for 36 s, which is about 12 rounds of the four 700 ms states.
t_end = time.time() + 36
while time.time() < t_end:
    buf += p.read(256)
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        s = line.decode("ascii", "replace").strip()
        if s.startswith("STATE "):
            st = int(s.split()[1])
            # Let the outputs settle, then capture 4 MB = 2 million samples per channel.
            # sc.capture returns a list of chunks; even bytes are CH1, odd bytes CH2.
            time.sleep(0.15)
            a = np.concatenate(sc.capture(4 << 20))
            c1 = a[0::2].astype(float)
            c2 = a[1::2].astype(float)
            res[st].append((c1.mean(), c1.min(), c1.max(), c2.mean()))
            # Drop whatever arrived during the capture so that the next capture starts
            # from a fresh STATE line.
            p.reset_input_buffer()
            buf = b""
# Description of each state; "middle" and "right" are the positions of the chips on the
# board.
names = {
    0: "both chips all low        ",
    1: "chip 0x21 all high (middle)",
    2: "both chips all low        ",
    3: "chip 0x20 all high (right) ",
}
# Reference level for channel 1: mean over all captures taken in the two all-low states.
base = np.mean([r[0] for r in res[0] + res[2]])
for st in (0, 1, 2, 3):
    r = np.array(res[st])
    if len(r) == 0:
        print(st, "no captures")
        continue
    # Conversions: channel 1, 500 mV per 128 counts (100 mV range, x1). Channel 2,
    # 50 V per 128 counts (1 V range, x10 probe), with its zero level taken as 131 counts;
    # where that zero value comes from is not evident from this script.
    print(
        "state %d %s: n=%d  CH1 mean %+7.2f mV vs all-low (spread %.2f), raw min..max %+.0f..%+.0f mV | CH2 mean %.2f V at x10"
        % (
            st,
            names[st],
            len(r),
            (r[:, 0].mean() - base) * 500 / 128,
            r[:, 0].std() * 500 / 128,
            (r[:, 1].min() - base) * 500 / 128,
            (r[:, 2].max() - base) * 500 / 128,
            (r[:, 3].mean() - 131) * 50.0 / 128,
        )
    )
