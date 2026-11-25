"""Fit the slow model of one coil and its driver channel to the measured curves (sim/measured.json).

usage: sim_fit.py            (run from the probe folder)
Writes sim/fit.json and journal/sim-slow-model-fit.png at the end. While it runs it rewrites
sim/live/fit.png and sim/live/progress.json after every generation of the search, so that
sim_watch.py can show the fit as it goes.

The model, per coil:
  supply -- shared wiring (RW per coil switched) -- R -- L1 -- [ L2 in parallel with RI ] -- driver output
  R   coil resistance, fixed at 150 ohm (measured by the user)
  L1  the inductance the coil shows at first
  L2  extra inductance that appears once the field has entered the iron; RI stands for the iron
      (currents induced in it), so the change-over time is L2 / RI
  "One inductance" is the same model without L2 and RI.
Driver channel:
  on   the output sits at V0 + RON * i above ground
  off  the coil current flows through the clamp diode to the supply; the diode's drop is
       N * 25.85 mV * ln(1 + i / IS) + RS * i
The yellow probe overshoots a little after a step; that is modelled as PA * exp(-t / 135 us) added
to the reading after a switch-off, with PA fitted.

Fitted against: the diode drop after a switch-off of six coils that had been on 5.26 ms and
0.34 ms, and the on-level's rise after a switch-on from rest. The three-coil curves are only
drawn for comparison."""
import os, json, time
import numpy as np
from scipy.optimize import least_squares, differential_evolution
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = json.load(open(os.path.join(HERE, "sim", "measured.json")))
LIVE = os.path.join(HERE, "sim", "live")
R = 150.0  # coil resistance, ohm
RW = 0.65  # shared supply wiring, ohm (entry 189)
VS = 8.94  # supply at the coils with nothing on, volts (rest level of the output)
VT = 0.02585  # thermal voltage
TAU_PROBE = 135e-6  # tail of the yellow probe's overshoot, seconds (entry 175)
# How long the coils were really on, measured on the captures: the requested 5 ms and 0.1 ms plus
# the time the switch-off write takes to reach its ninth clock.
ON_LONG, ON_SHORT = 5.26e-3, 0.34e-3
SINGLE = False  # True while fitting the one-inductance variant


def diode(i, IS, N, RS):
    """Clamp diode drop in volts at current i (amperes; negative currents count as zero)."""
    i = np.maximum(i, 0.0)
    return N * VT * np.log1p(i / IS) + RS * i


DT = 4e-6  # time step of the integration, seconds


def _run(p, n_coils, y, t_end, t_eval, drive, v0, ron):
    """Step the coil model from state y = [i, i2] to t_end; return the current at t_eval and the end state.

    drive=True: driver on (supply less the driver's own drop across the coil).
    drive=False: driver off (the coil discharges through the clamp diode).
    Backward Euler with a fixed step: the diode makes the equations stiff at small currents, and an
    implicit step stays stable there. The step for i is solved by Newton's method."""
    L1, L2, RI, IS, N, RS = p[:6]
    rser = R + RW * n_coils
    if SINGLE:
        RI = 0.0
    k2 = 0.0 if SINGLE else DT * RI / L2
    i, i2 = y
    steps = int(round(t_end / DT))
    out = np.empty(len(t_eval))
    idx = np.minimum(np.round(np.asarray(t_eval) / DT).astype(int), steps)
    order = np.argsort(idx)
    nxt = 0
    a = L1 / DT
    for n in range(steps + 1):
        while nxt < len(order) and idx[order[nxt]] == n:
            out[order[nxt]] = i
            nxt += 1
        if n == steps:
            break
        # unknown: the new i. The new i2 follows from it: i2' = (i2 + k2 * i') / (1 + k2).
        c2 = k2 / (1.0 + k2)
        base2 = i2 / (1.0 + k2)
        x = i
        for _ in range(4):
            xi = x if x > 0.0 else 0.0
            i2n = base2 + c2 * x
            if drive:
                f = a * (x - i) - (VS - v0) + (ron + rser) * x + RI * (x - i2n)
                df = a + ron + rser + RI * (1.0 - c2)
            else:
                vd = N * VT * np.log1p(xi / IS) + RS * xi
                dvd = (N * VT / (xi + IS) + RS) if x > 0.0 else 0.0
                f = a * (x - i) + vd + rser * xi + RI * (x - i2n)
                df = a + dvd + (rser if x > 0.0 else 0.0) + RI * (1.0 - c2)
            x -= f / df
        if not drive and x < 0.0:
            x = 0.0  # the diode blocks: no reverse current
        i2 = base2 + c2 * x
        i = x
    return out, [i, i2]


