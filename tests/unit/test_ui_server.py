"""Real-HTTP tests for the ``dtk ui`` local server (detectkit/ui/server.py).

Mirrors ``tests/unit/test_tune_server.py``'s pattern: build the server in-memory
(no filesystem project, no real DB), run ``serve_forever`` on a background
thread, and drive it with real ``urllib`` requests against ``127.0.0.1``.

Subprocess-spawning routes (``/api/run`` / ``/api/autotune`` / ``/api/unlock`` /
``/api/tune``) are exercised by monkeypatching the module-level argv builders
(``_pipeline_argv`` / ``_tune_argv``) to trivial ``python -c ...`` one-liners —
this proves the job lifecycle (spawn -> pump -> status/log polling -> stop)
without ever invoking the real ``dtk`` CLI or touching a database.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

import detectkit.ui.jobs as ui_jobs
import detectkit.ui.server as ui_server
from detectkit.cli.main import cli
from detectkit.config.metric_config import AlertConfig, MetricConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.ui.jobs import JobManager
from detectkit.ui.server import build_ui_server

INTERVAL_S = 3600


class _StubManager:
    """Minimal InternalTablesManager stand-in serving one fixed series.

    Good enough for both ``build_overview_payload`` and ``build_report_payload``
    (the two DB-touching routes) — the exact numbers don't matter for these
    server-level tests, only that both render without raising.
    """

    def __init__(self, n: int = 30) -> None:
        base = datetime(2026, 1, 1)
        self._times = [base + timedelta(hours=i) for i in range(n)]
        self._ts = np.array([np.datetime64(t, "ms") for t in self._times])
        self._val = np.full(n, 10.0)
        self._det_rows = [
            {
                "timestamp": t,
                "detector_id": "det1",
                "detector_name": "MADDetector",
                "is_anomaly": False,
                "confidence_lower": 9.0,
                "confidence_upper": 11.0,
                "value": 10.0,
                "detection_metadata": {},
            }
            for t in self._times
        ]

    def get_last_datapoint_timestamp(self, metric_name):  # noqa: ARG002
        return self._times[-1]

    def get_first_datapoint_timestamp(self, metric_name):  # noqa: ARG002
        return self._times[0]

    def check_lock(self, metric_name, detector_id, process_type):  # noqa: ARG002
        return None

    def load_datapoints(self, metric_name, from_timestamp=None, to_timestamp=None):  # noqa: ARG002
        ts, val = self._ts, self._val
        mask = np.ones(len(ts), dtype=bool)
        if from_timestamp is not None:
            mask &= ts >= np.datetime64(from_timestamp, "ms")
        if to_timestamp is not None:
            mask &= ts < np.datetime64(to_timestamp, "ms")
        return {
            "timestamp": ts[mask],
            "value": val[mask],
            "seasonality_data": np.array(["{}"] * int(mask.sum()), dtype=object),
            "seasonality_columns": [],
        }

    def load_detections(
        self, metric_name, detector_id=None, from_timestamp=None, to_timestamp=None  # noqa: ARG002
    ):
        out = []
        for r in self._det_rows:
            if from_timestamp is not None and r["timestamp"] < from_timestamp:
                continue
            if to_timestamp is not None and r["timestamp"] >= to_timestamp:
                continue
            out.append(r)
        return out


def _metrics(names: list[str]) -> list[tuple[Path, MetricConfig]]:
    return [
        (
            Path("metrics") / f"{name}.yml",
            MetricConfig(
                name=name,
                interval="1h",
                query="SELECT 1",
                alerting=[AlertConfig(channels=["slack"], consecutive_anomalies=1)],
            ),
        )
        for name in names
    ]


def _build(tmp_path: Path, *, project_name: str = "proj", metrics=None, **kwargs):
    project_config = ProjectConfig(name=project_name, default_profile="p")
    return build_ui_server(
        project_config=project_config,
        project_root=tmp_path,
        metrics=metrics if metrics is not None else _metrics(["orders"]),
        internal_manager=_StubManager(),
        initial_window="7d",
        echo=lambda *_a: None,
        **kwargs,
    )


def _serve(server) -> threading.Thread:
    th = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    th.start()
    return th


def _teardown(server) -> None:
    """Stop any spawned subprocess before closing the server (avoid leaking them)."""
    server.jobs.shutdown()
    try:
        server.shutdown()
    except Exception:
        pass
    server.server_close()


def _get(url: str):
    return urllib.request.urlopen(url, timeout=5)


def _post(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=5)


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ── auth ──────────────────────────────────────────────────────────────────────


def test_wrong_or_missing_token_rejected_on_every_verb(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base = url.split("/?")[0]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(f"{base}/?token=WRONG")
        assert ei.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(f"{base}/")  # no token at all
        assert ei.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/run?token=WRONG", {"select": "*", "steps": ["load"]})
        assert ei.value.code == 403
    finally:
        _teardown(server)


# ── GET / (shell) ─────────────────────────────────────────────────────────────


def test_index_page_has_project_name_and_dtk_ui_marker(tmp_path):
    server, url = _build(tmp_path, project_name="Acme Co")
    _serve(server)
    try:
        html = _get(url).read().decode()
        assert "Acme Co" in html
        assert "__DTK_UI__" in html
    finally:
        _teardown(server)


# ── GET /api/overview ─────────────────────────────────────────────────────────


def test_overview_returns_metric_rows(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        payload = json.loads(_get(f"{base}/api/overview?token={token}&window=all").read())
        assert payload["metrics"][0]["name"] == "orders"
        assert payload["project"] == "proj"
    finally:
        _teardown(server)


def test_overview_bad_window_returns_400(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(f"{base}/api/overview?token={token}&window=bogus")
        assert ei.value.code == 400
    finally:
        _teardown(server)


# ── GET /metric/<name> ────────────────────────────────────────────────────────


def test_metric_report_renders_and_unknown_metric_404s(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        html = _get(f"{base}/metric/orders?token={token}&window=all").read().decode()
        assert "__DTK_REPORT__" in html
        with pytest.raises(urllib.error.HTTPError) as ei:
            _get(f"{base}/metric/does-not-exist?token={token}")
        assert ei.value.code == 404
    finally:
        _teardown(server)


# ── POST /api/run — lifecycle, log offset paging, exclusivity, validation ────


def test_run_job_transitions_to_failed_with_log_lines_and_offset_paging(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_pipeline_argv",
        lambda **kw: [  # noqa: ARG005
            sys.executable,
            "-c",
            "print('line1'); print('line2'); import sys; sys.exit(1)",
        ],
    )
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        r = _post(
            f"{base}/api/run?token={token}",
            {"select": "*", "steps": ["load", "detect", "alert"]},
        )
        job_id = json.loads(r.read())["job_id"]

        def _job_status() -> str:
            return json.loads(_get(f"{base}/api/job/{job_id}?token={token}").read())["status"]

        assert _wait_until(lambda: _job_status() != "running")
        snap = json.loads(_get(f"{base}/api/job/{job_id}?token={token}").read())
        assert snap["status"] == "failed"
        assert snap["returncode"] == 1
        assert "line1" in snap["lines"]
        assert "line2" in snap["lines"]

        # Offset paging: re-polling from next_offset yields no duplicate lines.
        snap2 = json.loads(
            _get(f"{base}/api/job/{job_id}?token={token}&offset={snap['next_offset']}").read()
        )
        assert snap2["lines"] == []
        assert snap2["next_offset"] == snap["next_offset"]
    finally:
        _teardown(server)


def test_second_run_while_one_is_running_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_pipeline_argv",
        lambda **kw: [sys.executable, "-c", "import time; time.sleep(3)"],  # noqa: ARG005
    )
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        r1 = _post(f"{base}/api/run?token={token}", {"select": "*", "steps": ["load"]})
        assert r1.status == 200
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/run?token={token}", {"select": "*", "steps": ["load"]})
        assert ei.value.code == 400
        assert "already running" in ei.value.read().decode()
    finally:
        _teardown(server)


def test_run_validation_rejects_bad_steps_and_bad_date(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/run?token={token}", {"select": "*", "steps": ["bogus"]})
        assert ei.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(
                f"{base}/api/run?token={token}",
                {"select": "*", "steps": ["load"], "from": "not-a-date"},
            )
        assert ei.value.code == 400
    finally:
        _teardown(server)


# ── POST /api/tune ────────────────────────────────────────────────────────────


def test_tune_unknown_metric_returns_400(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/tune?token={token}", {"metric": "does-not-exist"})
        assert ei.value.code == 400
    finally:
        _teardown(server)


def test_tune_url_timeout_returns_400_and_kills_process(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_tune_argv",
        lambda **kw: [sys.executable, "-c", "import time; time.sleep(5)"],  # noqa: ARG005
    )
    server, url = _build(tmp_path, tune_url_timeout=1.0)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/tune?token={token}", {"metric": "orders"})
        assert ei.value.code == 400

        jobs = json.loads(_get(f"{base}/api/jobs?token={token}").read())["jobs"]
        assert jobs and jobs[0]["kind"] == "tune"
        job_id = jobs[0]["id"]

        def _job_status() -> str:
            return json.loads(_get(f"{base}/api/job/{job_id}?token={token}").read())["status"]

        # The handler already called stop() before replying; the process
        # should reach "stopped" quickly once its grace-period thread reaps it.
        assert _wait_until(lambda: _job_status() != "running")
        assert _job_status() == "stopped"
    finally:
        _teardown(server)


# ── POST /api/job/<id>/stop ───────────────────────────────────────────────────


def test_stop_endpoint_stops_a_sleeping_job(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_pipeline_argv",
        lambda **kw: [sys.executable, "-c", "import time; time.sleep(5)"],  # noqa: ARG005
    )
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        r = _post(f"{base}/api/run?token={token}", {"select": "*", "steps": ["load"]})
        job_id = json.loads(r.read())["job_id"]

        # POST /api/job/<id>/stop is sent with no JSON body.
        r2 = _post(f"{base}/api/job/{job_id}/stop?token={token}")
        assert json.loads(r2.read()) == {"ok": True}

        def _job_status() -> str:
            return json.loads(_get(f"{base}/api/job/{job_id}?token={token}").read())["status"]

        assert _wait_until(lambda: _job_status() != "running")
        assert _job_status() == "stopped"

        # Stopping again (already stopped) is refused.
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/job/{job_id}/stop?token={token}")
        assert ei.value.code == 400
    finally:
        _teardown(server)


def test_stop_unknown_job_returns_400(tmp_path):
    server, url = _build(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(f"{base}/api/job/deadbeef/stop?token={token}")
        assert ei.value.code == 400
    finally:
        _teardown(server)


# ── GET /api/jobs ─────────────────────────────────────────────────────────────


def test_jobs_list_is_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ui_server,
        "_tune_argv",
        lambda **kw: [  # noqa: ARG005
            sys.executable,
            "-c",
            "print('Tuner: http://127.0.0.1:9999/?token=x')",
        ],
    )
    server, url = _build(tmp_path, metrics=_metrics(["orders", "signups", "billing"]))
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        for name in ["orders", "signups", "billing"]:
            r = _post(f"{base}/api/tune?token={token}", {"metric": name})
            assert r.status == 200
        jobs = json.loads(_get(f"{base}/api/jobs?token={token}").read())["jobs"]
        labels = [j["label"] for j in jobs]
        assert labels == ["tune --select billing", "tune --select signups", "tune --select orders"]
    finally:
        _teardown(server)


def test_job_manager_caps_retained_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_jobs, "_MAX_JOBS", 2)
    manager = JobManager()
    ids = []
    for i in range(3):
        job = manager.spawn(
            "run", f"run {i}", [sys.executable, "-c", "print('x')"], cwd=tmp_path, env={}
        )
        ids.append(job.id)
        # Wait for completion before spawning the next one, so the cap logic
        # isn't racing subprocess completion.
        assert _wait_until(lambda: manager.get(job.id).status != "running")  # noqa: B023
    snapshots = manager.list_snapshots()
    assert len(snapshots) == 2
    assert [s["id"] for s in snapshots] == [ids[2], ids[1]]  # newest first, oldest capped out


def test_spawn_pipeline_gate_is_atomic_under_contention(tmp_path):
    """N simultaneous spawn_pipeline calls admit exactly one job (TOCTOU guard)."""
    manager = JobManager()
    argv = [sys.executable, "-c", "import time; time.sleep(3)"]
    barrier = threading.Barrier(6)
    results: list[object] = []
    results_lock = threading.Lock()

    def _attempt() -> None:
        barrier.wait()
        job = manager.spawn_pipeline("run", "run *", argv, cwd=tmp_path, env={})
        with results_lock:
            results.append(job)

    threads = [threading.Thread(target=_attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    try:
        admitted = [j for j in results if j is not None]
        assert len(results) == 6
        assert len(admitted) == 1
    finally:
        manager.shutdown()


def test_tune_reclick_same_metric_reuses_running_session(tmp_path, monkeypatch):
    """A second /api/tune for the same metric returns the live session's URL;
    a different metric still gets its own tuner."""
    monkeypatch.setattr(
        ui_server,
        "_tune_argv",
        lambda **kw: [  # noqa: ARG005
            sys.executable,
            "-u",
            "-c",
            "import time; print('  Tuner: http://127.0.0.1:1/?token=x'); time.sleep(30)",
        ],
    )
    server, url = _build(tmp_path, metrics=_metrics(["orders", "signups"]))
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        first = json.loads(_post(f"{base}/api/tune?token={token}", {"metric": "orders"}).read())
        again = json.loads(_post(f"{base}/api/tune?token={token}", {"metric": "orders"}).read())
        assert again["job_id"] == first["job_id"]
        assert again["url"] == first["url"]
        other = json.loads(_post(f"{base}/api/tune?token={token}", {"metric": "signups"}).read())
        assert other["job_id"] != first["job_id"]
    finally:
        _teardown(server)


def test_job_log_offsets_keep_streaming_past_buffer_cap(tmp_path, monkeypatch):
    """Poll offsets are absolute over the job's lifetime, so a job more verbose
    than the buffer cap keeps streaming instead of going silent at the cap."""
    monkeypatch.setattr(ui_jobs, "_MAX_LINES", 50)
    manager = JobManager()
    job = manager.spawn(
        "run",
        "run *",
        [sys.executable, "-c", "for i in range(120): print(f'line{i}')"],
        cwd=tmp_path,
        env={},
    )
    assert _wait_until(lambda: manager.get(job.id).status != "running")
    snap = manager.snapshot(job, 0)
    assert snap["next_offset"] == 120
    assert snap["lines"] == [f"line{i}" for i in range(70, 120)]  # last 50 retained
    # A poller that had consumed up to absolute line 100 gets only the tail.
    tail = manager.snapshot(job, 100)
    assert tail["lines"] == [f"line{i}" for i in range(100, 120)]
    assert tail["next_offset"] == 120
    # Fully caught up: nothing new, offset stable.
    done = manager.snapshot(job, snap["next_offset"])
    assert done["lines"] == []
    assert done["next_offset"] == 120


# ── CLI smoke test ────────────────────────────────────────────────────────────


def test_dtk_ui_help_smoke():
    runner = CliRunner()
    result = runner.invoke(cli, ["ui", "--help"])
    assert result.exit_code == 0
    assert "--select" in result.output
    assert "--window" in result.output
    assert "--no-open" in result.output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
