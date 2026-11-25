"""Run a burst of MCP-style (or native) writes with the solenoid supply on and the scope capturing.
usage: burst_scope.py <scratch> <port> <volts> <amps> <tag> <N> <stateA> <stateB> <delay ms> [hold-state]
Saves a picture: overview, one write in detail, and the worst ground excursion.

  scratch  working folder: scope_zero.json is read from <scratch>/out and results go there;
           <scratch>/scripts is added to the import path after this tools folder
  port     serial port of the board running the test firmware (115200 baud)
  volts, amps  voltage and current limit set on the bench supply for the solenoids
  tag      text used in the output file names and titles
  N, stateA, stateB, delay ms  the burst: N writes alternating between the two states, that
           many milliseconds apart. They are passed to the board as given ("b N A B D").
  hold-state  listed in the usage line but never read by the code; stateA is what is held
           before the burst.
Environment: NOPSU=1 leaves the supply alone (it must then be set by hand; <volts> is still
used in the title); CH1RANGE = scope range of CH1 (default 100mV; CH2 is always 100mV);
WATCH = first argument given to "psu watch" (default 14), taken to be how many seconds the
supply is logged.

Needs: the scope plugged into this computer (scope.py's Scope class), the DP100 bench supply
(dp100.py) unless NOPSU=1, the "psu" script next to this file (it reads the supply through the
Pi over ssh), matplotlib. CH1 = a solenoid output through a x10 probe, CH2 = ground at the
driver chip through a x1 probe, read in millivolts.
Writes, in <scratch>/out: burst_<tag>.png (2 rows x 3 columns: solenoid output above, ground
below; 30 ms overview, 500 us around one write, 40 us around the worst ground excursion),
burst_<tag>.npy (the first 4,000,000 bytes of the capture, 0.125 s) and, if the supply was
logged, burst_<tag>_supply.png (supply voltage and current against time).
Prints: the board's replies, levels on both channels, counts of ground samples beyond 60, 100
and 200 mV, and a summary of the supply current when idle, with the coil held, and in the burst.
The supply output is switched off at the end unless NOPSU=1.
"""

import sys, json, time, threading, numpy as np, serial

# Arguments. S = scratch folder, port = serial port, volts / amps = supply setting, tag = label.
S, port, volts, amps, tag = (
    sys.argv[1],
    sys.argv[2],
    float(sys.argv[3]),
    float(sys.argv[4]),
    sys.argv[5],
)
# N = number of writes, A and B = the two states (kept as text), D = milliseconds between writes.
N, A, B, D = int(sys.argv[6]), sys.argv[7], sys.argv[8], int(sys.argv[9])
import os

HERE = os.path.dirname(os.path.abspath(__file__))  # this tools folder, wherever the project lives
# Modules are looked for in this tools folder first, then in <scratch>/scripts.
sys.path.insert(0, S + "/scripts")
sys.path.insert(0, HERE)
from scope import Scope
import os

NOPSU = os.environ.get("NOPSU") == "1"  # supply's data cable unplugged: do not touch the supply
if not NOPSU:
    from dp100 import DP100
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Z = zero level in ADC counts for each range and channel, from the scratch folder's own table.
# RATE = samples per second. psu = the bench supply, or None when it is not to be touched.
Z = json.load(open(S + "/out/scope_zero.json"))
RATE = 16e6
psu = None if NOPSU else DP100()
# sc = the scope: 16 MS/s, CH1 on range R1, CH2 on 100mV, two channels.
sc = Scope()
R1 = os.environ.get("CH1RANGE", "100mV")
sc.setup(16, R1, "100mV", 2)
FS1 = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}[
    R1
]  # volts at a x10 tip for 128 counts
# p = the board's serial port.
p = serial.Serial(port, 115200, timeout=0.2)


def wait(tok, t=4):
    """Read from the board until the bytes tok have been seen or t seconds have passed.

    Returns everything received, as stripped text.
    """
    end = time.time() + t
    buf = b""
    while time.time() < end and tok not in buf:
        buf += p.read(64)
    return buf.decode("ascii", "replace").strip()


# Wait up to 4 s for the board to announce itself; show the last 16 characters received.
print("board:", wait(b"READY")[-16:])
# Track the bench supply's reported voltage and current for the whole run, through the Pi.
import subprocess

