/*
 * make-bot-icon.mjs — generate the detectkit bot avatar (public/bot-icon.png).
 *
 * Alert channels (Slack / Mattermost / webhook) render the bot avatar from a
 * raster URL, so the SVG brand mark is rasterized to a 512×512 PNG here and
 * served from the docs site at https://dtk.pipelab.dev/bot-icon.png — the
 * default `icon_url` in detectkit/alerting/channels/branding.py.
 *
 * The geometry is the brand mark (src/assets/logo.svg) on a full-bleed clay
 * tile so it reads well when chat clients crop the avatar to a circle.
 *
 * Run after changing the logo/brand:  node scripts/make-bot-icon.mjs
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, '..', 'public', 'bot-icon.png');
const SIZE = 512;

// Brand mark on a full-bleed clay tile (#D15B36) with the warm-paper stroke
// (#FBF9F3) — kept in sync with src/assets/logo.svg.
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${SIZE}" height="${SIZE}">
  <rect x="0" y="0" width="100" height="100" rx="22" fill="#D15B36"/>
  <polyline points="14,62 36,62 50,22 64,62 86,62" fill="none" stroke="#FBF9F3" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="50" cy="22" r="6.5" fill="#FBF9F3"/>
</svg>`;

await sharp(Buffer.from(svg), { density: 384 })
  .resize(SIZE, SIZE)
  .png({ compressionLevel: 9 })
  .toFile(OUT);

console.log(`wrote ${path.relative(path.resolve(here, '..'), OUT)} (${SIZE}x${SIZE})`);
