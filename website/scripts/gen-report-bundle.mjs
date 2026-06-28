/*
 * gen-report-bundle.mjs — bundle the library HTML report renderer.
 *
 * Bundles src/scripts/report/report.ts (which consumes the ReportPayload
 * contract and shares low-level canvas primitives with the landing demo via
 * src/scripts/core/canvas.ts) into a single minified IIFE and writes it to
 * detectkit/reporting/assets/report.js. The Python report builder
 * (detectkit/reporting/) inlines that asset into a self-contained standalone
 * HTML; at load it assigns `window.__DTK_REPORT__ = { render }`.
 *
 *   node scripts/gen-report-bundle.mjs        (or: npm run build:report-bundle)
 *
 * No new dependencies: esbuild ships transitively with astro/vite. Same
 * generated-asset pattern as make-bot-icon.mjs / gen-tune-bundle.mjs.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEBSITE = path.resolve(here, '..');
const REPO = path.resolve(WEBSITE, '..');
const ENTRY = path.join(WEBSITE, 'src', 'scripts', 'report', 'report.ts');
const OUT_DIR = path.join(REPO, 'detectkit', 'reporting', 'assets');
const OUT_FILE = path.join(OUT_DIR, 'report.js');

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const result = await build({
    entryPoints: [ENTRY],
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    target: 'es2019',
    minify: true,
    legalComments: 'none',
    logLevel: 'info',
  });

  const code = result.outputFiles[0].text;
  await fs.writeFile(OUT_FILE, code, 'utf8');

  const kb = (Buffer.byteLength(code, 'utf8') / 1024).toFixed(1);
  console.log(`gen-report-bundle: wrote ${path.relative(REPO, OUT_FILE)} (${kb} KB)`);

  if (!code.includes('__DTK_REPORT__')) {
    console.error('gen-report-bundle: bundle does not assign window.__DTK_REPORT__');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
