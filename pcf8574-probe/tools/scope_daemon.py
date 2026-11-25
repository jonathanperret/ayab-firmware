"""Scope server, to run on the computer the 6022BE is plugged into (the Pi). It is the only program
that talks to the scope: it captures continuously for a live view and, on request, records a block
to a file for analysis, so the two never fight over the scope.
usage: sudo python3 scope_daemon.py [port, default 8000]
  /live?pre=US&post=US&trig=MODE&ch=N  latest frame as JSON: whole frame + a window around the trigger
  /record?name=N&mb=M&r1=R&r2=R        record M megabytes at 16 MS/s into out/N.npy, then resume live
  /set?r1=R&r2=R                       ranges for the live view (100mV 250mV 500mV 1V)
Trigger modes: pair (an edge that follows another within 300 us), rise, fall, big (largest step),
none.

Any other path returns a short status (frame count, ranges, last error). All answers are JSON.

Needs: scope.py and scope_zero.json in the same folder as this file, the scope with its sigrok
firmware loaded (scope_loadfw.py), numpy and pyusb. It always samples both channels at 16 MS/s.
Writes: recordings to the "out" folder next to this file (created if missing), as numpy uint8
arrays of interleaved CH1, CH2 bytes. Prints nothing; it runs until killed.
Clients: scope_page.py (its page polls /live and calls /set) and scope_trial.py (calls /record).

Details of the requests:
  /live    pre, post = microseconds to show before / after the trigger (defaults 20 and 80);
           trig = trigger mode (default pair); ch = channel to trigger on, 1 or 2 (default 1).
  /record  name = file name without extension (any folder part is dropped); mb = size in units
           of 2**20 bytes, above 0 and up to 256 (default 16); r1, r2 = ranges (default: the
           current live ranges). The request returns once the file is written, or with an error
           after 60 s. The live view stays on the recording's ranges afterwards.
"""

import sys, os, json, time, threading, numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from scope import Scope

# PORT = TCP port to listen on. HERE = the folder holding this file.
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
HERE = os.path.dirname(os.path.abspath(__file__))
# U = samples per microsecond (16 MS/s). Times in samples are written as <microseconds> * U.
U = 16
# FS = volts at the tip of a x10 probe that correspond to 128 ADC counts, for each range.
FS = {"100mV": 5.0, "250mV": 10.0, "500mV": 25.0, "1V": 50.0}
# Z = zero level in ADC counts for each range and channel: Z[range]["ch1_zero" or "ch2_zero"].
Z = json.load(open(os.path.join(HERE, "scope_zero.json")))
# lock protects the frame, its number and its time, which are replaced together.
lock = threading.Lock()
# st = everything shared between the capture thread and the HTTP handlers:
#   r          the two ranges wanted for the live view [CH1, CH2]
#   frame      latest live frame: (CH1 counts, CH2 counts, [range1, range2]) or None
#   n, t       number of frames captured so far, and time.time() of the latest
#   recording  name of the recording in progress, or None
#   err        text of the last error, or None once a capture has succeeded again
#   req        a recording request waiting for the capture thread to pick it up, or None
#   done       set by the capture thread when the requested recording has finished or failed
#   result     what /record answers: ok, path, bytes, ranges, or ok=False and err
st = dict(
    r=["500mV", "500mV"],
    frame=None,
    n=0,
    t=0.0,
    recording=None,
    err=None,
    req=None,
    done=threading.Event(),
    result=None,
)


def volts(raw, ch, r):
    """Convert raw samples to volts at the tip of a x10 probe.

    raw: uint8 array of ADC counts; ch: channel index, 0 for CH1 or 1 for CH2; r: range name.
    Returns a float32 array: (counts - zero level of that range and channel) * FS[r] / 128.
    """
    return (raw.astype(np.float32) - Z[r]["ch%d_zero" % (ch + 1)]) * FS[r] / 128


