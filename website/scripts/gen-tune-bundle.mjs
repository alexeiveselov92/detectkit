/*
 * gen-tune-bundle.mjs — bundle the interactive `dtk tune` renderer.
 *
 * Bundles src/scripts/report/tune.ts (which reuses the same faithful detector
 * port + chart that power the landing playground via src/scripts/demo/ and the
 * low-level canvas primitives in src/scripts/core/canvas.ts) into a single
 * minified IIFE and writes it to detectkit/tuning/assets/tune.js. The Python
 * tuning layer (detectkit/tuning/) inlines that asset into a self-contained
 * interactive HTML page; at load it assigns `window.__DTK_TUNE__ = { render }`.
 *
 *   node scripts/gen-tune-bundle.mjs        (or: npm run build:tune-bundle)
 *
 * No new dependencies: esbuild ships transitively with astro/vite. Same
 * generated-asset pattern as gen-report-bundle.mjs / make-bot-icon.mjs.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEBSITE = path.resolve(here, '..');
const REPO = path.resolve(WEBSITE, '..');
const ENTRY = path.join(WEBSITE, 'src', 'scripts', 'report', 'tune.ts');
const WORKER_ENTRY = path.join(WEBSITE, 'src', 'scripts', 'report', 'tune.worker.ts');
const OUT_DIR = path.join(REPO, 'detectkit', 'tuning', 'assets');
const OUT_FILE = path.join(OUT_DIR, 'tune.js');

const COMMON = {
  bundle: true,
  write: false,
  format: 'iife',
  platform: 'browser',
  target: 'es2019',
  minify: true,
  legalComments: 'none',
  logLevel: 'info',
};

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  // 1) Bundle the detector worker on its own. It runs the parity-checked detector
  //    port off the UI thread; we embed its code as a string so the report stays
  //    a single self-contained file (the main bundle spins it up from a Blob URL).
  const workerRes = await build({ ...COMMON, entryPoints: [WORKER_ENTRY] });
  const workerCode = workerRes.outputFiles[0].text;

  // 2) Bundle the main renderer, injecting the worker source as a string literal
  //    via `define` (esbuild replaces the __DTK_WORKER_SRC__ identifier).
  const result = await build({
    ...COMMON,
    entryPoints: [ENTRY],
    define: { __DTK_WORKER_SRC__: JSON.stringify(workerCode) },
  });

  const code = result.outputFiles[0].text;
  await fs.writeFile(OUT_FILE, code, 'utf8');

  const kb = (Buffer.byteLength(code, 'utf8') / 1024).toFixed(1);
  console.log(`gen-tune-bundle: wrote ${path.relative(REPO, OUT_FILE)} (${kb} KB)`);

  if (!code.includes('__DTK_TUNE__')) {
    console.error('gen-tune-bundle: bundle does not assign window.__DTK_TUNE__');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
