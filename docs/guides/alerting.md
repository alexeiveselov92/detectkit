# Alerting Guide

This guide explains how to configure and customize alerting in detectkit.

> **This guide is split into focused pages:**
>
> - **This page** — how alerting works + the quorum / direction / consecutive filtering rules.
> - [Alert channels](alerting-channels.md) — Mattermost, Slack, Telegram, Email, generic webhook.
> - [Multiple alert blocks](alerting-multiple-blocks.md) — route one metric to several independent alert rules.
> - [Cooldown, suppression & recovery](alerting-cooldown-recovery.md)
> - [No-data & error alerts](alerting-no-data-errors.md)
> - [Templates, mentions & testing](alerting-templates-mentions.md)
> - [Patterns & troubleshooting](alerting-patterns.md)

## Overview

detectkit's alerting system:
- Checks only recent data (not historical)
- Requires consecutive anomalies (reduces false positives)
- Supports multiple channels (Mattermost, Slack, Telegram, Email, generic webhook)
- Filters by detector agreement and direction
- Customizable templates
- @mentions for users and groups (channel-agnostic)

## How Alerting Works

### Alert Flow

```
1. Detection Step
   └─> Detects anomalies in recent data

2. Alert Step
   ├─> Load the most recent detection results
   ├─> Per timestamp: check the quorum —
   │   at least min_detectors anomalies matching the direction policy
   ├─> Require consecutive_anomalies quorum points,
   │   each exactly one interval apart (a grid gap breaks the chain)
   └─> Send alert through configured channels
```

### Key Concepts

