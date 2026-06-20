# Alert Channels

Channels are configured in `profiles.yml` and referenced by name in metric configs.

## Bot identity (name & avatar)

By default the alert bot uses the **detectkit brand** — the display name
`detectkit` and the brand avatar. On Slack, Mattermost and generic webhooks the
avatar is sent as an `icon_url` (a hosted PNG). Override it per channel:

- `username` — change the display name.
- `icon_url` — use your own avatar image (a public PNG/JPG URL).
- `icon_emoji` — use an emoji instead of an avatar image.

`icon_url` takes precedence over `icon_emoji`; setting either one opts out of
the brand avatar. Telegram and email brand differently — see their sections.

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

