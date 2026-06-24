/*
 * check-demo-parity.mjs — prove the TS detector port matches detectkit.
 *
 * The landing demo re-implements detectkit's windowed statistical detectors
 * (MAD / Z-Score / IQR) in TypeScript (src/scripts/demo/detector.ts). This
 * script is the golden-parity gate: it reads the frozen Python output
 * (src/scripts/demo/golden.json, produced by website/scripts/gen-demo-golden.py),
 * bundles detector.ts with esbuild, runs its `runDetector` over each case, and
 * asserts every point reproduces the real detectkit band within 1e-6.
 *
 *   node scripts/check-demo-parity.mjs        (or: npm run check:demo-parity)
 *
 * Per point we assert: `scored` matches; when scored, |lower - exp.lower| and
 * |upper - exp.upper| are < 1e-6 and `isAnomaly` matches. Prints a per-case
 * PASS/FAIL summary and exits non-zero on any mismatch, so it fits a CI gate.
 *
 * No new dependencies: esbuild ships transitively with astro/vite, and the
 * bundle is loaded from a temp .mjs file (portable across Node versions).
 */
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEBSITE = path.resolve(here, '..');
const DETECTOR_TS = path.join(WEBSITE, 'src', 'scripts', 'demo', 'detector.ts');
const GOLDEN_JSON = path.join(WEBSITE, 'src', 'scripts', 'demo', 'golden.json');

const TOL = 1e-6;

/** Bundle detector.ts to ESM and dynamically import its `runDetector`. */
async function loadRunDetector() {
  const result = await build({
    entryPoints: [DETECTOR_TS],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'node',
    target: 'node18',
    logLevel: 'silent',
  });
  const code = result.outputFiles[0].text;

  // Load from a temp .mjs file: portable ESM import across Node versions
  // (data: URLs with relative-free, fully-bundled code also work, but a real
  // file gives clean stack traces if the port throws).
  const tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'dtk-demo-parity-'));
  const tmpFile = path.join(tmpDir, 'detector.bundle.mjs');
  await fs.writeFile(tmpFile, code, 'utf8');
  try {
    const mod = await import(pathToFileURL(tmpFile).href);
    if (typeof mod.runDetector !== 'function') {
      throw new Error('detector.ts does not export a `runDetector` function');
    }
    return mod.runDetector;
  } finally {
    await fs.rm(tmpDir, { recursive: true, force: true });
  }
}

/**
 * Rebuild a demo `Series` object from a golden case. The golden stores the
 * series in the same camelCase shape `runDetector` consumes; `truthAnomaly`
 * isn't used by the detector, so we pad it with `false`.
 */
function seriesFromCase(c) {
  const s = c.series;
  const series = {
    timestamps: s.timestamps,
    values: s.values.map((v) => (v === null ? NaN : v)),
    intervalSeconds: s.intervalSeconds,
    truthAnomaly: s.values.map(() => false),
  };
  if (s.seasonalityData) series.seasonalityData = s.seasonalityData;
  if (s.seasonalityColumns) series.seasonalityColumns = s.seasonalityColumns;
  return series;
}

/** Compare a TS ScoredPoint[] against the golden expected[] for one case. */
function checkCase(name, scored, expected) {
  const mismatches = [];

  if (scored.length !== expected.length) {
    mismatches.push(
      `point count mismatch: got ${scored.length}, expected ${expected.length}`,
    );
    return mismatches;
  }

  for (let i = 0; i < expected.length; i++) {
    const exp = expected[i];
    const got = scored[i];

    if (Boolean(got.scored) !== Boolean(exp.scored)) {
      mismatches.push(
        `idx ${i}: scored mismatch (got ${got.scored}, expected ${exp.scored})`,
      );
      continue; // band fields are meaningless if scored disagrees
    }

    if (!exp.scored) continue; // un-scorable point: nothing more to check

    if (Boolean(got.isAnomaly) !== Boolean(exp.isAnomaly)) {
      mismatches.push(
        `idx ${i}: isAnomaly mismatch (got ${got.isAnomaly}, expected ${exp.isAnomaly})`,
      );
    }

    const dLower = Math.abs(got.lower - exp.lower);
    const dUpper = Math.abs(got.upper - exp.upper);
    if (!(dLower < TOL)) {
      mismatches.push(
        `idx ${i}: lower off by ${dLower.toExponential(3)} ` +
          `(got ${got.lower}, expected ${exp.lower})`,
      );
    }
    if (!(dUpper < TOL)) {
      mismatches.push(
        `idx ${i}: upper off by ${dUpper.toExponential(3)} ` +
          `(got ${got.upper}, expected ${exp.upper})`,
      );
    }
  }

  return mismatches;
}

async function main() {
  let golden;
  try {
    golden = JSON.parse(await fs.readFile(GOLDEN_JSON, 'utf8'));
  } catch (err) {
    console.error(
      `check-demo-parity: cannot read ${path.relative(WEBSITE, GOLDEN_JSON)} ` +
        `— run \`python website/scripts/gen-demo-golden.py\` first.\n${err.message}`,
    );
    process.exit(1);
  }

  const cases = golden.cases || [];
  if (cases.length === 0) {
    console.error('check-demo-parity: golden.json has no cases');
    process.exit(1);
  }

  const runDetector = await loadRunDetector();

  let failed = 0;
  const MAX_SHOWN = 8; // cap noise per failing case

  for (const c of cases) {
    const series = seriesFromCase(c);
    let mismatches;
    try {
      const scored = runDetector(series, c.params);
      mismatches = checkCase(c.name, scored, c.expected);
    } catch (err) {
      mismatches = [`runDetector threw: ${err.stack || err.message}`];
    }

    if (mismatches.length === 0) {
      console.log(`PASS  ${c.name}  (${c.expected.length} points)`);
    } else {
      failed++;
      console.log(`FAIL  ${c.name}  (${mismatches.length} mismatch(es))`);
      for (const m of mismatches.slice(0, MAX_SHOWN)) console.log(`        ${m}`);
      if (mismatches.length > MAX_SHOWN) {
        console.log(`        … and ${mismatches.length - MAX_SHOWN} more`);
      }
    }
  }

  console.log('');
  if (failed > 0) {
    console.log(`check-demo-parity: ${failed}/${cases.length} case(s) FAILED`);
    process.exit(1);
  }
  console.log(`check-demo-parity: all ${cases.length} case(s) PASSED`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
