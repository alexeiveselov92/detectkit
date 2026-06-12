# detectkit - Architecture Design

## Overview

detectkit is designed as a modular, database-agnostic library for metric monitoring with automatic anomaly detection. The architecture follows a pipeline pattern with three main stages: **Load → Detect → Alert**.

## Core Principles

1. **Numpy-first**: All data processing uses numpy arrays for performance
2. **Database-agnostic**: Abstract interface for different databases
3. **Idempotent**: All operations can be safely rerun
4. **Modular**: Small, focused modules with clear responsibilities
5. **Type-safe**: Pydantic models and type hints throughout

---

## Module Structure

```
detectkit/
├── cli/              # Command-line interface (Click-based)
├── config/           # Configuration management (Pydantic models)
├── core/             # Core utilities (Interval, dataclasses)
├── database/         # Database abstraction layer
├── loaders/          # Metric data loading pipeline
├── detectors/        # Anomaly detection algorithms
├── alerting/         # Alert orchestration & channels
├── orchestration/    # Pipeline coordination & task management
└── utils/            # Shared utilities
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     User Configuration                       │
│  - detectkit_project.yml                                      │
│  - metrics/*.yml                                            │
│  - profiles.yml                                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    CLI (dtk run)                            │
│  - Parse arguments                                          │
│  - Select metrics (tags, paths, excludes)                   │
│  - Validate configurations                                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               Pipeline Orchestrator                          │
│  - Check _dtk_tasks for locks                              │
│  - Coordinate load → detect → alert                         │
│  - Handle errors & retries                                  │
└───────────┬─────────────┬─────────────┬─────────────────────┘
            │             │             │
            ▼             ▼             ▼
    ┌──────────┐  ┌─────────────┐  ┌────────────┐
    │  Loader  │  │  Detectors  │  │  Alerting  │
    └────┬─────┘  └──────┬──────┘  └──────┬─────┘
         │               │                │
         ▼               ▼                ▼
    ┌────────────────────────────────────────────┐
    │         Database Manager                    │
    │  - ClickHouse / Postgres / MySQL           │
    │  - Execute queries                         │
    │  - Insert batches                          │
    │  - Manage transactions                     │
    └────────────────────────────────────────────┘
```

---

## Key Components

### 1. Configuration Layer

**Purpose**: Parse and validate YAML configurations into typed Python objects

**Components**:
- `ProjectConfig` - Project-level settings
- `MetricConfig` - Individual metric configuration
- `ProfileConfig` - Database connection profiles
- `DetectorConfig` - Detector parameters
- `AlertingConfig` - Alert settings

**Key Features**:
- Pydantic validation with custom validators
- Environment variable substitution (`${VAR}`)
- Default values and inheritance

**Example**:
```python
class MetricConfig(BaseModel):
    name: str
    profile: str
    query: Optional[str] = None
    query_file: Optional[str] = None
    interval: Union[int, str]  # parsed into Interval
    detectors: List[DetectorConfig]

    @validator('query', 'query_file')
    def validate_query_xor(cls, v, values):
        # Ensure query XOR query_file
        ...
```

---

### 2. Core Utilities

#### IntervalManager (`core/interval.py`)

**Purpose**: Parse and manipulate time intervals

**Features**:
- Parse string formats: "10min", "1h", "1d"
- Parse integer seconds: 600
- Floor timestamps to interval boundaries
- Calculate last complete point for alerting

**Implementation**:
```python
class Interval:
    def __init__(self, value: Union[int, str]):
        self._seconds = self._parse(value)

    def floor_timestamp(self, ts: datetime) -> datetime:
        """Round down to interval boundary"""
        epoch = int(ts.timestamp())
        floored = (epoch // self._seconds) * self._seconds
        return datetime.fromtimestamp(floored, tz=timezone.utc)
```

#### Dataclasses (`core/dataclasses.py`)

**Purpose**: Typed containers for data passing between components

**Key Classes**:
```python
@dataclass
class MetricData:
    """Raw metric data with seasonality"""
    metric_name: str
    timestamps: np.ndarray         # datetime64[ns]
    values: np.ndarray             # float64, may contain NaN
    seasonality: Dict[str, np.ndarray]
    interval_seconds: int

@dataclass
class DetectionData:
    """Detection results from a detector"""
    metric_name: str
    detector_id: str
    timestamps: np.ndarray
    is_anomaly: np.ndarray         # bool
    confidence_lower: np.ndarray   # float64
    confidence_upper: np.ndarray   # float64
    values: np.ndarray
    detector_params: Dict
    detection_metadata: Dict[str, np.ndarray]
```

