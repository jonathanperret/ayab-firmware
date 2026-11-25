"""Draw the copper route between pairs of pads of a gEDA .pcb file, with its length, over the layout.
usage: pcb_paths.py <file.pcb> <out.png> <title> PANEL...
PANEL = "name|xmin,xmax,ymin,ymax|elements to outline (comma)|padA>padB:label,padA>padB:label[|parts]"   (coordinates in mil)
parts (optional) = "x1,y1,x2,y2:label;..." : an 0603 body (63 x 31 mil) drawn to scale, centred between the two points and lying along them
Tracks are split properly where other tracks, vias, pins or pads join them, so lengths are along the copper.

In more detail, each PANEL argument gives one picture, side by side in <out.png>:
  name       title of the panel
  box        the part of the board to show: xmin,xmax,ymin,ymax in mil, in the .pcb
             file's coordinates (y grows downwards)
  elements   comma-separated element names (U3,C5,...): their surface-mount pads are
             drawn and their names written
  routes     comma-separated "padA>padB:label". A pad or pin is named
             <element name>-<pin number>, for example U3-8. Each route is drawn in its own
             colour (at most four per panel: a fifth stops the script with an IndexError)
             and listed in the legend with its length.
  parts      optional, see above; for showing where a component could be fitted.
An unknown pad name stops the script with a KeyError.

Prints one line per route: panel name, label, the two pads, the length in mm and how much
of it is on the top and on the bottom layer; or "no route".
Writes the picture to <out.png>. Needs matplotlib.

All lengths are held in mil (1 mil = 0.0254 mm) and converted to mm for output.
Only Line records of layers 1 and 2 are followed, which the script takes to be top and
bottom. Polygons (copper areas) and arcs are not read, so a connection made only through
one of them is not found.
"""

import sys, re, math, heapq
import matplotlib

# "Agg" draws to a file without needing a display.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# fn: layout file to read. outf: picture to write. title: text above the whole picture.
# panels: one PANEL description per picture.
fn, outf, title, panels = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]


def num(s):
    """Convert a coordinate or size as written in the .pcb file to mil.

    s: text such as "12.5mil", "0.3mm" (0.0254 mm per mil) or a bare number, which is in
    hundredths of a mil. Returns a float in mil.
    """
    s = s.strip()
    return (
        float(s[:-3])
        if s.endswith("mil")
        else float(s[:-2]) / 0.0254 if s.endswith("mm") else float(s) / 100.0
    )


