"""Project-level error alert dispatch shared by ``TaskManager`` and the CLI.

Why this lives here, not on ``TaskManager``:

The task manager only sees errors that happen during ``run_metric``. Three
classes of failures crash earlier — at the CLI level, before a TaskManager
exists at all:

1. ``profiles_config = ProfilesConfig.from_yaml(...)``  (no profile, can't
   build channels — out of scope for this dispatcher)
2. ``db_manager = profiles_config.create_manager(profile)``  (DB unreachable;
   profiles ARE loaded — channels can be built and we should alert)
3. ``internal_manager.ensure_tables()``  (DB reachable but DDL fails)

For (2) and (3) the operator needs the same project-level error alert as for
runtime failures. Extracting the dispatch into a free function lets the CLI
call it directly without needing a TaskManager.
"""

from __future__ import annotations

from typing import Any

import click
import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.utils.datetime_utils import now_utc_naive


def dispatch_project_error_alert(
    *,
    profiles_config: Any,
    project_config: Any,
    metric_name: str,
    exc: BaseException,
) -> bool:
    """Send a project-level error alert based on ``project_config.error_alerting``.

    Args:
        profiles_config: Loaded ``ProfilesConfig`` (needed to resolve channel
            names → channel instances). ``None`` short-circuits the dispatch.
        project_config: Loaded ``ProjectConfig``. Reads ``error_alerting``.
        metric_name: A string identifier for the failure context. Use the
            real metric name when failing inside a metric run, or a
            placeholder like ``"<startup>"`` for early failures.
        exc: The exception that triggered the alert. Its type name and
            ``str(exc)`` are passed to the channel template as
            ``{error_type}`` and ``{error_message}``.

    Returns:
        ``True`` when the alert was actually attempted (caller should treat
        this as "abort the rest of the run"). ``False`` when alerting is
        disabled, has no channels configured, no profiles to resolve them
        against, or the dispatch itself raised.
    """
    cfg = getattr(project_config, "error_alerting", None)
    if not cfg or not cfg.enabled or not cfg.channels:
        return False
    if profiles_config is None:
        return False

    try:
        channels = _build_channels(profiles_config, cfg.channels)
        if not channels:
            click.echo(
                click.style(
                    "  │ Project error_alerting enabled but no valid channels "
                    "resolved — skipping.",
                    fg="yellow",
                ),
                err=True,
            )
            return False

        alert_data = AlertData(
            metric_name=metric_name,
            timestamp=np.datetime64(now_utc_naive(), "ms"),
            timezone=cfg.timezone or "UTC",
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="pipeline",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={"reason": "pipeline_error"},
            consecutive_count=0,
            is_error=True,
            error_type=type(exc).__name__,
            error_message=str(exc),
            description=None,
            mentions=cfg.mentions,
            project_name=getattr(project_config, "name", None),
        )

        click.echo(
            click.style(
                f"  │ ⚠ Project error alert → sending to {len(channels)} channel(s)...",
                fg="yellow",
                bold=True,
            )
        )
        for channel in channels:
            channel_name = channel.__class__.__name__
            try:
                ok = bool(channel.send(alert_data, template=cfg.template))
                mark = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
                click.echo(f"  │   {mark} {channel_name}")
            except Exception as channel_exc:
                click.echo(
                    click.style(
                        f"  │   ✗ {channel_name}: " f"{type(channel_exc).__name__}: {channel_exc}",
                        fg="red",
                    ),
                    err=True,
                )

        return True
    except Exception as dispatch_exc:
        # Never let alert dispatch crash the caller — they're already
        # handling another error and need to surface it cleanly.
        click.echo(
            click.style(
                f"  │ Failed to dispatch project error alert: "
                f"{type(dispatch_exc).__name__}: {dispatch_exc}",
                fg="red",
            ),
            err=True,
        )
        return False


def _build_channels(profiles_config: Any, channel_names: list[str]) -> list:
    """Resolve channel names against the loaded profiles config.

    Mirrors ``_TaskManagerBase._create_alert_channels`` but lives outside
    the TaskManager so the CLI early-failure paths can call it before a
    TaskManager exists.
    """
    channels = []
    for name in channel_names:
        try:
            channel_config = profiles_config.get_alert_channel_config(name)
            channels.append(AlertChannelFactory.create_from_config(channel_config))
        except (ValueError, KeyError, ImportError, TypeError) as exc:
            # Config-level problems (missing channel, bad type, missing
            # driver, wrong constructor args) — skip this channel but
            # keep going so a single typo doesn't kill the whole alert.
            print(f"Warning: Failed to create channel '{name}': {type(exc).__name__}: {exc}")
    return channels
