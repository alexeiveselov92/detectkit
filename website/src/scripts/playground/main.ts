// Entry point for the interactive playground.
//
// The playground is now a LITERAL instance of the shipped `dtk tune` cockpit
// (../report/tune) fed a synthetic metric — the same chart, detector worker,
// mode-aware rail, live recall/FDR quality bar and warm-up honesty the product
// ships, with no forked shell. This composition root owns only the extra layer the
// real product doesn't need: a data-GENERATOR toolbar (rhythm / noise / trend /
// interval / incident / size) that fabricates a metric, plus a one-click "shape
// break" showcase. The detector/threshold/window/seasonality/alerting controls all
// live in the cockpit's rail — we don't reimplement them.
//
// The cockpit builds its state once at mount, so a data change rebuilds the payload
// and RE-MOUNTS render() (idempotent — it clears the mount first). We destroy the
// previous instance first (releasing its worker + listeners) and carry the user's
// tuned knobs across the re-mount via the cockpit's `onState` hook, so changing the
// data shape never resets the detector you were tuning.

import '../report/tune'; // side-effect: assigns window.__DTK_TUNE__ = { render }
import { warmupRequirement } from '../demo/detector';
import { generateSeries } from '../demo/synth';
import type {
  AlertDirection,
  AnomalyKind,
  DetectorParams,
  NoiseLevel,
  SeasonalityPreset,
  Series,
  SynthOptions,
  TrendKind,
} from '../demo/types';
import type { DetectorSeed, TunePayload } from '../report/tune/types';
import { buildSyntheticPayload, defaultSeed } from './payload';

// The cockpit's render() signature (it's exposed on window, not exported, exactly
// as the shipped HTML consumes it). `hooks`/the returned handle are the additive
// playground extension points (no-ops for the product).
type TuneRender = (
  payload: TunePayload,
  mount: HTMLElement,
  hooks?: {
    onState?: (s: {
      params: DetectorParams;
      windowPoints: number | null;
      share: number | null;
    }) => void;
  },
) => { destroy: () => void; resize: () => void };

// Each interval picks a point count spanning a readable number of cycles (matches
// the historical demo). The cockpit dims the warm-up lead-in; we regrow the series
// below so a usable effective zone always remains (autoreg's warm-up can exceed the
// 1d base length).
const INTERVALS: Record<string, { seconds: number; points: number }> = {
  '10min': { seconds: 600, points: 720 }, // ~5 days
  '1h': { seconds: 3600, points: 504 }, // ~3 weeks
  '1d': { seconds: 86400, points: 150 }, // ~5 months
};

