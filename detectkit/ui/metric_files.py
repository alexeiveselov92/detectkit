"""Metric YAML file create/update/delete for the ``dtk ui`` cockpit.

The single mutation seam behind the UI's metric-management routes. Mirrors
``tuning/config_writer.py``'s validate-before-write discipline: every mutation
validates the **full raw YAML text** through :class:`MetricConfig` (plus a
deep detector-params check via the factory) *before touching the filesystem*,
and every destructive step (update / delete) first archives the previous file
**verbatim** under ``metrics/.history/<metric>/`` — the same archive ``dtk
tune`` writes, which metric discovery deliberately excludes
(``config/validator.py``). Unlike ``config_writer`` there is no re-emit: the
user edits the raw YAML text in the browser and that text lands on disk,
comments intact (normalized only to end with a newline).

These functions are pure filesystem + validation; the UI server layers the
session bookkeeping (its in-memory ``(path, config)`` list) and locking on
top. None of this touches the database — rows keyed by a deleted or renamed
metric stay in the ``_dtk_*`` tables until ``dtk clean`` prunes them.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from detectkit.config.metric_config import MetricConfig
from detectkit.config.metric_io import (
    archive_metric_text,
    safe_metric_stem,
    unwrap_metric_mapping,
)
from detectkit.config.validator import discover_metric_files
from detectkit.detectors.factory import DetectorFactory

# Conservative charset for the filename derived from the metric name and for
# user-supplied folder parts: no path separators, no leading dot (hidden paths
# are excluded from discovery), nothing the filesystem could mangle.
_SAFE_PART_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


@dataclass(frozen=True)
class MetricWrite:
    """Result of a create/update: the file written and the validated config."""

    path: Path
    config: MetricConfig
    archived: Path | None = None


def text_digest(text: str) -> str:
    """Stable digest of a metric file's text — the editor's optimistic-concurrency token.

    ``GET /api/metric-source`` hands it out with the text; the editor echoes it
    back on save, and :func:`update_metric_file` refuses when the on-disk text
    no longer matches (a ``dtk tune`` Apply or another editor session landed in
    between), so a stale editor can't silently clobber a newer config.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_metric_text(text: str) -> MetricConfig:
    """Validate raw YAML text as a full metric config (flat or nested ``metric:`` form).

    Raises ``ValueError`` with a message fit for the editor's error pane —
    YAML syntax errors, non-mapping documents, and ``MetricConfig`` validation
    failures all land here. Detector params are additionally deep-validated by
    constructing each factory-known detector (``prophet``/``timesfm`` pass on
    config-level validation alone — the factory can't build them yet).
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError("metric config must be a non-empty YAML mapping")
    data = unwrap_metric_mapping(data)  # the nested `metric: { ... }` form
    try:
        config = MetricConfig.model_validate(data)
    except Exception as exc:
        raise ValueError(f"invalid metric config: {exc}") from exc
    _validate_detector_params(config)
    return config


def _validate_detector_params(config: MetricConfig) -> None:
    """Construct each factory-known detector so bad params fail at save, not at run.

    Mirrors the detect step's derivation (``get_algorithm_params`` +
    seasonality → ``DetectorFactory.create_from_config``). Types the factory
    doesn't know (the reserved ``prophet``/``timesfm``) are skipped — the
    config-level type check already accepted them.
    """
    for i, dc in enumerate(config.detectors):
        if dc.type not in DetectorFactory.DETECTOR_TYPES:
            continue
        try:
            params = dc.get_algorithm_params()
            seasonality = dc.get_seasonality_components()
            if seasonality is not None:
                params["seasonality_components"] = seasonality
            DetectorFactory.create_from_config({"type": dc.type, "params": params})
        except Exception as exc:
            raise ValueError(f"detector #{i + 1} ({dc.type}): {exc}") from exc


def _lenient_name_from_text(text: str) -> str | None:
    """The ``name:`` of a metric YAML text, or ``None`` when it can't be parsed.

    Lenient by design — a broken file can't collide by name (project validation
    surfaces it loudly elsewhere), and the result is only ever used for
    uniqueness checks and as a *sanitized* archive-directory key.
    """
    try:
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — unparseable files just don't participate
        return None
    if not isinstance(data, dict):
        return None
    name = unwrap_metric_mapping(data).get("name")
    return name if isinstance(name, str) else None


def _lenient_name(path: Path) -> str | None:
    """:func:`_lenient_name_from_text` for a file on disk (used by the uniqueness scan)."""
    try:
        return _lenient_name_from_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _ensure_unique_name(metrics_dir: Path, name: str, exclude: Path | None) -> None:
    """Refuse a name already used by another live metric YAML in the project.

    Checked against the **whole** ``metrics/`` tree (not just the UI session's
    selector-filtered list) — a duplicate name corrupts the shared ``_dtk_*``
    tables regardless of what the current session shows.
    """
    exclude_resolved = exclude.resolve() if exclude is not None else None
    for candidate in discover_metric_files(metrics_dir):
        if exclude_resolved is not None and candidate.resolve() == exclude_resolved:
            continue
        if _lenient_name(candidate) == name:
            raise ValueError(
                f"metric name '{name}' is already used by {candidate}; "
                "metric names must be unique across the project"
            )


def _safe_part(value: str, what: str) -> str:
    if not _SAFE_PART_RE.match(value):
        raise ValueError(
            f"{what} '{value}' can't be used in a file path — use letters, digits, "
            "'_', '-' or '.' (no leading dot, no path separators)"
        )
    return value


def _resolve_folder(metrics_dir: Path, folder: str) -> Path:
    """``metrics/<folder>`` with each component charset-checked (no ``..``, no hidden dirs)."""
    folder = folder.strip().strip("/")
    if not folder:
        return metrics_dir
    parts = [_safe_part(p, "folder component") for p in folder.split("/")]
    return metrics_dir.joinpath(*parts)


def _guard_editable(path: Path, metrics_dir: Path) -> None:
    """Only live metric YAMLs under ``metrics/`` are editable — never the archive."""
    try:
        parts = path.resolve().relative_to(metrics_dir.resolve()).parts
    except ValueError:
        raise ValueError(f"not a metric file under {metrics_dir}: {path}") from None
    if any(part.startswith(".") for part in parts):
        raise ValueError(f"refusing to edit an archived/hidden metric file: {path}")


def _normalized(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def create_metric_file(*, project_root: Path, text: str, folder: str = "") -> MetricWrite:
    """Validate *text* and write it as a new ``metrics/[<folder>/]<name>.yml``.

    Raises ``ValueError`` (writing nothing) on invalid YAML/config, a name
    already used elsewhere in the project, an unsafe folder, or a target file
    that already exists.
    """
    config = parse_metric_text(text)
    metrics_dir = project_root / "metrics"
    target_dir = _resolve_folder(metrics_dir, folder)
    filename = safe_metric_stem(config.name)
    path = target_dir / f"{filename}.yml"
    if path.exists():
        raise ValueError(f"file already exists: {_rel(path, project_root)}")
    _ensure_unique_name(metrics_dir, config.name, exclude=None)
    target_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalized(text), encoding="utf-8")
    return MetricWrite(path=path, config=config)


def update_metric_file(
    *, project_root: Path, path: Path, text: str, expected_digest: str | None = None
) -> MetricWrite:
    """Validate *text*, archive the previous file verbatim, then overwrite in place.

    A rename (the YAML's ``name:`` changed) is allowed — uniqueness is checked
    against every other live metric file. The archive is keyed by the **old**
    name (it is the old config being preserved). When *expected_digest* is
    given (the :func:`text_digest` of the text the editor was opened with), the
    write is refused if the on-disk text no longer matches — a ``dtk tune``
    Apply or another editor session saved in between, and silently overwriting
    it would lose that change. Raises ``ValueError`` without touching anything
    on a bad config or a stale digest; the archive is written only after the
    new text validates.
    """
    metrics_dir = project_root / "metrics"
    _guard_editable(path, metrics_dir)
    config = parse_metric_text(text)
    original_text = path.read_text(encoding="utf-8")
    if expected_digest is not None and text_digest(original_text) != expected_digest:
        raise ValueError(
            "the metric file changed on disk after this editor was opened "
            "(a dtk tune Apply or another editor session?) — nothing was written; "
            "reopen the metric to load the latest version"
        )
    _ensure_unique_name(metrics_dir, config.name, exclude=path)
    old_name = _lenient_name_from_text(original_text) or path.stem
    archived = archive_metric_text(project_root, old_name, original_text)
    path.write_text(_normalized(text), encoding="utf-8")
    return MetricWrite(path=path, config=config, archived=archived)


def delete_metric_file(*, project_root: Path, path: Path) -> Path:
    """Archive the file verbatim (``…-deleted.yml``) then remove it; return the archive path.

    Only the YAML file is removed — the metric's rows in the ``_dtk_*`` tables
    remain until ``dtk clean`` prunes them, and the archived copy makes the
    delete reversible by hand.
    """
    metrics_dir = project_root / "metrics"
    _guard_editable(path, metrics_dir)
    original_text = path.read_text(encoding="utf-8")
    name = _lenient_name_from_text(original_text) or path.stem
    archived = archive_metric_text(project_root, name, original_text, suffix="-deleted")
    path.unlink()
    return archived


def _rel(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()
