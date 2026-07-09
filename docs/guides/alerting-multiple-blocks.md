# Multiple Alert Configurations

You can define multiple independent alerting configs per metric — each with its own channels, timezone, template, and conditions:

```yaml
alerting:
  - enabled: true
    channels:
      - mattermost_ops
    timezone: "Europe/Moscow"
    consecutive_anomalies: 3

  - enabled: true
    channels:
      - slack_critical
    timezone: "UTC"
    consecutive_anomalies: 1      # More sensitive for this channel
    direction: "up"               # Only upward anomalies
    template_consecutive: "templates/slack_alert.j2"
```

Each config is evaluated and sent independently. Single dict format (backward-compatible) continues to work.

> **Changed or removed an alert config?** Each block's cooldown/recovery state
> in `_dtk_alert_states` is keyed by a hash of its functional fields (channels,
> `min_detectors`, `consecutive_anomalies`, `direction`, `alert_cooldown`,
> `cooldown_reset_on_recovery`), so editing
> those fields or removing a block leaves the old state row behind. Run
> [`dtk clean --select <metric>`](../reference/cli.md#dtk-clean) to prune it.
> (Disabling a block with `enabled: false` keeps its state — the hash is
> unchanged — so a temporarily-paused alert is never treated as orphaned.)
