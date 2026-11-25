"""Theoretical current rise and fall of a coil: air core (one inductance) against a solid iron core,
modelled as L1 in series with (L2 in parallel with a resistance standing for the iron).
usage: coil_model_chart.py <out.png>

Writes a picture with two panels to <out.png>: on the left the current after 8 V is applied
to the coil at time 0, on the right the current after the coil, carrying its full current,
is short-circuited at time 0. Each panel shows three curves over 8 ms: an air-core coil of
80 mH, an air-core coil of 240 mH, and the iron-core model. Also prints a table of the six
currents (mA) at 0.1, 0.5, 1, 2 and 4 ms.

Needs numpy and matplotlib. All values (8 V, 150 ohm, 80 mH, 160 mH, 160 ohm) are fixed
in the script; there are no other arguments or environment variables.

The circuits, with i the current through the coil:

  air core:   V --- R --- L --- 0 V
              v = R*i + L*di/dt
              rise from 0:  i(t) = V/R * (1 - exp(-t*R/L))
              fall from V/R with v = 0:  i(t) = V/R * exp(-t*R/L)

  iron core:  V --- R --- L1 ---+--- L2 ---+--- 0 V
                                |          |
                                +--- RI ---+
              i2 is the part of i that flows through L2; the rest, i - i2, flows through RI.
              Both branches see the same voltage:  L2*di2/dt = RI*(i - i2)
              Around the loop:                     v = R*i + L1*di/dt + RI*(i - i2)

RI stands for the eddy currents in the solid iron. Just after a step, i2 cannot change yet,
so the change of current goes through RI and the coil behaves like L1 alone (80 mH). Once
i2 has caught up with i, nothing flows in RI and the coil behaves like L1 + L2 (240 mH).
"""

import sys, numpy as np
import matplotlib

# "Agg" draws to a file without needing a display.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

V, R = 8.0, 150.0  # volts across coil and its resistance; final current V/R = 53 mA
# L1, L2 in henries, RI in ohms.
L1, L2, RI = (
    0.080,
    0.160,
    160.0,
)  # iron model: 80 mH at first, 240 mH in the end, changeover L2/RI = 1 ms
dt = 1e-6  # time step: 1 microsecond
t = np.arange(0, 8e-3, dt)  # the times computed: 0 to 8 ms, in seconds


def air(L, rise):
    """Current of an air-core coil (resistance R, a single inductance L) at each time in t.

    L:    inductance in henries.
    rise: True for the current after V is applied to a coil with no current;
          False for the current after a coil carrying V/R is short-circuited.
    Returns an array of currents in amps, one per element of t (exact formula).
    """
    e = np.exp(-t * R / L)  # exponential decay with time constant L/R
    return V / R * (1 - e) if rise else V / R * e


def iron(rise):
    """Current of the iron-core model at each time in t, by step-by-step integration.

    rise: True for the current after V is applied to a coil with no current;
          False for the current after a coil carrying V/R is short-circuited.
    Returns an array of currents in amps, one per element of t.
    """
    # i: current through R and L1 (the current one would measure), in amps.
    # i2: the part of it that flows through L2. At the start of the fall the coil has been
    # on for a long time, so both equal V/R and nothing flows in RI.
    i = 0.0 if rise else V / R
    i2 = i
    v = V if rise else 0.0  # voltage applied from time 0 on: V, or 0 for the short circuit
    out = np.empty_like(t)
    for k in range(len(t)):
        out[k] = i
        # RI*(i - i2) is the voltage across RI, which is also the voltage across L2.
        d2 = RI * (i - i2) / L2  # di2/dt, amps per second
        # What remains of v after the drop in R and the drop across L2/RI is across L1.
        di = (v - R * i - RI * (i - i2)) / L1  # di/dt, amps per second
        # Forward Euler step: both rates are computed from the old values, then applied.
        i += di * dt
        i2 += d2 * dt
    return out


