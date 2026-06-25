// Entry point for the interactive "playground" landing block.
//
// Reads the controls inside #dkx, fabricates a synthetic metric (synth.ts), runs
// the faithful detector port (detector.ts), paints values + corridor + flagged
// points + the trailing window (chart.ts), and fills the scorecard. Everything is
// client-side: a control change re-runs synth -> detect -> render in well under a
// frame, so the VPS only ever serves the static bundle.

import { createChart } from './chart';
import { effectiveStartIndex, runDetector } from './detector';
import { generateSeries } from './synth';
import type {
  AnomalyKind,
  ChartAlert,
  DetectorParams,
  DetectorType,
  Detrend,
  HoverInfo,
  NoiseLevel,
  Scorecard,
  ScoredPoint,
  SeasonalityPreset,
  Series,
  Smoothing,
  SynthOptions,
  TrendKind,
  WindowWeights,
} from './types';

// Each interval picks a point count that spans a readable number of cycles.
const INTERVALS: Record<string, { seconds: number; points: number; label: string }> = {
  '10min': { seconds: 600, points: 720, label: '10-minute' }, // ~5 days
  '1h': { seconds: 3600, points: 504, label: 'hourly' }, // ~3 weeks
  '1d': { seconds: 86400, points: 150, label: 'daily' }, // ~5 months
};

const DETECTOR_THRESHOLD_DEFAULT: Record<DetectorType, number> = {
  mad: 3,
  zscore: 3,
  iqr: 1.5,
};

