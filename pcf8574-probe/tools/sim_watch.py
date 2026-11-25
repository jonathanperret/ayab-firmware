"""Small local page that shows the fit of sim_fit.py as it runs.

usage: sim_watch.py [port, default 8011]     then open http://localhost:8011
Serves sim/live/fit.png (redrawn by sim_fit.py about once a second) and the list of
steps from sim/live/progress.json, with the circuit diagram of sim/schematic.svg and one bar per
search parameter. The page reloads its data every second. Local only."""
import os, sys, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim", "live")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8011
PAGE = """<!doctype html><meta charset=utf-8><title>Fit in progress</title>
<style>body{font-family:system-ui,sans-serif;background:#16181c;color:#e8e8e8;margin:14px}
img{width:100%;background:#fcfcfb;border-radius:6px}h2{margin:0 0 8px}
table{border-collapse:collapse;font-size:13px;margin-top:10px}td,th{padding:2px 10px;text-align:left;border-bottom:1px solid #2c2f36}
#st{font-size:16px;margin:6px 0}small{color:#9aa}</style>
<h2>Coil and driver model: fit in progress</h2><div id=st>waiting for the first step…</div>
<img id=im>
<h3 style="margin:14px 0 2px">Fit error as the search goes <small style="font-weight:normal;color:#9aa">(best so far; lower is better; the scale is logarithmic)</small></h3>
<canvas id=err width=1400 height=230 style="width:100%;height:230px;background:#22252b;border-radius:6px"></canvas>
<h3 style="margin:14px 0 2px">The circuit being simulated <small style="font-weight:normal;color:#9aa">(one coil and its driver channel; yellow figures are the best values so far)</small></h3>
<div id=schem style="max-width:1100px">__SCHEMATIC__</div>
<h3 style="margin:14px 0 2px">Where the search is looking</h3>
<div style="font-size:13px;color:#9aa;margin-bottom:6px">Each bar is one setting's allowed range. Grey ticks: settings tried earlier. Coloured ticks: the latest batch, greener = smaller error. White marker: the best so far.</div>
<div id=axes></div><table id=tb></table><p><small>dots: measured; lines: the model with the best values found so far</small></p>
<script>
const $=id=>document.getElementById(id);let last='';
const trace=new Map(),MCOL={'one inductance':'#8fb4ff','two inductances':'#ff9a5c'};
function drawError(s){(s.history||[]).forEach(e=>trace.set(e.model+'|'+Math.round(e.seconds*2),e));
 const pts=[...trace.values()].sort((a,b)=>a.seconds-b.seconds);if(pts.length<2)return;
 const c=$('err'),g=c.getContext('2d'),W=c.width,H=c.height,L=70,R=W-170,T=14,B=H-30;g.clearRect(0,0,W,H);g.font='13px sans-serif';
 const tmax=Math.max(10,pts[pts.length-1].seconds),lo=Math.max(1,Math.min(...pts.map(p=>p.rms_mV))*0.8),hi=Math.max(...pts.map(p=>p.rms_mV))*1.15;
 const X=t=>L+t/tmax*(R-L),Y=v=>B-(Math.log(v)-Math.log(lo))/(Math.log(hi)-Math.log(lo))*(B-T);
 [5,10,20,30,50,70,100,150,200,300,500].filter(v=>v>lo&&v<hi).forEach(v=>{g.strokeStyle='#343841';g.beginPath();g.moveTo(L,Y(v));g.lineTo(R,Y(v));g.stroke();g.fillStyle='#9aa';g.textAlign='right';g.fillText(v+' mV',L-8,Y(v)+4)});
 const step=tmax>240?60:tmax>80?20:10;for(let t=0;t<=tmax;t+=step){g.fillStyle='#9aa';g.textAlign='center';g.fillText(t+' s',X(t),H-10)}
 Object.keys(MCOL).forEach(m=>{const q=pts.filter(p=>p.model===m);if(!q.length)return;g.strokeStyle=MCOL[m];g.lineWidth=2.5;g.beginPath();q.forEach((p,k)=>k?g.lineTo(X(p.seconds),Y(p.rms_mV)):g.moveTo(X(p.seconds),Y(p.rms_mV)));g.stroke();
  const e=q[q.length-1];g.fillStyle=MCOL[m];g.beginPath();g.arc(X(e.seconds),Y(e.rms_mV),4,0,7);g.fill();g.textAlign='left';g.fillText(m+': '+e.rms_mV.toFixed(1)+' mV',X(e.seconds)+10,Y(e.rms_mV)+(m==='one inductance'?-8:14))})}
const UNIT=[' mH',' mH',' Ω','','','',' V'];
function fillSchematic(s){if(!s.axes)return;s.axes.forEach((a,i)=>{const e=$('v-'+i);if(e)e.textContent=a.used?a.best_text+UNIT[i]:'not used'});
 const g=$('g-two');if(g)g.style.opacity=s.axes[1].used?1:0.25}
function drawAxes(s){fillSchematic(s);const box=$('axes');if(!s.axes)return;
 if(box.children.length!==s.axes.length){box.innerHTML='';s.axes.forEach((a,i)=>{const d=document.createElement('div');d.style.cssText='display:flex;align-items:center;gap:10px;margin:3px 0';
   d.innerHTML='<div style="width:250px;font-size:13px" id=an'+i+'></div><div style="width:64px;text-align:right;font-size:12px;color:#9aa" id=al'+i+'></div><canvas id=ac'+i+' width=900 height=34 style="flex:1;height:34px;background:#22252b;border-radius:5px"></canvas><div style="width:64px;font-size:12px;color:#9aa" id=ah'+i+'></div><div style="width:90px;font-size:15px;font-weight:600" id=ab'+i+'></div>';box.appendChild(d)})}
 const batch=s.per_step||70;
 s.axes.forEach((a,i)=>{$('an'+i).textContent=a.name;$('an'+i).style.opacity=a.used?1:0.35;$('al'+i).textContent=a.lo;$('ah'+i).textContent=a.hi;$('ab'+i).textContent=a.used?a.best_text:'not used';
  const c=$('ac'+i),g=c.getContext('2d'),W=c.width,H=c.height;g.clearRect(0,0,W,H);if(!a.used)return;
  const X=p=>6+Math.max(0,Math.min(1,p))*(W-12),n=a.pts.length;
  const errs=a.pts.slice(-batch).map(p=>p[1]),lo=Math.min(...errs),hi=Math.max(...errs);
  a.pts.forEach((p,k)=>{const recent=k>=n-batch;if(recent){const f=hi>lo?(p[1]-lo)/(hi-lo):0;g.fillStyle='hsl('+Math.round(125*(1-Math.min(1,f)))+',75%,55%)';g.fillRect(X(p[0])-1.5,6,3,H-12)}
   else{g.fillStyle='rgba(160,165,175,0.28)';g.fillRect(X(p[0])-1,11,2,H-22)}});
  g.fillStyle='#fff';const x=X(a.best);g.fillRect(x-1.5,1,3,H-2);g.beginPath();g.moveTo(x-6,0);g.lineTo(x+6,0);g.lineTo(x,7);g.fill()})}
async function tick(){try{const s=await (await fetch('/progress?'+Date.now())).json();const h=s.history||[];
 if(h.length){const e=h[h.length-1],key=e.model+e.generation+'/'+(e.evaluations||0);
  $('st').textContent=(s.running?'Running: ':'Finished: ')+e.model+', step '+e.generation+' of '+e.of+', '+(e.evaluations||0)+' settings tried, error '+e.rms_mV.toFixed(1)+' mV, '+Math.round(e.seconds)+' s elapsed';
  drawError(s);
  if(key!==last){drawAxes(s);last=key;$('im').src='/fit.png?'+Date.now();
   $('tb').innerHTML='<tr><th>model</th><th>step</th><th>error, mV</th><th>best values so far</th></tr>'+h.slice(-14).reverse().map(r=>'<tr><td>'+r.model+'</td><td>'+r.generation+'</td><td>'+r.rms_mV.toFixed(1)+'</td><td>'+r.text+'</td></tr>').join('')}}
 }catch(e){$('st').textContent='nothing to show yet'}setTimeout(tick,1000)}
tick();</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/progress":
                body = open(os.path.join(LIVE, "progress.json"), "rb").read(); ct = "application/json"
            elif path == "/fit.png":
                body = open(os.path.join(LIVE, "fit.png"), "rb").read(); ct = "image/png"
            else:
                svg = open(os.path.join(os.path.dirname(LIVE), "schematic.svg")).read()
                body = PAGE.replace("__SCHEMATIC__", svg).encode(); ct = "text/html; charset=utf-8"
        except FileNotFoundError:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
