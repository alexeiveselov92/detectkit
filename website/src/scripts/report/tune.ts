// tune.ts — the interactive manual-tuning renderer for `dtk tune`.
//
// The human-in-the-loop sibling of the report renderer. The Python tuning layer
// (detectkit/tuning/) bakes a TunePayload — the metric's REAL gap-filled series,
// the per-point seasonality keys, the current detector config and the alert
// consecutive window — into a self-contained HTML page and inlines this bundle.
// At load it assigns `window.__DTK_TUNE__ = { render }`.
//
// Unlike the read-only report, this view RECOMPUTES live: it reuses the same
// faithful TypeScript detector port (../demo/detector) and chart (../demo/chart)
// that power the landing playground, fed the real series instead of synthetic
// data. Turning a knob re-runs runDetector → chart.render in well under a frame.
// When the payload carries a `save_url` (the localhost server), an "Apply to
// metric" button POSTs the chosen config back; without it (a static preview) the
// sliders still recompute but there is no write-back.
//
// The state-free helpers (types, DOM controls, formatters, styles, the worker
// client, the quality metrics) live in ./tune/*; render() below stays the
// composition root.

import { createChart } from '../demo/chart';
import type {
  AlertDirection,
  ChartAlert,
  ChartHandle,
  Detrend,
  DetectorParams,
  DetectorType,
  Incident,
  LassoInfo,
  ScoredPoint,
  Series,
  Smoothing,
  Stabilization,
  ThresholdInfo,
  WindowWeights,
} from '../demo/types';
import { applyParams, configText } from './tune/config-text';
import { ctlLabel, el, rangeControl, segControl } from './tune/controls';
import type { SegSpec } from './tune/controls';
import { fmtDur, fmtInterval, fmtNum, fmtTs } from './tune/format';
import type { WorkerResult } from './tune/protocol';
import { computeQuality, renderMetricsBar } from './tune/quality';
import { injectStyle } from './tune/style';
import {
  MIN_SAMPLES_PER_GROUP_DEFAULT,
  MIN_SAMPLES_PER_GROUP_FLOOR,
  ROOT_CLASS,
  THRESHOLD_DEFAULT,
} from './tune/types';
import type { AutotuneResult, DetectorEntry, DetectorSeed, TunePayload, UiMode } from './tune/types';
import { createTuneWorkerClient } from './tune/worker-client';

// The bundled detector worker source, injected as a string literal at build time
// (see website/scripts/gen-tune-bundle.mjs). Instantiated from a Blob URL so the
// report stays a single self-contained file with no external requests.
declare const __DTK_WORKER_SRC__: string;

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

// Optional, purely-additive hooks. The shipped `dtk tune` HTML calls
// render(payload, mount) with neither argument, so its behavior is unchanged; the
// landing playground passes an `onState` callback (to preserve the tuned knobs
// across a data-generator re-mount) and calls the returned `destroy()` before each
// re-mount (to release the worker + global listeners rather than leak one per run).
interface TuneHooks {
  onState?: (s: {
    params: DetectorParams;
    windowPoints: number | null;
    share: number | null;
  }) => void;
}

