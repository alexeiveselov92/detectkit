"""``dtk ui`` — the project-level monitoring cockpit.

Opens a localhost web UI over the already-persisted ``_dtk_*`` tables: an
overview of every selected metric's alerting behavior, a per-metric detail
view (the existing HTML report in an iframe), and a pipeline control panel
that drives the real ``dtk run`` / ``dtk autotune`` / ``dtk unlock`` / ``dtk
tune`` commands as subprocesses. Like ``dtk tune`` it takes no pipeline lock —
it only reads the internal tables and spawns other ``dtk`` invocations, each
of which takes its own lock exactly as if run from the terminal.
"""

from __future__ import annotations

import click

from detectkit.cli.commands.run import find_project_root, select_metrics
from detectkit.config.profile import ProfilesConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.ui.overview import ALL_WINDOW_PRESETS
from detectkit.ui.server import build_form_meta, serve_ui


def run_ui(
    *,
    select: str = "*",
    profile: str | None = None,
    window: str = "30d",
    no_open: bool = False,
) -> None:
    """Bootstrap the project and serve the cockpit until Ctrl-C."""
    if window not in ALL_WINDOW_PRESETS:
        allowed = ", ".join(sorted(ALL_WINDOW_PRESETS))
        click.echo(
            click.style(
                f"Error: invalid --window '{window}'. Choose one of: {allowed}.",
                fg="red",
                bold=True,
            )
        )
        raise SystemExit(1)

    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: Not in a detectkit project directory!", fg="red", bold=True))
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        raise SystemExit(1)

    click.echo(f"Project root: {project_root}")

    try:
        project_config = ProjectConfig.from_yaml_file(project_root / "detectkit_project.yml")
    except Exception as exc:
        click.echo(click.style(f"Error loading detectkit_project.yml: {exc}", fg="red", bold=True))
        raise SystemExit(1) from exc

    try:
        metrics = select_metrics(select, project_root)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red", bold=True))
        raise SystemExit(1) from exc
    if not metrics:
        click.echo(click.style(f"No metrics found matching selector: {select}", fg="yellow"))
        raise SystemExit(1)
    metrics = sorted(metrics, key=lambda item: str(item[0]))

    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(click.style("Error: profiles.yml not found!", fg="red", bold=True))
        click.echo(f"Expected at: {profiles_path}")
        raise SystemExit(1)

    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
        db_manager = profiles_config.create_manager(profile)
        internal_manager = InternalTablesManager(db_manager)
        internal_manager.ensure_tables()
    except Exception as exc:
        click.echo(click.style(f"Error connecting to the database: {exc}", fg="red", bold=True))
        raise SystemExit(1) from exc

    click.echo(click.style(f"detectkit UI: {project_config.name}", fg="cyan", bold=True))
    click.echo(f"  {len(metrics)} metric(s) covered by --select {select} (window: {window})")

    form_meta = build_form_meta(profiles_config)

    try:
        serve_ui(
            project_config=project_config,
            project_root=project_root,
            metrics=metrics,
            internal_manager=internal_manager,
            initial_window=window,
            profile=profile,
            echo=click.echo,
            open_browser=not no_open,
            form_meta=form_meta,
        )
    except KeyboardInterrupt:
        pass
