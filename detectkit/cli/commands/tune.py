"""``dtk tune`` — interactive manual tuning of a metric's detector.

The human-in-the-loop sibling of ``dtk autotune``: load the metric's persisted
datapoints, open an interactive browser view of the **real** series, let the
user turn the detector's knobs and watch the band recompute live, then write the
chosen config back into the metric YAML (archiving the previous version first).

Unlike ``run``/``autotune`` it takes **no pipeline lock** — it neither runs the
pipeline nor persists detections; it only edits a config file (like a human
editing YAML). Re-run ``dtk run`` afterwards to recompute detections under the
new config.
"""

from __future__ import annotations

from datetime import datetime

import click

from detectkit.cli._output import echo_done, echo_error, echo_noop
from detectkit.cli.commands.autotune import _load_project
from detectkit.cli.commands.run import parse_date, select_metrics
from detectkit.tuning import build_tune_payload, render_tune_html, serve_tuner


def run_tune(
    *,
    select: str,
    profile: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    no_serve: bool = False,
    no_open: bool = False,
) -> bool:
    """Run the interactive tuner for the single selected metric.

    Returns ``True`` when a config was written (or a static preview emitted),
    ``False`` on a no-op / error / cancellation.
    """
    loaded = _load_project(profile)
    if loaded is None:
        return False
    project_root, project_config, internal_manager, _db_manager = loaded
    project_name = getattr(project_config, "name", None)

    metrics = select_metrics(select, project_root)
    if not metrics:
        echo_error(select, "no metrics matched the selector")
        return False
    if len(metrics) > 1:
        names = ", ".join(c.name for _p, c in metrics)
        echo_error(
            select,
            f"matched {len(metrics)} metrics ({names}); `dtk tune` tunes one at a time — "
            "narrow --select to a single metric",
        )
        return False

    metric_path, config = metrics[0]
    name = config.name

    from_dt = parse_date(from_date) if from_date else None
    to_dt = parse_date(to_date) if to_date else None
    data = internal_manager.load_datapoints(name, from_timestamp=from_dt, to_timestamp=to_dt)
    ts = data["timestamp"]
    if len(ts) == 0:
        echo_noop(name, "no datapoints — run `dtk run --select <name> --steps load` first")
        return False

    start = ts[0].astype("datetime64[ms]").astype(datetime)
    end = ts[-1].astype("datetime64[ms]").astype(datetime)
    payload = build_tune_payload(
        metric_config=config,
        internal=internal_manager,
        start=start,
        end=end,
        project_name=project_name,
    )
    if not payload["points"]:
        echo_noop(name, "no datapoints in the resolved window")
        return False

    # Static, read-only preview (no localhost server, no write-back).
    if no_serve:
        out = project_root / "metrics" / f"{name}__tuner.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_tune_html(payload), encoding="utf-8")
        echo_done(
            f"{name}: wrote static tuner preview {out.relative_to(project_root)} "
            "(read-only — sliders recompute live, but no Apply)"
        )
        return True

    applied = serve_tuner(
        payload=payload,
        original_path=metric_path,
        project_root=project_root,
        open_browser=not no_open,
        echo=click.echo,
    )
    if applied is None:
        echo_noop(name, "tuning cancelled — metric unchanged")
        return False

    click.echo(f"  Archived previous config: {applied.archived.relative_to(project_root)}")
    echo_done(f"{name}: applied tuned detector → {applied.saved.relative_to(project_root)}")
    click.echo(f"  Re-run `dtk run --select {name}` to recompute detections under the new config.")
    return True
