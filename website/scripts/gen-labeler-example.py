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

_METRIC = "sessions_per_visitor_avg"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUT = _REPO_ROOT / "docs" / "examples" / "autotune-labeler.html"


def _sample_series() -> dict[str, np.ndarray]:
    """Three weeks of hourly data with a daily cycle + two visible incidents."""
    n = 24 * 21
    rng = np.random.RandomState(7)
    base = np.datetime64("2026-05-01T00:00:00", "ms")
    ts = (base + np.arange(n) * np.timedelta64(1, "h")).astype("datetime64[ms]")
    hours = np.arange(n) % 24
    vals = (120 + 45 * np.sin(2 * np.pi * (hours - 6) / 24) + rng.normal(0, 5, n)).astype(float)
    vals[150:158] -= 70  # a sustained dip
    vals[300:305] += 90  # a spike
    return {"timestamp": ts, "value": vals}


def main() -> None:
    html = render_labeler_html(_METRIC, _sample_series())
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(html, encoding="utf-8")
    print(f"gen-labeler-example: wrote {_OUT.relative_to(_REPO_ROOT)} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
