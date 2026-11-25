"""What-if model of the fast event: a short current pulse through the driver, and what it does at the
expander, given the board's track lengths. NOT a fitted model: the pulse is assumed, the track
inductances are estimated from the layout, and couplings between tracks are left out.

usage: sim_fast.py            (run from the probe folder)
Writes sim/fast_whatif.cir (ngspice), journal/sim-fast-whatif.png, and prints a table for several
assumed pulses.

The circuit (lengths from the layout file, see the journal):
  bulk capacitors by the jack -- 9 V track (100 mm) -- driver clamp pin
  driver ground pin -- ground track (86 mm) -- controller's ground pad -- ground bus (128 mm) -- capacitors
  the pulse: a current from the driver's clamp pin to its ground pin (clamp diodes caught conducting
  when the outputs switch on)
  expander: its ground pin hangs from the driver's ground pin through 24 mm of track to C6 and 10 mm more;
  its supply pin is fed from the controller's 5 V through 132 mm to C6's tap and 76 mm more
  two bus lines from the controller to the expander (100 mm): one pulled high by 5 kohm at the
  controller, one held low by the controller; each expander pin has 10 pF and protection diodes to
  the expander's own supply and ground
Everything is referred to the controller's ground."""
import os, math, subprocess
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.join(HERE, "sim")


def track_nH(length_mm, width_mil):
    """Inductance of a straight track on its own (no return path nearby), in nanohenries."""
    l = length_mm * 1e-3; w = width_mil * 25.4e-6 + 35e-6
    return 2e-7 * l * (math.log(2 * l / w) + 0.5 + 0.2235 * w / l) * 1e9


TRACKS = dict(  # name: (length mm, width mil, what it is)
    L9=(100, 100, "9 V, capacitors to driver"),
    LG1=(86, 50, "ground, driver to controller pad"),
    LGB=(128, 100, "ground bus, controller pad to capacitors"),
    LB1=(24, 30, "ground, driver to C6"),
    LB2=(10, 25, "ground, C6 to expander"),
    L5F=(132, 25, "5 V, controller to C6's tap"),
    L5B=(76, 25, "5 V, C6 to expander supply pin"),
    LBUS=(100, 15, "one bus line, controller to expander"),
)
LVAL = {k: track_nH(v[0], v[1]) for k, v in TRACKS.items()}

NETLIST = """* What-if: a short current pulse through the driver, seen at the expander. Assumptions throughout.
* Reference (node 0) is the controller's ground pad.
* Each track is an inductance with 150 ohm across it as a stand-in for its losses (unknown).
.param ipk = 0.3      ; peak of the assumed pulse, amperes
.param tr = 20n       ; its rise time; it falls in the same time

Vbulk capp capn 8.9
LGB capn 0 {LGB:.1f}n
RdLGB capn 0 150
L9 capp com {L9:.1f}n
RdL9 capp com 150
Ipulse com j PULSE(0 {{ipk}} 20n {{tr}} {{tr}} 1p 1)   ; a triangle: up in tr, down in tr
LG1 j 0 {LG1:.1f}n
RdLG1 j 0 150

* expander's ground branch, with C6
LB1 j c6n {LB1:.1f}n
RdLB1 j c6n 150
LB2 c6n vss {LB2:.1f}n
RdLB2 c6n vss 150
* 5 V from the controller
V5 n5 0 5
L5F n5 c6p {L5F:.1f}n
RdL5F n5 c6p 150
LC6 c6p c6a 1n
RC6 c6a c6b 20m
C6 c6b c6n 1u
L5B c6p vdd {L5B:.1f}n
RdL5B c6p vdd 150
* the expander between its supply and ground pins
Cchip vdd vss 100p
Rchip vdd vss 5k

* a bus line held high by its pull-up at the controller
Rpu n5 hc 5k
Chc hc 0 10p
LBH hc hu {LBUS:.1f}n
RdLBH hc hu 150
Chu hu vss 10p
Dhl vss hu DESD
Dhh hu vdd DESD
* a bus line held low by the controller
Rlo lc 0 25
LBL lc lu {LBUS:.1f}n
RdLBL lc lu 150
Clu lu vss 10p
Dll vss lu DESD
Dlh lu vdd DESD
.model DESD D(IS=1e-12 N=1 RS=5 CJO=3p)

.control
set wr_singlescale
save all @dhl[id] @dhh[id] @dll[id] @dlh[id]
tran 0.1n 300n
wrdata fast_whatif.txt v(com,j) v(vss) v(vdd,vss) v(hu,vss) v(lu,vss) @dhl[id] @dhh[id] @dll[id] @dlh[id] v(j)
.endc
.end
"""


