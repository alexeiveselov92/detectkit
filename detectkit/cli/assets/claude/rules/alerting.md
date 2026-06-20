# detectkit — Alerting

detectkit is **alert-centric**: the *alert* is the primary entity and a detector
anomaly is secondary evidence a rule interprets (the same anomaly means
different things under different rules). Configure alerting per metric under
`alerting:`. Channels themselves are defined in `profiles.yml` (see
`project.md`).

```yaml
alerting:
  enabled: true
  channels: [mattermost_ops]
  min_detectors: 1
  direction: "same"
  consecutive_anomalies: 3
  alert_cooldown: "30min"
```

## The alert rule (quorum × direction × consecutive)

At the alert step, detectkit looks at the most recent detections and applies one
combined contract:

1. **Quorum** — at each timestamp, group all detectors' anomalies. The point
   satisfies the quorum when at least `min_detectors` of them match the
   `direction` policy.
2. **Consecutive** — an alert fires only when the latest `consecutive_anomalies`
   timestamps each satisfy the quorum **and** are grid-adjacent (exactly one
   `interval` apart). A missing detection row between two anomalies breaks the
   chain.

### `min_detectors` (default 1)

How many detectors must qualify at **every** point in the chain. `1` = any one
detector (high recall); `N` = all must agree (high precision).

### `direction` (default `"same"`)

Which anomalies count toward the quorum:

- `"same"` — at the latest point, ≥`min_detectors` detectors must agree on **one**
  direction (up and down counted separately — disagreement is not consensus).
  The winning direction is **locked for the whole chain**. Ties: more detectors
  win, then the more severe side.
- `"any"` — every anomaly counts regardless of direction (1 up + 1 down
  satisfies `min_detectors: 2`).
- `"up"` — only anomalies above the interval count (others ignored, never block).
- `"down"` — only anomalies below the interval count.

Pick by meaning: `"up"` for CPU/error rate (high is bad), `"down"` for cache hit
rate/uptime (low is bad), `"any"` for single-detector "any deviation matters",
`"same"` for multi-detector consensus.

### `consecutive_anomalies` (default 3)

Grid-adjacent quorum points required before alerting. `1` = alert immediately
(critical metrics); `3` = balanced; `5+` = noisy metrics. Gaps in the detection
grid break the chain.

### Worked example (two detectors A, B; `min_detectors: 2`)

| `direction` | A | B | Result |
|---|---|---|---|
| `same` | up | down | no alert (disagreement) |
| `same` | up | up | quorum; "up" locked for the chain |
| `up` | up | down | no quorum (only one "up", needs 2) |
| `down` | up | up | no quorum ("up" ignored) |
| `any` | up | down | quorum (every anomaly counts) |

## Cooldown (spam control) — **set it in production**

`alert_cooldown` defaults to **`null` = no cooldown**, meaning a persisting
anomaly re-alerts on **every** `dtk run` (e.g. every cron tick). Always set a
cooldown for production metrics.

```yaml
alert_cooldown: "30min"            # or seconds: 1800
cooldown_reset_on_recovery: true   # default — reset the timer when the metric recovers
```

- With `cooldown_reset_on_recovery: true` (recommended): alert on first
  occurrence, suppress duplicates while it persists, alert again on a fresh
  incident after recovery.
- With `false` (strict): an absolute minimum time between any alerts, regardless
  of recovery — for very noisy metrics.
- No-data and anomaly alerts **share** the same cooldown state within an alert
  block. State lives in `_dtk_alert_states`.

## Recovery notifications

```yaml
notify_on_recovery: true        # default false
template_recovery: null         # optional custom body
```

Sends one notification per incident when the metric returns to normal after an
alert fired. **Direction-aware**: after a "down" alert, a fresh "up" anomaly
does not block recovery (the original condition no longer holds). Independent of
`alert_cooldown` (recovery always sends once per incident). Default body is
alert-centric (`🟢 Alert cleared: <metric>`).

## No-data alerts