def simulate(p, on_time, n_coils, t_off, t_on=None, v0=0.72, ron=3.0):
    """Run one coil: on from rest for on_time, then off.

    Returns (current at the times t_on during the on phase, or None; diode drop at the times t_off
    after the switch-off; current at those times; the state [i, i2] at the switch-off)."""
    i_on = None
    if t_on is not None:
        i_on, _ = _run(p, n_coils, [0.0, 0.0], max(t_on), t_on, True, v0, ron)
    _, y0 = _run(p, n_coils, [0.0, 0.0], on_time, [on_time], True, v0, ron)
    i_off, _ = _run(p, n_coils, y0, max(t_off), t_off, False, v0, ron)
    i_off = np.maximum(i_off, 0.0)
    return i_on, diode(i_off, *p[3:6]), i_off, np.array(y0)


def unpack(x):
    """Search variables (logs of L1, L2, RI, IS; then N, RS, PA) to plain values."""
    L1, L2, RI, IS = np.exp(x[:4])
    return [L1, L2, RI, IS, x[4], x[5], x[6]]


def on_level_fit(i_on, v_meas):
    """Best V0 and RON for 'on-level = V0 + RON * i', and the residuals."""
    A = np.vstack([np.ones_like(i_on), i_on]).T
    coef, *_ = np.linalg.lstsq(A, v_meas, rcond=None)
    return coef, A @ coef - v_meas


OFF_CASES = (("off_5ms", ON_LONG), ("off_0.1ms", ON_SHORT))
N_RES = sum(int(np.sum(np.array(M[k]["t"]) >= 0.1e-3)) for k, _ in OFF_CASES) + len(M["on_6"]["t"])


def _residuals(x):
    p = unpack(x)
    res = []
    for key, on_time in OFF_CASES:
        t = np.array(M[key]["t"]); v = np.array(M[key]["v"]); use = t >= 0.1e-3
        _, vd, _, _ = simulate(p, on_time, 6, t[use])
        res.append(vd + p[6] * np.exp(-t[use] / TAU_PROBE) - v[use])
    t = np.array(M["on_6"]["t"]); v = np.array(M["on_6"]["v"])
    i_on, _, _, _ = simulate(p, ON_LONG, 6, [1e-4], t_on=t)
    _, r_on = on_level_fit(i_on, v)
    res.append(5.0 * r_on)  # the on-level is known to a few millivolts: weigh it more
    return np.concatenate(res)


def residuals(x):
    """Residuals against the three fitted curves; a large constant if the model fails to run."""
    try:
        r = _residuals(x)
    except Exception:
        return np.full(N_RES, 10.0)
    return r if (len(r) == N_RES and np.all(np.isfinite(r))) else np.full(N_RES, 10.0)


def describe(p):
    two = "" if SINGLE else ", then +%.0f mH through %.0f ohm (change-over %.2f ms)" % (p[1] * 1e3, p[2], p[1] / p[2] * 1e3)
    return "inductance %.0f mH%s; diode %.2f V at 50 mA, %.2f V at 5 mA" % (p[0] * 1e3, two, diode(0.05, *p[3:6]), diode(0.005, *p[3:6]))


SEC, GRID, SURF, INK = "#52514e", "#e1e0d9", "#fcfcfb", "#0b0b0b"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"


