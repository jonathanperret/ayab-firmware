"""Trace a net's copper in a gEDA .pcb file and report the route between named pads.
usage: pcb_ground.py <file.pcb> <out.png> <start pad, e.g. U3-8> <pad> [<pad> ...]
Finds all copper connected to the start pad (tracks on top/bottom, vias, pins), then for
every pair of the pads given (the start pad included) prints the shortest route along the
tracks between the two, and how much of it is shared with the other routes.

A pad or pin is named <element name>-<pin number>, for example U3-8. An unknown name stops
the script with a KeyError.

Prints:
  - how many tracks, vias, pads and pins were read, and on which layers polygons are;
  - the list of pads and pins that the copper connected to the start pad reaches;
  - for each pair of pads: the route length in mm, the track widths (mil) and the layers
    used, or "no route found";
  - for each pair of routes that have tracks in common: the length in common, in mm.
Writes to <out.png> a picture of the whole board with the copper connected to the start
pad in colour (red on top, blue on the bottom), the rest in grey and the pads given as
labelled black dots. Axis units are mil.

Needs matplotlib. All lengths are held in mil (1 mil = 0.0254 mm).

What is and is not followed:
  - Only Line records of layers 1 and 2, which the script takes to be top and bottom.
  - Polygons (copper areas) are only counted, and arcs are not read at all. Two pads
    joined only through a polygon or an arc are therefore reported as not connected.
  - A route is measured through a graph in which a junction in the middle of a track is
    approximated (see the comments below), so a length can differ a little from the true
    length along the copper. pcb_paths.py splits tracks at junctions and is exact there.
"""

import sys, re, math, heapq, itertools
import matplotlib

# "Agg" draws to a file without needing a display.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# fn: layout file to read. outf: picture to write. pads_wanted: pad names; the first one is
# the start pad.
fn, outf, pads_wanted = sys.argv[1], sys.argv[2], sys.argv[3:]


def num(s):
    """Convert a coordinate or size as written in the .pcb file to mil.

    s: text such as "12.5mil", "0.3mm" or "1250".
    Returns a float in mil.
    """
    s = s.strip()
    if s.endswith("mil"):
        return float(s[:-3])
    if s.endswith("mm"):
        return float(s[:-2]) / 0.0254  # 0.0254 mm per mil
    return float(s) / 100.0  # bare numbers are 1/100 mil


