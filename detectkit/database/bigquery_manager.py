"""BigQuery **source-only** database manager.

BigQuery is supported as a hybrid-mode *source* (a metric's ``load`` SQL runs
against it) but **not** as a state backend: it implements only the minimal
:class:`~detectkit.database.source_manager.SourceDatabaseManager` contract
(connect + :meth:`execute_query` + :meth:`close`), with no DDL, upsert, lock or
internal-table machinery. :meth:`ProfileConfig.create_manager` refuses a
``bigquery`` profile as state and routes it here via
:meth:`ProfileConfig.create_source_manager`; the ``_dtk_*`` state lives in a
cheaper local backend (DuckDB/PostgreSQL/ClickHouse).

Behaviors that are deliberate and load-bearing:

- **Eager connectivity probe, with bounded retries.** ``bigquery.Client(...)``
  alone performs no network I/O, so construction runs a ``SELECT 1`` probe — a
  query with no table references processes 0 bytes and is free on on-demand
  billing — to fail fast on bad credentials/project at hybrid-pool build
  (parity with the other backends' eager connect). The probe also applies
  :meth:`_job_config`, so a typo in ``settings`` or a bad ``dataset`` surfaces
  immediately. The client library's default retry treats network-level errors
  (connection refused, DNS) as transient and would retry them for 10+ minutes;
  the probe caps that at ``_PROBE_TIMEOUT_S`` and load queries at
  ``_RETRY_TIMEOUT_S`` / ``_JOB_RETRY_TIMEOUT_S``, so an unreachable endpoint
  fails the run in seconds-to-minutes, not silently stalls it.
- **Auth resolution.** ``credentials_json_path`` (a service-account key file)
  when set; otherwise **Application Default Credentials** (gcloud ADC, an
  attached service account, or Workload Identity). A **plain-``http://``**
  ``api_endpoint`` — the BigQuery emulator — switches to anonymous credentials
  so no ADC lookup is attempted; an ``https://`` endpoint override (a regional
  ``*.rep.googleapis.com`` endpoint, Private Service Connect) is a real,
  authenticated Google endpoint and resolves auth exactly as above.
- **Timestamps.** BigQuery ``TIMESTAMP`` columns come back as tz-aware UTC
  datetimes — the loader converts tz-aware values to naive UTC since v0.62.0.
  ``DATETIME`` comes back naive and is taken verbatim; use ``TIMESTAMP`` (or
  cast) for the metric's ``timestamp`` column unless the naive values already
  are UTC.
- **No column-name folding.** Unlike Snowflake, BigQuery preserves the case of
  column aliases, so ``SELECT ts AS timestamp`` reaches the loader unchanged.

Billing note: on-demand queries bill a 10 MiB minimum of bytes processed per
referenced table, so frequent small monitoring queries are disproportionately
expensive — the whole point of hybrid mode is to load from BigQuery and keep
cheap state elsewhere. A ``settings: {maximum_bytes_billed: ...}`` guardrail
caps what a single load query may scan.
"""

from __future__ import annotations

from typing import Any

from detectkit.database.source_manager import SourceDatabaseManager