REFERENCE = None  # (parameters, single?) of a finished fit to draw dashed for comparison


def picture(p, path, heading):
    """Measured points against the model with parameters p (the best so far), in three panels.

    If REFERENCE is set, that earlier fit is drawn as dashed grey lines for comparison."""
    global SINGLE
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.0), facecolor=SURF)
    for a in ax:
        a.set_facecolor(SURF); a.grid(color=GRID, lw=0.8); a.tick_params(colors=SEC, length=0)
        [s.set_visible(False) for s in a.spines.values()]
    for key, key3, on_time, col, lab in (("off_5ms", "off3_5ms", ON_LONG, C1, "on 5.26 ms"), ("off_0.1ms", "off3_0.1ms", ON_SHORT, C2, "on 0.34 ms")):
        t = np.array(M[key]["t"]); _, vd, _, _ = simulate(p, on_time, 6, t)
        ax[0].plot(t * 1e3, M[key]["v"], "o", ms=4, color=col, label="measured, six coils, %s" % lab)
        ax[0].plot(t * 1e3, M[key3]["v"], "x", ms=4, color=col, alpha=0.6, label="measured, three coils, %s" % lab)
        ax[0].plot(t * 1e3, vd + p[6] * np.exp(-t / TAU_PROBE), "-", color=col, lw=2.2, label="model, best so far, %s" % lab)
        if REFERENCE is not None:
            keep = SINGLE; SINGLE = REFERENCE[1]; q = REFERENCE[0]
            _, vr, _, _ = simulate(q, on_time, 6, t); SINGLE = keep
            ax[0].plot(t * 1e3, vr + q[6] * np.exp(-t / TAU_PROBE), "--", color="#898781", lw=1.3, label="one inductance, its best fit" if key == "off_5ms" else None)
    ax[0].set_title("After a switch-off: output above its rest level (clamp diode drop)", loc="left", color=INK, fontsize=11)
    ax[0].set_xlabel("ms after the switch-off", color=SEC); ax[0].set_ylabel("V", color=SEC); ax[0].set_ylim(-0.05, 1.3); ax[0].legend(fontsize=8, frameon=False)
    t = np.array(M["on_6"]["t"]); tf = np.linspace(1e-5, 5e-3, 200)
    i_m, _, _, _ = simulate(p, ON_LONG, 6, [1e-4], t_on=t); (v0, ron), _ = on_level_fit(i_m, np.array(M["on_6"]["v"]))
    i_f, _, _, _ = simulate(p, ON_LONG, 6, [1e-4], t_on=tf)
    ax[1].plot(t * 1e3, M["on_6"]["v"], "o", ms=4, color=C1, label="measured, six coils")
    ax[1].plot(t * 1e3, M["on_3"]["v"], "x", ms=4, color=C2, label="measured, three coils")
    ax[1].plot(t * 1e3, M["on_1"]["v"], "+", ms=5, color=C3, label="measured, one coil")
    ax[1].plot(tf * 1e3, v0 + ron * i_f, "-", color=C1, lw=2.2, label="model, best so far, six coils")
    if REFERENCE is not None:
        keep = SINGLE; SINGLE = REFERENCE[1]; q = REFERENCE[0]
        i_rm, _, _, _ = simulate(q, ON_LONG, 6, [1e-4], t_on=t); (rv0, rron), _ = on_level_fit(i_rm, np.array(M["on_6"]["v"]))
        i_rf, _, _, _ = simulate(q, ON_LONG, 6, [1e-4], t_on=tf); SINGLE = keep
        ax[1].plot(tf * 1e3, rv0 + rron * i_rf, "--", color="#898781", lw=1.3, label="one inductance, its best fit")
        ax[2].plot(tf * 1e3, i_rf * 1e3, "--", color="#898781", lw=1.3, label="one inductance, its best fit")
    ax[1].set_title("After a switch-on from rest: the output's on-level", loc="left", color=INK, fontsize=11)
    ax[1].set_xlabel("ms after the switch-on", color=SEC); ax[1].set_ylabel("V", color=SEC); ax[1].set_ylim(0.7, 0.92); ax[1].legend(fontsize=8, frameon=False)
    ax[2].plot(tf * 1e3, i_f * 1e3, "-", color=C3, lw=1.8, label="switched on from rest")
    tt = np.arange(0.0, 6e-3, 2e-5) + 1e-6
    for (label, on_time), col in zip((("5.26 ms on", ON_LONG), ("0.34 ms on", ON_SHORT)), (C1, C2)):
        _, _, io, _ = simulate(p, on_time, 6, tt)
        ax[2].plot(tt * 1e3, io * 1e3, "-", color=col, lw=1.8, label="after switch-off, %s" % label)
    ax[2].set_title("Coil current according to the model", loc="left", color=INK, fontsize=11)
    ax[2].set_xlabel("ms after the edge", color=SEC); ax[2].set_ylabel("mA", color=SEC); ax[2].set_ylim(0, 56); ax[2].legend(fontsize=8, frameon=False)
    fig.suptitle(heading, x=0.01, ha="left", color=INK, fontsize=12)
    plt.tight_layout(rect=(0, 0, 1, 0.93)); tmp = path + ".tmp.png"; plt.savefig(tmp, dpi=90, facecolor=SURF); plt.close(fig); os.replace(tmp, path)
    return float(v0), float(ron)