function init(): void {
  const root = document.getElementById('dkx');
  if (!root) return;
  const canvas = root.querySelector<HTMLCanvasElement>('#dkx-canvas');
  if (!canvas) return;

  let seed = 7;

  // ---- control readers -------------------------------------------------------
  // Segmented controls are button groups: [data-control=<name>] > button[data-v].
  const seg = (name: string): string => {
    const on = root.querySelector<HTMLButtonElement>(`[data-control="${name}"] button.on`);
    return on?.dataset.v ?? '';
  };
  const setSeg = (name: string, value: string): void => {
    root.querySelectorAll<HTMLButtonElement>(`[data-control="${name}"] button`).forEach((b) => {
      b.classList.toggle('on', b.dataset.v === value);
    });
  };
  const num = (id: string): number => {
    const el = root.querySelector<HTMLInputElement>(`#${id}`);
    return el ? Number(el.value) : 0;
  };
  const out = (id: string, text: string): void => {
    const el = root.querySelector<HTMLElement>(`#${id}`);
    if (el) el.textContent = text;
  };

  const readSynth = (): SynthOptions => {
    const iv = INTERVALS[seg('interval')] ?? INTERVALS['1h'];
    return {
      seasonality: (seg('seasonality') || 'flat') as SeasonalityPreset,
      noise: (seg('noise') || 'medium') as NoiseLevel,
      trend: (seg('trend') || 'none') as TrendKind,
      intervalSeconds: iv.seconds,
      points: iv.points,
      anomaly: (seg('anomaly') || 'cluster') as AnomalyKind,
      anomalyMagnitude: num('dkx-magnitude') / 100,
      seed,
    };
  };

  const seasonalityComponents = (): string[][] | null => {
    switch (seg('conditioning')) {
      case 'hour':
        return [['hour_of_day']];
      case 'hour_dow':
        return [['hour_of_day', 'day_of_week']];
      default:
        return null;
    }
  };

  // Distinct seasonal keys present for a grouping (max across groups). A group's
  // per-key band engages only when the window holds min_samples_per_group points
  // of the current key, and same-key points recur once per this many positions —
  // so window_size must be >= min_samples_per_group * cardinality or every point
  // falls back to the global band (the seasonality silently does nothing).
  const seasonalCardinality = (series: Series, groups: string[][] | null): number => {
    const rows = series.seasonalityData;
    if (!groups || !rows || rows.length === 0) return 0;
    let card = 0;
    for (const g of groups) {
      const seen = new Set<string>();
      for (const row of rows) seen.add(g.map((c) => String(row?.[c] ?? '')).join('|'));
      card = Math.max(card, seen.size);
    }
    return card;
  };

  const readParams = (): DetectorParams => {
    const type = (seg('detector') || 'mad') as DetectorType;
    const weights = (seg('weights') || 'none') as WindowWeights;
    const smoothing = (seg('smoothing') || 'none') as Smoothing;
    return {
      type,
      threshold: num('dkx-threshold'),
      windowSize: num('dkx-window'),
      minSamples: 30,
      inputType: 'values',
      smoothing,
      smoothingAlpha: 0.3,
      smoothingWindow: 10,
      windowWeights: weights,
      halfLife: weights === 'exponential' ? num('dkx-halflife') : null,
      detrend: (seg('detrend') || 'none') as Detrend,
      seasonalityComponents: seasonalityComponents(),
      minSamplesPerGroup: type === 'zscore' ? 3 : type === 'iqr' ? 4 : 10,
      consecutiveAnomalies: num('dkx-consecutive'),
    };
  };

  // ---- scorecard -------------------------------------------------------------
  const computeScorecard = (
    series: Series,
    scored: ScoredPoint[],
    consecutive: number,
  ): Scorecard => {
    const truth = series.truthAnomaly;
    const n = scored.length;
    const flagged = scored.map((p) => p.scored && p.isAnomaly);

    // Point-wise confusion over SCORED points only (warm-up points excluded).
    let tp = 0;
    let fp = 0;
    let fn = 0;
    let tn = 0;
    let scoredTotal = 0;
    let flaggedTotal = 0;
    let injectedTotal = 0;
    for (let i = 0; i < n; i++) {
      if (truth[i]) injectedTotal++;
      if (!scored[i].scored) continue;
      scoredTotal++;
      const f = flagged[i];
      const t = truth[i];
      if (f) flaggedTotal++;
      if (f && t) tp++;
      else if (f && !t) fp++;
      else if (!f && t) fn++;
      else tn++;
    }

    // Human-friendly "caught vs missed": an injected point counts as caught if a
    // flag lands within +/-1 grid step (tolerates a one-point timing slip).
    const near = (i: number): boolean =>
      [i - 1, i, i + 1].some((j) => j >= 0 && j < n && flagged[j]);
    let caught = 0;
    let missed = 0;
    for (let i = 0; i < n; i++) {
      if (!truth[i]) continue;
      if (near(i)) caught++;
      else missed++;
    }
    const falsePositives = fp;

    const precision = tp + fp > 0 ? tp / (tp + fp) : 0;
    const recall = tp + fn > 0 ? tp / (tp + fn) : 0;
    const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
    const mccDen = Math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn));
    const mcc = mccDen > 0 ? (tp * tn - fp * fn) / mccDen : 0;

    // Alert layer: one alert per MAXIMAL run of grid-adjacent flagged points
    // that reaches `consecutive` — fired at the point where the run first hits
    // the threshold. A gap (non-adjacent grid step) or an un-flagged point ends
    // the run, so each qualifying incident contributes exactly one fire index.
    const alertFireIndexes: number[] = [];
    let runLen = 0;
    for (let i = 0; i < n; i++) {
      const adjacent =
        i > 0 &&
        scored[i].timestamp - scored[i - 1].timestamp === series.intervalSeconds * 1000;
      runLen = flagged[i] ? (adjacent ? runLen + 1 : 1) : 0;
      if (runLen === consecutive) alertFireIndexes.push(i);
    }

    return {
      caught,
      missed,
      falsePositives,
      injectedTotal,
      flaggedTotal,
      scoredTotal,
      flagRate: scoredTotal > 0 ? flaggedTotal / scoredTotal : 0,
      precision,
      recall,
      f1,
      mcc,
      alertWouldFire: alertFireIndexes.length > 0,
      alertFireIndex: alertFireIndexes.length > 0 ? alertFireIndexes[0] : -1,
      alertFireIndexes,
    };
  };

  const fmtTime = (ts: number, intervalSeconds: number): string => {
    const d = new Date(ts);
    const iso = d.toISOString();
    return intervalSeconds >= 86400 ? iso.slice(0, 10) : iso.slice(0, 16).replace('T', ' ');
  };

  // ---- chart + render loop ---------------------------------------------------
  const onHover = (info: HoverInfo | null): void => {
    const el = root.querySelector<HTMLElement>('#dkx-readout');
    if (!el) return;
    if (!info || !info.point) {
      el.classList.remove('on');
      return;
    }
    const p = info.point;
    const iv = currentSeries ? currentSeries.intervalSeconds : 3600;
    const at = fmtTime(p.timestamp, iv);
    const span =
      currentSeries && info.windowStart <= info.windowEnd
        ? `${fmtTime(currentSeries.timestamps[info.windowStart], iv)} → ${fmtTime(
            currentSeries.timestamps[info.windowEnd],
            iv,
          )}`
        : '—';
    const band = p.scored ? `[${p.lower.toFixed(1)}, ${p.upper.toFixed(1)}]` : 'not scored yet';
    const verdict = !p.scored
      ? p.reason === 'missing_data'
        ? 'gap'
        : 'warming up'
      : p.isAnomaly
        ? `ANOMALY (${p.direction}, ${p.severity.toFixed(1)}σ out)`
        : 'normal';
    el.innerHTML =
      `<span class="dkx-ro-k">point</span> ${at} ` +
      `<span class="dkx-ro-k">value</span> ${Number.isFinite(p.value) ? p.value.toFixed(1) : '—'} ` +
      `<span class="dkx-ro-k">expected</span> ${band} ` +
      `<span class="dkx-ro-k">window</span> ${span} ` +
      `<span class="dkx-ro-v dkx-ro-${p.isAnomaly && p.scored ? 'anom' : 'ok'}">${verdict}</span>`;
    el.classList.add('on');
  };

  // navigable: mouse-wheel zoom + drag-to-pan + double-click reset + a bottom
  // navigator strip, so a dense series (many tight cycles) can be zoomed in to
  // inspect individual peaks (same control as `dtk tune`).
  // yFit:'data': fit the y-axis to the DATA, not the confidence band. Otherwise
  // widening the Threshold grows the band AND the axis in lockstep, so the
  // corridor always looks thin — even when it has ballooned past zero and the
  // metric is effectively useless. With data-fit the band visibly widens (and
  // clips past the plot edges) as you raise the threshold, so the real trade-off —
  // fewer flags, but an ever-wider, eventually-meaningless band — is on screen.
  const chart = createChart(canvas, { onHover, yFit: 'data', navigable: true });

  let currentSeries: Series | null = null;

  const setBadge = (sc: Scorecard, series: Series): void => {
    out('dkx-stat-caught', `${sc.caught}/${sc.injectedTotal}`);
    out('dkx-stat-fp', String(sc.falsePositives));
    out('dkx-stat-flagged', String(sc.flaggedTotal));
    out('dkx-stat-flagrate', `${(sc.flagRate * 100).toFixed(1)}%`);
    out('dkx-stat-mcc', sc.mcc.toFixed(2));

    const alertEl = root.querySelector<HTMLElement>('#dkx-alert');
    if (alertEl) {
      const fires = sc.alertFireIndexes;
      if (fires.length > 0) {
        const count = fires.length;
        // A compact strip of fire times (cap the rendered chips so the card
        // never overflows; the count above is always exact).
        const shown = fires.slice(0, 6);
        const chips = shown
          .map(
            (i) =>
              `<span class="dkx-fire-chip">${fmtTime(series.timestamps[i], series.intervalSeconds)}</span>`,
          )
          .join('');
        const more = count > shown.length ? `<span class="dkx-fire-more">+${count - shown.length}</span>` : '';
        alertEl.innerHTML =
          `<div class="dkx-alert-head"><span class="dkx-dot dkx-dot-anom"></span>` +
          `<b>${count}</b> alert${count === 1 ? '' : 's'} would fire</div>` +
          `<div class="dkx-fire-strip">${chips}${more}</div>`;
        alertEl.className = 'dkx-alert on fires';
      } else {
        alertEl.innerHTML =
          `<div class="dkx-alert-head"><span class="dkx-dot dkx-dot-ok"></span>` +
          `no alert <span class="dkx-alert-sub">(need ${num('dkx-consecutive')} in a row)</span></div>`;
        alertEl.className = 'dkx-alert on quiet';
      }
    }
  };

  let queued = false;
  const recompute = (): void => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const params = readParams();
      const synth = readSynth();

      // Size the series by the warm-up so the EFFECTIVE zone dominates the
      // chart. A provisional series at the interval's base length tells us where
      // detection reaches full power; if too little of it would actually be
      // scored, regenerate longer so ~300+ effective points remain.
      const provisional = generateSeries(synth);
      const eff = effectiveStartIndex(provisional, params);
      let series = provisional;
      if (provisional.timestamps.length - eff < 300) {
        const points = Math.min(eff + 320, 1200);
        series = generateSeries({ ...synth, points });
      }
      currentSeries = series;

      const scored = runDetector(series, params);
      const sc = computeScorecard(series, scored, params.consecutiveAnomalies);

      // Surface ALL fired alerts on the chart timeline (one per incident).
      const alerts: ChartAlert[] = sc.alertFireIndexes.map((i) => ({
        t: series.timestamps[i],
        kind: 'anomaly',
      }));

      chart.render({ series, scored, params, alerts });
      setBadge(sc, series);

      // echo the live config (so people see the knobs map to real params)
      out(
        'dkx-config',
        `${params.type} · threshold=${params.threshold} · window_size=${params.windowSize}` +
          (params.windowWeights !== 'none'
            ? ` · weights=${params.windowWeights}${params.windowWeights === 'exponential' ? `(half_life=${params.halfLife})` : ''}`
            : '') +
          (params.detrend !== 'none' ? ` · detrend=${params.detrend}` : '') +
          (params.smoothing !== 'none' ? ` · smoothing=${params.smoothing}` : '') +
          (params.seasonalityComponents
            ? ` · seasonality=[${params.seasonalityComponents.map((g) => g.join('+')).join(',')}]`
            : '') +
          ` · consecutive_anomalies=${params.consecutiveAnomalies}`,
      );

      // Surface when the window is too small to fill the chosen seasonality, so
      // the band silently uses global stats (mirrors the Python detector's runtime
      // warning + the dtk tune indicator). Without it, the wide band reads as a bug.
      const warnEl = root.querySelector<HTMLElement>('#dkx-season-warn');
      if (warnEl) {
        const card = seasonalCardinality(series, params.seasonalityComponents);
        const needed = params.minSamplesPerGroup * card;
        if (params.seasonalityComponents && card > 0 && params.windowSize < needed) {
          warnEl.textContent =
            `⚠ Seasonality inactive at this window: ${params.windowSize} < ${needed} ` +
            `(min_samples_per_group ${params.minSamplesPerGroup} × ${card} keys). Each point keeps ` +
            `only ~${Math.floor(params.windowSize / card)} same-key point(s), so the band falls back ` +
            `to global statistics. Raise the window to ≥ ${needed} to condition on the season.`;
          warnEl.hidden = false;
        } else {
          warnEl.hidden = true;
        }
      }

      // Note in the legend hint whether the live line is the smoothed series.
      const smoothEl = root.querySelector<HTMLElement>('#dkx-smooth-note');
      if (smoothEl) {
        if (params.smoothing !== 'none') {
          smoothEl.textContent = `· line shown is ${params.smoothing}-smoothed (raw is the faint ghost)`;
          smoothEl.classList.remove('hidden');
        } else {
          smoothEl.classList.add('hidden');
        }
      }
    });
  };

  // ---- wire controls ---------------------------------------------------------
  // Segmented buttons: clicking sets the active sibling and (for detector type)
  // resets the threshold default, then recomputes.
  root.querySelectorAll<HTMLElement>('[data-control]').forEach((group) => {
    const name = group.dataset.control as string;
    group.querySelectorAll<HTMLButtonElement>('button[data-v]').forEach((btn) => {
      btn.addEventListener('click', () => {
        setSeg(name, btn.dataset.v as string);
        if (name === 'detector') {
          const t = btn.dataset.v as DetectorType;
          const tEl = root.querySelector<HTMLInputElement>('#dkx-threshold');
          if (tEl) {
            tEl.value = String(DETECTOR_THRESHOLD_DEFAULT[t]);
            out('dkx-threshold-val', tEl.value);
          }
        }
        if (name === 'weights') {
          root
            .querySelector<HTMLElement>('#dkx-halflife-row')
            ?.classList.toggle('hidden', btn.dataset.v !== 'exponential');
        }
        recompute();
      });
    });
  });

  // Range inputs: live value echo + recompute.
  const ranges: [string, string, (v: number) => string][] = [
    ['dkx-magnitude', 'dkx-magnitude-val', (v) => `${v}%`],
    ['dkx-threshold', 'dkx-threshold-val', (v) => v.toFixed(1)],
    ['dkx-window', 'dkx-window-val', (v) => String(v)],
    ['dkx-halflife', 'dkx-halflife-val', (v) => String(v)],
    ['dkx-consecutive', 'dkx-consecutive-val', (v) => String(v)],
  ];
  for (const [id, valId, fmt] of ranges) {
    const el = root.querySelector<HTMLInputElement>(`#${id}`);
    el?.addEventListener('input', () => {
      out(valId, fmt(Number(el.value)));
      recompute();
    });
  }

  // Reseed: new random instance of the same shape.
  root.querySelector<HTMLButtonElement>('#dkx-reseed')?.addEventListener('click', () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    recompute();
  });

  window.addEventListener('resize', () => chart.resize());

  // Initial value echoes + first paint.
  for (const [id, valId, fmt] of ranges) {
    const el = root.querySelector<HTMLInputElement>(`#${id}`);
    if (el) out(valId, fmt(Number(el.value)));
  }
  recompute();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}