def run(ipk, tr):
    net = NETLIST.format(**LVAL).replace(".param ipk = 0.3 ", ".param ipk = %g " % ipk).replace(".param tr = 20n ", ".param tr = %gn " % (tr * 1e9))
    open(os.path.join(SIM, "fast_whatif.cir"), "w").write(net)
    r = subprocess.run(["ngspice", "-b", "fast_whatif.cir"], cwd=SIM, capture_output=True, text=True)
    if not os.path.exists(os.path.join(SIM, "fast_whatif.txt")): raise SystemExit(r.stdout[-2000:] + r.stderr[-2000:])
    d = np.loadtxt(os.path.join(SIM, "fast_whatif.txt"))
    names = ["t", "rail", "gnd", "supply", "high", "low", "i_hl", "i_hh", "i_ll", "i_lh", "j"]
    return {n: d[:, k] for k, n in enumerate(names)}


if __name__ == "__main__":
    print("estimated track inductances (each track taken on its own):")
    for k, (l, w, what) in TRACKS.items(): print("  %-5s %5.0f nH   %3d mm x %3d mil   %s" % (k, LVAL[k], l, w, what))
    cases = [(0.3, 20e-9), (0.15, 10e-9), (0.6, 40e-9), (0.1, 20e-9), (1.0, 20e-9)]
    print("\nassumed pulse       | clamp rail at driver | expander ground vs  | expander supply    | bus line held high   | bus line held low")
    print("peak, rise          | lowest (rest 8.9 V)  | controller ground   | pin 16 - pin 8     | vs expander ground   | vs expander ground     current forced into the pins' protection diodes")
    results = {}
    for ipk, tr in cases:
        w = run(ipk, tr); results[(ipk, tr)] = w
        inj = max(np.abs(w["i_hl"]).max(), np.abs(w["i_hh"]).max(), np.abs(w["i_ll"]).max(), np.abs(w["i_lh"]).max()) * 1e3
        print("%.2f A, %2.0f ns (%.0f A/us) | %6.1f V             | %+.1f / %+.1f V       | %.2f .. %.2f V     | %.1f .. %.1f V        | %.1f .. %.1f V          up to %.0f mA" % (
            ipk, tr * 1e9, ipk / tr * 1e-6, w["rail"].min(), w["gnd"].max(), w["gnd"].min(), w["supply"].min(), w["supply"].max(), w["high"].min(), w["high"].max(), w["low"].min(), w["low"].max(), inj))
    w = run(*cases[0])   # leave the base case as the circuit file and draw it
    SEC, GRID, SURF, INK = "#52514e", "#e1e0d9", "#fcfcfb", "#0b0b0b"; C = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
    fig, ax = plt.subplots(2, 2, figsize=(13, 8), facecolor=SURF, sharex=True)
    t = w["t"] * 1e9
    panels = [(ax[0][0], [("rail", "clamp rail at the driver, against the driver's ground", C[0])], "The driver's clamp rail (rest: 8.9 V)"),
              (ax[0][1], [("gnd", "expander's ground against the controller's ground", C[1])], "The expander's ground (rest: 0 V)"),
              (ax[1][0], [("supply", "expander's supply pin against its ground pin", C[2])], "The 5 V across the expander (rest: 5 V)"),
              (ax[1][1], [("high", "a bus line held high by its pull-up", C[3]), ("low", "a bus line held low by the controller", C[1])], "Bus lines at the expander, against the expander's ground")]
    for a, traces, title in panels:
        a.set_facecolor(SURF); a.grid(color=GRID, lw=0.8); a.tick_params(colors=SEC, length=0); [s.set_visible(False) for s in a.spines.values()]
        for key, lab, col in traces: a.plot(t, w[key], color=col, lw=2, label=lab)
        a.set_title(title, loc="left", color=INK, fontsize=11); a.set_ylabel("V", color=SEC)
        if len(traces) > 1: a.legend(fontsize=9, frameon=False)
    if True:
        a = ax[1][0]; lo, hi = w["supply"].min(), w["supply"].max(); pad = max(0.25, (hi - lo) * 0.3); a.set_ylim(min(4.5, lo - pad), max(5.5, hi + pad))
    for a in ax[1]: a.set_xlabel("nanoseconds", color=SEC)
    fig.suptitle("What-if: an assumed pulse of 0.3 A rising in 20 ns through the driver, with track inductances estimated from the layout (not a measurement)", x=0.01, ha="left", color=INK, fontsize=11.5)
    plt.tight_layout(rect=(0, 0, 1, 0.95)); plt.savefig(os.path.join(HERE, "journal", "sim-fast-whatif.png"), dpi=95, facecolor=SURF)
