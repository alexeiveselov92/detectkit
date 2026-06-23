"""Generate a self-contained HTML labeler for a metric series.

Emits a single HTML file (inline CSS/JS, no CDN) with the series embedded as a
JSON literal: a zoomable/pannable canvas chart where the user click-drags over
incident spans (with an optional per-incident description) and exports a labels
file in the canonical schema, fed back via
``dtk autotune --select <metric> --incidents <file-or-dir>``.

The page is offline-only — a browser cannot write to the project, so Export
downloads a **versioned** file (``<metric>-<UTC-stamp>.yml``); drop it into
``incidents/<metric>/`` to keep every labeling round (``--incidents`` accepts
that directory and uses the newest version).

Docs sync: the autotune reference page + landing embed a *live* copy of this
output (``docs/examples/autotune-labeler.html``) so the site always shows the
real UI. After changing the template below, regenerate that example so the docs
don't drift:  ``python website/scripts/gen-labeler-example.py``  (also in the
release checklist).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from detectkit.utils.json_utils import json_dumps_sorted


def _ts_to_str(ts64: np.datetime64) -> str:
    ms = int(ts64.astype("datetime64[ms]").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


# Built with .replace() (not .format()), so braces are literal — keep them single.
# Self-contained: inline brand styling/logo/JS, no network. Palette + fonts mirror
# website/src/styles/brand.css (.claude/rules/design.md); incident bands use the
# anomaly status color, the drag preview the no-data color.
_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>detectkit · label incidents · __METRIC__</title>
<style>
  :root {
    --clay:#d15b36; --clay-700:#b4471f; --paper:#f5f1e8; --muted:#6e675b; --faint:#9a9384;
    --term-bg:#211e1a; --term-surface:#1b1916; --term-border:#332f29; --term-text:#c9c2b4;
    --anomaly:#d63232; --nodata:#f0ad4e;
    --ui:'Schibsted Grotesk',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
    --mono:'JetBrains Mono',ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace;
  }
  * { box-sizing: border-box; }
  body { font-family: var(--ui); margin: 0; background: var(--term-bg); color: var(--term-text);
    -webkit-font-smoothing: antialiased; }
  .shell { max-width: 1080px; margin: 0 auto; padding: 22px 22px 44px; }
  .brand { display:flex; align-items:center; gap:9px; margin-bottom: 14px; }
  .brand svg { width: 26px; height: 26px; border-radius: 7px; display:block; }
  .brand b { color: var(--paper); font-weight: 600; font-size: 15px; letter-spacing: .2px; }
  .brand span { color: var(--faint); font-size: 12px; }
  h1 { font-size: 18px; line-height: 1.3; margin: 0 0 6px; color: var(--paper); font-weight: 600; }
  h1 code { color: var(--clay); font-family: var(--mono); font-size: .82em; }
  .hint { color: var(--faint); font-size: 13px; margin: 0 0 18px; line-height: 1.55; }
  .hint code, code.k { color: var(--term-text); font-family: var(--mono); font-size: 12px;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 5px; padding: 1px 6px; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom: 12px; }
  button { font-family: var(--ui); font-size: 13px; font-weight: 500; border: 0; border-radius: 7px;
    padding: 9px 15px; cursor: pointer; transition: background .12s ease, border-color .12s ease, color .12s ease; }
  button.primary { background: var(--clay); color: #fff; }
  button.primary:hover { background: var(--clay-700); }
  button.ghost { background: transparent; color: var(--term-text); border: 1px solid var(--term-border); }
  button.ghost:hover { border-color: var(--faint); color: var(--paper); }
  .summary { margin-left: auto; color: var(--faint); font-size: 12.5px; font-family: var(--mono); }
  .summary b { color: var(--clay); font-weight: 600; }
  canvas#c { width: 100%; height: clamp(300px, 44vh, 500px); display:block; touch-action: none;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 10px; cursor: crosshair; }
  .zoombar { display:flex; align-items:center; gap:8px; margin: 10px 0 6px; }
  .rangelbl { margin-left: auto; color: var(--faint); font-size: 12px; font-family: var(--mono); }
  canvas#ov { width: 100%; height: 66px; display:block; touch-action: none;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 10px; cursor: grab; }
  .navhint { color: var(--faint); font-size: 12px; margin: 7px 2px 0; }
  .empty { color: var(--faint); font-size: 13px; margin: 18px 2px; font-style: italic; }
  ul { list-style: none; margin: 16px 0 0; padding: 0; }
  li { display:flex; align-items:center; gap:11px; padding: 9px 12px; font-size: 13px; flex-wrap: wrap;
    border: 1px solid var(--term-border); border-radius: 8px; margin-bottom: 7px; background: var(--term-surface); }
  li .dot { width:9px; height:9px; border-radius:50%; background: var(--anomaly); flex: 0 0 auto; }
  li .span { font-family: var(--mono); color: var(--term-text); }
  li .dur { color: var(--faint); font-size: 12px; }
  li input.desc { flex: 1 1 220px; min-width: 160px; background: var(--term-bg); color: var(--paper);
    border: 1px solid var(--term-border); border-radius: 6px; padding: 6px 9px; font-family: var(--ui); font-size: 12.5px; }
  li input.desc::placeholder { color: var(--muted); }
  li input.desc:focus { outline: none; border-color: var(--clay); }
  li button { margin-left: auto; padding: 5px 11px; font-size: 12px; }
  footer { margin-top: 26px; padding-top: 14px; border-top: 1px solid var(--term-border);
    color: var(--faint); font-size: 12px; line-height: 1.6; }
  footer code { font-family: var(--mono); color: var(--term-text); }
</style>
<div class="shell">
  <div class="brand">
    <svg viewBox="0 0 100 100" aria-hidden="true"><rect x="3" y="3" width="94" height="94" rx="26" fill="#D15B36"/><polyline points="14,62 36,62 50,22 64,62 86,62" fill="none" stroke="#FBF9F3" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="50" cy="22" r="6.5" fill="#FBF9F3"/></svg>
    <b>detectkit</b><span>· incident labeler</span>
  </div>
  <h1>Label incidents — <code>__METRIC__</code></h1>
  <p class="hint">Click-drag across the chart to mark each real incident, add a short description, then
  <b>Export</b>. Save the file into <code class="k">incidents/__METRIC__/</code> and run
  <code class="k">dtk autotune --select __METRIC__ --incidents incidents/__METRIC__/</code></p>
  <div class="toolbar">
    <button id="export" class="primary">Export labels</button>
    <button id="clear" class="ghost">Clear all</button>
    <span id="summary" class="summary"></span>
  </div>
  <canvas id="c" aria-label="metric series — drag to mark an incident, scroll to zoom"></canvas>
  <div class="zoombar">
    <button id="zreset" class="ghost">Reset zoom</button>
    <span id="range" class="rangelbl"></span>
  </div>
  <canvas id="ov" aria-label="navigator — drag the window to pan, its edges to stretch the view"></canvas>
  <div class="navhint">Scroll to zoom where you point · double-click to reset · drag the navigator window
  below to move, or drag its edges to stretch / squeeze the view.</div>
  <div id="empty" class="empty">No incidents marked yet — drag across a span on the chart above.</div>
  <ul id="list"></ul>
  <footer>All times UTC · self-contained, nothing leaves your browser · re-label any time —
  exports are versioned (<code>__METRIC__-&lt;timestamp&gt;.yml</code>), so keep every round in
  <code>incidents/__METRIC__/</code>. Generated by <code>dtk autotune --label</code>.</footer>
</div>
<script>
const DATA = __PAYLOAD__;
const pts = DATA.points.map(p => ({ts: Date.parse(p.t.replace(' ','T')+'Z'), v: p.v}));
const N = pts.length;
const vraw = pts.filter(p => p.v !== null).map(p => p.v);
const vmin0 = vraw.length ? Math.min.apply(null, vraw) : 0;
const vmax0 = vraw.length ? Math.max.apply(null, vraw) : 1;
const vpad = (vmax0 - vmin0) * 0.06 || 1;
const vmin = vmin0 - vpad, vmax = vmax0 + vpad;
const tmin = N ? pts[0].ts : 0, tmax = N ? pts[N-1].ts : 1, fullSpan = (tmax - tmin) || 1;
const step = fullSpan / Math.max(1, N - 1);
const minSpan = Math.max(step * 8, 1000);
let viewMin = tmin, viewMax = tmax;
const incidents = [];
const c = document.getElementById('c'), ov = document.getElementById('ov');
const ctx = c.getContext('2d'), octx = ov.getContext('2d');
const M = {l:56, r:16, t:14, b:30}, OM = {l:56, r:16, t:8, b:8};
let dpr = 1, hover = null, dragging = null, ovAct = null;

const clamp = (x,a,b) => Math.max(a, Math.min(b, x));
const vspan = () => viewMax - viewMin;
const plotW = () => c.width - (M.l+M.r)*dpr;
const plotH = () => c.height - (M.t+M.b)*dpr;
const px = ts => M.l*dpr + (ts-viewMin)/(vspan()||1)*plotW();
const py = v => (c.height - M.b*dpr) - (v-vmin)/((vmax-vmin)||1)*plotH();
const ovWd = () => ov.width - (OM.l+OM.r)*dpr;
const ovHt = () => ov.height - (OM.t+OM.b)*dpr;
const ovpx = ts => OM.l*dpr + (ts-tmin)/fullSpan*ovWd();
const ovpy = v => (ov.height - OM.b*dpr) - (v-vmin)/((vmax-vmin)||1)*ovHt();
const pad2 = n => String(n).padStart(2,'0');
const fmtTs = ts => new Date(ts).toISOString().slice(0,19).replace('T',' ');
const fmtTick = (ts, sp) => { const s = new Date(ts).toISOString();
  return sp < 2*86400000 ? s.slice(5,16).replace('T',' ') : s.slice(5,10); };
const fmtVal = v => { const a = Math.abs(v); return a>=1000 ? v.toFixed(0) : a>=10 ? v.toFixed(1) : v.toFixed(2); };
function fmtDur(ms) { const m = Math.round(ms/60000); if (m<60) return m+'m';
  const h = Math.floor(m/60), mm = m%60; if (h<24) return h+'h'+(mm?(' '+mm+'m'):'');
  const d = Math.floor(h/24), hh = h%24; return d+'d'+(hh?(' '+hh+'h'):''); }
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const yamlStr = s => '"' + String(s).replace(/\\\\/g,'\\\\\\\\').replace(/"/g,'\\\\"') + '"';

function setView(a, b) {
  let s = b - a;
  if (s < minSpan) { const m=(a+b)/2; a=m-minSpan/2; b=m+minSpan/2; s=minSpan; }
  if (s >= fullSpan) { a=tmin; b=tmax; }
  if (a < tmin) { b += tmin-a; a=tmin; }
  if (b > tmax) { a -= b-tmax; b=tmax; }
  viewMin = clamp(a, tmin, tmax); viewMax = clamp(b, tmin, tmax);
  drawAll();
}

// Series drawing with min/max decimation (one envelope segment per pixel column)
// so a 100k-point series stays fast and spikes stay visible; direct polyline when
// few points are visible (zoomed in).
function drawSeries(ctx2, xfn, yfn, lo, hi, leftDev, widthDev, color, lw) {
  const cols = Math.max(1, Math.round(widthDev)), sp = (hi-lo)||1;
  let vis = 0;
  for (let i=0;i<N;i++) { const p=pts[i]; if (p.v===null||p.ts<lo||p.ts>hi) continue; vis++; }
  ctx2.strokeStyle = color; ctx2.lineWidth = lw*dpr; ctx2.beginPath();
  if (vis <= cols) {
    let pen = false;
    for (let i=0;i<N;i++) { const p=pts[i];
      if (p.v===null || p.ts<lo || p.ts>hi) { pen=false; continue; }
      const X=xfn(p.ts), Y=yfn(p.v);
      if (!pen) { ctx2.moveTo(X,Y); pen=true; } else ctx2.lineTo(X,Y);
    }
  } else {
    const cmin = new Array(cols).fill(null), cmax = new Array(cols).fill(null);
    for (let i=0;i<N;i++) { const p=pts[i]; if (p.v===null||p.ts<lo||p.ts>hi) continue;
      let col = Math.floor((p.ts-lo)/sp*(cols-1)); col = col<0?0:col>cols-1?cols-1:col;
      if (cmin[col]===null||p.v<cmin[col]) cmin[col]=p.v;
      if (cmax[col]===null||p.v>cmax[col]) cmax[col]=p.v;
    }
    let pen = false;
    for (let col=0;col<cols;col++) { if (cmax[col]===null) { pen=false; continue; }
      const X=leftDev+col, yh=yfn(cmax[col]), yl=yfn(cmin[col]);
      if (!pen) { ctx2.moveTo(X,yh); pen=true; } else ctx2.lineTo(X,yh);
      ctx2.lineTo(X,yl);
    }
  }
  ctx2.stroke();
}

function draw() {
  ctx.clearRect(0,0,c.width,c.height);
  ctx.font = (11*dpr)+'px ui-sans-serif, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  for (let i=0;i<=4;i++) { const v=vmin+(vmax-vmin)*i/4, yy=py(v);
    ctx.strokeStyle='rgba(255,255,255,0.05)'; ctx.lineWidth=1*dpr;
    ctx.beginPath(); ctx.moveTo(M.l*dpr,yy); ctx.lineTo(c.width-M.r*dpr,yy); ctx.stroke();
    ctx.fillStyle='#6e675b'; ctx.textAlign='right'; ctx.fillText(fmtVal(v),(M.l-8)*dpr,yy); }
  ctx.textBaseline = 'top';
  for (let i=0;i<=5;i++) { const ts=viewMin+vspan()*i/5, xx=px(ts);
    ctx.fillStyle='#6e675b'; ctx.textAlign=i===0?'left':i===5?'right':'center';
    ctx.fillText(fmtTick(ts,vspan()), xx, (c.height-M.b+8)*dpr); }
  ctx.save(); ctx.beginPath(); ctx.rect(M.l*dpr, M.t*dpr, plotW(), plotH()); ctx.clip();
  incidents.forEach(iv => { const x0=px(iv.a), x1=px(iv.b);
    ctx.fillStyle='rgba(214,50,50,0.20)'; ctx.fillRect(x0, M.t*dpr, x1-x0, plotH());
    ctx.strokeStyle='rgba(214,50,50,0.55)'; ctx.lineWidth=1*dpr; ctx.strokeRect(x0, M.t*dpr, x1-x0, plotH()); });
  if (dragging) { const x0=px(dragging.a), x1=px(dragging.b);
    ctx.fillStyle='rgba(240,173,78,0.28)'; ctx.fillRect(Math.min(x0,x1), M.t*dpr, Math.abs(x1-x0), plotH()); }
  drawSeries(ctx, px, py, viewMin, viewMax, M.l*dpr, plotW(), '#d15b36', 1.5);
  ctx.restore();
  if (hover && !dragging && !ovAct) drawHover();
}

function drawHover() {
  let best=null, bd=Infinity;
  for (let i=0;i<N;i++) { const p=pts[i]; if (p.v===null||p.ts<viewMin||p.ts>viewMax) continue;
    const d=Math.abs(p.ts-hover.ts); if (d<bd) { bd=d; best=p; } }
  if (!best) return;
  const X=px(best.ts), Y=py(best.v);
  ctx.strokeStyle='rgba(201,194,180,0.25)'; ctx.lineWidth=1*dpr;
  ctx.beginPath(); ctx.moveTo(X, M.t*dpr); ctx.lineTo(X, c.height-M.b*dpr); ctx.stroke();
  ctx.fillStyle='#f5f1e8'; ctx.beginPath(); ctx.arc(X,Y,3*dpr,0,7); ctx.fill();
  const label=fmtTick(best.ts, 0)+'  ·  '+fmtVal(best.v);
  ctx.font=(11*dpr)+'px ui-monospace, monospace'; const tw=ctx.measureText(label).width;
  let bx=X+8*dpr; if (bx+tw+12*dpr > c.width) bx=X-tw-20*dpr;
  ctx.fillStyle='rgba(27,25,22,0.92)'; ctx.strokeStyle='#332f29';
  ctx.fillRect(bx, M.t*dpr+2, tw+12*dpr, 20*dpr); ctx.strokeRect(bx, M.t*dpr+2, tw+12*dpr, 20*dpr);
  ctx.fillStyle='#c9c2b4'; ctx.textAlign='left'; ctx.textBaseline='middle';
  ctx.fillText(label, bx+6*dpr, M.t*dpr+12);
}

function drawOverview() {
  octx.clearRect(0,0,ov.width,ov.height);
  octx.save(); octx.beginPath(); octx.rect(OM.l*dpr, OM.t*dpr, ovWd(), ovHt()); octx.clip();
  incidents.forEach(iv => { const x0=ovpx(iv.a), x1=ovpx(iv.b);
    octx.fillStyle='rgba(214,50,50,0.30)'; octx.fillRect(x0, OM.t*dpr, x1-x0, ovHt()); });
  drawSeries(octx, ovpx, ovpy, tmin, tmax, OM.l*dpr, ovWd(), 'rgba(209,91,54,0.7)', 1.1);
  octx.restore();
  const vx0=ovpx(viewMin), vx1=ovpx(viewMax);
  octx.fillStyle='rgba(27,25,22,0.55)';
  octx.fillRect(OM.l*dpr, OM.t*dpr, vx0-OM.l*dpr, ovHt());
  octx.fillRect(vx1, OM.t*dpr, (ov.width-OM.r*dpr)-vx1, ovHt());
  octx.fillStyle='rgba(245,241,232,0.06)'; octx.fillRect(vx0, OM.t*dpr, vx1-vx0, ovHt());
  octx.strokeStyle='#d15b36'; octx.lineWidth=1.5*dpr;
  octx.strokeRect(vx0, OM.t*dpr+1, vx1-vx0, ovHt()-2);
  octx.fillStyle='#d15b36'; const hy=OM.t*dpr+ovHt()/2-9*dpr;
  octx.fillRect(vx0-2*dpr, hy, 4*dpr, 18*dpr); octx.fillRect(vx1-2*dpr, hy, 4*dpr, 18*dpr);
}

const tsAt = clientX => { const r=c.getBoundingClientRect();
  const fr=((clientX-r.left)-M.l)/((r.width-(M.l+M.r))||1); return viewMin + clamp(fr,0,1)*vspan(); };
const ovTsAtCss = clientX => { const r=ov.getBoundingClientRect();
  const fr=((clientX-r.left)-OM.l)/((r.width-(OM.l+OM.r))||1); return tmin + clamp(fr,0,1)*fullSpan; };
const ovEdgeCss = ts => { const r=ov.getBoundingClientRect();
  return r.left + OM.l + (ts-tmin)/fullSpan*(r.width-(OM.l+OM.r)); };

c.addEventListener('wheel', e => { e.preventDefault(); const t=tsAt(e.clientX);
  let s=clamp(vspan()*Math.pow(1.0015, e.deltaY), minSpan, fullSpan);
  const f=(t-viewMin)/(vspan()||1); setView(t-f*s, t-f*s+s); }, {passive:false});
c.addEventListener('mousedown', e => { dragging={a:tsAt(e.clientX), b:tsAt(e.clientX), sx:e.clientX, cx:e.clientX}; });
c.addEventListener('mousemove', e => { if (ovAct) return;
  if (dragging) { dragging.b=tsAt(e.clientX); dragging.cx=e.clientX; } else { hover={ts:tsAt(e.clientX)}; } draw(); });
c.addEventListener('mouseleave', () => { if (!dragging) { hover=null; draw(); } });

ov.addEventListener('mousedown', e => { e.preventDefault(); ov.style.cursor='grabbing';
  const xl=ovEdgeCss(viewMin), xr=ovEdgeCss(viewMax), x=e.clientX, H=8;
  if (Math.abs(x-xl)<=H) ovAct={type:'l'};
  else if (Math.abs(x-xr)<=H) ovAct={type:'r'};
  else if (x>xl && x<xr) ovAct={type:'pan', grab:ovTsAtCss(x), vMin:viewMin, vMax:viewMax};
  else { const t=ovTsAtCss(x), s=vspan(); setView(t-s/2, t+s/2); ovAct={type:'pan', grab:t, vMin:viewMin, vMax:viewMax}; }
});
ov.addEventListener('mousemove', e => { if (ovAct) return; const x=e.clientX, H=8;
  const xl=ovEdgeCss(viewMin), xr=ovEdgeCss(viewMax);
  ov.style.cursor = (Math.abs(x-xl)<=H || Math.abs(x-xr)<=H) ? 'ew-resize' : (x>xl && x<xr) ? 'grab' : 'pointer'; });
ov.addEventListener('wheel', e => { e.preventDefault(); const t=ovTsAtCss(e.clientX);
  const s=clamp(vspan()*Math.pow(1.0015, e.deltaY), minSpan, fullSpan); setView(t-s/2, t+s/2); }, {passive:false});

window.addEventListener('mousemove', e => { if (!ovAct) return; const t=ovTsAtCss(e.clientX);
  if (ovAct.type==='l') setView(Math.min(t, viewMax-minSpan), viewMax);
  else if (ovAct.type==='r') setView(viewMin, Math.max(t, viewMin+minSpan));
  else { const d=t-ovAct.grab; setView(ovAct.vMin+d, ovAct.vMax+d); } });
window.addEventListener('mouseup', () => {
  if (ovAct) { ovAct=null; return; }
  if (!dragging) return;
  if (Math.abs(dragging.cx-dragging.sx) > 4) {
    const a=clamp(Math.min(dragging.a,dragging.b),tmin,tmax), b=clamp(Math.max(dragging.a,dragging.b),tmin,tmax);
    incidents.push({a, b, label:''});
  }
  dragging=null; render();
});

document.getElementById('zreset').onclick = () => setView(tmin, tmax);
c.addEventListener('dblclick', () => setView(tmin, tmax));
document.getElementById('clear').onclick = () => { incidents.length=0; render(); };
window.setLabel = (i, val) => { if (incidents[i]) incidents[i].label = val; };
window.rm = i => { incidents.splice(i,1); render(); };

function render() {
  incidents.sort((p,q)=>p.a-q.a);
  const list=document.getElementById('list');
  list.innerHTML = incidents.map((iv,i)=>'<li><span class="dot"></span>'
    +'<span class="span">'+fmtTs(iv.a)+' &rarr; '+fmtTs(iv.b)+'</span>'
    +'<span class="dur">'+fmtDur(iv.b-iv.a)+'</span>'
    +'<input class="desc" type="text" placeholder="describe this incident (optional)" '
    +'value="'+esc(iv.label||'')+'" oninput="setLabel('+i+', this.value)">'
    +'<button class="ghost" onclick="rm('+i+')">remove</button></li>').join('');
  document.getElementById('empty').style.display = incidents.length ? 'none' : '';
  const total=incidents.reduce((s,iv)=>s+(iv.b-iv.a),0);
  document.getElementById('summary').innerHTML = incidents.length
    ? '<b>'+incidents.length+'</b> incident'+(incidents.length>1?'s':'')+' · '+fmtDur(total)+' total' : '';
  drawAll();
}

document.getElementById('export').onclick = () => {
  const d=new Date();
  const stamp=d.getUTCFullYear()+pad2(d.getUTCMonth()+1)+pad2(d.getUTCDate())+'T'
    +pad2(d.getUTCHours())+pad2(d.getUTCMinutes())+pad2(d.getUTCSeconds())+'Z';
  let y='metric: __METRIC__\\ntimezone: UTC\\nincidents:\\n';
  const sorted=incidents.slice().sort((p,q)=>p.a-q.a);
  if (!sorted.length) y+='  []\\n';
  sorted.forEach(iv => { y+='  - {start: "'+fmtTs(iv.a)+'", end: "'+fmtTs(iv.b)+'"'
    + (iv.label && iv.label.trim() ? ', label: '+yamlStr(iv.label.trim()) : '') + '}\\n'; });
  const blob=new Blob([y], {type:'text/yaml'}); const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='__METRIC__-'+stamp+'.yml'; a.click();
};

function drawAll() { draw(); drawOverview();
  document.getElementById('range').textContent =
    'viewing ' + fmtTs(viewMin) + ' → ' + fmtTs(viewMax) + '  ·  ' + fmtDur(vspan()) + ' of ' + fmtDur(fullSpan); }
function fit() { dpr = window.devicePixelRatio || 1;
  c.width=c.clientWidth*dpr; c.height=c.clientHeight*dpr;
  ov.width=ov.clientWidth*dpr; ov.height=ov.clientHeight*dpr; drawAll(); }
window.addEventListener('resize', fit); fit(); render();
</script>
"""


def render_labeler_html(metric_name: str, data: dict[str, np.ndarray]) -> str:
    """Return a self-contained HTML labeler page for *metric_name*'s series."""
    timestamps = data["timestamp"]
    values = data["value"]
    points = []
    for i in range(len(timestamps)):
        v = values[i]
        points.append({"t": _ts_to_str(timestamps[i]), "v": None if np.isnan(v) else float(v)})
    payload = json_dumps_sorted({"metric": metric_name, "points": points})
    return _TEMPLATE.replace("__PAYLOAD__", payload).replace("__METRIC__", metric_name)