# What is read from the file:
lines = []  # tracks: dicts with l (layer 1 or 2), a and b (end points, mil), w (width, mil)
vias = []  # (x, y, radius of the copper ring), mil
pads = {}  # "element-number" -> dict describing a surface-mount pad or a through-hole pin
layer = None  # number of the Layer block being read, None outside one
elem = None  # the Element being read (name, position), None outside one
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
        elem = dict(name=f[2].strip('"'), x=num(f[4]), y=num(f[5]))
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
            pads["%s-%s" % (elem["name"], f[8].strip('"'))] = dict(
                el=elem["name"],
                # A pad flagged "onsolder" is on the bottom (layer 2), otherwise on top (1).
                layers=[2 if "onsolder" in f[9] else 1],
                # seg: the pad's centre line in board coordinates; th: its thickness.
                seg=(elem["x"] + x1, elem["y"] + y1, elem["x"] + x2, elem["y"] + y2),
                th=th,
                # x, y: centre of the pad in board coordinates.
                x=elem["x"] + (x1 + x2) / 2,
                y=elem["y"] + (y1 + y2) / 2,
            )
            continue
        # Pin[x y diameter clearance mask drill "name" "number" flags]: a through-hole pin,
        # present on both layers. r is the radius of its copper ring.
        m = re.match(r"Pin\[(.*)\]", t)
        if m:
            f = re.findall(r'"[^"]*"|\S+', m.group(1))
            pads["%s-%s" % (elem["name"], f[7].strip('"'))] = dict(
                el=elem["name"],
                layers=[1, 2],
                x=elem["x"] + num(f[0]),
                y=elem["y"] + num(f[1]),
                r=num(f[2]) / 2,
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


def proj(p, a, b):
    """Find the point of the segment from a to b that is nearest to the point p.

    p, a, b: (x, y) in mil.
    Returns (u, q, d): u is the position of that point along the segment, from 0 at a to
    1 at b (it is an end of the segment when p is beyond it); q is the point itself (x, y);
    d is its distance to p in mil. A segment of zero length is treated as the point a.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy  # squared length of the segment
    u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + u * dx, a[1] + u * dy)
    return u, q, math.hypot(p[0] - q[0], p[1] - q[1])


# The copper as a graph. A node is a point where copper can be entered or left: a track
# end, a point where something joins a track, or the centre of a via, pin or pad. An edge
# is a piece of copper between two nodes, with its length.
nodes = {}  # key -> node number
coords = []  # node number -> (x, y) in mil
adj = {}  # node number -> list of (neighbour node, length in mil, layer)


def node(key, xy):
    """Return the number of the node with this key, creating it at xy if it is new.

    key: ("p", layer, x, y) for a point on a track, or ("t", name) for a via, pin or pad.
    xy:  position (x, y) in mil, recorded only when the node is created.
    """
    if key not in nodes:
        nodes[key] = len(coords)
        coords.append(xy)
    return nodes[key]


def edge(i, j, w, lay):
    """Connect nodes i and j, in both directions, by an edge of length w (mil) on layer lay.

    Nothing is added when i and j are the same node.
    """
    if i == j:
        return
    adj.setdefault(i, []).append((j, w, lay))
    adj.setdefault(j, []).append((i, w, lay))


def tnode(l, xy):
    """Return the node for the point xy on a track of layer l.

    The position is rounded to 0.1 mil in the key, so points at the same place on the same
    layer (two track ends that meet, for instance) are one node. The same place on the
    other layer is a different node: layers are only joined through vias and pins.
    """
    return node(("p", l, round(xy[0], 1), round(xy[1], 1)), xy)


# splits[j] lists the points at which track j must be cut, as (u, point), u being the
# position along the track from 0 (end a) to 1 (end b). To begin with: its two ends.
splits = [[(0.0, ln["a"]), (1.0, ln["b"])] for ln in lines]
# track ends landing on other tracks
# The end of track l1 touches track l2 (same layer) when its distance d to l2's centre line
# is no more than 0.9 times the sum of the two half-widths (why 0.9 rather than 1 is not
# stated). Then l2 is cut at q, the point of its centre line nearest to that end, and the
# end is joined to q by an edge of length d (zero when the end is exactly on the line).
for i, l1 in enumerate(lines):
    for end in (l1["a"], l1["b"]):
        for j, l2 in enumerate(lines):
            if i == j or l1["l"] != l2["l"]:
                continue
            u, q, d = proj(end, l2["a"], l2["b"])
            if d <= (l1["w"] + l2["w"]) / 2 * 0.9:
                splits[j].append((u, q))
                edge(tnode(l1["l"], end), tnode(l2["l"], q), d, l1["l"])
# vias, pins (both layers) and pads (one layer)
# Vias get the names via0, via1, ... Each via, pin or pad ("thing") is a single node,
# whatever the layer: this is how a route changes layer.
things = [
    ("via%d" % i, dict(x=v[0], y=v[1], r=v[2], layers=[1, 2])) for i, v in enumerate(vias)
] + list(pads.items())
for name, t in things:
    n0 = node(("t", name), (t["x"], t["y"]))
    for j, ln in enumerate(lines):
        if ln["l"] not in t["layers"]:
            continue
        # q: point of the track nearest to the thing's centre, d: its distance.
        u, q, d = proj((t["x"], t["y"]), ln["a"], ln["b"])
        if "seg" in t:
            # A surface-mount pad is long, so a track can end on it far from its centre.
            # Also measure from each end of the track (u = 0 and u = 1) to the pad's centre
            # line; if one of them is nearer than d, that track end becomes the junction.
            best = (d, u, q)
            for e, uu in ((ln["a"], 0.0), (ln["b"], 1.0)):
                _, _, dd = proj(e, t["seg"][:2], t["seg"][2:])
                if dd < best[0]:
                    best = (dd, uu, e)
            d, u, q = best
            # The track touches the pad within half the pad's thickness plus half the
            # track's width.
            reach = t["th"] / 2 + ln["w"] / 2
        else:
            # A via or pin is round: the track touches it when its centre line passes
            # within the ring's radius plus half the track's width.
            reach = t["r"] + ln["w"] / 2
        # 0.95: a margin on the touching distance (the reason for this value is not stated).
        if d <= reach * 0.95:
            # Cut the track at q and join the thing's centre to q by a straight edge.
            splits[j].append((u, q))
            edge(n0, tnode(ln["l"], q), math.hypot(t["x"] - q[0], t["y"] - q[1]), ln["l"])
# Now cut every track: put its cut points in order along it and make one edge between each
# point and the next, as long as the piece of track between them.
for ln, sp in zip(lines, splits):
    sp.sort()
    for (u1, p1), (u2, p2) in zip(sp, sp[1:]):
        edge(
            tnode(ln["l"], p1),
            tnode(ln["l"], p2),
            math.hypot(p1[0] - p2[0], p1[1] - p2[1]),
            ln["l"],
        )


def route(a, b):
    """Shortest route along the copper between the pads or pins named a and b.

    Uses Dijkstra's algorithm: always continue from the nearest node not yet settled, and
    stop when that node is b.
    Returns (length in mm, path), where path is the list of pieces from a to b, each
    ((x, y) from, (x, y) to, layer) in mil; or (None, []) when the two are not connected.
    """
    src, dst = nodes[("t", a)], nodes[("t", b)]
    dist = {src: 0.0}  # node -> shortest distance from a found so far, mil
    prev = {}  # node -> (previous node on that shortest route, layer of the edge taken)
    pq = [(0.0, src)]  # heap of (distance, node)
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        # A node can be in the heap several times; skip entries made stale by a shorter
        # route found since. 1e18 stands for "not reached yet".
        if d > dist.get(u, 1e18):
            continue
        for v, w, lay in adj.get(u, []):
            if d + w < dist.get(v, 1e18):
                dist[v] = d + w
                prev[v] = (u, lay)
                heapq.heappush(pq, (d + w, v))
    if dst not in dist:
        return None, []
    # Walk back from b to a through the "previous node" links, then reverse the list.
    path = []
    u = dst
    while u in prev:
        p, lay = prev[u]
        path.append((coords[p], coords[u], lay))
        u = p
    return dist[dst] * 0.0254, path[::-1]  # 0.0254 mm per mil


# Colours: main text, secondary text, scale bar, background.
INK, SEC, MUTED, SURF = "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
# Route colours, in the order the routes are listed in a panel.
COL = ["#eb6834", "#2a78d6", "#1baf7a", "#6250d6"]
# One row of panels, each 8.2 inches wide and 7.4 high. squeeze=False keeps axes a
# two-dimensional array even with a single panel.
fig, axes = plt.subplots(
    1, len(panels), figsize=(8.2 * len(panels), 7.4), facecolor=SURF, squeeze=False
)
for ax, spec in zip(axes[0], panels):
    # Split the panel description into its fields (see the top of the file).
    fields = spec.split("|")
    name, box, els, prs = fields[:4]
    parts = fields[4] if len(fields) > 4 else ""
    x0, x1, y0, y1 = [float(v) for v in box.split(",")]  # xmin, xmax, ymin, ymax in mil
    ax.set_facecolor(SURF)
    # Background: every track that is not wholly more than 50 mil outside the box, in grey
    # (top layer a little darker than bottom). Line width is the track width in mil / 9,
    # at least 1 point.
    for ln in lines:
        if (
            max(ln["a"][0], ln["b"][0]) < x0 - 50
            or min(ln["a"][0], ln["b"][0]) > x1 + 50
            or max(ln["a"][1], ln["b"][1]) < y0 - 50
            or min(ln["a"][1], ln["b"][1]) > y1 + 50
        ):
            continue
        ax.plot(
            [ln["a"][0], ln["b"][0]],
            [ln["a"][1], ln["b"][1]],
            color="#d9d8d2" if ln["l"] == 1 else "#e6e5df",
            lw=max(1.0, ln["w"] / 9),
            solid_capstyle="round",
            zorder=1,
        )
    # Surface-mount pads of the listed elements, as grey rectangles: the pad's centre line
    # widened by half the thickness (h) on every side. Through-hole pins are not drawn.
    for n, p in pads.items():
        if p["el"] in els.split(","):
            if "seg" in p:
                sx0, sy0, sx1, sy1 = p["seg"]
                h = p["th"] / 2
                ax.add_patch(
                    Rectangle(
                        (min(sx0, sx1) - h, min(sy0, sy1) - h),
                        abs(sx1 - sx0) + 2 * h,
                        abs(sy1 - sy0) + 2 * h,
                        fc="#c3c2b7",
                        ec="none",
                        zorder=2,
                    )
                )
    for vx, vy, vr in vias:  # vias as rings, so a route's end marker is not mistaken for one
        if x0 < vx < x1 and y0 < vy < y1:
            # Outer ring at the via's copper radius, and a dot of 0.4 times that radius.
            ax.add_patch(plt.Circle((vx, vy), vr, fc=SURF, ec="#52514e", lw=1.4, zorder=8))
            ax.add_patch(plt.Circle((vx, vy), vr * 0.4, fc="#52514e", ec="none", zorder=8))
    # Name of each listed element, written at the average position of its pads and pins.
    for e in els.split(","):
        ps = [p for n, p in pads.items() if p["el"] == e]
        if ps:
            ax.text(
                sum(p["x"] for p in ps) / len(ps),
                sum(p["y"] for p in ps) / len(ps),
                e,
                ha="center",
                va="center",
                color=SEC,
                fontsize=12,
                weight="bold",
                zorder=3,
            )
    # The routes. k is the route's rank in the panel and picks its colour.
    for k, pr in enumerate(prs.split(",")):
        ab, label = pr.split(":")
        a, b = ab.split(">")
        L, path = route(a, b)  # L: length in mm
        if L is None:
            print(name, ab, "no route")
            continue
        # top: length of the pieces on layer 1, in mm. The rest of L is on layer 2.
        top = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q, lay in path if lay == 1) * 0.0254
        print(
            "%s: %s, %s to %s: %.0f mm (%.0f mm on top, %.0f mm on bottom)"
            % (name, label, a, b, L, top, L - top)
        )
        # Draw each piece: solid on the top layer, dashed on the bottom layer.
        for p, q, lay in path:
            ax.plot(
                [p[0], q[0]],
                [p[1], q[1]],
                color=COL[k],
                lw=3.2,
                ls="-" if lay == 1 else (0, (2.2, 1.6)),
                solid_capstyle="round",
                zorder=4 + k,
            )
        # A coloured square at each end of the route, with a short label: "U3 pin 8" for a
        # pad of an element whose name starts with U, otherwise just the element's name.
        for pd in (a, b):
            ax.plot(
                pads[pd]["x"], pads[pd]["y"], "s", ms=8, color=COL[k], mec=SURF, mew=1.5, zorder=9
            )
            ax.annotate(
                pd.replace("-", " pin ") if pd[0] == "U" else pd.split("-")[0],
                (pads[pd]["x"], pads[pd]["y"]),
                xytext=(8, 8),
                textcoords="offset points",
                color=INK,
                fontsize=9,
                zorder=10,
            )
        # An empty line, only so that the legend has an entry with this colour and length.
        ax.plot([], [], color=COL[k], lw=3.2, label="%s: %.0f mm" % (label, L))
    # Optional 0603 component outlines. Each is given by two points (mil): the body is
    # centred half-way between them and its long side points from the first to the second.
    for part in [q for q in parts.split(";") if q]:
        xy, lab = part.split(":")
        ax_, ay_, bx_, by_ = [float(v) for v in xy.split(",")]
        cx, cy = (ax_ + bx_) / 2, (ay_ + by_) / 2  # centre of the body
        ang = math.atan2(by_ - ay_, bx_ - ax_)  # direction of the body, radians
        c, sn = math.cos(ang), math.sin(ang)

        def corner(u, v):
            """Board position (x, y) of the point u mil along and v mil across the body.

            u and v are measured from the body's centre; this rotates them by the body's
            direction and adds the centre.
            """
            return (cx + u * c - v * sn, cy + u * sn + v * c)

        # The body is 63 x 31 mil, so its corners are at +/-31.5 along and +/-15.5 across.
        body = [corner(-31.5, -15.5), corner(31.5, -15.5), corner(31.5, 15.5), corner(-31.5, 15.5)]
        ax.add_patch(plt.Polygon(body, closed=True, fc="#f4d98a", ec=INK, lw=1.6, zorder=12))
        for sgn in (-1, 1):  # the two metal ends
            # Each end cap covers the last 12 mil of the body (from 19.5 to 31.5 mil).
            ax.add_patch(
                plt.Polygon(
                    [
                        corner(sgn * 31.5, -15.5),
                        corner(sgn * 19.5, -15.5),
                        corner(sgn * 19.5, 15.5),
                        corner(sgn * 31.5, 15.5),
                    ],
                    closed=True,
                    fc="#b9b8b0",
                    ec=INK,
                    lw=1.0,
                    zorder=13,
                )
            )
        # The part's label, offset from the body and tied to it by a thin line.
        ax.annotate(
            lab,
            (cx, cy),
            xytext=(34, 30),
            textcoords="offset points",
            color=INK,
            fontsize=10,
            weight="bold",
            arrowprops=dict(arrowstyle="-", color=INK, lw=1),
            zorder=14,
        )
    ax.set_xlim(x0, x1)
    # y limits given as (ymax, ymin): in the .pcb file y grows downwards, so this shows the
    # board the right way up.
    ax.set_ylim(y1, y0)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    [s.set_visible(False) for s in ax.spines.values()]
    ax.set_title(name, loc="left", color=INK, fontsize=12)
    leg = ax.legend(
        loc="lower left", frameon=True, facecolor=SURF, edgecolor="#e1e0d9", fontsize=10
    )
    [t.set_color(INK) for t in leg.get_texts()]
    # Scale bar near the bottom right corner: 393.7 mil is 10 mm. It starts 450 mil left of
    # the right edge and sits 40 mil above the bottom edge, with its caption above it.
    ax.plot([x1 - 450, x1 - 450 + 393.7], [y1 - 40, y1 - 40], color=MUTED, lw=2)
    ax.text(x1 - 450 + 197, y1 - 55, "10 mm", ha="center", color=SEC, fontsize=9)
fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=13)
# Key to the drawing conventions, along the bottom of the figure.
fig.text(
    0.01,
    0.01,
    "solid line: top layer   dashed: bottom layer   ring with dot: via   coloured square: end of a route (a pad, not a via)   grey: all other tracks",
    color=SEC,
    fontsize=9,
)
# Keep the bottom 3 % of the figure for the key and the top 5 % for the title.
plt.tight_layout(rect=(0, 0.03, 1, 0.95))
plt.savefig(outf, dpi=100, facecolor=SURF)
