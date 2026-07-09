"""Project-level monitoring cockpit for detectkit (``dtk ui``).

A localhost web UI over the already-persisted ``_dtk_*`` tables: an overview of
every selected metric's alerting behavior (how often alerts fire, per metric /
per tag / per ``metrics/`` folder), a per-metric detail view (the existing HTML
report in an iframe), a pipeline control panel that drives the existing CLI
commands (``dtk run`` / ``dtk autotune`` / ``dtk unlock`` as subprocesses,
``dtk tune`` launched per metric), and metric management — creating, editing
and deleting metric YAML files from a browser editor.

``dtk ui`` is a *superstructure over existing dtk commands*: the server itself
never runs the pipeline in-process and takes no pipeline lock — spawned ``dtk
run`` subprocesses take their own lock exactly as if run from the terminal.
Alert counts are replayed from stored detections via the pure
``AlertOrchestrator.replay`` (the same seam ``dtk run --report`` uses), so the
numbers match what the pipeline would actually have alerted.

- ``overview.py`` — ``build_overview_payload``: per-metric frequency/quality
  stats, pure given an ``InternalTablesManager``.
- ``jobs.py`` — ``JobManager``: subprocess registry + output pumping for the
  pipeline control panel.
- ``server.py`` — ``build_ui_server`` / ``serve_ui``: routes, token auth, the
  single ``db_lock`` serializing DB-touching requests.
- ``metric_files.py`` — the metric-YAML create/update/delete seam: validate
  before write, archive to ``metrics/.history/<metric>/`` before every
  overwrite or delete.
- ``html.py`` — ``render_ui_html``: inlines the committed ``assets/ui.js``
  renderer bundle + the boot payload into one self-contained page.
"""
