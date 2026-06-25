// Library HTML report renderer.
//
// Consumes the ReportPayload contract (payload.ts) baked by detectkit/reporting/
// into a self-contained HTML file, and paints an interactive report into a mount
// element: a header + summary chips, a zoom/pan canvas chart (value line, per-
// detector confidence bands + anomaly dots with a legend toggle, alert markers
// and shaded incident spans), preset range buttons, a hover readout, and an
// alerts list whose rows zoom the chart to their event.
//
// It shares all low-level canvas primitives with the landing demo via
// core/canvas.ts. It is bundled (esbuild → IIFE) to detectkit/reporting/assets/
// report.js, which assigns `window.__DTK_REPORT__ = { render }`. Nothing is
// exported for ESM — the global is the public surface (see DtkReportGlobal).
//
// Styling is inlined via an injected <style scoped to a root class>, using brand
// hexes directly: this renders inside a Python-generated standalone HTML and
// cannot rely on the site's landing.css.

import {
  type AlertMark,
  type BandPoint,
  type Domain,
  type Margins,
  type Scales,
  drawAlertMarkers,
  drawAnomalyDots,
  drawGridAndAxes,
  drawSeriesDecimated,
  drawWarmupOverlay,
  fillBand,
  fit,
  fmtDur,
  fmtTs,
  fmtVal,
  makeScales,
  rgba,
  scoredRuns,
  token,
} from '../core/canvas';
import type {
  AlertKind,
  ReportAlert,
  ReportDetector,
  ReportPayload,
} from './payload';

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

const MARGINS: Margins = { l: 56, r: 16, t: 14, b: 28 };
const MIN_SPAN_MS = 5 * 60 * 1000; // never zoom tighter than 5 minutes
const ROOT_CLASS = 'dtk-report';

// Status hex per alert kind (resolved live so a themed :root can override).
function kindColor(kind: AlertKind): string {
  if (kind === 'recovery') return token('--st-recovery');
  if (kind === 'no_data') return token('--st-nodata');
  return token('--st-anomaly');
}

function kindLabel(kind: AlertKind): string {
  if (kind === 'recovery') return 'recovery';
  if (kind === 'no_data') return 'no-data';
  return 'anomaly';
}

const esc = (s: unknown): string =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

// ----------------------------------------------------------------------------
// Per-detector view state
// ----------------------------------------------------------------------------

interface DetectorView {
  det: ReportDetector;
  /** chart band points, aligned to det.points (bounds nulled before effectiveStart) */
  band: BandPoint[];
  /** flagged anomaly marks (t, value-on-the-metric-line), effective zone only */
  anomalies: { t: number; v: number }[];
  /** ms timestamp this detector reaches full power, or null (whole window effective) */
  effectiveStart: number | null;
  /** brand accent for this detector's band (clay; subsequent ones tinted) */
  color: string;
  shown: boolean;
}

// A per-detector palette so multiple bands stay distinguishable. Index 0 is the
// primary (clay); the rest cycle a small set of brand-adjacent hues.
const BAND_PALETTE = ['--clay', '--st-error', '--st-recovery', '--st-nodata'];

// ----------------------------------------------------------------------------
// Renderer
// ----------------------------------------------------------------------------

