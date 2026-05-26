"""
Implementation of 'dtk unlock' command.

Force-releases stale pipeline locks left behind by a run that died without
releasing them (e.g. the database restarted mid-run). Normally the lock
auto-expires after its timeout, but this command clears it immediately.
"""

import click

from detectkit.cli.commands.run import find_project_root, select_metrics
from detectkit.config.profile import ProfilesConfig
from detectkit.database.internal_tables import InternalTablesManager


def run_unlock(select: str, profile: str | None):
    """
    Clear pipeline locks for the selected metric(s).

    Args:
        select: Metric selector (name, path, or tag) — same semantics as `dtk run`
        profile: Profile name to use (defaults to project's default_profile)
    """
    # Find project root
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style(
                "Error: Not in a detectkit project directory!",
                fg="red",
                bold=True,
            )
        )
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        return

    click.echo(f"Project root: {project_root}")

    # Select metrics based on selector
    try:
        metrics = select_metrics(select, project_root)
    except ValueError as e:
        click.echo(click.style(f"Error: {e}", fg="red", bold=True))
        return

    if not metrics:
        click.echo(
            click.style(
                f"No metrics found matching selector: {select}",
                fg="yellow",
            )
        )
        return

    # Load profiles.yml
    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(click.style("Error: profiles.yml not found!", fg="red", bold=True))
        click.echo(f"Expected at: {profiles_path}")
        return

    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
    except Exception as e:
        click.echo(click.style(f"Error loading profiles.yml: {e}", fg="red", bold=True))
        return

    # Create database / internal tables manager
    try:
        db_manager = profiles_config.create_manager(profile)
    except Exception as e:
        click.echo(click.style(f"Error creating database manager: {e}", fg="red", bold=True))
        return

    internal_manager = InternalTablesManager(db_manager)

    click.echo(f"Found {len(metrics)} metric(s) to unlock")
    click.echo()

    cleared = 0
    for _, config in metrics:
        metric_name = config.name
        try:
            was_locked = internal_manager.clear_lock(metric_name)
        except Exception as e:
            click.echo(
                click.style(f"  ✗ {metric_name}: error clearing lock: {e}", fg="red"),
                err=True,
            )
            continue

        if was_locked:
            cleared += 1
            click.echo(click.style(f"  ✓ {metric_name}: lock cleared", fg="green"))
        else:
            click.echo(f"  • {metric_name}: no active lock")

    click.echo()
    click.echo(
        click.style(
            f"Done. Cleared {cleared} lock(s) of {len(metrics)} metric(s).",
            fg="cyan",
            bold=True,
        )
    )
