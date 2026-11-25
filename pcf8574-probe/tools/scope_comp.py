"""Probe compensation check: capture the scope's calibration square wave on the Pi at several ranges,
average the rising edges and report the overshoot (+) or undershoot (-) against the settled level.
usage: scope_comp.py <out.png> <tag> [ranges, default 100mV,250mV,500mV,1V]

  tag     text put in the file names and in the picture's title
  ranges  comma-separated list of scope ranges to test; both channels use the same range
Environment: MS = sample rate in million samples per second (default 16).

Runs on the Mac. For each range it runs scope.py on the Pi over ssh (2 channels, 4 megabytes,
saved as out/comp_<tag>_<range>.npy in the "scope" folder of the account hard-coded below),
copies the file into the project's captures folder with scp, and analyses it. It uses scope.py
directly, not scope_daemon.py.
Needs: key-based ssh access to the Pi with sudo, scope.py installed there, a probe on the
scope's calibration output for each channel to be checked, capio.py next to this file,
matplotlib. scope_zero.json is not used: each trace is centred on its own median.
Writes: captures/comp_<tag>_<range>.npy for each range, and <out.png> with one row per range and
one plot per channel showing the averaged rising edge in percent of the step.
Prints: one line per range with, for each channel, the step height in volts, the square wave's
frequency, the overshoot in percent and roughly how long it lasts.
scope_live.py shows the same measurement continuously while the probe is being trimmed.
"""

import sys, os, subprocess, numpy as np
# Make capio.py, which sits next to this file, importable from wherever the script is run.
import os as _os, sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import capio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Arguments. outf = output picture, tag = label, ranges = list of range names to test.
outf, tag = sys.argv[1], sys.argv[2]
ranges = (sys.argv[3] if len(sys.argv) > 3 else "100mV,250mV,500mV,1V").split(",")
S = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures"
)  # durable folder in the project
# FS = volts at the tip of a x10 probe for 128 ADC counts, for each range.
# MS = sample rate in MS/s, RATE = the same in samples per second.
FS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}
MS = int(__import__("os").environ.get("MS", "16"))
RATE = MS * 1e6
U = MS  # samples per microsecond
# One row of two plots (CH1, CH2) per range.
fig, ax = plt.subplots(len(ranges), 2, figsize=(13, 2.8 * len(ranges)), squeeze=False)
for row, r in enumerate(ranges):
    # Capture on the Pi: scope.py <rate> <range> <range> 2 channels, 4 megabytes. The capture is
    # made as root, so the file is then handed to the ssh user for scp to read it.
    name = "comp_%s_%s" % (tag, r)
    subprocess.run(
        [
            "ssh",
            "jonathan@raspberrypi.local",
            "cd ~/scope && sudo python3 scope.py %d %s %s 2 4 out/%s.npy >/dev/null && sudo chown jonathan out/%s.npy"
            % (MS, r, r, name, name),
        ],
        check=True,
    )
    # Fetch the capture and load it. line = the text printed for this range.
    subprocess.run(
        [
            "scp",
            "-q",
            "jonathan@raspberrypi.local:scope/out/%s.npy" % name,
            "%s/%s.npy" % (S, name),
        ],
        check=True,
    )
    a = capio.load("%s/%s.npy" % (S, name))
    line = "%-6s" % r
    # Each channel in turn; col = its colour in the plot (CH1 yellow, CH2 blue).
    for ch, col in ((0, "#c9a000"), (1, "#1f6fd0")):
        # v = the channel in volts at the probe tip, centred on its median.
        # sm = v smoothed over k samples (2 us), used only to find the edges.
        v = a[ch::2].astype(np.float32) * FS[r] / 128
        v -= np.median(v)
        k = 2 * U
        sm = np.convolve(v, np.ones(k) / k, "same")
        # up = samples where the smoothed wave rises through mid, the point halfway between its
        # 5th and 95th percentiles. Edges within 500 us of either end are dropped; at least 3
        # are required.
        mid = (np.percentile(sm, 5) + np.percentile(sm, 95)) / 2
        up = np.flatnonzero((sm[:-1] < mid) & (sm[1:] >= mid))
        up = up[(up > 500 * U) & (up < len(v) - 500 * U)]
        if len(up) < 3:
            line += "  CH%d: no square wave found (span %.2f V)" % (ch + 1, np.ptp(sm))
            continue
        # period = median time between rising edges, in seconds.
        period = np.median(np.diff(up)) / RATE
        seg = np.mean([v[u - 100 * U : u + 400 * U] for u in up], axis=0)  # -100 us .. +400 us
        # low = level before the edge (100 to 25 us before it).
        low = seg[: 75 * U].mean()
        settled = seg[400 * U : 480 * U].mean()
        amp = settled - low  # settled: 300 to 380 us after the edge
        early = seg[105 * U : 115 * U].mean()  # 5 to 15 us after the edge
        over = (early - settled) / amp * 100
        # time for the excess to fall to a third
        # ex = the excess over the settled level, from 5 us after the edge on, smoothed over
        # 10 us. tau = time in microseconds, counted from that 5 us point,
        # until the smoothed excess is below a third of its initial value. It is only worked out
        # when the overshoot exceeds 2 %, and is 0 otherwise (also when the level is never reached).
        ex = np.convolve(seg[105 * U :] - settled, np.ones(10 * U) / (10 * U), "valid")
        tau = np.argmax(np.abs(ex) < abs(early - settled) / 3) / RATE * 1e6 if abs(over) > 2 else 0
        line += "  CH%d: %.2f V, %.0f Hz, edge %+.0f %% (dies away in ~%.0f us)" % (
            ch + 1,
            amp,
            1 / period,
            over,
            tau,
        )
        # Plot the averaged edge in percent of the step, against microseconds from the edge.
        x = (np.arange(len(seg)) - 100 * U) / RATE * 1e6
        ax[row][ch].plot(x, (seg - low) / amp * 100, color=col, lw=1)
        ax[row][ch].axhline(100, color="gray", lw=0.6, ls="--")
        ax[row][ch].set_ylim(-10, 160)
        ax[row][ch].set_title("CH%d, %s range: %+.0f %%" % (ch + 1, r, over))
        ax[row][ch].set_xlabel("us from the rising edge")
        ax[row][ch].set_ylabel("% of step")
        ax[row][ch].grid(alpha=0.3)
    print(line)
# Title and write the picture.
fig.suptitle("Probe compensation, calibration square wave, average of all rising edges (%s)" % tag)
plt.tight_layout()
plt.savefig(outf, dpi=75)
