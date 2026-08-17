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

## Fraction-based alert window (`anomaly_window` + `min_anomaly_share`)

An optional second rule, **OR-ed** with the consecutive rule above — either can
fire an alert (if both would fire at once, the message leads with the
consecutive-streak story):

```yaml
alerting:
  consecutive_anomalies: 3   # still evaluated
  anomaly_window: "30min"    # duration string or seconds → grid points via the interval
  min_anomaly_share: 0.3     # fraction in (0, 1]
```

Must be set **together**. Fires when **both** hold: the **latest point**
itself meets the quorum (never fires on a stale window with a clean tail),
**and** at least `min_anomaly_share` of the trailing `anomaly_window` grid
points also meet the quorum. Same `min_detectors` × `direction` quorum
machinery per point as above; for `direction: same` the winning direction is
locked from the **latest** point's quorum (same as the consecutive walk).

Missing/no-data grid slots count only in the **denominator** — an outage
makes the rule *harder* to fire, not easier (`no_data_alert` covers outages
separately). **Recovery hysteresis**: with `notify_on_recovery`, recovery
needs the window share to also drop **below half** `min_anomaly_share` (not
just a clean latest point), so a share hovering at the threshold doesn't flap
alert/recover.

Use it for **flapping incidents** — mostly anomalous with occasional clean
points that would otherwise reset a pure `consecutive_anomalies` chain and
silently swallow an ongoing incident (the motivating case: Yandex's
production write-up names the anomaly window as their single most effective
false-positive fix).

Message rendering: the Rule chip is now built from a shared `rule_display` —
legacy configs (no fraction rule) render byte-identical
(`min_detectors=… · direction=… · consecutive=…`); a share-configured metric
also names the fraction rule (`… · consecutive=3 (or share>=30% over 30m)`),
and a share-**fired** alert leads with it instead
(`… · share>=30% over 30m`). A share-fired alert's lead sentence reports the
window story directly, e.g. `14 of the last 30 10min intervals were
anomalous (47%) — at or above the 30% share threshold over 5h.`; its "Anomaly
began" is the first matched point the window can see (bounded by the window,
unlike a consecutive alert's fully resolved onset). New opt-in template vars:
`{rule_display}`, `{window_points}`, `{window_matched}`. Recovery messages
echo the same combined chip as a consecutive-fired alert of a
share-configured config (`… · consecutive=3 (or share>=30% over 30m)`), so
fire and recovery always name one rule; a scattered share-fired incident's
"Incident lasted …" line may undercount (it reconstructs a contiguous run).
Reports and `dtk ui`'s overview pick up share-fired
alerts automatically via the shared replay seam.

Both paths tune this pair now: supervised `dtk autotune` runs a 2-D sweep of
`anomaly_window` × `min_anomaly_share` OR-ed with the chosen
`consecutive_anomalies` rule, adopted only on a strictly greater score (a tie
keeps the consecutive-only rule); `dtk tune`'s cockpit has always-visible
anomaly-window / min-share rail controls with live replay of the same OR-ed
rule, and Apply writes the pair back (or removes both when off).

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

On a **multi-detector** metric the recovery message reports the detector that
actually fired the incident — its name, params and `Expected` range at the
recovered point — so a metric pairing a MAD band with a `manual_bounds` floor
clears with the same detector's numbers it fired with.

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
naturally sparse metrics. With a `loading_delay` configured (`metrics.md`), the
"last complete interval" shifts back by that same delay, so the deliberately
withheld newest interval never trips a false no-data alert while it's still in
flight upstream.

## Temporary suppression

```yaml
suppress_until: "2026-04-11 18:00:00"   # UTC; default null
```

