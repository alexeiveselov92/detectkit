"""Unit tests for the BigQuery source-only backend.

BigQuery has no in-process fake (the goccy/bigquery-emulator is a Docker
service — exercised by ``tests/integration/test_bigquery_emulator.py``), so
the live end-to-end path is integration-tier. Everything decision-shaped is
still unit-testable without a network: the client-kwargs / auth resolution
seam (:meth:`_client_kwargs`), the per-query job config
(:meth:`_job_config`), the row conversion in :meth:`execute_query` (against
real ``google.cloud.bigquery.table.Row`` objects), and the eager ``SELECT 1``
connect probe (against a stubbed ``bigquery.Client``).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("google.cloud.bigquery")

from google.cloud import bigquery  # noqa: E402
from google.cloud.bigquery.table import Row  # noqa: E402

from detectkit.database.bigquery_manager import BigQuerySourceManager  # noqa: E402


def _mgr(**kwargs: Any) -> BigQuerySourceManager:
    """Build a manager without connecting (skip __init__'s client + probe)."""
    mgr = BigQuerySourceManager.__new__(BigQuerySourceManager)
    defaults: dict[str, Any] = {
        "project": "proj",
        "credentials_json_path": None,
        "location": None,
        "dataset": None,
        "api_endpoint": None,
        "settings": {},
    }
    defaults.update(kwargs)
    for name, value in defaults.items():
        setattr(mgr, f"_{name}", value)
    mgr._closed = False
    return mgr


def _write_service_account_json(tmp_path) -> str:
    """Write a syntactically valid service-account key file with a real RSA key."""
    import json

    cryptography = pytest.importorskip("cryptography")  # noqa: F841
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    info = {
        "type": "service_account",
        "project_id": "proj",
        "private_key_id": "kid",
        "private_key": pem,
        "client_email": "svc@proj.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    path = tmp_path / "sa.json"
    path.write_text(json.dumps(info))
    return str(path)


# ── _client_kwargs seam (no network) ─────────────────────────────────────────


class TestClientKwargs:
    def test_project_only_uses_adc(self):
        """No key file, no endpoint -> ADC: the client resolves credentials itself."""
        kw = _mgr()._client_kwargs()
        assert kw == {"project": "proj"}

    def test_location_included_when_set(self):
        kw = _mgr(location="EU")._client_kwargs()
        assert kw["location"] == "EU"

    def test_service_account_key_file(self, tmp_path):
        from google.oauth2 import service_account

        path = _write_service_account_json(tmp_path)
        kw = _mgr(credentials_json_path=path)._client_kwargs()
        assert isinstance(kw["credentials"], service_account.Credentials)
        assert kw["credentials"].service_account_email == "svc@proj.iam.gserviceaccount.com"

    def test_api_endpoint_switches_to_anonymous_credentials(self):
        """The plain-http emulator path must not attempt an ADC lookup."""
        from google.auth.credentials import AnonymousCredentials

        kw = _mgr(api_endpoint="http://localhost:9050")._client_kwargs()
        assert isinstance(kw["credentials"], AnonymousCredentials)
        assert kw["client_options"] == {"api_endpoint": "http://localhost:9050"}

    def test_https_api_endpoint_keeps_adc(self):
        """An https endpoint override (regional rep endpoint, Private Service
        Connect) is a real authenticated Google endpoint — ADC applies, NOT
        anonymous credentials (found in review: anonymous would 401 exactly
        where key files are organizationally banned)."""
        kw = _mgr(api_endpoint="https://bigquery.eu.rep.googleapis.com")._client_kwargs()
        assert "credentials" not in kw
        assert kw["client_options"] == {"api_endpoint": "https://bigquery.eu.rep.googleapis.com"}

    def test_key_file_wins_over_api_endpoint_anonymous(self, tmp_path):
        """An explicit key file is used even when api_endpoint is set."""
        from google.oauth2 import service_account

        path = _write_service_account_json(tmp_path)
        kw = _mgr(credentials_json_path=path, api_endpoint="http://localhost:9050")._client_kwargs()
        assert isinstance(kw["credentials"], service_account.Credentials)
        assert kw["client_options"] == {"api_endpoint": "http://localhost:9050"}


# ── _job_config seam ─────────────────────────────────────────────────────────


class TestJobConfig:
    def test_trivial_config_is_none(self):
        assert _mgr()._job_config() is None

    def test_dataset_becomes_default_dataset(self):
        config = _mgr(dataset="analytics")._job_config()
        assert config.default_dataset == bigquery.DatasetReference("proj", "analytics")

    def test_settings_apply_as_job_config_attributes(self):
        config = _mgr(settings={"maximum_bytes_billed": 10_000_000})._job_config()
        assert config.maximum_bytes_billed == 10_000_000

    def test_unknown_setting_key_rejected(self):
        """A typo'd settings key must fail loudly, not be a silent no-op attr."""
        with pytest.raises(ValueError, match="maximum_bytes_billed"):
            _mgr(settings={"maximum_bytes_biled": 1})._job_config()


# ── execute_query row conversion + close, against a stub client ──────────────


class _StubClient:
    """Stands in for bigquery.Client: records queries, returns canned rows."""

    def __init__(self, rows: list[Row] | None = None):
        self.rows = rows or []
        self.queries: list[str] = []
        self.job_configs: list[Any] = []
        self.retries: list[Any] = []
        self.job_retries: list[Any] = []
        self.close_calls = 0

    def query(
        self, query: str, job_config: Any = None, retry: Any = None, job_retry: Any = None
    ) -> _StubJob:
        self.queries.append(query)
        self.job_configs.append(job_config)
        self.retries.append(retry)
        self.job_retries.append(job_retry)
        return _StubJob(self.rows)

    def close(self) -> None:
        self.close_calls += 1


class _StubJob:
    def __init__(self, rows: list[Row]):
        self._rows = rows

    def result(self, retry: Any = None, timeout: Any = None) -> list[Row]:
        return self._rows


class TestExecuteQuery:
    def test_rows_convert_to_column_keyed_dicts(self):
        rows = [
            Row((1.0, "a"), {"value": 0, "name": 1}),
            Row((2.0, "b"), {"value": 0, "name": 1}),
        ]
        mgr = _mgr()
        mgr._client = _StubClient(rows)
        out = mgr.execute_query("SELECT value, name FROM t")
        assert out == [{"value": 1.0, "name": "a"}, {"value": 2.0, "name": "b"}]
        assert mgr._client.queries == ["SELECT value, name FROM t"]

    def test_column_case_preserved_no_snowflake_fold(self):
        """The module docstring promises NO column-name folding (BigQuery
        preserves alias case) — a Snowflake-style isupper()->lower() fold
        copy-pasted in would rename VALUE_UC and fail here."""
        rows = [Row((1.0, 2.0), {"VALUE_UC": 0, "MixedCase": 1})]
        mgr = _mgr()
        mgr._client = _StubClient(rows)
        out = mgr.execute_query("SELECT value AS VALUE_UC, value AS MixedCase FROM t")
        assert out == [{"VALUE_UC": 1.0, "MixedCase": 2.0}]

    def test_retries_are_bounded(self):
        """Network-level errors must not be retried on the library's 600 s /
        2400 s defaults — an unreachable endpoint would stall a scheduled run
        for tens of minutes (found in review, verified empirically)."""
        mgr = _mgr()
        mgr._client = _StubClient()
        mgr.execute_query("SELECT 1")
        (retry,) = mgr._client.retries
        (job_retry,) = mgr._client.job_retries
        assert retry is not None and retry._timeout == mgr._RETRY_TIMEOUT_S
        assert job_retry is not None and job_retry._timeout == mgr._JOB_RETRY_TIMEOUT_S

    def test_job_config_threaded_into_query(self):
        mgr = _mgr(dataset="analytics")
        mgr._client = _StubClient()
        mgr.execute_query("SELECT 1")
        (config,) = mgr._client.job_configs
        assert config.default_dataset == bigquery.DatasetReference("proj", "analytics")

    def test_params_rejected(self):
        """BigQuery params are typed objects, not DB-API dicts — refuse loudly."""
        mgr = _mgr()
        mgr._client = _StubClient()
        with pytest.raises(ValueError, match="params"):
            mgr.execute_query("SELECT 1", params={"a": 1})

    def test_close_is_idempotent(self):
        mgr = _mgr()
        mgr._client = _StubClient()
        mgr.close()
        mgr.close()
        assert mgr._client.close_calls == 1


# ── eager connect probe (__init__ against a stubbed Client class) ────────────


class TestInitProbe:
    def test_init_builds_client_and_probes_select_1(self, monkeypatch):
        created: dict[str, Any] = {}

        class _FakeClient(_StubClient):
            def __init__(self, **kwargs):
                super().__init__()
                created["kwargs"] = kwargs
                created["client"] = self

        monkeypatch.setattr("google.cloud.bigquery.Client", _FakeClient)

        mgr = BigQuerySourceManager(project="proj", location="EU")
        assert created["kwargs"] == {"project": "proj", "location": "EU"}
        # The eager probe ran exactly once, before any load query — with a
        # fail-fast retry bound and job-level retry disabled.
        assert created["client"].queries == ["SELECT 1"]
        (retry,) = created["client"].retries
        assert retry is not None and retry._timeout == mgr._PROBE_TIMEOUT_S
        assert created["client"].job_retries == [None]
        mgr.close()

    def test_bad_settings_fail_at_construction(self, monkeypatch):
        """The probe applies _job_config, so a typo'd settings key fails the
        hybrid-pool build instead of the first load query."""

        # _StubClient(**kwargs) rejects kwargs; patch in a tolerant subclass.
        class _FakeClient(_StubClient):
            def __init__(self, **kwargs):
                super().__init__()

        monkeypatch.setattr("google.cloud.bigquery.Client", _FakeClient)
        with pytest.raises(ValueError, match="Unknown BigQuery query setting"):
            BigQuerySourceManager(project="proj", settings={"nope": 1})

    def test_failed_probe_closes_the_client(self, monkeypatch):
        """A probe failure must not leak the just-built client (the hybrid
        pool caches only the error — nothing else can close it)."""
        created: dict[str, Any] = {}

        class _FailingClient(_StubClient):
            def __init__(self, **kwargs):
                super().__init__()
                created["client"] = self

            def query(self, *args: Any, **kwargs: Any) -> _StubJob:
                raise RuntimeError("probe boom")

        monkeypatch.setattr("google.cloud.bigquery.Client", _FailingClient)
        with pytest.raises(RuntimeError, match="probe boom"):
            BigQuerySourceManager(project="proj")
        assert created["client"].close_calls == 1
