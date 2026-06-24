"""Interactive manual tuning for detectkit (``dtk tune``).

The human-in-the-loop sibling of ``dtk autotune``. Where autotune searches the
detector configuration automatically and writes a *new* ``__tuned_<id>.yml``,
``dtk tune`` opens an interactive browser view of the metric's **real**
persisted series, lets the user turn the detector's knobs and watch the
confidence band / flagged anomalies recompute live (the same TypeScript detector
port that powers the landing playground), and — on a click — writes the chosen
config **back into the metric YAML**, safely:

1. the chosen detector + params are validated through ``MetricConfig`` and the
   ``DetectorFactory`` *before anything is written* (a broken config never lands);
2. the previous metric YAML is archived verbatim under ``metrics/.history/<metric>/``
   so the history of chosen parameters is trackable;
3. only then is the metric file re-emitted with the tuned detector.

Delivery mirrors the autotune incident labeler: a localhost-only server with a
one-shot token, nothing exposed off the machine, nothing written until the user
explicitly clicks **Apply**. The renderer bundle (``assets/tune.js``) is the
committed, shared chart core — regenerate it when the renderer TS changes.
"""

from detectkit.tuning.config_writer import apply_tuned_config
from detectkit.tuning.html import render_tune_html
from detectkit.tuning.payload import build_tune_payload
from detectkit.tuning.server import build_tune_server, serve_tuner

__all__ = [
    "apply_tuned_config",
    "build_tune_payload",
    "build_tune_server",
    "render_tune_html",
    "serve_tuner",
]