---

### 3. Database Layer

**Purpose**: Abstract database operations for multiple backends

#### BaseDatabaseManager (`database/base.py`)

**Interface**:
```python
class BaseDatabaseManager(ABC):
    @abstractmethod
    def execute_query(self, query: str, params: Dict) -> Dict[str, np.ndarray]:
        """Execute SQL and return columns as numpy arrays"""

    @abstractmethod
    def insert_batch(self, table: str, data: Dict[str, np.ndarray],
                     conflict_strategy: str = "ignore"):
        """Insert batch with conflict handling"""

    @abstractmethod
    def get_last_timestamp(self, table: str, metric: str) -> Optional[datetime]:
        """Get last recorded timestamp for metric"""

    @abstractmethod
    def upsert_task_status(self, metric: str, detector_id: str,
                          process_type: str, status: str, **kwargs):
        """Update or insert task status in _dtk_tasks"""

    @property
    @abstractmethod
    def internal_location(self) -> str:
        """Full path to internal schema/database"""
```

#### ClickHouseManager (`database/clickhouse.py`)

**Key Features**:
- Native protocol via `clickhouse-driver`
- Efficient batch inserts using `execute_insert`
- Jinja2 template rendering for queries
- Deduplication via PRIMARY KEY

**Considerations**:
- ClickHouse: `database` = schema (no nesting)
- Use `INSERT` for writes (no UPDATE support)
- Delete + Insert pattern for `_dtk_tasks` updates

---

### 4. Loading Pipeline

#### MetricLoader (`loaders/loader.py`)

**Responsibilities**:
1. Determine start point for loading
2. Execute SQL queries in batches
3. Validate source data (no duplicates)
4. Fill missing time points with NaN
5. Write to `_dtk_datapoints`

**Key Methods**:
```python
class MetricLoader:
    def load(self, from_timestamp: Optional[datetime] = None,
             full_refresh: bool = False) -> int:
        """Load metric data from source"""

    def _load_batch(self, start: datetime) -> Dict[str, np.ndarray]:
        """Execute SQL for one batch"""

    def _fill_missing_points(self, batch_data, start) -> Dict:
        """Generate complete time series with NaN for gaps"""

    def _validate_no_duplicates(self, data):
        """Check for duplicate timestamps in source"""
```

**Idempotency Strategy**:
```python
# 1. Get last timestamp from storage
last_ts = db.get_last_timestamp("_dtk_datapoints", metric_name)

# 2. Start from next point
start = last_ts + interval if last_ts else config.loading_start_time

# 3. Use INSERT IGNORE (ClickHouse) or ON CONFLICT DO NOTHING (Postgres)
db.insert_batch(table, data, conflict_strategy="ignore")
```

---

### 5. Detection Pipeline

#### BaseDetector (`detectors/base.py`)

**Interface**:
```python
class BaseDetector(ABC):
    def __init__(self, **params):
        self.params = params
        self._validate_params()  # fail fast on bad config

    @abstractmethod
    def _validate_params(self):
        """Validate parameters at construction time"""

    @abstractmethod
    def detect(self, data: dict[str, np.ndarray]) -> list[DetectionResult]:
        """
        Run detection. `data` contains "timestamp", "value" and optionally
        "seasonality_data"/"seasonality_columns" arrays (full batch
        including the historical context window).
        """

    @abstractmethod
    def _get_non_default_params(self) -> dict[str, Any]:
        """Params that differ from defaults — every parameter that changes
        detection output participates in the detector ID"""

    def get_detector_id(self) -> str:
        """Generate detector ID from class name + non-default params"""
        non_default = self._get_non_default_params()
        sorted_params = sorted(non_default.items())
        hash_string = self.__class__.__name__ + str(sorted_params)
        return hashlib.sha256(hash_string.encode()).hexdigest()[:16]

    def get_context_size(self) -> int:
        """Historical points needed before the first detected point
        (window_size + smoothing warm-up + 1 for change-based input_type)"""
```

Shared preprocessing helpers (`_preprocess_input` for `input_type`,
`_apply_smoothing` for EMA/SMA) also live in `BaseDetector`.