# The seven search parameters as shown on the watch page: label, number format, scale, logarithmic?
AXES = [("inductance at first, mH", "%.0f", 1e3, True), ("extra inductance later, mH", "%.0f", 1e3, True), ("resistance standing for the iron, ohm", "%.0f", 1.0, True),
        ("diode saturation current, A", "%.1e", 1.0, True), ("diode steepness factor N", "%.2f", 1.0, False), ("diode series resistance, ohm", "%.2f", 1.0, False),
        ("probe overshoot, V", "%.2f", 1.0, False)]
lo = np.array([np.log(0.02), np.log(0.005), np.log(5.0), np.log(1e-16), 0.8, 0.0, 0.0])
hi = np.array([np.log(0.6), np.log(1.0), np.log(5000.0), np.log(1e-5), 4.0, 6.0, 1.5])
history = []
T0 = time.time()


def best_fit(name, single, generations=60):
    """Global search (differential evolution), then a local polish. Reports progress to sim/live."""
    global SINGLE
    SINGLE = single
    state = dict(gen=0, evals=0, best=None, best_x=None, drawn=0.0, trail=[])

    def axes():
        """For the watch page: where the settings tried lie within each parameter's search range.

        Positions are fractions of the range (0 = lower bound, 1 = upper bound); for the first four
        parameters the range is logarithmic."""
        recent = state["trail"][-420:]
        out = []
        for k, (label, fmt, scale, logarithmic) in enumerate(AXES):
            used = not (single and k in (1, 2))
            text = lambda v: fmt % ((np.exp(v) if logarithmic else v) * scale)
            pos = lambda v: float((v - lo[k]) / (hi[k] - lo[k]))
            out.append(dict(name=label, used=used, lo=text(lo[k]), hi=text(hi[k]), best=pos(state["best_x"][k]), best_text=text(state["best_x"][k]),
                            pts=[[round(pos(x[k]), 4), round(r, 1)] for x, r in recent]))
        return out

    def show(note):
        """Write the progress file and redraw the picture with the best setting found so far."""
        p = unpack(state["best_x"]); rms = float(np.sqrt(state["best"] / N_RES))
        entry = dict(model=name, generation=state["gen"], of=generations, rms_mV=rms * 1e3, seconds=time.time() - T0, evaluations=state["evals"], text=describe(p))
        json.dump(dict(running=True, history=history + [entry], axes=axes(), per_step=10 * len(lo)), open(os.path.join(LIVE, "progress.json"), "w"))
        picture(p, os.path.join(LIVE, "fit.png"), "%s, %s: rms error %.1f mV — %s" % (name, note, rms * 1e3, describe(p)))
        state["drawn"] = time.time()
        return entry

    def cost(x):
        state["evals"] += 1
        c = float(np.sum(residuals(x) ** 2))
        state["trail"].append((np.array(x), float(np.sqrt(c / N_RES)) * 1e3))
        if state["best"] is None or c < state["best"]:
            state["best"], state["best_x"] = c, np.array(x)
        if time.time() - state["drawn"] > 1.0:  # about once a second, whatever the search is doing
            show("search step %d of %d, %d settings tried" % (state["gen"] + 1, generations, state["evals"]))
        return c

    def progress(xk, convergence=None):
        state["gen"] += 1
        entry = show("search step %d of %d done" % (state["gen"], generations))
        history.append(entry)
        print("%-16s step %2d/%d  rms %.1f mV  %s" % (name, state["gen"], generations, entry["rms_mV"], entry["text"]), flush=True)

    de = differential_evolution(cost, list(zip(lo, hi)), seed=1, popsize=10, maxiter=generations, tol=1e-7, polish=False, callback=progress)
    f = least_squares(residuals, de.x, bounds=(lo, hi), diff_step=1e-3)
    c = float(np.sum(f.fun**2))
    if c < state["best"]:
        state["best"], state["best_x"] = c, np.array(f.x)
    history.append(show("finished"))
    return f


