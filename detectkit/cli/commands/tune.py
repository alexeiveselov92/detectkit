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

import click

from detectkit.autotune.labels import (
    load_alert_reviews,
    load_capture_windows,
    load_incidents_for_display,
    newest_labels_file,
)
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
    interval_seconds = config.get_interval().seconds

    # Seed the synced labeler with the newest already-marked incidents from the
    # shared store incidents/<metric>/ (the same files dtk autotune reads), so
    # labeling round-trips across both tools. Best-effort — a missing/bad file
    # just yields no seed.
    incidents_dir = project_root / "incidents" / name
    preload_incidents: list[dict[str, str]] = []
    preload_capture: list[dict[str, str]] = []
    preload_reviews: list[dict[str, str]] = []
    newest = newest_labels_file(incidents_dir)
    if newest is not None:
        try:
            preload_incidents = load_incidents_for_display(
                newest, interval_seconds=interval_seconds, metric_name=name
            )
            preload_capture = load_capture_windows(
                newest, interval_seconds=interval_seconds, metric_name=name
            )
            preload_reviews = load_alert_reviews(
                newest, interval_seconds=interval_seconds, metric_name=name
            )
            click.echo(
                f"  Seeded {len(preload_incidents)} incident(s) from "
                f"{newest.relative_to(project_root)}"
            )
        except Exception as exc:  # noqa: BLE001 — preload is a best-effort convenience
            click.echo(click.style(f"  Could not preload {newest}: {exc}", fg="yellow"))

    from_dt = parse_date(from_date) if from_date else None
    to_dt = parse_date(to_date) if to_date else None
    # False-alert-rate budget for the cockpit's quality bar: metric overrides
    # project; the builder falls back to a built-in default when both are unset.
    budget = config.false_alert_budget
    if budget is None:
        budget = getattr(project_config, "false_alert_budget", None)
    # The builder resolves the window itself (recent ~TUNE_DEFAULT_POINTS by
    # default, or the explicit --from/--to span) and reads only that slice — no
    # need to pull the whole history just to find the bounds.
    payload = build_tune_payload(
        metric_config=config,
        internal=internal_manager,
        start=from_dt,
        end=to_dt,
        project_name=project_name,
        incidents=preload_incidents,
        capture_windows=preload_capture,
        alert_reviews=preload_reviews,
        false_alert_budget=budget,
    )
    n_points = len(payload["points"])
    if n_points == 0:
        echo_noop(
            name,
            "no datapoints in range — run `dtk run --select <name> --steps load` first, "
            "or widen --from/--to",
        )
        return False
    span = "the most recent points" if not (from_date or to_date) else "the selected window"
    click.echo(f"  Tuning on {n_points} points ({span}; pass --from/--to for a different span).")

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
        metric_name=name,
        incidents_dir=incidents_dir,
        interval_seconds=interval_seconds,
        # Enable the server-side Autotune mode: the config (autotune block, interval)
        # + a DB handle to reload the metric's history for the engine.
        metric_config=config,
        internal_manager=internal_manager,
    )
    if applied is None:
        echo_noop(name, "tuning cancelled — metric unchanged")
        return False

    click.echo(f"  Archived previous config: {applied.archived.relative_to(project_root)}")
    updated = ", ".join(applied.updated) or "detector"
    echo_done(
        f"{name}: applied tuned detector(s) [{updated}] → {applied.saved.relative_to(project_root)}"
    )
    if applied.preserved:
        click.echo(f"  Preserved the metric's other detector(s): {', '.join(applied.preserved)}")
    click.echo(f"  Re-run `dtk run --select {name}` to recompute detections under the new config.")
    return True