function render(payload: ReportPayload, mount: HTMLElement): void {
  injectStyle();

  mount.classList.add(ROOT_CLASS);
  mount.innerHTML = '';

  const root = document.createElement('div');
  root.className = 'dtk-report-root';
  mount.appendChild(root);

  // --- value lookup by timestamp (for placing anomaly dots on the line) ------
  const valueAt = new Map<number, number>();
  for (const p of payload.points) if (p.v !== null) valueAt.set(p.t, p.v);

  // --- detector views --------------------------------------------------------
  // Each detector's band + anomaly dots are drawn only at/after its OWN
  // effective_start (full-power onset). Before it, the band is a degraded
  // lead-in (global fallback / partial window) and is suppressed by nulling the
  // bounds, so scoredRuns / fillBand never paint it.
  const views: DetectorView[] = payload.detectors.map((det, di) => {
    const eff = det.effective_start;
    const band: BandPoint[] = det.points.map((p) =>
      eff !== null && p.t < eff ? { t: p.t, lo: null, hi: null } : { t: p.t, lo: p.lo, hi: p.hi },
    );
    const anomalies: { t: number; v: number }[] = [];
    for (const p of det.points) {
      if (p.a === 1 && (eff === null || p.t >= eff)) {
        const v = valueAt.get(p.t);
        if (v !== undefined) anomalies.push({ t: p.t, v });
      }
    }
    return {
      det,
      band,
      anomalies,
      effectiveStart: eff,
      color: token(BAND_PALETTE[di % BAND_PALETTE.length]),
      shown: di === 0, // only the primary detector's band shows by default
    };
  });
  if (views.length === 1) views[0].shown = true;

  // --- header ----------------------------------------------------------------
  root.appendChild(buildHeader(payload));

  // --- legend (only when >1 detector) ----------------------------------------
  let legendEl: HTMLElement | null = null;
  if (views.length > 1) {
    legendEl = buildLegend(views, () => chart.repaint());
    root.appendChild(legendEl);
  }

  // --- toolbar (presets) + hover readout -------------------------------------
  const bar = document.createElement('div');
  bar.className = 'dtk-bar';
  root.appendChild(bar);

  const presets = document.createElement('div');
  presets.className = 'dtk-presets';
  bar.appendChild(presets);

  const readout = document.createElement('div');
  readout.className = 'dtk-readout';
  readout.textContent = 'hover the chart for a point readout';
  bar.appendChild(readout);

  // --- chart canvas ----------------------------------------------------------
  const chartWrap = document.createElement('div');
  chartWrap.className = 'dtk-chart';
  const canvas = document.createElement('canvas');
  chartWrap.appendChild(canvas);
  root.appendChild(chartWrap);

  const chart = createReportChart(canvas, payload, views, valueAt, (html) => {
    readout.innerHTML = html;
  });

  // preset buttons
  const PRESETS: { label: string; ms: number | null }[] = [
    { label: '24h', ms: 24 * 3600 * 1000 },
    { label: '7d', ms: 7 * 86400 * 1000 },
    { label: '30d', ms: 30 * 86400 * 1000 },
    { label: 'All', ms: null },
  ];
  for (const pr of PRESETS) {
    const b = document.createElement('button');
    b.className = 'dtk-preset';
    b.textContent = pr.label;
    b.onclick = () => {
      if (pr.ms === null) chart.resetView();
      else chart.setView(payload.period.end - pr.ms, payload.period.end);
      markActivePreset(presets, b);
    };
    presets.appendChild(b);
  }

  // y = 0 reference line toggle — for real-valued metrics best read relative to 0.
  const zeroLabel = document.createElement('label');
  zeroLabel.className = 'dtk-zero';
  zeroLabel.title = 'Draw a horizontal line at y = 0 and scale the chart to include zero.';
  const zeroBox = document.createElement('input');
  zeroBox.type = 'checkbox';
  zeroBox.onchange = () => chart.setZeroLine(zeroBox.checked);
  zeroLabel.appendChild(zeroBox);
  zeroLabel.appendChild(document.createTextNode(' y = 0'));
  presets.appendChild(zeroLabel);

  // --- alerts list -----------------------------------------------------------
  root.appendChild(buildAlertsList(payload, (al) => chart.focusAlert(al)));

  // --- size + resize ---------------------------------------------------------
  chart.resize();
  let raf = 0;
  const onResize = (): void => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      chart.resize();
    });
  };
  window.addEventListener('resize', onResize);
}

// ----------------------------------------------------------------------------
// Header
// ----------------------------------------------------------------------------

