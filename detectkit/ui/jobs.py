"""Subprocess registry + output pumping for the ``dtk ui`` control panel.

The server never runs the pipeline in-process — every ``Run`` / ``Autotune`` /
``Unlock`` / ``Clean`` / ``Tune`` click spawns the real ``dtk`` CLI as a
subprocess (``python -m detectkit.cli.main ...``), exactly as if typed at a
terminal. This module only
tracks those subprocesses: pumping their merged stdout/stderr into an in-memory
line buffer the page polls, and reporting status/return code.
"""

from __future__ import annotations

import secrets
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Cap on retained stdout/stderr lines per job — a runaway/verbose process must
# not grow memory unboundedly; the oldest lines are dropped once the cap is hit.
_MAX_LINES = 5000
# Cap on retained jobs — the drawer only ever needs recent history.
_MAX_JOBS = 20
# Grace period between SIGTERM and SIGKILL when stopping a job.
_STOP_GRACE_SECONDS = 5.0


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


@dataclass
class Job:
    """One spawned subprocess and its captured output.

    All mutable fields (``lines``, ``status``, ``returncode``, ``url``,
    ``finished_at``, ``stop_requested``) are guarded by ``lock`` — the pump
    thread writes them, request-handler threads read/poll them.
    """

    id: str
    kind: str  # "run" | "autotune" | "unlock" | "clean" | "tune"
    label: str
    argv: list[str]
    proc: subprocess.Popen[str]
    started_at: int
    metric: str | None = None  # tune jobs: the metric being tuned (dedup key)
    lock: threading.Lock = field(default_factory=threading.Lock)
    lines: list[str] = field(default_factory=list)
    # Count of lines dropped off the front of ``lines`` once the buffer cap is
    # hit. Poll offsets are ABSOLUTE line indices (dropped + buffered), so a
    # verbose job keeps streaming past the cap instead of the poller's offset
    # pinning at the buffer length and never advancing again.
    dropped: int = 0
    truncated: bool = False
    status: str = "running"  # running | done | failed | stopped
    returncode: int | None = None
    url: str | None = None
    finished_at: int | None = None
    stop_requested: bool = False


def _pump(job: Job) -> None:
    """Read *job*'s merged stdout line by line into its buffer until it exits."""
    assert job.proc.stdout is not None
    try:
        for raw_line in job.proc.stdout:
            line = raw_line.rstrip("\n")
            with job.lock:
                job.lines.append(line)
                if len(job.lines) > _MAX_LINES:
                    job.lines.pop(0)
                    job.dropped += 1
                    job.truncated = True
    finally:
        returncode = job.proc.wait()
        with job.lock:
            job.returncode = returncode
            if job.stop_requested:
                job.status = "stopped"
            else:
                job.status = "done" if returncode == 0 else "failed"
            job.finished_at = _now_ms()


