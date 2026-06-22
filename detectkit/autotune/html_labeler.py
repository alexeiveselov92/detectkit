"""Generate a self-contained HTML labeler for a metric series.

Emits a single HTML file (inline CSS/JS, no CDN) with the series embedded as a
JSON literal: a canvas line chart where the user click-drags over incident
spans and exports a labels file in the canonical schema, which is then fed back
via ``dtk autotune --select <metric> --incidents <file>``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from detectkit.utils.json_utils import json_dumps_sorted


def _ts_to_str(ts64: np.datetime64) -> str:
    ms = int(ts64.astype("datetime64[ms]").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


# Built with .replace() (not .format()), so braces are literal — keep them single.
_TEMPLATE = """<meta charset="utf-8">
<title>detectkit · label incidents · __METRIC__</title>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 0; background:#211e1a; color:#c9c2b4; }
  header { padding: 14px 20px; border-bottom: 1px solid #332f29; }
  h1 { font-size: 15px; margin: 0; color:#f5f1e8; }
  .hint { color:#9a9384; font-size: 12px; margin-top: 4px; }
  #wrap { padding: 16px 20px; }
  canvas { width: 100%; height: 320px; background:#1b1916; border:1px solid #332f29; border-radius:6px; cursor: crosshair; }
  #list { margin-top: 14px; font-size: 13px; }
  .row { display:flex; gap:10px; align-items:center; padding:4px 0; border-bottom:1px solid #2a2722; }
  button { background:#d15b36; color:#fff; border:0; padding:8px 14px; border-radius:5px; cursor:pointer; font-size:13px; }
  button.ghost { background:#332f29; color:#c9c2b4; }
  code { color:#d15b36; }
</style>
<header>
  <h1>Label incidents — <code>__METRIC__</code></h1>
  <div class="hint">Click-drag across the chart to mark a real incident, then Export and run
  <code>dtk autotune --select __METRIC__ --incidents incidents-__METRIC__.yml</code></div>
</header>
<div id="wrap">
  <canvas id="c"></canvas>
  <div style="margin-top:12px; display:flex; gap:10px;">
    <button id="export">Export incidents-__METRIC__.yml</button>
    <button id="clear" class="ghost">Clear all</button>
  </div>
  <div id="list"></div>
</div>
<script>
const DATA = __PAYLOAD__;
const pts = DATA.points.map(p => ({t: p.t, ts: Date.parse(p.t.replace(' ','T')+'Z'), v: p.v}));
const incidents = [];
const c = document.getElementById('c');
const vals = pts.map(p => p.v).filter(v => v !== null);
const vmin = Math.min.apply(null, vals), vmax = Math.max.apply(null, vals);
const tmin = pts[0].ts, tmax = pts[pts.length-1].ts;
function fit() { c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; draw(); }
function x(ts) { return (ts - tmin) / ((tmax - tmin) || 1) * c.width; }
function y(v) { return c.height - (v - vmin) / ((vmax - vmin) || 1) * (c.height*0.85) - c.height*0.07; }
function draw() {
  const ctx = c.getContext('2d'); ctx.clearRect(0,0,c.width,c.height);
  ctx.fillStyle = 'rgba(214,50,50,0.18)';
  incidents.forEach(iv => { const x0=x(iv.a), x1=x(iv.b); ctx.fillRect(Math.min(x0,x1),0,Math.abs(x1-x0),c.height); });
  ctx.strokeStyle = '#d15b36'; ctx.lineWidth = 1.4*devicePixelRatio; ctx.beginPath();
  let started=false;
  pts.forEach(p => { if (p.v===null) { started=false; return; } const px=x(p.ts), py=y(p.v);
    if (!started) { ctx.moveTo(px,py); started=true; } else ctx.lineTo(px,py); });
  ctx.stroke();
}
let dragging=null;
c.addEventListener('mousedown', e => { const r=c.getBoundingClientRect(); const ts=tmin+(e.clientX-r.left)/r.width*(tmax-tmin); dragging={a:ts,b:ts}; });
c.addEventListener('mousemove', e => { if(!dragging) return; const r=c.getBoundingClientRect(); dragging.b=tmin+(e.clientX-r.left)/r.width*(tmax-tmin); draw();
  const ctx=c.getContext('2d'); ctx.fillStyle='rgba(240,173,78,0.25)'; ctx.fillRect(Math.min(x(dragging.a),x(dragging.b)),0,Math.abs(x(dragging.b)-x(dragging.a)),c.height); });
window.addEventListener('mouseup', () => { if(!dragging) return; if(Math.abs(dragging.b-dragging.a)>1000) { incidents.push({a:Math.min(dragging.a,dragging.b), b:Math.max(dragging.a,dragging.b)}); render(); } dragging=null; draw(); });
function fmt(ts) { return new Date(ts).toISOString().slice(0,19).replace('T',' '); }
function render() { const el=document.getElementById('list'); el.innerHTML = incidents.map((iv,i)=>'<div class="row"><span>'+fmt(iv.a)+' &rarr; '+fmt(iv.b)+'</span><button class="ghost" onclick="rm('+i+')">remove</button></div>').join(''); draw(); }
function rm(i) { incidents.splice(i,1); render(); }
document.getElementById('clear').onclick = () => { incidents.length=0; render(); };
document.getElementById('export').onclick = () => {
  let y = 'metric: __METRIC__\\ntimezone: UTC\\nincidents:\\n';
  if (!incidents.length) y += '  []\\n';
  incidents.forEach(iv => { y += '  - {start: "'+fmt(iv.a)+'", end: "'+fmt(iv.b)+'"}\\n'; });
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
