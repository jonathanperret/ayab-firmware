"""Ground jump at the switching edges, located from the I2C clock on CH2.
usage: scope_bounce.py <out.png> <title> <range1> <range2> name=file.npy ...
CH1 = the node of interest, CH2 = SCL. For each capture: finds the trials (a write that starts 4-6.5 ms
after the previous bus activity), takes the 9th-clock rising edges that apply the 'off' byte and the
following byte(s), plus the last byte of the preceding write (switch-on from cold), and overlays CH1's raw
samples around each over all trials. Prints lowest/highest/peak-to-peak per edge (median and extreme).

  range1/2   scope ranges the captures were made with, for CH1 and CH2 (100mV 250mV 500mV 1V)
  name=file  one row of the picture per capture; name is the row label, file a capture of
             interleaved CH1, CH2 bytes at 16 MS/s (.npy or .npz, through capio.load)

Needs: scope_zero.json and capio.py next to this file, matplotlib. The clock must swing through
2.5 V at the probe tip to be detected.
Writes: <out.png>, four columns per capture (switch-on from cold, switch-off, back-on stage 1,
back-on stage 2), each showing CH1 minus its resting level from 2 us before to 8 us after the
clock edge, one dot per sample, all trials overlaid, on a shared voltage scale.
Prints: per capture, the number of trials found and CH1's resting level; per column, the lowest
and highest value and the peak-to-peak size, each as median over the trials and as extreme. These
are measured from 0.25 us before to 4 us after the clock edge.
"""

import sys, os, json, numpy as np
# Make capio.py, which sits next to this file, importable from wherever the script is run.
import os as _os, sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import capio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Arguments. caps = list of [row name, capture file].
outf, title, r1, r2 = sys.argv[1:5]
caps = [x.split("=", 1) for x in sys.argv[5:]]
# Z = zero level in ADC counts for each range and channel. FS = volts at the tip of a x10 probe
# for 128 ADC counts, for each range. U = samples per microsecond (16 MS/s).
Z = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_zero.json")))
FS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}
U = 16
# COLS = titles of the four columns, also used as keys for the edges collected below.
COLS = ["switch-on from cold", "switch-off", "back-on, stage 1", "back-on, stage 2"]
fig, ax = plt.subplots(len(caps), 4, figsize=(17, 2.6 * len(caps)), squeeze=False, sharey=True)
# PRE, POST = samples shown before and after each clock edge (2 us and 8 us).
PRE, POST = 2 * U, 8 * U
for row, (name, f) in enumerate(caps):
    # a = raw capture. v1, v2 = CH1 and CH2 in volts at the probe tip, cut to the same length n.
    a = capio.load(f)
    v1 = (a[0::2].astype(np.float32) - Z[r1]["ch1_zero"]) * FS[r1] / 128
    v2 = (a[1::2].astype(np.float32) - Z[r2]["ch2_zero"]) * FS[r2] / 128
    n = min(len(v1), len(v2))
    v1, v2 = v1[:n], v2[:n]
    # hi = clock high: CH2, averaged over 3 samples, above 2.5 V. rise = sample numbers of the
    # clock's rising edges. Fewer than 50 of them means there is no clock to work with.
    hi = np.convolve(v2, np.ones(3) / 3, "same") > 2.5
    rise = np.flatnonzero(~hi[:-1] & hi[1:]) + 1
    if len(rise) < 50:
        print(name, ": no clock found on CH2 (span %.2f..%.2f V)" % (v2.min(), v2.max()))
        continue
    # bursts = the rising edges grouped into bus transactions: a pause of more than 200 us
    # between two edges starts a new group.
    cut = np.flatnonzero(np.diff(rise) > 200 * U)
    bursts = np.split(rise, cut + 1)
    # ev = for each column, the sample numbers of the clock edges to show. sizes = number of
    # clock pulses in each accepted write.
    ev = {c: [] for c in COLS}
    sizes = []
    for k in range(1, len(bursts)):
        # b = this burst, p = the one before it. gap = idle time between them in milliseconds.
        # A trial is kept if that gap is between 4 and 6.5 ms, the burst has at least 27 clock
        # edges and the previous one at least 3, and both lie 400 us away from the capture's ends.
        b, p = bursts[k], bursts[k - 1]
        gap = (b[0] - p[-1]) / U / 1000.0
        if (
            not (4.0 < gap < 6.5)
            or len(b) < 27
            or len(p) < 3
            or b[-1] > n - 400 * U
            or p[0] < 400 * U
        ):
            continue
        sizes.append(len(b))
        # Which edge is which, counting rising edges from 0: 0 to 8 clock the address byte and
        # its acknowledge, 9 to 17 the first data byte, so b[17] is the 9th clock of the first
        # data byte, b[26] that of the second and b[35] that of the third, when there is one.
        # p[-2] is the last-but-one rising edge of the previous write. Why not the last one is not
        # stated; it fits the last rising edge being the stop condition rather than a clock pulse.
        ev[COLS[0]].append(p[-2])
        ev[COLS[1]].append(b[17])
        ev[COLS[2]].append(b[26])
        if len(b) >= 36:
            ev[COLS[3]].append(b[35])
    # base = CH1's resting level in volts: its median, taken on one sample in 64.
    base = np.median(v1[::64])
    print(
        "%s: %d trials (clock pulses per event write: %s); CH1 at rest %.3f V"
        % (name, len(sizes), sorted(set(sizes)), base)
    )
    # One plot per column. x = the plot.
    for col, c in enumerate(COLS):
        x = ax[row][col]
        x.grid(alpha=0.3)
        if row == 0:
            x.set_title(c)
        if col == 0:
            x.set_ylabel(name + "\nV", fontsize=8)
        # No edge of this kind in the capture.
        if not ev[c]:
            x.text(0.5, 0.5, "none", transform=x.transAxes, ha="center", color="gray")
            continue
        # t = time axis in microseconds from the clock edge. lo, hi_ = for each trial, the lowest
        # and highest CH1 value (relative to rest) in w, the stretch from 4 samples (0.25 us)
        # before the edge to 4 us after it. pp = peak-to-peak size per trial.
        t = (np.arange(-PRE, POST)) / U
        lo = []
        hi_ = []
        for e in ev[c]:
            seg = v1[e - PRE : e + POST] - base
            x.plot(t, seg, ".", color="#c9a000", ms=2.5, alpha=0.7)
            w = seg[PRE - 4 : PRE + 4 * U]
            lo.append(w.min())
            hi_.append(w.max())
        lo = np.array(lo)
        hi_ = np.array(hi_)
        pp = hi_ - lo
        x.text(
            0.98,
            0.95,
            "p-p median %.2f V, max %.2f V" % (np.median(pp), pp.max()),
            transform=x.transAxes,
            ha="right",
            va="top",
            fontsize=8,
        )
        print(
            "   %-22s %2d edges: lowest median %+.2f (extreme %+.2f), highest median %+.2f (extreme %+.2f), peak-to-peak median %.2f max %.2f V"
            % (
                c,
                len(lo),
                np.median(lo),
                lo.min(),
                np.median(hi_),
                hi_.max(),
                np.median(pp),
                pp.max(),
            )
        )
# Label the bottom row, add the title, write the picture.
for x in ax[-1]:
    x.set_xlabel("us from the clock edge that applies the byte")
fig.suptitle(title)
plt.tight_layout()
plt.savefig(outf, dpi=70)
