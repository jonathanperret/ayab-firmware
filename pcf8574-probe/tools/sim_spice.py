"""Write the fitted slow model as an ngspice circuit, run it, and compare it with the measurements.

usage: sim_spice.py            (run from the probe folder, after sim_fit.py)
Reads sim/fit.json (the "two inductances" result). Writes sim/coil_driver.cir, a circuit of one coil
and its driver channel that can be run on its own with "ngspice -b sim/coil_driver.cir", and
journal/sim-slow-model-spice.png. Prints how far ngspice's curves are from the measured points
and from the script's own solver."""
import os, json, subprocess
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = json.load(open(os.path.join(HERE, "sim", "fit.json")))["two inductances"]
M = json.load(open(os.path.join(HERE, "sim", "measured.json")))
N_COILS = 6
TAU_PROBE = 135e-6

NETLIST = """* One solenoid coil of the AYAB interface board and its driver channel: slow model
* Fitted to scope captures of the driver output (journal entries 177-179, 204). Not a model of
* anything faster than about 20 microseconds: no capacitances, no diode recovery, no wiring inductance.
*
* Run:  ngspice -b coil_driver.cir      (writes coil_driver_<case>.txt: time, output volts, coil amps)
* The two cases are the two captures the model was fitted to: coils on for 5.26 ms and for 0.34 ms.

.param n_coils = {n}          ; coils switched together (they share the supply wiring)
.param t_on = 5.26m           ; how long the driver is on (overridden below for the second case)

Vsup  sup 0  {VS}             ; supply at the coils with nothing on
Rwire sup a  {{ {RW} * n_coils }} ; shared supply wiring, per coil when n_coils switch together
Rcoil a   b  {R}              ; coil resistance (measured)
L1    b   c  {L1}             ; inductance the coil shows at first
L2    c   out {L2}            ; extra inductance once the field has entered the iron ...
Riron c   out {RI}            ; ... and the resistance standing for currents induced in the iron
Dclamp out sup DCLAMP         ; the driver's clamp diode, back to the supply
.model DCLAMP D(IS={IS} N={N} RS={RS})

* Driver channel: a switch, then its fixed drop and its resistance to ground
S1    out d1 ctl 0 SWDRV
Vdrop d1  d2 {V0}
Ron   d2  0  {RON}
.model SWDRV SW(RON=0.01 ROFF=1G VT=0.5 VH=0.1)
Vctl  ctl 0  PULSE(0 1 1m 1u 1u {{t_on}} 1)   ; on at 1 ms, off t_on later

.control
set wr_singlescale
foreach ton 5.26m 0.34m
  alterparam t_on = $ton
  reset
  tran 2u 13m 0 2u
  wrdata coil_driver_{{$ton}}.txt v(out) i(L1)
end
.endc
.end
""".format(n=N_COILS, VS=F["VS"], RW=F["RW"], R=F["R"], L1=F["L1"], L2=F["L2"], RI=F["RI"], IS=F["IS"], N=F["N"], RS=F["RS"], V0=F["V0"], RON=F["RON"])

sim = os.path.join(HERE, "sim")
open(os.path.join(sim, "coil_driver.cir"), "w").write(NETLIST)
run = subprocess.run(["ngspice", "-b", "coil_driver.cir"], cwd=sim, capture_output=True, text=True)
if run.returncode != 0:
    print(run.stdout[-1500:], run.stderr[-1500:]); raise SystemExit("ngspice failed")

SEC, GRID, SURF, INK = "#52514e", "#e1e0d9", "#fcfcfb", "#0b0b0b"
fig, ax = plt.subplots(1, 2, figsize=(13, 4.8), facecolor=SURF)
for a in ax:
    a.set_facecolor(SURF); a.grid(color=GRID, lw=0.8); a.tick_params(colors=SEC, length=0); [s.set_visible(False) for s in a.spines.values()]
for ton, key, col, lab in (("5.26m", "off_5ms", "#2a78d6", "on 5.26 ms"), ("0.34m", "off_0.1ms", "#eb6834", "on 0.34 ms")):
    d = np.loadtxt(os.path.join(sim, "coil_driver_%s.txt" % ton)); t, vout, il = d[:, 0], d[:, 1], d[:, 2]
    t_off = 1e-3 + float(ton[:-1]) * 1e-3 + 2e-6      # the switch-off, in the simulation's time
    tm = np.array(M[key]["t"]); vm = np.array(M[key]["v"])
    v_spice = np.interp(t_off + tm, t, vout) - F["VS"] + F["PA"] * np.exp(-tm / TAU_PROBE)
    use = tm >= 0.1e-3
    print("%s: ngspice against the measured points: rms %.1f mV, worst %.0f mV; coil current at switch-off %.1f mA" % (lab, np.sqrt(np.mean((v_spice[use] - vm[use]) ** 2)) * 1e3, np.max(np.abs(v_spice[use] - vm[use])) * 1e3, np.interp(t_off - 4e-6, t, il) * 1e3))
    ax[0].plot(tm * 1e3, vm, "o", ms=4, color=col, label="measured, six coils, %s" % lab)
    ax[0].plot(tm * 1e3, v_spice, "-", color=col, lw=2, label="ngspice, %s" % lab)
    ax[1].plot((t - 1e-3) * 1e3, il * 1e3, "-", color=col, lw=2, label="ngspice, %s" % lab)
ax[0].set_title("After a switch-off: output above its rest level", loc="left", color=INK, fontsize=11); ax[0].set_xlabel("ms after the switch-off", color=SEC); ax[0].set_ylabel("V", color=SEC); ax[0].legend(fontsize=8, frameon=False)
ax[1].set_title("Coil current in the same two runs", loc="left", color=INK, fontsize=11); ax[1].set_xlabel("ms after the switch-on", color=SEC); ax[1].set_ylabel("mA", color=SEC); ax[1].set_xlim(-0.5, 8); ax[1].legend(fontsize=8, frameon=False)
fig.suptitle("The fitted model as an ngspice circuit (sim/coil_driver.cir), against the captures", x=0.01, ha="left", color=INK, fontsize=12)
plt.tight_layout(rect=(0, 0, 1, 0.93)); plt.savefig(os.path.join(HERE, "journal", "sim-slow-model-spice.png"), dpi=95, facecolor=SURF)