# psu_log = list of (seconds since t_start, volts, amperes). watch = the "psu watch" process;
# its two arguments are WATCH (default 14) and 0.1.
psu_log = []
t_start = time.time()
watch = subprocess.Popen(
    [os.path.join(HERE, "psu"), "watch", str(float(os.environ.get("WATCH", "14"))), "0.1"],
    stdout=subprocess.PIPE,
    text=True,
)


def _w():
    """Thread body: turn each three-field line from "psu watch" into a psu_log entry.

    The second field is taken as volts and the third as amperes; the first is not used.
    """
    for line in watch.stdout:
        f = line.split()
        if len(f) == 3:
            psu_log.append((time.time() - t_start, float(f[1]), float(f[2])))


threading.Thread(target=_w, daemon=True).start()
# events = (seconds since t_start, text) markers for the supply plot.
events = []
time.sleep(1.5)
# The run itself. Whatever happens, the supply is switched off afterwards (finally, below).
try:
    # Switch the supply on at the requested voltage and current limit and let it settle.
    if psu:
        psu.apply(on=True, vset=volts, iset=amps)
        time.sleep(0.8)
    # Hold state A with an "m" command for 1.5 s and read the supply.
    events.append((time.time() - t_start, "hold " + A))
    p.reset_input_buffer()
    p.write(("m %s\n" % A).encode())
    print(wait(b"\n", 3))
    time.sleep(1.5)
    if psu:
        print(
            "supply with state %s held: %.3f V, %.3f A"
            % (A, psu.info()["vout"], psu.info()["iout"])
        )
    # Start the burst with a "b" command, wait 0.3 s, then capture while it runs.
    events.append((time.time() - t_start, "burst starts"))
    p.reset_input_buffer()
    p.write(("b %d %s %s %d\n" % (N, A, B, D)).encode())
    time.sleep(0.3)
    chunks = sc.capture(24 << 20)  # 0.75 s at 16 MS/s
    # Wait up to 90 s for the board's line reporting the end of the burst.
    res = wait(b"\n", 90)
    print(res)
    events.append((time.time() - t_start, "burst ends, all off"))
    time.sleep(1.5)
finally:
    if psu:
        psu.apply(on=False)
        time.sleep(0.3)
        print("supply output off")
    else:
        print("supply left as it is (not under computer control)")
