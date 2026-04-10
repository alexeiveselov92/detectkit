# Changelog

All notable changes to detectkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.16] - 2026-04-10

### Added
- **`suppress_until`** field in alerting config — temporarily suppress alerts until a specified
  UTC datetime without disabling the metric. Load and detect steps continue running; alerts
  auto-resume after the specified time. One-time setup, no need to toggle `enabled` twice.

### Fixed
- **Timezone display in alerts**: timestamps are now converted from UTC to the configured
  `timezone` (e.g., `Europe/Moscow`) before formatting. Previously, UTC time was displayed
  with the timezone label appended, showing incorrect local time.
- **Recovery alert metadata**: recovery messages now show the detector name and confidence
  interval from the last anomalous detection instead of "Detector: unknown" and "CI: N/A".

## [0.3.14] - 2026-04-09

### Fixed
- **Direction-aware recovery**: recovery for `direction="up"` / `"down"` / `"same"` alerts no
  longer waits for the metric to return inside the confidence interval. A `down`-only alert
  now recovers as soon as the latest point is no longer a `down` anomaly (including when it
  flips to an `up` anomaly), matching the semantics of `_count_consecutive_anomalies()`.
- **ManualBoundsDetector recovery / alerting**: anomaly direction is now read from
  `detection_metadata.direction` (authoritative `"below"`/`"above"` written by every detector)
  instead of being reconstructed from `value` vs `confidence_lower/upper`. One-sided manual
  bounds (e.g. only `upper_bound` set, `confidence_lower=None`) no longer break direction
  resolution in `AlertOrchestrator._check_recovery_since_last_alert()` and
  `TaskManager._load_recent_detections()`.

### Changed
- `InternalTablesManager.get_recent_detections()` now selects `detection_metadata` and exposes
  it as `detection_metadata_list` in the grouped result.
- New `AlertOrchestrator._get_alert_trigger_direction()` helper resolves the direction of the
  alert-triggering point for `direction="same"` recovery checks.

## [0.3.13] - 2026-04-08

### Added
- New internal table `_dtk_alert_states` for independent alert state per alerting config block
  (`last_alert_sent`, `last_recovery_sent`, `alert_count` keyed by `metric_name` + `alert_config_id`)
- `alert_config_id` generated as MD5 hash of all config params (channels, min_detectors, direction,
  consecutive_anomalies, alert_cooldown, cooldown_reset_on_recovery) — configs with the same channels
  but different conditions correctly get different IDs and independent state

### Fixed
- **Multi-config alerting**: when a metric has multiple `alerting:` blocks, each now tracks its own
  alert/recovery state independently — fixes false recoveries caused by shared `last_alert_sent`
- **Recovery threshold**: recovery now requires 0 detectors flagging the latest point as anomalous
  (previously used `< min_detectors`, causing false recovery when some detectors still saw anomaly)
- **Recovery message point**: `_build_recovery_data()` now correctly uses the newest detection point
  (`detections[-1]`) instead of the oldest (`detections[0]`)

### Changed
- `get_last_alert_timestamp`, `update_alert_timestamp`, `get_last_recovery_timestamp`,
  `update_recovery_timestamp` now require `alert_config_id` parameter
- `upsert_task_status` simplified — alert state no longer stored in `_dtk_tasks`
- `AlertOrchestrator.__init__` requires `alert_config_id` parameter

### Migration
New table is created automatically on next `dtk run` via `ensure_tables()`.
Existing alert state in `_dtk_tasks` is not migrated — first run after upgrade starts with clean state.

## [0.3.12] - 2026-04-08

### Fixed
- Custom `template_consecutive` from alerting config now correctly passed to `send_alerts()`
- Numpy timezone warning in `upsert_task_status`: strip tzinfo from datetime fields before
  converting to `datetime64[ms]`

### Changed
- Centralized UTC datetime handling into `detectkit/utils/datetime_utils.py`
  (`now_utc`, `now_utc_naive`, `to_naive_utc`, `to_aware_utc`)

## [0.3.11] - 2026-04-08

### Fixed
- Recovery notifications never fired: `upsert_task_status` was destroying `last_alert_sent` /
  `last_recovery_sent` on every DELETE+INSERT cycle (fields were reset to NULL)
- Alert mutations now use `mutations_sync=1` to prevent race conditions between alert step
  and lock release

