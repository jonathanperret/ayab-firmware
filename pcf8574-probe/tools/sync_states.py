"""Capture the scope continuously while reading the 'STATE n' lines of the
statecycle sketch, and report each channel's mean level per state.

usage: sync_states.py <scratch dir> <serial port> [seconds, default 9]

  scratch dir  folder that holds scripts/scope.py (the scope driver) and
               out/scope_zero.json (the zero level of each channel, per input range)
  serial port  port of the controller (115200 baud)
  seconds      how long to capture

Firmware needed on the board: statecycle (../statecycle/src/main.cpp). It holds four
static states for 700 ms each and prints "STATE n" as it enters each one:
  0 and 2: both expanders 00;  1: expander 0x21 = FF;  3: expander 0x20 = FF.

Scope: 8 MS/s, two channels, both on the 100 mV range. As the printed labels and the
scale factors below show, channel 1 is a solenoid output seen through a x10 probe and
channel 2 a ground difference seen at x1.

Prints the number of STATE lines received, then one line per state: number of scope
chunks used, mean solenoid-output voltage (V), mean ground voltage (mV) and the spread
(standard deviation) of the per-chunk ground means."""

import sys, json, time, threading, numpy as np, serial

# S = the scratch folder; the scope driver is imported from its scripts/ subfolder.
S = sys.argv[1]
sys.path.insert(0, S + "/scripts")
from scope import Scope

port = sys.argv[2]
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 9
# Z = zero levels in raw counts, looked up as Z[range]["ch1_zero"] and ["ch2_zero"].
Z = json.load(open(S + "/out/scope_zero.json"))
sc = Scope()
# 8 MS/s, channel 1 and channel 2 both on the 100 mV range, 2 channels.
sc.setup(8, "100mV", "100mV", 2)
p = serial.Serial(port, 115200, timeout=0.02)
# marks: (time.time() when the line was read, state number) for each "STATE n" line.
# stop: set to True to end the reader thread.
marks = []
stop = False


def rd():
    """Reader thread: collect the "STATE n" lines from the serial port into 'marks'.

    Takes no argument and returns nothing; runs until the global 'stop' becomes true.
    Each mark is stamped with the computer's time when the line was read, which is a
    little later than the moment the sketch changed state."""
    buf = b""
    while not stop:
        buf += p.read(256)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            s = line.decode("ascii", "replace").strip()
            if s.startswith("STATE "):
                marks.append((time.time(), int(s.split()[1])))


th = threading.Thread(target=rd)
th.start()
time.sleep(2.2)  # opening the port resets the board; let it start
# Capture loop. Register 0xE3 starts (1) and stops (0) the scope's sampling; data is read
# from USB endpoint 0x86. The first 64 KB are start-up junk and are thrown away. After
# that, 1 MB chunks are read (2 s timeout) and stored with the time at which each read
# returned. The two channels are interleaved, so 1 MB is 62.5 ms at 8 MS/s.
chunks = []
sc.reg(0xE3, 1)
sc.d.read(0x86, 1 << 16, 1000)
t_end = time.time() + secs
while time.time() < t_end:
    a = np.frombuffer(sc.d.read(0x86, 1 << 20, 2000), dtype=np.uint8)
    chunks.append((time.time(), a))
sc.reg(0xE3, 0)
stop = True
th.join()
# Assign each chunk to a state. res[state] = list of (solenoid volts, ground millivolts).
res = {0: [], 1: [], 2: [], 3: []}
for t, a in chunks:
    t_mid = t - 0.031  # middle of a 62.5 ms chunk
    # prev / nxt: the state marks before and after the middle of this chunk.
    prev = [m for m in marks if m[0] <= t_mid]
    nxt = [m for m in marks if m[0] > t_mid]
    if not prev or not nxt:
        continue
    if t_mid - prev[-1][0] < 0.12 or nxt[0][0] - t_mid < 0.12:
        continue  # keep clear of transitions
    # Even bytes are channel 1, odd bytes channel 2. Counts are converted with the zero
    # level of the 100 mV range: channel 1 at 5 V per 128 counts (x10 probe), channel 2
    # at 500 mV per 128 counts (x1).
    sol = (a[0::2].astype(float).mean() - Z["100mV"]["ch1_zero"]) * 5.0 / 128
    gnd = (a[1::2].astype(float).mean() - Z["100mV"]["ch2_zero"]) * 500.0 / 128
    # Filed under the state announced by the last mark before the chunk.
    res[prev[-1][1]].append((sol, gnd))
# Description of each state; "middle" and "right" are the positions of the chips on the
# board.
names = {
    0: "both chips all low",
    1: "middle chip (0x21) all high",
    2: "both chips all low",
    3: "right chip (0x20) all high",
}
print("state marks received: %d" % len(marks))
for st in (0, 1, 2, 3):
    r = np.array(res[st])
    if len(r) == 0:
        print("state", st, "no data")
        continue
    print(
        "state %d %-28s n=%2d  solenoid-output %.2f V (x10)   ground %+6.2f mV (spread %.2f)"
        % (st, names[st], len(r), r[:, 0].mean(), r[:, 1].mean(), r[:, 1].std())
    )