**Quorum**: at a given timestamp, the set of anomalous detections that
match the `direction` policy. A timestamp counts toward an alert only
when at least `min_detectors` detections qualify. See
[Alert Filtering](#alert-filtering) for the exact rules per direction.

**Consecutive Anomalies**: the latest `consecutive_anomalies` timestamps
must each satisfy the quorum AND be exactly one metric interval apart.

**Example** with `consecutive_anomalies: 3` (10-min interval):
```
10:00 Quorum ✓
10:10 Quorum ✓
10:20 Quorum ✓  → Alert sent!
10:30 Normal ✗  → chain reset
```

A gap in the detection grid (missing detection row) breaks the chain:
```
10:00 Quorum ✓
10:10 (no detection row)
10:20 Quorum ✓
10:30 Quorum ✓  → only 2 consecutive points, no alert
```

**Recent Data Only**: Alerts check only the most recent points, not historical data.

## Basic Configuration

### Minimal Setup

```yaml
name: api_response_time
interval: 5min
query: "..."

detectors:
  - type: mad
    params:
      threshold: 3.0

# Enable alerting
alerting:
  enabled: true
  channels:
    - mattermost_ops
```

This uses defaults:
- `consecutive_anomalies: 3` - Requires 3 consecutive anomalous points
- `min_detectors: 1` - One detector is enough
- `direction: "same"` - The detectors forming the quorum must agree on one direction
- `alert_cooldown: null` - No cooldown: a persisting anomaly re-alerts on every `dtk run` (set a cooldown for production metrics)

### Complete Configuration

```yaml
alerting:
  enabled: true                  # Enable/disable alerting
  timezone: "Europe/Moscow"      # Display timezone (default: UTC)

  # Channels
  channels:
    - mattermost_ops
    - slack_critical
    - email_team

  # Dashboard / runbook links (v0.13.0)
  dashboard_url: https://grafana.ops/d/api-errors   # clickable title / link / button
  links:                                            # extra "label: url" links
    Runbook: https://runbooks.ops/api-errors

  # Filtering
  min_detectors: 1               # Detectors that must satisfy the quorum per point
  direction: "same"              # "same", "any", "up", "down"
  consecutive_anomalies: 3       # Consecutive quorum points required

  # Cooldown (default null = re-alert on EVERY run while anomaly persists)
  alert_cooldown: "2h"

  # Special alerts
  no_data_alert: false           # Alert on missing data

  # Custom templates
  template_single: null          # Used when consecutive_count <= 1
  template_consecutive: null     # Used for streaks; each falls back to the other
```

## Alert Filtering

The three conditions combine into one contract:

1. At every timestamp, detections from all detectors are grouped together.
2. A timestamp satisfies the **quorum** when at least `min_detectors`
   anomalies match the `direction` policy.
3. An alert fires when the latest `consecutive_anomalies` timestamps each
   satisfy the quorum AND sit on a contiguous interval grid (each point
   exactly one metric interval after the previous — gaps break the chain).

### Consecutive Anomalies

Require N consecutive quorum-satisfying points before alerting.

```yaml
alerting:
  consecutive_anomalies: 1   # Alert immediately (use with caution)
  consecutive_anomalies: 3   # Alert after 3 consecutive (recommended)
  consecutive_anomalies: 5   # Alert after 5 consecutive (conservative)
```

The points must be **grid-adjacent**: a missing detection row between two
anomalies (e.g. a day without runs, or a detector `start_time` boundary)
breaks the chain — anomalies separated by gaps are never counted as
consecutive.

**Use cases**:
- `1` - Critical metrics (errors should be 0)
- `3` - Standard (good balance)
- `5+` - Noisy metrics or high false-positive cost

### Direction Policy

Controls which anomalies count toward the quorum.

```yaml
alerting:
  direction: "same"   # Quorum must agree on ONE direction (default)
  direction: "any"    # Every anomaly counts, regardless of direction
  direction: "up"     # Only anomalies above the interval count
  direction: "down"   # Only anomalies below the interval count
```

- **`"up"` / `"down"`**: only anomalies in that direction count toward
  `min_detectors`. Detectors firing the other way are ignored — they
  neither help nor block the quorum.
- **`"any"`**: every anomaly counts; one up-anomaly plus one
  down-anomaly together satisfy `min_detectors: 2`.
- **`"same"`** (default): at the latest point, at least `min_detectors`
  detectors must agree on ONE direction. Up- and down-anomalies are
  counted separately — disagreement is not consensus. If both directions
  independently reach quorum, the side with more detectors wins; ties go
  to the more severe side. The winning direction is then **locked for
  the whole consecutive chain**: every older point must satisfy the
  quorum in that same direction.

**Use cases**:
- `"same"` - Multiple detectors (reduce false positives, default)
- `"any"` - Most single-detector metrics (any deviation matters)
- `"up"` - CPU usage, error rates (high is bad, low is good)
- `"down"` - Cache hit rate, uptime (low is bad, high is good)

### Multiple Detector Agreement

`min_detectors` is how many detectors must satisfy the direction policy
at **every** point in the consecutive chain:

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 3.0

alerting:
  min_detectors: 1  # One qualifying detector per point is enough
  min_detectors: 2  # Both detectors must qualify at each point
```

**Use cases**:
- `1` - High recall (catch more anomalies, some false positives)
- `N` (all) - High precision (fewer false positives, may miss some)

### Worked Examples

Two detectors A and B, `min_detectors: 2`, both anomalous at the latest
point:

| `direction` | A says | B says | Result |
|---|---|---|---|
| `same` | up | down | **No alert** — disagreement is not consensus |
| `same` | up | up | Quorum met; direction "up" locked for the chain |
| `up` | up | down | **No quorum** — only one "up" anomaly, needs 2 ups |
| `up` | up | up | Quorum met |
| `down` | up | up | **No quorum** — "up" anomalies are ignored, never blocking |
| `any` | up | down | Quorum met — every anomaly counts |

### Alert Payload

The message is built from the **highest-severity** detection of the
latest quorum (ties broken by detector name, so the choice is
deterministic): value, confidence interval and timestamp come from that
record. For multi-detector alerts, `{detector_name}` renders as
`"N detectors"`, `{severity}` is the maximum across the quorum, and
per-detector metadata is included.

### Combined Filtering Example

```yaml
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 2.5

alerting:
  min_detectors: 2          # Both must qualify at each point
  direction: "same"         # ...and agree on one direction
  consecutive_anomalies: 3  # ...for 3 grid-adjacent points
```

This creates a **very conservative** alert:
- Both detectors must report an anomaly
- Both must fire in the same direction (both "up" or both "down")
- That must hold for 3 consecutive, gap-free points

