"""Generate a self-contained HTML labeler for a metric series.

Emits a single HTML file (inline CSS/JS, no CDN) with the series embedded as a
JSON literal: a canvas line chart where the user click-drags over incident
spans and exports a labels file in the canonical schema, which is then fed back
via ``dtk autotune --select <metric> --incidents <file>``.

Docs sync: the autotune reference page embeds a *live* copy of this output
(``docs/examples/autotune-labeler.html``) so the site always shows the real UI.
After changing the template below, regenerate that example so the docs don't
drift:  ``python website/scripts/gen-labeler-example.py``  (also in the release
checklist).
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
  .shell { max-width: 1080px; margin: 0 auto; padding: 22px 22px 40px; }
  .brand { display:flex; align-items:center; gap:9px; margin-bottom: 14px; }
  .brand svg { width: 26px; height: 26px; border-radius: 7px; display:block; }
  .brand b { color: var(--paper); font-weight: 600; font-size: 15px; letter-spacing: .2px; }
  .brand span { color: var(--faint); font-size: 12px; }
  h1 { font-size: 18px; line-height: 1.3; margin: 0 0 6px; color: var(--paper); font-weight: 600; }
  h1 code { color: var(--clay); font-family: var(--mono); font-size: .82em; }
  .hint { color: var(--faint); font-size: 13px; margin: 0 0 18px; line-height: 1.5; }
  .hint code { color: var(--term-text); font-family: var(--mono); font-size: 12px;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 5px; padding: 1px 6px; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom: 12px; }
  button { font-family: var(--ui); font-size: 13px; font-weight: 500; border: 0; border-radius: 7px;
    padding: 9px 15px; cursor: pointer; transition: background .12s ease, border-color .12s ease; }
  button.primary { background: var(--clay); color: #fff; }
  button.primary:hover { background: var(--clay-700); }
  button.ghost { background: transparent; color: var(--term-text); border: 1px solid var(--term-border); }
  button.ghost:hover { border-color: var(--faint); color: var(--paper); }
  .summary { margin-left: auto; color: var(--faint); font-size: 12.5px; font-family: var(--mono); }
  .summary b { color: var(--clay); font-weight: 600; }
  canvas { width: 100%; height: clamp(320px, 46vh, 520px); display:block;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 10px; cursor: crosshair; }
  .empty { color: var(--faint); font-size: 13px; margin: 16px 2px; font-style: italic; }
  ul { list-style: none; margin: 14px 0 0; padding: 0; }
  li { display:flex; align-items:center; gap:12px; padding: 9px 12px; font-size: 13px;
    border: 1px solid var(--term-border); border-radius: 8px; margin-bottom: 7px; background: var(--term-surface); }
  li .dot { width:9px; height:9px; border-radius:50%; background: var(--anomaly); flex: 0 0 auto; }
  li .span { font-family: var(--mono); color: var(--term-text); }
  li .dur { color: var(--faint); font-size: 12px; }
  li button { margin-left: auto; padding: 5px 11px; font-size: 12px; }
  footer { margin-top: 26px; padding-top: 14px; border-top: 1px solid var(--term-border);
    color: var(--faint); font-size: 12px; }
  footer code { font-family: var(--mono); color: var(--term-text); }
</style>
<div class="shell">
  <div class="brand">
    <svg viewBox="0 0 100 100" aria-hidden="true"><rect x="3" y="3" width="94" height="94" rx="26" fill="#D15B36"/><polyline points="14,62 36,62 50,22 64,62 86,62" fill="none" stroke="#FBF9F3" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="50" cy="22" r="6.5" fill="#FBF9F3"/></svg>
    <b>detectkit</b><span>· incident labeler</span>
  </div>
  <h1>Label incidents — <code>__METRIC__</code></h1>
  <p class="hint">Click-drag across the chart to mark each real incident, then <b>Export</b> and run
  <code>dtk autotune --select __METRIC__ --incidents incidents-__METRIC__.yml</code></p>
  <div class="toolbar">
    <button id="export" class="primary">Export incidents-__METRIC__.yml</button>
    <button id="clear" class="ghost">Clear all</button>
    <span id="summary" class="summary"></span>
  </div>
  <canvas id="c" aria-label="metric series chart — drag horizontally to mark an incident span"></canvas>
  <div id="empty" class="empty">No incidents marked yet — drag across a span on the chart above.</div>
  <ul id="list"></ul>
  <footer>All times UTC · self-contained, no data leaves your browser · generated by
  <code>dtk autotune --label</code></footer>
</div>
<script>
const DATA = __PAYLOAD__;
const pts = DATA.points.map(p => ({t: p.t, ts: Date.parse(p.t.replace(' ','T')+'Z'), v: p.v}));
const incidents = [];
const c = document.getElementById('c');
const ctx = c.getContext('2d');
const vals = pts.map(p => p.v).filter(v => v !== null);
const vmin = vals.length ? Math.min.apply(null, vals) : 0;
const vmax = vals.length ? Math.max.apply(null, vals) : 1;
const tmin = pts.length ? pts[0].ts : 0;
const tmax = pts.length ? pts[pts.length-1].ts : 1;
const M = {l: 56, r: 16, t: 14, b: 30};  // css-px plot margins
let dpr = 1, hover = null, dragging = null;
function plotW() { return c.width - (M.l + M.r) * dpr; }
function plotH() { return c.height - (M.t + M.b) * dpr; }
function px(ts) { return M.l*dpr + (ts - tmin) / ((tmax - tmin) || 1) * plotW(); }
function py(v)  { return (c.height - M.b*dpr) - (v - vmin) / ((vmax - vmin) || 1) * plotH(); }
function tsAt(clientX) { const r=c.getBoundingClientRect();
  const fr=((clientX-r.left)-M.l)/((r.width-(M.l+M.r))||1); return tmin + Math.max(0,Math.min(1,fr))*(tmax-tmin); }
function fmtTs(ts) { return new Date(ts).toISOString().slice(0,19).replace('T',' '); }
function fmtAxis(ts) { return new Date(ts).toISOString().slice(5,16).replace('T',' '); }
function fmtVal(v) { const a=Math.abs(v); return a>=1000 ? v.toFixed(0) : a>=10 ? v.toFixed(1) : v.toFixed(2); }
function fmtDur(ms) { const m=Math.round(ms/60000); if(m<60) return m+'m';
  const h=Math.floor(m/60), mm=m%60; if(h<24) return h+'h'+(mm?(' '+mm+'m'):'');
  const d=Math.floor(h/24), hh=h%24; return d+'d'+(hh?(' '+hh+'h'):''); }
function fit() { dpr = window.devicePixelRatio || 1;
  c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr; draw(); }
function draw() {
  ctx.clearRect(0,0,c.width,c.height);
  ctx.font = (11*dpr)+'px ui-sans-serif, system-ui, sans-serif';
  // y gridlines + value ticks
  ctx.textBaseline = 'middle';
  for (let i=0;i<=4;i++) { const v=vmin+(vmax-vmin)*i/4, yy=py(v);
    ctx.strokeStyle='rgba(255,255,255,0.05)'; ctx.lineWidth=1*dpr; ctx.beginPath();
    ctx.moveTo(M.l*dpr, yy); ctx.lineTo(c.width-M.r*dpr, yy); ctx.stroke();
    ctx.fillStyle='#6e675b'; ctx.textAlign='right'; ctx.fillText(fmtVal(v), (M.l-8)*dpr, yy); }
  // x ticks
  ctx.textBaseline='top';
  for (let i=0;i<=5;i++) { const ts=tmin+(tmax-tmin)*i/5, xx=px(ts);
    ctx.fillStyle='#6e675b'; ctx.textAlign = i===0?'left':i===5?'right':'center';
    ctx.fillText(fmtAxis(ts), xx, (c.height-M.b+8)*dpr); }
  // committed incident bands
  incidents.forEach(iv => { const x0=px(iv.a), x1=px(iv.b);
    ctx.fillStyle='rgba(214,50,50,0.20)'; ctx.fillRect(Math.min(x0,x1), M.t*dpr, Math.abs(x1-x0), plotH());
    ctx.strokeStyle='rgba(214,50,50,0.55)'; ctx.lineWidth=1*dpr;
    ctx.strokeRect(Math.min(x0,x1), M.t*dpr, Math.abs(x1-x0), plotH()); });
  // drag preview
  if (dragging) { const x0=px(dragging.a), x1=px(dragging.b);
    ctx.fillStyle='rgba(240,173,78,0.28)'; ctx.fillRect(Math.min(x0,x1), M.t*dpr, Math.abs(x1-x0), plotH()); }
  // series line
  ctx.strokeStyle='#d15b36'; ctx.lineWidth=1.5*dpr; ctx.beginPath();
  let started=false;
  pts.forEach(p => { if (p.v===null) { started=false; return; } const X=px(p.ts), Y=py(p.v);
    if (!started) { ctx.moveTo(X,Y); started=true; } else ctx.lineTo(X,Y); });
  ctx.stroke();
  // hover crosshair + tooltip
  if (hover && !dragging) drawHover();
}
function drawHover() {
  let best=null, bd=Infinity;
  for (const p of pts) { if (p.v===null) continue; const d=Math.abs(p.ts-hover.ts);
    if (d<bd) { bd=d; best=p; } }
  if (!best) return;
  const X=px(best.ts), Y=py(best.v);
  ctx.strokeStyle='rgba(201,194,180,0.25)'; ctx.lineWidth=1*dpr; ctx.beginPath();
  ctx.moveTo(X, M.t*dpr); ctx.lineTo(X, c.height-M.b*dpr); ctx.stroke();
  ctx.fillStyle='#f5f1e8'; ctx.beginPath(); ctx.arc(X,Y,3*dpr,0,7); ctx.fill();
  const label=fmtAxis(best.ts)+'  ·  '+fmtVal(best.v);
  ctx.font=(11*dpr)+'px ui-monospace, monospace'; const tw=ctx.measureText(label).width;
  let bx=X+8*dpr; if (bx+tw+12*dpr > c.width) bx=X-tw-20*dpr;
  ctx.fillStyle='rgba(27,25,22,0.92)'; ctx.strokeStyle='#332f29';
  ctx.fillRect(bx, M.t*dpr+2, tw+12*dpr, 20*dpr); ctx.strokeRect(bx, M.t*dpr+2, tw+12*dpr, 20*dpr);
  ctx.fillStyle='#c9c2b4'; ctx.textAlign='left'; ctx.textBaseline='middle';
  ctx.fillText(label, bx+6*dpr, M.t*dpr+12);
}
c.addEventListener('mousedown', e => { dragging={a:tsAt(e.clientX), b:tsAt(e.clientX)}; });
c.addEventListener('mousemove', e => { if (dragging) { dragging.b=tsAt(e.clientX); }
  else { hover={ts:tsAt(e.clientX)}; } draw(); });
c.addEventListener('mouseleave', () => { hover=null; draw(); });
window.addEventListener('mouseup', () => { if(!dragging) return;
  if (Math.abs(dragging.b-dragging.a) > 1000) incidents.push({a:Math.min(dragging.a,dragging.b), b:Math.max(dragging.a,dragging.b)});
  dragging=null; render(); });
function render() {
  const list=document.getElementById('list');
  incidents.sort((p,q)=>p.a-q.a);
  list.innerHTML = incidents.map((iv,i)=>'<li><span class="dot"></span>'
    +'<span class="span">'+fmtTs(iv.a)+' &rarr; '+fmtTs(iv.b)+'</span>'
    +'<span class="dur">'+fmtDur(iv.b-iv.a)+'</span>'
    +'<button class="ghost" onclick="rm('+i+')">remove</button></li>').join('');
  document.getElementById('empty').style.display = incidents.length ? 'none' : '';
  const total = incidents.reduce((s,iv)=>s+(iv.b-iv.a),0);
  document.getElementById('summary').innerHTML = incidents.length
    ? '<b>'+incidents.length+'</b> incident'+(incidents.length>1?'s':'')+' · '+fmtDur(total)+' total'
    : '';
  draw();
}
function rm(i) { incidents.splice(i,1); render(); }
document.getElementById('clear').onclick = () => { incidents.length=0; render(); };
document.getElementById('export').onclick = () => {
  let y = 'metric: __METRIC__\\ntimezone: UTC\\nincidents:\\n';
  if (!incidents.length) y += '  []\\n';
  incidents.forEach(iv => { y += '  - {start: "'+fmtTs(iv.a)+'", end: "'+fmtTs(iv.b)+'"}\\n'; });
  const blob = new Blob([y], {type:'text/yaml'}); const a=document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'incidents-__METRIC__.yml'; a.click();
};
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
