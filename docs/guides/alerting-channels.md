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
  anomaly/recovery renders as **two stacked attachments** so a long alert folds
  in the channel. Slack and Mattermost natively collapse only an attachment's
  text block behind a "Show more" toggle (Slack above 700 characters / 5 line
  breaks, Mattermost above ~200px of height) and never collapse the fields grid,
  so the message is split into:
  - an always-visible **base card** — a status-colored accent bar, a clickable
    title (the project + metric; links to `dashboard_url` when set), a short
    markdown lead — *how long it has been going on* ("Anomalous for 2h 30m — 15
    consecutive 10min intervals.") with the **Rule** chip right beneath it — and
    a compact fields grid kept to the essentials: **Value / Expected**, plus a
    compact always-visible **Links** field of clickable labels (Dashboard / any
    extra links / "How to read this alert" — never raw URLs);
  - a neutral, foldable **detail card** — the verbose tail as one markdown text
    block (Quorum / Severity / Anomaly began / Latest reading — began / alert
    fired / recovered on recovery — / Detectors / Parameters), which the chat
    client collapses behind "Show more" once it's long.

  No-data / error alerts are short, so they render as a single base card. The
  branded footer (`detectkit · <project>`) and footer icon ride on the **last**
  attachment (the bottom of the message). `@mentions` ride in the **top-level
  message text** (not the attachment) so Slack actually notifies. A custom
  `template` renders instead as a single plain text-only attachment (status
  color, title and branding kept, no fields grid, no fold split).
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

On both anomaly and recovery alerts the **firing rule is set apart the same way
in every channel**: a bold **Rule** label followed by an inline-code chip
(`min_detectors=… · direction=… · consecutive=…`), with the quorum explanation
on its own line — so the configured rule reads at a glance instead of running
into the surrounding prose. (Bold is rendered in each platform's native syntax;
the code chip looks the same everywhere.)

### Dashboard and runbook links

Two metric-level `alerting:` fields surface as first-class links on every
channel:

- `dashboard_url` — optional dashboard/runbook URL. Rendered as the clickable
  attachment title **and** a `Dashboard` label in the webhook `Links` field, an
  inline "Open dashboard" link on Telegram, and an "Open dashboard" button in
  email. On webhooks the URL is always hidden behind a clickable label (a real
  Grafana URL can be paragraph-long with all its variables), using each
  platform's link syntax — Slack `<url|label>`, Mattermost/generic markdown
  links. Also exposed to custom templates as `{dashboard_url}` (raw URL,
  empty string when unset) and `{dashboard_line}` (`Dashboard: <url>\n` when set,
  else empty — appended to the default plain-text templates).
- `links` — a `label: url` map of extra links shown as more clickable labels in
  the same webhook `Links` field (and alongside the other links on Telegram/email).

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
clickable label in the webhook `Links` field, on the Telegram links line (after
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
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` (optional) - Target channel (Slack/Mattermost)
- `timeout` (default: `10`) - HTTP timeout in seconds
- `extra_headers` (optional) - Additional HTTP headers for custom auth

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
