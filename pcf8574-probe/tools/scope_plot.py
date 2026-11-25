"""Plot a capture made by scope_trial.py: overview, one event, and the back-on edge in close-up.
usage: scope_plot.py <in.npy> <out.png> <range1> <range2> <label1> <label2> <title> [event index]
                     [thresh volts]

  in.npy       capture of interleaved CH1, CH2 bytes at 16 MS/s (.npy or .npz, through capio.load)
  range1/2     scope ranges the capture was made with (100mV 250mV 500mV 1V)
  label1/2     legend text for CH1 (drawn yellow) and CH2 (drawn blue)
  event index  which CH1 fall to show in detail, counting from 0 (default 2)
  thresh       CH1 threshold in volts at the probe tip that separates on from off (default 0.7)

Needs: scope_zero.json and capio.py next to this file, matplotlib.
Writes: <out.png> with four stacked plots: the whole capture, 11 ms around the chosen fall of
CH1, 600 us around it, and 120 us of raw samples around the moment CH1 comes back up.
Prints: minimum, maximum and mean of each channel in volts, the number of falls and rises of
CH1 with the times of the first falls, and the voltage ranges seen in the close-up.
"""

import sys, json, os, numpy as np
# Make capio.py, which sits next to this file, importable from wherever the script is run.
import os as _os, sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import capio
import matplotlib

# Draw straight to a file; no display is needed.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Arguments. inf / outf = input and output files, l1 / l2 = channel labels, which = index of
# the event to detail, thr = CH1 threshold in volts.
inf, outf, r1, r2, l1, l2, title = sys.argv[1:8]
which = int(sys.argv[8]) if len(sys.argv) > 8 else 2
thr = float(sys.argv[9]) if len(sys.argv) > 9 else 0.7
# Z = zero level in ADC counts for each range and channel.
Z = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_zero.json")))
FS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}  # volts at a x10 tip for 128 counts
# a = raw capture. v1, v2 = CH1 and CH2 in volts at the probe tip, cut to the same length n.
# t = time of each sample in seconds.
a = capio.load(inf)
RATE = 16e6
v1 = (a[0::2].astype(np.float32) - Z[r1]["ch1_zero"]) * FS[r1] / 128
v2 = (a[1::2].astype(np.float32) - Z[r2]["ch2_zero"]) * FS[r2] / 128
n = min(len(v1), len(v2))
v1, v2 = v1[:n], v2[:n]
t = np.arange(n) / RATE
print(
    "CH1 min %.2f max %.2f mean %.2f | CH2 min %.2f max %.2f mean %.2f"
    % (v1.min(), v1.max(), v1.mean(), v2.min(), v2.max(), v2.mean())
)
# events: CH1 falling through the threshold after at least 1 ms above it
# hi = CH1 above the threshold. sm = the same after a majority vote over k = 2400 samples, which
# is 150 us at 16 MS/s (not the 1 ms the comment above mentions), so shorter excursions are
# ignored. falls / rises = samples where sm goes from above to below / from below to above.
hi = v1 > thr
k = 2400
sm = np.convolve(hi, np.ones(k) / k, "same") > 0.5
falls = np.flatnonzero(sm[:-1] & ~sm[1:])
rises = np.flatnonzero(~sm[:-1] & sm[1:])
print(
    "%d falls, %d rises of CH1 through %.1f V; first falls at ms:" % (len(falls), len(rises), thr),
    np.round(falls[:8] / RATE * 1e3, 2),
)
# Four stacked plots. The first is the whole capture, drawing one sample in d = 200.
fig, ax = plt.subplots(4, 1, figsize=(12, 13))
d = 200
ax[0].plot(t[::d] * 1e3, v1[::d], color="#c9a000", lw=0.6, label=l1)
ax[0].plot(t[::d] * 1e3, v2[::d], color="#1f6fd0", lw=0.6, label=l2)
ax[0].set_title(title + "\nwhole capture (one sample in %d shown)" % d)
ax[0].set_xlabel("ms")
# Three more plots around the chosen fall f (a sample number). Each entry below is (time shown
# before the reference in s, time shown after it in s, axis unit, factor from seconds to that
# unit, title). They are skipped if the capture has too few falls.
if len(falls) > which:
    f = falls[which]
    for i, (pre, post, unit, scale, name) in enumerate(
        (
            (7e-3, 4e-3, "ms", 1e3, "one trial"),
            (100e-6, 500e-6, "us", 1e6, "switch-off and back-on"),
            (None, None, "us", 1e6, "back-on edge in close-up"),
        )
    ):
        if pre is None:
            # the back-on: first time CH1 rises through the threshold after the fall, raw samples
            # Search from 15 us to 1.5 ms after the fall (240 to 24000 samples). c = the first
            # sample above the threshold; if there is none, 150 us after the fall is used
            # instead. The window runs from 30 us before c to 90 us after it.
            seg = v1[f + 240 : f + 24000]
            up = np.flatnonzero(seg > thr)
            c = f + 240 + (up[0] if len(up) else 2160)
            lo, hi_ = c - 480, c + 1440
            ref = c
        else:
            lo, hi_ = int(f - pre * RATE), int(f + post * RATE)
            ref = f
        # Keep the window inside the capture. x = time axis relative to the reference.
        lo = max(lo, 0)
        hi_ = min(hi_, n)
        x = (np.arange(lo, hi_) - ref) / RATE * scale
        ax[i + 1].plot(
            x,
            v1[lo:hi_],
            color="#c9a000",
            lw=0.8,
            label=l1,
            marker="." if pre is None else None,
            ms=2,
        )
        ax[i + 1].plot(
            x,
            v2[lo:hi_],
            color="#1f6fd0",
            lw=0.8,
            label=l2,
            marker="." if pre is None else None,
            ms=2,
        )
        ax[i + 1].set_title("%s (event %d, at %.2f ms)" % (name, which, f / RATE * 1e3))
        ax[i + 1].set_xlabel(unit)
        if pre is None:
            print(
                "close-up: CH1 %.2f..%.2f CH2 %.2f..%.2f V"
                % (v1[lo:hi_].min(), v1[lo:hi_].max(), v2[lo:hi_].min(), v2[lo:hi_].max())
            )
# Common decoration, then write the picture.
for x in ax:
    x.set_ylabel("V at the tip")
    x.grid(alpha=0.3)
    x.legend(loc="upper right")
plt.tight_layout()
plt.savefig(outf, dpi=80)
