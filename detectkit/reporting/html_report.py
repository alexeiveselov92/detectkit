"""Render a report payload into a single self-contained HTML file.

The self-contained inline-bundle delivery model (shared with the ``dtk tune``
page): one HTML document with the renderer JS inlined (the pre-built
``assets/report.js`` bundle — one source shared with the website landing demo)
and the data baked in as a JS literal. No CDN, no network, nothing leaves the
browser. Placeholders are substituted with ``str.replace`` (NOT ``.format``) so
literal ``{}`` in the JS/CSS survive.
"""

from __future__ import annotations

from html import escape
from importlib.resources import files

from detectkit.utils.json_utils import json_dumps_sorted

# A small clay tile, mirroring the brand mark — keeps the report on-brand without
# a network request (data-URI favicon).
_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'"
    "%3E%3Crect width='32' height='32' rx='7' fill='%23d15b36'/%3E%3Cpolyline points="
    "'6,20 12,12 18,18 26,9' fill='none' stroke='%23fbf9f3' stroke-width='2.4' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>detectkit report — __METRIC__</title>
<link rel="icon" href="__FAVICON__" />
<!-- Optional brand webfonts; system fallbacks below keep the report readable offline. -->
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Schibsted+Grotesk:wght@400;500;600;700&display=swap" />
<style>
:root{
  --term-bg:#211e1a; --term-border:#332f29; --term-text:#c9c2b4;
  --clay:#d15b36; --paper:#f5f1e8; --surface:#fbf9f3; --border:#e6e0d4;
  --ink:#1b1916; --muted:#6e675b; --faint:#9a9384;
  --st-anomaly:#d63232; --st-recovery:#36a64f; --st-nodata:#f0ad4e; --st-error:#5a7a8c;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'Schibsted Grotesk',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
}
html,body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);}
*{box-sizing:border-box;}
</style>
</head>
<body>
<div id="dtk-report"></div>
<script>window.__DTK_PAYLOAD__ = __PAYLOAD__;</script>
<script>__REPORT_JS__</script>
<script>
(function(){
  var mount = document.getElementById('dtk-report');
  try { window.__DTK_REPORT__.render(window.__DTK_PAYLOAD__, mount); }
  catch (e) { mount.textContent = 'Failed to render report: ' + e; }
})();
</script>
</body>
</html>
"""


def _report_js() -> str:
    """Read the committed report renderer bundle shipped in the wheel."""
    return (files("detectkit.reporting") / "assets" / "report.js").read_text(encoding="utf-8")


def render_report_html(payload: dict) -> str:
    """Build the self-contained HTML document for ``payload``.

    Pure: no DB, no filesystem writes. The caller writes the returned string.
    """
    metric = escape(str(payload.get("metric", "metric")))
    html = _TEMPLATE
    html = html.replace("__METRIC__", metric)
    html = html.replace("__FAVICON__", _FAVICON)
    html = html.replace("__PAYLOAD__", json_dumps_sorted(payload))
    # JS last: its body must not be re-scanned for the other placeholders.
    html = html.replace("__REPORT_JS__", _report_js())
    return html
