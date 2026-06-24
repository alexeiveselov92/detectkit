#!/usr/bin/env python3
"""gen-labeler-example.py — regenerate the docs' live labeler example.

The autotune reference page shows the interactive incident labeler exactly as
`dtk autotune --select <metric> --label` produces it. To keep that demo honest,
the page does NOT hand-mock the UI: it embeds the *real* artifact rendered by
``detectkit.autotune.html_labeler.render_labeler_html`` over a small, fixed
synthetic series, written to ``docs/examples/autotune-labeler.html``.

``sync-docs.mjs`` then ships that file to the site under ``/examples/``.

Run after changing the labeler template (``detectkit/autotune/html_labeler.py``):

    python website/scripts/gen-labeler-example.py

The output is deterministic (fixed dates + seed) so re-running only changes the
file when the template actually changes — keeping git diffs meaningful.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from detectkit.autotune.html_labeler import render_labeler_html

_METRIC = "api_p95_latency_ms"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT = _REPO_ROOT / "docs" / "examples" / "autotune-labeler.html"


def _sample_series() -> dict[str, np.ndarray]:
    """Three weeks of hourly p95 API latency (ms) with a daily cycle + two incidents.

    Latency in ms keeps the demo self-consistent (values are naturally well above 1,
    unlike a 0–1 rate) while keeping the two incidents towering over the baseline so
    they stay obvious to label.
    """
    n = 24 * 21
    rng = np.random.RandomState(7)
    base = np.datetime64("2026-05-01T00:00:00", "ms")
    ts = (base + np.arange(n) * np.timedelta64(1, "h")).astype("datetime64[ms]")
    hours = np.arange(n) % 24
    # baseline ~170ms p95, higher through the working day, light noise
    vals = 170 + 60 * np.sin(2 * np.pi * (hours - 9) / 24) + rng.normal(0, 12, n)
    vals = np.clip(vals, 0.0, None)
    vals[150:158] += 750.0  # a sustained slowdown (p95 ~900ms)
    vals[300:305] += 1150.0  # a sharp latency spike (~1300ms)
    return {"timestamp": ts, "value": vals.astype(float)}


def main() -> None:
    html = render_labeler_html(_METRIC, _sample_series(), interval_seconds=3600)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(html, encoding="utf-8")
    print(f"gen-labeler-example: wrote {_OUT.relative_to(_REPO_ROOT)} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
