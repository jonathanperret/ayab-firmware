"""What the coil-current capture should look like for each candidate description of the coils.

usage: coil_current_preview.py <out.png>

One coil of 150 ohm switched on from rest with 8.2 V across it (8.94 V supply less the driver's
0.7 V), as the current-sense amplifier in the coils' supply wire would see it. Three candidates:
one inductance of 240 mH; one inductance of 80 mH (about what the component tester read); and
80 mH at first becoming 240 mH (80 mH in series with 160 mH that has 160 ohm across it).
Left: the first half millisecond, where the slope alone tells them apart. Right: the whole rise."""
import sys
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

V, R = 8.2, 150.0
dt = 1e-6
t = np.arange(0, 8e-3, dt)


def single(L):
    return V / R * (1 - np.exp(-t * R / L))


def double(L1, L2, RI):
    i = i2 = 0.0
    out = np.empty_like(t)
    for k in range(len(t)):
        out[k] = i
        di = (V - R * i - RI * (i - i2)) / L1
        d2 = RI * (i - i2) / L2
        i += di * dt
        i2 += d2 * dt
    return out


curves = [
    ("One inductance, 240 mH", single(0.240), "#2a78d6"),
    ("One inductance, 80 mH", single(0.080), "#1baf7a"),
    ("80 mH at first, 240 mH in the end", double(0.080, 0.160, 160.0), "#eb6834"),
]
INK, SEC, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
plt.rcParams.update({"font.size": 11})
fig, ax = plt.subplots(1, 2, figsize=(13, 5.2), facecolor=SURF)
for a, tmax, title in ((ax[0], 0.5, "The first half millisecond"), (ax[1], 8.0, "The whole rise")):
    a.set_facecolor(SURF)
    n = int(tmax * 1e-3 / dt)
    for label, y, col in curves:
        a.plot(t[:n] * 1e3, y[:n] * 1e3, color=col, lw=2, label=label)
    a.set_title(title, loc="left", color=INK, fontsize=12)
    a.set_xlabel("milliseconds after switch-on", color=SEC)
    a.set_xlim(0, tmax)
    a.set_ylim(0, None)
    a.grid(color=GRID, lw=0.8)
    a.tick_params(colors=MUTED, length=0)
    [s.set_visible(False) for s in a.spines.values()]
    a.axhline(0, color=AXIS, lw=1)
ax[0].set_ylabel("coil current, mA", color=SEC)
k = int(0.1e-3 / dt)
ax[0].axvline(0.1, color=AXIS, lw=1, ls=(0, (4, 4)))
for (label, y, col), offset in zip(curves, ((8, -14), (-52, 10), (8, -16))):  # label positions chosen not to collide
    ax[0].plot([0.1], [y[k] * 1e3], "o", ms=8, color=col, mec=SURF, mew=2, zorder=5)
    ax[0].annotate("%.1f mA" % (y[k] * 1e3), (0.1, y[k] * 1e3), xytext=offset, textcoords="offset points", color=SEC, fontsize=10)
ax[0].text(0.105, ax[0].get_ylim()[1] * 0.96, "at 0.1 ms", color=SEC, fontsize=9, va="top")
leg = ax[1].legend(loc="lower right", frameon=False, fontsize=10)
[tx.set_color(INK) for tx in leg.get_texts()]
fig.suptitle("Expected coil current after switch-on, for three descriptions of the coil (a model, not a measurement)", x=0.01, ha="left", color=INK, fontsize=13)
plt.tight_layout(rect=(0, 0, 1, 0.94))
plt.savefig(sys.argv[1], dpi=105, facecolor=SURF)
for label, y, col in curves:
    print("%-36s" % label, "  ".join("%.2f ms: %.1f mA" % (T, y[int(T * 1e-3 / dt)] * 1e3) for T in (0.05, 0.1, 0.2, 0.5, 1, 2, 4)))
