"""Derive the netlist of an LTspice schematic (.asc) without LTspice, to check its wiring.

usage: asc_netlist.py <file.asc> [--check | --spice]
Reads the pin positions of each symbol from LTspice's own symbol files, applies the symbol's rotation
or mirroring, joins pins through the wires and labels, and prints one line per component with the
nets its pins are on. With --check it only reports what share of pins land on a wire, a label or
another pin (used to validate the rotation rules on LTspice's example schematics). With --spice it
prints the complete netlist, with values and the schematic's directives, as LTspice's batch mode takes it.
Knows flat schematics made of library symbols; hierarchical sheets are not handled."""
import sys, os, re

SYM = os.path.expanduser("~/Library/Application Support/LTspice/lib/sym")


def pins(symbol):
    out = []; path = os.path.join(SYM, symbol.replace("\\", "/") + ".asy")
    cur = None
    for line in open(path, encoding="latin-1"):
        f = line.split()
        if f[:1] == ["PIN"]:
            cur = [int(f[1]), int(f[2]), None, None]; out.append(cur)
        elif f[:2] == ["PINATTR", "PinName"] and cur:
            cur[2] = " ".join(f[2:])
        elif f[:2] == ["PINATTR", "SpiceOrder"] and cur:
            cur[3] = int(f[2])
    return sorted(out, key=lambda p: p[3] or 0)


def place(px, py, x, y, orient):
    if orient.startswith("M"):
        px = -px
    r = int(orient[1:])
    for _ in range(r // 90):
        px, py = -py, px
    return x + px, y + py


DIRECTIVES = []  # the SPICE directives typed on the schematic last loaded (TEXT lines starting with "!")


def load(path):
    wires, flags, syms = [], [], []
    DIRECTIVES.clear()
    for line in open(path, encoding="latin-1"):
        f = line.split()
        if f[:1] == ["WIRE"]: wires.append(tuple(map(int, f[1:5])))
        elif f[:1] == ["FLAG"]: flags.append((int(f[1]), int(f[2]), f[3]))
        elif f[:1] == ["SYMBOL"]: syms.append(dict(sym=f[1], x=int(f[2]), y=int(f[3]), o=f[4], name="?", value="", attr={}))
        elif f[:1] == ["SYMATTR"] and syms:
            syms[-1]["attr"][f[1]] = " ".join(f[2:])
            if f[1] == "InstName": syms[-1]["name"] = f[2]
            elif f[1] == "Value": syms[-1]["value"] = " ".join(f[2:])
        elif f[:1] == ["TEXT"]:
            text = line.split(None, 5)[5].rstrip("\n") if len(line.split(None, 5)) > 5 else ""
            if text.startswith("!"):
                DIRECTIVES.extend(t for t in text[1:].split("\\n") if t.strip())
    return wires, flags, syms


def symbol_defaults(symbol):
    """The attributes a symbol file gives its instances unless the schematic overrides them (Prefix, Value...)."""
    out = {}
    for line in open(os.path.join(SYM, symbol.replace("\\", "/") + ".asy"), encoding="latin-1"):
        f = line.split()
        if f[:1] == ["SYMATTR"] and len(f) > 2:
            out[f[1]] = " ".join(f[2:])
    return out


def spice_netlist(path, title=None):
    """The complete netlist of a schematic as text, ready for "LTspice -b": one line per component
    (name, nets in the symbol's pin order, value and extra parameters), then the schematic's directives."""
    comp, net, _ = netlist(path)
    lines = ["* " + (title or os.path.abspath(path))]
    for s, pp in comp:
        d = symbol_defaults(s["sym"]); d.update(s["attr"])
        prefix = d.get("Prefix", "X")
        name = s["name"] if s["name"].upper().startswith(prefix.upper()) else prefix + s["name"]
        parts = [name] + [net(p) for p, _ in pp] + [d.get(k, "") for k in ("Value", "Value2", "SpiceLine", "SpiceLine2")]
        lines.append(" ".join(x for x in parts if x))
    lines += DIRECTIVES + [".backanno", ".end"]
    return "\n".join(lines) + "\n"


def on_wire(p, w):
    x1, y1, x2, y2 = w
    if x1 == x2: return p[0] == x1 and min(y1, y2) <= p[1] <= max(y1, y2)
    if y1 == y2: return p[1] == y1 and min(x1, x2) <= p[0] <= max(x1, x2)
    return p in ((x1, y1), (x2, y2))


def netlist(path):
    wires, flags, syms = load(path)
    parent = {}
    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def join(a, b): parent[find(a)] = find(b)
    for k, w in enumerate(wires): join(("w", k), (w[0], w[1])); join(("w", k), (w[2], w[3]))
    points = set((w[0], w[1]) for w in wires) | set((w[2], w[3]) for w in wires) | set((x, y) for x, y, _ in flags)
    comp = []
    for s in syms:
        try: pl = pins(s["sym"])
        except FileNotFoundError: continue
        pp = [(place(px, py, s["x"], s["y"], s["o"]), name) for px, py, name, _ in pl]
        comp.append((s, pp)); points |= set(p for p, _ in pp)
    for p in points:
        find(p)
        for k, w in enumerate(wires):
            if on_wire(p, w): join(p, ("w", k))
    names = {}
    for x, y, n in flags: names[find((x, y))] = n
    for a in list(parent):                       # two labels with the same name are one net
        pass
    byname = {}
    for root, n in list(names.items()):
        if n in byname: join(root, byname[n])
        else: byname[n] = root
    names = {find(r): n for r, n in names.items()}
    auto = {}
    def net(p):
        r = find(p)
        if r in names: return names[r]
        return auto.setdefault(r, "N%03d" % (len(auto) + 1))
    touched = lambda p: any(on_wire(p, w) for w in wires) or any((x, y) == p for x, y, _ in flags)
    return comp, net, touched


if __name__ == "__main__":
    comp, net, touched = netlist(sys.argv[1])
    if "--spice" in sys.argv:
        print(spice_netlist(sys.argv[1]), end="")
    elif "--check" in sys.argv:
        tot = sum(len(pp) for _, pp in comp); ok = sum(1 for s, pp in comp for p, _ in pp if touched(p) or sum(1 for s2, pp2 in comp for q, _ in pp2 if q == p) > 1)
        by = {}
        for s, pp in comp:
            for p, _ in pp:
                good = touched(p) or sum(1 for s2, pp2 in comp for q, _ in pp2 if q == p) > 1
                a = by.setdefault(s["o"], [0, 0]); a[0] += good; a[1] += 1
        print("%s: %d of %d pins connected; by orientation: %s" % (os.path.basename(sys.argv[1]), ok, tot, "  ".join("%s %d/%d" % (o, a, b) for o, (a, b) in sorted(by.items()))))
    else:
        for s, pp in comp:
            print("%-7s %-10s %s   %s" % (s["name"], s["sym"], " ".join("%s=%s" % (n, net(p)) for p, n in pp), s["value"]))