function buildHeader(payload: ReportPayload): HTMLElement {
  const h = document.createElement('div');
  h.className = 'dtk-header';

  const intervalMin = payload.interval_seconds / 60;
  const intervalStr =
    payload.interval_seconds >= 86400
      ? payload.interval_seconds / 86400 + 'd'
      : payload.interval_seconds >= 3600
        ? payload.interval_seconds / 3600 + 'h'
        : intervalMin >= 1
          ? intervalMin + 'min'
          : payload.interval_seconds + 's';

  const title = payload.project
    ? `${esc(payload.project)} · ${esc(payload.metric)}`
    : esc(payload.metric);

  const s = payload.summary;
  h.innerHTML =
    `<div class="dtk-h-top">` +
    `<h1 class="dtk-title">${title}</h1>` +
    `<div class="dtk-meta">${esc(fmtTs(payload.period.start))} – ${esc(
      fmtTs(payload.period.end),
    )} · interval ${esc(intervalStr)}${
      payload.generated_at ? ` · generated ${esc(payload.generated_at)}` : ''
    }</div>` +
    `</div>` +
    (payload.description ? `<p class="dtk-desc">${esc(payload.description)}</p>` : '') +
    `<div class="dtk-chips">` +
    chip('anomalies', s.anomalies, '--st-anomaly') +
    chip('alerts', s.alerts, '--clay') +
    chip('recoveries', s.recoveries, '--st-recovery') +
    chip('no-data', s.no_data, '--st-nodata') +
    `</div>`;
  return h;
}

function chip(label: string, count: number, colorVar: string): string {
  const c = token(colorVar);
  return (
    `<span class="dtk-chip">` +
    `<span class="dtk-dot" style="background:${esc(c)}"></span>` +
    `<span class="dtk-chip-n">${count}</span>` +
    `<span class="dtk-chip-l">${esc(label)}</span>` +
    `</span>`
  );
}

// ----------------------------------------------------------------------------
// Legend
// ----------------------------------------------------------------------------

function buildLegend(views: DetectorView[], onToggle: () => void): HTMLElement {
  const wrap = document.createElement('div');
  wrap.className = 'dtk-legend';
  views.forEach((v) => {
    const b = document.createElement('button');
    b.className = 'dtk-legend-item' + (v.shown ? '' : ' off');
    b.innerHTML =
      `<span class="dtk-swatch" style="background:${esc(v.color)}"></span>` +
      `<span class="dtk-legend-name">${esc(v.det.name)}</span>` +
      `<span class="dtk-legend-id">${esc(v.det.id.slice(0, 8))}</span>` +
      `<span class="dtk-legend-n">${v.det.anomaly_count}</span>`;
    b.onclick = () => {
      v.shown = !v.shown;
      b.classList.toggle('off', !v.shown);
      onToggle();
    };
    wrap.appendChild(b);
  });
  return wrap;
}

// ----------------------------------------------------------------------------
// Alerts list
// ----------------------------------------------------------------------------

function buildAlertsList(payload: ReportPayload, onClick: (al: ReportAlert) => void): HTMLElement {
  const wrap = document.createElement('div');
  wrap.className = 'dtk-alerts';

  const head = document.createElement('div');
  head.className = 'dtk-alerts-head';
  head.textContent = `Alerts (${payload.alerts.length})`;
  wrap.appendChild(head);

  if (payload.alerts.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'dtk-alerts-empty';
    empty.textContent = 'No alerts fired in this period.';
    wrap.appendChild(empty);
    return wrap;
  }

  const list = document.createElement('div');
  list.className = 'dtk-alerts-list';
  // newest first
  const sorted = [...payload.alerts].sort((a, b) => b.t - a.t);
  for (const al of sorted) {
    const row = document.createElement('button');
    row.className = 'dtk-alert-row';
    const col = kindColor(al.kind);
    const dirStr = al.direction !== 'none' ? ` · ${esc(al.direction)}` : '';
    const sevStr = al.severity > 0 ? ` · sev ${al.severity.toFixed(2)}` : '';
    const valStr = al.value !== null ? ` · value ${fmtVal(al.value)}` : '';
    const span =
      al.onset !== null && al.kind !== 'no_data'
        ? ` · ${fmtDur(Math.max(0, al.t - al.onset))} (${al.consecutive} pts)`
        : '';
    row.innerHTML =
      `<span class="dtk-alert-time">${esc(fmtTs(al.t))}</span>` +
      `<span class="dtk-badge" style="background:${esc(rgba(col, 0.18))};color:${esc(
        col,
      )};border-color:${esc(rgba(col, 0.5))}">${esc(kindLabel(al.kind))}</span>` +
      `<span class="dtk-alert-body">` +
      `<span class="dtk-alert-rule">${esc(al.rule)}</span>` +
      `<span class="dtk-alert-sub">${esc(al.detector)}${dirStr}${sevStr}${valStr}${esc(
        span,
      )}</span>` +
      `</span>`;
    row.onclick = () => onClick(al);
    list.appendChild(row);
  }
  wrap.appendChild(list);
  return wrap;
}