def loop():
    """Capture thread: the only code that touches the scope. Never returns.

    Each pass either serves a pending recording request or captures one live frame, then
    publishes the frame in st. After any error it waits, reopens the scope and carries on.
    """
    # cur = the ranges the scope is currently set to, or None if it has to be set up again.
    sc = Scope()
    cur = None
    while True:
        try:
            req = st["req"]
            # A recording was asked for: set the requested ranges, capture the requested amount
            # in one go at 16 MS/s on two channels, and save it.
            if req is not None:
                st["req"] = None
                st["recording"] = req["name"]
                r = [req["r1"], req["r2"]]
                sc.setup(16, r[0], r[1], 2)
                cur = list(r)
                st["r"] = list(r)
                a = np.concatenate(sc.capture(int(req["mb"] * (1 << 20))))
                path = os.path.join(HERE, "out", req["name"] + ".npy")
                np.save(path, a)
                # The daemon runs under sudo, so the file would belong to root. Hand it to the user
                # who ran sudo, so that it can be fetched with scp. Failure here is ignored.
                try:
                    os.chown(
                        path, int(os.environ.get("SUDO_UID", 0)), int(os.environ.get("SUDO_GID", 0))
                    )
                except Exception:
                    pass
                # Publish the result and wake up the HTTP handler waiting in /record.
                st["result"] = dict(ok=True, path=path, bytes=int(len(a)), ranges=r)
                st["recording"] = None
                st["done"].set()
                a = a[-(2 << 20) :]  # show its tail as the live frame
            else:
                # Live view: apply a range change if one was asked for, then capture one frame.
                # 2 << 20 bytes = 2 MiB = 1 MiB of samples per channel.
                if cur != st["r"]:
                    cur = list(st["r"])
                    sc.setup(16, cur[0], cur[1], 2)
                a = np.concatenate(
                    sc.capture(2 << 20, chunk=1 << 20)
                )  # 65 ms: always holds one whole trial
            # n = samples per channel. Split the interleaved bytes into CH1 (even positions) and CH2
            # (odd positions) and publish them as the new frame.
            n = len(a) // 2
            with lock:
                st["frame"] = (a[0 : 2 * n : 2].copy(), a[1 : 2 * n : 2].copy(), list(cur))
                st["n"] += 1
                st["t"] = time.time()
                st["err"] = None
        # Anything went wrong (typically a USB error). Record it for the clients.
        except Exception as e:
            st["err"] = repr(e)
            st["recording"] = None
            # If a recording was in progress (its request already taken, no result yet), make
            # /record answer with the error instead of waiting for its timeout. This also fires
            # after a failed live capture when no recording is pending, which is harmless.
            if st["req"] is None and not st["done"].is_set():
                st["result"] = dict(ok=False, err=repr(e))
                st["done"].set()
            # Reopen the scope after a short pause. Scope() exits with SystemExit when the scope is
            # absent, hence BaseException; in that case wait 2 s more before the next pass.
            time.sleep(0.5)
            try:
                sc = Scope()
                cur = None
            except BaseException as e2:
                st["err"] = "scope: %s" % e2
                time.sleep(2)


def edges(v, thr):
    """Find the fast steps in a trace.

    v: one channel in volts; thr: smallest step that counts, in volts.
    A step is a change of more than thr between two samples that are 4 samples (0.25 us)
    apart. Steps that start within 8 us of the previous reported one are taken as the same
    edge. Returns a list of (sample number, signed step in volts), in time order.
    """
    # d[i] = change of v from sample i to sample i + 4.
    d = v[4:] - v[:-4]
    idx = np.flatnonzero(np.abs(d) > thr)
    if not len(idx):
        return []
    # Keep the first index of each group; a new group starts more than 8 us after the last kept.
    out = [(int(idx[0]), float(d[idx[0]]))]
    for i in idx:
        if i - out[-1][0] > 8 * U:
            out.append((int(i), float(d[i])))
    return out


