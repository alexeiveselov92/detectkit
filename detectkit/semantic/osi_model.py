"""Lenient pydantic models for the OSI (Open Semantic Interchange) core spec.

These mirror the **verified** OSI v1.0 / 0.2.0.dev constructs (``core-spec/spec.md``)
just enough for detectkit's converter to read a model and resolve a metric — NOT
a full validator. Two deliberate choices keep this robust against an evolving
draft spec:

- ``extra="ignore"`` everywhere, so OSI fields detectkit doesn't use (and fields
  added by future spec revisions) never break parsing.
- Only the constructs the converter actually needs are typed; everything else is
  carried opaquely.

Verified shape (see ``reference_osi_spec_facts``):
``semantic_model`` → ``datasets`` (with **``source``** = physical
``database.schema.table`` or query) / ``relationships`` / ``metrics``; each may
carry ``ai_context`` and ``custom_extensions`` (``[{vendor_name, data}]`` where
``data`` is a JSON string). Expressions are ``{dialects: [{dialect, expression}]}``
over a fixed dialect set (``ANSI_SQL``/``SNOWFLAKE``/``MDX``/``TABLEAU``/
``DATABRICKS``/``MAQL`` — **no ClickHouse**). There is no grain field (time is only
``dimension.is_time``) and no ratio/derived metric *type* (a ratio is just SQL).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from detectkit.semantic.errors import OsiParseError

# The detectkit vendor namespace for ``custom_extensions[].vendor_name``. The
# ONE place the convention lives, shared by the importer (reads physical/grain
# overrides) and the exporter (writes the detect/alert config back).
DETECTKIT_VENDOR = "detectkit"


class _Lenient(BaseModel):
    """Base: ignore unknown OSI fields so an evolving draft spec can't break us."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class OsiCustomExtension(_Lenient):
    """A vendor extension: ``{vendor_name, data}`` where ``data`` is a JSON string."""

    vendor_name: str = ""
    data: str = ""

    def parsed(self) -> dict[str, Any]:
        """``data`` decoded from its JSON string (``{}`` if blank/invalid)."""
        if not self.data:
            return {}
        try:
            obj = json.loads(self.data)
            return obj if isinstance(obj, dict) else {}
        except (ValueError, TypeError):
            return {}


class _HasExtensions(_Lenient):
    custom_extensions: list[OsiCustomExtension] = Field(default_factory=list)

    def extension(self, vendor_name: str = DETECTKIT_VENDOR) -> dict[str, Any]:
        """The decoded ``data`` of the first extension for *vendor_name* (``{}`` if none)."""
        for ext in self.custom_extensions:
            if ext.vendor_name == vendor_name:
                return ext.parsed()
        return {}


class OsiDialectExpr(_Lenient):
    dialect: str = ""
    expression: str = ""


class OsiExpression(_Lenient):
    dialects: list[OsiDialectExpr] = Field(default_factory=list)

    def for_dialect(self, *preferred: str) -> str | None:
        """First expression matching one of *preferred* dialects (case-insensitive),
        falling back to the first available expression."""
        by_name = {d.dialect.upper(): d.expression for d in self.dialects if d.expression}
        for name in preferred:
            if name.upper() in by_name:
                return by_name[name.upper()]
        for d in self.dialects:
            if d.expression:
                return d.expression
        return None


class OsiDimension(_Lenient):
    is_time: bool = False


class OsiField(_HasExtensions):
    name: str = ""
    expression: OsiExpression | None = None
    dimension: OsiDimension | None = None
    ai_context: Any | None = None


class OsiMetric(_HasExtensions):
    name: str = ""
    expression: OsiExpression | None = None
    description: str | None = None
    ai_context: Any | None = None


class OsiRelationship(_HasExtensions):
    name: str = ""
    # ``from`` is a Python keyword → store as ``from_`` with the OSI alias.
    from_: str = Field(default="", alias="from")
    to: str = ""
    from_columns: list[str] = Field(default_factory=list)
    to_columns: list[str] = Field(default_factory=list)


class OsiDataset(_HasExtensions):
    name: str = ""
    # Physical binding: "database.schema.table" or a query (verified spec field).
    source: str = ""
    primary_key: list[str] = Field(default_factory=list)
    fields: list[OsiField] = Field(default_factory=list)

    def field(self, name: str) -> OsiField | None:
        return next((f for f in self.fields if f.name == name), None)


