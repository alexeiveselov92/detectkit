"""HTML reporting for detectkit.

Renders a self-contained HTML report of a metric's results — values, confidence
intervals, anomalies, and reconstructed alerts — over a chosen period, so a user
can see how a metric actually performed without standing up BI / SQL / a
third-party charting tool. Built from the persisted internal tables (``builder``)
and rendered with the shared JS chart core (``html_report``). Emitted on demand
by ``dtk run --report`` and after ``dtk autotune --report``.
"""

from detectkit.reporting.builder import build_report_payload, resolve_window
from detectkit.reporting.html_report import render_report_html

__all__ = [
    "build_report_payload",
    "render_report_html",
    "resolve_window",
]
