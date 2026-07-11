# Alert Channels

Channels are configured in `profiles.yml` and referenced by name in metric configs.

## Default message rendering

With no custom `template`, each channel renders a native, alert-centric layout:
the message leads with the rule that fired, and the anomaly value is supporting
evidence. The shared value computation (value, expected, severity, quorum,
detectors, parameters) is computed in one shared place, so templates
and native rendering read the same numbers. Every default title/headline/subject
also leads with the **project name** (`[name] `) — see
[Project label](#project-label-multi-project-channels).

- **Slack / Mattermost / generic webhook** (all webhook-based channels): an
  alert renders as **one status-colored attachment** — a single block with a
  single color (the left accent bar), whose long tail collapses behind a
  **"Show more"** toggle, exactly like an AlertManager alert. The whole body is
  one markdown text block, ordered **most-important-first** so the fold hides only
  the verbose tail:
  - a clickable **title** (the project + metric; links to `dashboard_url` when
    set), then a short markdown **lead** — *how long it has been going on*
    ("Anomalous for 2h 30m — 15 consecutive 10min intervals.") with the **Rule**
    chip right beneath it;
  - **Value / Expected**, then a compact **Links** line of clickable labels
    (Dashboard / any extra links / "How to read this alert" — never raw URLs);
  - the verbose tail — Quorum / Severity / Anomaly began / Latest reading (began
    / alert fired / recovered on recovery) / Detectors / Parameters — which the
    chat client folds behind "Show more" once the message is long.

  Slack and Mattermost natively collapse only an attachment's text block (Slack
  above 700 characters / 5 line breaks, Mattermost above ~200px of height) and
  render the title, the color bar and the footer **outside** that fold — so the
  branded footer (`detectkit · <project>`) and its **logo (footer icon)** stay
  visible even when the body is collapsed. No-data / error alerts stay short,
  single un-folded cards; a long anomaly (or a full recovery timeline) folds its
  tail. `@mentions` ride in the **top-level message text** (not the attachment)
  so Slack actually notifies. A custom `template` renders as a single plain
  text-only attachment (the raw template replaces the structured lead/Value/tail
  sections; status color, title and branding kept).
- **Telegram**: a structured, HTML-escaped message (default `parse_mode` is now
  `HTML`) — a colored status dot (red anomaly / green recovery / yellow no-data /
  blue error), a bold headline (`[project] Status · metric`), the lead (how long
  it has been going on) followed by the rule, then the evidence in `<code>`
  (value / expected / quorum / severity / began → latest / detector / params),
  a links line with an inline "Open dashboard" link followed by a "How to read
  this alert" link, then mentions. Custom templates are sent
  verbatim under the parse mode, so keep them HTML-safe (or set
  `parse_mode: Markdown`).
- **Email**: a branded HTML card (inline-CSS, table-based, Outlook-safe) — a
  colored accent and status pill, a small project eyebrow above the metric, the
  metric, the lead (how long it has been going on) with the **Rule** chip beneath
  it, a 2-column stat grid (value / expected / severity / quorum / anomaly began
  / latest reading; began / alert fired / recovered on recovery), a monospace
  params box, an optional "Open dashboard" button, and a
  footer (`Sent by detectkit · <project>`) that ends with a clay-colored "How to
  read this alert ->" link. The subject is prefixed with `[project]` and the
  plain-text body remains the multipart fallback.
