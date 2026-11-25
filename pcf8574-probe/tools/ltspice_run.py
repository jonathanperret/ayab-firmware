"""Run an LTspice schematic from the command line and read the results back.

usage: ltspice_run.py <file.asc> [name=value ...] [--traces "V(out),I(L1)"] [--plot out.png] [--keep]

What it does:
  1. turns the schematic into a netlist (asc_netlist.py; LTspice on a Mac cannot do that itself from
     the command line), applying any name=value given here to the schematic's .param lines;
  2. runs LTspice on that netlist in the background ("LTspice -b");
  3. reads the waveform file and the log, prints the log's measurements (.meas) and a summary of the
     requested traces, and draws them if --plot is given.
The netlist, log and waveform file go to a folder "build" next to the schematic.

As a module: run(asc, params={}) returns (waves, measurements, log_text), where waves is a list with
one dict per .step run, mapping trace names (lower case, e.g. "v(out)", "i(l1)", "time") to arrays.

Limits: flat schematics made of LTspice's library symbols; transient analyses; LTspice at the path
below."""
import sys, os, re, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import asc_netlist

LTSPICE = "/Applications/LTspice.app/Contents/MacOS/LTspice"


def text_of(raw_bytes):
    """LTspice writes its text files in UTF-16 on some versions and plain text on others."""
    if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff") or raw_bytes[1:2] == b"\x00":
        return raw_bytes.decode("utf-16-le", "replace").lstrip("﻿")
    return raw_bytes.decode("utf-8", "replace")


def with_params(netlist, params):
    """Set name=value in the netlist's .param lines; names not found there get a line of their own."""
    lines = netlist.split("\n")
    for name, value in params.items():
        pat = re.compile(r"(?i)\b(%s)\s*=\s*\S+" % re.escape(name)); done = False
        for k, line in enumerate(lines):
            if line.strip().lower().startswith(".param") and pat.search(line):
                lines[k] = pat.sub(lambda m: "%s=%s" % (m.group(1), value), line); done = True
        if not done:
            lines.insert(len(lines) - 3, ".param %s=%s" % (name, value))   # before .backanno / .end
    return "\n".join(lines)


def read_raw(path):
    """Read a transient .raw file. Returns one dict per .step run: trace name (lower case) -> array.

    Layout: a text header ending with the line "Binary:", then, for each point, the time as an 8-byte
    float followed by every other variable as a 4-byte float (8-byte if the header's flags say
    "double"). LTspice marks some time values by making them negative; the sign is dropped. With
    .step, the runs follow one another, each starting again from its first time."""
    data = open(path, "rb").read()
    for marker, enc in (("Binary:\n".encode("utf-16-le"), "utf-16-le"), (b"Binary:\n", "utf-8")):
        k = data.find(marker)
        if k >= 0:
            header = data[:k].decode(enc, "replace"); body = data[k + len(marker):]; break
    else:
        raise ValueError("no binary section in %s (is it an ASCII raw file?)" % path)
    nvar = int(re.search(r"No\. Variables:\s*(\d+)", header).group(1)); npts = int(re.search(r"No\. Points:\s*(\d+)", header).group(1))
    flags = re.search(r"Flags:\s*(.*)", header).group(1).lower()
    names = [ln.split("\t")[2].lower() for ln in header.split("Variables:\n", 1)[1].strip().split("\n")[:nvar]]
    kind = "<f8" if "double" in flags else "<f4"
    dtype = np.dtype([(names[0], "<f8")] + [(n, kind) for n in names[1:]])
    rec = np.frombuffer(body[: dtype.itemsize * npts], dtype=dtype)
    t = np.abs(rec[names[0]])
    starts = [0] + [int(i) + 1 for i in np.flatnonzero(np.diff(t) < 0)] + [len(t)]
    runs = []
    for a, b in zip(starts, starts[1:]):
        run = {n: np.array(rec[n][a:b], dtype=float) for n in names}; run[names[0]] = t[a:b]; runs.append(run)
    return runs


def read_measurements(log):
    """The .meas results in a log: name -> list of rows (one per .step run), each row a list of numbers."""
    out = {}; name = None
    for line in log.split("\n"):
        m = re.match(r"\s*Measurement:\s*(\S+)", line)
        if m: name = m.group(1); out[name] = []; continue
        m = re.match(r"\s*(\w+)\s*:\s*.*?=\s*([-+0-9.eE]+)", line)          # unstepped: "name: expr=value ..."
        if m and not line.strip().lower().startswith(("circuit", "start", "total", "solver")):
            out.setdefault(m.group(1), []).append([float(m.group(2))]); continue
        if name and re.match(r"\s*\d+\s", line):
            f = line.split()
            try: out[name].append([float(x) for x in f[1:]])
            except ValueError: pass
        elif name and not line.strip():
            name = None
    return out