# What is read from the file:
lines = []  # tracks: dicts with l (layer 1 or 2), a and b (end points, mil), w (width, mil)
vias = []  # (x, y, radius of the copper ring), mil
pads = {}  # "element-number" -> dict describing a surface-mount pad or a through-hole pin
layer = None  # number of the Layer block being read, None outside one
elem = None  # the Element being read (name, position), None outside one
polys = []  # one entry (the layer number) per Polygon found on layers 1 and 2
for raw in open(fn):
    t = raw.strip()
    # Layer(1 "top") starts a block of tracks. No test is made for the end of a block:
    # layer stays set until the next Element or Layer line.
    m = re.match(r'Layer\((\d+) "([^"]*)"', t)
    if m:
        layer = int(m.group(1))
        elem = None
        continue
    # Element[flags "description" "name" "value" x y ...] starts a component. The fields
    # are split on spaces, keeping quoted strings whole. x, y is the reference point that
    # the component's pads and pins are positioned from.
    m = re.match(r"Element\[(.*)\]", t)
    if m:
        f = re.findall(r'"[^"]*"|\S+', m.group(1))
        elem = dict(name=f[2].strip('"'), x=num(f[4]), y=num(f[5]), flags=f[0])
        layer = None
        continue
    # Via[x y diameter ...]: a plated hole joining both layers. Half the diameter is kept
    # as the radius.
    m = re.match(r"Via\[(.*)\]", t)
    if m:
        f = m.group(1).split()
        vias.append((num(f[0]), num(f[1]), num(f[2]) / 2))
        continue
    if elem is not None:
        # Pad[x1 y1 x2 y2 thickness clearance mask "name" "number" flags]: a surface-mount
        # pad. It is a stroke of the given thickness drawn from (x1, y1) to (x2, y2), both
        # relative to the element's reference point.
        m = re.match(r"Pad\[(.*)\]", t)
        if m:
            f = re.findall(r'"[^"]*"|\S+', m.group(1))
            x1, y1, x2, y2, th = [num(v) for v in f[:5]]
            # A pad flagged "onsolder" is on the bottom (layer 2), otherwise on top (1).
            side = 2 if "onsolder" in f[9] else 1
            pads["%s-%s" % (elem["name"], f[8].strip('"'))] = dict(
                # x, y: centre of the pad in board coordinates.
                x=elem["x"] + (x1 + x2) / 2,
                y=elem["y"] + (y1 + y2) / 2,
                # r: half the thickness plus half the length, a radius from the centre that
                # reaches the ends of the pad. It is not used below for pads (seg and th are).
                r=th / 2 + math.hypot(x2 - x1, y2 - y1) / 2,
                layers=[side],
                # seg: the pad's centre line in board coordinates; th: its thickness.
                seg=(elem["x"] + x1, elem["y"] + y1, elem["x"] + x2, elem["y"] + y2),
                th=th,
            )
            continue
        # Pin[x y diameter clearance mask drill "name" "number" flags]: a through-hole pin,
        # present on both layers. r is the radius of its copper ring.
        m = re.match(r"Pin\[(.*)\]", t)
        if m:
            f = re.findall(r'"[^"]*"|\S+', m.group(1))
            pads["%s-%s" % (elem["name"], f[7].strip('"'))] = dict(
                x=elem["x"] + num(f[0]), y=elem["y"] + num(f[1]), r=num(f[2]) / 2, layers=[1, 2]
            )
            continue
    if layer in (1, 2):
        # Line[x1 y1 x2 y2 width ...]: a straight track, in board coordinates.
        m = re.match(r"Line\[(.*)\]", t)
        if m:
            f = m.group(1).split()
            lines.append(
                dict(l=layer, a=(num(f[0]), num(f[1])), b=(num(f[2]), num(f[3])), w=num(f[4]))
            )
            continue
        # Polygons are only noted so that the summary line can warn they exist.
        if t.startswith("Polygon"):
            polys.append(layer)
print(
    "%d tracks on top/bottom, %d vias, %d pads and pins, polygons on layers %s"
    % (len(lines), len(vias), len(pads), polys)
)


def dps(p, a, b):
    """Distance from the point p to the segment from a to b (all (x, y) in mil).

    This is the distance to the nearest point of the segment, which is one of its ends
    when p is beyond them. Returns mil.
    """
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy  # squared length of the segment
    # u: position along the segment (0 at a, 1 at b) of the point nearest to p, kept within
    # the segment. A segment of zero length is treated as the point a.
    u = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - u * dx, py - ay - u * dy)


# graph nodes: track endpoints (per layer) and the centres of vias / pins / pads;
# edges: tracks, plus zero-length joins
# (The joins are in fact given a length: the straight distance between the two points.)
nodes = []  # node number -> its key
idx = {}  # key -> node number


def node(key):
    """Return the number of the node with this key, creating the node if it is new.

    key: ("p", layer, x, y) for a track end, with x and y rounded to 0.1 mil, so that track
    ends at the same place on the same layer share one node; or ("t", name) for a via, pin
    or pad.
    """
    if key not in idx:
        idx[key] = len(nodes)
        nodes.append(key)
    return idx[key]


adj = {}  # node number -> list of (neighbour node, length in mil, tag)


def edge(i, j, w, tag):
    """Connect nodes i and j, in both directions, by an edge of length w (mil).

    tag says what the edge is: a track number (an integer index into lines) for a track
    followed from end to end, ("j", track number) for a join onto that track, or
    ("t", name) for a join to a via, pin or pad.
    """
    adj.setdefault(i, []).append((j, w, tag))
    adj.setdefault(j, []).append((i, w, tag))


# One edge per track, between its two ends, as long as the track.
for k, ln in enumerate(lines):
    ln["na"] = node(("p", ln["l"], round(ln["a"][0], 1), round(ln["a"][1], 1)))
    ln["nb"] = node(("p", ln["l"], round(ln["b"][0], 1), round(ln["b"][1], 1)))
    edge(ln["na"], ln["nb"], math.hypot(ln["a"][0] - ln["b"][0], ln["a"][1] - ln["b"][1]), k)