## [0.3.10] - 2026-04-08

### Fixed
- False recovery detection: check latest point's anomaly status instead of counting consecutive anomalies
- Alert step now always runs (recovery notifications need it even when no new anomalies detected)
- `min_detectors` now correctly read from alerting config instead of being hardcoded to 1

## [0.3.9] - 2026-04-07

### Added
- Multiple alerting configurations per metric: `alerting` now accepts a list of alert configs, each with its own channels, timezone, template, and conditions
- Backward-compatible: single `alerting:` dict still works as before

## [0.3.8] - 2026-04-07

### Added
- **Channel-agnostic mentions** in alert messages (`mentions` config field)
- `format_mentions()` method on `BaseAlertChannel` — overridable per channel
- Platform-specific formatting: Mattermost (`@user`), Slack (`<!here>`, `<@UID>`), Telegram (`@user`), Email (`CC: user`)
- `{mentions}` and `{mentions_line}` template variables for custom placement
- Special keywords: `here`, `channel`, `all` for broadcast mentions
- Documentation: mentions guide, 4 example scenarios, updated configuration reference

## [0.3.7] - 2026-04-06

### Changed
- Mattermost alerts now use attachments format with colored sidebar (red for anomaly, green for recovery)
- Webhook default templates omit metric name from body (shown in attachment title)

## [0.3.6] - 2026-04-06

### Added
- Recovery notifications: `notify_on_recovery: true` in alerting config sends a message when metric stabilizes after an anomaly
- `template_recovery` config option for custom recovery message template
- `{status}` template variable in all alert templates (`"ANOMALY"` or `"RECOVERED"`)
- `is_recovery` field on `AlertData` to distinguish recovery messages from anomaly alerts
- `AlertOrchestrator.should_send_recovery()` — checks recovery conditions and returns AlertData
- `AlertOrchestrator.send_recovery()` — sends recovery via configured channels and tracks timestamp
- `_dtk_tasks.last_recovery_sent` column for deduplication (one recovery notification per incident)
- `InternalTablesManager.get_last_recovery_timestamp()` and `update_recovery_timestamp()` methods
- `BaseAlertChannel.get_default_recovery_template()` method

### Migration
Existing installations need to add the new column manually:
```sql
ALTER TABLE _dtk_tasks ADD COLUMN last_recovery_sent Nullable(DateTime64(3, 'UTC'));
```

## [0.3.2] - 2025-11-11

### Fixed
- Critical bug: Newly added detectors no longer start processing from 1970-01-01 (epoch)
- `get_last_detection_timestamp()` now properly handles epoch timestamps returned by ClickHouse for NULL values
- This completes the epoch fix from v0.2.5 which only fixed the datapoints method

## [0.3.1] - 2025-11-10

### Fixed
- CLI now shows warnings when metric files fail to parse (YAML syntax errors, validation errors, etc.) instead of silently skipping them
- Tag selector (`--select tag:`) now searches both `.yml` and `.yaml` files (previously only searched `.yml`, inconsistent with name selector)

### Changed
- Improved error messages when no metrics are found - now provides feedback about which files were skipped due to parsing errors
- Made metric file discovery consistent across both tag and name selectors

## [0.3.0] - 2025-11-10

### Added
- Alert cooldown system to prevent spam from persistent anomalies
- `alert_cooldown` configuration parameter (supports "30min" string or integer seconds)
- `cooldown_reset_on_recovery` option to reset cooldown when metric recovers
- `_dtk_tasks.last_alert_sent` column to track last alert timestamp
- `_dtk_tasks.alert_count` column to track total alerts sent per metric

### Changed
- `AlertOrchestrator` now checks cooldown period before sending alerts
- `InternalTablesManager` added methods: `get_last_alert_timestamp()`, `update_alert_timestamp()`
- Alert orchestration moved cooldown check before expensive operations for performance

### Fixed
- Alert spam when persistent anomalies generate duplicate alerts at every interval

## [0.2.8] - 2025-11-10

### Fixed
- Detection step no longer runs with 0 points when current interval is incomplete
- Alerts no longer sent when 0 anomalies detected in current run
- `get_recent_detections()` now filters by `created_after` to prevent loading old detections from previous runs

## [0.2.7] - 2025-11-10