class BigQuerySourceManager(SourceDatabaseManager):
    """Read-only BigQuery connection for hybrid-mode source profiles.

    Constructs the client and runs the free ``SELECT 1`` probe eagerly (see
    the module docstring for the probe, auth resolution and timestamp rules).

    Args:
        project: GCP project id billed for the queries (e.g. ``"my-project"``)
        credentials_json_path: Path to a service-account JSON key file
            (unset -> Application Default Credentials)
        location: Job location (e.g. ``"EU"``; unset -> BigQuery infers it
            from the referenced datasets)
        dataset: Default dataset for unqualified table names in queries
        api_endpoint: Override the API endpoint — for the BigQuery emulator
            (e.g. ``"http://localhost:9050"``) or private endpoints; a
            plain-``http://`` endpoint without a key file switches auth to
            anonymous credentials (``https://`` endpoints authenticate
            normally via key file or ADC)
        settings: Extra ``QueryJobConfig`` attributes applied to every query
            (e.g. ``maximum_bytes_billed``, ``labels``, ``use_query_cache``);
            unknown attribute names are rejected at the probe
    """

    # The client library's DEFAULT_RETRY/DEFAULT_JOB_RETRY treat network-level
    # errors as transient and retry them for 600/2400 seconds — an unreachable
    # endpoint would stall a scheduled run for tens of minutes. These caps keep
    # the probe genuinely fail-fast and load queries bounded (long-RUNNING
    # queries are unaffected: waiting on a healthy job is not a retry).
    _PROBE_TIMEOUT_S = 30.0
    _RETRY_TIMEOUT_S = 120.0
    _JOB_RETRY_TIMEOUT_S = 600.0

    def __init__(
        self,
        project: str,
        credentials_json_path: str | None = None,
        location: str | None = None,
        dataset: str | None = None,
        api_endpoint: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise ImportError(
                "google-cloud-bigquery is not installed. "
                "Install with: pip install detectkit[bigquery]"
            ) from exc

        self._project = project
        self._credentials_json_path = credentials_json_path
        self._location = location
        self._dataset = dataset
        self._api_endpoint = api_endpoint
        self._settings = settings or {}

        self._closed = False
        self._client = bigquery.Client(**self._client_kwargs())
        try:
            self._probe()
        except Exception:
            # Don't leak the just-built client (and the HTTP session the probe
            # request lazily created) — the hybrid pool caches only the error.
            self.close()
            raise

    def _client_kwargs(self) -> dict[str, Any]:
        """Build ``bigquery.Client(...)`` kwargs without any network I/O.

        The testable seam: it resolves auth (service-account key file → ADC →
        anonymous for the emulator path) and includes ``location`` /
        ``client_options`` only when set.
        """
        kwargs: dict[str, Any] = {"project": self._project}

        if self._credentials_json_path is not None:
            from google.oauth2 import service_account

            kwargs["credentials"] = service_account.Credentials.from_service_account_file(
                self._credentials_json_path
            )
        elif self._api_endpoint is not None and self._api_endpoint.startswith("http://"):
            # Plain-HTTP endpoint = the emulator: skip the ADC lookup entirely
            # (it would fail on a machine with no gcloud auth). An https
            # endpoint override (regional/private) is a real, authenticated
            # Google endpoint and falls through to ADC below.
            from google.auth.credentials import AnonymousCredentials

            kwargs["credentials"] = AnonymousCredentials()
        # else: Application Default Credentials, resolved by the client itself.

        if self._location is not None:
            kwargs["location"] = self._location
        if self._api_endpoint is not None:
            kwargs["client_options"] = {"api_endpoint": self._api_endpoint}

        return kwargs

    def _job_config(self) -> Any:
        """Build the per-query ``QueryJobConfig``, or ``None`` when trivial.

        ``dataset`` becomes ``default_dataset`` (unqualified table names in the
        metric SQL resolve against it); each ``settings`` key must name a real
        ``QueryJobConfig`` property (typos would otherwise be silently ignored
        attributes — rejected here instead, surfacing at the connect probe).
        """
        if self._dataset is None and not self._settings:
            return None

        from google.cloud import bigquery

        config = bigquery.QueryJobConfig()
        if self._dataset is not None:
            config.default_dataset = bigquery.DatasetReference(self._project, self._dataset)
        for key, value in self._settings.items():
            if not isinstance(getattr(type(config), key, None), property):
                raise ValueError(
                    f"Unknown BigQuery query setting '{key}': settings keys must be "
                    f"QueryJobConfig attributes (e.g. maximum_bytes_billed, labels)"
                )
            setattr(config, key, value)
        return config

    def _probe(self) -> None:
        """Fail fast on bad credentials/project/settings at construction.

        ``SELECT 1`` references no table, processes 0 bytes and is free on
        on-demand billing; it exercises exactly the permission the loader
        needs (``bigquery.jobs.create`` on the project). Retries are capped
        at ``_PROBE_TIMEOUT_S`` (and job-level retry disabled), so an
        unreachable endpoint fails the pool build in seconds instead of the
        library default's 10+ minutes of connection-error retries.
        """
        from google.cloud.bigquery.retry import DEFAULT_RETRY

        retry = DEFAULT_RETRY.with_timeout(self._PROBE_TIMEOUT_S)
        self._client.query(
            "SELECT 1", job_config=self._job_config(), retry=retry, job_retry=None
        ).result(retry=retry, timeout=self._PROBE_TIMEOUT_S)

    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a read query and return all rows as column-keyed dicts.

        BigQuery takes typed ``ScalarQueryParameter`` objects rather than
        DB-API params; the loader renders its SQL with Jinja and always calls
        this param-less, so a non-empty ``params`` is rejected instead of
        being silently dropped. DDL/DML statements (used by tests to seed the
        emulator) return an empty row set.
        """
        if params:
            raise ValueError(
                "BigQuerySourceManager does not support query params; "
                "render values into the SQL instead (the loader always does)"
            )
        from google.cloud.bigquery.retry import DEFAULT_JOB_RETRY, DEFAULT_RETRY

        # Bounded retries (see the class constants): network-level errors stop
        # being retried after minutes, not tens of minutes. No `timeout=` on
        # result() — a long-running healthy query may legitimately take longer.
        retry = DEFAULT_RETRY.with_timeout(self._RETRY_TIMEOUT_S)
        rows = self._client.query(
            query,
            job_config=self._job_config(),
            retry=retry,
            job_retry=DEFAULT_JOB_RETRY.with_timeout(self._JOB_RETRY_TIMEOUT_S),
        ).result(retry=retry)
        return [dict(row.items()) for row in rows]

    def close(self) -> None:
        """Close the client's HTTP transport. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._client.close()
