/*
 * check-tune-worker.mjs — behavior gate for the tune cockpit's detector worker.
 *
 * Bundles src/scripts/report/tune.worker.ts with esbuild, shims the worker
 * global (`self`), drives it with `series` + `run` messages and asserts the
 * alert-fire semantics — in particular the fraction alert rule (issue #101):
 *
 *   - latest-point gate: a stale window (newest point clean) never fires;
 *   - missing-slot denominator: slots before the series start / gaps count
 *     against the share, never toward it;
 *   - OR-merge with the consecutive rule, deduped by fire point;
 *   - legacy path: without the pair, fires are exactly the consecutive rule's.
 *
 * Detector flags are made deterministic with manual_bounds (value > 50 flags).
 *
 *   node scripts/check-tune-worker.mjs        (or: npm run check:tune-worker)
 */
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEBSITE = path.resolve(here, '..');
const WORKER_TS = path.join(WEBSITE, 'src', 'scripts', 'report', 'tune.worker.ts');

async function loadWorker() {
  const result = await build({
    entryPoints: [WORKER_TS],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
    target: 'node18',
    logLevel: 'silent',
    banner: {
      js:
        'const __POSTS__ = [];\n' +
        'globalThis.self = { onmessage: null, postMessage: (m) => __POSTS__.push(m) };\n' +
        'globalThis.__DTK_POSTS__ = __POSTS__;',
    },
  });
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'dtk-tune-worker-'));
  const tmpFile = path.join(tmpDir, 'tune.worker.bundle.mjs');
  await fs.writeFile(tmpFile, result.outputFiles[0].text, 'utf8');
  await import(pathToFileURL(tmpFile).href);
  return {
    post: (data) => globalThis.self.onmessage({ data }),
    posts: globalThis.__DTK_POSTS__,
  };
}

const INTERVAL = 600; // seconds
const BASE = Date.UTC(2026, 0, 1);

/** Build a gap-filled series where `values[i] > 50` flags (manual_bounds). */
function series(values) {
  return {
    timestamps: values.map((_, i) => BASE + i * INTERVAL * 1000),
    values,
    intervalSeconds: INTERVAL,
    truthAnomaly: values.map(() => false),
  };
}

const PARAMS = {
  type: 'manual_bounds',
  threshold: 3.0,
  windowSize: 100,
  minSamples: 30,
  inputType: 'values',
  smoothing: 'none',
  smoothingAlpha: 0.3,
  smoothingWindow: 10,
  windowWeights: 'none',
  halfLife: null,
  detrend: 'none',
  stabilization: 'none',
  seasonalityComponents: null,
  minSamplesPerGroup: 10,
  consecutiveAnomalies: 2,
  lowerBound: -50,
  upperBound: 50,
  direction: 'any',
  lags: 5,
};

let failures = 0;
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`PASS  ${name}`);
  } else {
    failures += 1;
    console.error(`FAIL  ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

async function main() {
  const w = await loadWorker();
  let id = 0;
  const run = (values, extra = {}) => {
    w.post({ type: 'series', series: series(values) });
    id += 1;
    w.post({ type: 'run', id, params: PARAMS, ...extra });
    const res = w.posts[w.posts.length - 1];
    if (!res || res.id !== id) throw new Error('worker did not reply');
    return res;
  };

  // Base scenario: a diffuse incident (alternating flags at 20..30) that the
  // consecutive=2 rule misses entirely, plus a solid 3-run at 40..42 it fires on.
  const vals = new Array(60).fill(0);
  for (let i = 20; i <= 30; i += 2) vals[i] = 100; // 6 alternating flags
  vals[40] = vals[41] = vals[42] = 100; // solid run

  const legacy = run(vals);
  check(
    'legacy path fires only the consecutive rule',
    legacy.fires.length === 1 && legacy.fires[0] === 41,
    `fires=${JSON.stringify(legacy.fires)}`,
  );

  const merged = run(vals, { anomalyWindowPoints: 4, minAnomalyShare: 0.3 });
  // share rule: at i=22..30 (even), trailing 4 slots hold 2 flags => 0.5 >= 0.3.
  const shareFire = merged.fires.find((f) => f >= 20 && f <= 30);
  check(
    'fraction rule catches the diffuse incident the consecutive rule misses',
    shareFire !== undefined,
    `fires=${JSON.stringify(merged.fires)}`,
  );
  check(
    'fires are deduped by fire point (no duplicates)',
    new Set(merged.fires).size === merged.fires.length,
    `fires=${JSON.stringify(merged.fires)}`,
  );
  const diffuseSpan = merged.fireSpans[merged.fires.indexOf(shareFire)];
  check(
    'share fire span covers the diffuse streak (onset -> last fire)',
    diffuseSpan[0] <= BASE + 20 * INTERVAL * 1000 && diffuseSpan[1] >= diffuseSpan[0],
    `span=${JSON.stringify(diffuseSpan)}`,
  );

  // Latest-point gate: window 3/4 anomalous but the newest point clean.
  const stale = new Array(40).fill(0);
  stale[10] = stale[11] = stale[12] = 100; // solid run, then clean
  const staleRes = run(stale, { anomalyWindowPoints: 4, minAnomalyShare: 0.5 });
  check(
    'a stale window never fires the share rule on a clean point',
    staleRes.fires.every((f) => f >= 10 && f <= 12),
    `fires=${JSON.stringify(staleRes.fires)}`,
  );

  // Missing-slot denominator: one isolated flag, w=6 s=0.3 (needs 1.8 slots).
  const isolated = new Array(40).fill(0);
  isolated[0] = 100; // also exercises slots before the series start
  isolated[20] = 100;
  const isoRes = run(isolated, { anomalyWindowPoints: 6, minAnomalyShare: 0.3 });
  check(
    'missing/leading slots count in the denominator only (no isolated fires)',
    isoRes.fires.length === 0,
    `fires=${JSON.stringify(isoRes.fires)}`,
  );

  // Both-or-neither: a window without a share (or below 2) stays legacy.
  const offRes = run(vals, { anomalyWindowPoints: 4, minAnomalyShare: null });
  check(
    'a half-pair (window without share) stays consecutive-only',
    JSON.stringify(offRes.fires) === JSON.stringify(legacy.fires),
    `fires=${JSON.stringify(offRes.fires)}`,
  );

  if (failures) {
    console.error(`\ncheck-tune-worker: ${failures} check(s) FAILED`);
    process.exit(1);
  }
  console.log('\ncheck-tune-worker: all checks PASSED');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