function markActivePreset(container: HTMLElement, active: HTMLElement): void {
  container.querySelectorAll('.dtk-preset').forEach((b) => b.classList.remove('active'));
  active.classList.add('active');
}

// ----------------------------------------------------------------------------
// Chart (zoom / pan / hover, over the baked report data)
// ----------------------------------------------------------------------------

interface ReportChart {
  repaint(): void;
  resize(): void;
  setView(a: number, b: number): void;
  resetView(): void;
  focusAlert(al: ReportAlert): void;
  setZeroLine(on: boolean): void;
}

function createReportChart(
  canvas: HTMLCanvasElement,
  payload: ReportPayload,
  views: DetectorView[],
  valueAt: Map<number, number>,
  setReadout: (html: string) => void,
): ReportChart {
  const ctxOrNull = canvas.getContext('2d');
  if (!ctxOrNull) throw new Error('report: 2D context unavailable');
  const g = ctxOrNull;

  // Series arrays for the decimated line.
  const timestamps: number[] = payload.points.map((p) => p.t);
  const values: number[] = payload.points.map((p) => (p.v === null ? NaN : p.v));

  // Full time domain.
  const tmin = payload.period.start;
  const tmax = payload.period.end;
  const fullSpan = tmax - tmin || 1;
  const minSpan = Math.min(MIN_SPAN_MS, fullSpan);

  // Value domain over the whole series + all band bounds (fixed; zoom is x-only,
  // matching the demo / html_labeler, which keep the y-domain stable).
  let vmin = 0;
  let vmax = 1;
  computeValueDomain();

  let viewMin = tmin;
  let viewMax = tmax;
  let dpr = 1;
  let hoverTs: number | null = null;
  // y = 0 reference line + 0-relative scaling (toggled via setZeroLine).
  let showZero = false;

  function computeValueDomain(): void {
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of values) {
      if (Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    for (const view of views) {
      for (const bp of view.band) {
        if (bp.lo !== null && Number.isFinite(bp.lo) && bp.lo < lo) lo = bp.lo;
        if (bp.hi !== null && Number.isFinite(bp.hi) && bp.hi > hi) hi = bp.hi;
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
      lo = 0;
      hi = 1;
    }
    // Fold 0 into the extent so the metric reads relative to zero when toggled on.
    if (showZero) {
      if (lo > 0) lo = 0;
      if (hi < 0) hi = 0;
    }
    if (hi <= lo) hi = lo + 1;
    const pad = (hi - lo) * 0.06;
    vmin = lo - pad;
    vmax = hi + pad;
  }

  function setZeroLine(on: boolean): void {
    if (showZero === on) return;
    showZero = on;
    computeValueDomain();
    paint();
  }

  // Divider for the warm-up overlay: the primary detector's full-power onset —
  // the first SHOWN detector with an effective_start, else the first such view.
  function primaryEffectiveStart(): number | null {
    for (const v of views) {
      if (v.shown && v.effectiveStart !== null) return v.effectiveStart;
    }
    for (const v of views) {
      if (v.effectiveStart !== null) return v.effectiveStart;
    }
    return null;
  }

  function domain(): Domain {
    return { tmin: viewMin, tmax: viewMax, vmin, vmax };
  }
  function scales(): Scales {
    return makeScales(canvas, MARGINS, domain(), dpr);
  }

  function setView(a: number, b: number): void {
    let s = b - a;
    if (s < minSpan) {
      const m = (a + b) / 2;
      a = m - minSpan / 2;
      b = m + minSpan / 2;
      s = minSpan;
    }
    if (s >= fullSpan) {
      a = tmin;
      b = tmax;
    }
    if (a < tmin) {
      b += tmin - a;
      a = tmin;
    }
    if (b > tmax) {
      a -= b - tmax;
      b = tmax;
    }
    viewMin = clamp(a, tmin, tmax);
    viewMax = clamp(b, tmin, tmax);
    paint();
  }

  function resetView(): void {
    viewMin = tmin;
    viewMax = tmax;
    paint();
  }

  function focusAlert(al: ReportAlert): void {
    const lo = al.onset !== null ? Math.min(al.onset, al.t) : al.t;
    const hi = al.t;
    const base = Math.max(hi - lo, minSpan);
    const pad = base * 1.5 + minSpan;
    setView(lo - pad, hi + pad);
  }

  // ---- paint ---------------------------------------------------------------
  let raf = 0;
  function schedule(): void {
    if (raf === 0) raf = requestAnimationFrame(paint);
  }

  function paint(): void {
    raf = 0;
    if (canvas.width === 0 || canvas.height === 0) return;
    const sc = scales();
    const faint = token('--faint');
    const muted = token('--muted');
    const clay = token('--clay');

    // background
    g.fillStyle = token('--term-bg');
    g.fillRect(0, 0, canvas.width, canvas.height);

    if (timestamps.length === 0) return;

    // gridlines + axes (time ticks track the current view)
    drawGridAndAxes(g, canvas, MARGINS, domain(), sc.px, sc.py, viewMin, viewMax, faint, muted, dpr);

    // y = 0 reference line (distinct from the faint gridlines) when in view
    if (showZero && vmin <= 0 && vmax >= 0) {
      const y0 = sc.py(0);
      g.strokeStyle = rgba(muted, 0.6);
      g.lineWidth = 1.25 * dpr;
      g.beginPath();
      g.moveTo(MARGINS.l * dpr, y0);
      g.lineTo(canvas.width - MARGINS.r * dpr, y0);
      g.stroke();
      g.fillStyle = muted;
      g.textAlign = 'right';
      g.textBaseline = 'middle';
      g.fillText('0', (MARGINS.l - 8) * dpr, y0);
    }

    // clip to plot rect
    g.save();
    g.beginPath();
    g.rect(MARGINS.l * dpr, MARGINS.t * dpr, sc.plotW(), sc.plotH());
    g.clip();

    // incident span shading (under the bands): onset → t for anomaly/recovery
    const top = MARGINS.t * dpr;
    const h = sc.plotH();
    for (const al of payload.alerts) {
      if (al.onset === null || al.kind === 'no_data') continue;
      const a = Math.min(al.onset, al.t);
      const b = Math.max(al.onset, al.t);
      if (b < viewMin || a > viewMax) continue;
      const col = kindColor(al.kind);
      const x0 = sc.px(a);
      const x1 = sc.px(b);
      g.fillStyle = rgba(col, 0.08);
      g.fillRect(x0, top, Math.max(x1 - x0, 1 * dpr), h);
    }

    // per-detector confidence bands (shown only) + anomaly dots
    for (const view of views) {
      if (!view.shown) continue;
      const runs = scoredRuns(view.band);
      fillBand(g, view.band, runs, sc.px, sc.py, view.color, 0.13, 0.4, dpr);
    }

    // value line (clay), gaps break the pen
    drawSeriesDecimated(
      g,
      timestamps,
      values,
      viewMin,
      viewMax,
      MARGINS.l * dpr,
      sc.plotW(),
      sc.px,
      sc.py,
      clay,
      1.5,
      dpr,
    );

    // anomaly dots per shown detector
    for (const view of views) {
      if (!view.shown) continue;
      drawAnomalyDots(g, view.anomalies, viewMin, viewMax, sc.px, sc.py, token('--st-anomaly'), dpr);
    }

    // warm-up overlay: dim the lead-in + dashed divider at the primary detector's
    // full-power onset (the first shown detector, else the first). Drawn over the
    // bands/line so the degraded region reads as not-yet-detecting.
    const dividerTs = primaryEffectiveStart();
    if (dividerTs !== null && dividerTs > viewMin) {
      drawWarmupOverlay(g, canvas, MARGINS, dpr, sc.px, dividerTs, 'detection at full power →');
    }

    // ALL alerts as chart markers (vertical tick + top triangle, colored by kind)
    const marks: AlertMark[] = payload.alerts.map((al) => ({ t: al.t, kind: al.kind }));
    drawAlertMarkers(g, canvas, MARGINS, dpr, sc.px, marks, (kind) => kindColor(kind as AlertKind));

    // hover crosshair
    if (hoverTs !== null) drawHover(sc, top, h, faint);

    g.restore();
  }

  // nearest grid point to a timestamp (binary search on the increasing grid)
  function nearestIndex(ts: number): number {
    const ta = timestamps;
    if (ta.length === 0) return -1;
    let lo = 0;
    let hi = ta.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (ta[mid] < ts) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && ts - ta[lo - 1] < ta[lo] - ts) lo -= 1;
    return lo;
  }

  function drawHover(sc: Scales, top: number, h: number, faint: string): void {
    const idx = nearestIndex(hoverTs as number);
    if (idx < 0) return;
    const ts = timestamps[idx];
    if (ts < viewMin || ts > viewMax) {
      setReadout('hover the chart for a point readout');
      return;
    }
    const X = sc.px(ts);
    g.strokeStyle = rgba(faint, 0.45);
    g.lineWidth = 1 * dpr;
    g.setLineDash([2 * dpr, 2 * dpr]);
    g.beginPath();
    g.moveTo(X, top);
    g.lineTo(X, top + h);
    g.stroke();
    g.setLineDash([]);

    const v = values[idx];
    if (Number.isFinite(v)) {
      const Y = sc.py(v);
      g.fillStyle = token('--term-bg');
      g.beginPath();
      g.arc(X, Y, 4 * dpr, 0, Math.PI * 2);
      g.fill();
      g.strokeStyle = token('--clay');
      g.lineWidth = 2 * dpr;
      g.beginPath();
      g.arc(X, Y, 4 * dpr, 0, Math.PI * 2);
      g.stroke();
    }
    updateReadout(idx);
  }

  function updateReadout(idx: number): void {
    const ts = timestamps[idx];
    const v = values[idx];
    let html = `<span class="dtk-ro-t">${esc(fmtTs(ts))}</span>`;
    html += `<span class="dtk-ro-v">value ${Number.isFinite(v) ? fmtVal(v) : '—'}</span>`;
    for (const view of views) {
      if (!view.shown) continue;
      const bp = view.band[idx];
      const dp = view.det.points[idx];
      if (bp && bp.lo !== null && bp.hi !== null) {
        const an = dp && dp.a === 1;
        const sev = an && dp.sev !== null ? ` sev ${dp.sev.toFixed(2)}` : '';
        const verdict = an
          ? `<span class="dtk-ro-anom" style="color:${esc(token('--st-anomaly'))}">anomaly${esc(
              sev,
            )}</span>`
          : '<span class="dtk-ro-ok">ok</span>';
        html +=
          `<span class="dtk-ro-det">` +
          `<span class="dtk-swatch" style="background:${esc(view.color)}"></span>` +
          `${esc(view.det.name)}: [${fmtVal(bp.lo)}, ${fmtVal(bp.hi)}] ${verdict}` +
          `</span>`;
      }
    }
    setReadout(html);
  }

  // ---- interaction ---------------------------------------------------------
  function tsAtClientX(clientX: number): number {
    const r = canvas.getBoundingClientRect();
    const fr = (clientX - r.left - MARGINS.l) / (r.width - (MARGINS.l + MARGINS.r) || 1);
    return viewMin + clamp(fr, 0, 1) * (viewMax - viewMin);
  }

  canvas.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      const t = tsAtClientX(e.clientX);
      const cur = viewMax - viewMin;
      const s = clamp(cur * Math.pow(1.0015, e.deltaY), minSpan, fullSpan);
      const f = (t - viewMin) / (cur || 1);
      setView(t - f * s, t - f * s + s);
    },
    { passive: false },
  );

  let drag: { x: number; vMin: number; vMax: number } | null = null;
  canvas.addEventListener('mousedown', (e) => {
    drag = { x: e.clientX, vMin: viewMin, vMax: viewMax };
    canvas.style.cursor = 'grabbing';
  });
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    const r = canvas.getBoundingClientRect();
    const perPx = (drag.vMax - drag.vMin) / (r.width - (MARGINS.l + MARGINS.r) || 1);
    const d = (e.clientX - drag.x) * perPx;
    setView(drag.vMin - d, drag.vMax - d);
  });
  window.addEventListener('mouseup', () => {
    if (drag) {
      drag = null;
      canvas.style.cursor = 'crosshair';
    }
  });
  canvas.addEventListener('mousemove', (e) => {
    if (drag) return;
    hoverTs = tsAtClientX(e.clientX);
    schedule();
  });
  canvas.addEventListener('mouseleave', () => {
    if (hoverTs !== null) {
      hoverTs = null;
      setReadout('hover the chart for a point readout');
      schedule();
    }
  });
  canvas.addEventListener('dblclick', () => resetView());
  canvas.style.cursor = 'crosshair';

  // ---- public --------------------------------------------------------------
  function resize(): void {
    dpr = fit(canvas);
    paint();
  }

  return {
    repaint: () => schedule(),
    resize,
    setView,
    resetView,
    focusAlert,
    setZeroLine,
  };
}

