"""Live probe-compensation page, to run on the computer the scope is plugged into (the Pi).
usage: sudo python3 scope_live.py [port, default 8000]   then open http://<that computer>:8000
Captures the calibration square wave continuously at 16 MS/s and shows each channel's average
rising edge and how far it overshoots (+) or undershoots (-) the level it settles to. Exits after
30 min.

Needs: scope.py in the same folder, the scope with its sigrok firmware loaded, and a probe on the
scope's calibration output for each channel to be trimmed. Both channels are set to the 250mV
range. It opens the scope itself and uses the same default port as scope_daemon.py, so the two
are not meant to run together.
Serves: "/" (the page, held in PAGE below) and "/data" (the latest analysis as JSON). Writes no
file and prints nothing. The numbers are in raw ADC counts and percent; scope_zero.json is not
used. scope_comp.py does the same measurement once, from the Mac, with a picture.
"""

import sys, json, time, threading, numpy as np
from http.server import BaseHTTPRequestHandler, HTTPServer
from scope import Scope

# PORT = TCP port to listen on. U = samples per microsecond (16 MS/s).
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
U = 16
# state = what the capture thread publishes for the HTTP handler: t = time of the latest capture,
# ch = analysis result for [CH1, CH2], n = number of captures so far, and "err" (added on the
# first failure) = text of the last error.
state = {"t": 0, "ch": [None, None], "n": 0}


def analyse(v):
    """Measure the overshoot of the average rising edge of a square wave.

    v: one channel's raw samples (ADC counts) at 16 MS/s.
    Returns dict(ok=False, span=size of the signal in counts) if no square wave is found.
    Otherwise dict(ok=True, over, counts, curve): over = overshoot (+) or undershoot (-) just
    after the edge, in percent of the step; counts = height of the step in ADC counts;
    curve = the averaged edge from 100 us before to 400 us after, one point per 2 us, in
    percent of the step (0 = low level, 100 = settled level).
    """
    v = v.astype(np.float32)
    # sm = v smoothed over k = 32 samples (2 us), used only to find the edges.
    k = 2 * U
    sm = np.convolve(v, np.ones(k) / k, "same")
    # lo, hi = low and high levels of the wave (5th and 95th percentiles). Less than 4 counts
    # apart means there is no usable square wave.
    lo, hi = np.percentile(sm, 5), np.percentile(sm, 95)
    if hi - lo < 4:
        return dict(ok=False, span=float(hi - lo))
    # up = samples where the smoothed wave rises through the midpoint. Edges closer than 150 us
    # to the start or 450 us to the end are dropped so that the slices below fit; at least 3
    # edges are required.
    mid = (lo + hi) / 2
    up = np.flatnonzero((sm[:-1] < mid) & (sm[1:] >= mid))
    up = up[(up > 150 * U) & (up < len(v) - 450 * U)]
    if len(up) < 3:
        return dict(ok=False, span=float(hi - lo))
    # seg = average over all edges of the raw samples from 100 us before to 400 us after.
    seg = np.mean([v[u - 100 * U : u + 400 * U] for u in up], axis=0)
    # low = level before the edge (100 to 25 us before it). settled = level 300 to 380 us after
    # it. amp = height of the step. early = level 5 to 15 us after the edge.
    low = seg[: 75 * U].mean()
    settled = seg[400 * U : 480 * U].mean()
    amp = settled - low
    early = seg[105 * U : 115 * U].mean()
    curve = ((seg - low) / amp * 100).reshape(-1, 2 * U).mean(axis=1)  # one point per 2 us
    return dict(
        ok=True,
        over=float((early - settled) / amp * 100),
        counts=float(amp),
        curve=[round(float(c), 1) for c in curve],
    )


def loop():
    """Capture thread: capture and analyse over and over for 30 minutes, then end the program.

    Each capture is 1 MiB of interleaved bytes, about 33 ms per channel. An error is recorded
    in state["err"] and the loop carries on after half a second; a later success does not
    clear it.
    """
    sc = Scope()
    sc.setup(16, "250mV", "250mV", 2)
    # t_end = time to stop: 1800 s after starting.
    t_end = time.time() + 1800
    while time.time() < t_end:
        try:
            # Even bytes are CH1, odd bytes are CH2.
            a = np.concatenate(sc.capture(1 << 20, chunk=1 << 19))
            state["ch"] = [analyse(a[0::2]), analyse(a[1::2])]
            state["t"] = time.time()
            state["n"] += 1
        except Exception as e:
            state["err"] = str(e)
            time.sleep(0.5)
    # os._exit ends the whole process at once, HTTP server included.
    import os

    os._exit(0)


