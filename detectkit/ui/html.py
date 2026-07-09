"""Render the ``dtk ui`` boot payload into a self-contained HTML shell.

Same delivery model as ``reporting/html_report.py`` and ``tuning/html.py``: one
HTML document with the renderer JS inlined (the committed ``assets/ui.js``
bundle) and the boot data baked in as a JS literal. Placeholders are
substituted with ``str.replace`` (NOT ``.format``) so literal ``{}`` in the
JS/CSS survive. The bundle assigns ``window.__DTK_UI__``. Unlike the report /
tune pages, no URLs are baked in here — the client reads ``token`` from
``location.search`` and builds every ``/api/...``/``/metric/...`` URL itself.
"""

from __future__ import annotations

from html import escape
from importlib.resources import files

from detectkit.utils.json_utils import json_dumps_sorted

# A small clay tile mirroring the brand mark (data-URI favicon, no network).
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
<title>detectkit ui — __PROJECT__</title>
<link rel="icon" href="__FAVICON__" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Schibsted+Grotesk:wght@400;500;600;700&display=swap" />
<style>
:root{
  --term-bg:#211e1a; --term-border:#332f29; --term-text:#c9c2b4;
  --clay:#d15b36; --clay-700:#b4471f; --paper:#f5f1e8; --surface:#fbf9f3; --border:#e6e0d4;
  --ink:#1b1916; --muted:#6e675b; --faint:#9a9384; --accent-green:#2e9e73;
  --st-anomaly:#d63232; --st-recovery:#36a64f; --st-nodata:#f0ad4e; --st-error:#5a7a8c;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'Schibsted Grotesk',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
}
html,body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);}
*{box-sizing:border-box;}
</style>
</head>
<body>
<div id="dtk-ui"></div>
<script>window.__DTK_UI_PAYLOAD__ = __PAYLOAD__;</script>
<script>__UI_JS__</script>
<script>
(function(){
  var mount = document.getElementById('dtk-ui');
  try { window.__DTK_UI__.render(window.__DTK_UI_PAYLOAD__, mount); }
  catch (e) { mount.textContent = 'Failed to render UI: ' + e; }
})();
</script>
</body>
</html>
"""


def _ui_js() -> str:
    """Read the committed UI renderer bundle shipped in the wheel."""
    return (files("detectkit.ui") / "assets" / "ui.js").read_text(encoding="utf-8")


def render_ui_html(payload: dict) -> str:
    """Build the self-contained UI shell HTML document for *payload*.

    Pure: no DB, no filesystem writes beyond reading the committed bundle. The
    caller (the server) serves the returned string directly.
    """
    project = escape(str(payload.get("project", "project")))
    html = _TEMPLATE
    html = html.replace("__PROJECT__", project)
    html = html.replace("__FAVICON__", _FAVICON)
    html = html.replace("__PAYLOAD__", json_dumps_sorted(payload))
    # JS last: its body must not be re-scanned for the other placeholders.
    html = html.replace("__UI_JS__", _ui_js())
    return html
