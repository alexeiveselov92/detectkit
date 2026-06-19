# Alert Channels

Channels are configured in `profiles.yml` and referenced by name in metric configs.

### Mattermost

```yaml
# In profiles.yml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
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
- `icon_emoji` (default: `":warning:"`) - Bot icon
- `channel` (optional) - Override webhook's default channel
- `timeout` (default: `10`) - HTTP timeout in seconds

### Slack

```yaml
# In profiles.yml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "#alerts"

# In metric config
alerting:
  channels:
    - slack_ops
```

Same parameters as Mattermost (Slack-compatible API).

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
- `smtp_username` (optional) - SMTP authentication username
- `smtp_password` (optional) - SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption

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
- `username` (default: `"detectk"`) - Bot display name
- `icon_emoji` (default: `":warning:"`) - Bot icon
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