Load and detect keep running; only alerting is paused until that time, then it
auto-resumes (no second edit needed). For permanent off, use `enabled: false`.
Accepts `"YYYY-MM-DD HH:MM:SS"`, `"YYYY-MM-DD HH:MM"`, the ISO `T` form, or a
bare `"YYYY-MM-DD"` (midnight UTC) — validated when the config loads, so a
typo is refused up front instead of failing the metric at alert time. Also a
field in the `dtk ui` Builder's alerting section.

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
pings. Discord and Google Chat mentions also ride in the top-level message
text (embed/card content never notifies): Discord maps
`all`/`everyone`/`channel` -> `@everyone`, `here` -> `@here`, and an already
`<@user_id>`/`<@&role_id>`-shaped value pings for real; Google Chat collapses
any broadcast keyword to the space-wide `<users/all>` and passes an already
`<users/USER_ID>`-shaped value through. On both, a bare name still renders but
does not ping. Teams mentions are always **plain text and never ping** (the
message posts under the flow's own identity, with no per-message entity to
attach a real mention to). ntfy has no mention concept — mentions render as
plain `@name` text inside the notification body.

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
Discord's embed title is clickable the same way; Teams and Google Chat each get
an `Open dashboard`-style button; ntfy uses it as the notification's tap target
(`click`) instead of an action button, so it's never duplicated as one. `links`
adds extra `label: url` entries alongside it. Both are also exposed to custom
templates — see `{dashboard_url}` / `{dashboard_line}` below.

## "How to read this alert" link

Every **default-rendered** alert (anomaly / recovery / no-data / error) on
**every** channel carries a `How to read this alert` link pointing non-operator
stakeholders to a plain-language interpretation guide. It defaults to the
official detectkit guide (`https://dtk.pipelab.dev/guides/reading-alerts/`) — no
config needed. Control it project-wide with `alert_help_url` in
`detectkit_project.yml` (tri-state, see `project.md`):

- **unset / null** → the official detectkit guide (default URL above)
- **a URL string** → your own runbook/wiki page instead
- **`false`** → hide the link entirely

Per-channel rendering (defaults only; the resolved help URL is rendered per channel as follows):

- **Slack / Mattermost / generic webhook** — a clickable `How to read this alert`
  label in the compact `Links` line (alongside `Dashboard` + any extra links),
  never a raw URL. Rendered in the platform's link syntax (Slack `<url|label>`,
  Mattermost/generic markdown links) so a long dashboard URL stays hidden behind
  its label.
- **Telegram** — appended to the links line (after the optional "Open dashboard"
  link) as an `<a>` link reading `How to read this alert`.
- **Email** — in the footer, after `Sent by detectkit · <project>` (and any CC),
  a clay-colored `How to read this alert ->` link.
- **Discord** — a clickable `How to read this alert` label in the embed
  description's compact `Links` line, alongside `Dashboard` and any extra
  links — never a raw URL.
- **Microsoft Teams** — an `Action.OpenUrl` button titled `How to read this
  alert`, alongside the Dashboard/extra-link buttons.
- **Google Chat** — its own action button in the card's button row, alongside
  Dashboard and any extra links.
- **ntfy** — one of the notification's `view` action buttons (up to three,
  shared with `links`; `dashboard_url` rides on `click` instead and never
  duplicates as a button).

Exposed to custom templates as `{help_url}` (raw URL, empty when unset/hidden)
and `{help_line}` (`How to read this alert: <url>\n`, empty when unset/hidden) —
mirrors `{dashboard_url}` / `{dashboard_line}`. See the template table below.

## How default messages render