#### Statistical Detectors (`detectors/statistical/`)

**Template Method design** (`_windowed.py`): MAD, Z-Score and IQR share one
implementation, `WindowedStatDetector`, which owns the whole per-point
pipeline — preprocessing (smoothing + `input_type` transform), trailing
window slice (current point excluded) with NaN filtering, optional
time-aware recency weighting, optional robust linear detrending, global
statistics + per-seasonality-group multipliers, confidence interval and
metadata. Subclasses only define:
- `THRESHOLD_DEFAULT`, `MIN_SAMPLES_FLOOR`, `MIN_SAMPLES_PER_GROUP_DEFAULT` class attributes
- `STATS`: ordered `(name, kind)` statistic spec (`kind` in `{"center", "spread"}`)
- `_compute_stats(values, weights)` — e.g. median/MAD, mean/std, q1/q3/IQR
- `_build_interval(stats, threshold)` — the confidence-interval formula
- `_severity(current, stats, distance)` — the severity formula

All windowing, weighting, detrending and seasonality logic therefore
behaves identically across the three detectors. `ManualBoundsDetector` is
separate (stateless, no window).

**Core Algorithm** (MAD example):

1. **Compute weights** (optional, time-aware — weight depends on a point's
   age on the time grid, so data gaps don't compress the decay):
   ```python
   ages = np.arange(1, window_size + 1)  # 1 = previous point

   if window_weights == 'exponential':
       # half_life: points (int) or duration string ("3d"), converted
       # via the data grid step; default = window_size / 20
       weights = 0.5 ** (ages / half_life_points)
   elif window_weights == 'linear':
       weights = (window_size + 1 - ages) / window_size
   ```

2. **Detrend** (optional, `detrend: linear`): estimate a robust slope over
   the window (split-median) and project every window point to the current
   point along that trend before computing statistics.

3. **Global statistics**:
   ```python
   global_median = weighted_median(window_values, weights)
   global_mad = weighted_mad(window_values, weights, global_median)
   ```

4. **Seasonality adjustments**:
   ```python
   for component in seasonality_components:
       # Create boolean mask
       mask = create_seasonality_mask(component, current_idx, window)

       # Filter data and weights
       filtered_values = window_values[mask]
       filtered_weights = weights[mask]

       # Compute component statistics
       comp_median = weighted_median(filtered_values, filtered_weights)
       comp_mad = weighted_mad(filtered_values, filtered_weights, comp_median)

       # Multipliers
       center_mult *= comp_median / global_median
       spread_mult *= comp_mad / global_mad
   ```

5. **Adjusted bounds**:
   ```python
   adjusted_center = global_median * center_mult
   adjusted_spread = global_mad * spread_mult   # MAD scaled by 1.4826 (σ-equivalent)
   lower = adjusted_center - threshold * adjusted_spread
   upper = adjusted_center + threshold * adjusted_spread
   ```

**Seasonality Handling**:
- Single column: `mask = (seasonality['day_of_week'] == current_value)`
- Multiple columns: `mask = (col1 == val1) & (col2 == val2) & ...`
- Empty mask → multiplier = 1.0 (no adjustment)
- Insufficient samples → multiplier = 1.0 + metadata flag

---

### 6. Alerting Pipeline

#### AlertOrchestrator (`alerting/orchestrator.py`)

**Workflow**:
1. Check `suppress_until` — if set and `now < suppress_until`, skip alerting entirely
2. Determine last complete point: `floor(now, interval) - interval`
3. Load detection results for all detectors at that point
4. If no data → send no_data alert (optional)
5. Invoke AlertDecisionEngine
6. If decision = True → render template → send via channels

#### AlertDecisionEngine (`alerting/decision.py`)

**Decision Logic**:
```python
def decide(self, detections: List[DetectionData]) -> Tuple[bool, Dict]:
    # 1. Count detectors with anomalies
    anomaly_detectors = [d for d in detections if d.is_anomaly[-1]]

    if len(anomaly_detectors) < config.min_detectors:
        return False, {}

    # 2. Check consecutive anomalies (if required)
    if config.consecutive_anomalies > 1:
        history = load_last_n_points(config.consecutive_anomalies)
        if not check_consecutive(history, config.direction):
            return False, {}

    # 3. Check direction
    if not check_direction(anomaly_detectors, config.direction):
        return False, {}

    return True, prepare_alert_data(anomaly_detectors)
```

**Consecutive Anomaly Logic**:
- Load last N points from `_dtk_detections`
- Iterate backwards (newest first)
- Track direction and count
- Stop if non-anomaly or direction change (when `direction="same"`)

#### AlertChannels (`alerting/channels/`)

**Base Interface**:
```python
class BaseAlertChannel(ABC):
    @abstractmethod
    def send(self, message: str, destination: Optional[str] = None):
        """Send alert message"""
```

**Implementations**:
- `MattermostChannel` - webhook POST
- `SlackChannel` - webhook POST
- `TelegramChannel` - Bot API
- `EmailChannel` - SMTP

---

### 7. Orchestration Layer

#### TaskManager (`orchestration/task_manager.py`)

**Purpose**: Manage task states in `_dtk_tasks` to prevent concurrent runs

**Key Methods**:
```python
class TaskManager:
    def can_start(self, metric: str, detector_id: str,
                  process_type: str, force: bool = False) -> bool:
        """Check if process can start"""
        task = self.db.get_task_status(metric, detector_id, process_type)

        if not task:
            return True  # first run

        if force:
            return True  # forced override

        if task.status == 'running':
            elapsed = now() - task.started_at
            return elapsed > task.timeout_seconds  # timeout

        return True  # completed or failed

    def mark_running(self, metric: str, detector_id: str, process_type: str):
        """Mark task as running"""

    def mark_completed(self, metric: str, detector_id: str, process_type: str):
        """Mark task as completed"""

    def mark_failed(self, metric: str, detector_id: str, process_type: str, error: str):
        """Mark task as failed"""
```

> **Implementation note (v0.6.0):** this logic lives in
> `InternalTablesManager.acquire_lock` / `check_lock`. A `running` row older
> than its `timeout_seconds` is treated as stale and overridden, so a run
> killed without releasing its lock (e.g. DB restart mid-run) never blocks
> future runs. `--force` skips the held-lock check but still acquires and
> releases the lock, so it also clears a stuck row. `dtk unlock` clears a stuck
> lock on demand.

#### PipelineOrchestrator (`orchestration/pipeline.py`)

**Responsibilities**:
1. Parse CLI arguments
2. Select metrics based on `--select`, `--exclude`, tags
3. For each metric:
   - Check task locks
   - Execute steps: load, detect, alert (based on `--steps`)
   - Handle errors
   - Update task status

**Sequential Execution** (MVP):
```python
for metric_config in selected_metrics:
    try:
        if 'load' in steps:
            loader.load(from_timestamp=args.from_date,
                       full_refresh=args.full_refresh)

        if 'detect' in steps:
            for detector_config in metric_config.detectors:
                detector.detect(...)

        if 'alert' in steps:
            orchestrator.run()

    except Exception as e:
        task_manager.mark_failed(metric, error=str(e))
        logger.error(f"Failed: {metric.name}", exc_info=True)
```

---

## Design Patterns

### 1. Strategy + Template Method - Detectors

Different detection algorithms implement the `BaseDetector` interface.
The three windowed statistical detectors extend `WindowedStatDetector`
(template method: shared pipeline, detector-specific statistics):
- `MADDetector` - Median Absolute Deviation, scaled by 1.4826 to σ-equivalents (robust to outliers)
- `ZScoreDetector` - Mean and Standard Deviation (classic Z-score)
- `IQRDetector` - Interquartile Range (percentile-based)
- `ManualBoundsDetector` - User-defined static thresholds (extends `BaseDetector` directly)

### 2. Template Method - Database Managers

`BaseDatabaseManager` defines common operations, subclasses implement DB-specific logic:
- `ClickHouseManager` - native protocol, INSERT semantics
- `PostgresManager` - psycopg2, UPSERT support
- `MySQLManager` - pymysql

### 3. Factory Pattern - Detector Registry

```python
class DetectorFactory:
    DETECTOR_TYPES = {
        'mad': MADDetector,
        'zscore': ZScoreDetector,
        'iqr': IQRDetector,
        'manual_bounds': ManualBoundsDetector,
        'manual': ManualBoundsDetector,  # alias
    }

    @classmethod
    def create(cls, detector_type: str, params: Dict) -> BaseDetector:
        detector_class = cls.DETECTOR_TYPES.get(detector_type)
        if not detector_class:
            raise ValueError(f"Unknown detector: {detector_type}")
        return detector_class(**params)
```

### 4. Chain of Responsibility - Alert Decision

Alert conditions checked in sequence:
1. Minimum detectors → return False if not met
2. Consecutive anomalies → return False if broken
3. Direction → return False if mismatch
4. All passed → return True

---

## Performance Considerations

### 1. Numpy Vectorization

**Avoid**:
```python
for i in range(len(values)):
    if values[i] > threshold:
        anomalies[i] = True
```

**Prefer**:
```python
anomalies = values > threshold
```

### 2. Batch Processing

- Load/detect in configurable batch sizes
- Balance between memory usage and query efficiency
- Default: 1000 points for load, 500 for detect

### 3. JSON Parsing Optimization

Use `orjson` with pre-allocated numpy arrays:
```python
import orjson

def parse_seasonality_batch(json_strings: List[str]) -> Dict[str, np.ndarray]:
    # Parse first to get keys
    first = orjson.loads(json_strings[0])
    keys = first.keys()
    n = len(json_strings)

    # Pre-allocate arrays
    arrays = {key: np.empty(n) for key in keys}

    # Fill by index (no append)
    for i, json_str in enumerate(json_strings):
        data = orjson.loads(json_str)
        for key in keys:
            arrays[key][i] = data.get(key, np.nan)

    return arrays
```

### 4. Database Query Optimization

- Use batch inserts instead of row-by-row
- Parameterized queries for safety
- Index on (metric_name, timestamp) for fast lookups

---

## Error Handling

### 1. Validation Errors

- Catch at config parsing stage (Pydantic)
- Provide clear error messages with file/line info
- Fail fast before any processing

### 2. Database Errors

- Retry transient errors (connection timeouts)
- Mark task as failed for persistent errors
- Log full traceback for debugging

### 3. Detection Errors

- Catch per-detector to avoid breaking entire batch
- Log warning and continue with other detectors
- Store error in detection_metadata

### 4. Alert Errors

- Catch per-channel to avoid breaking other channels
- Log error but don't fail task
- Optional: send error notification to fallback channel

---

## Security Considerations

### 1. SQL Injection

- Use parameterized queries via Jinja2
- Never concatenate user input into SQL strings
- Validate all Jinja variables before rendering

### 2. Credential Management

- Store credentials in `profiles.yml` (not in metric configs)
- Support environment variable substitution: `${DB_PASSWORD}`
- Add `profiles.yml` to `.gitignore`

### 3. Webhook Security

- Validate webhook URLs (https only for production)
- Support signing/verification for incoming webhooks (future)
- Rate limiting on alert sending (future)

---

## Testing Strategy

### 1. Unit Tests

**Core modules**:
- `test_interval.py` - all parsing edge cases
- `test_detectors.py` - synthetic data with known anomalies
- `test_config.py` - validation logic

**Mocking**:
- Database connections via `unittest.mock`
- Fixture data in `tests/fixtures/`

### 2. Integration Tests

**End-to-end**:
- Spin up ClickHouse in Docker (testcontainers)
- Run full pipeline: init → load → detect → alert
- Verify data in tables
- Check idempotency (run twice, same result)

### 3. Property-Based Tests

Use `hypothesis` for:
- Interval parsing with random valid/invalid inputs
- Detector behavior with random time series
- Ensure no crashes on edge cases (empty data, all NaN, etc.)

---

## Future Extensions

### 1. Advanced Detectors

- Prophet integration (via optional dependency)
- TimesFM integration (Google's foundation model)
- Custom ML models (user-provided)

### 2. Multi-metric Correlation

- Detect anomalies across related metrics
- E.g., revenue drop + traffic drop = more severe

### 3. Adaptive Thresholds

- Auto-tune detector parameters based on historical performance
- Reduce false positives over time

### 4. Web UI

- Dashboard for viewing metrics & anomalies
- Configuration editor
- Alert history

### 5. Distributed Execution

- Celery/Airflow integration for parallel processing
- Kubernetes operator for cloud-native deployments

---

## Migration Path

When adding new features, follow this pattern:

1. **Define interface** in base class (e.g., `BaseDetector`)
2. **Implement** for primary use case (e.g., `MADDetector`)
3. **Add tests** for new implementation
4. **Document** in `docs/reference/`
5. **Update registry** (if applicable)
6. **Announce** in CHANGELOG.md

This ensures backward compatibility and gradual feature rollout.
