"""Extract, from the captures of the driver output (yellow probe on U5 pin 17), the averaged curves
that the slow circuit model is fitted to. Writes sim/measured.json.

usage: sim_extract.py            (run from the probe folder)

Curves, all averages over the trials found in one capture:
  off_5ms, off_0.1ms   output minus its rest level after a switch-off that is not followed by a switch-on
                       (six coils), i.e. the drop across the conducting clamp diode, against time
  off3_5ms, off3_0.1ms the same with three coils, kept as a check
  on_6, on_3, on_1     the output's on-level after a switch-on from rest, against time
Times are in seconds from the edge, voltages in volts at the probe tip."""
import sys, os, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capio

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZERO = json.load(open(os.path.join(HERE, "tools", "scope_zero.json")))["500mV"]["ch1_zero"]
U = 16  # samples per microsecond
VOLTS_PER_COUNT = 25.0 / 128  # 500 mV range with a x10 probe


def volts(name):
    a = capio.load(os.path.join(HERE, "captures", name))
    return (a[0::2].astype(np.float32) - ZERO) * VOLTS_PER_COUNT


def bins(seg, pre, times_us, width_us):
    """Mean of seg over width_us starting at each time (microseconds after the edge at index pre)."""
    return [float(seg[pre + int(t * U) : pre + int((t + width_us) * U)].mean()) for t in times_us]


out = {}
# Switch-off, left off: the output rises through 5 V after having been low.
t_off = [50, 100, 150, 200, 300, 400] + list(range(500, 6001, 100))
for key, name in (("off_5ms", "cap6_7E_5000"), ("off_0.1ms", "cap6_7E_100"), ("off3_5ms", "cap6_0E_5000"), ("off3_0.1ms", "cap6_0E_100")):
    v = volts(name)
    hi = v > 5
    up = np.flatnonzero(~hi[:-1] & hi[1:])
    up = [u for u in up if u > 300 * U and v[u - 60 * U : u - 4 * U].max() < 3 and u + 12000 * U < len(v)]
    seg = np.mean([v[u - 200 * U : u + 12000 * U] for u in up], axis=0)
    rest = float(seg[-3000 * U :].mean())
    out[key] = dict(t=[t * 1e-6 for t in t_off], v=[x - rest for x in bins(seg, 200 * U, t_off, 50)], rest=rest, events=len(up))
# Switch-on from rest: the output falls through 5 V after at least 20 ms high, and stays low about 5 ms.
t_on = [300, 400, 500, 600, 800, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 3500, 4000, 4500]
for key, name in (("on_6", "cap5_7E"), ("on_3", "cap5_0E"), ("on_1", "cap5_02")):
    v = volts(name)
    lo = v < 5
    fall = np.flatnonzero(~lo[:-1] & lo[1:])
    cold = [f for f in fall if f > 20000 * U and v[f - 20000 * U : f - 100].min() > 5 and f + 4800 * U < len(v) and v[f + 200 : f + 4800 * U].max() < 5]
    seg = np.mean([v[f - 100 * U : f + 5000 * U] for f in cold], axis=0)
    out[key] = dict(t=[t * 1e-6 for t in t_on], v=bins(seg, 100 * U, t_on, 100), events=len(cold))
json.dump(out, open(os.path.join(HERE, "sim", "measured.json"), "w"), indent=1)
for k, d in out.items():
    print("%-11s %2d events, %d points, first %.3f V, last %.3f V" % (k, d["events"], len(d["t"]), d["v"][0], d["v"][-1]))
