# Design & brand

detectkit's visual identity — colors, type, and theming. The **canonical
sources live in the repo** (no external design files needed):

- `website/src/styles/brand.css` — the design **tokens** as CSS custom
  properties (used by the docs site and the marketing landing).
- `website/brand/Detectkit Brand.dc.html` — the full **brand guide** (logo
  usage, color directions, typography, alert styling, landing layouts).
- `website/src/assets/logo.svg`, `website/public/favicon.svg`,
  `website/src/components/Logo.astro` — the logo / wordmark assets.

`brand.css` is derived **verbatim** from the brand guide — keep the two in sync
if either changes.

## Color tokens

The base palette (`:root` in `brand.css`), theme-independent:

| Token | Hex | Role |
|---|---|---|
| `--clay` | `#d15b36` | Primary brand / accent |
| `--clay-700` | `#b4471f` | Darker accent (hover/pressed) |
| `--ink` | `#1b1916` | Primary text / near-black |
| `--muted` | `#6e675b` | Secondary text |
| `--faint` | `#9a9384` | Tertiary text / hints |
| `--paper` | `#f5f1e8` | Warm page background (light) |
| `--surface` | `#fbf9f3` | Raised surface (light) |
| `--border` | `#e6e0d4` | Hairlines / dividers (light) |
| `--term-bg` | `#211e1a` | Terminal / dark surface |
| `--term-border` | `#332f29` | Dark surface border |
| `--term-text` | `#c9c2b4` | Text on dark surfaces |
| `--accent-green` | `#2e9e73` | Positive accent |

### Status colors (semantic)

These map alert states to color and are kept **in sync with the alert channel
rendering** (`detectkit/alerting/channels/webhook.py`), so dashboards and
notifications read the same way:

| Token | Hex | Meaning |
|---|---|---|
| `--st-recovery` | `#36a64f` | Recovery / all-clear |
| `--st-nodata` | `#f0ad4e` | No-data alert |
| `--st-anomaly` | `#d63232` | Anomaly alert |
| `--st-error` | `#5a7a8c` | Pipeline error |

## Typography

- **`--sl-font`** — `Schibsted Grotesk` (UI, headings, body), with a
  system-sans fallback stack.
- **`--sl-font-mono`** — `JetBrains Mono` (code, terminal, metrics), with a
  monospace fallback stack.

Both are loaded from Google Fonts in `website/astro.config.mjs`.

## Theming

The site ships **two themes**, both built from the tokens above:

- **Dark** (default) — terminal surfaces (`--term-*`) with the clay accent.
- **Light** (`:root[data-theme='light']`) — a warm "paper" theme
  (`--paper` / `--surface`).

Starlight's color variables (`--sl-color-*`) are mapped from the brand palette
in `brand.css` for each theme — change a brand token there and both the docs
chrome and the landing follow. Code blocks stay on a dark theme in both modes
(`expressiveCode.themes: ['github-dark']` in `astro.config.mjs`) to match the
terminal aesthetic.

## Using the tokens

- In the website, reference the CSS variables directly
  (`color: var(--clay)`), never hardcode hex — that keeps theming and the
  landing consistent.
- For anything outside CSS (slides, diagrams, external dashboards), copy the hex
  values from the tables above; they are the single source of truth alongside
  the brand guide.
