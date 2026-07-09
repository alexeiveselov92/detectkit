"""Shared low-level seams for metric YAML files.

Three tiny helpers that were previously re-implemented per caller and had
already started to drift (``tuning/config_writer.py``'s archive write had no
same-second collision handling; the nested-form unwrap lived in four copies):

- :func:`unwrap_metric_mapping` — the nested ``metric: {...}`` form accepted
  everywhere a metric YAML is read (``MetricConfig.from_yaml_file``, the tune
  write-back, the ``dtk ui`` editor).
- :func:`safe_metric_stem` — a metric name reduced to one safe path component
  (filenames, ``.history`` archive keys).
- :func:`archive_metric_text` — the ``metrics/.history/<metric>/`` verbatim
  archive convention shared by ``dtk tune``'s Apply and ``dtk ui``'s
  update/delete, collision-safe within one UTC second.

No imports from the rest of detectkit — safe to use from any layer.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_CHAR_RE = re.compile(r"[A-Za-z0-9_.\-]")


def unwrap_metric_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """The metric body of a parsed YAML mapping — unwraps the nested ``metric: {...}`` form.

    Returns the **same object reference** for the flat form and the nested
    body for the wrapped form, so in-place mutations (the tune write-back
    edits the body inside the original document) behave identically.
    """
    nested = data.get("metric")
    return nested if isinstance(nested, dict) else data


def safe_metric_stem(name: str) -> str:
    """A single safe path component for a metric name — sanitized, never refused.

    ``MetricConfig`` accepts names (unicode letters, a leading ``-``) that make
    unsafe or awkward filenames; rather than rejecting a valid metric, every
    character outside the safe set is replaced with ``_`` and leading dots or
    dashes are stripped. Path separators can never survive, so the result is
    always one component; a same-stem collision surfaces as "file already
    exists". Used for created files' stems and ``.history`` archive keys.
    """
    stem = "".join(c if _SAFE_CHAR_RE.fullmatch(c) else "_" for c in name)
    stem = stem.lstrip(".-")
    return stem or "metric"


def metric_stamp(now: datetime | None = None) -> str:
    """UTC filesystem-safe timestamp (``20260709T101530Z``) used in archive filenames."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def archive_metric_text(
    project_root: Path,
    metric_name: str,
    text: str,
    *,
    suffix: str = "",
    stamp: str | None = None,
    now: datetime | None = None,
) -> Path:
    """Write *text* verbatim into ``metrics/.history/<key>/`` and return the path.

    The directory key is the **sanitized** metric name (:func:`safe_metric_stem`)
    — at archive time the name can be attacker/editor-influenced free text
    (an on-disk ``name:`` changed after boot), and joining it raw into a path
    would let ``../`` or an absolute component escape ``metrics/.history/``.
    Two archives within the same UTC second get ``-1``, ``-2``, … suffixes so
    a tune Apply and a UI save landing together never overwrite each other's
    snapshot.
    """
    key = safe_metric_stem(metric_name)
    archive_dir = project_root / "metrics" / ".history" / key
    archive_dir.mkdir(parents=True, exist_ok=True)
    base = f"{key}-{stamp or metric_stamp(now)}{suffix}"
    archive_path = archive_dir / f"{base}.yml"
    counter = 1
    while archive_path.exists():
        archive_path = archive_dir / f"{base}-{counter}.yml"
        counter += 1
    archive_path.write_text(text, encoding="utf-8")
    return archive_path