class OsiSemanticModel(_HasExtensions):
    name: str = ""
    ai_context: Any | None = None
    datasets: list[OsiDataset] = Field(default_factory=list)
    relationships: list[OsiRelationship] = Field(default_factory=list)
    metrics: list[OsiMetric] = Field(default_factory=list)

    def metric(self, name: str) -> OsiMetric | None:
        return next((m for m in self.metrics if m.name == name), None)

    def dataset(self, name: str) -> OsiDataset | None:
        return next((d for d in self.datasets if d.name == name), None)


def normalize_ai_context(raw: Any) -> dict[str, Any] | None:
    """Coerce an OSI ``ai_context`` (string OR ``{instructions, synonyms, examples}``)
    into detectkit's ``AiContextConfig`` shape, or ``None`` when empty.

    OSI allows ``ai_context`` to be a bare string (→ ``instructions``) or a struct;
    detectkit's ``ai_context`` accepts exactly the same, so this maps 1:1.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return {"instructions": s} if s else None
    if isinstance(raw, dict):
        out: dict[str, Any] = {}
        instr = raw.get("instructions")
        if isinstance(instr, str) and instr.strip():
            out["instructions"] = instr.strip()
        syn = raw.get("synonyms")
        if isinstance(syn, list):
            out["synonyms"] = [str(x).strip() for x in syn if str(x).strip()]
        ex = raw.get("examples")
        if isinstance(ex, list):
            out["examples"] = [str(x).strip() for x in ex if str(x).strip()]
        return out or None
    return None


def parse_osi_models(text: str, *, source: str = "<input>") -> list[OsiSemanticModel]:
    """Parse OSI YAML *text* into a list of :class:`OsiSemanticModel`.

    The text seam behind :func:`load_osi_models`: it takes the raw YAML string
    directly, so a caller with no file on disk — e.g. the ``dtk ui`` Builder's
    "From OSI" paste box, which hands the browser's textarea contents straight
    to the server — can parse a model without writing a temp file first.
    Accepts the canonical ``semantic_model:`` root (a list, per the OSI
    examples) as well as a single mapping or a bare list, for robustness.
    Raises :class:`OsiParseError` on empty/malformed text; *source* names the
    origin (a file path, or a caller-chosen marker like ``"<pasted OSI
    model>"``) so error messages stay actionable without a real path.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OsiParseError(f"invalid YAML in {source}: {exc}") from exc
    if not raw:
        raise OsiParseError(f"empty OSI model file: {source}")

    node: Any = raw.get("semantic_model", raw) if isinstance(raw, dict) else raw
    items = node if isinstance(node, list) else [node]
    models: list[OsiSemanticModel] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            models.append(OsiSemanticModel.model_validate(item))
        except Exception as exc:  # pydantic ValidationError, etc.
            raise OsiParseError(f"could not parse a semantic_model in {source}: {exc}") from exc
    if not models:
        raise OsiParseError(f"no semantic_model found in {source}")
    return models


def load_osi_models(path: Path) -> list[OsiSemanticModel]:
    """Parse an OSI YAML file into a list of :class:`OsiSemanticModel`.

    Existence-checks *path*, reads it, then delegates to :func:`parse_osi_models`
    with ``source=str(path)`` — the same parsing/error-message behavior as
    before the text/path split, just re-homed onto the text seam.
    """
    if not path.exists():
        raise OsiParseError(f"OSI model file not found: {path}")
    return parse_osi_models(path.read_text(), source=str(path))


def find_metric(
    models: list[OsiSemanticModel], metric_name: str
) -> tuple[OsiSemanticModel, OsiMetric]:
    """Locate *metric_name* across *models*; raise :class:`OsiParseError` if absent/ambiguous."""
    hits = [(m, m.metric(metric_name)) for m in models]
    hits = [(m, met) for m, met in hits if met is not None]
    if not hits:
        available = sorted({mt.name for mdl in models for mt in mdl.metrics})
        raise OsiParseError(
            f"metric '{metric_name}' not found. Available: {', '.join(available) or '(none)'}"
        )
    if len(hits) > 1:
        owners = ", ".join(m.name for m, _ in hits)
        raise OsiParseError(
            f"metric '{metric_name}' is ambiguous — defined in multiple models ({owners})"
        )
    return hits[0][0], hits[0][1]  # type: ignore[return-value]