def find_trigger(v, mode, minstep):
    """Choose the sample to centre the zoomed view on.

    v: the trigger channel in volts; mode: "pair", "rise", "fall", "big" or "none";
    minstep: smallest step, in volts, that may count as an edge.
    Returns a sample number, or None if nothing qualifies (or mode is "none").
    """
    # span = the trace's peak-to-peak size in volts, ignoring the most extreme 0.1 % at each
    # end, estimated on one sample in 16.
    span = float(np.percentile(v[::16], 99.9) - np.percentile(v[::16], 0.1))
    if mode == "none" or span <= 0:
        return None
    # Edges are steps of more than 40 % of the span (and at least minstep). Those within
    # 100 us of either end of the frame are dropped so that the zoom window fits.
    ev = [e for e in edges(v, max(span * 0.4, minstep)) if 100 * U < e[0] < len(v) - 100 * U]
    if not ev:
        return None
    # pair: the first edge that follows another edge by less than 300 us. If there is no
    # such pair, fall back to the biggest step.
    if mode == "pair":
        for a, b in zip(ev, ev[1:]):
            if b[0] - a[0] < 300 * U:
                return b[0] + 2
        mode = "big"
    # rise / fall: keep only edges of that direction; the first one is returned at the end.
    if mode == "rise":
        ev = [e for e in ev if e[1] > 0]
    if mode == "fall":
        ev = [e for e in ev if e[1] < 0]
    if not ev:
        return None
    # The + 2 moves from the start of the 4-sample difference to its middle.
    if mode == "big":
        return max(ev, key=lambda e: abs(e[1]))[0] + 2
    return ev[0][0] + 2


def columns(v, lo, hi, cols=700):
    """Reduce v[lo:hi] to something a page can draw.

    v: trace in volts; lo, hi: sample range (clipped to the trace); cols: number of columns.
    If the range holds at most 2 * cols samples, returns (samples, None, lo, hi). Otherwise
    the range is cut into cols equal groups and the result is (minimum of each group,
    maximum of each group, lo, end of the last whole group). Values are rounded to 1 mV.
    """
    lo = max(lo, 0)
    hi = min(hi, len(v))
    seg = v[lo:hi]
    if len(seg) <= 2 * cols:
        return [round(float(x), 3) for x in seg], None, lo, hi
    # k = samples per column; the remainder that does not fill a column is dropped.
    k = len(seg) // cols
    seg = seg[: k * cols].reshape(cols, k)
    return (
        [round(float(x), 3) for x in seg.min(axis=1)],
        [round(float(x), 3) for x in seg.max(axis=1)],
        lo,
        lo + k * cols,
    )


