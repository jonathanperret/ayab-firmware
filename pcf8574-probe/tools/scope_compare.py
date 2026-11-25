"""Side-by-side view of several captures around one switch-off / back-on event.
usage: scope_compare.py <out.png> <title> <label1> <label2> <range> name=file.npy ...

  label1/2  legend text for CH1 (drawn yellow) and CH2 (drawn blue)
  range     scope range the captures were made with, either one name for both channels or
            "range1,range2" (100mV 250mV 500mV 1V)
  name=file one row of the picture per capture; name is the row title, file a capture of
            interleaved CH1, CH2 bytes at 16 MS/s (.npy or .npz, through capio.load)
Environment: TWIN=1 gives each channel its own self-scaling voltage axis. That is also done
automatically when the two ranges differ; otherwise both share one axis fixed at -1.5..7.5 V.

In each capture the script looks for "back-on" edges: a fast edge that follows another fast
edge by 50 to 200 us. It shows the third one (or the last, if there are fewer): on the left
150 us before to 250 us after, on the right 2 us before to 6 us after with every sample marked.
Needs: scope_zero.json and capio.py next to this file, matplotlib.
Writes: <out.png>. Prints, per capture: the number of edges and back-on edges and each channel's
voltage range, then the spread of a few measurements over all back-on edges.
scope_trial.py runs this script to make its quick-look picture.
"""

import sys, json, os, numpy as np
import os as _os, sys as _sys
# Make capio.py, which sits next to this file, importable from wherever the script is run.

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import capio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Arguments. caps = list of [row name, capture file].
outf, title, l1, l2, rng = sys.argv[1:6]
caps = [x.split("=", 1) for x in sys.argv[6:]]
# ZZ = zero level in ADC counts for each range and channel. FSS = volts at the tip of a x10
# probe for 128 ADC counts, for each range. RATE = samples per second.
ZZ = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_zero.json")))
FSS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}
RATE = 16e6
r1, r2 = rng.split(",") if "," in rng else (rng, rng)  # one range for both channels, or "ch1,ch2"
TWIN = r1 != r2 or bool(
    os.environ.get("TWIN")
)  # TWIN=1: separate, self-scaling axes even on one range
# One row of two plots per capture.
fig, ax = plt.subplots(len(caps), 2, figsize=(14, 3.1 * len(caps)), squeeze=False)
for row, (name, f) in enumerate(caps):
    # a = raw capture. v1, v2 = CH1 and CH2 in volts at the probe tip, cut to the same length n.
    a = capio.load(f)
    v1 = (a[0::2].astype(np.float32) - ZZ[r1]["ch1_zero"]) * FSS[r1] / 128
    v2 = (a[1::2].astype(np.float32) - ZZ[r2]["ch2_zero"]) * FSS[r2] / 128
    n = min(len(v1), len(v2))
    v1, v2 = v1[:n], v2[:n]
    # Note: the next comment describes an earlier method. What the code does now is on the lines
    # after it: it collects every fast change on either channel.
    # the back-on edge: largest fast change on CH2, else on CH1, away from the ends
    # Only look between 3 ms (48000 samples) from the start and 3 ms from the end. d1, d2 = size
    # of the change from each sample to the next, in volts.
    lo, hi = 48000, n - 48000
    d2 = np.abs(np.diff(v2[lo:hi]))
    d1 = np.abs(np.diff(v1[lo:hi]))
    # every event: samples where either channel jumps by more than 0.5 V between samples
    idx = np.flatnonzero((d2 > 0.5) | (d1 > 0.5)) + lo
    # ev = one sample number per edge: jumps less than 15 us (240 samples) after the last kept
    # one belong to the same edge. gaps = time from each edge to the next, in microseconds.
    ev = [idx[0]] if len(idx) else []
    for i in idx:
        if i - ev[-1] > 240:
            ev.append(i)
    gaps = np.diff(ev) / RATE * 1e6 if len(ev) > 1 else np.array([])
    # back-on = an event that follows another by 50..200 us
    back = [ev[k + 1] for k in range(len(ev) - 1) if 50 < gaps[k] < 200]
    print(
        "%s: %d edges seen, %d back-on edges; CH1 %.2f..%.2f, CH2 %.2f..%.2f"
        % (name, len(ev), len(back), v1.min(), v1.max(), v2.min(), v2.max())
    )
    # Nothing to show for this capture: say so in the titles of its two plots.
    if not back:
        for c in (0, 1):
            ax[row][c].set_title(name + ": no edge found on either channel")
        continue
    # c = the back-on edge to draw.
    c = back[min(2, len(back) - 1)]
    # For every back-on edge b: lowest and highest CH2 from 1.5 us before to 4.5 us after it
    # (24 and 72 samples), and lowest CH1 from 150 us to 1.5 us before it (the printed text says
    # "100 us", but 2400 samples are 150 us). s = the same as an array, one row per edge.
    stats = [
        (v2[b - 24 : b + 72].min(), v2[b - 24 : b + 72].max(), v1[b - 2400 : b - 24].min())
        for b in back
    ]
    s = np.array(stats)
    print(
        "   over %d back-on edges: CH2 lowest %.2f..%.2f, highest %.2f..%.2f; CH1 lowest in the 100 us before: %.2f..%.2f"
        % (
            len(back),
            s[:, 0].min(),
            s[:, 0].max(),
            s[:, 1].min(),
            s[:, 1].max(),
            s[:, 2].min(),
            s[:, 2].max(),
        )
    )
    # Left plot: 150 us before to 250 us after c. Right plot: 2 us before to 6 us after, with
    # a dot on every sample. a0, a1 = sample range, x = time axis in microseconds from c.
    for col, (pre, post) in enumerate(((150e-6, 250e-6), (2e-6, 6e-6))):
        a0, a1 = int(c - pre * RATE), int(c + post * RATE)
        x = (np.arange(a0, a1) - c) / RATE * 1e6
        ax[row][col].plot(
            x, v1[a0:a1], color="#c9a000", lw=0.9, label=l1, marker="." if col else None, ms=4
        )
        # Separate axes: CH1 on the left scale, CH2 on a second scale on the right.
        if TWIN:
            tw = ax[row][col].twinx()
            tw.plot(
                x, v2[a0:a1], color="#1f6fd0", lw=0.9, label=l2, marker="." if col else None, ms=4
            )
            tw.set_ylabel("blue: V at the tip", color="#1f6fd0")
            ax[row][col].set_ylabel("yellow: V at the tip", color="#a08000")
            if col == 0:
                tw.legend(loc="lower right", fontsize=8)
        # Shared axis for both channels, fixed from -1.5 V to 7.5 V.
        else:
            ax[row][col].plot(
                x, v2[a0:a1], color="#1f6fd0", lw=0.9, label=l2, marker="." if col else None, ms=4
            )
            ax[row][col].set_ylabel("V at the tip")
            ax[row][col].set_ylim(-1.5, 7.5)
        ax[row][col].set_title(name + (" — back-on edge, raw samples" if col else ""))
        ax[row][col].set_xlabel("us from the back-on edge")
        ax[row][col].grid(alpha=0.3)
    ax[row][0].legend(loc="center right" if not TWIN else "upper right", fontsize=8)
fig.suptitle(title)
plt.tight_layout()
plt.savefig(outf, dpi=75)