def run(asc, params=None):
    """Netlist the schematic, run it in LTspice's batch mode, return (waves, measurements, log text)."""
    asc = os.path.abspath(asc); build = os.path.join(os.path.dirname(asc), "build"); os.makedirs(build, exist_ok=True)
    stem = os.path.join(build, os.path.splitext(os.path.basename(asc))[0])
    netlist = with_params(asc_netlist.spice_netlist(asc, title=os.path.basename(asc)), params or {})
    open(stem + ".net", "w").write(netlist)
    for ext in (".raw", ".log"):
        if os.path.exists(stem + ext): os.remove(stem + ext)
    subprocess.run([LTSPICE, "-b", stem + ".net"], cwd=build, capture_output=True, timeout=300)
    if not os.path.exists(stem + ".log"):
        raise RuntimeError("LTspice wrote no log for %s.net" % stem)
    log = text_of(open(stem + ".log", "rb").read())
    if not os.path.exists(stem + ".raw"):
        raise RuntimeError("LTspice produced no waveforms. Its log says:\n" + log)
    return read_raw(stem + ".raw"), read_measurements(log), log


if __name__ == "__main__":
    args = sys.argv[1:]
    def option(flag):
        if flag in args:
            i = args.index(flag); v = args[i + 1]; del args[i:i + 2]; return v
        return None
    traces = option("--traces"); plot = option("--plot")
    asc = args[0]; params = dict(a.split("=", 1) for a in args[1:] if "=" in a)
    waves, meas, log = run(asc, params)
    # With .step, the log names each run's setting, in the order the runs appear in the waveform file.
    steps = re.findall(r"(?m)^\.step\s+(.+?)\s*$", log)
    labels = steps if len(steps) == len(waves) else ["run %d" % (k + 1) for k in range(len(waves))]
    problems = [ln for ln in log.split("\n") if re.search(r"(?i)\berror\b|unknown|singular|convergence failed", ln)]
    print("%s: %d run(s), %d traces, %s points each" % (os.path.basename(asc), len(waves), len(waves[0]), "/".join(str(len(w["time"])) for w in waves)))
    if problems: print("LTspice reported:\n  " + "\n  ".join(problems[:8]))
    print("traces:", " ".join(sorted(waves[0])))
    for name, rows in meas.items():
        print("measurement %s: %s" % (name, "; ".join(" ".join("%.6g" % x for x in r) for r in rows)))
    wanted = [t.strip().lower() for t in traces.split(",")] if traces else []
    for tr in wanted:
        for k, w in enumerate(waves):
            if tr not in w: print("no trace", tr); break
            print("%-12s %-16s min %.5g, max %.5g, last %.5g" % (tr, labels[k] + ":", w[tr].min(), w[tr].max(), w[tr][-1]))
    if plot and wanted:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        SEC, GRID, SURF, INK = "#52514e", "#e1e0d9", "#fcfcfb", "#0b0b0b"; COL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
        fig, ax = plt.subplots(len(wanted), 1, figsize=(11, 3.0 * len(wanted)), facecolor=SURF, squeeze=False, sharex=True)
        for a, tr in zip(ax[:, 0], wanted):
            a.set_facecolor(SURF); a.grid(color=GRID, lw=0.8); a.tick_params(colors=SEC, length=0); [s.set_visible(False) for s in a.spines.values()]
            for k, w in enumerate(waves):
                if tr in w: a.plot(w["time"] * 1e3, w[tr], color=COL[k % 4], lw=1.8, label=labels[k])
            a.set_title(tr, loc="left", color=INK, fontsize=11)
            a.set_ylabel("V" if tr.startswith("v(") else "A", color=SEC)
            if len(waves) > 1: a.legend(fontsize=8, frameon=False)
        ax[-1, 0].set_xlabel("ms", color=SEC); fig.suptitle("%s run in LTspice %s" % (os.path.basename(asc), " ".join("%s=%s" % kv for kv in params.items())), x=0.01, ha="left", color=INK, fontsize=12)
        plt.tight_layout(rect=(0, 0, 1, 0.95)); plt.savefig(plot, dpi=95, facecolor=SURF); print("picture:", plot)