def live(q):
    """Build the answer to /live.

    q: the parsed query string (dict of lists, as parse_qs returns it).
    Returns a dict: n (frame number), age (seconds since the frame was captured), recording,
    err, ranges; and, once a frame exists: trig (true if a trigger was found), trig_ms
    (position of the zoom centre in the frame, ms), frame_ms (frame length, ms) and ch, a list
    with one entry per channel holding the whole frame (over_lo, over_hi) and the zoom window
    (zoom_lo, zoom_hi, with t0 and t1 = its start and end in microseconds relative to the
    trigger), as produced by columns(), plus the frame's min, max and mean in volts.
    """
    with lock:
        fr = st["frame"]
        n = st["n"]
        t = st["t"]
    out = dict(
        n=n,
        age=time.time() - t if t else None,
        recording=st["recording"],
        err=st["err"],
        ranges=st["r"],
    )
    if fr is None:
        return out
    # pre, post = window before / after the trigger in microseconds. tch = trigger channel
    # index (0 or 1). v = both channels in volts, using the ranges the frame was taken with.
    pre = float(q.get("pre", ["20"])[0])
    post = float(q.get("post", ["80"])[0])
    mode = q.get("trig", ["pair"])[0]
    tch = int(q.get("ch", ["1"])[0]) - 1
    v = [volts(fr[0], 0, fr[2][0]), volts(fr[1], 1, fr[2][1])]
    # N = samples per channel in the frame.
    N = len(v[0])
    trig = find_trigger(v[tch], mode, 6 * FS[fr[2][tch]] / 128)  # a step under 6 counts is noise
    # c = sample the zoom is centred on. Without a trigger it is placed so that the window
    # starts at the beginning of the frame.
    c = trig if trig is not None else int(pre * U)
    out.update(
        ranges=fr[2], trig=trig is not None, trig_ms=c / U / 1000.0, frame_ms=N / U / 1000.0, ch=[]
    )
    for k in (0, 1):
        # Whole frame, then the window from pre us before c to post us after it. a, b = the
        # sample range actually returned for the window.
        olo, ohi, _, _ = columns(v[k], 0, N)
        zlo, zhi, a, b = columns(v[k], int(c - pre * U), int(c + post * U))
        out["ch"].append(
            dict(
                over_lo=olo,
                over_hi=ohi,
                zoom_lo=zlo,
                zoom_hi=zhi,
                t0=(a - c) / U,
                t1=(b - c) / U,
                min=float(v[k].min()),
                max=float(v[k].max()),
                mean=float(v[k].mean()),
            )
        )
    return out


class H(BaseHTTPRequestHandler):
    """HTTP request handler: every request is a GET answered with JSON."""

    def log_message(self, *a):
        """Suppress the per-request log lines that the base class prints."""
        pass

    def do_GET(self):
        """Answer /live, /set, /record or (any other path) a status summary.

        Errors while handling a request are returned as {"ok": false, "err": ...} with HTTP
        status 400.
        """
        # u = the parsed URL, q = its query parameters (each value is a list).
        u = urlparse(self.path)
        q = parse_qs(u.query)
        code = 200
        try:
            if u.path == "/live":
                body = live(q)
            # /set: change the live-view ranges. A missing r1 or r2 keeps the current one. The
            # capture thread applies the change before its next frame.
            elif u.path == "/set":
                r = [q.get("r1", [st["r"][0]])[0], q.get("r2", [st["r"][1]])[0]]
                if r[0] not in FS or r[1] not in FS:
                    raise ValueError("unknown range")
                st["r"] = r
                body = dict(ok=True, ranges=r)
            # /record: hand a request to the capture thread and wait for it. basename() keeps
            # the file inside the "out" folder whatever name is sent.
            elif u.path == "/record":
                req = dict(
                    name=os.path.basename(q["name"][0]),
                    mb=float(q.get("mb", ["16"])[0]),
                    r1=q.get("r1", [st["r"][0]])[0],
                    r2=q.get("r2", [st["r"][1]])[0],
                )
                if req["r1"] not in FS or req["r2"] not in FS or not 0 < req["mb"] <= 256:
                    raise ValueError("bad request")
                # Clear the previous result, post the request, then wait up to 60 s for the
                # capture thread to signal that it is done. There is a single request slot: two
                # /record requests at the same time are not handled.
                st["done"].clear()
                st["result"] = None
                st["req"] = req
                body = st["result"] if st["done"].wait(60) else dict(ok=False, err="timed out")
            # Any other path: a short status.
            else:
                body = dict(
                    ok=True, what="scope daemon", frames=st["n"], ranges=st["r"], err=st["err"]
                )
        except Exception as e:
            body = dict(ok=False, err=repr(e))
            code = 400
        # Send the answer. The Access-Control header lets a page served from another computer
        # (scope_page.py's page, served by the Mac) read it; no-store keeps browsers from
        # reusing an old frame.
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# Start-up: make sure the recordings folder exists, start the capture thread, and serve HTTP
# on every network interface until the process is killed.
os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
threading.Thread(target=loop, daemon=True).start()
ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