# The page. It shows one card per channel (CH1 yellow, CH2 blue) with the overshoot as a large
# number, a one-line verdict and a plot of the averaged rising edge (vertical axis 60 % to 150 %
# of the step, dashed line at 100 %, 500 us across). The number is green below 2 %, yellow below
# 6 %, red beyond. Its script fetches /data, redraws, and asks again 200 ms later; the bottom
# line gives the capture number, its age and any error.
PAGE = """<!doctype html><meta charset=utf-8><title>Probe trim</title>
<style>body{font-family:system-ui,sans-serif;background:#16181c;color:#e8e8e8;margin:16px}
.row{display:flex;gap:16px;flex-wrap:wrap}.card{flex:1;min-width:320px;background:#22252b;border-radius:10px;padding:14px}
.num{font-size:84px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}.hint{font-size:20px;margin:6px 0 10px}
canvas{width:100%;height:260px;background:#111;border-radius:6px}small{color:#9aa}</style>
<h2>Probe trim: turn the screw until the number reads 0 and the top is flat</h2>
<div class=row><div class=card><div style="color:#e6c229">CH1 yellow</div><div class=num id=n0>–</div><div class=hint id=h0></div><canvas id=c0 width=700 height=260></canvas></div>
<div class=card><div style="color:#4f9cff">CH2 blue</div><div class=num id=n1>–</div><div class=hint id=h1></div><canvas id=c1 width=700 height=260></canvas></div></div>
<p><small id=st></small></p>
<script>
const col=['#e6c229','#4f9cff'];
function draw(i,d){const c=document.getElementById('c'+i),g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);
 const y=v=>c.height-20-(v-60)/(150-60)*(c.height-40);            // 60 %..150 % of the step
 g.strokeStyle='#555';g.setLineDash([5,5]);g.beginPath();g.moveTo(0,y(100));g.lineTo(c.width,y(100));g.stroke();g.setLineDash([]);
 g.fillStyle='#889';g.font='12px sans-serif';g.fillText('100 % = settled level',6,y(100)-6);g.fillText('rising edge, 500 us across',6,c.height-6);
 if(!d||!d.ok)return;g.strokeStyle=col[i];g.lineWidth=2;g.beginPath();
 d.curve.forEach((v,k)=>{const x=k/d.curve.length*c.width;k?g.lineTo(x,y(Math.max(55,Math.min(155,v)))):g.moveTo(x,y(Math.max(55,v)))});g.stroke();}
async function tick(){try{const r=await fetch('/data');const s=await r.json();
 s.ch.forEach((d,i)=>{const n=document.getElementById('n'+i),h=document.getElementById('h'+i);
  if(!d||!d.ok){n.textContent='–';h.textContent='no square wave on this channel';draw(i,null);return}
  const o=d.over;n.textContent=(o>=0?'+':'')+o.toFixed(1)+' %';n.style.color=Math.abs(o)<2?'#5fd16a':Math.abs(o)<6?'#e6c229':'#ff6b5f';
  h.textContent=Math.abs(o)<2?'good':(o>0?'overshoots: edge too high':'undershoots: edge too low, rounded corner');draw(i,d)});
 document.getElementById('st').textContent='capture '+s.n+', '+(s.age).toFixed(1)+' s old'+(s.err?' — '+s.err:'');
}catch(e){document.getElementById('st').textContent='no answer from the Pi'}setTimeout(tick,200)}
tick();</script>"""


class H(BaseHTTPRequestHandler):
    """HTTP request handler: /data returns the latest analysis as JSON, anything else the page."""

    def log_message(self, *a):
        """Suppress the per-request log lines that the base class prints."""
        pass

    def do_GET(self):
        """Answer one request. For /data: ch (the two analyse() results), n, age in s, err."""
        if self.path.startswith("/data"):
            body = json.dumps(
                dict(
                    ch=state["ch"], n=state["n"], age=time.time() - state["t"], err=state.get("err")
                )
            ).encode()
            ct = "application/json"
        else:
            body = PAGE.encode()
            ct = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# Start the capture thread and serve HTTP on every network interface until loop() ends the
# process.
threading.Thread(target=loop, daemon=True).start()
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
