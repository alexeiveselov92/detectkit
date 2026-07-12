"""
Metric data loader.

Loads time-series data from databases with:
- SQL query execution (with Jinja2 templating)
- Gap filling for missing timestamps
- Seasonality feature extraction
- Batch processing
- Integration with InternalTablesManager
"""

from datetime import datetime, timedelta

import numpy as np

from detectkit.config.metric_config import MetricConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.manager import BaseDatabaseManager
from detectkit.loaders.errors import SourceDatabaseError
from detectkit.loaders.query_template import QueryTemplate
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc
from detectkit.utils.json_utils import json_dumps_sorted


class MetricLoader:
    """
    Loads metric data from database with preprocessing.

    Features:
    - Execute SQL queries with Jinja2 templating
    - Fill gaps in time series
    - Extract seasonality features (hour, day_of_week, etc.)
    - Save to _dtk_datapoints table
    - Batch processing for large datasets

    Example:
        >>> config = MetricConfig.from_yaml_file("metrics/cpu_usage.yml")
        >>> manager = ClickHouseDatabaseManager(...)
        >>> internal = InternalTablesManager(manager)
        >>>
        >>> loader = MetricLoader(config, manager, internal)
        >>> data = loader.load(
        ...     from_date=datetime(2024, 1, 1),
        ...     to_date=datetime(2024, 1, 2)
        ... )
        >>> loader.save(data)
    """

    def __init__(
        self,
        config: MetricConfig,
        db_manager: BaseDatabaseManager,
        internal_manager: InternalTablesManager,
        source_profile_name: str | None = None,
    ):
        """
        Initialize metric loader.

        Args:
            config: Metric configuration
            db_manager: Database manager for executing the metric's SQL. In
                hybrid mode this is a SOURCE-profile manager, distinct from
                the manager holding _dtk_* state; ``internal_manager`` below
                always talks to state.
            internal_manager: Internal tables manager for saving data
            source_profile_name: Name of the source profile *db_manager*
                belongs to, when it differs from the active state profile
                (hybrid mode). ``None`` (the default) means *db_manager* IS
                the state manager, so a query failure is indistinguishable
                from a state failure and is left unwrapped. When set, a
                query failure is wrapped in :class:`SourceDatabaseError` so
                it can be told apart from a state-database failure.
        """
        self.config = config
        self.db_manager = db_manager
        self.internal_manager = internal_manager
        self.source_profile_name = source_profile_name
        self.query_template = QueryTemplate()

    def load(
        self,
        from_date: datetime,
        to_date: datetime,
        fill_gaps: bool = True,
    ) -> dict[str, np.ndarray]:
        """
        Load metric data from database.

        Steps:
        1. Render SQL query with Jinja2
        2. Execute query
        3. Extract seasonality features
        4. Fill gaps (if enabled)
        5. Return as numpy arrays

        Args:
            from_date: Start date (inclusive)
            to_date: End date (exclusive)
            fill_gaps: Whether to fill missing timestamps with NULL

        Returns:
            Dictionary with keys:
            - timestamp: np.array of datetime64[ms]
            - value: np.array of float64 (nullable)
            - seasonality_data: np.array of JSON strings
            - seasonality_columns: list of column names

        Raises:
            ValueError: If query returns invalid data
            Exception: If query execution fails

        Example:
            >>> data = loader.load(
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 2)
            ... )
            >>> print(data["timestamp"])
            >>> print(data["value"])
        """
        # Normalize datetimes to naive UTC (ClickHouse returns naive UTC for DateTime64)
        from_date = to_naive_utc(from_date)
        to_date = to_naive_utc(to_date)

        # Get interval
        interval = self.config.get_interval()
        interval_seconds = interval.seconds

        # Render SQL query
        query_text = self.config.get_query_text()
        rendered_query = self.query_template.render(
            query_text,
            dtk_start_time=from_date,
            dtk_end_time=to_date,
            interval_seconds=interval_seconds,
        )

        # Execute query. In hybrid mode (source_profile_name set) a failure
        # here is wrapped so it reads as "source database down", not an
        # indistinguishable state-database failure.
        try:
            results = self.db_manager.execute_query(rendered_query)
        except Exception as exc:
            if self.source_profile_name is not None:
                raise SourceDatabaseError(self.source_profile_name, exc) from exc
            raise

        if not results:
            # No data - return empty arrays
            return self._create_empty_result()

        # Get column names from config (with defaults)
        if self.config.query_columns:
            timestamp_col = self.config.query_columns.timestamp
            value_col = self.config.query_columns.metric
        else:
            # Default column names
            timestamp_col = "timestamp"
            value_col = "value"

        # Filter results to exclude to_date (exclusive end)
        # SQL queries often use BETWEEN which includes both boundaries,
        # but our semantics are [from_date, to_date) - exclusive end
        filtered_results = []
        for row in results:
            if timestamp_col not in row:
                raise ValueError(
                    f"Query must return '{timestamp_col}' column "
                    f"(configured as timestamp column). "
                    f"Got columns: {list(row.keys())}"
                )

            # Filter by timestamp
            row_ts = row[timestamp_col]
            if isinstance(row_ts, datetime):
                # Naive-UTC convention: a tz-aware timestamp from the source
                # (DuckDB now()/TIMESTAMPTZ, PostgreSQL timestamptz) is
                # converted — not rejected — so it compares cleanly with the
                # naive-UTC window bounds and stores consistently downstream.
                if row_ts.tzinfo is not None:
                    row_ts = to_naive_utc(row_ts)
                    row[timestamp_col] = row_ts
                if row_ts >= to_date:
                    continue
            else:
                # Convert to datetime for comparison
                row_dt = np.datetime64(row_ts, "ms").astype(datetime)
                if row_dt >= to_date:
                    continue

            filtered_results.append(row)

        results = filtered_results

        if not results:
            # No data after filtering - return empty arrays
            return self._create_empty_result()

        # Convert results to numpy arrays
        timestamps = []
        values = []

        for row in results:
            if value_col not in row:
                raise ValueError(
                    f"Query must return '{value_col}' column "
                    f"(configured as metric value column). "
                    f"Got columns: {list(row.keys())}"
                )

            timestamps.append(row[timestamp_col])
            values.append(row[value_col])

        # Convert to numpy
        timestamp_array = np.array(timestamps, dtype="datetime64[ms]")
        value_array = np.array(values, dtype=np.float64)

        # Extract seasonality data BEFORE gap filling (from query results)
        # This is needed because gap filling may add rows that don't exist in query results
        seasonality_from_query = None
        seasonality_columns_from_query = []

        if self.config.query_columns and self.config.query_columns.seasonality:
            # Query returns custom seasonality columns - extract them
            seasonality_columns_from_query = self.config.query_columns.seasonality
            seasonality_from_query = []

            for row in results:
                features = {}
                for col in seasonality_columns_from_query:
                    if col not in row:
                        raise ValueError(
                            f"Query must return seasonality column '{col}' "
                            f"(configured in query_columns.seasonality). "
                            f"Got columns: {list(row.keys())}"
                        )
                    features[col] = row[col]

                # Convert to JSON
                seasonality_from_query.append(json_dumps_sorted(features))

            seasonality_from_query = np.array(seasonality_from_query, dtype=object)

        # Fill gaps if needed
        if fill_gaps:
            original_timestamps = timestamp_array
            timestamp_array, value_array = self._fill_gaps(
                timestamp_array, value_array, from_date, to_date, interval_seconds
            )

            # Realign query-provided seasonality to the gap-filled grid.
            # Gap rows can appear ANYWHERE in the range and _fill_gaps also
            # re-sorts rows onto the grid, so each original JSON payload
            # must follow its own timestamp — unconditionally (equal
            # lengths do not imply equal ordering).
            if seasonality_from_query is not None:
                empty_json = json_dumps_sorted({})
                aligned = np.full(len(timestamp_array), empty_json, dtype=object)
                positions = np.searchsorted(timestamp_array, original_timestamps)
                in_range = positions < len(timestamp_array)
                matched = np.zeros(len(original_timestamps), dtype=bool)
                matched[in_range] = (
                    timestamp_array[positions[in_range]] == original_timestamps[in_range]
                )
                aligned[positions[matched]] = seasonality_from_query[matched]
                seasonality_from_query = aligned

        # Determine final seasonality data and columns
        if seasonality_from_query is not None:
            # Use seasonality from query
            seasonality_data = seasonality_from_query
            seasonality_columns = seasonality_columns_from_query
        else:
            # Extract seasonality features from timestamps (standard behavior)
            seasonality_data = self._extract_seasonality(
                timestamp_array, self.config.seasonality_columns
            )
            seasonality_columns = self.config.seasonality_columns

        return {
            "timestamp": timestamp_array,
            "value": value_array,
            "seasonality_data": seasonality_data,
            "seasonality_columns": seasonality_columns,
        }

    def save(self, data: dict[str, np.ndarray]) -> int:
        """
        Save loaded data to _dtk_datapoints table.

        Args:
            data: Data dictionary from load()

        Returns:
            Number of rows inserted

        Example:
            >>> data = loader.load(from_date, to_date)
            >>> rows = loader.save(data)
            >>> print(f"Saved {rows} data points")
        """
        if len(data["timestamp"]) == 0:
            return 0

        interval = self.config.get_interval()

        return self.internal_manager.save_datapoints(
            metric_name=self.config.name,
            data=data,
            interval_seconds=interval.seconds,
            seasonality_columns=data["seasonality_columns"],
        )

    def load_and_save(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> int:
        """
        Load and save data in one operation with batching.

        If from_date is None, loads from last saved timestamp.
        If to_date is None, loads until now.

        Args:
            from_date: Start date (if None, use last saved timestamp)
            to_date: End date (if None, use now)

        Returns:
            Total number of rows inserted

        Example:
            >>> # Load from last saved point until now
            >>> rows = loader.load_and_save()
            >>>
            >>> # Load specific range
            >>> rows = loader.load_and_save(
            ...     from_date=datetime(2024, 1, 1),
            ...     to_date=datetime(2024, 1, 2)
            ... )
        """
        # Determine date range
        if from_date is None:
            # Get last saved timestamp
            last_ts = self.internal_manager.get_last_datapoint_timestamp(self.config.name)
            if last_ts:
                # Start from next interval after last timestamp
                interval = self.config.get_interval()
                from_date = last_ts + timedelta(seconds=interval.seconds)
            else:
                # No data yet - use loading_start_time from config if available
                if self.config.loading_start_time:
                    # Parse loading_start_time string (format: "YYYY-MM-DD HH:MM:SS" in UTC)
                    from_date = datetime.strptime(
                        self.config.loading_start_time, "%Y-%m-%d %H:%M:%S"
                    )  # naive UTC from config string
                else:
                    # No data and no loading_start_time - need to specify from_date
                    raise ValueError(
                        "No existing data for metric and no loading_start_time configured. "
                        "Please specify from_date for initial load or set loading_start_time in config."
                    )

        if to_date is None:
            to_date = now_utc_naive()

        # Load and save
        data = self.load(from_date, to_date, fill_gaps=True)
        return self.save(data)

    def _create_empty_result(self) -> dict[str, np.ndarray]:
        """Create empty result dictionary."""
        return {
            "timestamp": np.array([], dtype="datetime64[ms]"),
            "value": np.array([], dtype=np.float64),
            "seasonality_data": np.array([], dtype=object),
            "seasonality_columns": self.config.seasonality_columns,
        }

    def _fill_gaps(
        self,
        timestamps: np.ndarray,
        values: np.ndarray,
        from_date: datetime,
        to_date: datetime,
        interval_seconds: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Fill missing timestamps with NULL values.

        Generates full timestamp range based on interval and fills
        missing points.

        Args:
            timestamps: Existing timestamps
            values: Existing values
            from_date: Range start
            to_date: Range end
            interval_seconds: Interval in seconds

        Returns:
            Tuple of (filled_timestamps, filled_values)
        """
        # Generate full timestamp range
        start_ts = np.datetime64(from_date, "ms")
        end_ts = np.datetime64(to_date, "ms")
        interval_delta = np.timedelta64(interval_seconds, "s")

        # Create full range
        full_timestamps = np.arange(start_ts, end_ts, interval_delta)

        if len(timestamps) == 0:
            # No data at all - return full range with NaN
            return full_timestamps, np.full(len(full_timestamps), np.nan)

        # Create mapping from existing timestamps to values
        ts_to_value = dict(zip(timestamps, values, strict=True))

        # Fill values for full range
        filled_values = np.array(
            [ts_to_value.get(ts, np.nan) for ts in full_timestamps],
            dtype=np.float64,
        )

        return full_timestamps, filled_values

    def _extract_seasonality(
        self,
        timestamps: np.ndarray,
        seasonality_columns: list[str],
    ) -> np.ndarray:
        """
        Extract seasonality features from timestamps.

        Args:
            timestamps: Array of datetime64 timestamps
            seasonality_columns: List of features to extract

        Returns:
            Array of JSON strings with seasonality data

        Supported features:
        - hour: Hour of day (0-23)
        - day_of_week: Day of week (0=Monday, 6=Sunday)
        - day_of_month: Day of month (1-31)
        - month: Month (1-12)
        - is_weekend: Boolean (Saturday=5, Sunday=6)
        - is_holiday: Boolean (requires holiday calendar - not implemented)
        """
        if len(timestamps) == 0:
            return np.array([], dtype=object)

        seasonality_data = []

        for ts in timestamps:
            # Convert numpy datetime64 to Python datetime
            ts_datetime = ts.astype("datetime64[s]").astype(datetime)

            features = {}

            for col in seasonality_columns:
                if col == "hour":
                    features["hour"] = ts_datetime.hour
                elif col == "day_of_week":
                    features["day_of_week"] = ts_datetime.weekday()  # 0=Monday
                elif col == "day_of_month":
                    features["day_of_month"] = ts_datetime.day
                elif col == "month":
                    features["month"] = ts_datetime.month
                elif col == "is_weekend":
                    features["is_weekend"] = ts_datetime.weekday() >= 5
                elif col == "is_holiday":
                    # TODO: Implement holiday calendar
                    features["is_holiday"] = False

            # Convert to JSON
            seasonality_data.append(json_dumps_sorted(features))

        return np.array(seasonality_data, dtype=object)
