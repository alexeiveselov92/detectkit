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

ClickHouse, PostgreSQL and MySQL are all fully supported. The connection fields
differ per backend (ClickHouse/MySQL use **databases**; PostgreSQL connects to a
`database` and uses **schemas**). See the per-backend
[Databases guide](databases.md) for a focused walkthrough of each.

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

PostgreSQL connects to a `database` and stores tables in **schemas** inside it.
The `database` must already exist; detectkit creates the schemas.

```yaml
profiles:
  prod:
    type: postgres
    host: localhost
    port: 5432
    user: postgres
    password: "your_password"

    database: detectkit         # database to connect to (must already exist)
    internal_schema: detectkit  # schema for _dtk_* tables (auto-created)
    data_schema: public         # schema for your data queries
```

**Required fields**:
- `type`: Must be `"postgres"`
- `host`: PostgreSQL server hostname
- `port`: PostgreSQL port (default: 5432)
- `database`: Database to connect to (must already exist)
- `internal_schema`: Schema for _dtk_* tables (detectkit creates it)
- `data_schema`: Schema for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `settings`: Extra `psycopg2.connect` keyword arguments

#### MySQL Profile

MySQL (8.0+) uses **databases** (no separate schema concept).

```yaml
profiles:
  prod:
    type: mysql
    host: localhost
    port: 3306
    user: root
    password: "your_password"

    # Database locations (auto-created)
    internal_database: detectkit
    data_database: analytics
```

**Required fields**:
- `type`: Must be `"mysql"`
- `host`: MySQL server hostname
- `port`: MySQL port (default: 3306)
- `internal_database`: Database for _dtk_* tables (detectkit creates it)
- `data_database`: Database for data queries

**Optional fields**:
- `user`: Username (default: `"default"`)
- `password`: Password (default: empty string)
- `database`: Optional default database for the connection
- `settings`: Extra `pymysql.connect` keyword arguments

### Alert Channels

#### Mattermost Channel

```yaml
alert_channels:
  mattermost_ops:
    type: mattermost
    webhook_url: "https://mattermost.example.com/hooks/xxx"
    channel: "alerts"          # Explicit channel name
    timeout: 10                 # Request timeout (seconds)
    # Bot name + avatar default to the detectkit brand (override below).
    # username: "detectkit"
    # icon_url: "https://.../bot.png"   # or icon_emoji: ":warning:"
```

**Required fields**:
- `type`: Must be `"mattermost"`
- `webhook_url`: Mattermost incoming webhook URL

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` - Override webhook's default channel
- `timeout` (default: `10`) - HTTP request timeout

#### Slack Channel

```yaml
alert_channels:
  slack_ops:
    type: slack
    webhook_url: "https://hooks.slack.com/services/xxx"
    channel: "#alerts"          # Explicit channel
    # Bot name + avatar default to the detectkit brand; override with
    # username / icon_url / icon_emoji.
```

Same fields as Mattermost (Slack-compatible webhook API).

#### Telegram Channel

```yaml
alert_channels:
  telegram_alerts:
    type: telegram
    bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id: "-1001234567890"
    parse_mode: "HTML"          # "Markdown", "HTML", or null (default: "HTML")
    disable_notification: false # Send silently without notification (default: false)
```

**Required fields**:
- `type`: Must be `"telegram"`
- `bot_token`: Telegram bot API token
- `chat_id`: Target chat/channel ID

**Optional fields**:
- `parse_mode` (default: `"HTML"`) - Message formatting: `"Markdown"`, `"HTML"`, or `null`
- `disable_notification` (default: `false`) - Send the message silently, without a notification sound

> The default `parse_mode` is now `HTML` (was `Markdown`). The built-in message
> is HTML-escaped, which fixes a "can't parse entities" error the old Markdown
> default raised on params JSON containing underscores (e.g. `window_size`).
> Custom templates are sent verbatim under the parse mode, so keep them
> HTML-safe — or set `parse_mode: Markdown` to restore the previous behavior.

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
- `from_name` (default: `"detectkit"`) - Sender display name in the `From`
  header (the brand logo is also rendered in the HTML body)
- `smtp_username`: SMTP authentication username (the channel only logs in when both `smtp_username` and `smtp_password` are set)
- `smtp_password`: SMTP authentication password
- `use_tls` (default: `true`) - Use TLS encryption
- `subject_template` (default: `"🔴 Alert: {metric_name}"`) - Email subject, supports `{metric_name}`
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
    channel: "#alerts"            # Target channel (optional, Slack/Mattermost)
    timeout: 10                    # Request timeout in seconds (default: 10)
    extra_headers:                 # Additional HTTP headers (optional)
      Authorization: "Bearer token"
    # Bot name + avatar default to the detectkit brand; override with
    # username / icon_url / icon_emoji.
```

**Required fields**:
- `type`: Must be `"webhook"`
- `webhook_url`: Endpoint URL to POST the JSON payload to

**Optional fields**:
- `username` (default: `"detectkit"`) - Bot display name
- `icon_url` (default: detectkit brand avatar) - Bot avatar image URL
- `icon_emoji` (optional) - Emoji icon, used instead of an avatar image
- `channel` - Override the receiver's default channel
- `timeout` (default: `10`) - HTTP request timeout
- `extra_headers`: Dict of additional HTTP headers to send