- **Discord**: one **embed** per alert (Discord's own rich-message unit) — a
  clickable title, a CommonMark description with the lead + **Rule** chip,
  Value/Expected and the compact Links line, then a fenced `Parameters` block
  (anomaly only, dropped rather than truncated if it would blow the size
  budget). Discord embeds have **no "Show more" fold**, so the verbose tail
  (Quorum / Severity / the anomalous span / Detectors) rides in a compact
  **inline field grid** instead of collapsing. The branded footer (name + logo)
  stays on every embed; `@mentions` ride in the top-level message content
  (never inside the embed, where Discord never delivers a ping).
- **Microsoft Teams**: an Adaptive Card posted through the **Workflows** app
  (Power Automate), not the retired Office 365 connector — a colored title,
  the lead, a monospace **Rule** line, a `FactSet` mirroring the webhook
  tail, detector params (anomaly only), and `Action.OpenUrl` buttons for the
  dashboard/links/help. See the caveats in its own section below (flow
  identity, no branding; mentions render but don't ping).
- **Google Chat**: a Cards v2 card — a header (title = the status-dot
  headline, since Cards v2 has no color bar; subtitle = the brand + project
  name; the brand avatar as a circle image), the lead + a bold **Rule**
  label (plain text, not a code chip), evidence rows, then action buttons for
  the dashboard/links/help. A custom `template` keeps the header and renders
  as one opaque text paragraph.
- **ntfy**: a push notification (title + message + tags), published via
  ntfy's JSON endpoint — no bot identity/avatar/color-bar concept, so the
  kind's tag renders as the client's leading emoji instead of a brand mark.
  See its own section below for the priority mapping and action-button
  limits.

On both anomaly and recovery alerts the **firing rule is set apart the same way
in every channel**: a bold **Rule** label followed by the rule
(`min_detectors=… · direction=… · consecutive=…`), with the quorum explanation
on its own line — so the configured rule reads at a glance instead of running
into the surrounding prose. (Bold is rendered in each platform's native syntax.
Most channels — Slack/Mattermost/webhook, Telegram, email, Discord — style the
rule itself as an inline-code chip too; Google Chat renders it as plain bold
label + plain text (no code styling), Teams as a single monospace text block,
and ntfy as plain text — a push notification has no markup at all.)

### Dashboard and runbook links

Two metric-level `alerting:` fields surface as first-class links on every
channel:

- `dashboard_url` — optional dashboard/runbook URL. Rendered as the clickable
  attachment title **and** a `Dashboard` label in the webhook `Links` line, an
  inline "Open dashboard" link on Telegram, and an "Open dashboard" button in
  email. On webhooks the URL is always hidden behind a clickable label (a real
  Grafana URL can be paragraph-long with all its variables), using each
  platform's link syntax — Slack `<url|label>`, Mattermost/generic markdown
  links. Also exposed to custom templates as `{dashboard_url}` (raw URL,
  empty string when unset) and `{dashboard_line}` (`Dashboard: <url>\n` when set,
  else empty — appended to the default plain-text templates).
- `links` — a `label: url` map of extra links shown as more clickable labels in
  the same webhook `Links` line (and alongside the other links on Telegram/email).

```yaml
# In metric config
alerting:
  channels:
    - mattermost_ops
  dashboard_url: https://grafana.ops/d/api-errors
  links:
    Runbook: https://runbooks.ops/api-errors
    Grafana: https://grafana.ops/d/api-errors
```

### "How to read this alert" link

Every default-rendered alert (anomaly, recovery, no-data, error) on every channel
also carries a **stakeholder-facing "How to read this alert" link** — a
plain-language pointer for non-operators who see the alert but don't run the
pipeline. By default it links to the official detectkit guide,
[Reading alerts](reading-alerts.md)
(`https://dtk.pipelab.dev/guides/reading-alerts/`). It renders per channel as a
clickable label in the webhook `Links` line, on the Telegram links line (after
"Open dashboard"), and in the email footer.

The link is controlled project-wide by the `alert_help_url` field in
`detectkit_project.yml` (tri-state: unset → the official guide, a URL string →
your own runbook/wiki page, `false` → hide the link entirely). See
[Configuration → `alert_help_url`](configuration.md#alert_help_url-string--bool-optional).

It is also exposed to custom templates as `{help_url}` (raw URL, empty string
when unset) and `{help_line}` (`How to read this alert: <url>\n` when set, else
empty — appended to the default plain-text templates), mirroring `{dashboard_url}`
/ `{dashboard_line}`.

## Bot identity (name & avatar)

By default the alert bot uses the **detectkit brand** — the display name
`detectkit` and the brand avatar. On Slack, Mattermost and generic webhooks the
avatar is sent as an `icon_url` (a hosted PNG). Override it per channel:

- `username` — change the display name.
- `icon_url` — use your own avatar image (a public PNG/JPG URL).
- `icon_emoji` — use an emoji instead of an avatar image.

`icon_url` takes precedence over `icon_emoji`; setting either one opts out of
the brand avatar. Telegram and email brand differently — see their sections.

Discord follows the same pattern with its own field names — `username` /
`avatar_url` (no `icon_emoji` equivalent; Discord embeds only take an image
URL). Google Chat has a single `icon_url` knob (no display-name override —
the subtitle always reads `detectkit`, or `detectkit · <project>`). Teams and
ntfy have **no** bot identity knob at all: Teams posts under the Workflow's
own identity/icon, and ntfy has no avatar concept — see each channel's own
section for what still distinguishes the alert (a plain-text footer for
Teams, the tag emoji for ntfy).

## Project label (multi-project channels)

Because the bot keeps the brand name + avatar by default, two detectkit projects
pointed at the **same** channel would otherwise look identical. To keep them
distinct without overriding the brand, detectkit stamps the project name
(`detectkit_project.yml` → `name`) onto every alert and shows it by default — no
extra config:

- The **title / headline / subject** leads with `[name] ` on every alert kind
  (anomaly, recovery, no-data, error): `🔴 [payments] Alert: api_error_rate`.
- **Slack / Mattermost / webhook** also pair it in the footer (`detectkit · payments`).
- **Telegram** carries it in the bold headline (it has no footer or per-message avatar).
- **Email** prefixes the subject, adds a project eyebrow above the metric, and
  pairs it in the footer.
- **Discord** pairs it in the embed footer (`detectkit · payments`), same as
  the webhook family.
- **Microsoft Teams** pairs it in the card's plain-text footer line — the only
  branding available on that path (see the Teams caveats below).
- **Google Chat** pairs it in the card header's subtitle
  (`detectkit · payments`).
- **ntfy** carries it in the title, same as every other kind's
  `{project_name_prefix}`; there's no footer to pair it in separately.

It is also exposed to custom templates as `{project_name}` and
`{project_name_prefix}` (`"[name] "` when set, else `""`). The `name` is
informational only (it keys no `_dtk_*` table), so you can rename it freely —
spaces are allowed for a prettier label like `name: "Payments API"`. Direct
library/API callers that don't pass a project name render unchanged.

### Mattermost

```yaml
# In profiles.yml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    # Bot identity is optional — defaults to the detectkit brand name + avatar.
    # username: "detectkit"             # override the display name
    # icon_url: "https://.../bot.png"   # override the avatar image
    # icon_emoji: ":warning:"           # or use an emoji instead of an avatar
    channel: "alerts"          # Explicit channel override
    timeout: 10

# In metric config
alerting:
  channels:
    - mattermost_ops
```

**Parameters**:
- `webhook_url` (required) - Mattermost incoming webhook URL
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` (optional) - Override webhook's default channel
- `timeout` (default: `10`) - HTTP timeout in seconds

### Slack

```yaml
# In profiles.yml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    channel: "#alerts"
    # Bot identity defaults to the detectkit brand (override with
    # username / icon_url / icon_emoji — see "Bot identity" above).

# In metric config
alerting:
  channels:
    - slack_ops
```

Same parameters as Mattermost (Slack-compatible API).

> Slack note: for the bot avatar to apply, the incoming webhook's app must allow
> customizing the username and icon. If your workspace pins the app's identity,
> the avatar falls back to the app's configured icon.

### Telegram

```yaml
# In profiles.yml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"

# In metric config
alerting:
  channels:
    - telegram_alerts
```

**Parameters**:
- `bot_token` (required) - Telegram bot API token
- `chat_id` (required) - Target chat/channel ID

**Setup**:
1. Create bot with @BotFather
2. Get bot token
3. Add bot to channel
4. Get chat ID (use @userinfobot)

> **Default formatting (Telegram):** the default `parse_mode` is now `HTML`. The
> built-in message is structured and HTML-escaped (status dot, headline, rule,
> evidence in `<code>`, optional "Open dashboard" link), which avoids the
> "can't parse entities" error the old Markdown default raised on params JSON
> containing underscores (e.g. `window_size`). Custom templates are sent
> verbatim, so keep them HTML-safe — or set `parse_mode: Markdown` to restore
> the previous behavior.

> **Bot avatar (Telegram):** Telegram bots show the avatar set on the bot
> account itself, not a per-message icon — so detectkit can't override it like
> it does for Slack/Mattermost. To brand it, set the bot's picture in @BotFather
> (`/setuserpic`). You can reuse the detectkit brand avatar from
> `https://dtk.pipelab.dev/bot-icon.png`.

### Email

```yaml
# In profiles.yml
alert_channels:
  email_ops:
    type: email
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_username: "your_email@gmail.com"
    smtp_password: "your_app_password"
    from_email: "alerts@example.com"
    from_name: "detectkit"        # display name in the From header (optional)
    to_emails:
      - "ops@example.com"
      - "devops@example.com"
    use_tls: true

# In metric config
alerting:
  channels:
    - email_ops
```

**Parameters**:
- `smtp_host` (required) - SMTP server hostname
- `smtp_port` (required) - SMTP port (587 for TLS, 465 for SSL)
- `from_email` (required) - Sender email
- `to_emails` (required) - List of recipients
- `from_name` (default: `"detectkit"`) - Sender display name in the `From`
  header (the email equivalent of the bot name)
- `smtp_username` (optional) - SMTP authentication username
- `smtp_password` (optional) - SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption

> **Branding (email):** the sender shows as `detectkit <from_email>` and the
> message is sent as multipart text + HTML, with the brand logo in the HTML
> header (the plain-text body stays the fallback). The avatar a mail client
> shows next to the sender is controlled by the sending domain (e.g. BIMI), not
> by the message — so brand it via `from_name` and your domain's avatar setup.

### Discord

```yaml
# In profiles.yml
alert_channels:
  discord_ops:
    type: discord
    webhook_url: "${DISCORD_WEBHOOK}"
    # Bot identity is optional — defaults to the detectkit brand name + avatar.
    # username: "detectkit"
    # avatar_url: "https://.../bot.png"
    timeout: 10

# In metric config
alerting:
  channels:
    - discord_ops
```

**Parameters**:
- `webhook_url` (required) - Discord incoming-webhook URL
  (`https://discord.com/api/webhooks/<id>/<token>`)
- `username` (default: `"detectkit"`) - Bot display name
- `avatar_url` (default: detectkit brand avatar) - Bot avatar image URL
- `timeout` (default: `10`) - HTTP timeout in seconds

**Default rendering**: one **embed** per alert — a clickable title (links to
`dashboard_url` when set), a CommonMark description (the lead + **Rule** chip,
then Value/Expected and the compact Links line), a fenced code block titled
"Parameters" on anomaly alerts (dropped entirely, never truncated mid-JSON, if
it would push the description past Discord's size budget), and the branded
footer + logo. A custom `template` renders as a single plain embed (color,
title, footer, timestamp kept; no field grid).

> **Bare `@name` doesn't ping (Discord).** A plain username in `mentions:`
> (e.g. `oncall_engineer`) renders as visible text but does **not** actually
> notify — Discord only delivers a ping for a real mention token. Put the
> literal `<@user_id>` (user) or `<@&role_id>` (role) form directly in
> `mentions:` for a real ping; the broadcast keywords `all`/`everyone`/`channel`
> → `@everyone` and `here` → `@here` **do** ping (paired with an
> `allowed_mentions` object). Mentions ride in the top-level message content —
> Discord never delivers a ping placed inside an embed.

> **No "Show more" fold (Discord).** Unlike Slack/Mattermost attachments,
> Discord embeds don't collapse long text behind a fold. So the verbose
> evidence that those channels hide (Quorum / Severity / the anomalous span /
> Detectors) rides instead in a compact **inline field grid** below the
> description — everything is visible at once on anomaly/recovery alerts;
> no-data and error stay short with no field grid.

### Microsoft Teams

```yaml
# In profiles.yml
alert_channels:
  teams_ops:
    type: teams
    webhook_url: "${TEAMS_WEBHOOK_URL}"
    timeout: 10

# In metric config
alerting:
  channels:
    - teams_ops
```

**Parameters**:
- `webhook_url` (required) - the **Workflows** app's webhook-trigger URL
  (Teams channel → **Workflows** → "When a Teams webhook request is
  received"). This is deliberately *not* the legacy Office 365 connector
  webhook, which Microsoft is retiring — that URL accepts a different payload
  shape and will not work here.
- `timeout` (default: `10`) - HTTP timeout in seconds

**Default rendering**: an Adaptive Card — a colored title (`Attention` red for
anomaly, `Good` green for recovery, `Warning` amber for no-data, `Accent` blue
for error), the lead sentence, a monospace **Rule** line, a `FactSet`
mirroring the other channels' verbose tail (Quorum/Severity/the anomalous
span/Detectors, or the recovery timeline), detector params on anomaly alerts,
and `Action.OpenUrl` buttons for the dashboard, extra links, and the help
link. A custom `template` renders a minimal card (colored title + the
rendered template text + footer; action buttons still attached).

> **Flow identity, no branding (Teams).** The message posts under the
> **Workflow's own identity and icon** — there is no per-message `username` /
> avatar override on this path, unlike the Slack/Mattermost-style webhook
> channels. The card's footer still names `detectkit` (and the project, when
> set) as plain text so two projects sharing one channel stay distinguishable,
> but there is no bot avatar to brand; rename the Workflow itself in Power
> Automate if you want a different sender name.

> **Mentions render but don't ping (Teams).** `@mentions` render as a plain,
> subtle text line on the card — a real Adaptive Card mention needs an Azure
> AD user object id, which detectkit's alert config doesn't carry. Configure
> an actual ping inside the Workflow itself if you need one.

### Google Chat

```yaml
# In profiles.yml
alert_channels:
  googlechat_ops:
    type: googlechat
    webhook_url: "${GOOGLE_CHAT_WEBHOOK_URL}"
    # icon_url: "https://.../bot.png"   # optional — defaults to the detectkit brand avatar
    timeout: 10

# In metric config
alerting:
  channels:
    - googlechat_ops
```

**Parameters**:
- `webhook_url` (required) - the space's full incoming-webhook URL (already
  carrying the `key`/`token` query params Google Chat issues when the webhook
  is registered)
- `icon_url` (default: detectkit brand avatar) - header avatar image URL
- `timeout` (default: `10`) - HTTP timeout in seconds

**Default rendering**: a Cards v2 card — a header (title = the status-dot
headline, since Cards v2 has no color bar so the emoji dot is the only color
cue; subtitle = `detectkit`, or `detectkit · <project>`; the brand avatar as a
circle image), the lead sentence followed by a bold **Rule** label and the
rule as plain text (Cards v2's HTML subset has a `<code>` tag, but this
channel doesn't reach for it — unlike the code-styled chip on the webhook
family/Telegram/email/Discord), evidence rows (value / expected / quorum /
severity / the anomalous span / detectors, trimmed for no-data/error), and a
row of action buttons for the dashboard, extra links, and the help link. A
custom `template` keeps the header and renders as a single opaque text
paragraph.

> **Only `<users/all>` actually pings (Google Chat).** Google Chat only
> triggers a notification — and pings mentioned users — from a
> `<users/USER_ID>` (or the space-wide `<users/all>`) token in the message's
> **top-level text**, never from card content. So `all`/`everyone`/`channel`/
> `here` (Chat has no separate "here" vs "channel" concept) all collapse to
> one deduped, space-wide `<users/all>` mention; anything else falls back to a
> plain, non-pinging `@name`. Mentions are added to the top-level `text` field
> only when `mentions:` is non-empty — a card with no mentions carries no
> top-level `text` and triggers no notification banner.

### ntfy

```yaml
# In profiles.yml
alert_channels:
  ntfy_ops:
    type: ntfy
    topic: "my-alerts"
    # server: "https://ntfy.sh"     # default; self-hosted servers work the same way
    # token: "${NTFY_TOKEN}"        # access token -> Authorization: Bearer
    # user: "${NTFY_USER}"          # basic auth, used only when token is unset
    # password: "${NTFY_PASSWORD}"
    # priority: 5                   # overrides the anomaly/error priority only
    timeout: 10

# In metric config
alerting:
  channels:
    - ntfy_ops
```

**Parameters**:
- `topic` (required) - ntfy topic to publish to
- `server` (default: `"https://ntfy.sh"`) - ntfy server base URL; a
  self-hosted server works the same way
- `token` (optional) - ntfy access token, sent as `Authorization: Bearer
  <token>`; wins over `user`/`password` when both are set
- `user` / `password` (optional) - HTTP basic auth, used only when `token` is
  unset
- `priority` (optional, `1`-`5`) - overrides the **anomaly/error** notification
  priority only (default `4`, high); a recovery or no-data notice always
  publishes at `3` (default) regardless of this setting — a deliberate choice
  so "all clear" / "still waiting on data" notices stay calm even when you
  want urgent anomalies to buzz the phone
- `timeout` (default: `10`) - HTTP timeout in seconds

**Default rendering**: a push notification — title + message body, published
via ntfy's JSON endpoint (not the header-based publish form, since HTTP
headers can't reliably carry non-ASCII titles/params). `dashboard_url` becomes
the notification's tap target (`click`); `links` plus the "how to read this
alert" link become up to **3** `view` action buttons — `dashboard_url` is
deliberately excluded from the action list since it already rides on `click`.

> **Tag emoji leads the title (ntfy).** ntfy has no bot avatar or color-bar
> concept — a push notification is just title + body + tags. detectkit maps
> each kind to an ntfy tag (`rotating_light` anomaly, `white_check_mark`
> recovery, `warning` no-data, `large_blue_circle` error), which ntfy clients
> render as a **leading emoji** on the notification. Because that would
> duplicate the status-dot emoji every other channel's title starts with,
> detectkit strips it from the ntfy title — the tag is the only status glyph
> shown.

> **Message byte cap.** ntfy's own per-message limit is ~4096 bytes; past it,
> ntfy silently converts the message into a file attachment instead of a
> plain notification. detectkit caps the message body at ~3800 UTF-8 bytes
> (truncated on a character boundary, with a trailing `…`) to stay comfortably
> under that.

### Generic Webhook

For any endpoint that accepts a Mattermost/Slack-compatible JSON payload —
use `extra_headers` to add custom authentication (e.g. an `Authorization`
header):

```yaml
# In profiles.yml
alert_channels:
  custom_webhook:
    type: webhook
    webhook_url: "https://custom.example.com/webhook"
    extra_headers:
      Authorization: "Bearer your_token"

# In metric config
alerting:
  channels:
    - custom_webhook
```

**Parameters**:
- `webhook_url` (required) - Target webhook URL
- `format` (default: `"attachments"`) - Payload shape: `attachments`, `json`,
  or `alertmanager` — see [Webhook payload formats](#webhook-payload-formats)
- `secret` (optional) - HMAC signing secret (env-interpolatable) — see
  [Request signing](#request-signing-secret)
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` (optional) - Target channel (Slack/Mattermost)
- `timeout` (default: `10`) - HTTP timeout in seconds
- `extra_headers` (optional) - Additional HTTP headers for custom auth

#### Webhook payload formats

`format` is **generic `type: webhook` only** — Slack and Mattermost channels
always send the attachments payload described at the top of this page,
regardless of this setting.

**`attachments`** (default) — today's Mattermost/Slack-compatible attachment
payload, unchanged.

**`json`** — a flat, stable, machine-readable payload for receivers that speak
their own wire protocol instead of Slack's. Formats `json` and `alertmanager`
both ignore a custom `template` (there's no text to template) and send an
`X-Detectkit-Event: anomaly|recovery|no_data|error` header alongside the body:

```yaml
alert_channels:
  ingestor:
    type: webhook
    webhook_url: "https://ingest.example.com/detectkit"
    format: json
    secret: "{{ env_var('DETECTKIT_WEBHOOK_SECRET') }}"
```

Example payload (an anomaly alert):

```json
{
  "schema_version": 1,
  "source": "detectkit",
  "kind": "anomaly",
  "status": "firing",
  "project": "my_project",
  "metric": "checkout_errors",
  "description": "Checkout error rate",
  "timestamp": "2026-07-11T10:30:00Z",
  "value": 42.5,
  "expected": { "lower": 10.0, "upper": 30.0 },
  "severity": 4.2,
  "direction": "up",
  "detector": {
    "name": "mad",
    "params": { "threshold": 3.0, "window_size": 100 }
  },
  "rule": {
    "min_detectors": 1,
    "direction": "any",
    "consecutive": 3,
    "window_points": null,
    "min_anomaly_share": null,
    "fired_by_share": false,
    "display": "min_detectors=1 · direction=any · consecutive=3"
  },
  "quorum": { "detector_count": 1, "min_detectors": 1 },
  "incident": {
    "onset": "2026-07-11T10:00:00Z",
    "streak": 3,
    "capped": false,
    "interval_seconds": 600,
    "duration_seconds": 1800
  },
  "links": {
    "dashboard": "https://grafana.example.com/d/abc",
    "help": "https://dtk.pipelab.dev/guides/reading-alerts/",
    "extra": {}
  },
  "mentions": [],
  "synonyms": [],
  "error": null,
  "display": {
    "title": "...",
    "lead": "...",
    "value": "42.50",
    "expected_range": "[10.00, 30.00]",
    "timestamp": "2026-07-11 10:30:00 (UTC)"
  }
}
```

- `kind: "recovery"` → `status: "resolved"`.
- `kind: "no_data"` / `"error"` → `status: "firing"` with `value`/`expected`
  both `null` (there's no anomaly value); an `error` kind also fills `error`
  as `{"type": "...", "message": "..."}` instead of `null`.
- `synonyms` mirrors the metric's OSI `ai_context.synonyms`, empty when unset.
- `display` carries the same rendered strings the other channels show, for a
  receiver that wants to log or forward something human-readable without
  reimplementing the formatting.

**`alertmanager`** — the [Prometheus Alertmanager webhook-receiver
payload](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
(version `"4"`), so any tool that already ingests Alertmanager webhooks (a
different on-call router, a NOC dashboard, a custom receiver) can take
detectkit alerts with no new integration:

```yaml
alert_channels:
  alertmanager_bridge:
    type: webhook
    webhook_url: "https://oncall.example.com/webhook/detectkit"
    format: alertmanager
```

```json
{
  "version": "4",
  "groupKey": "detectkit/my_project/checkout_errors",
  "truncatedAlerts": 0,
  "status": "firing",
  "receiver": "detectkit",
  "groupLabels": { "alertname": "checkout_errors" },
  "commonLabels": {
    "alertname": "checkout_errors",
    "metric": "checkout_errors",
    "kind": "anomaly",
    "severity": "critical",
    "source": "detectkit",
    "project": "my_project"
  },
  "commonAnnotations": {
    "summary": "...",
    "description": "...",
    "value": "42.50",
    "expected": "[10.00, 30.00]",
    "direction": "up"
  },
  "externalURL": "",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "checkout_errors",
        "metric": "checkout_errors",
        "kind": "anomaly",
        "severity": "critical",
        "source": "detectkit",
        "project": "my_project"
      },
      "annotations": {
        "summary": "...",
        "description": "...",
        "value": "42.50",
        "expected": "[10.00, 30.00]",
        "direction": "up"
      },
      "startsAt": "2026-07-11T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "https://grafana.example.com/d/abc",
      "fingerprint": "..."
    }
  ]
}
```

`severity` label is `critical` for `anomaly`/`error`, `warning` for `no_data`.
The anomaly `direction` is deliberately an **annotation**, not a label — a
recovery reports no direction, and a direction label would change the label
set (and the `fingerprint`) between the trigger and the resolve.
A **recovery** sends `status: "resolved"` reusing the **same** `labels` and
`fingerprint` as the anomaly it resolves (`kind` stays `"anomaly"`) with
`endsAt` set — so Alertmanager-style receivers pair the trigger and the
resolve into one incident. No-data alerts don't have a matching resolution,
so they never auto-resolve.

#### Request signing (`secret`)

Set `secret` (a plain string or an env-interpolated one) to sign every
request, regardless of `format`, with a GitHub-style HMAC header:

```
X-Detectkit-Signature-256: sha256=<hex HMAC-SHA256 of the raw request body, key = secret>
```

Verify it on the receiving end before trusting the payload:

```python
import hashlib
import hmac

def verify_detectkit_signature(secret: str, body: bytes, header_value: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)
```

Compute the HMAC over the **raw** request body (bytes, before any JSON
re-parsing) — re-serializing the payload can reorder keys or change
whitespace and break the signature.

#### Rocket.Chat

Rocket.Chat isn't a dedicated channel type — route it through the **generic
webhook** channel (`type: webhook`, default `format: attachments`) pointed at
a Rocket.Chat **incoming webhook** integration. Rocket.Chat's script-less
incoming webhooks accept requests through the same endpoint as its
`chat.postMessage` API, whose payload schema is close enough to Slack's
attachments format (`color` / `title` / `title_link` / `text` / `fields`) that
the default `attachments` rendering lands correctly:

```yaml
# In profiles.yml
alert_channels:
  rocketchat_ops:
    type: webhook
    webhook_url: "https://rocketchat.example.com/hooks/<integrationId>/<token>"
    # format defaults to "attachments" — Rocket.Chat's incoming-webhook
    # payload schema accepts the same color/title/text/fields shape.

# In metric config
alerting:
  channels:
    - rocketchat_ops
```

Two things to know before relying on it:

- **`username` / `icon_url` / `icon_emoji` don't do anything on Rocket.Chat.**
  Its own field names for a per-message sender override are `alias` / `avatar`
  / `emoji`, not detectkit's Slack-shaped `username` / `icon_url` /
  `icon_emoji` — Rocket.Chat ignores the fields it doesn't recognize, so the
  brand name/avatar knobs are silently no-ops there. Brand the bot instead on
  the integration itself, via the **Alias** / **Avatar URL** / **Emoji**
  fields in Rocket.Chat's incoming-webhook settings (Manage → Workspace →
  Integrations → your webhook) — those apply to every message the
  integration posts. Rocket.Chat's attachment schema also has no `footer` /
  `footer_icon` field, so the branded footer + logo detectkit appends to the
  attachment is dropped; the alert still renders in full (title, color bar,
  body, fields) — just without that watermark.
- **A message needs a top-level `text` to reliably post.** detectkit's
  `attachments` payload only sets a top-level `text` field when `mentions:` is
  configured (it rides the `@mention` string) — otherwise the request is
  `username` + `attachments` only. Rocket.Chat's own webhook examples always
  pair a top-level `text` with `attachments`, so an alert config with no
  `mentions` is worth verifying with `dtk test-alert` before you rely on it;
  if messages don't show up, add at least one entry to `mentions` (e.g.
  `mentions: ["@here"]`) to guarantee a top-level `text`.

If you want the destination channel to be overridable per-request via the
payload's `channel` field, enable "Allow to overwrite destination channel in
the body parameters" on the Rocket.Chat integration — otherwise every message
posts to whatever channel the webhook is configured for, and detectkit's
optional `channel` param has no effect.

### Multiple Channels

Send alerts to multiple channels within a single config:

```yaml
alerting:
  enabled: true
  channels:
    - mattermost_ops       # Team chat
    - slack_critical       # Escalation channel
    - email_oncall         # On-call engineer
```

All channels receive the same alert message.
