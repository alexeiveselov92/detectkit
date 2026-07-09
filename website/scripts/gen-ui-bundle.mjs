/*
 * gen-ui-bundle.mjs — bundle the `dtk ui` project-level cockpit renderer.
 *
 * Bundles src/scripts/ui/ui.ts (which shares low-level canvas primitives with
 * the landing demo + report/tune renderers via src/scripts/core/canvas.ts)
 * into a single minified IIFE and writes it to detectkit/ui/assets/ui.js. The
 * Python UI server (detectkit/ui/) inlines that asset into a self-contained
 * standalone HTML shell; at load it assigns `window.__DTK_UI__ = { render }`.
 *
 *   node scripts/gen-ui-bundle.mjs        (or: npm run build:ui-bundle)
 *
 * No new dependencies: esbuild ships transitively with astro/vite. Same
 * generated-asset pattern as gen-report-bundle.mjs / gen-tune-bundle.mjs /
 * make-bot-icon.mjs. No worker, no `define` — unlike gen-tune-bundle.mjs, the
 * cockpit has no off-thread detector to embed.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEBSITE = path.resolve(here, '..');
const REPO = path.resolve(WEBSITE, '..');
const ENTRY = path.join(WEBSITE, 'src', 'scripts', 'ui', 'ui.ts');
const OUT_DIR = path.join(REPO, 'detectkit', 'ui', 'assets');
const OUT_FILE = path.join(OUT_DIR, 'ui.js');

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
  console.log(`gen-ui-bundle: wrote ${path.relative(REPO, OUT_FILE)} (${kb} KB)`);

  if (!code.includes('__DTK_UI__')) {
    console.error('gen-ui-bundle: bundle does not assign window.__DTK_UI__');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
