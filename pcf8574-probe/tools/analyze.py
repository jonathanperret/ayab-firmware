"""Summarise and plot scope captures saved as cap_<name>.npy.

usage: analyze.py <outdir> <name> [<name> ...]

The captures are raw two-channel recordings as written by run_capture.py (bytes of
channel 1 and channel 2 interleaved). The sample rate is taken to be 16 MS/s.
Channel 1 is the ground of the interface board measured against the ground of the UNO
(100 mV range, x1 probe); channel 2 is a second signal on a x10 probe, treated as a logic
signal with a threshold of 2 V above its baseline.

The zero level of each channel is the median of the FIRST capture named on the command
line, and is used for all the others; that one should therefore be a quiet capture.

For each name, prints one line: lowest and highest ground voltage, how many samples are
more than 40 mV away from zero, the range of channel 2 and its number of edges; and writes
<outdir>/plot_<name>.png with three panels: the ground voltage over the whole capture, and
a close-up of both channels around the largest ground excursion."""

import sys, numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

outdir = sys.argv[1]
rate = 16e6  # samples per second per channel (fixed)
K1 = 500.0 / 128  # mV per LSB, CH1 at 100mV/div, x1 probe
K2 = 12.5 / 128  # V per LSB, CH2 at 250mV/div, x10 probe


def load(name):
    """Load one capture and split it into its two channels.

    name: the part of the file name between "cap_" and ".npy".
    Returns (channel 1, channel 2) as two int16 arrays of raw counts (0-255) of equal
    length."""
    a = np.load("%s/cap_%s.npy" % (outdir, name))
    n = len(a) // 2
    return a[0 : 2 * n : 2].astype(np.int16), a[1 : 2 * n : 2].astype(np.int16)


names = sys.argv[2:]
# base1, base2: zero level of each channel in raw counts, set from the first capture.
base1 = base2 = None
for name in names:
    c1, c2 = load(name)
    if base1 is None:
        base1, base2 = np.median(c1), np.median(c2)
    # v1: channel 1 in mV, v2: channel 2 in V, both relative to the baselines.
    v1 = (c1 - base1) * K1
    v2 = (c2 - base2) * K2
    # hi: channel 2 above 2 V. edges: indices where it crosses that threshold.
    hi = v2 > 2.0
    edges = np.flatnonzero(hi[1:] != hi[:-1])
    print(
        "%-11s CH1 ground: min %+6.0f mV max %+6.0f mV, |dev|>40mV in %7d samples (%.4f%%) | CH2: min %.1f V max %.1f V, %d edges"
        % (
            name,
            v1.min(),
            v1.max(),
            (np.abs(v1) > 40).sum(),
            100.0 * (np.abs(v1) > 40).mean(),
            v2.min(),
            v2.max(),
            len(edges),
        )
    )
    # overview envelope
    # Each block of 4000 samples (0.25 ms) is drawn as a band from its minimum to its
    # maximum; t is the start of each block in ms. r2, the same for channel 2, is computed
    # but not drawn.
    blk = 4000
    m = len(v1) // blk
    t = np.arange(m) * blk / rate * 1e3
    fig, ax = plt.subplots(3, 1, figsize=(11, 8))
    r1 = v1[: m * blk].reshape(m, blk)
    r2 = v2[: m * blk].reshape(m, blk)
    ax[0].fill_between(t, r1.min(1), r1.max(1), color="C0")
    ax[0].set_ylabel("board GND vs UNO GND (mV)")
    ax[0].set_title("%s: whole capture (min/max envelope, %.2f s)" % (name, len(v1) / rate))
    ax[0].set_xlabel("ms")
    ax[0].grid(alpha=0.3)
    # zoom on worst CH1 excursion
    # i: sample with the largest absolute ground voltage. The close-up covers 400 samples
    # (25 microseconds) on each side; tz is in microseconds relative to that sample.
    i = int(np.argmax(np.abs(v1)))
    w = 400
    lo, hi_ = max(0, i - w), min(len(v1), i + w)
    tz = (np.arange(lo, hi_) - i) / rate * 1e6
    ax[1].plot(tz, v1[lo:hi_], "C0.-", ms=3)
    ax[1].set_ylabel("board GND (mV)")
    ax[1].grid(alpha=0.3)
    ax[1].set_title("zoom on largest ground excursion (%+.0f mV)" % v1[i])
    ax[2].plot(tz, v2[lo:hi_], "C1.-", ms=3)
    ax[2].set_ylabel("CH2 (V)")
    ax[2].set_xlabel("µs from excursion")
    ax[2].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("%s/plot_%s.png" % (outdir, name), dpi=80)
    plt.close(fig)
