"""Generate a self-contained HTML labeler for a metric series.

Emits a single HTML file (inline CSS/JS, no CDN) with the series embedded as a
JSON literal: a zoomable/pannable canvas chart where the user click-drags over
incident spans (with an optional per-incident description) and exports a labels
file in the canonical schema, fed back via
``dtk autotune --select <metric> --incidents <file-or-dir>``.

It can be **seeded with existing incidents** (the ``incidents=`` argument) so a
labels file can be opened and edited in place — the round-trip flow of filling
incidents in over time. Beyond click-drag marking it supports **threshold
capture** (grab every contiguous span above/below a horizontal line in one
gesture), **on-chart deletion** (each band carries an ✕ handle; the selected
band also responds to the Delete key), and an in-browser **Import** button that
loads a labels file you pick (YAML/JSON).

The page is offline-only — a browser cannot write to the project, so Export
downloads a **versioned** file named after the metric, with the optional set name
folded in as a suffix (``<metric>[-<name>]-<UTC-stamp>.yml``); drop it into
``incidents/<metric>/`` to keep every labeling round (``--incidents`` accepts
that directory and uses the newest version).

Docs sync: the autotune reference page + landing embed a *live* copy of this
output (``docs/examples/autotune-labeler.html``) so the site always shows the
real UI. After changing the template below, regenerate that example so the docs
don't drift:  ``python website/scripts/gen-labeler-example.py``  (also in the
release checklist).
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta

import numpy as np

from detectkit.utils.json_utils import json_dumps_sorted


def _ts_to_str(ts64: np.datetime64) -> str:
    ms = int(ts64.astype("datetime64[ms]").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


# The brand mark, served as the page favicon (data URI, no network). Mirrors the
# inline header logo + website/public/favicon.svg (.claude/rules/design.md).
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect x="3" y="3" width="94" height="94" rx="26" fill="#D15B36"/>'
    '<polyline points="14,62 36,62 50,22 64,62 86,62" fill="none" stroke="#FBF9F3" '
    'stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
    '<circle cx="50" cy="22" r="6.5" fill="#FBF9F3"/></svg>'
)


def _favicon_data_uri() -> str:
    b64 = base64.b64encode(_FAVICON_SVG.encode("utf-8")).decode("ascii")
    return "data:image/svg+xml;base64," + b64


# Built with .replace() (not .format()), so braces are literal — keep them single.
# Self-contained: inline brand styling/logo/JS, no network. Palette + fonts mirror
# website/src/styles/brand.css (.claude/rules/design.md); incident bands use the
# anomaly status color, the drag preview / threshold guide the no-data color.
_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="__FAVICON__">
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
  .ichip { display:inline-flex; align-items:center; gap:6px; vertical-align: middle; margin-left: 8px;
    font-family: var(--mono); font-size: 12px; font-weight: 500; color: var(--paper);
    background: rgba(209,91,54,0.16); border: 1px solid var(--clay); border-radius: 999px; padding: 3px 10px; }
  .ichip .d { width:6px; height:6px; border-radius:50%; background: var(--clay); }
  .ichip b { color: var(--clay); font-weight: 700; }
  .hint { color: var(--faint); font-size: 13px; margin: 0 0 18px; line-height: 1.55; }
  .hint code, code.k { color: var(--term-text); font-family: var(--mono); font-size: 12px;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 5px; padding: 1px 6px; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom: 12px; }
  button { font-family: var(--ui); font-size: 13px; font-weight: 500; border: 0; border-radius: 7px;
    padding: 9px 15px; cursor: pointer; transition: background .12s ease, border-color .12s ease, color .12s ease; }
  button.primary { background: var(--clay); color: #fff; }
  button.primary:hover { background: var(--clay-700); }
  button.primary:disabled { background: var(--term-border); color: var(--faint); cursor: default; }
  button.ghost { background: transparent; color: var(--term-text); border: 1px solid var(--term-border); }
  button.ghost:hover { border-color: var(--faint); color: var(--paper); }
  button.ghost.active { border-color: var(--nodata); color: var(--paper); background: rgba(240,173,78,0.16); }
  input.setname { background: var(--term-surface); color: var(--paper); border: 1px solid var(--term-border);
    border-radius: 7px; padding: 9px 11px; font-family: var(--ui); font-size: 13px; min-width: 200px; }
  input.setname::placeholder { color: var(--muted); }
  input.setname:focus { outline: none; border-color: var(--clay); }
  .summary { margin-left: auto; color: var(--faint); font-size: 12.5px; font-family: var(--mono); }
  .summary b { color: var(--clay); font-weight: 600; }
  .savemsg { margin: 4px 2px 0; font-size: 13px; display: none; }
  .savemsg.ok { display: block; color: var(--accent-green, #2e9e73); }
  .savemsg.err { display: block; color: var(--anomaly); }
  .savemsg.info { display: block; color: var(--faint); }
  .thbar { display:none; flex-wrap:wrap; gap:12px; align-items:center; margin: 0 0 12px;
    padding: 11px 13px; border: 1px solid var(--nodata); border-radius: 9px; background: var(--term-surface); }
  .thbar .thlabel { color: var(--nodata); font-size: 12.5px; font-weight: 600; }
  .thbar label { color: var(--faint); font-size: 12.5px; display:inline-flex; align-items:center; gap:6px; }
  .thbar select, .thbar input { background: var(--term-bg); color: var(--paper); border: 1px solid var(--term-border);
    border-radius: 6px; padding: 6px 8px; font-family: var(--ui); font-size: 12.5px; }
  .thbar input.num { width: 84px; font-family: var(--mono); }
  .thbar input:focus, .thbar select:focus { outline: none; border-color: var(--nodata); }
  .thbar button { padding: 7px 13px; }
  .thbar .thscope { color: var(--faint); font-size: 12px; white-space: nowrap; }
  .thbar .thscope.hint { font-style: italic; }
  .thbar .thscope b { color: var(--nodata); font-weight: 600; font-style: normal; }
  canvas#c { width: 100%; height: clamp(300px, 44vh, 500px); display:block; touch-action: none;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 10px; cursor: crosshair; }
  .zoombar { display:flex; align-items:center; gap:8px; margin: 10px 0 6px; }
  .rangelbl { margin-left: auto; color: var(--faint); font-size: 12px; font-family: var(--mono); }
  canvas#ov { width: 100%; height: 66px; display:block; touch-action: none;
    background: var(--term-surface); border: 1px solid var(--term-border); border-radius: 10px; cursor: grab; }
  .navhint { color: var(--faint); font-size: 12px; margin: 7px 2px 0; line-height: 1.55; }
  .empty { color: var(--faint); font-size: 13px; margin: 18px 2px; font-style: italic; }
  ul { list-style: none; margin: 16px 0 0; padding: 0; }
  li { display:flex; align-items:center; gap:11px; padding: 9px 12px; font-size: 13px; flex-wrap: wrap;
    border: 1px solid var(--term-border); border-radius: 8px; margin-bottom: 7px; background: var(--term-surface); }
  li.sel { border-color: var(--clay); background: rgba(209,91,54,0.10); }
  li .dot { width:9px; height:9px; border-radius:50%; background: var(--anomaly); flex: 0 0 auto; }
  li .span { font-family: var(--mono); color: var(--term-text); }
  li .dur { color: var(--faint); font-size: 12px; }
  li input.desc { flex: 1 1 220px; min-width: 160px; background: var(--term-bg); color: var(--paper);
    border: 1px solid var(--term-border); border-radius: 6px; padding: 6px 9px; font-family: var(--ui); font-size: 12.5px; }
  li input.desc::placeholder { color: var(--muted); }
  li input.desc:focus { outline: none; border-color: var(--clay); }
  li button { margin-left: auto; padding: 5px 11px; font-size: 12px; }
  li button.focus { margin-left: auto; }
  li button.focus + button { margin-left: 0; }
  footer { margin-top: 26px; padding-top: 14px; border-top: 1px solid var(--term-border);
    color: var(--faint); font-size: 12px; line-height: 1.6; }
  footer code { font-family: var(--mono); color: var(--term-text); }
</style>
<div class="shell">
  <div class="brand">
    <svg viewBox="0 0 100 100" aria-hidden="true"><rect x="3" y="3" width="94" height="94" rx="26" fill="#D15B36"/><polyline points="14,62 36,62 50,22 64,62 86,62" fill="none" stroke="#FBF9F3" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="50" cy="22" r="6.5" fill="#FBF9F3"/></svg>
    <b>detectkit</b><span>· incident labeler</span>
  </div>
  <h1>Label incidents — <code>__METRIC__</code><span id="intervalchip" class="ichip"
    title="The metric's sampling interval — the spacing between points, taken straight from the metric."></span></h1>
  <p class="hint">Click-drag across the chart to mark each real incident, add a short description, then
  <b>Export</b>. Save the file into <code class="k">incidents/__METRIC__/</code> and run
  <code class="k">dtk autotune --select __METRIC__ --incidents incidents/__METRIC__/</code></p>
  <div class="toolbar">
    <button id="importbtn" class="ghost" title="open an existing labels file to keep editing">Import file…</button>
    <input id="file" type="file" accept=".yml,.yaml,.json,.txt" style="display:none">
    <input id="setname" class="setname" type="text" placeholder="name this set (optional)" />
    <button id="export" class="primary">Export labels</button>
    <button id="thbtn" class="ghost" title="capture every span above or below a horizontal line">Threshold capture</button>
    <button id="clear" class="ghost">Clear all</button>
    <span id="summary" class="summary"></span>
  </div>
  <div id="thbar" class="thbar">
    <span class="thlabel">Threshold capture</span>
    <label>grab points
      <select id="thdir"><option value="above">above the line</option><option value="below">below the line</option></select>
    </label>
    <label>line value
      <input id="thval" class="num" type="number" step="any" placeholder="hover chart" />
    </label>
    <label>bridge gaps ≤
      <input id="thgap" class="num" type="number" min="0" step="1" value="0" /> intervals
    </label>
    <span id="thscope" class="thscope"></span>
    <button id="thwin" class="ghost" style="display:none" title="capture across the whole current view again">↺ whole view</button>
    <button id="thadd" class="primary" disabled>Add 0 spans</button>
    <button id="thdone" class="ghost">Done</button>
  </div>
  <div id="savemsg" class="savemsg"></div>
  <canvas id="c" aria-label="metric series — drag to mark an incident, scroll to zoom"></canvas>
  <div class="zoombar">
    <button id="zreset" class="ghost">Reset zoom</button>
    <span id="range" class="rangelbl"></span>
  </div>
  <canvas id="ov" aria-label="navigator — drag the window to pan, its edges to stretch the view"></canvas>
  <div class="navhint">Drag on an empty area to mark an incident · drag an existing incident's edges to
  adjust it, or its middle to move it · click its <b>✕</b> (or select it and press Delete) to remove it ·
  use <b>Threshold capture</b> to grab every span past a horizontal line at once (click sets the line; drag
  across the chart to limit it to a time window — handy when the metric behaves differently across periods) ·
  <b>focus</b> a row to jump the chart to it · scroll to zoom, double-click to reset · drag the navigator
  window below to pan.</div>
  <div id="empty" class="empty">No incidents marked yet — drag across a span on the chart above.</div>
  <ul id="list"></ul>
  <footer>All times UTC · self-contained, nothing leaves your browser · re-label any time —
  exports are versioned (<code>__METRIC__[-&lt;name&gt;]-&lt;timestamp&gt;.yml</code>), so keep every round in
  <code>incidents/__METRIC__/</code>. Generated by <code>dtk autotune --label</code>.</footer>
</div>
<script>
const DATA = __PAYLOAD__;
// When served by `dtk autotune --label` (local server), this is the save endpoint
// and Export POSTs straight into incidents/<metric>/. As a static file it is null,
// and Export falls back to a browser download.
const SAVE_URL = __SAVE_URL__;
// The metric's sampling interval (seconds). Passed straight from the metric when
// known; otherwise inferred from the median spacing of points.
const INTERVAL_S = __INTERVAL__;
// Incidents to seed the editor with (editing an existing labels file). Each is
// {start, end, label} in "YYYY-MM-DD HH:MM:SS" UTC; a point is start === end.
const PRELOAD = __INCIDENTS__;
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
// Seed from PRELOAD so re-opening a saved labels file continues where it left off.
PRELOAD.forEach(p => { const a = Date.parse(String(p.start).replace(' ','T')+'Z'),
  b = Date.parse(String(p.end).replace(' ','T')+'Z');
  if (!isNaN(a) && !isNaN(b)) incidents.push({a: Math.min(a,b), b: Math.max(a,b), label: p.label || ''}); });
const c = document.getElementById('c'), ov = document.getElementById('ov');
const ctx = c.getContext('2d'), octx = ov.getContext('2d');
const M = {l:56, r:16, t:14, b:30}, OM = {l:56, r:16, t:8, b:8};
let dpr = 1, hover = null, dragging = null, ovAct = null;
// selObj: the currently selected incident (object ref, survives re-sorting);
// hoverRow/hoverDel: list-row / ✕-handle hover targets; threshold-capture state.
let selObj = null, hoverRow = -1, hoverDel = -1, thMode = false, thHover = null;
// Threshold-capture window: thDown tracks a press, thDragWin a live drag, capWin
// the committed custom window (null → capture within the current view).
let thDown = null, thDragWin = null, capWin = null;

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

// Value at a CSS-pixel Y on the chart (inverse of py) — used to read the
// threshold line off the cursor.
const vAt = clientY => { const r=c.getBoundingClientRect();
  const fr=((clientY-r.top)-M.t)/((r.height-(M.t+M.b))||1);
  return vmax - clamp(fr,0,1)*(vmax-vmin); };
// The active threshold value: the locked input wins, else the live cursor value.
function thEff() { const s=thvalEl.value.trim();
  return (s!=='' && !isNaN(Number(s))) ? Number(s) : thHover; }
// The active capture window: a live/committed custom window, else the current
// view — so the threshold only grabs the period you're looking at (or painted),
// not the whole series. Returns [lo, hi] in ms.
function capRange() {
  const w = thDragWin || capWin;
  if (w) return [Math.min(w.a,w.b), Math.max(w.a,w.b)];
  return [viewMin, viewMax]; }
// Contiguous runs of points on the chosen side of the line within the capture
// window, bridging short gaps.
function thRuns() { const val=thEff(); if (val===null) return [];
  const dir=thdirEl.value, gapMax=Math.max(0, parseInt(thgapEl.value)||0);
  const win=capRange(), lo=win[0], hi=win[1];
  const runs=[]; let s=null, e=null, gap=0;
  for (let i=0;i<N;i++) { const p=pts[i]; if (p.ts<lo || p.ts>hi) continue;
    const q = p.v!==null && (dir==='above' ? p.v>val : p.v<val);
    if (q) { if (s===null) s=p.ts; e=p.ts; gap=0; }
    else if (s!==null) { gap++; if (gap>gapMax) { runs.push([s,e]); s=null; gap=0; } } }
  if (s!==null) runs.push([s,e]);
  return runs; }
function thCount() { const n=thRuns().length;
  thaddEl.textContent = 'Add '+n+' span'+(n===1?'':'s'); thaddEl.disabled = n===0; updateThWin(); }
// Add a captured span, merging it into any overlapping incidents (a single span
// can bridge several) into one band that keeps the first one's label.
function addCaptured(a,b) {
  let host=null;
  for (let i=incidents.length-1;i>=0;i--) { const iv=incidents[i];
    if (a<=iv.b && b>=iv.a) {
      if (host===null) { iv.a=Math.min(iv.a,a); iv.b=Math.max(iv.b,b); host=iv; }
      else { host.a=Math.min(host.a,iv.a); host.b=Math.max(host.b,iv.b);
        if (selObj===iv) selObj=host; incidents.splice(i,1); } } }
  if (host===null) incidents.push({a, b, label:''}); }
function toggleTh(on) { thMode = (on===undefined) ? !thMode : !!on;
  thbtnEl.classList.toggle('active', thMode); thbarEl.style.display = thMode ? 'flex' : 'none';
  if (thMode) { hover=null; } else { thHover=null; thDown=null; thDragWin=null; capWin=null; updateThWin(); }
  c.style.cursor = thMode ? 'crosshair' : 'crosshair'; if (thMode) { updateThWin(); thCount(); } draw(); }

function rr(g,x,y,w,h,r) { g.beginPath();
  g.moveTo(x+r,y); g.arcTo(x+w,y,x+w,y+h,r); g.arcTo(x+w,y+h,x,y+h,r);
  g.arcTo(x,y+h,x,y,r); g.arcTo(x,y,x+w,y,r); g.closePath(); }
// The ✕ delete handle at a band's top-right (device px); `hot` brightens it.
function drawDelHandle(x1, hot) { const s=14*dpr, m=3*dpr, bx=x1-s-m, by=M.t*dpr+m;
  ctx.fillStyle = hot ? 'rgba(214,50,50,0.95)' : 'rgba(27,25,22,0.82)';
  ctx.strokeStyle = 'rgba(214,50,50,0.9)'; ctx.lineWidth = 1*dpr;
  rr(ctx, bx, by, s, s, 3*dpr); ctx.fill(); ctx.stroke();
  ctx.strokeStyle = hot ? '#fff' : '#d63232'; ctx.lineWidth = 1.5*dpr;
  const p=4*dpr; ctx.beginPath();
  ctx.moveTo(bx+p, by+p); ctx.lineTo(bx+s-p, by+s-p);
  ctx.moveTo(bx+s-p, by+p); ctx.lineTo(bx+p, by+s-p); ctx.stroke(); }

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
  // Threshold-capture preview bands (amber), under the committed incident bands.
  if (thMode) { const val=thEff(); if (val!==null) thRuns().forEach(r => {
    const x0=px(r[0]), w=Math.max(px(r[1])-x0, 2*dpr);
    ctx.fillStyle='rgba(240,173,78,0.22)'; ctx.fillRect(x0, M.t*dpr, w, plotH());
    ctx.strokeStyle='rgba(240,173,78,0.6)'; ctx.lineWidth=1*dpr; ctx.strokeRect(x0, M.t*dpr, w, plotH()); }); }
  incidents.forEach((iv,idx) => { const x0=px(iv.a), x1=px(iv.b), w=Math.max(x1-x0, 2*dpr);
    const isSel=(iv===selObj), isHov=(idx===hoverRow);
    ctx.fillStyle = (isSel||isHov) ? 'rgba(214,50,50,0.32)' : 'rgba(214,50,50,0.20)';
    ctx.fillRect(x0, M.t*dpr, w, plotH());
    ctx.strokeStyle = isSel ? 'rgba(214,50,50,0.95)' : isHov ? 'rgba(214,50,50,0.78)' : 'rgba(214,50,50,0.55)';
    ctx.lineWidth=(isSel?2:1)*dpr; ctx.strokeRect(x0, M.t*dpr, w, plotH());
    // draggable edge handles
    ctx.fillStyle='rgba(214,50,50,0.95)';
    ctx.fillRect(x0-1.5*dpr, M.t*dpr, 3*dpr, plotH());
    ctx.fillRect(x1-1.5*dpr, M.t*dpr, 3*dpr, plotH());
    if ((x1-x0) >= 22*dpr || isSel) drawDelHandle(x1, isSel || idx===hoverDel); });
  if (dragging && dragging.mode==='new') { const x0=px(dragging.a), x1=px(dragging.b);
    ctx.fillStyle='rgba(240,173,78,0.28)'; ctx.fillRect(Math.min(x0,x1), M.t*dpr, Math.abs(x1-x0), plotH()); }
  drawSeries(ctx, px, py, viewMin, viewMax, M.l*dpr, plotW(), '#d15b36', 1.5);
  if (thMode) {
    const win=capRange(), narrow = !!(thDragWin || capWin);
    const xlo=clamp(px(win[0]), M.l*dpr, c.width-M.r*dpr), xhi=clamp(px(win[1]), M.l*dpr, c.width-M.r*dpr);
    if (narrow) {  // dim everything outside the capture window
      ctx.fillStyle='rgba(27,25,22,0.5)';
      ctx.fillRect(M.l*dpr, M.t*dpr, xlo-M.l*dpr, plotH());
      ctx.fillRect(xhi, M.t*dpr, (c.width-M.r*dpr)-xhi, plotH());
      ctx.strokeStyle='rgba(240,173,78,0.7)'; ctx.lineWidth=1*dpr; ctx.setLineDash([3*dpr,3*dpr]);
      ctx.beginPath(); ctx.moveTo(xlo,M.t*dpr); ctx.lineTo(xlo,c.height-M.b*dpr);
      ctx.moveTo(xhi,M.t*dpr); ctx.lineTo(xhi,c.height-M.b*dpr); ctx.stroke(); ctx.setLineDash([]); }
    const val=thEff();
    if (val!==null && val>=vmin && val<=vmax) { const yy=py(val);
      ctx.strokeStyle='#f0ad4e'; ctx.lineWidth=1.5*dpr; ctx.setLineDash([6*dpr,4*dpr]);
      ctx.beginPath(); ctx.moveTo(xlo, yy); ctx.lineTo(xhi, yy); ctx.stroke(); ctx.setLineDash([]); } }
  ctx.restore();
  if (thMode) drawThLabel();
  else if (dragging && !ovAct) drawDragLabel();
  else if (hover && !ovAct) drawHover();
}

// Readout while picking a threshold: the line value, side, and how many spans
// would be captured.
function drawThLabel() {
  const val=thEff(), win=capRange(), narrow = !!(thDragWin || capWin);
  let text;
  if (val===null) {  // no line yet — prompt how to use the mode
    text = 'drag the chart to pick a period  ·  hover or type a value to set the line';
  } else { const n=thRuns().length;
    text='line '+fmtVal(val)+'  ·  '+thdirEl.value+'  ·  '+n+' span'+(n===1?'':'s')
      + (narrow ? ('  ·  '+fmtDur(win[1]-win[0])+' window') : ''); }
  ctx.font=(11*dpr)+'px ui-monospace, monospace';
  const tw=ctx.measureText(text).width, bw=tw+14*dpr, bh=22*dpr, bx=M.l*dpr+6*dpr, by=M.t*dpr+2;
  ctx.fillStyle='rgba(27,25,22,0.96)'; ctx.strokeStyle='#f0ad4e'; ctx.lineWidth=1*dpr;
  ctx.fillRect(bx, by, bw, bh); ctx.strokeRect(bx, by, bw, bh);
  ctx.fillStyle='#f0ad4e'; ctx.textAlign='left'; ctx.textBaseline='middle';
  ctx.fillText(text, bx+7*dpr, by+bh/2);
}

// Live time readout while marking/resizing/moving an incident, so you can place
// an edge precisely (an edge shows old → new; move/new show the resulting span).
function drawDragLabel() {
  let text, atTs;
  if (dragging.mode==='new') {
    const a=Math.min(dragging.a,dragging.b), b=Math.max(dragging.a,dragging.b);
    text = fmtTs(a)+'  →  '+fmtTs(b); atTs = dragging.b;
  } else { const iv=dragging.iv; if (!iv) return;
    if (dragging.mode==='edge') {
      const old = dragging.edge==='a' ? dragging.a0 : dragging.b0;
      const cur = dragging.edge==='a' ? iv.a : iv.b;
      text = (dragging.edge==='a' ? 'start: ' : 'end: ') + fmtTs(old) + '  →  ' + fmtTs(cur);
      atTs = cur;
    } else { text = fmtTs(iv.a) + '  →  ' + fmtTs(iv.b); atTs = (iv.a+iv.b)/2; }
  }
  const X = clamp(px(atTs), M.l*dpr, c.width-M.r*dpr);
  ctx.font=(11*dpr)+'px ui-monospace, monospace';
  const tw=ctx.measureText(text).width, bw=tw+14*dpr, bh=22*dpr, by=M.t*dpr+2;
  let bx = X - bw/2;
  if (bx < M.l*dpr) bx = M.l*dpr;
  if (bx+bw > c.width-M.r*dpr) bx = c.width-M.r*dpr-bw;
  ctx.fillStyle='rgba(27,25,22,0.96)'; ctx.strokeStyle='#d15b36'; ctx.lineWidth=1*dpr;
  ctx.fillRect(bx, by, bw, bh); ctx.strokeRect(bx, by, bw, bh);
  ctx.fillStyle='#f5f1e8'; ctx.textAlign='left'; ctx.textBaseline='middle';
  ctx.fillText(text, bx+7*dpr, by+bh/2);
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
// Hit-test an existing incident's ✕ handle / edge / body in CSS px.
const EDGE_PX = 6;
const minStep = () => Math.max(step, 1);
const pxCss = ts => { const r=c.getBoundingClientRect();
  return M.l + (ts-viewMin)/(vspan()||1)*(r.width-(M.l+M.r)); };
function hitIncident(clientX, clientY) {
  const r=c.getBoundingClientRect(), x=clientX-r.left, y=clientY-r.top;
  for (let i=0;i<incidents.length;i++) { const xa=pxCss(incidents[i].a), xb=pxCss(incidents[i].b);
    if ((xb-xa)>=22 || incidents[i]===selObj) {
      const s=14, m=3, hx0=xb-s-m, hy0=M.t+m;
      if (x>=hx0 && x<=hx0+s && y>=hy0 && y<=hy0+s) return {i, edge:'del'}; } }
  for (let i=0;i<incidents.length;i++) { const xa=pxCss(incidents[i].a), xb=pxCss(incidents[i].b);
    if (Math.abs(x-xa)<=EDGE_PX) return {i, edge:'a'};
    if (Math.abs(x-xb)<=EDGE_PX) return {i, edge:'b'}; }
  for (let i=0;i<incidents.length;i++) { const xa=pxCss(incidents[i].a), xb=pxCss(incidents[i].b);
    if (x>xa+EDGE_PX && x<xb-EDGE_PX) return {i, edge:'move'}; }
  return null;
}
c.addEventListener('mousedown', e => {
  // In threshold mode a press either sets the line (a click) or paints a capture
  // window (a horizontal drag) — resolved on mouseup by how far it moved.
  if (thMode) { thDown = {x:e.clientX, ts:tsAt(e.clientX)}; thHover = vAt(e.clientY); thCount(); draw(); return; }
  const hit = hitIncident(e.clientX, e.clientY), t = tsAt(e.clientX);
  if (hit && hit.edge==='del') { removeIncident(incidents[hit.i]); return; }
  if (hit && hit.edge==='move') { const iv=incidents[hit.i]; selObj=iv;
    dragging={mode:'move', iv, grab:t, a0:iv.a, b0:iv.b, sx:e.clientX, cx:e.clientX}; render(); }
  else if (hit) { const iv=incidents[hit.i]; selObj=iv;
    dragging={mode:'edge', iv, edge:hit.edge, a0:iv.a, b0:iv.b, sx:e.clientX, cx:e.clientX}; draw(); }
  else { selObj=null; dragging={mode:'new', a:t, b:t, sx:e.clientX, cx:e.clientX}; draw(); }
});
c.addEventListener('mousemove', e => { if (ovAct) return;
  if (thMode && !dragging) {
    if (thDown && Math.abs(e.clientX - thDown.x) > 6) { thDragWin = {a: thDown.ts, b: tsAt(e.clientX)}; }
    else { if (thDown) thDragWin = null; thHover = vAt(e.clientY); }
    thCount(); draw(); return; }
  if (dragging) {
    dragging.cx=e.clientX; const t=tsAt(e.clientX);
    if (dragging.mode==='new') { dragging.b=t; }
    else if (dragging.mode==='edge') { const iv=dragging.iv; if (!iv) return;
      if (dragging.edge==='a') iv.a=clamp(Math.min(t, iv.b-minStep()), tmin, tmax);
      else iv.b=clamp(Math.max(t, iv.a+minStep()), tmin, tmax); }
    else if (dragging.mode==='move') { const iv=dragging.iv; if (!iv) return;
      let na=dragging.a0+(t-dragging.grab), nb=dragging.b0+(t-dragging.grab);
      if (na<tmin) { nb+=tmin-na; na=tmin; } if (nb>tmax) { na-=nb-tmax; nb=tmax; }
      iv.a=clamp(na,tmin,tmax); iv.b=clamp(nb,tmin,tmax); }
    draw();
  } else {
    const hit=hitIncident(e.clientX, e.clientY);
    hoverDel = (hit && hit.edge==='del') ? hit.i : -1;
    c.style.cursor = hit ? (hit.edge==='del' ? 'pointer' : hit.edge==='move' ? 'grab' : 'ew-resize') : 'crosshair';
    hover={ts:tsAt(e.clientX)}; draw();
  }
});
c.addEventListener('mouseleave', () => { if (!dragging) { hover=null; hoverDel=-1; draw(); } });

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
window.addEventListener('mouseup', e => {
  if (ovAct) { ovAct=null; return; }
  if (thMode && thDown) {
    if (Math.abs(e.clientX - thDown.x) > 6) {  // a drag → set the capture window
      const a=thDown.ts, b=tsAt(e.clientX); capWin = {a:Math.min(a,b), b:Math.max(a,b)};
    } else {  // a click → set the threshold line value
      thvalEl.value = String(Math.round(vAt(e.clientY)*1000)/1000);
    }
    thDown=null; thDragWin=null; updateThWin(); thCount(); draw(); return;
  }
  if (!dragging) return;
  if (dragging.mode==='new') {
    if (Math.abs(dragging.cx-dragging.sx) > 4) {
      const a=clamp(Math.min(dragging.a,dragging.b),tmin,tmax), b=clamp(Math.max(dragging.a,dragging.b),tmin,tmax);
      const iv={a, b, label:''}; incidents.push(iv); selObj=iv;
    } else { selObj=null; }  // a plain click on empty space clears the selection
  } else { const iv=dragging.iv;  // edge/move: keep start <= end
    if (iv && iv.a>iv.b) { const t=iv.a; iv.a=iv.b; iv.b=t; } }
  dragging=null; render();
});

// Remove an incident by object reference (survives list re-sorting).
function removeIncident(iv) { const k=incidents.indexOf(iv); if (k<0) return;
  incidents.splice(k,1); if (selObj===iv) selObj=null; hoverDel=-1; render(); }
window.addEventListener('keydown', e => {
  const t=e.target, typing = t && (t.tagName==='INPUT' || t.tagName==='TEXTAREA' || t.isContentEditable);
  if (e.key==='Escape') { if (thMode) toggleTh(false); else if (selObj) { selObj=null; draw(); } return; }
  if ((e.key==='Delete' || e.key==='Backspace') && selObj && !typing) { e.preventDefault(); removeIncident(selObj); }
});

document.getElementById('zreset').onclick = () => setView(tmin, tmax);
c.addEventListener('dblclick', () => { if (!thMode) setView(tmin, tmax); });
document.getElementById('clear').onclick = () => { incidents.length=0; selObj=null; render(); };
window.setLabel = (i, val) => { if (incidents[i]) incidents[i].label = val; };
window.rm = i => { const iv=incidents[i]; if (iv && selObj===iv) selObj=null; incidents.splice(i,1); render(); };
window.hl = i => { hoverRow=i; draw(); };
window.focusInc = i => { const iv=incidents[i]; if (!iv) return; selObj=iv;
  const pad=Math.max((iv.b-iv.a)*1.5, step*10, minSpan*0.5); setView(iv.a-pad, iv.b+pad); render(); };

// Threshold-capture controls.
const thbtnEl=document.getElementById('thbtn'), thbarEl=document.getElementById('thbar');
const thvalEl=document.getElementById('thval'), thdirEl=document.getElementById('thdir');
const thgapEl=document.getElementById('thgap'), thaddEl=document.getElementById('thadd');
const thdoneEl=document.getElementById('thdone'), thwinEl=document.getElementById('thwin');
const thscopeEl=document.getElementById('thscope');
// Always-visible scope readout so the time-window control is discoverable
// (the ✕/↺ reset only appears once a window exists).
function updateThWin() {
  thwinEl.style.display = capWin ? '' : 'none';
  if (!thscopeEl) return;
  const w = thDragWin || capWin;
  if (w) { const r=capRange(); thscopeEl.innerHTML = 'period: <b>'+fmtDur(r[1]-r[0])+'</b>'; thscopeEl.className='thscope'; }
  else { thscopeEl.textContent = 'period: current view — drag the chart to limit it'; thscopeEl.className='thscope hint'; } }
thwinEl.onclick = () => { capWin=null; updateThWin(); thCount(); draw(); };
thbtnEl.onclick = () => toggleTh();
thdoneEl.onclick = () => toggleTh(false);
thdirEl.onchange = () => { thCount(); draw(); };
thgapEl.oninput = () => { thCount(); draw(); };
thvalEl.oninput = () => { thCount(); draw(); };
thaddEl.onclick = () => { const runs=thRuns(); if (!runs.length) return;
  runs.forEach(r => addCaptured(r[0], r[1]));
  setMsg('Added '+runs.length+' incident'+(runs.length===1?'':'s')+' from the threshold — review and tidy below.', 'ok');
  render(); thCount(); };

// Import an existing labels file (YAML/JSON) the user picks, merging it in.
const fileEl=document.getElementById('file');
document.getElementById('importbtn').onclick = () => fileEl.click();
function normEntry(e) { const lab = e.label!=null ? String(e.label) : '';
  const toMs = s => Date.parse(String(s).trim().replace(' ','T')+'Z');
  if (e.at!=null) { const t=toMs(e.at); return isNaN(t) ? null : {a:t, b:t, label:lab}; }
  if (e.start!=null && e.end!=null) { const a=toMs(e.start), b=toMs(e.end);
    return (isNaN(a)||isNaN(b)) ? null : {a:Math.min(a,b), b:Math.max(a,b), label:lab}; }
  return null; }
function parseLabelsText(txt) {
  txt = txt.trim();
  if (txt[0]==='[' || txt[0]==='{') { try { const j=JSON.parse(txt);
    const arr = Array.isArray(j) ? j : (j.incidents || []);
    return arr.map(normEntry).filter(Boolean); } catch (e) { /* fall through to YAML */ } }
  const out=[], lines=txt.split(/\\r?\\n/); let cur=null;
  const flush = () => { if (cur) { const e=normEntry(cur); if (e) out.push(e); cur=null; } };
  for (let ln of lines) {
    if (/^\\s*-/.test(ln)) { flush(); cur={}; ln=ln.replace(/^\\s*-\\s*/, ''); }
    if (cur===null) continue;
    // strip only the wrapping braces of a flow map, so braces inside a quoted
    // label survive (a global brace strip would mangle them).
    ln = ln.trim();
    if (ln[0]==='{') ln=ln.slice(1);
    if (ln[ln.length-1]==='}') ln=ln.slice(0,-1);
    const re=/(start|end|at|label)\\s*:\\s*("([^"]*)"|'([^']*)'|[^,]+)/g; let m;
    while ((m=re.exec(ln))) { const k=m[1];
      const v = m[3]!==undefined ? m[3] : (m[4]!==undefined ? m[4] : m[2]); cur[k]=String(v).trim(); } }
  flush();
  return out; }
fileEl.onchange = ev => { const f=ev.target.files && ev.target.files[0]; if (!f) return;
  const rd=new FileReader();
  rd.onload = () => { try { const got=parseLabelsText(String(rd.result));
      if (!got.length) { setMsg('No incidents found in '+f.name+'.', 'err'); }
      else { got.forEach(g => incidents.push(g)); render();
        setMsg('Imported '+got.length+' incident'+(got.length===1?'':'s')+' from '+f.name+'.', 'ok'); }
    } catch (err) { setMsg('Could not read '+f.name+': '+err.message, 'err'); }
    fileEl.value=''; };
  rd.readAsText(f); };

function render() {
  incidents.sort((p,q)=>p.a-q.a);
  const list=document.getElementById('list');
  list.innerHTML = incidents.map((iv,i)=>'<li data-k="'+i+'" class="'+(iv===selObj?'sel':'')+'"'
    +' onmouseenter="hl('+i+')" onmouseleave="hl(-1)"><span class="dot"></span>'
    +'<span class="span">'+fmtTs(iv.a)+' &rarr; '+fmtTs(iv.b)+'</span>'
    +'<span class="dur">'+fmtDur(iv.b-iv.a)+'</span>'
    +'<input class="desc" type="text" placeholder="describe this incident (optional)" '
    +'value="'+esc(iv.label||'')+'" oninput="setLabel('+i+', this.value)">'
    +'<button class="ghost focus" title="zoom the chart to this incident" onclick="focusInc('+i+')">focus</button>'
    +'<button class="ghost" onclick="rm('+i+')">remove</button></li>').join('');
  document.getElementById('empty').style.display = incidents.length ? 'none' : '';
  const total=incidents.reduce((s,iv)=>s+(iv.b-iv.a),0);
  document.getElementById('summary').innerHTML = incidents.length
    ? '<b>'+incidents.length+'</b> incident'+(incidents.length>1?'s':'')+' · '+fmtDur(total)+' total' : '';
  if (selObj) { const k=incidents.indexOf(selObj);
    if (k>=0 && list.children[k]) list.children[k].scrollIntoView({block:'nearest'}); }
  drawAll();
}

const slug = s => (String(s).toLowerCase().replace(/[^a-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'') || '__METRIC__');
const setMsg = (text, cls) => { const el=document.getElementById('savemsg');
  el.textContent=text; el.className='savemsg '+cls; };
const buildYaml = () => {
  let y='metric: __METRIC__\\ntimezone: UTC\\nincidents:\\n';
  const sorted=incidents.slice().sort((p,q)=>p.a-q.a);
  if (!sorted.length) y+='  []\\n';
  sorted.forEach(iv => { y+='  - {start: "'+fmtTs(iv.a)+'", end: "'+fmtTs(iv.b)+'"'
    + (iv.label && iv.label.trim() ? ', label: '+yamlStr(iv.label.trim()) : '') + '}\\n'; });
  return y;
};

const exportBtn = document.getElementById('export');
if (SAVE_URL) exportBtn.textContent = 'Save & tune';
exportBtn.onclick = () => {
  const y = buildYaml();
  const name = document.getElementById('setname').value;
  if (SAVE_URL) {
    setMsg('Saving…', 'info'); exportBtn.disabled = true;
    fetch(SAVE_URL, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: name, yaml: y})})
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || ('HTTP '+r.status)); }))
      .then(res => setMsg('Saved to ' + res.saved + ' — autotune is now running in your terminal. '
        + 'You can close this tab.', 'ok'))
      .catch(e => { exportBtn.disabled = false; setMsg('Save failed: ' + e.message, 'err'); });
  } else {
    const d=new Date();
    const stamp=d.getUTCFullYear()+pad2(d.getUTCMonth()+1)+pad2(d.getUTCDate())+'T'
      +pad2(d.getUTCHours())+pad2(d.getUTCMinutes())+pad2(d.getUTCSeconds())+'Z';
    // Always name the file after the metric; the optional set name is a suffix.
    const s = name.trim() ? slug(name) : '';
    const suffix = (s && s !== '__METRIC__') ? '-' + s : '';
    const fname = '__METRIC__' + suffix + '-' + stamp + '.yml';
    const blob=new Blob([y], {type:'text/yaml'}); const a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=fname; a.click();
    setMsg('Downloaded ' + fname + ' — move it into incidents/__METRIC__/ and re-run.', 'info');
  }
};

function drawAll() { draw(); drawOverview();
  document.getElementById('range').textContent =
    'viewing ' + fmtTs(viewMin) + ' → ' + fmtTs(viewMax) + '  ·  ' + fmtDur(vspan()) + ' of ' + fmtDur(fullSpan); }
function fit() { dpr = window.devicePixelRatio || 1;
  c.width=c.clientWidth*dpr; c.height=c.clientHeight*dpr;
  ov.width=ov.clientWidth*dpr; ov.height=ov.clientHeight*dpr; drawAll(); }
function fmtInterval(s) { if (s<=0) return '?';
  if (s%86400===0) return (s/86400)+'d'; if (s%3600===0) return (s/3600)+'h';
  if (s%60===0) return (s/60)+'min'; return s+'s'; }
function medianIntervalSec() { if (N<2) return 0;
  const d=[]; for (let i=1;i<N;i++) d.push(pts[i].ts-pts[i-1].ts);
  d.sort((a,b)=>a-b); return Math.round(d[Math.floor(d.length/2)]/1000); }
const intervalSec = (typeof INTERVAL_S==='number' && INTERVAL_S>0) ? INTERVAL_S : medianIntervalSec();
document.getElementById('intervalchip').innerHTML =
  '<span class="d"></span>interval <b>'+fmtInterval(intervalSec)+'</b>';
window.addEventListener('resize', fit); fit(); render();
</script>
"""