class JobManager:
    """In-memory registry of spawned CLI subprocesses (last :data:`_MAX_JOBS`)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Serializes the check-and-spawn of pipeline jobs (run/autotune/unlock)
        # so two near-simultaneous POSTs can't both pass the single-job gate
        # (spawn_pipeline). Separate from _lock: spawn() acquires _lock
        # internally, so holding _gate around it must not self-deadlock.
        self._gate = threading.Lock()
        self._jobs: list[Job] = []

    def spawn(
        self,
        kind: str,
        label: str,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        metric: str | None = None,
    ) -> Job:
        """Start *argv* as a subprocess and begin pumping its output.

        Never called while holding a DB lock — spawning is fire-and-forget;
        the caller returns the job id immediately and polls for progress.
        """
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        job = Job(
            id=secrets.token_hex(4),
            kind=kind,
            label=label,
            argv=list(argv),
            proc=proc,
            started_at=_now_ms(),
            metric=metric,
        )
        with self._lock:
            self._jobs.append(job)
            if len(self._jobs) > _MAX_JOBS:
                # Evict the oldest *finished* job — never a running one, which
                # would orphan its process (untracked by stop()/shutdown()).
                # If everything is still running, the registry briefly exceeds
                # the cap rather than losing track of a live subprocess.
                for i, old in enumerate(self._jobs):
                    with old.lock:
                        still_running = old.status == "running"
                    if not still_running:
                        self._jobs.pop(i)
                        break
        threading.Thread(target=_pump, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            for job in self._jobs:
                if job.id == job_id:
                    return job
        return None

    def set_url(self, job: Job, url: str) -> None:
        """Record the tuner URL a "tune" job reported on its stdout."""
        with job.lock:
            job.url = url

    def snapshot(self, job: Job, offset: int = 0) -> dict[str, Any]:
        """``{id, kind, label, status, returncode, url, next_offset, lines}``.

        ``offset`` / ``next_offset`` are ABSOLUTE line indices over the job's
        whole lifetime (``dropped + buffered``), not indices into the current
        buffer — otherwise a job more verbose than :data:`_MAX_LINES` would pin
        the poller's offset at the buffer length and the stream would go silent
        forever. Lines that already fell off the front are simply gone
        (``truncated=True``), matching a live terminal's scrollback.
        """
        with job.lock:
            lines = list(job.lines)
            dropped = job.dropped
            status = job.status
            returncode = job.returncode
            url = job.url
        total = dropped + len(lines)
        start = max(dropped, min(offset, total))
        return {
            "id": job.id,
            "kind": job.kind,
            "label": job.label,
            "status": status,
            "returncode": returncode,
            "url": url,
            "next_offset": total,
            "lines": lines[start - dropped :],
        }

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Every job's summary (no ``lines``), newest first."""
        with self._lock:
            jobs = list(self._jobs)
        out = []
        for job in reversed(jobs):
            with job.lock:
                out.append(
                    {
                        "id": job.id,
                        "kind": job.kind,
                        "label": job.label,
                        "status": job.status,
                        "returncode": job.returncode,
                        "url": job.url,
                        "started_at": job.started_at,
                        "finished_at": job.finished_at,
                    }
                )
        return out

    def spawn_pipeline(
        self,
        kind: str,
        label: str,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> Job | None:
        """Atomically spawn a pipeline job, or return ``None`` if one is running.

        The busy check and the spawn happen under one gate, so two
        near-simultaneous requests can't both observe "idle" and each start a
        subprocess (the plain check-then-``spawn()`` sequence is a TOCTOU race
        across the server's request threads).
        """
        with self._gate:
            if self.pipeline_active():
                return None
            return self.spawn(kind, label, argv, cwd=cwd, env=env)

    def running_tune_for(self, metric: str) -> Job | None:
        """The still-running tune job for *metric*, if any (dedup for /api/tune)."""
        with self._lock:
            jobs = list(self._jobs)
        for job in jobs:
            with job.lock:
                if job.kind == "tune" and job.metric == metric and job.status == "running":
                    return job
        return None

    def pipeline_active(self) -> bool:
        """True when a non-``tune`` job (run/autotune/unlock/clean) is still running.

        Tune jobs are excluded: multiple concurrent tuners are fine (each
        tunes a different metric, no pipeline lock involved), but Run/Autotune/
        Unlock/Clean all mutate the same DB-level state, so the panel only
        ever lets one of those run at a time.
        """
        with self._lock:
            jobs = list(self._jobs)
        for job in jobs:
            with job.lock:
                if job.kind != "tune" and job.status == "running":
                    return True
        return False

    def stop(self, job_id: str) -> bool:
        """Terminate a running job (grace period, then kill). False if not running."""
        job = self.get(job_id)
        if job is None:
            return False
        with job.lock:
            if job.status != "running":
                return False
            job.stop_requested = True
        try:
            job.proc.terminate()
        except Exception:
            pass

        def _grace() -> None:
            try:
                job.proc.wait(timeout=_STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    job.proc.kill()
                except Exception:
                    pass

        threading.Thread(target=_grace, daemon=True).start()
        return True

    def wait_for_line(
        self, job: Job, predicate: Callable[[str], bool], timeout: float
    ) -> str | None:
        """Block (polling) until a line matching *predicate* appears, or *timeout*.

        Returns ``None`` on timeout or if the job stops running before a
        matching line appears. Used by ``POST /api/tune`` to wait for the
        ``Tuner: <url>`` line ``serve_tuner`` echoes.
        """
        deadline = time.monotonic() + timeout
        checked = 0
        while True:
            with job.lock:
                new_lines = job.lines[checked:]
                checked = len(job.lines)
                status = job.status
            for line in new_lines:
                if predicate(line):
                    return line
            if status != "running":
                return None
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    def shutdown(self) -> None:
        """Terminate every still-running job (grace period, then kill)."""
        with self._lock:
            jobs = list(self._jobs)
        running = []
        for job in jobs:
            with job.lock:
                if job.status != "running":
                    continue
            try:
                job.proc.terminate()
            except Exception:
                pass
            running.append(job)
        deadline = time.monotonic() + _STOP_GRACE_SECONDS
        for job in running:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                job.proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    job.proc.kill()
                except Exception:
                    pass