// ----------------------------------------------------------------------------
// Styling (injected once, scoped under .dtk-report)
// ----------------------------------------------------------------------------

let styleInjected = false;
function injectStyle(): void {
  if (styleInjected) return;
  styleInjected = true;
  const css = `
.${ROOT_CLASS}{--term-bg:#211e1a;--term-border:#332f29;--term-text:#c9c2b4;
  --clay:#d15b36;--clay-700:#b4471f;--ink:#1b1916;--paper:#f5f1e8;--surface:#fbf9f3;
  --border:#e6e0d4;--muted:#6e675b;--faint:#9a9384;
  --anom:#d63232;--rec:#36a64f;--nod:#f0ad4e;
  --sans:'Schibsted Grotesk',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-family:var(--sans);color:var(--ink);}
.${ROOT_CLASS} *{box-sizing:border-box;}
.${ROOT_CLASS} .dtk-report-root{max-width:1100px;margin:0 auto;padding:20px 18px 40px;}
/* --- header row ----------------------------------------------------------- */
.${ROOT_CLASS} .dtk-header{margin-bottom:16px;padding-left:12px;
  border-left:3px solid var(--clay);}
.${ROOT_CLASS} .dtk-h-top{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;}
.${ROOT_CLASS} .dtk-title{font-size:21px;font-weight:700;margin:0;color:var(--ink);
  font-family:var(--sans);letter-spacing:-0.01em;}
.${ROOT_CLASS} .dtk-meta{font-size:12px;color:var(--muted);font-family:var(--mono);}
.${ROOT_CLASS} .dtk-desc{margin:8px 0 0;font-size:13px;color:var(--muted);max-width:760px;
  line-height:1.5;}
/* --- summary chips (surface cards) ---------------------------------------- */
.${ROOT_CLASS} .dtk-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}
.${ROOT_CLASS} .dtk-chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;
  background:var(--surface);border:1px solid var(--border);border-radius:10px;font-size:12px;}
.${ROOT_CLASS} .dtk-dot{width:8px;height:8px;border-radius:50%;display:inline-block;}
.${ROOT_CLASS} .dtk-chip-n{font-weight:700;font-family:var(--mono);color:var(--ink);}
.${ROOT_CLASS} .dtk-chip-l{color:var(--faint);font-family:var(--mono);font-size:11px;
  text-transform:uppercase;letter-spacing:0.05em;}
/* --- detector legend ------------------------------------------------------ */
.${ROOT_CLASS} .dtk-legend{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;}
.${ROOT_CLASS} .dtk-legend-item{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;
  background:var(--surface);border:1px solid var(--border);border-radius:8px;cursor:pointer;
  color:var(--ink);font-size:12px;font-family:var(--sans);transition:border-color .12s ease;}
.${ROOT_CLASS} .dtk-legend-item:hover{border-color:var(--clay);}
.${ROOT_CLASS} .dtk-legend-item.off{opacity:0.45;}
.${ROOT_CLASS} .dtk-legend-id{color:var(--faint);font-family:var(--mono);font-size:11px;}
.${ROOT_CLASS} .dtk-legend-n{color:var(--anom);font-weight:700;font-family:var(--mono);}
.${ROOT_CLASS} .dtk-swatch{width:10px;height:10px;border-radius:2px;display:inline-block;}
/* --- toolbar (presets + readout) ------------------------------------------ */
.${ROOT_CLASS} .dtk-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;
  gap:8px;margin-bottom:8px;}
.${ROOT_CLASS} .dtk-presets{display:flex;gap:5px;}
.${ROOT_CLASS} .dtk-preset{padding:5px 13px;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;color:var(--muted);cursor:pointer;
  font-size:12px;font-family:var(--sans);transition:border-color .12s ease,color .12s ease;}
.${ROOT_CLASS} .dtk-preset:hover{border-color:var(--clay);color:var(--ink);}
.${ROOT_CLASS} .dtk-preset.active{background:var(--clay);color:#fff;border-color:var(--clay);}
.${ROOT_CLASS} .dtk-zero{display:inline-flex;align-items:center;gap:5px;margin-left:6px;
  font-size:12px;color:var(--muted);font-family:var(--sans);cursor:pointer;user-select:none;}
.${ROOT_CLASS} .dtk-zero input{accent-color:var(--clay);cursor:pointer;}
.${ROOT_CLASS} .dtk-readout{font-size:11px;color:var(--muted);
  font-family:var(--mono);display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;}
.${ROOT_CLASS} .dtk-readout .dtk-swatch{margin-right:4px;}
.${ROOT_CLASS} .dtk-ro-t{font-weight:700;color:var(--ink);}
/* --- chart panel (dark terminal surface) ---------------------------------- */
.${ROOT_CLASS} .dtk-chart{position:relative;width:100%;height:360px;background:var(--term-bg);
  border:1px solid var(--term-border);border-radius:12px;overflow:hidden;
  box-shadow:0 24px 60px -30px rgba(27,25,22,.45);}
.${ROOT_CLASS} .dtk-chart canvas{width:100%;height:100%;display:block;}
/* --- alerts list (surface cards) ------------------------------------------ */
.${ROOT_CLASS} .dtk-alerts{margin-top:18px;}
.${ROOT_CLASS} .dtk-alerts-head{font-size:12px;font-weight:600;color:var(--faint);
  margin-bottom:9px;font-family:var(--mono);text-transform:uppercase;letter-spacing:0.06em;}
.${ROOT_CLASS} .dtk-alerts-empty{font-size:13px;color:var(--muted);padding:8px 0;}
.${ROOT_CLASS} .dtk-alerts-list{display:flex;flex-direction:column;gap:5px;
  max-height:340px;overflow:auto;}
.${ROOT_CLASS} .dtk-alert-row{display:flex;align-items:center;gap:10px;width:100%;text-align:left;
  padding:8px 11px;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;cursor:pointer;color:var(--ink);font-family:var(--sans);
  transition:border-color .12s ease,box-shadow .12s ease;}
.${ROOT_CLASS} .dtk-alert-row:hover{border-color:var(--clay);
  box-shadow:0 4px 14px -8px rgba(27,25,22,.35);}
.${ROOT_CLASS} .dtk-alert-time{font-size:11px;color:var(--muted);
  font-family:var(--mono);white-space:nowrap;min-width:142px;}
.${ROOT_CLASS} .dtk-badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;
  font-weight:700;border:1px solid;text-transform:uppercase;letter-spacing:0.03em;white-space:nowrap;}
.${ROOT_CLASS} .dtk-alert-body{display:flex;flex-direction:column;gap:2px;min-width:0;}
.${ROOT_CLASS} .dtk-alert-rule{font-size:12px;color:var(--ink);
  font-family:var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.${ROOT_CLASS} .dtk-alert-sub{font-size:11px;color:var(--muted);}
`;
  const style = document.createElement('style');
  style.setAttribute('data-dtk-report', '');
  style.textContent = css;
  document.head.appendChild(style);
}

// ----------------------------------------------------------------------------
// Global entry (the only public surface — no ESM exports)
// ----------------------------------------------------------------------------

(window as unknown as { __DTK_REPORT__: { render: typeof render } }).__DTK_REPORT__ = { render };