os.makedirs(LIVE, exist_ok=True)
fits = {}
for name, single in (("one inductance", True), ("two inductances", False)):
    fits[name] = best_fit(name, single, generations=30 if single else 60)
    if single:
        REFERENCE = (unpack(fits[name].x), True)  # shown dashed while the second model is searched
summary = {}
for name, f in fits.items():
    SINGLE = name == "one inductance"
    p = unpack(f.x); rms = float(np.sqrt(np.mean(f.fun**2)))
    REFERENCE = None if SINGLE else (unpack(fits["one inductance"].x), True)
    v0, ron = picture(p, os.path.join(HERE, "journal", "sim-slow-model-fit-%s.png" % name.replace(" ", "-")), "%s: rms error %.1f mV — %s" % (name, rms * 1e3, describe(p)))
    tt = np.arange(0.0, 6e-3, 1e-5) + 1e-6; rows = {}
    for label, on_time in (("5.26 ms on", ON_LONG), ("0.34 ms on", ON_SHORT)):
        _, _, io, y0 = simulate(p, on_time, 6, tt)
        rows[label] = dict(at_switch_off_mA=float(y0[0] * 1e3), below_half_mA_after_ms=float(tt[np.argmax(io < 0.5e-3)] * 1e3),
                           mA_at_gap_ms={"%.1f" % (g * 1e3): float(io[np.argmin(np.abs(tt - g))] * 1e3) for g in (0.2e-3, 0.5e-3, 0.8e-3, 1.2e-3, 1.7e-3, 2.2e-3, 3.2e-3)})
    summary[name] = dict(rms_mV=rms * 1e3, R=R, RW=RW, VS=VS, L1=p[0], L2=None if SINGLE else p[1], RI=None if SINGLE else p[2], IS=p[3], N=p[4], RS=p[5], PA=p[6], V0=v0, RON=ron, currents=rows)
    print("\n%s: rms %.1f mV; %s; driver on %.3f V + %.1f ohm x current; probe overshoot %.2f V" % (name, rms * 1e3, describe(p), v0, ron, p[6]))
    for label, r in rows.items():
        print("   %s: %.1f mA at switch-off, below 0.5 mA after %.2f ms; mA at gaps (ms): %s" % (label, r["at_switch_off_mA"], r["below_half_mA_after_ms"], "  ".join("%s:%.1f" % kv for kv in r["mA_at_gap_ms"].items())))
json.dump(summary, open(os.path.join(HERE, "sim", "fit.json"), "w"), indent=1)
json.dump(dict(running=False, history=history), open(os.path.join(LIVE, "progress.json"), "w"))
