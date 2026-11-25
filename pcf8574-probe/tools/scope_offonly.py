"""Average the switch-off events of several captures and plot the output's fall-back, to read how long
the clamp diodes conduct.
usage: scope_offonly.py <out.png> <title> <range> name=file.npy ...
(CH1 = output, CH2 = clamp common)

  range      the one scope range both channels were captured with (100mV 250mV 500mV 1V)
  name=file  one curve per capture, at most six (there are six colours); name is its legend
             text, file a capture of interleaved CH1, CH2 bytes at 16 MS/s (.npy or .npz,
             through capio.load)

A switch-off is taken to be CH1 rising through 5 V after staying below 3 V from 60 us to 4 us
before. All switch-offs of a capture are averaged, from 200 us before to 6 ms after.
Needs: scope_zero.json and capio.py next to this file, matplotlib.
Writes: <out.png> with two plots, CH1 above and CH2 below, both smoothed over 8 us, one curve
per capture. The titles name the probed points (U5 pin 17 and U5 pin 10); they are fixed text.
Prints: per capture, the number of events, the output level just after switch-off and at rest,
the clamp common level, the time at which the output has fallen halfway back to rest, and the
lowest level reached afterwards with its time. Voltages are at the probe tip.
"""

import sys, os, json, numpy as np
# Make capio.py, which sits next to this file, importable from wherever the script is run.
import os as _os, sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import capio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Arguments. caps = list of [curve name, capture file].
outf, title, rng = sys.argv[1:4]
caps = [x.split("=", 1) for x in sys.argv[4:]]
# Z = zero levels in ADC counts for the chosen range ("ch1_zero", "ch2_zero").
Z = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_zero.json")))[
    rng
]
# FS = volts at the tip of a x10 probe for 128 ADC counts on the chosen range.
# U = samples per microsecond (16 MS/s).
FS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}[rng]
U = 16
fig, ax = plt.subplots(2, 1, figsize=(12, 8))
# cols = one colour per capture.
cols = ["#c9a000", "#d1495b", "#1f6fd0", "#2a9d8f", "#7b2cbf", "#555"]
for k, (name, f) in enumerate(caps):
    # a = raw capture. v1, v2 = CH1 and CH2 in volts at the probe tip, cut to the same length n.
    a = capio.load(f)
    v1 = (a[0::2].astype(np.float32) - Z["ch1_zero"]) * FS / 128
    v2 = (a[1::2].astype(np.float32) - Z["ch2_zero"]) * FS / 128
    n = min(len(v1), len(v2))
    v1, v2 = v1[:n], v2[:n]
    # up = samples where CH1 rises through 5 V, keeping only those at least 300 us after the
    # start and 6100 us before the end so that the slices below fit.
    hi = v1 > 5
    up = np.flatnonzero(~hi[:-1] & hi[1:])
    up = up[(up > 300 * U) & (up < n - 6100 * U)]
    up = [
        u for u in up if v1[u - 60 * U : u - 4 * U].max() < 3
    ]  # a real switch-off: output was low just before
    if not up:
        print(name, ": no switch-off found")
        continue
    # seg1, seg2 = CH1 and CH2 averaged over all switch-offs, from 200 us before to 6000 us
    # after. t = the matching time axis.
    seg1 = np.mean([v1[u - 200 * U : u + 6000 * U] for u in up], axis=0)
    seg2 = np.mean([v2[u - 200 * U : u + 6000 * U] for u in up], axis=0)
    t = (np.arange(len(seg1)) - 200 * U) / U / 1000.0  # ms
    # com, rest = clamp common level and output level at rest: means over the last 2 ms of the
    # averaged segment (4 to 6 ms after the switch-off).
    com = seg2[-2000 * U :].mean()
    rest = seg1[-2000 * U :].mean()
    # sm = averaged output smoothed over 8 us. after = sm from 16 us after the switch-off on.
    # lvl = output level just after the switch-off (mean from 16 to 36 us after it).
    # mid = halfway between that level and rest. tend = first time the output is below mid.
    sm = np.convolve(seg1, np.ones(8 * U) / (8 * U), "same")
    after = sm[200 * U + 16 * U :]
    lvl = after[: 20 * U].mean()
    mid = (lvl + rest) / 2
    tend = np.argmax(after < mid) / U + 16  # us after the switch-off
    print(
        "%s: %d events; output %.2f V just after switch-off, %.2f V at rest, clamp common %.2f V; falls halfway back at %.0f us; lowest afterwards %.2f V at %.0f us"
        % (name, len(up), lvl, rest, com, tend, after.min(), np.argmin(after) / U + 16)
    )
    # Plot one point every d samples (4 us). The CH2 curve is smoothed the same way as CH1.
    d = 4 * U
    ax[0].plot(
        t[::d], sm[::d], color=cols[k], lw=1.3, label="%s (halfway back at %.0f us)" % (name, tend)
    )
    ax[1].plot(
        t[::d],
        np.convolve(seg2, np.ones(8 * U) / (8 * U), "same")[::d],
        color=cols[k],
        lw=1.0,
        label=name,
    )
# Titles, axes and limits, then write the picture. Time axis: -0.2 to 6 ms. The CH1 plot
# is limited to 5..11 V.
ax[0].set_title(
    title + "\nCH1: U5 pin 17, output of solenoid 9, average of all switch-offs, smoothed over 8 us"
)
ax[1].set_title("CH2: U5 pin 10, clamp common")
for x in ax:
    x.set_xlabel("ms after the switch-off")
    x.set_ylabel("V at the tip")
    x.grid(alpha=0.3)
    x.legend(fontsize=9)
    x.set_xlim(-0.2, 6)
ax[0].set_ylim(5, 11)
plt.tight_layout()
plt.savefig(outf, dpi=75)