# a track end touching another track of the same layer joins it (T junctions): split is
# approximated by a join to its nearer end, weighted by distance
# In detail: the end of track l1 touches track l2 when its distance to l2's centre line is
# no more than 0.9 times the sum of the two half-widths (why 0.9 rather than 1 is not
# stated). The end is then joined to both ends of l2, each join as long as the straight
# line between the two points. When the end lies on l2's centre line these are the true
# distances along l2. The track l2 itself is not cut at the junction.
for i, l1 in enumerate(lines):
    for end, n1 in ((l1["a"], l1["na"]), (l1["b"], l1["nb"])):
        for j, l2 in enumerate(lines):
            if i == j or l1["l"] != l2["l"]:
                continue
            if dps(end, l2["a"], l2["b"]) <= (l1["w"] + l2["w"]) / 2 * 0.9:
                edge(n1, l2["na"], math.hypot(end[0] - l2["a"][0], end[1] - l2["a"][1]), ("j", j))
                edge(n1, l2["nb"], math.hypot(end[0] - l2["b"][0], end[1] - l2["b"][1]), ("j", j))
# Vias, pins and pads ("things"). Vias get the names via0, via1, ... and, like pins, exist
# on both layers. Each thing is one node, whatever the layer: this is how a route changes
# layer.
things = [
    ("via%d" % i, dict(x=v[0], y=v[1], r=v[2], layers=[1, 2])) for i, v in enumerate(vias)
] + list(pads.items())
for name, t in things:
    n0 = node(("t", name))
    for ln in lines:
        if ln["l"] not in t["layers"]:
            continue
        # d: distance from the thing's centre to the track's centre line.
        d = dps((t["x"], t["y"]), ln["a"], ln["b"])
        if "seg" in t:
            # A surface-mount pad is long: also try the distance from each end of the track
            # to the pad's centre line, and keep the smallest of the three. The track
            # touches the pad when that is within half the pad's thickness plus half the
            # track's width.
            d = min(
                d,
                dps(ln["a"], t["seg"][:2], t["seg"][2:]),
                dps(ln["b"], t["seg"][:2], t["seg"][2:]),
            )
            reach = t["th"] / 2 + ln["w"] / 2
        else:
            # A via or pin is round: the track touches it when its centre line passes
            # within the ring's radius plus half the track's width.
            reach = t["r"] + ln["w"] / 2
        # 0.95: a margin on the touching distance (the reason for this value is not stated).
        if d <= reach * 0.95:
            # As for track junctions, the thing is joined to both ends of the track by the
            # straight distance from its centre, and the track is not cut.
            edge(n0, ln["na"], math.hypot(t["x"] - ln["a"][0], t["y"] - ln["a"][1]), ("t", name))
            edge(n0, ln["nb"], math.hypot(t["x"] - ln["b"][0], t["y"] - ln["b"][1]), ("t", name))


def dijkstra(src):
    """Shortest distances from node src to every node that copper connects it to.

    Dijkstra's algorithm: always continue from the nearest node not yet settled.
    Returns (dist, prev): dist maps each reachable node to its distance from src in mil;
    prev maps each of them (except src) to (previous node on the shortest route, tag of the
    edge taken, its length in mil).
    """
    dist = {src: 0}
    prev = {}
    pq = [(0, src)]  # heap of (distance found so far, node)
    while pq:
        d, u = heapq.heappop(pq)
        # A node can be in the heap several times; skip entries made stale by a shorter
        # route found since. 1e18 stands for "not reached yet".
        if d > dist.get(u, 1e18):
            continue
        for v, w, tag in adj.get(u, []):
            if d + w < dist.get(v, 1e18):
                dist[v] = d + w
                prev[v] = (u, tag, w)
                heapq.heappush(pq, (d + w, v))
    return dist, prev