def render_labeler_html(
    metric_name: str,
    data: dict[str, np.ndarray],
    *,
    save_url: str | None = None,
    interval_seconds: int | None = None,
    incidents: list[dict[str, str]] | None = None,
) -> str:
    """Return a self-contained HTML labeler page for *metric_name*'s series.

    With ``save_url`` (set by ``dtk autotune --label``'s local server) the page's
    Export button POSTs the labels straight to that endpoint; without it (a static
    file) Export falls back to a browser download. ``interval_seconds`` is the
    metric's sampling interval shown as a chip (inferred from the data if omitted).
    ``incidents`` seeds the editor with already-labeled spans (each a
    ``{"start", "end", "label"}`` dict in naive-UTC ``"YYYY-MM-DD HH:MM:SS"``; a
    point is ``start == end``) so an existing labels file can be opened and edited.
    """
    import json

    timestamps = data["timestamp"]
    values = data["value"]
    points = []
    for i in range(len(timestamps)):
        v = values[i]
        points.append({"t": _ts_to_str(timestamps[i]), "v": None if np.isnan(v) else float(v)})
    payload = json_dumps_sorted({"metric": metric_name, "points": points})
    preload = json_dumps_sorted(incidents or [])
    return (
        _TEMPLATE.replace("__PAYLOAD__", payload)
        .replace("__INCIDENTS__", preload)
        .replace("__FAVICON__", _favicon_data_uri())
        .replace("__SAVE_URL__", json.dumps(save_url))
        .replace("__INTERVAL__", json.dumps(interval_seconds))
        .replace("__METRIC__", metric_name)
    )