function render(
  payload: TunePayload,
  mount: HTMLElement,
  hooks?: TuneHooks,
): { destroy: () => void; resize: () => void } {
  injectStyle();
  mount.classList.add(ROOT_CLASS);
  mount.innerHTML = '';
  const root = el('div', 'dtk-tune-root');
  mount.appendChild(root);

  // ---- series from the real persisted points -------------------------------
  const n = payload.points.length;
  const fullSeries: Series = {
    timestamps: payload.points.map((p) => p.t),
    values: payload.points.map((p) => (p.v == null ? NaN : p.v)),
    intervalSeconds: payload.interval_seconds,
    truthAnomaly: new Array(n).fill(false),
    seasonalityData: payload.seasonality_columns.length ? payload.seasonality : undefined,
    seasonalityColumns: payload.seasonality_columns.length
      ? payload.seasonality_columns
      : undefined,
  };
  // The active series fed to the detector + chart. The trim slider can shorten it
  // to the most-recent N points, so a very long/heavy metric recomputes faster
  // (cost is O(points × window)) once you've confirmed a smaller period suffices.
  let series: Series = fullSeries;
  const sliceSeries = (count: number): Series => {
    const start = Math.max(0, n - count);
    if (start <= 0) return fullSeries;
    return {
      timestamps: fullSeries.timestamps.slice(start),
      values: fullSeries.values.slice(start),
      intervalSeconds: fullSeries.intervalSeconds,
      truthAnomaly: fullSeries.truthAnomaly.slice(start),
      seasonalityData: fullSeries.seasonalityData
        ? fullSeries.seasonalityData.slice(start)
        : undefined,
      seasonalityColumns: fullSeries.seasonalityColumns,
    };
  };
  // ---- incident labels (the synced labeler shares this exact array) ---------
  // Parsed to ms from the seeded display strings; the labeler chart mutates this
  // SAME array in place (drag create/move/resize/delete) and the controls list
  // edits labels in place — one source of truth, so nothing diverges.
  const parseDisplayTs = (s: string): number => Date.parse(s.replace(' ', 'T') + 'Z');
  const incidents: Incident[] = (payload.incidents || [])
    .map((p) => ({ start: parseDisplayTs(p.start), end: parseDisplayTs(p.end), label: p.label || '' }))
    .filter((iv) => Number.isFinite(iv.start) && Number.isFinite(iv.end))
    .map((iv) => ({ start: Math.min(iv.start, iv.end), end: Math.max(iv.start, iv.end), label: iv.label }));
  // Seeded threshold-capture window (regime scope) from the saved labels file —
  // restored so re-opening keeps the painted scope. Only the first is used.
  const seedCaptureWin = ((): { start: number; end: number } | null => {
    const w = (payload.capture_windows || [])[0];
    if (!w) return null;
    const a = parseDisplayTs(w.start);
    const b = parseDisplayTs(w.end);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    return { start: Math.min(a, b), end: Math.max(a, b) };
  })();
  // Most-recent worker output, for the live metrics + the synced labeler chart.
  let lastFireTs: number[] = [];
  // Per-alert anomaly-streak spans (ms) — recall/FDR match incidents by OVERLAP
  // with these, not just the fire point (which lands consecutive-1 intervals in).
  let lastFireSpans: Array<[number, number]> = [];
  let lastScored: ScoredPoint[] = [];
  let lastAlerts: ChartAlert[] = [];

  // ---- per-alert review verdicts (validated / false alarm) -------------------
  // The user can confirm each fired alert right on the chart (Review mode / a click
  // on a marker). Stored by STREAK SPAN so a verdict survives a recompute that moves
  // the alerts — it re-binds by overlap, not by an exact timestamp. A 'valid' span
  // also counts as a VIRTUAL incident for recall/FDR (and is written as an incident
  // on Save, so confirming alerts also feeds dtk autotune). 'false' is an explicit
  // false-alarm mark (slate marker); it never rescues the alert from the FDR.
  type Verdict = 'valid' | 'false';
  const reviews: Array<{ start: number; end: number; verdict: Verdict }> = (payload.alert_reviews || [])
    .map((r) => ({
      start: parseDisplayTs(r.start),
      end: parseDisplayTs(r.end),
      verdict: (r.verdict === 'false' ? 'false' : 'valid') as Verdict,
    }))
    .filter((r) => Number.isFinite(r.start) && Number.isFinite(r.end));
  const spanTol = (): number => (payload.interval_seconds * 1000) / 2;
  const reviewFor = (s: number, e: number): Verdict | null => {
    const tol = spanTol();
    for (const r of reviews) if (e >= r.start - tol && s <= r.end + tol) return r.verdict;
    return null;
  };
  const setReview = (s: number, e: number, v: Verdict | null): void => {
    const tol = spanTol();
    for (let i = reviews.length - 1; i >= 0; i--) {
      const r = reviews[i];
      if (e >= r.start - tol && s <= r.end + tol) reviews.splice(i, 1);
    }
    if (v) reviews.push({ start: s, end: e, verdict: v });
  };
  // Confirming an alert valid IS marking an incident there: a valid verdict is the
  // user asserting "a real incident happened in this span". So a valid review is a
  // first-class ground-truth incident — derived from the STORED review span (not the
  // current fire span), so it stays in the ground truth even if the current knob
  // setting no longer fires there (that's a recall MISS the metrics should show) and
  // survives recompute. These show up as rows in the Marked-incidents list and feed
  // recall/FDR alongside the hand-marked incidents — the two are one set, not two.
  const overlapIv = (
    a: { start: number; end: number },
    b: { start: number; end: number },
  ): boolean => {
    const tol = spanTol();
    return a.end >= b.start - tol && a.start <= b.end + tol;
  };
  const validatedSpans = (): Incident[] =>
    reviews
      .filter((r) => r.verdict === 'valid')
      .map((r) => ({ start: r.start, end: r.end, label: 'confirmed alert' }));
  // Validated spans NOT already covered by a hand-marked incident (dedup by overlap)
  // — so the same real incident is never listed/scored/saved twice (e.g. after a
  // Save→reopen, where a confirmed alert is seeded both as an incident and a review).
  const validatedExtra = (): Incident[] =>
    validatedSpans().filter((v) => !incidents.some((iv) => overlapIv(v, iv)));
  // The full ground-truth incident set the live metrics, the list and Save all share.
  const groundTruth = (): Incident[] => [...incidents, ...validatedExtra()];
  // Deleting a hand-marked incident asserts "no real incident in this span", so any
  // confirmed-VALID alert overlapping it is retracted too (cleared to un-reviewed, like
  // unconfirmAlert). Otherwise that verdict — which validatedExtra() was hiding behind
  // the incident — RESURFACES as its own "confirmed alert" row, so the deleted incident
  // appears to turn INTO a confirmed alert instead of vanishing. (Seeded case: Save
  // writes each confirmed alert as both an incident AND a review, so on reopen every
  // incident is backed by one.) Leaves explicit 'false' verdicts alone. Returns whether
  // anything was cleared (→ the alert markers need repainting).
  const retractConfirmationFor = (iv: Incident): boolean => {
    let changed = false;
    for (let i = reviews.length - 1; i >= 0; i--) {
      if (reviews[i].verdict === 'valid' && overlapIv(reviews[i], iv)) {
        reviews.splice(i, 1);
        changed = true;
      }
    }
    return changed;
  };
  // Build the alert markers with their review-verdict color (red / green / slate).
  const buildAlerts = (): ChartAlert[] =>
    lastFireTs.map((t, i) => {
      const sp = lastFireSpans[i] ?? [t, t];
      const v = reviewFor(sp[0], sp[1]);
      return { t, kind: v === 'valid' ? 'anomaly-validated' : v === 'false' ? 'anomaly-false' : 'anomaly' };
    });

  // ---- mutable parameter state, seeded from the metric's current config -----
  // `seed` is the ACTIVE detector's seed — the picker (a multi-detector metric)
  // re-seeds it when you switch which detector you're tuning. readParams() reads
  // the passthrough knobs (minSamples/inputType/smoothing*) off it.
  let seed = payload.detector;

  // The Min-samples-per-group knob (below) only exists when the metric has
  // seasonality columns — the parameter is inert without seasonality — so it is
  // declared here (null until created) and readParams() honors the seed value
  // when it is absent. Per-type default/floor helpers keep it in step with the
  // Threshold knob (both reset to the new type's default on a detector switch).
  let minSamplesPerGroupCtl: ReturnType<typeof rangeControl> | null = null;
  const mspgDefault = (t: DetectorType): number => MIN_SAMPLES_PER_GROUP_DEFAULT[t] ?? 10;
  const mspgFloor = (t: DetectorType): number => MIN_SAMPLES_PER_GROUP_FLOOR[t] ?? 1;
  let consecutive = payload.consecutive_anomalies;
  // Fraction alert rule (issue #101): OR-ed with the consecutive rule, exactly
  // like the pipeline. 0/absent window ⇒ off (legacy consecutive-only); the
  // pair is both-or-neither (the share control only matters with a window).
  let anomalyWindowPoints = payload.anomaly_window_points ?? 0;
  let minAnomalyShare = payload.min_anomaly_share ?? 0.3;
  const shareWindowPoints = (): number | null =>
    anomalyWindowPoints >= 2 ? anomalyWindowPoints : null;
  const shareValue = (): number | null => (anomalyWindowPoints >= 2 ? minAnomalyShare : null);

  // ---- multi-detector picker state ------------------------------------------
  // The cockpit tunes ONE detector at a time but a metric can configure several
  // (e.g. a mad pattern detector + a manual_bounds floor). We open on `activeIndex`
  // (the slot the payload picked), remember each detector's live params across
  // switches (`editedParams`), and track which slots the user actually edited
  // (`dirty`). On Apply we write back ONLY the active + dirty slots — every other
  // detector is preserved verbatim by the server, so a retune can't silently drop a
  // floor and kill a min_detectors>=2 alert (the reported bug).
  const detectorEntries: DetectorEntry[] = payload.detectors || [];
  let activeIndex: number | null =
    typeof payload.detector_index === 'number' ? payload.detector_index : null;
  // The slot the cockpit opened on — "the detector you came to tune". It is written
  // on Apply even if you didn't move a knob (matching single-detector behaviour). A
  // detector you merely SWITCHED the picker to but never edited is NOT written, so a
  // lower-bound-only manual_bounds floor can't gain a phantom upper_bound just from
  // being looked at.
  const initialIndex: number | null = activeIndex;
  const dirty = new Set<number>();
  const editedParams = new Map<number, DetectorParams>();
  const markActiveDirty = (): void => {
    if (activeIndex != null) dirty.add(activeIndex);
  };

  // manual_bounds support: derive the value domain from the REAL series so the
  // lower/upper sliders have a sensible range, and seed default bounds. If the
  // metric already uses manual_bounds, its seeded bounds win; otherwise default
  // to the p5/p95 band so switching to manual_bounds shows feedback immediately.
  const finiteVals = fullSeries.values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  const dataMin = finiteVals.length ? finiteVals[0] : 0;
  const dataMax = finiteVals.length ? finiteVals[finiteVals.length - 1] : 1;
  const pct = (q: number): number =>
    finiteVals.length
      ? finiteVals[Math.min(finiteVals.length - 1, Math.max(0, Math.round(q * (finiteVals.length - 1))))]
      : 0;
  const boundPad = Math.max((dataMax - dataMin) * 0.05, 1e-9);
  const boundMin = dataMin - boundPad;
  const boundMax = dataMax + boundPad;
  const boundStep = Math.max((boundMax - boundMin) / 400, 1e-9);
  const seedLower = seed.lowerBound != null ? seed.lowerBound : pct(0.05);
  const seedUpper = seed.upperBound != null ? seed.upperBound : pct(0.95);
  // seasonality: each available column is assigned to a group id (0 = off).
  // Columns sharing a group are conjoined into one seasonal key; separate groups
  // apply independent (cumulative) corrections — the full string[][] the detector
  // supports, not just "all-separate" or "all-in-one".
  const seedGroups = seed.seasonalityComponents ?? [];
  const colGroup = new Map<string, number>();
  seedGroups.forEach((grp, gi) => grp.forEach((c) => colGroup.set(c, gi + 1)));

  const buildSeasonality = (): string[][] | null => {
    let maxG = 0;
    colGroup.forEach((g) => {
      if (g > maxG) maxG = g;
    });
    const groups: string[][] = [];
    for (let g = 1; g <= maxG; g++) {
      const cols = payload.seasonality_columns.filter((c) => colGroup.get(c) === g);
      if (cols.length) groups.push(cols);
    }
    return groups.length ? groups : null;
  };

  // Distinct seasonal keys present for a grouping (max across groups). Same-key
  // points recur once per this many positions, so the window must hold ~this many
  // × min_samples_per_group points before a group fills; below that the detector
  // silently falls back to the global band (seasonality has no effect).
  const seasonalCardinality = (groups: string[][] | null): number => {
    if (!groups || !payload.seasonality.length) return 0;
    let card = 0;
    for (const g of groups) {
      const seen = new Set<string>();
      for (const row of payload.seasonality) seen.add(g.map((c) => String(row?.[c] ?? '')).join('|'));
      card = Math.max(card, seen.size);
    }
    return card;
  };

  // Captures EVERY control's state — including windowed-only knobs while an
  // autoreg/manual_bounds type is selected (their rows hide but the state must
  // survive: editedParams round-trips through the slot picker and a later
  // windowed re-seed restores it). Consumers that render or persist params must
  // therefore branch by detector type (applyParams, updateSeasonWarn, the
  // chart's smoothing ghost) rather than trust an inert field — nulling a field
  // here instead would silently lose the windowed slot's setting (#148).
  const readParams = (): DetectorParams => ({
    type: detectorCtl.get() as DetectorType,
    threshold: thresholdCtl.get(),
    windowSize: windowCtl.get(),
    // Read from the live Min-samples knob (capped at the window); it exists for
    // every detector but is inert for manual_bounds (which has no window).
    minSamples: Math.round(minSamplesCtl.get()),
    inputType: seed.inputType,
    smoothing: smoothingCtl.get() as Smoothing,
    smoothingAlpha: seed.smoothingAlpha,
    smoothingWindow: seed.smoothingWindow,
    windowWeights: weightsCtl.get() as WindowWeights,
    halfLife: weightsCtl.get() === 'exponential' ? halfLifeCtl.get() : null,
    detrend: detrendCtl.get() as Detrend,
    stabilization: stabilizationCtl.get() as Stabilization,
    seasonalityComponents: buildSeasonality(),
    // Read the live knob when it exists (seasonal metrics), else honor the
    // seeded config value — NOT the per-type default: the old default-first
    // read silently discarded a metric's configured min_samples_per_group.
    minSamplesPerGroup: minSamplesPerGroupCtl
      ? Math.round(minSamplesPerGroupCtl.get())
      : seed.minSamplesPerGroup ?? mspgDefault(detectorCtl.get() as DetectorType),
    consecutiveAnomalies: consecutive,
    direction: directionCtl.get() as AlertDirection,
    // Read from the bound sliders regardless of type; the windowed detectors
    // ignore these, the manual_bounds port reads them.
    lowerBound: lowerBoundCtl.get(),
    upperBound: upperBoundCtl.get(),
    // autoreg only — ignored by the other detectors.
    lags: lagsCtl.get(),
  });

  // ---- header ---------------------------------------------------------------
  const header = el('div', 'dtk-tune-header');
  const titleRow = el('div', 'dtk-tune-titlerow');
  titleRow.appendChild(el('h1', 'dtk-tune-title', payload.metric));
  const badge = el('span', 'dtk-tune-badge', payload.save_url ? 'manual tuning' : 'preview');
  titleRow.appendChild(badge);
  header.appendChild(titleRow);
  const sub = payload.project ? `${payload.project} · ` : '';
  header.appendChild(
    el(
      'div',
      'dtk-tune-sub',
      `${sub}${n} points · ${fmtInterval(payload.interval_seconds)} grid`,
    ),
  );
  if (payload.description) header.appendChild(el('div', 'dtk-tune-desc', payload.description));
  root.appendChild(header);

  // ---- alert-quality metrics bar (the "speedometer") -----------------------
  // Operator-facing numbers, recomputed live (real incidents / caught / alerts /
  // false / reviewed). Rides pinned in the HUD over the chart so it stays in view
  // across every mode — never scrolled past.
  const metricsBar = el('div', 'dtk-tune-metrics');

  // ---- cockpit layout: chart-windshield + always-visible control rail -------
  // The chart fills the screen as the windshield; the live metrics ride pinned in
  // a HUD strip over it, and every control lives in a right-hand RAIL that is
  // always visible with its own scroll. So you turn a knob and watch the band
  // change with no scrolling and no gaze-drop to a dock below. The rail is also
  // MODE-AWARE: it shows only the panel the current mode needs — the detector
  // knobs + effective config + Apply in Tune, the verdict actions in Review, the
  // capture tools + incident list + Save in Label — instead of every control at
  // once. Collapse it (⟩) to hand the chart the whole width.
  const cockpit = el('div', 'dtk-tune-cockpit');
  root.appendChild(cockpit);
  const stage = el('div', 'dtk-tune-stage');
  cockpit.appendChild(stage);
  // HUD over the chart: the speedometer leads, the mode switch sits at the right.
  const hud = el('div', 'dtk-tune-hud');
  hud.appendChild(metricsBar);
  stage.appendChild(hud);
  // Stage footer (hover readout + stat line + season warning) — created now,
  // filled below; attached right under the chart. (The legend is a TOP strip,
  // mounted above the chart, not here — see below.)
  const stageFoot = el('div', 'dtk-tune-stagefoot');

  // The control rail: a fixed header (mode-named + collapse), the scrolling control
  // column split into per-mode GROUPS, and a Tune-only action footer (effective
  // config + Apply) that never scrolls away.
  const rail = el('div', 'dtk-tune-rail');
  cockpit.appendChild(rail);
  const railHead = el('div', 'dtk-tune-railhead');
  const railTitle = el('span', 'dtk-rail-title', 'Tune · controls');
  const dockToggle = el('button', 'dtk-dock-toggle', '⟩');
  dockToggle.type = 'button';
  dockToggle.title = 'Collapse the control rail to give the chart the whole width.';
  railHead.appendChild(railTitle);
  railHead.appendChild(dockToggle);
  rail.appendChild(railHead);
  const controls = el('div', 'dtk-tune-controls');
  rail.appendChild(controls);
  // Controls split into ALWAYS-visible common groups + per-mode groups. The common
  // groups apply to every mode, so they stay put as you switch — `topCommon` (the
  // data window: Points shown) at the top, `alertCommon` (the alert rule — direction
  // + consecutive — and the y = 0 view toggle) at the bottom. setUiMode only toggles
  // the per-mode group sandwiched between them. Column order: topCommon · <mode> ·
  // alertCommon.
  const topCommon = el('div', 'dtk-rail-group');
  const tuneGroup = el('div', 'dtk-rail-group');
  const reviewGroup = el('div', 'dtk-rail-group');
  const labelGroup = el('div', 'dtk-rail-group');
  const autotuneGroup = el('div', 'dtk-rail-group');
  const alertCommon = el('div', 'dtk-rail-group');
  reviewGroup.style.display = 'none';
  labelGroup.style.display = 'none';
  autotuneGroup.style.display = 'none';
  controls.append(topCommon, tuneGroup, reviewGroup, labelGroup, autotuneGroup, alertCommon);
  // Tune-only footer (effective config + Apply); hidden in Review / Label.
  const railFoot = el('div', 'dtk-tune-railfoot');
  rail.appendChild(railFoot);
  // A slim tab on the chart's right edge re-opens the rail once collapsed.
  const railOpen = el('button', 'dtk-rail-open', '⚙');
  railOpen.type = 'button';
  railOpen.title = 'Show the control rail';
  railOpen.style.display = 'none';
  stage.appendChild(railOpen);

  const setDock = (open: boolean): void => {
    rail.style.display = open ? '' : 'none';
    railOpen.style.display = open ? 'none' : '';
    // The chart's ResizeObserver re-fits it when the rail hides/shows.
  };
  dockToggle.onclick = (): void => setDock(false);
  railOpen.onclick = (): void => setDock(true);

  // ---- trim slider (top of the rail — applies to every mode) ---------------
  // Shorten the active sample to the most-recent N points. The fitted period
  // shrinks and the live recompute speeds up (cost ∝ points × window). Echo is
  // live; the actual re-slice/recompute is debounced.
  const trimWrap = el('div', 'dtk-tune-trim');
  const trimHead = el('div', 'dtk-tune-trim-head');
  trimHead.appendChild(
    ctlLabel(
      'Points shown',
      'Trim the active sample to the most-recent N points. Fewer points recompute faster ' +
        '(cost grows with points × window) and make a shorter period easier to read — handy ' +
        'once you can see a smaller window/period is enough.',
    ),
  );
  const trimEcho = el('span', 'dtk-tune-trim-val');
  trimHead.appendChild(trimEcho);
  trimWrap.appendChild(trimHead);
  const trimInput = el('input', 'dtk-range');
  trimInput.type = 'range';
  trimInput.min = String(Math.min(n, 200));
  trimInput.max = String(n);
  trimInput.step = String(Math.max(1, Math.round(n / 200)));
  trimInput.value = String(n);
  trimWrap.appendChild(trimInput);
  topCommon.appendChild(trimWrap);

  // chart
  const chartWrap = el('div', 'dtk-tune-chart');
  const canvas = el('canvas');
  chartWrap.appendChild(canvas);
  // recompute spinner overlay (top-right of the chart)
  const spinner = el('div', 'dtk-tune-spin');
  spinner.appendChild(el('span', 'dtk-spin-ring'));
  spinner.appendChild(el('span', 'dtk-spin-txt', 'computing…'));
  chartWrap.appendChild(spinner);
  stage.appendChild(chartWrap);
  stage.appendChild(stageFoot);

  // ---- mode switch (Tune / Review / Label / Autotune) -----------------------
  // One chart, four jobs: the mode picks which layers lead and which interactions
  // are armed. 'tune' steers the band, 'review' confirms the fired alerts, 'label'
  // marks incidents, and 'autotune' runs the server-side search and re-seeds the
  // knobs with the winner (the chart leads with the band, like 'tune'). setUiMode
  // (defined once the tool bars exist) drives the chart + reveals the matching tools.
  const modeRow = el('div', 'dtk-tune-modes');
  const modeBtns: Partial<Record<UiMode, HTMLButtonElement>> = {};
  const MODES: Array<{ v: UiMode; label: string; hint: string }> = [
    { v: 'tune', label: 'Tune', hint: 'Steer the band — the confidence corridor leads; incidents recede to read-only context. Hover a point for its window.' },
    { v: 'review', label: 'Review alerts', hint: 'Confirm the fired alerts — click a marker to cycle un-reviewed → valid (green) → false (slate). The band ghosts so the alerts lead.' },
    { v: 'label', label: 'Label incidents', hint: 'Mark real incidents — drag a span, lasso the anomaly cloud, or threshold-capture. The band hides so incidents lead.' },
    { v: 'autotune', label: 'Autotune', hint: 'Let the autotune engine search for the best detector server-side, using your marked incidents as ground truth, then re-seed the knobs with the winner. Review the band, then Apply.' },
  ];
  MODES.forEach((md) => {
    const b = el('button', 'dtk-mode-btn', md.label);
    b.type = 'button';
    b.title = md.hint;
    b.dataset.v = md.v;
    b.onclick = (): void => setUiMode(md.v);
    modeBtns[md.v] = b;
    modeRow.appendChild(b);
  });
  // The mode switch rides in the HUD at the right of the chart (metrics already
  // mounted at its left), so switching modes never requires a scroll.
  hud.appendChild(modeRow);

  // Legend — a colour key for the chart, pinned at the TOP of the stage (right
  // under the HUD, above the chart) so it reads almost immediately and stays put
  // in EVERY mode (it lives in the stage, not the mode-aware rail). It leads with
  // the alert colours — red (fired), green (confirmed valid), slate (false alarm) —
  // the three markers a user most needs decoded while reviewing.
  const legend = el('div', 'dtk-tune-legend');
  const legItem = (sw: string, text: string, hint: string): void => {
    const item = el('span', 'dtk-leg-item');
    item.title = hint;
    item.appendChild(el('span', `dtk-leg-sw ${sw}`));
    item.appendChild(el('span', 'dtk-leg-txt', text));
    legend.appendChild(item);
  };
  legItem('alert', 'alert', 'A fired alert, not yet reviewed — enough consecutive anomalies to meet the rule.');
  legItem('alert-ok', 'valid alert', 'An alert you confirmed is real (click a marker in Review mode). Counts toward recall.');
  legItem('alert-no', 'false alarm', 'An alert you marked a false positive. Stays in the false-alert rate.');
  legItem('dot', 'anomaly', 'A point the detector flagged as anomalous (outside the band).');
  legItem('line', 'metric', 'The metric value over time.');
  legItem('band', 'expected range', "The detector's confidence band — values inside it read as normal.");
  legItem('center', 'band center', 'The expected value at the middle of the band.');
  // Mount it as a top strip between the HUD and the chart, not in the footer below.
  stage.insertBefore(legend, chartWrap);

  const readout = el('div', 'dtk-tune-readout');
  stageFoot.appendChild(readout);

  // Surfaces when the window is too small to fill the chosen seasonality, so the
  // band silently uses global (un-conditioned) statistics. Mirrors the Python
  // detector's runtime warning — without it a wide band reads like a bug.
  const seasonWarn = el('div', 'dtk-tune-warn');
  seasonWarn.style.display = 'none';
  stageFoot.appendChild(seasonWarn);
  const updateSeasonWarn = (params: DetectorParams): void => {
    // Seasonality is a windowed-detector concept: autoreg (v1 rejects it) and
    // manual_bounds never condition on seasonal keys, but their params still
    // carry the hidden group selector's state (readParams deliberately captures
    // every control so a slot/type round-trip can restore it). Without this
    // guard the leaked value blamed the autoreg band's width on a seasonality
    // fallback — machinery the detector doesn't even have (#148).
    if (params.type === 'autoreg' || params.type === 'manual_bounds') {
      seasonWarn.style.display = 'none';
      return;
    }
    const groups = params.seasonalityComponents;
    const card = seasonalCardinality(groups);
    const needed = params.minSamplesPerGroup * card;
    if (groups && card > 0 && params.windowSize < needed) {
      seasonWarn.textContent =
        `⚠ Seasonality inactive at this window: ${params.windowSize} < ${needed} ` +
        `(min_samples_per_group ${params.minSamplesPerGroup} × ${card} key${card === 1 ? '' : 's'}). ` +
        `Each point keeps only ~${Math.floor(params.windowSize / card)} same-key point(s), so the ` +
        `band falls back to global statistics (seasonality has no effect) — this, not the smaller ` +
        `window itself, is why the band widened. Raise the window to ≥ ${needed}, or lower ` +
        `“Min samples per group”.`;
      seasonWarn.style.display = '';
    } else {
      seasonWarn.style.display = 'none';
    }
  };

  // Surfaces the only genuinely-blank state left now that the chart draws the
  // band wherever the detector scores (it no longer hides the cold-start lead-in):
  // the detector produced NO band at all in the shown window — its window can't
  // collect `min_samples` valid points here (too small, too little shown history,
  // or gaps across the view). Without this the chart is a bare line with no cue.
  // (`scoredCount` comes from the worker's scored array; 0 ⇒ nothing to draw.)
  const warmupWarn = el('div', 'dtk-tune-warn');
  warmupWarn.style.display = 'none';
  stageFoot.appendChild(warmupWarn);
  const updateWarmupWarn = (scoredCount: number, params: DetectorParams): void => {
    const shown = series.timestamps.length;
    if (shown === 0 || scoredCount > 0) {
      warmupWarn.style.display = 'none';
      return;
    }
    if (params.type === 'autoreg') {
      const lags = Math.max(1, Math.round(params.lags ?? 5));
      const effMin = Math.max(params.minSamples, lags + 2);
      const fixes = [
        'raise Points shown / Window size',
        `lower “Min samples” (${params.minSamples}) or Lags (${lags})`,
      ];
      if (params.stabilization === 'clamp') fixes.push('turn Stabilization off');
      warmupWarn.textContent =
        `⚠ No band drawn: autoreg scored 0 points in the shown window. It needs ${effMin} ` +
        `gap-free fit rows of ${lags + 1} consecutive points each, and the ${params.windowSize}-point ` +
        `window can't collect them here (too small, too little shown history, or gaps in view). ` +
        `To get a band: ${fixes.join(', or ')}.`;
    } else {
      warmupWarn.textContent =
        `⚠ No band drawn: the detector scored 0 points in the shown window — the ` +
        `${params.windowSize}-point window holds fewer than “Min samples” (${params.minSamples}) valid ` +
        `points here. To get a band: raise Points shown / Window size, or lower “Min samples”.`;
    }
    warmupWarn.style.display = '';
  };

  // ---- live alert-quality metrics ------------------------------------------
  // The false-alert-rate budget the quality bar flags when exceeded (a fraction in
  // (0, 1]); resolved metric → project → built-in default by the payload builder.
  const budget =
    typeof payload.false_alert_budget === 'number' && payload.false_alert_budget > 0
      ? payload.false_alert_budget
      : null;
  function renderMetrics(): void {
    const q = computeQuality(lastFireSpans, {
      timestamps: series.timestamps,
      tol: spanTol(),
      incidents,
      validatedSpans: validatedSpans(),
      reviewFor,
    });
    renderMetricsBar(metricsBar, q, budget);
  }

  // Filled once the capture toolbars are built (the chart pushes preview state here
  // on every hover / window paint / knob change / lasso draw).
  let updateThresholdUI: (info: ThresholdInfo) => void = () => {};
  let updateLassoUI: (info: LassoInfo) => void = () => {};
  // ONE chart for the whole cockpit: band + anomaly dots + alert markers + incident
  // spans on a single windshield. The MODE (tune / review / label) decides which
  // layers lead and which recede, and which interactions are armed — so tuning,
  // confirming alerts and marking incidents share one canvas (no stacked half-charts).
  const chart: ChartHandle = createChart(canvas, {
    navigable: true,
    labeling: true,
    mode: 'tune',
    // Fit the y-axis to the data, not the band — so turning the Threshold slider
    // visibly widens/narrows the corridor relative to the metric instead of the
    // axis rescaling in lockstep and making the change look like a no-op.
    yFit: 'data',
    onHover: (info): void => {
      if (!info || !info.point || !info.point.scored) {
        readout.textContent = '';
        return;
      }
      const p = info.point;
      readout.textContent =
        `t=${fmtTs(p.timestamp)}  value=${fmtNum(p.value)}  ` +
        `band=[${fmtNum(p.lower)}, ${fmtNum(p.upper)}]` +
        (p.isAnomaly ? `  ⚠ ${p.direction} (sev ${p.severity.toFixed(2)})` : '');
    },
    onIncidentsChange: (_incidents, removed): void => {
      // The chart mutates `incidents` in place (shared ref); reflect it. If a span was
      // DELETED on the chart (✕ handle / Delete key), retract any confirmed-valid verdict
      // it overlapped (see retractConfirmationFor) so the incident is fully removed
      // instead of resurfacing as a "confirmed alert" — same as deleting it from the list.
      const retracted = removed ? retractConfirmationFor(removed) : false;
      if (retracted) repaintAlerts();
      else {
        refreshIncidentList();
        renderMetrics();
      }
    },
    onThresholdChange: (info): void => updateThresholdUI(info),
    onLassoChange: (info): void => updateLassoUI(info),
    onAlertReviewChange: (fireTs, verdict): void => {
      // Map the clicked marker back to its streak span and store the verdict by span.
      const idx = lastFireTs.indexOf(fireTs);
      const sp = idx >= 0 ? lastFireSpans[idx] : [fireTs, fireTs];
      setReview(sp[0], sp[1], verdict === 'unreviewed' ? null : (verdict as Verdict));
      repaintAlerts();
    },
  });
  chart.setIncidents(incidents);
  if (seedCaptureWin) chart.setCaptureWindow(seedCaptureWin);
  // Rebuild the alert markers' verdict colors, re-render the chart and refresh the
  // metrics — after a recompute (alerts moved) or a single review click.
  const repaintAlerts = (): void => {
    lastAlerts = buildAlerts();
    if (lastParams) {
      chart.render({ series, scored: lastScored, params: lastParams, alerts: lastAlerts, incidents });
    }
    renderMetrics();
    // A confirmed-valid alert IS an incident, so keep the list in lockstep with the
    // verdicts — confirming one in Review mode makes it show up in the incident list.
    refreshIncidentList();
  };

  // ---- threshold-capture toolbar (above the labeler chart) ------------------
  // Mark incidents fast: set a horizontal line and grab every contiguous span past
  // it in one click — the same tool as the autotune html labeler, here feeding the
  // synced incident labeler. All capture state lives in the labeler chart; this bar
  // just drives it and reflects the live run count + scope.
  const thWrap = el('div', 'dtk-th');
  const toolToggles = el('div', 'dtk-th-toggles');
  const thToggle = el('button', 'dtk-th-toggle', 'Threshold capture');
  thToggle.type = 'button';
  thToggle.title =
    'Mark incidents fast: set a horizontal line and grab every contiguous span above (or below) ' +
    'it. Click the chart to set the line, drag across it to limit the capture to a time window.';
  toolToggles.appendChild(thToggle);
  // Lasso anomalies: loop around a cloud of anomaly dots on the labeler chart →
  // each grid-adjacent run (small gaps bridged) becomes one incident span.
  const lassoToggle = el('button', 'dtk-th-toggle', 'Lasso anomalies');
  lassoToggle.type = 'button';
  lassoToggle.title =
    'Draw a freeform loop around a cloud of anomaly dots on the chart below — each run of ' +
    'consecutive anomalies (small gaps bridged) becomes one incident span. The ideal way to ' +
    'turn what the detector already flags into ground-truth incidents.';
  toolToggles.appendChild(lassoToggle);
  thWrap.appendChild(toolToggles);
  const thBar = el('div', 'dtk-th-bar');
  const thDirSel = el('select', 'dtk-th-sel');
  for (const [v, lbl] of [
    ['above', 'above the line'],
    ['below', 'below the line'],
  ] as const) {
    const o = el('option');
    o.value = v;
    o.textContent = lbl;
    thDirSel.appendChild(o);
  }
  const thValInput = el('input', 'dtk-th-num');
  thValInput.type = 'number';
  thValInput.step = 'any';
  thValInput.placeholder = 'hover chart';
  const thGapInput = el('input', 'dtk-th-num');
  thGapInput.type = 'number';
  thGapInput.min = '0';
  thGapInput.step = '1';
  thGapInput.value = '0';
  const thScope = el('span', 'dtk-th-scope');
  const thWinReset = el('button', 'dtk-inc-btn', '↺ whole view');
  thWinReset.type = 'button';
  thWinReset.style.display = 'none';
  const thAdd = el('button', 'dtk-apply-btn dtk-th-add', 'Add 0 spans');
  thAdd.type = 'button';
  thAdd.disabled = true;
  const thDone = el('button', 'dtk-inc-btn', 'Done');
  thDone.type = 'button';
  const thGrp = (labelText: string, control: HTMLElement): HTMLElement => {
    const w = el('label', 'dtk-th-grp');
    w.appendChild(el('span', 'dtk-th-lbl', labelText));
    w.appendChild(control);
    return w;
  };
  thBar.appendChild(thGrp('grab points', thDirSel));
  thBar.appendChild(thGrp('line value', thValInput));
  thBar.appendChild(thGrp('bridge gaps ≤', thGapInput));
  thBar.appendChild(thScope);
  thBar.appendChild(thWinReset);
  thBar.appendChild(thAdd);
  thBar.appendChild(thDone);
  thBar.style.display = 'none';
  thWrap.appendChild(thBar);

  // ---- lasso bar (live capture readout + done) ------------------------------
  const lassoBar = el('div', 'dtk-th-bar');
  const lassoInfo = el('span', 'dtk-th-scope', 'draw a loop around the anomaly dots on the chart below');
  const lassoDone = el('button', 'dtk-inc-btn', 'Done');
  lassoDone.type = 'button';
  lassoBar.appendChild(lassoInfo);
  lassoBar.appendChild(lassoDone);
  lassoBar.style.display = 'none';
  thWrap.appendChild(lassoBar);
  // The capture tools live in the Label panel of the rail (shown in Label mode).
  labelGroup.appendChild(thWrap);

  // ---- review bar (Review mode): confirm/clear all alerts at once -----------
  const reviewBar = el('div', 'dtk-th-bar dtk-tune-reviewbar');
  reviewBar.appendChild(
    el(
      'span',
      'dtk-th-scope',
      'Click a red alert marker to confirm it valid (green) or mark it a false alarm — cycle un-reviewed → valid → false.',
    ),
  );
  const confirmAllBtn = el('button', 'dtk-apply-btn dtk-th-add', 'Confirm all unreviewed valid');
  confirmAllBtn.type = 'button';
  confirmAllBtn.onclick = (): void => {
    for (const [s, e] of lastFireSpans) if (!reviewFor(s, e)) setReview(s, e, 'valid');
    repaintAlerts();
  };
  const clearReviewBtn = el('button', 'dtk-inc-btn', 'Clear verdicts');
  clearReviewBtn.type = 'button';
  clearReviewBtn.onclick = (): void => {
    reviews.length = 0;
    repaintAlerts();
  };
  reviewBar.appendChild(confirmAllBtn);
  reviewBar.appendChild(clearReviewBtn);
  reviewGroup.appendChild(reviewBar);

  // Drive the chart mode + reveal the matching tools. Defined here (after the tool
  // bars exist) and called by the mode buttons + on first paint.
  const RAIL_TITLES: Record<UiMode, string> = {
    tune: 'Tune · controls',
    review: 'Review · verdicts',
    label: 'Label · incidents',
    autotune: 'Autotune · search',
  };
  function setUiMode(md: UiMode): void {
    // The Autotune panel renders the chart exactly like Tune (band leads): it shows
    // the recomputed band after the engine re-seeds the knobs. So the chart only
    // knows the three layer-modes; 'autotune' maps to 'tune' for the chart.
    chart.setMode(md === 'autotune' ? 'tune' : md);
    (Object.keys(modeBtns) as UiMode[]).forEach((v) =>
      modeBtns[v]?.classList.toggle('on', v === md),
    );
    if (md !== 'label') {
      setThActive(false);
      setLassoActive(false);
    }
    // Swap the rail to the current mode's panel (and rename its header): detector
    // knobs + effective config + Apply in Tune, the verdict actions in Review, the
    // capture tools + incident list + Save in Label, the autotune search in Autotune
    // — never all the controls at once. The Tune-only action footer (effective config
    // + Apply) also rides in Autotune so the searched config can be applied in place.
    tuneGroup.style.display = md === 'tune' ? '' : 'none';
    reviewGroup.style.display = md === 'review' ? '' : 'none';
    labelGroup.style.display = md === 'label' ? '' : 'none';
    autotuneGroup.style.display = md === 'autotune' ? '' : 'none';
    railFoot.style.display = md === 'tune' || md === 'autotune' ? '' : 'none';
    railTitle.textContent = RAIL_TITLES[md];
  }

  let thActive = false;
  let lassoActive = false;
  // True only for the synchronous span of the value input's own oninput, so the UI
  // refresh below can tell a user keystroke apart from a chart-driven value change
  // (a chart click should win and write the input; typing must not be clobbered).
  let thTyping = false;
  const setThActive = (on: boolean): void => {
    thActive = on;
    thToggle.classList.toggle('on', on);
    thBar.style.display = on ? 'flex' : 'none';
    chart.setThresholdMode(on);
    if (on && lassoActive) setLassoActive(false); // mutually exclusive tools
  };
  // Lasso mode: commits incidents on mouseup via onIncidentsChange, so the bar is
  // just a live readout + Done. The chart enforces threshold/lasso exclusivity too.
  const setLassoActive = (on: boolean): void => {
    lassoActive = on;
    lassoToggle.classList.toggle('on', on);
    lassoBar.style.display = on ? 'flex' : 'none';
    chart.setLassoMode(on);
    if (on && thActive) setThActive(false);
  };
  thToggle.onclick = (): void => setThActive(!thActive);
  thDone.onclick = (): void => setThActive(false);
  lassoToggle.onclick = (): void => setLassoActive(!lassoActive);
  lassoDone.onclick = (): void => setLassoActive(false);
  thDirSel.onchange = (): void =>
    chart.setThresholdDirection(thDirSel.value as 'above' | 'below');
  thValInput.oninput = (): void => {
    const s = thValInput.value.trim();
    thTyping = true;
    chart.setThresholdValue(s !== '' && !isNaN(Number(s)) ? Number(s) : null);
    thTyping = false;
  };
  thGapInput.oninput = (): void => chart.setThresholdGap(Number(thGapInput.value) || 0);
  thWinReset.onclick = (): void => chart.clearCaptureWindow();
  thAdd.onclick = (): void => {
    chart.applyThreshold(); // commits spans → incidents (fires onIncidentsChange)
  };
  // Esc backs out of whichever capture tool is active; routed through the setters
  // so the toggle/bar state stays in sync with the chart.
  const onKeydown = (ev: KeyboardEvent): void => {
    if (ev.key !== 'Escape') return;
    if (thActive) setThActive(false);
    else if (lassoActive) setLassoActive(false);
  };
  window.addEventListener('keydown', onKeydown);
  updateLassoUI = (info): void => {
    lassoInfo.textContent = info.active
      ? `${info.anomalies} anomal${info.anomalies === 1 ? 'y' : 'ies'} → ` +
        `${info.incidents} incident${info.incidents === 1 ? '' : 's'} — release to add`
      : 'draw a loop around the anomaly dots on the chart below';
  };
  updateThresholdUI = (info): void => {
    thAdd.textContent = `Add ${info.runs} span${info.runs === 1 ? '' : 's'}`;
    thAdd.disabled = info.runs === 0;
    // Mirror a pinned line value into the input — including a chart click while the
    // input is focused — but never overwrite the digits the user is mid-typing.
    if (info.locked && info.value != null && !thTyping) {
      thValInput.value = String(Math.round(info.value * 1000) / 1000);
    }
    // The reset only makes sense for a COMMITTED window, not a window mid-drag.
    thWinReset.style.display = info.committed ? '' : 'none';
    thScope.textContent = info.window
      ? `scope: ${fmtDur(info.windowMs)} painted`
      : 'scope: current view — drag the chart to limit it';
  };

  // ---- detector worker + debounced recompute --------------------------------
  // runDetector is O(points x window) and re-runs from scratch on every change;
  // running it in a Worker keeps the UI responsive no matter the size. The
  // worker-client module (worker-client.ts) owns the worker lifecycle (spawn /
  // kill-in-flight / debounce); this closure only supplies what changes per
  // recompute (params/share) and reacts to results (repaint the chart, refresh
  // the stat line + metrics).
  // Root-side mirror of the last dispatched params — repaintAlerts() re-renders
  // the chart with them between worker results.
  let lastParams: DetectorParams | null = null;
  const workerClient = createTuneWorkerClient({
    src: __DTK_WORKER_SRC__,
    series,
    getParams: readParams,
    getShare: () => ({ windowPoints: shareWindowPoints(), share: shareValue() }),
    onDispatch: (params): void => {
      lastParams = params;
      // Remember the active detector's live params so switching detectors (and Apply)
      // can write back every slot the user tuned, not just the one on screen.
      if (activeIndex != null) editedParams.set(activeIndex, params);
      spinner.classList.add('on');
      // Report live state to an external driver (landing playground only) so a data
      // regeneration can carry the tuned knobs across the re-mount. No-op in the
      // shipped cockpit (no hooks passed).
      hooks?.onState?.({ params, windowPoints: shareWindowPoints(), share: shareValue() });
    },
    onResult: (res: WorkerResult, params: DetectorParams): void => {
      spinner.classList.remove('on');
      lastScored = res.scored;
      lastFireTs = res.fires.map((i) => series.timestamps[i]);
      lastFireSpans = res.fireSpans;
      // Re-bind each fired alert to its stored review verdict (by streak-span overlap)
      // so a recompute that moves the alerts keeps the greens/slates it earned.
      lastAlerts = buildAlerts();
      chart.render({ series, scored: res.scored, params, alerts: lastAlerts, incidents });
      renderMetrics();
      const scoredCount = res.scored.reduce((acc, p) => acc + (p.scored ? 1 : 0), 0);
      statBar.textContent =
        `${res.flagged} flagged · ${res.fires.length} alert${res.fires.length === 1 ? '' : 's'} · ` +
        // The TRUE context requirement (get_context_size), not the shown-length-
        // clamped eff — so "warm-up 405 pts" reads honestly even when fewer are shown.
        `warm-up ${res.need} pts`;
      updateSeasonWarn(params);
      updateWarmupWarn(scoredCount, params);
      configEcho.textContent = configText(params, consecutive, shareWindowPoints(), shareValue());
    },
    onError: (): void => {
      spinner.classList.remove('on');
      statBar.textContent = 'recompute failed — see the browser console';
    },
  });
  const recompute = workerClient.recompute;

  // ---- trim: re-slice the active series, re-post, recompute -----------------
  const trimSpan = (count: number): string =>
    count > 1 ? fmtDur(fullSeries.timestamps[n - 1] - fullSeries.timestamps[n - count]) : '—';
  const setTrimEcho = (count: number): void => {
    trimEcho.textContent =
      count >= n ? `${n} pts · full (${trimSpan(n)})` : `${count} pts · ${trimSpan(count)}`;
  };
  setTrimEcho(n);
  function setActivePoints(count: number): void {
    series = sliceSeries(count);
    workerClient.postSeries(series);
    updateWindowReach();
    recompute();
  }
  // Live echo while dragging; the (expensive) re-slice + re-post + recompute fires
  // only on release (`change`), not on every mid-drag pause.
  trimInput.oninput = (): void => {
    setTrimEcho(Number(trimInput.value));
  };
  trimInput.onchange = (): void => {
    setActivePoints(Number(trimInput.value));
  };
  // A detector knob changed (as opposed to an alert-layer/view control): mark the
  // active detector dirty so Apply writes it back, then recompute. Programmatic
  // re-seeds (detector switch, autotune winner) call recompute() directly, so they
  // never mark dirty — only genuine user edits do.
  const detectorChanged = (): void => {
    markActiveDirty();
    // Keep the window slider's explore cap in step with the shown-point count
    // (see windowReachFor); cheap, and it only ever moves the max, never the value.
    updateWindowReach();
    recompute();
  };

  // ---- controls -------------------------------------------------------------
  // Multi-detector picker: when the metric configures more than one detector, let
  // the user choose WHICH one to tune here (the cockpit shows one band at a time)
  // and make it plain that the others are preserved on Apply. Hidden for the common
  // single-detector metric, so that UX is unchanged.
  const tunableEntries = detectorEntries.filter((d) => d.tunable);
  const preservedEntries = detectorEntries.filter((d) => !d.tunable);
  if (detectorEntries.length > 1) {
    const pickWrap = el('div', 'dtk-ctl dtk-tune-detpick');
    pickWrap.appendChild(
      ctlLabel(
        'Tuning detector',
        'This metric has several detectors. Pick which one to tune here; every other ' +
          'detector is preserved unchanged when you Apply — so a manual_bounds floor or a ' +
          'min_detectors≥2 quorum keeps working.',
      ),
    );
    if (tunableEntries.length > 1) {
      const seg = el('div', 'dtk-seg dtk-detpick-seg');
      const buttons: HTMLButtonElement[] = [];
      const paint = (): void =>
        buttons.forEach((b) => b.classList.toggle('on', Number(b.dataset.v) === activeIndex));
      tunableEntries.forEach((d) => {
        const b = el('button', 'dtk-seg-btn', `#${d.index + 1} ${d.type}`);
        b.type = 'button';
        b.dataset.v = String(d.index);
        b.title = d.summary;
        b.onclick = (): void => {
          switchDetector(d.index);
          paint();
        };
        buttons.push(b);
        seg.appendChild(b);
      });
      paint();
      pickWrap.appendChild(seg);
    }
    const noteParts: string[] = [];
    if (preservedEntries.length) {
      noteParts.push(
        `Preserved (not tunable here): ${preservedEntries.map((d) => d.summary).join('; ')}.`,
      );
    }
    noteParts.push('Apply rewrites only the detector(s) you tune and keeps the rest verbatim.');
    pickWrap.appendChild(el('div', 'dtk-tune-note', noteParts.join(' ')));
    tuneGroup.appendChild(pickWrap);
  }

  const detectorCtl = segControl(
    'Detector',
    [
      { label: 'MAD', value: 'mad' },
      { label: 'Z-Score', value: 'zscore' },
      { label: 'IQR', value: 'iqr' },
      { label: 'Autoreg', value: 'autoreg' },
      { label: 'Manual', value: 'manual_bounds' },
    ],
    seed.type,
    (v) => {
      // reset threshold + min-samples-per-group to the new type's defaults for a
      // sane starting point (IQR's group floor is 4, so raise the slider min first).
      thresholdCtl_setDefault(THRESHOLD_DEFAULT[v as DetectorType] ?? 3.0);
      if (minSamplesPerGroupCtl) {
        const nt = v as DetectorType;
        minSamplesPerGroupCtl.setMin(mspgFloor(nt));
        minSamplesPerGroupCtl.set(mspgDefault(nt));
      }
      // Reset min_samples to the sane per-type default (30), clamped to the window
      // — so switching to autoreg drops a windowed detector's (possibly huge)
      // min_samples instead of carrying it over and blanking the band.
      minSamplesCtl.setMax(Math.max(2, windowCtl.get()));
      minSamplesCtl.set(Math.min(30, Math.max(2, windowCtl.get())));
      markActiveDirty();
      refreshVisibility();
      updateWindowReach();
      recompute();
    },
    'The statistic for the band: MAD (robust median, default), Z-Score (mean/std) or IQR ' +
      '(quartiles) — all windowed — Autoreg (predicts each point from its previous values and ' +
      'flags dynamics breaks) or Manual (fixed lower/upper thresholds, no window/history).',
  );
  tuneGroup.appendChild(detectorCtl.row);

  // manual_bounds: lower/upper threshold sliders (shown only for that detector).
  // The value domain is the real series range padded a little; both bounds are
  // always written on Apply (the Python detector requires lower < upper).
  const lowerBoundCtl = rangeControl(
    'Lower bound',
    {
      min: boundMin,
      max: boundMax,
      step: boundStep,
      value: seedLower,
      fmt: (v) => fmtNum(v),
      hint: 'Manual bounds: values below this read as anomalous. Drag in from the data range to ' +
        'see how many points fall outside (and how many alerts that yields).',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(lowerBoundCtl.row);

  const upperBoundCtl = rangeControl(
    'Upper bound',
    {
      min: boundMin,
      max: boundMax,
      step: boundStep,
      value: seedUpper,
      fmt: (v) => fmtNum(v),
      hint: 'Manual bounds: values above this read as anomalous.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(upperBoundCtl.row);

  const thresholdCtl = rangeControl(
    'Threshold (σ-equivalent)',
    {
      min: 0.5,
      max: 10,
      step: 0.1,
      value: seed.threshold,
      fmt: (v) => v.toFixed(1),
      hint: 'Band half-width in σ-equivalents. Lower = tighter band = more flags; higher = ' +
        'wider band = fewer flags.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(thresholdCtl.row);
  const thresholdInput = thresholdCtl.row.querySelector<HTMLInputElement>('input');
  const thresholdOut = thresholdCtl.row.querySelector<HTMLElement>('.dtk-ctl-val');
  const thresholdCtl_setDefault = (v: number): void => {
    if (thresholdInput) thresholdInput.value = String(v);
    if (thresholdOut) thresholdOut.textContent = v.toFixed(1);
  };

  // Slider reach: enough to explore, capped so there's always a healthy scored
  // region. The band is now drawn wherever the detector scores (the cockpit no
  // longer hides a 2·window+lags warm-up), so autoreg no longer needs its old
  // tighter, stabilization-aware cap — every type shares the simple half-of-shown
  // reach. NEVER below the metric's actual window_size, so the seeded value is
  // always representable and Apply can't silently shrink the metric's window.
  // step=1 keeps the exact configured value addressable (a step-5 grid would snap
  // e.g. 168 → 170 and write the wrong window back).
  const windowReachFor = (shown: number): number =>
    Math.max(50, Math.min(2000, Math.floor(shown / 2)));
  const windowMax = Math.max(windowReachFor(n), seed.windowSize);
  const windowCtl = rangeControl(
    'Window size (points)',
    {
      min: Math.max(1, Math.min(10, seed.windowSize)),
      max: windowMax,
      step: 1,
      value: seed.windowSize,
      // Echo the wall-clock span the window covers on the metric grid (like the
      // "Points shown" trim), so "how much history is this" reads at a glance.
      fmt: (v) => `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}`,
      hint: 'How many trailing points form the baseline window for each scored point. ' +
        'Larger = steadier baseline (more history); smaller = adapts faster to shifts.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(windowCtl.row);

  // autoreg: AR order (lags) — shown only for that detector.
  const lagsCtl = rangeControl(
    'Lags (AR order)',
    {
      min: 1,
      max: 24,
      step: 1,
      value: Math.max(1, Math.round(seed.lags ?? 5)),
      fmt: (v) => String(v),
      hint: 'Autoreg: how many immediately-preceding values predict the current one. More lags ' +
        'capture longer short-range patterns but need more history per fit.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(lagsCtl.row);

  // Min samples — the fewest valid points the window must hold before a point is
  // scored (for autoreg, gap-free fit rows). Exposed as a knob because a config
  // — often an autotune winner sized for a large window — can carry a min_samples
  // so high that a smaller window or trimmed view can't collect it, so the band
  // never appears, and previously there was no way to lower it in the cockpit.
  // Capped at the window size (min_samples can never exceed the window — the max
  // tracks the Window slider), floored at 2. Shown for every detector except
  // manual_bounds (which has no window).
  const minSamplesCtl = rangeControl(
    'Min samples (fit points)',
    {
      min: 2,
      max: Math.max(2, seed.windowSize),
      step: 1,
      value: Math.min(Math.max(2, seed.minSamples), Math.max(2, seed.windowSize)),
      fmt: (v) => String(Math.round(v)),
      hint: 'Fewest valid points the window must hold before a point is scored — for autoreg, ' +
        'gap-free fit rows. Lower it if the band will not appear on a smaller window: an ' +
        'autotuned config sized for a large window can set this too high to score on a shorter ' +
        'view. Capped at the window size.',
    },
    detectorChanged,
  );
  tuneGroup.appendChild(minSamplesCtl.row);

  const weightsCtl = segControl(
    'Recency weighting',
    [
      { label: 'none', value: 'none' },
      { label: 'exponential', value: 'exponential' },
      { label: 'linear', value: 'linear' },
    ],
    seed.windowWeights,
    () => {
      markActiveDirty();
      refreshVisibility();
      recompute();
    },
    'Weight recent points in the window more heavily: none (flat), exponential (half-life ' +
      'decay) or linear. Helps the baseline track a drifting level.',
  );
  tuneGroup.appendChild(weightsCtl.row);

  const halfLifeCtl = rangeControl(
    'Half-life (points)',
    {
      min: 1,
      max: windowMax,
      step: 1,
      value: seed.halfLife ?? Math.max(5, Math.round(seed.windowSize / 20)),
      // Same grid-span echo as the window: half-life in points is abstract, the
      // equivalent duration ("767 · 32d") makes the decay horizon concrete.
      fmt: (v) => `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}`,
      hint: 'Exponential weighting only: the age (in points) at which a point counts half as ' +
        'much as the newest. Smaller = faster decay = fresher baseline.',
    },
    detectorChanged,
  );
  const halfLifeRow = halfLifeCtl.row;
  halfLifeRow.style.display = seed.windowWeights === 'exponential' ? '' : 'none';
  tuneGroup.appendChild(halfLifeRow);

  // Re-derive the window slider's reach when the shown-point count changes (a
  // trim). Only ever adjusts EXPLORE headroom: never below the seed or the
  // current value, so neither a trim nor a type switch silently rewrites the
  // knob. The half-life max additionally guards its own seed/live value — a
  // configured half_life can exceed the window reach (e.g. "30d" on a 10min
  // grid) and must never be silently clamped down by a re-seed.
  const updateWindowReach = (): void => {
    const mx = Math.max(windowReachFor(series.timestamps.length), seed.windowSize, windowCtl.get());
    windowCtl.setMax(mx);
    halfLifeCtl.setMax(Math.max(mx, seed.halfLife ?? 0, halfLifeCtl.get()));
    // min_samples can never exceed the window (Python + config-emitter clamp it);
    // keep its cap on the live window value, so shrinking the window drags an
    // over-large min_samples down with it instead of wedging the band to blank.
    minSamplesCtl.setMax(Math.max(2, windowCtl.get()));
  };

  const detrendCtl = segControl(
    'Detrend',
    [
      { label: 'none', value: 'none' },
      { label: 'linear', value: 'linear' },
    ],
    seed.detrend,
    detectorChanged,
    'Remove a robust linear trend from each window before computing the band, so a steadily ' +
      'rising/falling metric is not flagged for the trend itself.',
  );
  tuneGroup.appendChild(detrendCtl.row);

  const stabilizationCtl = segControl(
    'Stabilization',
    [
      { label: 'none', value: 'none' },
      { label: 'clamp', value: 'clamp' },
    ],
    seed.stabilization ?? 'none',
    detectorChanged,
    'Anomaly-robust baseline: flagged points enter later windows clamped to the bound they ' +
      'violated, so a long incident cannot inflate the band and mask itself mid-incident.',
  );
  tuneGroup.appendChild(stabilizationCtl.row);

  const smoothingCtl = segControl(
    'Smoothing',
    [
      { label: 'none', value: 'none' },
      { label: 'EMA', value: 'ema' },
      { label: 'SMA', value: 'sma' },
    ],
    seed.smoothing,
    detectorChanged,
    'Smooth the series before detection (EMA or SMA) so single-point jitter does not flag. ' +
      'The detector judges the smoothed line; the raw values show as a faint ghost.',
  );
  tuneGroup.appendChild(smoothingCtl.row);

  // seasonality (only when the metric has seasonality columns).
  // Each column is assigned a group: Off, or G1/G2/G3… Columns sharing a group
  // are conjoined into ONE seasonal key (e.g. dow×hour); separate groups apply
  // independent corrections — the full string[][] grouping the detector supports.
  let seasonalityRow: HTMLElement | null = null;
  // Re-seed the per-column group assignment (e.g. from an autotune result). No-op
  // when the metric has no seasonality columns; overridden below when it does.
  let setSeasonalityGroups: (groups: string[][]) => void = () => {};
  if (payload.seasonality_columns.length) {
    const cols = payload.seasonality_columns;
    const row = el('div', 'dtk-ctl');
    seasonalityRow = row;
    row.appendChild(
      ctlLabel(
        'Seasonality groups',
        'Condition the band on seasonal keys. Pick a group per column: columns in the SAME ' +
          'group are combined into one key (e.g. dow×hour); separate groups each apply their ' +
          'own correction. Off = ignore that column.',
      ),
    );
    // Offer Off + as many groups as there are columns (each could stand alone).
    // Sized to the column count — never fewer — so any grouping a re-seed
    // (e.g. an autotune winner) hands back always has a matching button to show on.
    const groupCount = cols.length;
    const opts: SegSpec[] = [{ label: '—', value: '0' }];
    for (let gi = 1; gi <= groupCount; gi++) opts.push({ label: `G${gi}`, value: String(gi) });
    // One repaint per column row, collected so a re-seed can refresh them all.
    const seasonPaints: Array<() => void> = [];
    cols.forEach((col) => {
      const crow = el('div', 'dtk-season-row');
      crow.appendChild(el('span', 'dtk-season-col', col));
      const seg = el('div', 'dtk-seg dtk-season-seg');
      const buttons: HTMLButtonElement[] = [];
      const cur = (): number => colGroup.get(col) ?? 0;
      const paint = (): void =>
        buttons.forEach((b) => b.classList.toggle('on', Number(b.dataset.v) === cur()));
      seasonPaints.push(paint);
      opts.forEach((opt) => {
        const b = el('button', 'dtk-seg-btn', opt.label);
        b.type = 'button';
        b.dataset.v = opt.value;
        b.title = opt.value === '0' ? `ignore ${col}` : `put ${col} in group ${opt.value}`;
        b.onclick = (): void => {
          colGroup.set(col, Number(opt.value));
          paint();
          detectorChanged();
        };
        buttons.push(b);
        seg.appendChild(b);
      });
      paint();
      crow.appendChild(seg);
      row.appendChild(crow);
    });
    tuneGroup.appendChild(row);
    setSeasonalityGroups = (groups: string[][]): void => {
      colGroup.clear();
      groups.forEach((grp, gi) => grp.forEach((c) => colGroup.set(c, gi + 1)));
      seasonPaints.forEach((p) => p());
    };

    // Min samples per seasonal group — how many same-key points the window must
    // hold before a seasonal group earns its OWN band (below it, the group falls
    // back to the global band). Sits right under the grouping it governs, and
    // ONLY exists for a seasonal metric (the parameter is inert without
    // seasonality). Exposing it here is the point of the whole knob: shrinking
    // Points shown / Window size can silently push a group under this threshold —
    // making the band look worse for a reason that isn't the window itself — so
    // lowering this is the recourse the under-fill warning now names, instead of
    // the user having no lever but "widen the window". Hidden for autoreg/manual
    // via windowedOnlyRows.
    minSamplesPerGroupCtl = rangeControl(
      'Min samples per group',
      {
        min: mspgFloor(seed.type),
        max: Math.max(50, seed.minSamplesPerGroup),
        step: 1,
        value: Math.max(mspgFloor(seed.type), seed.minSamplesPerGroup),
        fmt: (v) => String(v),
        hint:
          'Per-seasonal-key minimum: a seasonality group only gets its own band once the ' +
          'window holds this many points sharing the current key — below it the group falls ' +
          'back to the global band (the seasonality has no effect). Lower it to keep seasonality ' +
          'active on a smaller window; raise it for steadier per-key statistics.',
      },
      detectorChanged,
    );
    tuneGroup.appendChild(minSamplesPerGroupCtl.row);
  }

  // Direction filter (alert-layer / view): which anomalies show + count as alerts.
  const directionCtl = segControl(
    'Direction',
    [
      { label: 'both', value: 'any' },
      { label: 'up', value: 'up' },
      { label: 'down', value: 'down' },
    ],
    payload.direction ?? 'any',
    recompute,
    'Which anomalies to show and count toward alerts: both directions, only spikes ABOVE the ' +
      'band (up) or only drops BELOW it (down). A preview filter mirroring the alert direction ' +
      'policy — it never changes the band itself.',
  );
  alertCommon.appendChild(directionCtl.row);

  const consecutiveCtl = rangeControl(
    'Alert: consecutive anomalies',
    {
      min: 1,
      max: 10,
      step: 1,
      value: consecutive,
      fmt: (v) => String(v),
      hint: 'How many anomalies in a row are required before an alert fires. Higher = fewer, ' +
        'more-confident alerts (the ▼ markers on the chart).',
    },
    (v) => {
      consecutive = v;
      recompute();
    },
  );
  alertCommon.appendChild(consecutiveCtl.row);

  // Fraction alert rule (issue #101): an anomaly-window (in grid points; 'off'
  // below 2) + a min share of flagged points within it. OR-ed with the
  // consecutive rule, exactly like the pipeline — good for diffuse incidents
  // where anomalies are frequent but never strictly consecutive.
  const anomalyWindowCtl = rangeControl(
    'Alert: anomaly window (points)',
    {
      min: 0,
      max: Math.max(96, anomalyWindowPoints),
      step: 1,
      value: anomalyWindowPoints,
      fmt: (v) =>
        v >= 2 ? `${v} · ${fmtDur(v * payload.interval_seconds * 1000)}` : 'off',
      hint: 'Fraction rule (OR-ed with the consecutive rule): also fire when at least the share ' +
        'below of the trailing window is anomalous AND the latest point is anomalous. Set to ' +
        'off (< 2) for the classic consecutive-only alert.',
    },
    (v) => {
      anomalyWindowPoints = v;
      refreshShareVisibility();
      recompute();
    },
  );
  alertCommon.appendChild(anomalyWindowCtl.row);

  const minAnomalyShareCtl = rangeControl(
    'Alert: min share in window',
    {
      min: 0.05,
      max: 1,
      step: 0.05,
      value: minAnomalyShare,
      fmt: (v) => `${Math.round(v * 100)}%`,
      hint: 'Fraction rule: the share of the anomaly window that must be flagged for the alert ' +
        'to fire. Missing points count against the share (an outage never makes it easier).',
    },
    (v) => {
      minAnomalyShare = v;
      recompute();
    },
  );
  alertCommon.appendChild(minAnomalyShareCtl.row);
  const refreshShareVisibility = (): void => {
    minAnomalyShareCtl.row.style.display = anomalyWindowPoints >= 2 ? '' : 'none';
  };
  refreshShareVisibility();

  // y = 0 reference line.
  const zeroRow = el('div', 'dtk-ctl');
  const zeroLab = el('label', 'dtk-check');
  const zeroBox = el('input');
  zeroBox.type = 'checkbox';
  zeroBox.onchange = (): void => {
    chart.setZeroLine(zeroBox.checked);
  };
  zeroLab.title =
    'Draw a horizontal line at y = 0 and include zero in the scale — for real-valued metrics ' +
    'best read relative to zero.';
  zeroLab.appendChild(zeroBox);
  zeroLab.appendChild(document.createTextNode(' Show y = 0 line'));
  zeroRow.appendChild(zeroLab);
  alertCommon.appendChild(zeroRow);

  // Marked-incidents list (label edit + focus + delete). Shares the SAME `incidents`
  // array the chart edits in Label mode.
  const incidentsWrap = el('div', 'dtk-ctl dtk-incidents');
  incidentsWrap.appendChild(
    ctlLabel(
      'Marked incidents',
      'The real incidents you marked (in Label mode). Edit a label, focus to zoom the chart to ' +
        'it, or remove it. Save the set below to incidents/<metric>/ — the same store dtk autotune reads.',
    ),
  );
  const incidentsList = el('div', 'dtk-inc-list');
  incidentsWrap.appendChild(incidentsList);
  labelGroup.appendChild(incidentsWrap);

  function focusIncident(iv: Incident): void {
    const pad = Math.max((iv.end - iv.start) * 0.5, payload.interval_seconds * 1000 * 5);
    chart.setViewWindow(iv.start - pad, iv.end + pad);
  }
  function deleteIncident(iv: Incident): void {
    const k = incidents.indexOf(iv);
    if (k >= 0) incidents.splice(k, 1);
    // Retract a confirmed-valid verdict this incident overlapped, so it doesn't
    // resurface as a "confirmed alert" row — the chart ✕ and this list ✕ stay in sync.
    const retracted = retractConfirmationFor(iv);
    chart.setIncidents(incidents);
    if (retracted) repaintAlerts(); // recolours markers + recomputes metrics + refreshes list
    else {
      refreshIncidentList();
      renderMetrics();
    }
  }
  // Un-confirm a validated-alert incident: clear its verdict (the green marker
  // reverts to an un-reviewed alert), then repaint everything — this is the inverse
  // of confirming the alert in Review mode, exposed here so the list is the single
  // place to add/remove every kind of incident.
  function unconfirmAlert(iv: Incident): void {
    setReview(iv.start, iv.end, null);
    chart.setIncidents(incidents);
    repaintAlerts(); // re-colours markers + recomputes metrics + refreshes this list
  }
  function refreshIncidentList(): void {
    incidentsList.innerHTML = '';
    // One list, two provenances: hand-marked incidents (editable label/delete) and
    // confirmed-valid alerts (a read-only "✓ alert" badge; ✕ un-confirms). Deduped:
    // a validated span already covered by a hand-marked incident shows once, as the
    // editable manual row. Sorted together so the list reads chronologically.
    type Row = { iv: Incident; kind: 'manual' | 'alert' };
    const rows: Row[] = [
      ...incidents.map((iv) => ({ iv, kind: 'manual' as const })),
      ...validatedExtra().map((iv) => ({ iv, kind: 'alert' as const })),
    ].sort((a, b) => a.iv.start - b.iv.start);
    if (!rows.length) {
      incidentsList.appendChild(
        el('div', 'dtk-inc-empty', 'None yet — switch to Label mode and drag across the chart, or confirm alerts in Review mode.'),
      );
      return;
    }
    for (const { iv, kind } of rows) {
      const row = el('div', 'dtk-inc-row' + (kind === 'alert' ? ' dtk-inc-fromalert' : ''));
      row.appendChild(el('span', 'dtk-inc-span', `${fmtTs(iv.start)} → ${fmtTs(iv.end)}`));
      row.appendChild(el('span', 'dtk-inc-dur', fmtDur(Math.max(0, iv.end - iv.start))));
      if (kind === 'alert') {
        // Confirmed-from-alert: a static badge (the verdict, not a free label) +
        // an ✕ that clears the verdict instead of editing a hand-marked span.
        const badge = el('span', 'dtk-inc-badge', '✓ confirmed alert');
        badge.title = 'A fired alert you confirmed valid (in Review mode). It counts as a real ' +
          'incident — remove it here to un-confirm the alert.';
        row.appendChild(badge);
      } else {
        const lbl = el('input', 'dtk-inc-label');
        lbl.type = 'text';
        lbl.value = iv.label || '';
        lbl.placeholder = 'label (optional)';
        lbl.oninput = (): void => {
          iv.label = lbl.value;
        };
        row.appendChild(lbl);
      }
      const focus = el('button', 'dtk-inc-btn', 'focus');
      focus.type = 'button';
      focus.onclick = (): void => focusIncident(iv);
      row.appendChild(focus);
      const del = el('button', 'dtk-inc-btn dtk-inc-del', '✕');
      del.type = 'button';
      del.title = kind === 'alert' ? 'un-confirm this alert' : 'remove this incident';
      del.onclick = (): void => (kind === 'alert' ? unconfirmAlert(iv) : deleteIncident(iv));
      row.appendChild(del);
      incidentsList.appendChild(row);
    }
  }

  // Show only the controls relevant to the selected detector — a 3-way split:
  // band rows (threshold/window/stabilization) for every history-based detector
  // (windowed AND autoreg), windowed-only rows (weights/detrend/smoothing/
  // seasonality) hidden for autoreg (v1 has none — the detector rejects
  // seasonality), lags for autoreg only, bounds for manual_bounds only.
  // Direction + consecutive + the anomaly-window pair (alert-layer) always show.
  const bandRows = [thresholdCtl.row, windowCtl.row, minSamplesCtl.row, stabilizationCtl.row];
  const windowedOnlyRows = [weightsCtl.row, detrendCtl.row, smoothingCtl.row];
  if (seasonalityRow) windowedOnlyRows.push(seasonalityRow);
  // The min-samples-per-group knob only exists for a seasonal metric; when it
  // does, it hides alongside the other windowed-only knobs for autoreg/manual.
  if (minSamplesPerGroupCtl) windowedOnlyRows.push(minSamplesPerGroupCtl.row);
  function refreshVisibility(): void {
    const t = detectorCtl.get() as DetectorType;
    const manual = t === 'manual_bounds';
    const autoreg = t === 'autoreg';
    for (const row of bandRows) row.style.display = manual ? 'none' : '';
    for (const row of windowedOnlyRows) row.style.display = manual || autoreg ? 'none' : '';
    lagsCtl.row.style.display = autoreg ? '' : 'none';
    lowerBoundCtl.row.style.display = manual ? '' : 'none';
    upperBoundCtl.row.style.display = manual ? '' : 'none';
    // half-life only when windowed AND exponential weighting.
    halfLifeRow.style.display =
      !manual && !autoreg && weightsCtl.get() === 'exponential' ? '' : 'none';
  }
  refreshVisibility();

  // Set every detector control from a camelCase seed (a metric detector, a
  // previously-edited detector, or an autotune winner) WITHOUT marking anything
  // dirty — .set() never fires onChange, and the caller drives one recompute after.
  // Updates the closed-over `seed` so readParams()'s passthrough knobs
  // (minSamples/inputType/smoothing*/minSamplesPerGroup) follow the active detector.
  function reseedControls(s: DetectorSeed): void {
    seed = s;
    detectorCtl.set(s.type);
    thresholdCtl.set(s.threshold);
    // A re-seed may carry a window/half-life beyond the slider's explore reach; raise
    // the max first so .set() can't silently clamp (which would shrink what Apply writes).
    updateWindowReach();
    windowCtl.set(s.windowSize);
    // min_samples cap tracks the seed's window (set AFTER windowCtl.set, since
    // updateWindowReach ran against the pre-set window); clamp the value into
    // [2, window] so a seed's min_samples never exceeds its own window.
    minSamplesCtl.setMax(Math.max(2, s.windowSize));
    minSamplesCtl.set(Math.min(Math.max(2, s.minSamples), Math.max(2, s.windowSize)));
    weightsCtl.set(s.windowWeights);
    if (s.windowWeights === 'exponential' && s.halfLife != null) halfLifeCtl.set(s.halfLife);
    detrendCtl.set(s.detrend);
    stabilizationCtl.set(s.stabilization ?? 'none');
    smoothingCtl.set(s.smoothing);
    setSeasonalityGroups(s.seasonalityComponents || []);
    if (minSamplesPerGroupCtl) {
      // Raise the floor (IQR floor 4) AND the reach before .set(), so a detector
      // configured above the slider's original max (fixed at creation from the
      // FIRST-opened detector's seed) isn't silently clamped down — which would
      // corrupt what Apply writes. Mirrors the window/half-life setMax-before-set
      // just above; the get() term keeps the current explore headroom.
      minSamplesPerGroupCtl.setMin(mspgFloor(s.type));
      minSamplesPerGroupCtl.setMax(Math.max(50, s.minSamplesPerGroup, minSamplesPerGroupCtl.get()));
      minSamplesPerGroupCtl.set(Math.max(mspgFloor(s.type), s.minSamplesPerGroup));
    }
    if (s.lowerBound != null) lowerBoundCtl.set(s.lowerBound);
    if (s.upperBound != null) upperBoundCtl.set(s.upperBound);
    if (s.lags != null || s.type === 'autoreg') {
      lagsCtl.set(Math.max(1, Math.round(s.lags ?? 5)));
    }
    refreshVisibility();
  }

  // Switch which of a multi-detector metric's detectors the cockpit is tuning.
  // FLUSH the outgoing detector's live control state into editedParams FIRST — a
  // just-released slider only *schedules* a debounced recompute, and reseeding the
  // controls below (plus recompute()'s own clearTimeout) would cancel that pending
  // capture, silently losing an edit made <130ms before the switch. Then load the
  // target (its in-session edits if any, else its original seed) and recompute.
  function switchDetector(idx: number): void {
    if (idx === activeIndex) return;
    const entry = detectorEntries.find((d) => d.index === idx);
    if (!entry || !entry.tunable || !entry.seed) return;
    if (activeIndex != null) editedParams.set(activeIndex, readParams());
    activeIndex = idx;
    reseedControls(editedParams.get(idx) ?? entry.seed);
    recompute();
  }

  // ---- stat bar + effective config + apply ----------------------------------
  const statBar = el('div', 'dtk-tune-stat');
  stageFoot.appendChild(statBar);

  // The effective-config readout is a vertical hog, so it's **collapsed by default**
  // (a one-line clickable header) to give the scrolling knob column more room; click
  // the header to expand it. configEcho stays updated even while hidden, so it shows
  // the current config the moment it's opened.
  const cfgWrap = el('div', 'dtk-tune-cfg');
  const cfgToggle = el('button', 'dtk-tune-cfg-k');
  cfgToggle.type = 'button';
  cfgToggle.title = 'Show or hide the exact config that will be written on Apply.';
  const configEcho = el('code', 'dtk-tune-cfg-v');
  let cfgOpen = false;
  const setCfgOpen = (open: boolean): void => {
    cfgOpen = open;
    configEcho.style.display = open ? '' : 'none';
    cfgToggle.textContent = `${open ? '▾' : '▸'} // effective config`;
  };
  cfgToggle.onclick = (): void => setCfgOpen(!cfgOpen);
  cfgWrap.appendChild(cfgToggle);
  cfgWrap.appendChild(configEcho);
  setCfgOpen(false);
  railFoot.appendChild(cfgWrap);

  if (payload.save_url) {
    const applyWrap = el('div', 'dtk-tune-apply');
    const btn = el('button', 'dtk-apply-btn', 'Apply to metric');
    btn.type = 'button';
    btn.title =
      'Write this detector config back into the metric YAML (the previous version is archived ' +
      'under metrics/.history/). Trimming the sample does not change what is written.';
    const msg = el('span', 'dtk-apply-msg');
    btn.onclick = (): void => {
      const activeParams = readParams();
      // Capture the on-screen detector's live params so it's written with its current
      // state (also covers the initial detector when it IS the active one).
      if (activeIndex != null) editedParams.set(activeIndex, activeParams);
      // Write back the detector the cockpit opened on (always) PLUS any slot the user
      // actually EDITED (dirty) — never a slot merely switched to and left untouched.
      // The server preserves every other detector verbatim, so a manual_bounds floor /
      // prophet alongside the tuned detector survives (the fix for the silent drop
      // that killed min_detectors≥2), and a lower-only floor you only glanced at in
      // the picker keeps its single bound.
      const out: Array<{ index: number | null; type: string; params: Record<string, unknown> }> =
        [];
      if (initialIndex != null) {
        for (const i of new Set<number>([initialIndex, ...dirty])) {
          const p = editedParams.get(i);
          if (p) out.push({ index: i, type: p.type, params: applyParams(p) });
        }
      } else {
        // No existing tunable slot (e.g. a prophet-only metric): append the fresh one.
        out.push({ index: null, type: activeParams.type, params: applyParams(activeParams) });
      }
      btn.disabled = true;
      msg.className = 'dtk-apply-msg info';
      msg.textContent = 'Applying…';
      fetch(payload.save_url as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          detectors: out,
          consecutive_anomalies: consecutive,
          // Fraction rule: exact-seconds duration (lossless points round-trip)
          // + share, or nulls to remove the pair from the alerting block.
          anomaly_window: shareWindowPoints()
            ? `${(shareWindowPoints() as number) * payload.interval_seconds}s`
            : null,
          min_anomaly_share: shareValue(),
        }),
      })
        .then((r) =>
          r.ok
            ? r.json()
            : r.text().then((t) => {
                throw new Error(t || `HTTP ${r.status}`);
              }),
        )
        .then((res: { saved?: string; updated?: string[]; preserved?: string[] }) => {
          msg.className = 'dtk-apply-msg ok';
          const kept =
            res.preserved && res.preserved.length ? ` Kept: ${res.preserved.join(', ')}.` : '';
          msg.textContent = `Applied → ${res.saved ?? 'metric'} (previous archived).${kept} You can close this tab.`;
        })
        .catch((e: Error) => {
          btn.disabled = false;
          msg.className = 'dtk-apply-msg err';
          msg.textContent = `Apply failed: ${e.message}`;
        });
    };
    applyWrap.appendChild(btn);
    applyWrap.appendChild(msg);
    railFoot.appendChild(applyWrap);
  } else {
    railFoot.appendChild(
      el(
        'div',
        'dtk-tune-note',
        'Static preview — sliders recompute live, but there is no write-back. ' +
          'Run `dtk tune` (without --no-serve) to apply a config.',
      ),
    );
  }

  // ---- save labels (incidents) ----------------------------------------------
  // Build the canonical labels YAML and either POST it to the localhost server
  // (writes incidents/<metric>/<stamp>.yml — the store dtk autotune reads) or, for
  // a static preview, download it for the user to drop in themselves.
  const yamlStr = (s: string): string => '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const fmtUtc = (ms: number): string => new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
  const buildLabelsYaml = (): string => {
    const lines = [`metric: ${payload.metric}`, 'timezone: UTC'];
    // Hand-marked incidents PLUS a derived incident for each confirmed (valid) alert
    // not already covered by one (groundTruth() = incidents ∪ overlap-deduped
    // validatedExtra), so confirming alerts feeds the next supervised `dtk autotune`
    // too. The seen-set below guards exact-span repeats.
    const seen = new Set<string>();
    const sorted = groundTruth()
      .sort((a, b) => a.start - b.start)
      .filter((iv) => {
        const k = `${Math.round(iv.start)}:${Math.round(iv.end)}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
    if (!sorted.length) {
      lines.push('incidents: []');
    } else {
      lines.push('incidents:');
      for (const iv of sorted) {
        const lbl = iv.label ? `, label: ${yamlStr(iv.label)}` : '';
        lines.push(`  - {start: "${fmtUtc(iv.start)}", end: "${fmtUtc(iv.end)}"${lbl}}`);
      }
    }
    // Persist the painted threshold-capture window so the regime scope is auditable
    // and restored on reopen. Pure metadata — autotune ignores it.
    const cap = chart.getCaptureWindow();
    if (cap) {
      lines.push('capture_windows:');
      lines.push(`  - {start: "${fmtUtc(cap.start)}", end: "${fmtUtc(cap.end)}"}`);
    }
    // Per-alert verdicts as metadata so the green/slate markers re-seed on reopen
    // (re-bound by streak-span overlap). Autotune ignores this block.
    if (reviews.length) {
      lines.push('alert_reviews:');
      for (const r of [...reviews].sort((a, b) => a.start - b.start)) {
        lines.push(`  - {start: "${fmtUtc(r.start)}", end: "${fmtUtc(r.end)}", verdict: ${r.verdict}}`);
      }
    }
    return lines.join('\n') + '\n';
  };

  const labelsWrap = el('div', 'dtk-tune-apply');
  const setNameInput = el('input', 'dtk-setname');
  setNameInput.type = 'text';
  setNameInput.placeholder = 'name this set (optional)';
  const saveLabelsBtn = el(
    'button',
    'dtk-apply-btn dtk-labels-btn',
    payload.labels_save_url ? 'Save incidents' : 'Download incidents',
  );
  saveLabelsBtn.type = 'button';
  saveLabelsBtn.title =
    'Write the marked incidents to incidents/<metric>/ (versioned) so they also feed the next ' +
    '`dtk autotune`. Saving labels does not end tuning — keep adjusting and apply the detector when ready.';
  const labelsMsg = el('span', 'dtk-apply-msg');
  saveLabelsBtn.onclick = (): void => {
    const yaml = buildLabelsYaml();
    if (!payload.labels_save_url) {
      const blob = new Blob([yaml], { type: 'text/yaml' });
      const a = el('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${payload.metric}.yml`;
      a.click();
      URL.revokeObjectURL(a.href);
      labelsMsg.className = 'dtk-apply-msg ok';
      labelsMsg.textContent = `Downloaded — drop it into incidents/${payload.metric}/`;
      return;
    }
    labelsMsg.className = 'dtk-apply-msg info';
    labelsMsg.textContent = 'Saving…';
    fetch(payload.labels_save_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: setNameInput.value, yaml }),
    })
      .then((r) =>
        r.ok
          ? r.json()
          : r.text().then((t) => {
              throw new Error(t || `HTTP ${r.status}`);
            }),
      )
      .then((res: { saved?: string }) => {
        labelsMsg.className = 'dtk-apply-msg ok';
        labelsMsg.textContent = `Saved → ${res.saved ?? 'incidents'} (keep tuning, or Apply the detector)`;
      })
      .catch((e: Error) => {
        labelsMsg.className = 'dtk-apply-msg err';
        labelsMsg.textContent = `Save failed: ${e.message}`;
      });
  };
  labelsWrap.appendChild(setNameInput);
  labelsWrap.appendChild(saveLabelsBtn);
  labelsWrap.appendChild(labelsMsg);
  labelGroup.appendChild(labelsWrap);

  // ---- autotune panel (Autotune mode) ---------------------------------------
  // Server-side autotune: POST the current ground truth (the same labels YAML as
  // Save incidents) plus the window currently shown (the 'Points shown' trim) to
  // the engine, which searches over exactly that window — the same series the
  // cockpit displays and scores — and returns the winning detector. We re-seed
  // every knob from it, recompute the
  // live band, and render the decision log — then the user reviews and Applies (in
  // Tune/Autotune mode). Re-seeding mirrors the initial render() seeding exactly,
  // via the same camelCase shape the server builds with seed_detector_params.
  function applyAutotuneResult(res: AutotuneResult): void {
    // Re-seed the ACTIVE detector's knobs from the winner (shared with the picker's
    // detector-switch). Autotune tunes the detector currently on screen; the metric's
    // other detectors are untouched and stay preserved on Apply. Marks the active
    // detector dirty so the searched config is written back.
    reseedControls(res.detector);
    markActiveDirty();
    if (res.consecutive_anomalies != null) {
      consecutive = res.consecutive_anomalies;
      consecutiveCtl.set(consecutive);
    }
    // Fraction rule from the sweep: re-seed the pair, or switch it off when the
    // legacy consecutive-only rule won (null ⇒ off).
    if (res.anomaly_window_points != null && res.min_anomaly_share != null) {
      anomalyWindowPoints = res.anomaly_window_points;
      minAnomalyShare = res.min_anomaly_share;
      anomalyWindowCtl.setMax(Math.max(96, anomalyWindowPoints));
      anomalyWindowCtl.set(anomalyWindowPoints);
      minAnomalyShareCtl.set(minAnomalyShare);
    } else {
      anomalyWindowPoints = 0;
      anomalyWindowCtl.set(0);
    }
    refreshShareVisibility();
    recompute();
  }

  autotuneGroup.appendChild(
    el(
      'div',
      'dtk-tune-note',
      'Run the full autotune engine server-side over the window shown (the ‘Points shown’ ' +
        'trim — the same series you see and score here), using the incidents you’ve marked ' +
        '(and confirmed alerts) as ground truth. It re-seeds the knobs with the winning ' +
        'detector — review the band, then Apply (here or in Tune). Nothing is written until ' +
        'you Apply; the next `dtk run` is the source of truth.',
    ),
  );
  if (payload.autotune_url) {
    const atWrap = el('div', 'dtk-tune-apply');
    const atBtn = el('button', 'dtk-apply-btn', 'Run autotune');
    atBtn.type = 'button';
    atBtn.title =
      'Search for the best detector over the window shown (the ‘Points shown’ trim). Uses ' +
      'your marked incidents as ground truth when present (supervised), else an unsupervised ' +
      'objective. Can take a few seconds on a long window.';
    const atMsg = el('span', 'dtk-apply-msg');
    atWrap.appendChild(atBtn);
    atWrap.appendChild(atMsg);
    autotuneGroup.appendChild(atWrap);

    const atResult = el('div', 'dtk-at-result');
    atResult.style.display = 'none';
    autotuneGroup.appendChild(atResult);

    const renderAutotuneResult = (res: AutotuneResult): void => {
      atResult.innerHTML = '';
      atResult.style.display = '';
      const head = el('div', 'dtk-at-head');
      head.appendChild(el('span', 'dtk-at-winner', res.winner));
      head.appendChild(
        el(
          'span',
          'dtk-at-score',
          `${res.scoring_metric} ${Number.isFinite(res.score) ? res.score.toFixed(3) : '—'} · ${res.mode}`,
        ),
      );
      atResult.appendChild(head);
      atResult.appendChild(
        el(
          'div',
          'dtk-at-meta',
          `${res.n_candidates} candidate${res.n_candidates === 1 ? '' : 's'} · ${res.n_points} pts` +
            (res.consecutive_anomalies != null ? ` · consecutive ${res.consecutive_anomalies}` : '') +
            (res.anomaly_window_points != null && res.min_anomaly_share != null
              ? ` · window ${res.anomaly_window_points}p × ${res.min_anomaly_share}`
              : '') +
            (res.seasonality && res.seasonality.length
              ? ` · seasonality ${JSON.stringify(res.seasonality)}`
              : ' · no seasonality'),
        ),
      );
      // Decision log — collapsed by default (it can be long), one line per stage.
      const logToggle = el('button', 'dtk-tune-cfg-k');
      logToggle.type = 'button';
      const logBody = el('div', 'dtk-at-log');
      let logOpen = false;
      const setLogOpen = (o: boolean): void => {
        logOpen = o;
        logBody.style.display = o ? '' : 'none';
        logToggle.textContent = `${o ? '▾' : '▸'} decision log (${res.decision_log.length})`;
      };
      logToggle.onclick = (): void => setLogOpen(!logOpen);
      for (const e of res.decision_log) {
        const line = el('div', 'dtk-at-logline');
        line.appendChild(el('span', 'dtk-at-stage', e.stage));
        line.appendChild(el('span', 'dtk-at-msg', e.message));
        logBody.appendChild(line);
      }
      setLogOpen(false);
      atResult.appendChild(logToggle);
      atResult.appendChild(logBody);
    };

    atBtn.onclick = (): void => {
      atBtn.disabled = true;
      atMsg.className = 'dtk-apply-msg info';
      atMsg.textContent = 'Autotuning over the shown window… this can take a moment.';
      fetch(payload.autotune_url as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // The current ground truth, so the search is supervised by what's marked.
          yaml: buildLabelsYaml(),
          // Tune on exactly the window shown (the 'Points shown' trim re-slices
          // `series`), so the engine optimizes the same series the cockpit displays
          // and scores — not the full history. Omitted → server uses full history.
          window: series.timestamps.length
            ? {
                start: series.timestamps[0],
                end: series.timestamps[series.timestamps.length - 1],
              }
            : null,
        }),
      })
        .then((r) =>
          r.ok
            ? r.json()
            : r.text().then((t) => {
                throw new Error(t || `HTTP ${r.status}`);
              }),
        )
        .then((res: AutotuneResult) => {
          atBtn.disabled = false;
          applyAutotuneResult(res);
          renderAutotuneResult(res);
          const sup =
            res.mode === 'supervised'
              ? ' — supervised by your incidents'
              : ' — unsupervised (mark incidents for a supervised tune)';
          atMsg.className = 'dtk-apply-msg ok';
          atMsg.textContent = `Tuned${sup}. Knobs updated; review the band, then Apply.`;
        })
        .catch((e: Error) => {
          atBtn.disabled = false;
          atMsg.className = 'dtk-apply-msg err';
          atMsg.textContent = `Autotune failed: ${e.message}`;
        });
    };
  } else {
    autotuneGroup.appendChild(
      el(
        'div',
        'dtk-tune-note',
        'Autotune needs the live server — run `dtk tune` without --no-serve.',
      ),
    );
  }

  // ---- first paint + resize -------------------------------------------------
  setUiMode('tune');
  refreshIncidentList();
  workerClient.runNow();
  renderMetrics();
  // Re-fit the chart whenever its box changes — window resize, font reflow, AND the
  // rail collapsing/expanding (which widens/narrows the windshield without a window
  // resize). ResizeObserver catches all three; fall back to window resize if absent.
  let rafResize = 0;
  const refit = (): void => {
    if (rafResize) cancelAnimationFrame(rafResize);
    rafResize = requestAnimationFrame(() => chart.resize());
  };
  let resizeObserver: ResizeObserver | null = null;
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(refit);
    resizeObserver.observe(chartWrap);
  } else {
    window.addEventListener('resize', refit);
  }

  // Teardown (additive; the shipped product mounts once and never calls this). The
  // landing playground re-mounts render() on each data regeneration, so it calls
  // destroy() first — releasing the worker, the global keydown listener and the
  // resize observer — instead of leaking one set per regeneration.
  return {
    destroy: (): void => {
      workerClient.destroy();
      window.removeEventListener('keydown', onKeydown);
      if (resizeObserver) resizeObserver.disconnect();
      else window.removeEventListener('resize', refit);
      if (rafResize) cancelAnimationFrame(rafResize);
      chart.destroy();
    },
    // Force a repaint (the canvas reads brand tokens off :root at draw time, so a
    // live theme toggle needs a nudge to re-read them). Additive; unused by the
    // shipped product, which never changes theme after load.
    resize: (): void => chart.resize(),
  };
}

// Expose the global the inlined HTML bootstrap calls (mirrors __DTK_REPORT__).
(window as unknown as { __DTK_TUNE__: { render: typeof render } }).__DTK_TUNE__ = { render };