With no custom `template`, each channel renders a structured, branded message
(alert-centric: the rule that fired leads, the anomaly value is evidence). The
shared value computation lives in one place,
so templates and native rendering stay consistent. Every alert title/headline
leads with a colored **status circle** — 🔴 anomaly, 🟢 recovery, 🟡 no-data,
🔵 pipeline error — so the status reads from color alone. It also leads with the
**project name** as a `[name] ` prefix (from `detectkit_project.yml`) — see
[Project label](#project-label-multi-project-channels) below.

- **Slack / Mattermost / generic webhook** — an alert renders as **one
  status-colored attachment** whose whole body is a single markdown `text` block,
  ordered **most-important-first** so a long alert folds its tail behind a
  **"Show more"** toggle — one block, one color, just like a reference
  AlertManager alert. The body order: the clickable title (the metric; links to
  `dashboard_url` when set), then the markdown lead (the duration sentence — see
  "Incident timing" below) with the **Rule** chip beneath it, **Value /
  Expected**, the compact **Links** line (dashboard + extra links + the "how to
  read this alert" guide as clickable labels, never raw URLs), and finally the
  verbose tail (Quorum / Severity / the anomalous span — Anomaly began → Latest
  reading; began → fired → recovered on recovery — / Detectors / Parameters).
  Both clients fold **only** the `text` (Slack above 700 chars / 5 line breaks;
  Mattermost above ~200px) and render the title, the color bar and the **footer**
  *outside* the fold — so the branded **footer + footer icon (the logo)** stays
  visible even when the body is collapsed. No-data / error stay short, single
  un-folded cards; a long anomaly (or a full recovery timeline) folds its tail.
  @mentions ride in the **top-level** message text so they notify. A custom
  `template` renders as a single plain text-only attachment (the raw template
  replaces the structured lead/Value/tail sections; color/title/branding kept).
- **Telegram** — default `parse_mode` is now **HTML**. The default message is
  structured and HTML-escaped: a colored status dot (red anomaly / green
  recovery / yellow no-data / blue error), a bold headline, the lead + rule, then
  evidence in `<code>` (value/expected/quorum/severity/began → latest/detector/
  params), an inline "Open dashboard" link, then mentions. This fixes the old
  Markdown mode raising "can't parse entities" on params JSON containing
  underscores (e.g. `window_size`). Custom templates are sent verbatim under the
  parse mode, so they must be HTML-safe; set `parse_mode: Markdown` to keep the
  old behavior.
- **Email** — a branded HTML card (inline-CSS, table-based, Outlook-safe):
  colored accent + status pill, the metric, the lead + Rule chip, a 2-col stat
  grid (value/expected/severity/quorum/anomaly began/latest reading; began/alert fired/recovered on recovery), a monospace params box,
  an optional "Open dashboard" button, and a footer. The plain-text body remains
  the multipart fallback.
- **Discord** — one **embed** (Discord embeds have no "Show more" fold, unlike
  Slack/Mattermost attachments): the clickable title, the lead + **Rule** chip,
  **Value/Expected** plus the compact **Links** line in the description, and
  the verbose tail (Quorum/Severity/anomalous span/Detectors) in an inline
  **field grid** instead of a folded block. Detector parameters (anomaly only)
  append as a fenced code block, dropped entirely (not truncated) if it would
  blow the description budget. No-data/error stay short (no fields).
  `@mentions` ride in the top-level `content`, never inside the embed. A
  custom `template` renders as a single plain embed (no fields).
- **Microsoft Teams** — an Adaptive Card posted via the Power Automate
  **Workflows** webhook (not the retired O365 connector): a colored title, the
  lead, a monospace `Rule: <value>` line, a `FactSet` mirroring the webhook
  tail for the kind, detector params (anomaly only), mentions, and a
  plain-text footer — plus `Action.OpenUrl` buttons for the
  dashboard/links/help. No brand avatar (the card posts under the flow's own
  identity/icon). A custom `template` renders a minimal 3-block card (colored
  title, template text, footer).
- **Google Chat** — a Cards v2 card (Cards v1 is deprecated): a header (title =
  the status-dot headline, since cards v2 has no color bar; subtitle = the
  brand name paired with the project; the brand avatar as a circle image),
  then the lead + a bold **Rule** label (plain text value, no code chip),
  evidence rows, and an action-button row. Mentions ride in the top-level
  `text` (card content never notifies). A custom `template` renders as one
  opaque text paragraph, header/branding unchanged.
- **ntfy** — a push notification, not a chat message (no bot identity/avatar/
  color bar): the title carries the status dot **stripped** (ntfy's own `tags`
  already render a leading emoji) and the body is the same plain-text content
  other channels send. `dashboard_url` becomes the notification's tap target
  (`click`); `links` plus the help link become up to three `view` action
  buttons. Priority defaults to 4 (high) for anomaly/error, 3 (default) for
  recovery/no-data — an explicit `priority` overrides only anomaly/error.

**Message order is uniform** — `description → Rule → Value/Expected` on every
channel, for both anomaly and recovery. The **firing rule is set apart
uniformly**: a bold **Rule** label + an inline-code chip (`min_detectors=… ·
direction=… · consecutive=…`) sitting right above the value/expected evidence.
Bold is platform-aware (`*Rule*` on Slack, `**Rule**` on Mattermost/generic/
Discord — all CommonMark/mrkdwn; `<b>Rule</b>` on Telegram; `<strong>` in
email), while the code chip is identical everywhere on those channels. Two of
the newer channels render the rule line differently rather than forcing their
format onto it: Google Chat uses `<b>Rule</b>` followed by plain escaped text
(no code tag — Cards v2's allowed HTML subset has `<code>`, but the renderer
doesn't reach for it here); Teams and ntfy render it as one unstyled `Rule:
<value>` line (Teams: a single `Monospace`-fontType `TextBlock`; ntfy: plain
text, since a push notification has no markup at all).

**Incident timing — "how long has this been going on".** Each default anomaly
leads with `Anomalous for 2h 30m — 15 consecutive 10min intervals.` (metric
interval + true streak length + wall-clock duration); the **Anomaly began /
Latest reading** fields bound the span. Labels are self-describing so the onset
isn't misread as the alert-fire moment: **Anomaly began** is the resolved onset,
**not** when the alert fired. Recovery shows the fuller **began → fired →
recovered** timeline (`Incident lasted …`), where **Alert fired** =
`onset + (consecutive_required − 1) × interval` (exposed as `{fired_display}`, omitted when the run is capped). The true
streak/onset is resolved only when an alert fires/clears (a bounded lookback over
the detection history; a run older than the window shows `over …`), so the hot
no-alert path stays cheap. Exposed to templates as `{anomaly_lead}` /
`{recovery_lead}` / `{duration_display}` / `{interval_display}` /
`{started_display}` / `{fired_display}` / `{window_line}` — and
`{consecutive_count}` now carries the *true* streak length. Custom templates and
the plain-text fallbacks follow the same order.

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
- **Discord** pairs it in the embed footer (`detectkit · payments`).
- **Microsoft Teams** has no avatar/username override at all (the Workflows
  identity owns those), so the project name rides only in the plain-text
  footer line (`detectkit · payments`).
- **Google Chat** pairs it in the card header subtitle (`detectkit · payments`).
- **ntfy** has no footer concept — the project name rides only in the title
  prefix (there is no separate branding surface to pair it with).

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
| `{synonyms}` / `{synonyms_line}` | alt names from `ai_context.synonyms` (opt-in; not in default templates — add `{synonyms_line}` for an "Also known as: …" line) |
| `{project_name}` / `{project_name_prefix}` | project label (`"[name] "` prefix, or `""`) |
| `{timestamp}`, `{timezone}` | when (display tz via `alerting.timezone`, default UTC) |
| `{value}` / `{value_display}` | metric value (`value_display` is NaN-safe) |
| `{confidence_lower}` / `{confidence_upper}` / `{confidence_interval}` | bounds |
| `{expected_range}` | one-sided-aware band (`>= 7.00`, `<= 1.10`, `[lo, hi]`, `N/A`) |
| `{detector_name}`, `{detector_count}` | who fired (`"N detectors"` for multi) |
| `{min_detectors}` / `{direction_policy}` / `{consecutive_required}` | the configured rule |
| `{rule_display}` | full rule chip (legacy `min_detectors=… · direction=… · consecutive=…`, or also naming `anomaly_window`/`min_anomaly_share` when configured — on recovery too, so fire and recovery name one rule) |
| `{window_points}` / `{window_matched}` | fraction-rule window size / matched count (empty unless configured / fired by it) |
| `{direction}`, `{severity}` | observed values |
| `{consecutive_count}` | **true** streak length (resolved at fire time, not capped at the rule) |
| `{anomaly_lead}` / `{recovery_lead}` | ready-made "how long" lead sentence |
| `{interval_display}` / `{duration_display}` / `{started_display}` / `{fired_display}` / `{window_line}` | incident-timing bits (interval, duration, onset, alert-fire moment, `Anomaly began… \| Latest reading…` line) |
| `{status}` | `ANOMALY` / `RECOVERED` / `NO_DATA` / `ERROR` |
| `{mentions}` / `{mentions_line}` | formatted mentions |
| `{dashboard_url}` | raw `dashboard_url` (empty string when unset) |
| `{dashboard_line}` | `Dashboard: <url>\n` when set, else empty (appended to default plain-text templates) |
| `{help_url}` | raw "How to read this alert" URL (empty when unset/hidden via `alert_help_url`) |
| `{help_line}` | `How to read this alert: <url>\n` when set, else empty (mirrors `{dashboard_line}`) |

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
