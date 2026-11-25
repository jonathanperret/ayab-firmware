"""The fast event with the pulse produced by the circuit itself instead of assumed.

usage: sim_pulse.py            (run from the probe folder, after sim_fit.py)
Writes sim/pulse_from_driver.cir (ngspice), journal/sim-pulse-from-driver.png, and prints tables.

How it joins the two earlier simulations:
  - from the slow model (sim/fit.json): the clamp diode's forward behaviour, the driver's on-voltage
    and resistance, and the current each coil carries at the moment of switching back on;
  - from the fast what-if (sim_fast.py): the track inductances estimated from the layout, the
    expander, C6 and the two bus lines.
During the event (some tens of nanoseconds) a coil's current cannot change, so each coil is a constant
current. Before the switch-on that current circulates through the clamp diode; the driver then
switches on over a time T_SW, the current moves over to the driver, and the diode, still full of
charge, conducts backwards for a moment. Both effects pull current from the 9 V rail to ground.

Still assumed, because nothing measured gives them: the clamp diode's reverse recovery (set in the simulator by its transit-time parameter TT), the time the
driver takes to switch on, and the capacitance on each output. N coils are lumped into one branch."""
import os, sys, json, subprocess
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_fast import LVAL

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.join(HERE, "sim")
F = json.load(open(os.path.join(SIM, "fit.json")))["two inductances"]

NETLIST = """* The fast event with the pulse produced by the driver's clamp diode and switch. See tools/sim_pulse.py.
* Reference (node 0) is the controller's ground pad. Tracks: inductance with 150 ohm across (losses unknown).
.param n = {n}          ; coils switched on together
.param i0 = {i0}        ; current in each coil at that moment, amperes (from the slow model)
.param tt = {tt}        ; clamp diode transit time, which sets its reverse recovery, seconds (ASSUMED)
.param tsw = {tsw}      ; time the driver takes to switch on, seconds (ASSUMED)
.param cout = 30p       ; capacitance on each output, farads (ASSUMED)

Vbulk capp capn 8.9
LGB capn 0 {LGB:.1f}n
RdGB capn 0 150
L9 capp com {L9:.1f}n
Rd9 capp com 150
* the coils: a constant current for the length of the event, from the 9 V side into the outputs
Icoil com out DC {{n*i0}}
* the clamp diodes (n in parallel), with the forward behaviour fitted in the slow model
Dclamp out com DCL area={{n}}
.model DCL D(IS={IS:.4g} N={N:.4g} RS={RS:.4g} TT={{tt}} CJO=20p)
Cout out j {{n*cout}}
* the driver's outputs: conductance rising from nothing to n/Ron over tsw, then the fixed drop
Vctl ctl 0 PWL(0 0 20n 0 {{20n+tsw}} 1)
Bsw out d1 I = V(out,d1) * (1e-9 + V(ctl) * n / {RON:.4g})
Vdrop d1 j {V0:.4g}
LG1 j 0 {LG1:.1f}n
RdG1 j 0 150

LB1 j c6n {LB1:.1f}n
RdB1 j c6n 150
LB2 c6n vss {LB2:.1f}n
RdB2 c6n vss 150
V5 n5 0 5
L5F n5 c6p {L5F:.1f}n
Rd5F n5 c6p 150
LC6 c6p c6a 1n
RC6 c6a c6b 20m
C6 c6b c6n 1u
L5B c6p vdd {L5B:.1f}n
Rd5B c6p vdd 150
Cchip vdd vss 100p
Rchip vdd vss 5k
Rpu n5 hc 5k
Chc hc 0 10p
LBH hc hu {LBUS:.1f}n
RdBH hc hu 150
Chu hu vss 10p
Dhl vss hu DESD
Dhh hu vdd DESD
Rlo lc 0 25
LBL lc lu {LBUS:.1f}n
RdBL lc lu 150
Clu lu vss 10p
Dll vss lu DESD
Dlh lu vdd DESD
.model DESD D(IS=1e-12 N=1 RS=5 CJO=3p)

.control
set wr_singlescale
save all @dclamp[id]
tran 0.05n 400n
wrdata pulse_from_driver.txt v(com,j) v(vss) v(vdd,vss) v(hu,vss) v(lu,vss) i(Vbulk) @dclamp[id] v(out,j)
.endc
.end
"""


def run(n, i0, tt, tsw):
    net = NETLIST.format(n=n, i0=i0, tt=tt, tsw=tsw, IS=F["IS"], N=F["N"], RS=F["RS"], RON=F["RON"], V0=F["V0"], **LVAL)
    open(os.path.join(SIM, "pulse_from_driver.cir"), "w").write(net)
    out = os.path.join(SIM, "pulse_from_driver.txt")
    if os.path.exists(out): os.remove(out)
    r = subprocess.run(["ngspice", "-b", "pulse_from_driver.cir"], cwd=SIM, capture_output=True, text=True)
    if not os.path.exists(out): raise SystemExit(r.stdout[-2500:] + r.stderr[-1500:])
    d = np.loadtxt(out)
    w = {k: d[:, i] for i, k in enumerate(["t", "rail", "gnd", "supply", "high", "low", "isup", "idiode", "out"])}
    w["isup"] = -w["isup"]          # current delivered by the bulk capacitors
    return w


