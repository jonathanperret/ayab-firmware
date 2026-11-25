"""Local page showing the scope captures as they are taken.
usage: scope_page.py <dir> [<dir> ...] [--port 8010]   then open http://localhost:8010
Lists the scope*.png / *.png pictures of the given folders, newest first, and reloads by itself.

Runs on the Mac and only listens on localhost. From the first folder every .png is listed; from
the other folders only those whose name starts with "scope". At most the 40 newest are shown.
The pictures themselves are made by other scripts (scope_trial.py writes one per capture).
The top of the page is a live oscilloscope view: the browser fetches frames directly from
scope_daemon.py on the Pi, at the address hard-coded in the page (http://raspberrypi.local:8000).
Serves: "/" (the page, held in PAGE below), "/list" (the pictures as JSON) and "/img" (one
picture). Writes no file and prints nothing; it runs until killed.
"""

import sys, os, json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Command line: take out "--port N" if present; what remains is the list of folders.
args = sys.argv[1:]
PORT = 8010
if "--port" in args:
    i = args.index("--port")
    PORT = int(args[i + 1])
    del args[i : i + 2]
DIRS = [os.path.abspath(d) for d in args]


def pictures():
    """List the pictures to show.

    Returns a list of dicts, newest first, at most 40: d = index of the folder in DIRS,
    f = file name, t = modification time (seconds since the epoch), s = size in bytes.
    """
    out = []
    for k, d in enumerate(DIRS):
        for f in os.listdir(d):
            if f.endswith(".png") and (k == 0 or f.startswith("scope")):
                p = os.path.join(d, f)
                out.append(dict(d=k, f=f, t=os.path.getmtime(p), s=os.path.getsize(p)))
    # Newest first; keep the first 40.
    out.sort(key=lambda x: -x["t"])
    return out[:40]


