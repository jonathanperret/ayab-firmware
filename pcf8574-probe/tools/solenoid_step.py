"""One controlled solenoid on/off with the scope running.
usage: solenoid_step.py <scratch dir> <serial port> <volts> <amps limit> <tag> [state-hex-on] [style n|m]
Leaves the bench supply output OFF at the end.

  scratch dir  working folder: scope_zero.json is read from <scratch>/out and results go there;
               <scratch>/scripts is added to the import path after this tools folder
  serial port  port of the board running the test firmware (115200 baud)
  volts, amps limit  voltage and current limit set on the bench supply for the solenoids
  tag          text used in the output file names and the title
  state-hex-on state to switch on, as the board expects it (default 8000; the picture's title
               always says "output 15")
  style        command letter used for the writes: n (default, "native") or m ("MCP-style")

Sequence: supply on; start capturing; send "<style> <state>"; 0.6 s later send "<style> 0000";
0.4 s later stop capturing; supply off. The supply's voltage and current are read at each stage.
Needs: the scope plugged into this computer (scope.py's Scope class), the DP100 bench supply
(dp100.py), matplotlib. Both scope channels are on the 100mV range at 8 MS/s. CH1 = the solenoid
output through a x10 probe (volts), CH2 = ground at the driver chip through a x1 probe
(millivolts).
Writes, in <scratch>/out: sol_<tag>.npy (the whole capture, interleaved CH1, CH2 bytes) and, if a
switching edge was found, sol_<tag>.png (2 rows x 3 columns: solenoid output above, ground
below; whole capture, 600 us around switch-on, 600 us around switch-off).
Prints: the board's replies, the supply readings, the solenoid output levels, and the ground's
steady shift and extremes near each edge, in millivolts relative to its level before switch-on.
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
on_state = sys.argv[6] if len(sys.argv) > 6 else "8000"
style = sys.argv[7] if len(sys.argv) > 7 else "n"
import os

HERE = os.path.dirname(os.path.abspath(__file__))  # this tools folder, wherever the project lives
# Modules are looked for in this tools folder first, then in <scratch>/scripts.
sys.path.insert(0, S + "/scripts")
sys.path.insert(0, HERE)
from scope import Scope
from dp100 import DP100
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Z = zero level in ADC counts for each range and channel, from the scratch folder's own table.
# RATE = samples per second. psu = the bench supply. sc = the scope: 8 MS/s, both channels on
# the 100mV range. p = the board's serial port.
Z = json.load(open(S + "/out/scope_zero.json"))
RATE = 8e6
psu = DP100()
sc = Scope()
sc.setup(8, "100mV", "100mV", 2)
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


def cmd(c):
    """Send the command line c to the board and return its reply.

    Input received earlier is discarded first; the reply is whatever arrives up to the first
    line end, waiting at most 3 s. The exchange is printed.
    """
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    r = wait(b"\n", 3)
    print("   %s -> %s" % (c, r))
    return r


# Wait up to 4 s for the board to announce itself; show the last 16 characters received.
print("board:", wait(b"READY")[-16:])
# The run itself. Whatever happens, the supply is switched off afterwards (finally, below).
try:
    # Supply on, settle, and read it with all outputs off (i0).
    psu.apply(on=True, vset=volts, iset=amps)
    time.sleep(0.8)
    i0 = psu.info()
    print("supply on: %.3f V, %.3f A (all outputs off)" % (i0["vout"], i0["iout"]))
    # chunks = the USB reads collected by the capture thread. run = flag that keeps it going.
    chunks = []
    run = True

    def grab():
        """Thread body: capture continuously into chunks until run is cleared.

        This does by hand what Scope.capture() does, without a size limit: start sampling
        (register 0xE3 = 1), throw away the first read, append 1 MiB reads, stop sampling.
        """
        sc.reg(0xE3, 1)
        sc.d.read(0x86, 1 << 16, 1000)
        while run:
            chunks.append(np.frombuffer(sc.d.read(0x86, 1 << 20, 2000), dtype=np.uint8))
        sc.reg(0xE3, 0)

    # Start capturing, wait 0.4 s, switch the solenoid on, wait 0.6 s and read the supply (i1),
    # switch everything off, wait 0.4 s, stop capturing and read the supply again (i2).
    th = threading.Thread(target=grab)
    th.start()
    time.sleep(0.4)
    cmd("%s %s" % (style, on_state))
    time.sleep(0.6)
    i1 = psu.info()
    print("solenoid on: supply reads %.3f V, %.3f A" % (i1["vout"], i1["iout"]))
    cmd("%s 0000" % style)
    time.sleep(0.4)
    run = False
    th.join()
    i2 = psu.info()
    print("solenoid off: supply reads %.3f V, %.3f A" % (i2["vout"], i2["iout"]))
finally:
    psu.apply(on=False)
    time.sleep(0.3)
    print("supply output switched off")
# Analysis. a = the raw capture, saved as it is. The reads are joined end to end; any samples
# lost between reads are not accounted for in the times below.
a = np.concatenate(chunks)
np.save("%s/out/sol_%s.npy" % (S, tag), a)
sol = (a[0::2].astype(float) - Z["100mV"]["ch1_zero"]) * 5.0 / 128  # V, x10
gnd = (a[1::2].astype(float) - Z["100mV"]["ch2_zero"]) * 500.0 / 128  # mV, x1
# n = samples per channel. hi = solenoid output above the midpoint between its 2nd and 98th
# percentiles. e = every sample where hi changes; the first is taken as the switch-on (on_i)
# and the last as the switch-off (off_i).
n = len(sol)
hi = sol > (np.percentile(sol, 2) + np.percentile(sol, 98)) / 2
e = np.flatnonzero(hi[1:] != hi[:-1])
on_i = e[0] if len(e) else None
off_i = e[-1] if len(e) else None
# Levels of the solenoid output: median of the first 0.2 s, median while on (from 0.1 s after
# switch-on to 0.05 s before switch-off), and the highest sample.
print(
    "solenoid-output channel: %.2f V before, %.2f V while on, peak %.2f V"
    % (
        np.median(sol[: int(0.2 * RATE)]),
        (
            np.median(sol[on_i + int(0.1 * RATE) : off_i - int(0.05 * RATE)])
            if on_i is not None and off_i > on_i
            else float("nan")
        ),
        sol.max(),
    )
)
# g0 = ground at rest in mV: median of the first 0.2 s of the capture.
g0 = np.median(gnd[: int(0.2 * RATE)])


def around(i, us):
    """Ground relative to rest around a sample.

    i: centre sample; us: half-width in microseconds.
    Returns the slice of gnd from us before i to us after i, minus g0, in millivolts.
    """
    w = int(us * 1e-6 * RATE)
    return gnd[max(0, i - w) : i + w] - g0


if on_i is not None:
    # Ground shift while the solenoid is on (same stretch as above), then its extremes within
    # 500 us of each edge.
    print(
        "ground, relative to its resting level (mV): steady shift while on %+.1f"
        % (np.median(gnd[on_i + int(0.1 * RATE) : off_i - int(0.05 * RATE)]) - g0)
    )
    for name, i in (("switch-on", on_i), ("switch-off", off_i)):
        r = around(i, 500)
        print("   within 0.5 ms of %s: min %+.0f, max %+.0f" % (name, r.min(), r.max()))
    # Picture: for each view (title, centre sample, half-width in microseconds), the solenoid
    # output on the top row and the ground relative to rest on the bottom row. The first view's
    # half-width is half the capture, so it shows everything.
    fig, ax = plt.subplots(2, 3, figsize=(15, 6.5))
    for c, (name, i, us) in enumerate(
        (
            ("whole capture", n // 2, n / RATE * 5e5),
            ("switch-on", on_i, 300),
            ("switch-off", off_i, 300),
        )
    ):
        # w = half-width in samples. lo, hi_ = sample range, clipped to the capture. step thins the
        # trace to about 20000 points. Time axis: ms for the whole capture, microseconds otherwise.
        w = int(us * 1e-6 * RATE)
        lo, hi_ = max(0, i - w), min(n, i + w)
        step = max(1, (hi_ - lo) // 20000)
        t = (np.arange(lo, hi_, step) - i) / RATE * (1e3 if c == 0 else 1e6)
        ax[0, c].plot(t, sol[lo:hi_:step], "C0", lw=0.7)
        ax[0, c].set_title(name)
        ax[0, c].grid(alpha=0.3)
        ax[1, c].plot(t, gnd[lo:hi_:step] - g0, "C1", lw=0.7)
        ax[1, c].grid(alpha=0.3)
        ax[1, c].set_xlabel("ms" if c == 0 else "µs from the edge")
    ax[0, 0].set_ylabel("solenoid output, S-3 pin 1 (V)")
    ax[1, 0].set_ylabel("ground at U5 pin 9 (mV, vs rest)")
    fig.suptitle(
        "%s: solenoid on output 15, supply %.1f V, %s write"
        % (tag, volts, "MCP-style" if style == "m" else "native")
    )
    fig.tight_layout()
    fig.savefig("%s/out/sol_%s.png" % (S, tag), dpi=75)
else:
    print("no switching edge found on the solenoid-output channel")