# Colours: main text, secondary text, tick labels, grid lines, axis lines, background.
INK, SEC, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
# One colour per curve.
C = {"air240": "#2a78d6", "iron": "#eb6834", "air80": "#1baf7a"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
# Two panels side by side sharing the current axis; the figure size is in inches.
fig, ax = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True, facecolor=SURF)
for a, rise, title in (
    (ax[0], True, "Switched on: 8 V applied at time 0"),
    (ax[1], False, "Switched off into a short circuit at time 0"),
):
    a.set_facecolor(SURF)
    ms = t * 1e3  # time axis in milliseconds
    # The three curves, in milliamps. "air240" is an air-core coil of L1 + L2.
    s = {"air240": air(L1 + L2, rise) * 1e3, "air80": air(L1, rise) * 1e3, "iron": iron(rise) * 1e3}
    a.plot(ms, s["air80"], color=C["air80"], lw=2, label="Air core, 80 mH")
    a.plot(ms, s["air240"], color=C["air240"], lw=2, label="Air core, 240 mH")
    a.plot(
        ms,
        s["iron"],
        color=C["iron"],
        lw=2,
        label="Solid iron core: 80 mH at first, 240 mH in the end",
    )
    a.set_title(title, color=INK, fontsize=12, loc="left")
    a.set_xlabel("milliseconds", color=SEC)
    a.set_xlim(0, 8)  # milliseconds
    a.set_ylim(0, 58)  # milliamps; the final current is 53 mA
    a.grid(color=GRID, lw=0.8)
    a.tick_params(colors=MUTED, length=0)
    # Hide the frame around the plot and draw only a base line at zero current.
    [sp.set_visible(False) for sp in a.spines.values()]
    a.axhline(0, color=AXIS, lw=1)
    # one time constant of each air-core coil
    for key, L in (("air80", L1), ("air240", L1 + L2)):
        tc = L / R * 1e3  # time constant L/R in milliseconds
        # After one time constant a rising current has covered 1 - 1/e = 63.2 % of the way
        # and a falling one is down to 1/e = 36.8 %. y is that current in milliamps.
        y = V / R * 1e3 * (0.632 if rise else 0.368)
        a.plot([tc], [y], "o", ms=8, color=C[key], mec=SURF, mew=2, zorder=5)
        # Label the dot with its time, shifted (in points) below the dot on the rising
        # curves and above it on the falling ones.
        a.annotate(
            "%.2f ms" % tc,
            (tc, y),
            xytext=(10, -14 if rise else 8),
            textcoords="offset points",
            color=SEC,
            fontsize=9,
        )
    # Note explaining the dots, placed in axes fractions (0..1): bottom right on the rise
    # panel, higher up on the fall panel.
    a.text(
        0.985,
        0.03 if rise else 0.62,
        "dots: one time constant (L / R) of each air-core coil",
        transform=a.transAxes,
        ha="right",
        color=SEC,
        fontsize=9,
    )
    if rise:
        # Dashed line at the final current V/R, with its label (the "53" is fixed text).
        a.axhline(V / R * 1e3, color=AXIS, lw=1, ls=(0, (4, 4)))
        a.text(7.9, V / R * 1e3 + 1, "final current 53 mA", ha="right", color=SEC, fontsize=9)
ax[0].set_ylabel("coil current, mA", color=SEC)
leg = ax[1].legend(loc="upper right", frameon=False, fontsize=10)
[tx.set_color(INK) for tx in leg.get_texts()]
fig.suptitle(
    "Current in a 150 ohm coil: one inductance (air core) against a solid iron core",
    color=INK,
    fontsize=13,
    x=0.01,
    ha="left",
)
# Leave the top 5 % of the figure for the overall title.
plt.tight_layout(rect=(0, 0, 1, 0.95))
plt.savefig(sys.argv[1], dpi=110, facecolor=SURF)

# Table of values on standard output. r and f: iron-core rise and fall curves, in amps.
r = iron(True)
f = iron(False)
for T in (0.1, 0.5, 1, 2, 4):  # times in milliseconds
    k = int(T * 1e-3 / dt)  # index of that time in t
    print(
        "%.1f ms: rise air80 %.1f, air240 %.1f, iron %.1f mA | fall air80 %.1f, air240 %.1f, iron %.1f mA"
        % (
            T,
            air(L1, True)[k] * 1e3,
            air(L1 + L2, True)[k] * 1e3,
            r[k] * 1e3,
            air(L1, False)[k] * 1e3,
            air(L1 + L2, False)[k] * 1e3,
            f[k] * 1e3,
        )
    )