# The page, in two parts.
# Captures (lower part): every 2 s its script fetches /list, rebuilds the row of thumbnails and,
# if a new picture has appeared and "always show the newest" is ticked, shows it large with a
# "new" badge for 8 s. Clicking a thumbnail shows that picture and unticks the box. Picture
# addresses carry the file time (t) so that a rewritten file is fetched again.
# Live view (upper part): its script polls scope_daemon.py's /live about every 150 ms (1.5 s
# after a failure) with the chosen window (microseconds before,after the trigger), trigger mode
# and trigger channel, and draws two canvases: the window around the trigger, and the whole
# frame with a white bar at the trigger. Each channel has its own self-scaling voltage axis
# (yellow labels on the left, blue on the right). Changing a range selector calls the daemon's
# /set. "pause" stops polling; "keep the last triggered frame" leaves the drawing alone while
# frames come without a trigger. The status line shows the frame number and each channel's
# minimum and maximum in volts.
PAGE = """<!doctype html><meta charset=utf-8><title>Scope captures</title>
<style>body{font-family:system-ui,sans-serif;background:#16181c;color:#e8e8e8;margin:14px}
h2{margin:0 0 8px}#cap{font-size:18px;margin:6px 0}#main{max-width:100%;background:#fff;border-radius:6px}
#new{display:inline-block;background:#5fd16a;color:#000;border-radius:5px;padding:1px 8px;margin-left:8px;font-size:14px;visibility:hidden}
#list{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.th{width:210px;cursor:pointer;background:#22252b;border-radius:6px;padding:5px;font-size:12px;border:2px solid transparent}
.th img{width:100%;background:#fff;border-radius:3px}.th.sel{border-color:#4f9cff}small{color:#9aa}label{font-size:14px;margin-left:14px}canvas{width:100%;background:#0d0f12;border-radius:6px;margin-top:6px;display:block}#ctl{font-size:14px}select{background:#22252b;color:#e8e8e8;border:1px solid #444;border-radius:4px;padding:2px}</style>
<h2>Live from the scope <small id=lst style="font-weight:normal"></small></h2>
<div id=ctl>window <select id=win><option value="2,6">8 us<option value="20,80" selected>100 us<option value="150,350">500 us<option value="500,4500">5 ms<option value="2000,18000">20 ms</select>
 trigger <select id=trig><option value=pair selected>second edge of a pair (the back-on)<option value=big>biggest step<option value=rise>first rising<option value=fall>first falling<option value=none>none</select>
 on <select id=tch><option value=1>yellow<option value=2>blue</select>
 yellow <select id=r1></select> blue <select id=r2></select>
 <label><input type=checkbox id=pause> pause</label> <label><input type=checkbox id=hold> keep the last triggered frame</label></div>
<canvas id=zoom width=1400 height=380></canvas><canvas id=over width=1400 height=150></canvas>
<h2 style="margin-top:18px">Captures <label><input type=checkbox id=follow checked> always show the newest</label></h2>
<div id=cap></div><img id=main><div id=list></div><p><small id=st></small></p>
<script>
let shown=null,newest=null;const $=id=>document.getElementById(id);
const url=p=>'/img?d='+p.d+'&f='+encodeURIComponent(p.f)+'&t='+p.t;
const when=t=>new Date(t*1000).toLocaleTimeString();
function show(p,fresh){shown=p.f;$('main').src=url(p);$('cap').innerHTML=p.f+' <small>'+when(p.t)+'</small><span id=new>new</span>';
 if(fresh){$('new').style.visibility='visible';setTimeout(()=>{const n=$('new');if(n)n.style.visibility='hidden'},8000)}}
async function tick(){try{const l=await (await fetch('/list')).json();
 if(l.length){const key=l[0].f+l[0].t;if(key!==newest){const first=newest===null;newest=key;if($('follow').checked||first)show(l[0],!first)}}
 $('list').innerHTML='';l.forEach(p=>{const d=document.createElement('div');d.className='th'+(p.f===shown?' sel':'');
  d.innerHTML='<img loading=lazy src="'+url(p)+'"><div>'+p.f+'</div><small>'+when(p.t)+'</small>';d.onclick=()=>{$('follow').checked=false;show(p,false);tick()};$('list').appendChild(d)});
 $('st').textContent=l.length+' pictures, checked '+new Date().toLocaleTimeString()}catch(e){$('st').textContent='page server not answering'}}
tick();setInterval(tick,2000);
// ---- live view, fed by scope_daemon.py on the Pi
const PI='http://raspberrypi.local:8000',COL=['#e6c229','#4f9cff'],RNG=['100mV','250mV','500mV','1V'];
['r1','r2'].forEach(id=>{RNG.forEach(r=>{const o=document.createElement('option');o.textContent=r;$(id).appendChild(o)});$(id).onchange=()=>fetch(PI+'/set?r1='+$('r1').value+'&r2='+$('r2').value)});
function nice(lo,hi){if(hi-lo<0.2){const m=(hi+lo)/2;lo=m-0.1;hi=m+0.1}const p=(hi-lo)*0.08;return[lo-p,hi+p]}
function trace(g,c,d,key,x0,x1,y0,y1,color){const lo=d[key+'_lo'],hi=d[key+'_hi'];if(!lo)return;const n=lo.length,X=k=>x0+(n>1?k/(n-1):0)*(x1-x0),Y=v=>y1-(v-c[0])/(c[1]-c[0])*(y1-y0);
 g.strokeStyle=color;g.lineWidth=1.4;g.beginPath();
 if(hi){for(let k=0;k<n;k++){g.moveTo(X(k),Y(lo[k]));g.lineTo(X(k),Y(hi[k])-1)}for(let k=0;k<n;k++){k?g.lineTo(X(k),Y((lo[k]+hi[k])/2)):g.moveTo(X(k),Y((lo[k]+hi[k])/2))}}
 else{for(let k=0;k<n;k++){k?g.lineTo(X(k),Y(lo[k])):g.moveTo(X(k),Y(lo[k]))}}g.stroke();
 if(!hi&&n<400){g.fillStyle=color;for(let k=0;k<n;k++)g.fillRect(X(k)-1.5,Y(lo[k])-1.5,3,3)}}
function panel(id,s,key,label){const cv=$(id),g=cv.getContext('2d'),W=cv.width,H=cv.height,L=64,R=W-64,T=14,B=H-26;g.clearRect(0,0,W,H);g.font='13px sans-serif';
 g.strokeStyle='#2a2e35';g.lineWidth=1;for(let i=0;i<=4;i++){const y=T+i*(B-T)/4;g.beginPath();g.moveTo(L,y);g.lineTo(R,y);g.stroke()}for(let i=0;i<=10;i++){const x=L+i*(R-L)/10;g.beginPath();g.moveTo(x,T);g.lineTo(x,B);g.stroke()}
 s.ch.forEach((d,i)=>{const lo=d[key+'_lo'],hi=d[key+'_hi']||lo;if(!lo||!lo.length)return;const c=nice(Math.min(...lo),Math.max(...hi));trace(g,c,d,key,L,R,T,B,COL[i]);
  g.fillStyle=COL[i];for(let j=0;j<=4;j++){const v=c[1]-j*(c[1]-c[0])/4,t=v.toFixed(Math.abs(c[1]-c[0])<2?2:1);g.textAlign=i?'left':'right';g.fillText(t,i?R+6:L-6,T+j*(B-T)/4+4)}});
 g.fillStyle='#9aa';g.textAlign='center';const d=s.ch[0];
 if(key==='zoom'){for(let i=0;i<=10;i+=2){const t=d.t0+i*(d.t1-d.t0)/10;g.fillText(Math.abs(d.t1-d.t0)>=2000?(t/1000).toFixed(1)+' ms':t.toFixed(Math.abs(d.t1-d.t0)<20?1:0)+' us',L+i*(R-L)/10,H-8)}
  if(s.trig&&d.t0<0){const x=L+(0-d.t0)/(d.t1-d.t0)*(R-L);g.strokeStyle='#888';g.setLineDash([4,4]);g.beginPath();g.moveTo(x,T);g.lineTo(x,B);g.stroke();g.setLineDash([])}}
 else{for(let i=0;i<=10;i+=2)g.fillText((i*s.frame_ms/10).toFixed(0)+' ms',L+i*(R-L)/10,H-8);if(s.trig){const x=L+s.trig_ms/s.frame_ms*(R-L);g.fillStyle='#fff';g.fillRect(x-1,T,2,B-T)}}
 g.textAlign='left';g.fillStyle='#9aa';g.fillText(label,L+8,T+14)}
let lastN=-1;
async function liveTick(){let wait=150;try{if(!$('pause').checked){const w=$('win').value.split(',');
  const s=await (await fetch(PI+'/live?pre='+w[0]+'&post='+w[1]+'&trig='+$('trig').value+'&ch='+$('tch').value)).json();
  if(s.ranges&&document.activeElement!==$('r1')&&document.activeElement!==$('r2')){$('r1').value=s.ranges[0];$('r2').value=s.ranges[1]}
  let msg=s.err?'scope error: '+s.err:(s.recording?'RECORDING '+s.recording+' … ':'')+'frame '+s.n+(s.ch?(s.trig?', triggered':', no trigger: showing the start of the frame'):'');
  if(s.ch&&s.n!==lastN&&!($('hold').checked&&!s.trig)){lastN=s.n;panel('zoom',s,'zoom','around the trigger');panel('over',s,'over','whole frame ('+s.frame_ms.toFixed(0)+' ms); white bar = trigger');
   msg+=' — yellow '+s.ch[0].min.toFixed(2)+' to '+s.ch[0].max.toFixed(2)+' V, blue '+s.ch[1].min.toFixed(2)+' to '+s.ch[1].max.toFixed(2)+' V'}
  $('lst').textContent=msg}}catch(e){$('lst').textContent='no answer from the scope server on the Pi';wait=1500}setTimeout(liveTick,wait)}
liveTick();</script>"""


class H(BaseHTTPRequestHandler):
    """HTTP request handler for the page, the picture list and the pictures."""

    def log_message(self, *a):
        """Suppress the per-request log lines that the base class prints."""
        pass

    def do_GET(self):
        """Answer one request.

        /list returns pictures() as JSON. /img?d=<folder index>&f=<file name> returns that PNG
        (only the base name of f is used, so nothing outside the listed folders can be read);
        any failure gives a 404. Every other path returns the page.
        """
        from urllib.parse import urlparse, parse_qs

        u = urlparse(self.path)
        q = parse_qs(u.query)
        ct = "text/html; charset=utf-8"
        body = PAGE.encode()
        if u.path == "/list":
            body = json.dumps(pictures()).encode()
            ct = "application/json"
        elif u.path == "/img":
            try:
                p = os.path.join(DIRS[int(q["d"][0])], os.path.basename(q["f"][0]))
                body = open(p, "rb").read()
                ct = "image/png"
            except Exception:
                self.send_error(404)
                return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# Serve on this computer only (127.0.0.1) until killed.
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
