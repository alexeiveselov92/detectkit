# Changelog

All notable changes to detectkit will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