def summary(w):
    rate = np.abs(np.gradient(w["isup"], w["t"])).max() * 1e-6
    return dict(rail=w["rail"].min(), gnd_hi=w["gnd"].max(), gnd_lo=w["gnd"].min(), sup_lo=w["supply"].min(), sup_hi=w["supply"].max(),
                low_hi=w["low"].max(), low_lo=w["low"].min(), ipk=w["isup"].max(), rev=-w["idiode"].min(), rate=rate)


if __name__ == "__main__":
    TSW = 20e-9
    print("Six coils at 40 mA each (switched back on 0.2 ms after a long pulse), driver switching on in 20 ns.")
    print("diode transit time | clamp rail lowest | supply current peak | diode reverse peak | fastest change | expander ground vs controller | 5 V across expander")
    for tt in (0, 10e-9, 30e-9, 100e-9, 300e-9, 1e-6):
        s = summary(run(6, 0.040, max(tt, 1e-12), TSW))
        print("  %6.0f ns        | %5.1f V           | %.2f A              | %.2f A             | %4.0f A/us      | %+.1f / %+.1f V                  | %.2f .. %.2f V" % (tt * 1e9, s["rail"], s["ipk"], s["rev"], s["rate"], s["gnd_hi"], s["gnd_lo"], s["sup_lo"], s["sup_hi"]))
    print("\nSame, with no reverse recovery in the diode, against how fast the driver switches on:")
    for tsw in (5e-9, 20e-9, 50e-9, 100e-9, 200e-9):
        s = summary(run(6, 0.040, 1e-12, tsw))
        print("  switch-on in %3.0f ns: clamp rail lowest %5.1f V, fastest change %4.0f A/us, expander ground %+.1f / %+.1f V" % (tsw * 1e9, s["rail"], s["rate"], s["gnd_hi"], s["gnd_lo"]))
    TT = 100e-9
    print("\nWith diode transit time %.0f ns and switch-on in 20 ns: coils and current per coil (from the slow model's table), against what the bench did" % (TT * 1e9))
    print("coils x mA each | bench      | clamp rail lowest | fastest change | expander ground vs controller | bus line held low, vs expander ground")
    cases = [(6, 39.5, "resets"), (6, 6.7, "resets"), (6, 2.0, "no reset"), (4, 45.0, "resets"), (3, 45.0, "no reset"), (3, 28.9, "no reset"), (3, 15.6, "resets"), (3, 6.7, "resets"), (3, 2.0, "no reset"), (1, 45.0, "no reset"), (6, 0.0, "no reset (from rest)")]
    for n, ma, bench in cases:
        s = summary(run(n, ma * 1e-3, TT, TSW))
        print("  %d x %4.1f mA   | %-10s | %5.1f V           | %4.0f A/us      | %+.2f / %+.2f V                | %+.1f .. %+.1f V" % (n, ma, bench, s["rail"], s["rate"], s["gnd_hi"], s["gnd_lo"], s["low_lo"], s["low_hi"]))
    # picture: the part that needs no assumption about the diode (no reverse recovery) against a modest one
    runs = [("no reverse recovery in the diodes", run(6, 0.040, 1e-12, TSW), "#2a78d6"), ("with reverse recovery (transit time 30 ns)", run(6, 0.040, 30e-9, TSW), "#eb6834")]
    SEC, GRID, SURF, INK = "#52514e", "#e1e0d9", "#fcfcfb", "#0b0b0b"
    fig, ax = plt.subplots(2, 2, figsize=(13, 8), facecolor=SURF, sharex=True)
    panels = [(ax[0][0], "isup", "Current drawn from the bulk capacitors, A"), (ax[0][1], "rail", "The driver's clamp rail against its ground, V"),
              (ax[1][0], "gnd", "The expander's ground against the controller's, V"), (ax[1][1], "supply", "The 5 V across the expander, V")]
    for a, key, title in panels:
        a.set_facecolor(SURF); a.grid(color=GRID, lw=0.8); a.tick_params(colors=SEC, length=0); [sp.set_visible(False) for sp in a.spines.values()]
        for lab, w, col in runs: a.plot(w["t"] * 1e9, w[key], color=col, lw=2, label=lab)
        a.set_title(title, loc="left", color=INK, fontsize=11); a.legend(fontsize=9, frameon=False)
    ax[0][0].set_xlim(0, 200)
    for a in ax[1]: a.set_xlabel("nanoseconds (the driver starts to switch on at 20)", color=SEC)
    fig.suptitle("Six coils at 40 mA switched back on: the pulse as the circuit produces it (switch-on in 20 ns and the diode's reverse recovery are assumed)", x=0.01, ha="left", color=INK, fontsize=11.5)
    plt.tight_layout(rect=(0, 0, 1, 0.95)); plt.savefig(os.path.join(HERE, "journal", "sim-pulse-from-driver.png"), dpi=95, facecolor=SURF)
    w = run(6, 0.040, 1e-12, TSW)   # leave the case without reverse recovery as the circuit file
    s0 = summary(w); dur = np.ptp(w["t"][w["rail"] < 4.45]) * 1e9
    print("\nno reverse recovery, six coils at 40 mA: the clamp rail is below half its rest value for %.0f ns" % dur)