function init(): void {
  const mount = document.getElementById('dkx-mount');
  const gen = document.getElementById('pg-gen');
  const tuneApi = (window as unknown as { __DTK_TUNE__?: { render: TuneRender } }).__DTK_TUNE__;
  if (!mount || !gen || !tuneApi) return;

  // ---- generator toolbar readers -------------------------------------------
  const seg = (name: string): string =>
    gen.querySelector<HTMLButtonElement>(`[data-control="${name}"] button.on`)?.dataset.v ?? '';
  const setSeg = (name: string, value: string): void => {
    gen
      .querySelectorAll<HTMLButtonElement>(`[data-control="${name}"] button`)
      .forEach((b) => b.classList.toggle('on', b.dataset.v === value));
  };
  const num = (id: string): number => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    return el ? Number(el.value) : 0;
  };

  let seedNum = 7;
  const readSynth = (): SynthOptions => {
    const iv = INTERVALS[seg('interval')] ?? INTERVALS['1h'];
    return {
      seasonality: (seg('rhythm') || 'daily') as SeasonalityPreset,
      noise: (seg('noise') || 'medium') as NoiseLevel,
      trend: (seg('trend') || 'none') as TrendKind,
      intervalSeconds: iv.seconds,
      points: iv.points,
      anomaly: (seg('incident') || 'cluster') as AnomalyKind,
      anomalyMagnitude: num('pg-size') / 100,
      seed: seedNum,
    };
  };

  // ---- live state carried across re-mounts ---------------------------------
  // The cockpit reports its live knob state on every recompute; we mirror it here so
  // a data regeneration re-seeds the SAME detector/alert config the user had, rather
  // than snapping back to the default.
  const state = {
    seed: defaultSeed('mad'),
    consecutive: 3,
    windowPoints: null as number | null,
    share: null as number | null,
    direction: 'any' as AlertDirection,
  };
  let handle: { destroy: () => void } | null = null;

  const seedToParams = (seed: DetectorSeed): DetectorParams => ({
    ...seed,
    consecutiveAnomalies: state.consecutive,
    direction: state.direction,
  });

  // Regenerate the synthetic metric and (re)mount the cockpit on it. `resetSeed`
  // forces a detector (the showcase); otherwise the user's tuned knobs are preserved.
  function regenerate(resetSeed?: DetectorSeed): void {
    const synth = readSynth();
    const seed = resetSeed ?? state.seed;

    // Size the series by the warm-up so the effective (scored) zone dominates the
    // chart — the same logic the standalone demo used: a provisional series at the
    // interval's base length tells us the warm-up requirement; if too little would
    // remain scored, regenerate longer (autoreg on the 1d grid needs this most).
    const provisional = generateSeries(synth);
    const need = warmupRequirement(provisional, seedToParams(seed));
    let series: Series = provisional;
    if (provisional.timestamps.length - need < 300) {
      series = generateSeries({ ...synth, points: Math.min(need + 320, 1200) });
    }

    const payload = buildSyntheticPayload({
      series,
      seed,
      consecutive: state.consecutive,
      windowPoints: state.windowPoints,
      share: state.share,
      direction: state.direction,
      incidentKind: synth.anomaly,
      description: `${synth.seasonality} rhythm · ${synth.noise} noise · ${synth.anomaly} incident`,
    });
    if (resetSeed) state.seed = resetSeed;

    handle?.destroy();
    handle = tuneApi.render(payload, mount as HTMLElement, {
      onState: ({ params, windowPoints, share }): void => {
        const { consecutiveAnomalies, direction, ...rest } = params;
        state.seed = rest;
        state.consecutive = consecutiveAnomalies;
        state.direction = direction ?? 'any';
        state.windowPoints = windowPoints;
        state.share = share;
      },
    });
  }

  // ---- wire the generator toolbar ------------------------------------------
  gen.querySelectorAll<HTMLElement>('[data-control]').forEach((group) => {
    const name = group.dataset.control as string;
    group.querySelectorAll<HTMLButtonElement>('button[data-v]').forEach((btn) => {
      btn.addEventListener('click', () => {
        setSeg(name, btn.dataset.v as string);
        regenerate();
      });
    });
  });

  // Size is a range slider — echo live, but re-mount only on release so a drag
  // doesn't rebuild the whole cockpit every frame.
  const sizeInput = document.getElementById('pg-size') as HTMLInputElement | null;
  const sizeVal = document.getElementById('pg-size-val');
  if (sizeInput) {
    sizeInput.addEventListener('input', () => {
      if (sizeVal) sizeVal.textContent = `${sizeInput.value}%`;
    });
    sizeInput.addEventListener('change', () => regenerate());
  }

  document.getElementById('pg-reseed')?.addEventListener('click', () => {
    seedNum = (seedNum * 1664525 + 1013904223) >>> 0;
    regenerate();
  });

  // Shape-break showcase: the autoreg "aha" in one click — a free-running pulse the
  // calendar seasonality can't capture, with a pattern_break (a frozen value: normal
  // in level, wrong in shape) that the windowed detectors miss and autoreg catches.
  document.getElementById('pg-showcase')?.addEventListener('click', () => {
    setSeg('rhythm', 'pulse');
    setSeg('incident', 'pattern_break');
    regenerate(defaultSeed('autoreg'));
  });

  // ---- first paint ----------------------------------------------------------
  if (sizeInput && sizeVal) sizeVal.textContent = `${sizeInput.value}%`;
  regenerate();

  // The canvas reads brand tokens off :root at draw time, so a live theme toggle
  // (the header button flips documentElement's data-theme) doesn't recolor the chart
  // until the next repaint. Nudge it whenever the resolved theme changes.
  new MutationObserver(() => handle?.resize()).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init, { once: true });
} else {
  init();
}
