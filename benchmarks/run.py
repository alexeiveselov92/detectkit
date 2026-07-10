"""CLI entry point for the detectkit benchmark harness.

Usage::

    python -m benchmarks.run --datasets synthetic
    python -m benchmarks.run --datasets synthetic,nab --download-nab
    python -m benchmarks.run --datasets yahoo --yahoo-dir /path/to/Yahoo_S5
    python -m benchmarks.run --datasets synthetic --detectors mad,iqr --max-series 6

Writes ``<out>/<stamp>-results.json`` (full per-series rows, for later
analysis) and ``<out>/<stamp>-results.md`` (a markdown summary table per
dataset), and prints the markdown tables to stdout.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import detectkit
from benchmarks.datasets import LabeledSeries, download_nab, load_nab, load_synthetic, load_yahoo
from benchmarks.runner import (
    DEFAULT_DETECTOR_MATRIX,
    DetectorAggregate,
    SeriesResult,
    aggregate,
    run_sweep,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BENCH_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = BENCH_ROOT / "data"
DEFAULT_RESULTS_ROOT = BENCH_ROOT / "results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Public-dataset benchmark harness for detectkit's detectors "
        "(NAB / Yahoo S5 / offline synthetic)."
    )
    parser.add_argument(
        "--datasets",
        default="synthetic",
        help="Comma-separated dataset list: synthetic,nab,yahoo (default: synthetic)",
    )
    parser.add_argument(
        "--download-nab",
        action="store_true",
        help="Download and extract the NAB repo into benchmarks/data/nab before running",
    )
    parser.add_argument(
        "--yahoo-dir",
        type=Path,
        default=None,
        help="Path to an already-extracted Yahoo S5 (Webscope) directory",
    )
    parser.add_argument(
        "--detectors",
        default=None,
        help="Comma-separated detector labels/types to restrict the sweep to "
        "(default: the whole matrix in benchmarks/runner.py)",
    )
    parser.add_argument(
        "--max-series", type=int, default=None, help="Cap the number of series per dataset"
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_RESULTS_ROOT, help="Output directory for result files"
    )
    parser.add_argument(
        "--seed", type=int, default=7, help="RNG seed for the synthetic dataset (default: 7)"
    )
    return parser.parse_args(argv)


def _load_datasets(dataset_names: list[str], args: argparse.Namespace) -> list[LabeledSeries]:
    series: list[LabeledSeries] = []
    for name in dataset_names:
        if name == "synthetic":
            items = load_synthetic(seed=args.seed)
        elif name == "nab":
            if args.download_nab:
                download_nab(DEFAULT_DATA_ROOT)
            items = load_nab(DEFAULT_DATA_ROOT, max_series=args.max_series)
        elif name == "yahoo":
            if args.yahoo_dir is None:
                raise SystemExit(
                    "--yahoo-dir is required for --datasets yahoo (Webscope S5 is "
                    "license-gated — see benchmarks/README.md)."
                )
            items = load_yahoo(args.yahoo_dir, max_series=args.max_series)
        else:
            raise SystemExit(f"Unknown dataset: {name!r}. Choose from: synthetic, nab, yahoo.")

        if args.max_series is not None:
            items = items[: args.max_series]
        logger.info("Loaded %d series from dataset '%s'", len(items), name)
        series.extend(items)
    return series


def _filter_matrix(
    labels: list[str] | None,
) -> list[tuple[str, str, dict]]:
    if labels is None:
        return DEFAULT_DETECTOR_MATRIX
    wanted = set(labels)
    return [entry for entry in DEFAULT_DETECTOR_MATRIX if entry[0] in wanted or entry[1] in wanted]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _write_json(
    path: Path, results: list[SeriesResult], aggregates: list[DetectorAggregate]
) -> None:
    payload = {
        # Results depend on the detectors' behavior, which changes across
        # releases — always record what produced them.
        "detectkit_version": detectkit.__version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series_results": [dataclasses.asdict(r) for r in results],
        "aggregates": [dataclasses.asdict(a) for a in aggregates],
    }
    path.write_text(json.dumps(payload, indent=2))


def _format_table(dataset: str, aggregates: list[DetectorAggregate]) -> str:
    rows = [a for a in aggregates if a.dataset == dataset]
    lines = [
        f"### {dataset}",
        "",
        "| detector | event_f1_best | f1_best | pr_auc | native_event_f1 | n_series | seconds |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in rows:
        lines.append(
            f"| {a.detector_label} | {a.mean_event_f1_best:.3f} | {a.mean_f1_best:.3f} | "
            f"{a.mean_pr_auc:.3f} | {a.mean_native_event_f1:.3f} | {a.n_series} | "
            f"{a.total_seconds:.2f} |"
        )
    return "\n".join(lines)


def _render_markdown(aggregates: list[DetectorAggregate], detectkit_version: str) -> str:
    datasets = sorted({a.dataset for a in aggregates})
    sections = [f"# detectkit benchmark results\n\ndetectkit version: `{detectkit_version}`"]
    sections.extend(_format_table(dataset, aggregates) for dataset in datasets)
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    dataset_names = [d.strip() for d in args.datasets.split(",") if d.strip()]
    detector_labels = (
        [d.strip() for d in args.detectors.split(",") if d.strip()] if args.detectors else None
    )

    series = _load_datasets(dataset_names, args)
    if not series:
        raise SystemExit("No series loaded — nothing to benchmark.")
    logger.info(
        "Loaded %d series total across dataset(s): %s", len(series), ", ".join(dataset_names)
    )

    matrix = _filter_matrix(detector_labels)
    results = run_sweep(series, matrix)
    aggregates = aggregate(results)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = args.out / f"{stamp}-results.json"
    md_path = args.out / f"{stamp}-results.md"

    _write_json(json_path, results, aggregates)
    md_text = _render_markdown(aggregates, detectkit.__version__)
    md_path.write_text(md_text)

    print(md_text)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