# Everything reachable from the start pad is "the net".
start = idx[("t", pads_wanted[0])]
dist0, _ = dijkstra(start)
net = sorted(n for n, t in pads.items() if idx.get(("t", n)) in dist0)
print("copper connected to %s reaches %d pads/pins: %s" % (pads_wanted[0], len(net), " ".join(net)))


def route(a, b):
    """Shortest route between the pads or pins named a and b.

    Returns (length in mil, set of the numbers of the tracks followed from end to end,
    list of the node numbers passed, from b back to a). When there is no route the result
    is (None, empty set, empty list).
    Stretches entered or left through a junction or a via, pin or pad are join edges, not
    track edges, so the tracks they run along are not in the set.
    """
    d, prev = dijkstra(idx[("t", a)])
    tgt = idx[("t", b)]
    if tgt not in d:
        return None, set(), []
    segs = set()
    pts = []
    # Walk back from b to a through the "previous node" links.
    u = tgt
    while u in prev:
        p, tag, w = prev[u]
        if isinstance(tag, int):  # an integer tag is a whole track
            segs.add(tag)
        pts.append(u)
        u = p
    pts.append(u)
    return d[tgt], segs, pts


MM = 0.0254  # millimetres per mil
routes = {}  # (pad a, pad b) -> (length in mil or None, set of track numbers, node list)
for a, b in itertools.combinations(pads_wanted, 2):
    L, segs, pts = route(a, b)
    routes[(a, b)] = (L, segs, pts)
    if L is None:
        print("%s to %s: no route found" % (a, b))
        continue
    # Widths (rounded to a whole mil) and layers of the whole tracks on the route.
    ws = sorted(set(round(lines[s]["w"]) for s in segs))
    ly = sorted(set(lines[s]["l"] for s in segs))
    print(
        "%s to %s: %.0f mm along the tracks; track widths (mil) %s; layers %s"
        % (a, b, L * MM, ws, ["top" if x == 1 else "bottom" for x in ly])
    )


def seglen(s):
    """Total length in mm of the tracks whose numbers are in the set s."""
    return (
        sum(
            math.hypot(lines[k]["a"][0] - lines[k]["b"][0], lines[k]["a"][1] - lines[k]["b"][1])
            for k in s
        )
        * MM
    )


# For every two routes, the tracks that both follow from end to end. Tracks that a route
# only joins part-way are not in its set (see route), so they are not counted here.
print("shared track length between routes:")
for (k1, r1), (k2, r2) in itertools.combinations(routes.items(), 2):
    if r1[0] is None or r2[0] is None:
        continue
    sh = r1[1] & r2[1]  # track numbers common to both routes
    if sh:
        print("  %s>%s and %s>%s: %.0f mm shared" % (k1[0], k1[1], k2[0], k2[1], seglen(sh)))
# picture
fig, ax = plt.subplots(figsize=(16, 5))  # inches
netnodes = set(dist0)  # numbers of all nodes connected to the start pad
for k, ln in enumerate(lines):
    on = ln["na"] in netnodes  # True when this track belongs to the start pad's net
    ax.plot(
        [ln["a"][0], ln["b"][0]],
        [ln["a"][1], ln["b"][1]],
        # On the net: red for the top layer, blue for the bottom. Otherwise light grey.
        color=("#d62828" if ln["l"] == 1 else "#1d6fd0") if on else "#dddddd",
        # Line width grows with the track width (width in mil / 12, at least 0.6 point).
        lw=max(0.6, ln["w"] / 12) if on else 0.4,
        solid_capstyle="round",
        zorder=2 if on else 1,
    )
# A black dot and the name at each pad given on the command line.
for n in pads_wanted:
    p = pads[n]
    ax.plot(p["x"], p["y"], "o", color="black", ms=6, zorder=5)
    ax.annotate(
        n, (p["x"], p["y"]), xytext=(4, 6), textcoords="offset points", fontsize=9, zorder=6
    )
ax.set_aspect("equal")
# In the .pcb file y grows downwards; flip the axis so the board appears the right way up.
ax.invert_yaxis()
ax.set_title(
    "Copper connected to %s: red = top, blue = bottom; grey = everything else" % pads_wanted[0]
)
ax.set_xlabel("mil")
plt.tight_layout()
plt.savefig(outf, dpi=90)