# Analysis. a = the raw capture. sol = CH1 in volts at the tip of a x10 probe. gnd = CH2 in
# millivolts: 500 mV for 128 counts, which is the 100mV range read through a x1 probe.
# n = samples per channel. g0 = median of the ground trace, used as its resting level.
a = np.concatenate(chunks)
sol = (a[0::2].astype(float) - Z[R1]["ch1_zero"]) * FS1 / 128
gnd = (a[1::2].astype(float) - Z["100mV"]["ch2_zero"]) * 500.0 / 128
n = len(sol)
g0 = np.median(gnd)
# hi = solenoid output above the midpoint between its 1st and 99th percentiles.
# rise = samples where it goes from low to high; the printout calls these dropouts.
hi = sol > (np.percentile(sol, 1) + np.percentile(sol, 99)) / 2
rise = np.flatnonzero(hi[1:] & ~hi[:-1])
print(
    "captured %.2f s; solenoid-output levels: low %.2f V, high (dropout/kick) up to %.2f V; %d dropouts seen"
    % (n / RATE, np.percentile(sol, 5), sol.max(), len(rise))
)
# dev = ground relative to its median, in mV. wi = the sample where it is furthest away.
dev = gnd - g0
wi = int(np.argmax(np.abs(dev)))
print(
    "ground vs its median: min %+.0f mV, max %+.0f mV; samples beyond +/-60 mV: %d, beyond +/-100 mV: %d, beyond +/-200 mV: %d"
    % (
        dev.min(),
        dev.max(),
        (np.abs(dev) > 60).sum(),
        (np.abs(dev) > 100).sum(),
        (np.abs(dev) > 200).sum(),
    )
)
# Picture: for each view (title, centre sample, half-width in microseconds), the solenoid
# output on the top row and the ground deviation on the bottom row.
fig, ax = plt.subplots(2, 3, figsize=(15, 6.5))
views = (
    ("30 ms overview", n // 2, 15000),
    ("one write in detail", int(rise[len(rise) // 2]) if len(rise) else n // 2, 250),
    ("worst ground excursion (%+.0f mV)" % dev[wi], wi, 20),
)
for c, (name, i, us) in enumerate(views):
    # w = half-width in samples. lo, hi_ = sample range, clipped to the capture. step thins the
    # trace to about 30000 points. The time axis is in ms for the overview and in microseconds
    # for the other two; the 20 us view marks every sample.
    w = int(us * 1e-6 * RATE)
    lo, hi_ = max(0, i - w), min(n, i + w)
    step = max(1, (hi_ - lo) // 30000)
    t = (np.arange(lo, hi_, step) - i) / RATE * (1e3 if us > 5000 else 1e6)
    ax[0, c].plot(t, sol[lo:hi_:step], "C0", lw=0.7, marker="." if us <= 20 else None, ms=3)
    ax[0, c].set_title(name)
    ax[0, c].grid(alpha=0.3)
    ax[1, c].plot(t, dev[lo:hi_:step], "C1", lw=0.7, marker="." if us <= 20 else None, ms=3)
    ax[1, c].grid(alpha=0.3)
    ax[1, c].set_xlabel("ms" if us > 5000 else "µs")
ax[0, 0].set_ylabel("solenoid output, S-3 pin 1 (V)")
ax[1, 0].set_ylabel("ground at U5 pin 9 (mV, vs median)")
fig.suptitle(
    "%s: burst of %d writes alternating %s / %s, %d ms apart, supply %.1f V"
    % (tag, N, A, B, D, volts)
)
fig.tight_layout()
fig.savefig("%s/out/burst_%s.png" % (S, tag), dpi=75)
# Keep the first 4e6 bytes of the raw capture (2e6 samples per channel, 0.125 s).
np.save("%s/out/burst_%s.npy" % (S, tag), a[: int(4e6)])

# Supply log: wait for "psu watch" to finish (30 s at most), then plot current (left axis, mA)
# and voltage (right axis, V) against time, with a dotted line at each event.
watch.wait(timeout=30)
if psu_log:
    L = np.array(psu_log)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax2 = ax.twinx()
    ax.plot(L[:, 0], L[:, 2] * 1000, "C3.-", ms=3, lw=0.8, label="current (mA)")
    ax2.plot(L[:, 0], L[:, 1], "C2", lw=0.8, label="voltage (V)")
    for t, name in events:
        ax.axvline(t, color="gray", ls=":")
        ax.text(t, ax.get_ylim()[1] * 0.02, " " + name, rotation=90, fontsize=7, va="bottom")
    ax.set_xlabel("s")
    ax.set_ylabel("supply current (mA)")
    ax2.set_ylabel("supply voltage (V)")
    ax2.set_ylim(0, max(4.0, L[:, 1].max() * 1.15))
    ax.grid(alpha=0.3)
    ax.set_title(
        "%s: bench supply as reported through the Pi (one reading every 0.1 s or so)" % tag
    )
    fig.tight_layout()
    fig.savefig("%s/out/burst_%s_supply.png" % (S, tag), dpi=75)
    # held = readings from 0.5 s after "hold" until the burst starts. burst = readings from
    # 0.3 s after the burst starts until 0.1 s before it ends. Idle = readings before "hold".
    held = L[(L[:, 0] > events[0][0] + 0.5) & (L[:, 0] < events[1][0])]
    burst = L[(L[:, 0] > events[1][0] + 0.3) & (L[:, 0] < events[2][0] - 0.1)]
    print(
        "supply readings: %d; idle %.0f mA; coil held on %.0f mA; during the burst %.0f mA (min %.0f, max %.0f); voltage min %.3f max %.3f V"
        % (
            len(L),
            L[L[:, 0] < events[0][0]][:, 2].mean() * 1000,
            held[:, 2].mean() * 1000 if len(held) else float("nan"),
            burst[:, 2].mean() * 1000 if len(burst) else float("nan"),
            burst[:, 2].min() * 1000 if len(burst) else float("nan"),
            burst[:, 2].max() * 1000 if len(burst) else float("nan"),
            L[:, 1].min(),
            L[:, 1].max(),
        )
    )