### Added
- `_dtk_metrics` informational table for analysts and dashboards
- Metric configuration metadata stored automatically on every `dtk run`
- `description` field support in metric configuration files
- Tags extraction and storage in `_dtk_metrics` table

### Fixed
- Timezone warning in `load_datapoints()` by converting timezone-aware datetimes to naive
- Project name handling in `dtk init` command (now extracts basename from path)

## [0.2.5] - 2025-11-08

### Fixed
- Critical bug: `get_last_timestamp()` returning epoch (1970-01-01) instead of None when no data exists
- Prevented incorrect historical data loading due to epoch timestamp

## [0.2.4] - 2025-11-07

### Changed
- Improved logging output formatting
- Enhanced error messages for better debugging

### Fixed
- Numpy datetime64 comparison warnings by ensuring datetime objects are timezone-naive

## [0.2.3] - 2025-11-07

### Fixed
- Metric name selector (`--select`) now correctly searches metrics in subdirectories
- Previously only searched in root `metrics/` directory

## [0.2.2] - 2025-11-07

### Added
- `requests` dependency for HTTP-based alert channels

## [0.2.1] - 2025-11-07

### Changed
- Alert formatting improved for better readability
- Database-agnostic architecture maintained across all components

### Fixed
- Recursion error in alert message formatting by adding `detector_params` field
- Broadcasting error in seasonality mask application
- Timezone comparison issues in datetime handling

## [0.2.0] - 2025-11-06

### Added
- **Detector Preprocessing**: Transform input values before detection
  - `input_type: "raw"` - Use values as-is (default)
  - `input_type: "diff"` - Detect on differences between consecutive points
  - `input_type: "pct_change"` - Detect on percentage changes
- **Value Smoothing**: Reduce noise with moving average
  - `smoothing_window: N` - Apply N-point moving average before detection
- **Recent Value Weighting**: Weight recent data more heavily
  - `recent_weight: 0.0-1.0` - Weight for recent 20% of window (default: 0.0)
- All statistical detectors (MAD, Z-Score, IQR, ManualBounds) support preprocessing

### Changed
- Detector base classes updated to support preprocessing pipeline
- Detection metadata now includes preprocessing information

## [0.1.2] - 2025-11-05

### Added
- Data integrity validation: uniqueness checks for datapoints and detections
- Tags support for metric categorization and filtering
- `tags` field in metric configuration (YAML array)

### Changed
- Internal tables rebuilt with ReplacingMergeTree engine for automatic deduplication

## [0.1.1] - 2025-11-04

### Added
- Seasonality support for Z-Score detector
- Seasonality support for IQR detector
- Documentation for seasonality features in all statistical detectors

## [0.1.0] - 2025-11-03

### Added
- Initial release of detectkit
- Core functionality:
  - Metric data loading from databases (ClickHouse, PostgreSQL, MySQL)
  - Statistical anomaly detectors (MAD, Z-Score, IQR, Manual Bounds)
  - Seasonality support (MAD detector)
  - Multi-channel alerting (Mattermost, Slack, Telegram, Email)
  - CLI interface (`dtk init`, `dtk run`)
  - Idempotent operations with resume capability
  - Internal tables for state management (_dtk_datapoints, _dtk_detections, _dtk_tasks)
- Documentation:
  - Comprehensive guides (configuration, alerting, detectors)
  - API reference for all detector types
  - Quick start guide
  - Installation instructions
- Testing:
  - 287+ unit tests
  - 87% code coverage

---

## Version Links

- [0.3.0]: https://github.com/alexeiveselov92/detectkit/releases/tag/v0.3.0
- [0.2.8]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.7...v0.2.8
- [0.2.7]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.5...v0.2.7
- [0.2.5]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.4...v0.2.5
- [0.2.4]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.3...v0.2.4
- [0.2.3]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.2...v0.2.3
- [0.2.2]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.1...v0.2.2
- [0.2.1]: https://github.com/alexeiveselov92/detectkit/compare/v0.2.0...v0.2.1
- [0.2.0]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.2...v0.2.0
- [0.1.2]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.1...v0.1.2
- [0.1.1]: https://github.com/alexeiveselov92/detectkit/compare/v0.1.0...v0.1.1
- [0.1.0]: https://github.com/alexeiveselov92/detectkit/releases/tag/v0.1.0
