"""Draw the circuit of the fast what-if simulation (sim/fast_whatif.cir) as sim/fast_whatif.svg.

usage: sim_fast_schematic.py [pulse]       (run from the probe folder)
Without argument: the what-if circuit with an assumed pulse, to sim/fast_whatif.svg.
With "pulse": the joined circuit of sim_pulse.py (sim/pulse_from_driver.cir), in which the coils, the
clamp diodes and the driver's switch produce the pulse, to sim/pulse_from_driver.svg.
The inductance figures are taken from sim_fast.py, so the drawing follows the simulation."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_fast import LVAL, TRACKS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOINED = len(sys.argv) > 1 and sys.argv[1] == "pulse"
BX = 1320 if JOINED else 1220          # where the bulk capacitors are drawn
out = []
W = 'stroke="#2b2d33" stroke-width="2" fill="none"'
P = 'stroke="#2b2d33" stroke-width="2" fill="#fcfcfb"'


def wire(*pts):
    out.append('<path %s d="M%s"/>' % (W, " L".join("%g %g" % p for p in pts)))


def dot(x, y):
    out.append('<circle cx="%g" cy="%g" r="4" fill="#2b2d33"/>' % (x, y))


def text(x, y, s, cls="t", anchor="middle"):
    out.append('<text class="%s" x="%g" y="%g" text-anchor="%s">%s</text>' % (cls, x, y, anchor, s))


def ind_h(x1, x2, y, key, above=True):
    """A track inductance drawn horizontally between x1 and x2 at height y, with its name and value."""
    x1, x2 = min(x1, x2), max(x1, x2)
    a, b = (x1 + x2) / 2 - 50, (x1 + x2) / 2 + 50
    wire((x1, y), (a, y)); wire((b, y), (x2, y))
    out.append('<path %s d="M%g %g q12.5 -26 25 0 q12.5 -26 25 0 q12.5 -26 25 0 q12.5 -26 25 0"/>' % (W, a, y))
    l, w, what = TRACKS[key]
    text((a + b) / 2, y - 30 if above else y + 22, what, "s")
    text((a + b) / 2, y - 46 if above else y + 38, "%.0f nH (%d mm)" % (LVAL[key], l), "v")


def res_v(x, y1, y2, label, value):
    m = (y1 + y2) / 2
    wire((x, y1), (x, m - 28)); wire((x, m + 28), (x, y2))
    out.append('<rect %s x="%g" y="%g" width="24" height="56"/>' % (P, x - 12, m - 28))
    text(x + 20, m - 2, label, "s", "start"); text(x + 20, m + 14, value, "v", "start")


def source_v(x, y1, y2, label, value, arrow=False, left=False):
    m = (y1 + y2) / 2
    wire((x, y1), (x, m - 30)); wire((x, m + 30), (x, y2))
    out.append('<circle %s cx="%g" cy="%g" r="30"/>' % (P, x, m))
    if arrow:
        out.append('<path %s d="M%g %g V%g M%g %g l-7 -12 M%g %g l7 -12"/>' % (W, x, m - 16, m + 16, x, m + 16, x, m + 16))
    else:
        text(x, m - 6, "+", "t"); text(x, m + 16, "−", "t")
    if left:
        text(x - 40, m - 2, label, "s", "end"); text(x - 40, m + 14, value, "v", "end")
    else:
        text(x + 40, m - 2, label, "s", "start"); text(x + 40, m + 14, value, "v", "start")


# 5 V: controller -> C6's tap -> back to the expander's supply pin
source_v(140, 50, 560, "controller's 5 V", "5 V", left=True)
wire((140, 50), (240, 50)); ind_h(240, 760, 50, "L5F"); dot(240, 50)
wire((760, 50), (760, 110)); dot(760, 110)
ind_h(760, 520, 110, "L5B", above=False); wire((520, 110), (520, 150))
# C6 between the 5 V tap and the expander's ground branch
wire((760, 110), (760, 240)); wire((760, 262), (760, 400))
out.append('<path %s d="M736 240 H784 M736 262 H784"/>' % W)
text(724, 248, "C6, 1 µF", "s", "end"); text(724, 264, "(with 1 nH, 20 mΩ)", "s", "end")
# the expander
out.append('<rect %s x="460" y="150" width="120" height="180"/>' % P)
text(520, 232, "expander U3", "t"); text(520, 250, "100 pF, 5 kΩ", "s"); text(520, 266, "across its supply", "s")
text(520, 168, "supply pin", "s"); text(520, 322, "ground pin", "s")
wire((520, 330), (520, 400)); ind_h(520, 760, 400, "LB2", above=False); dot(760, 400)
ind_h(760, 1000, 400, "LB1", above=False); dot(1000, 400)
# the driver
if not JOINED:
    source_v(1000, 200, 400, "driver U5:", "assumed pulse", arrow=True)
    text(1040, 330, "0.3 A, up in 20 ns,", "s", "start"); text(1040, 346, "down in 20 ns", "s", "start")
    text(1000, 190, "clamp pin", "s"); text(1012, 420, "ground pin", "s", "start")
    ind_h(1000, BX, 200, "L9")
else:
    # clamp rail from the diodes (left) past the driver to the coils (right)
    wire((910, 200), (1100, 200)); dot(1000, 200); text(1000, 188, "clamp pin", "s")
    # output node
    wire((910, 300), (1100, 300)); dot(1000, 300); text(1008, 318, "outputs", "s", "start")
    # clamp diodes: from the outputs up to the clamp rail
    wire((910, 300), (910, 266)); wire((910, 234), (910, 200))
    out.append('<path %s d="M894 266 H926 L910 234 Z"/>' % P); out.append('<path %s d="M894 234 H926"/>' % W)
    text(990, 322, "clamp diodes,", "s", "end"); text(990, 338, "reverse recovery assumed", "v", "end")
    # the coils: a constant current from the 9 V side into the outputs
    out.append('<circle %s cx="1100" cy="250" r="26"/>' % P)
    out.append('<path %s d="M1100 236 V264 M1100 264 l-6 -11 M1100 264 l6 -11"/>' % W)
    wire((1100, 200), (1100, 224)); wire((1100, 276), (1100, 300))
    text(1134, 246, "the coils' current,", "s", "start"); text(1134, 262, "from the slow model", "v", "start")
    # the driver's outputs: a switch, then its fixed drop and resistance, down to the ground pin
    wire((1000, 300), (1000, 326)); out.append('<path %s d="M1000 326 L1016 352"/>' % W); out.append('<circle cx="1000" cy="326" r="3" fill="#2b2d33"/><circle cx="1000" cy="354" r="3" fill="#2b2d33"/>')
    wire((1000, 354), (1000, 400))
    text(1026, 344, "driver U5 switching on", "s", "start"); text(1026, 360, "in 20 ns (assumed), then", "v", "start"); text(1026, 376, "0.73 V and 3.1 Ω per output", "s", "start")
    text(1012, 420, "ground pin", "s", "start")
    wire((1100, 200), (1140, 200)); ind_h(1140, BX, 200, "L9")
source_v(BX, 200, 560, "bulk capacitors", "8.9 V")
# ground: driver -> controller's pad, then the bus to the capacitors
wire((1000, 400), (1000, 480)); ind_h(1000, 300, 480, "LG1", above=False); wire((300, 480), (300, 560)); dot(300, 560)
wire((140, 560), (300, 560)); ind_h(300, BX, 560, "LGB", above=False)
text(220, 584, "controller's ground pad", "s"); text(220, 600, "(the reference)", "s")
# the two bus lines
res_v(240, 50, 200, "pull-up", "5 kΩ"); ind_h(240, 460, 200, "LBUS"); dot(240, 200)
text(232, 222, "10 pF", "s", "end")
wire((240, 280), (240, 300)); res_v(240, 300, 560, "controller holding", "the line low, 25 Ω"); dot(240, 560)
ind_h(240, 460, 280, "LBUS", above=False)
text(452, 194, "pin", "s", "end"); text(452, 274, "pin", "s", "end")
text(470, 206, "held high", "s", "start"); text(470, 286, "held low", "s", "start")
text(650, 640, "Every pin of the expander that a bus line reaches has 10 pF and protection diodes to the expander's own supply and ground.", "s")
text(650, 660, "Each track is an inductance, estimated from its length and width; 150 Ω across each stands in for its losses. Coupling between tracks is not modelled.", "s")
if JOINED:
    text(650, 680, "Each output also has 30 pF to the driver's ground (assumed). The coils are a constant current because the event is too short for it to change.", "s")
    text(650, 710, "Circuit of the joined simulation (sim/pulse_from_driver.cir): the coils, clamp diodes and driver produce the pulse.", "t")
else:
    text(650, 690, "Circuit of the fast what-if simulation (sim/fast_whatif.cir). The pulse is assumed, not measured.", "t")

svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="-110 -20 %d %d" font-family="system-ui, Helvetica, Arial, sans-serif" font-size="13">
<style>.t{fill:#0b0b0b;font-weight:600}.s{fill:#52514e}.v{fill:#1c5cab;font-weight:600}</style>
<rect x="-110" y="-20" width="%d" height="%d" fill="#fcfcfb"/>
%s
</svg>
''' % (1610 if JOINED else 1510, 750 if JOINED else 730, 1610 if JOINED else 1510, 750 if JOINED else 730, "\n".join(out))
name = "pulse_from_driver.svg" if JOINED else "fast_whatif.svg"
open(os.path.join(HERE, "sim", name), "w").write(svg)
print("wrote sim/" + name)