```yaml
no_data_alert: true             # default false
template_no_data: null          # optional custom body
```

Fires when the **last complete interval** (now floored to a boundary, minus one
interval) has no datapoint, or the row's value is `NULL`/`NaN`. `min_detectors`
and `consecutive_anomalies` do **not** apply (it's a single binary signal).
Honors `alert_cooldown` and `suppress_until`. Webhook channels render it amber.
Use for cron loaders where source absence is a real failure; **don't** enable on
naturally sparse metrics.

## Temporary suppression

```yaml
suppress_until: "2026-04-11 18:00:00"   # UTC; default null
```

Load and detect keep running; only alerting is paused until that time, then it
auto-resumes (no second edit needed). For permanent off, use `enabled: false`.

## Mentions

```yaml
mentions: [oncall_engineer, here]   # plain names, no @
```

Channel-agnostic: you write plain usernames and each channel renders them
natively. Special broadcast keywords: `here`, `channel`, `all`. Available as
`{mentions}` / `{mentions_line}` template variables (appended automatically if
not placed in a template). On Slack/Mattermost the default rendering puts the
mentions in the **top-level message text** (not the attachment) so they actually
notify. Slack `@username` is display-only — use Slack user IDs (`U…`) for real
pings.

## Dashboard / runbook links

```yaml
dashboard_url: https://grafana.ops/d/api-errors   # optional; default null
links:                                             # optional; default {}
  Runbook: https://runbooks.ops/api-errors
  Grafana: https://grafana.ops/d/api-errors
```

`dashboard_url` is surfaced as a first-class action on **every** channel: the
attachment title is clickable and a link is shown on Slack/Mattermost, Telegram
gets an inline "Open dashboard" link, and email gets an "Open dashboard" button.
`links` adds extra `label: url` entries alongside it. Both are also exposed to
custom templates — see `{dashboard_url}` / `{dashboard_line}` below.

## How default messages render

With no custom `template`, each channel renders a structured, branded message
(alert-centric: the rule that fired leads, the anomaly value is evidence). The
shared value computation lives in one place (`BaseAlertChannel.build_context`),
so templates and native rendering stay consistent. Every alert title/headline
leads with a colored **status circle** — 🔴 anomaly, 🟢 recovery, 🟡 no-data,
🔵 pipeline error — so the status reads from color alone. It also leads with the
**project name** as a `[name] ` prefix (from `detectkit_project.yml`) — see
[Project label](#project-label-multi-project-channels) below.

- **Slack / Mattermost / generic webhook** — one message *attachment* with a
  status-colored accent bar, a clickable title (the metric; links to
  `dashboard_url` when set), a short markdown lead (the rule), and a compact
  fields grid: short fields Value / Expected / Quorum / Severity, then full-width
  Detected-at / Detectors / Parameters, plus a branded footer + footer icon.
  @mentions ride in the **top-level** message text so they notify. A custom
  `template` instead renders as a plain text-only attachment (color/title/
  branding kept, no fields grid).
- **Telegram** — default `parse_mode` is now **HTML**. The default message is
  structured and HTML-escaped: a colored status dot (red anomaly / green
  recovery / yellow no-data / blue error), a bold headline, the rule, then
  evidence in `<code>` (value/expected/severity/time/detector/params), an inline
  "Open dashboard" link, then mentions. This fixes the old Markdown mode raising
  "can't parse entities" on params JSON containing underscores (e.g.
  `window_size`). Custom templates are sent verbatim under the parse mode, so
  they must be HTML-safe; set `parse_mode: Markdown` to keep the old behavior.
- **Email** — a branded HTML card (inline-CSS, table-based, Outlook-safe):
  colored accent + status pill, the metric, a 2-col value/expected/severity
  table, a monospace params box, an optional "Open dashboard" button, and a
  footer. The plain-text body remains the multipart fallback.

## Project label (multi-project channels)

The bot keeps the **detectkit brand** name + avatar by default (so users rarely
override them). To still tell apart two projects posting to the **same** channel,
detectkit stamps the project name (`detectkit_project.yml` → `name`) onto every
alert and shows it by default — no config needed:

- **Title / headline / subject** lead with a `[name] ` prefix on every kind
  (anomaly, recovery, no-data, error): `🔴 [payments] Alert: api_error_rate`.
- **Webhook (Slack/Mattermost)** also pairs it in the footer: `detectkit · payments`.
- **Telegram** carries it in the bold headline (no footer/avatar to override).
- **Email** prefixes the subject, shows a small project eyebrow above the metric,
  and pairs it in the footer (`Sent by detectkit · payments`).

It is exposed to custom templates as `{project_name}` and `{project_name_prefix}`
(`"[name] "` when set, else `""`). Direct library/API callers that don't set it
render unchanged. The `name` is informational only (it does not key any `_dtk_*`
table), so renaming it is safe — spaces are allowed for a prettier label.

## Multiple alert configs per metric

`alerting:` may be a **list** of independent blocks, each with its own channels,
timezone, template, and rule — evaluated and sent independently:

```yaml
alerting:
  - {enabled: true, channels: [mattermost_ops], consecutive_anomalies: 3}
  - {enabled: true, channels: [slack_critical], consecutive_anomalies: 1, direction: "up"}
```

Each block's state is keyed by a hash of its functional fields; editing those
fields or removing a block orphans its `_dtk_alert_states` row (prune with
`dtk clean`). Disabling with `enabled: false` keeps the hash, so a paused alert
is never treated as orphaned.

## Templates

Defaults are alert-centric. Override with:
- `template_single` — alerts with `consecutive_count` ≤ 1.
- `template_consecutive` — streaks (`> 1`); falls back to `template_single`.
- `template_recovery`, `template_no_data` — recovery / no-data bodies.

Templates are plain `{var}` strings (or Jinja2 `.j2` files under `templates_dir`
referenced by path). Key variables:

| Variable | Meaning |
|---|---|
| `{metric_name}`, `{description}` / `{description_line}` | identity |
| `{project_name}` / `{project_name_prefix}` | project label (`"[name] "` prefix, or `""`) |
| `{timestamp}`, `{timezone}` | when (display tz via `alerting.timezone`, default UTC) |
| `{value}` / `{value_display}` | metric value (`value_display` is NaN-safe) |
| `{confidence_lower}` / `{confidence_upper}` / `{confidence_interval}` | bounds |
| `{expected_range}` | one-sided-aware band (`>= 7.00`, `<= 1.10`, `[lo, hi]`, `N/A`) |
| `{detector_name}`, `{detector_count}` | who fired (`"N detectors"` for multi) |
| `{min_detectors}` / `{direction_policy}` / `{consecutive_required}` | the configured rule |
| `{direction}`, `{consecutive_count}`, `{severity}` | observed values |
| `{status}` | `ANOMALY` / `RECOVERED` / `NO_DATA` / `ERROR` |
| `{mentions}` / `{mentions_line}` | formatted mentions |
| `{dashboard_url}` | raw `dashboard_url` (empty string when unset) |
| `{dashboard_line}` | `Dashboard: <url>\n` when set, else empty (appended to default plain-text templates) |

> For no-data/error alerts there is no numeric value — avoid `{value:.2f}` in
> those templates (detectkit falls back to the default template rather than
> crashing, but write kind-appropriate templates).

## Test, tune, debug

```bash
dtk test-alert <metric>     # mock alert through the real channels, using this rule
```

- **Too many alerts** → raise `consecutive_anomalies`, raise detector
  `threshold`, use `min_detectors: 2`, add seasonality, or set a `direction`.
- **No alerts** → check `enabled: true`, channels exist in `profiles.yml`,
  detections exist (`dtk run --steps detect`), the quorum/consecutive thresholds
  aren't too high, and `direction` isn't filtering the move out.
- **Wrong direction** (alerting when CPU drops) → set `direction: "up"`.
- Aim for **< 5 alerts/day/team** to avoid fatigue.
