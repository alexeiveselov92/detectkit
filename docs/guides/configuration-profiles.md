# Profiles Configuration

File: `profiles.yml`

### Basic Structure

```yaml
# Default profile to use
default_profile: prod

# Database profiles
profiles:
  prod:
    type: clickhouse
    host: localhost
    port: 9000
    # ... database-specific settings

# Alert channels
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    # ... channel-specific settings
```

### Database Profiles

> **Only ClickHouse is implemented today.** PostgreSQL and MySQL profiles
> validate at config load, but `create_manager()` raises
> `NotImplementedError("... coming soon")` for them
> (`detectkit/config/profile.py:152,154`). ClickHouse is the only supported
> backend for running the pipeline.

#### ClickHouse Profile

```yaml
profiles:
  prod:
    type: clickhouse
    host: clickhouse.example.com
    port: 9000
    user: default
    password: "your_password"

    # Internal tables location (for _dtk_* tables)
    internal_database: analytics

    # Data tables location (for your metrics)
    data_database: default

    # ClickHouse-specific settings
    settings:
      max_execution_time: 600
      max_memory_usage: 10000000000
```

**Required fields**:
- `type`: Must be `"clickhouse"`
- `host`: ClickHouse server hostname
- `port`: ClickHouse native protocol port (default: 9000)
- `internal_database`: Database for _dtk_* tables
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Dict of ClickHouse settings to apply

#### PostgreSQL Profile

> **Not yet implemented.** This profile shape is accepted by the config
> loader, but running it raises `NotImplementedError("PostgreSQL support
> coming soon")`. Use ClickHouse for now.

```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: "your_password"

    # Schema locations
    internal_schema: detectkit  # For _dtk_* tables
    data_schema: public         # For data queries
```

**Required fields**:
- `type`: Must be `"postgres"`
- `host`: PostgreSQL server hostname
- `port`: PostgreSQL port (default: 5432)
- `internal_schema`: Schema for _dtk_* tables
- `data_schema`: Schema for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Dict of database-specific settings

#### MySQL Profile

> **Not yet implemented.** This profile shape is accepted by the config
> loader, but running it raises `NotImplementedError("MySQL support coming
> soon")`. Use ClickHouse for now.

```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: "your_password"

    # Database locations
    internal_database: detectkit
    data_database: analytics
```

**Required fields**:
- `type`: Must be `"mysql"`
- `host`: MySQL server hostname
- `port`: MySQL port (default: 3306)
- `internal_database`: Database for _dtk_* tables
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Dict of database-specific settings

### Alert Channels

#### Mattermost Channel

```yaml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "alerts"          # Explicit channel name
    timeout: 10                 # Request timeout (seconds)
```

**Required fields**:
- `type`: Must be `"mattermost"`
- `webhook_url`: Mattermost incoming webhook URL

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `icon_emoji` (default: `":warning:"`) - Bot icon
- `channel` - Override webhook's default channel
- `timeout` (default: `10`) - HTTP request timeout

#### Slack Channel

```yaml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    username: "detectkit"
    icon_emoji: ":warning:"
    channel: "#alerts"          # Explicit channel
```

Same fields as Mattermost (Slack-compatible webhook API).

#### Telegram Channel

```yaml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"
    parse_mode: "Markdown"      # "Markdown", "HTML", or null (default: "Markdown")
    disable_notification: false # Send silently without notification (default: false)
```

**Required fields**:
- `type`: Must be `"telegram"`
- `bot_token`: Telegram bot API token
- `chat_id`: Target chat/channel ID

**Optional fields**:
- `parse_mode` (default: `"Markdown"`) - Message formatting: `"Markdown"`, `"HTML"`, or `null`
- `disable_notification` (default: `false`) - Send the message silently, without a notification sound

#### Email Channel

```yaml
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
```

**Required fields**:
- `type`: Must be `"email"`
- `smtp_host`: SMTP server hostname
- `smtp_port`: SMTP server port
- `from_email`: Sender email address
- `to_emails`: List of recipient email addresses

**Optional fields**:
- `smtp_username`: SMTP authentication username (the channel only logs in when both `smtp_username` and `smtp_password` are set)
- `smtp_password`: SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption
- `subject_template` (default: `"⚠ Alert: {metric_name}"`) - Email subject, supports `{metric_name}`
- `template`: Custom message body template (falls back to the built-in default)

#### Generic Webhook Channel

Sends alerts to any endpoint that accepts a JSON payload (Mattermost/Slack
attachments format). Use this for custom webhook receivers or when you need
extra HTTP headers (e.g., bearer auth).

```yaml
alert_channels:
  custom_hook:
    type: webhook
    webhook_url: "https://custom.example.com/webhook"
    username: "detectk"           # Bot display name (default: "detectk")
    icon_emoji: ":warning:"       # Bot icon (default: ":warning:")
    channel: "#alerts"            # Target channel (optional, Slack/Mattermost)
    timeout: 10                    # Request timeout in seconds (default: 10)
    extra_headers:                 # Additional HTTP headers (optional)
      Authorization: "Bearer token"
```

**Required fields**:
- `type`: Must be `"webhook"`
- `webhook_url`: Endpoint URL to POST the JSON payload to

**Optional fields**:
- `username` (default: `"detectk"`) - Bot display name
- `icon_emoji` (default: `":warning:"`) - Bot icon
- `channel` - Override the receiver's default channel
- `timeout` (default: `10`) - HTTP request timeout
- `extra_headers`: Dict of additional HTTP headers to send

