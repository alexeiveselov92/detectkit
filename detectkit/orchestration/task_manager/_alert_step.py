"""ALERT pipeline step: evaluates conditions and dispatches notifications."""

from __future__ import annotations

from datetime import datetime

import click

from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.task_manager._base import _TaskManagerBase
from detectkit.orchestration.task_manager._types import make_alert_config_id
from detectkit.utils.datetime_utils import now_utc_naive


class _AlertStepMixin(_TaskManagerBase):
    def _run_alert_step(self, config: MetricConfig) -> dict[str, int]:
        """Walk every active alert config and send/recover as needed."""
        alerts_sent = 0

        if not config.alerting:
            click.echo("  │ Alerting not enabled")
            return {"alerts_sent": 0}

        active_configs = [c for c in config.alerting if c.enabled and c.channels]
        if not active_configs:
            click.echo("  │ No active alert configs")
            return {"alerts_sent": 0}

        interval = config.get_interval()
        multi = len(active_configs) > 1

        for i, alerting_config in enumerate(active_configs):
            if multi:
                click.echo(
                    f"  │ [config {i + 1}/{len(active_configs)}] "
                    f"channels: {alerting_config.channels}"
                )

            if alerting_config.suppress_until:
                suppress_dt = datetime.strptime(alerting_config.suppress_until, "%Y-%m-%d %H:%M:%S")
                if now_utc_naive() < suppress_dt:
                    click.echo(
                        f"  │ Alerts suppressed until " f"{alerting_config.suppress_until} UTC"
                    )
                    continue

            click.echo("  │ Checking alert conditions...")
            alert_config_id = make_alert_config_id(alerting_config)

            orchestrator = AlertOrchestrator(
                metric_name=config.name,
                interval=interval,
                alert_config_id=alert_config_id,
                conditions=AlertConditions(
                    min_detectors=alerting_config.min_detectors,
                    direction=alerting_config.direction,
                    consecutive_anomalies=alerting_config.consecutive_anomalies,
                ),
                timezone_display=alerting_config.timezone,
                internal=self.internal,
                alert_config=alerting_config,
                description=config.description,
                mentions=alerting_config.mentions,
            )

            last_point = orchestrator.get_last_complete_point()

            # No-data branch must run BEFORE the recent_detections short-circuit
            # below: when data is missing there are no detections to evaluate,
            # so the regular path would silently exit with alerts_sent=0.
            should_no_data, no_data_alert_data = orchestrator.should_alert_no_data(last_point)
            if should_no_data:
                click.echo(
                    click.style(
                        f"  │ ⚠ No-data alert! Latest interval "
                        f"{last_point.strftime('%Y-%m-%d %H:%M:%S')} has no datapoint.",
                        fg="yellow",
                        bold=True,
                    )
                )
                alerts_sent += self._send_alerts(
                    orchestrator=orchestrator,
                    alerting_config=alerting_config,
                    alert_data=no_data_alert_data,
                    multi=multi,
                    template=alerting_config.template_no_data,
                )
                continue

            recent_detections = self._load_recent_detections(
                metric_name=config.name,
                last_point=last_point,
                num_points=alerting_config.consecutive_anomalies,
            )

            if not recent_detections:
                click.echo("  │ No recent detections found")
                if not multi:
                    return {"alerts_sent": 0}
                continue

            should_alert, alert_data = orchestrator.should_alert(recent_detections)
            if should_alert:
                alerts_sent += self._send_alerts(
                    orchestrator=orchestrator,
                    alerting_config=alerting_config,
                    alert_data=alert_data,
                    multi=multi,
                )
                continue

            if alerting_config.notify_on_recovery:
                self._maybe_send_recovery(
                    orchestrator=orchestrator,
                    alerting_config=alerting_config,
                    recent_detections=recent_detections,
                    multi=multi,
                )
            else:
                click.echo(f"  {'│' if multi else '└─'} No alert needed (conditions not met)")

        if multi:
            click.echo(f"  └─ Total alerts sent: {alerts_sent}")
        return {"alerts_sent": alerts_sent}

    # ── helpers ───────────────────────────────────────────────────────────

    def _send_alerts(
        self,
        *,
        orchestrator: AlertOrchestrator,
        alerting_config,
        alert_data,
        multi: bool,
        template=None,
    ) -> int:
        # No-data alerts log their own header above; only show the generic
        # "Alert triggered!" line for anomaly alerts.
        if not getattr(alert_data, "is_no_data", False):
            click.echo(
                click.style(
                    f"  │ ⚠ Alert triggered! "
                    f"Sending to {len(alerting_config.channels)} channel(s)...",
                    fg="yellow",
                    bold=True,
                )
            )

        channels = self._create_alert_channels(alerting_config.channels)
        if not channels:
            click.echo(
                click.style(
                    f"  {'│' if multi else '└─'} No valid alert channels available",
                    fg="yellow",
                )
            )
            return 0

        if template is None:
            template = alerting_config.template_consecutive

        results = orchestrator.send_alerts(alert_data, channels, template=template)
        sent = sum(1 for ok in results.values() if ok)
        for channel_name, ok in results.items():
            mark = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
            click.echo(f"  │   {mark} {channel_name}")

        click.echo(
            click.style(
                f"  {'│' if multi else '└─'} Sent {sent}/{len(channels)} alerts",
                fg="green" if sent > 0 else "yellow",
            )
        )
        return sent

    def _maybe_send_recovery(
        self,
        *,
        orchestrator: AlertOrchestrator,
        alerting_config,
        recent_detections,
        multi: bool,
    ) -> None:
        should_recover, recovery_data = orchestrator.should_send_recovery(recent_detections)
        if not should_recover:
            click.echo(f"  {'│' if multi else '└─'} No alert needed (conditions not met)")
            return

        click.echo(
            click.style(
                f"  │ ✓ Recovery detected! "
                f"Sending to {len(alerting_config.channels)} channel(s)...",
                fg="green",
                bold=True,
            )
        )

        channels = self._create_alert_channels(alerting_config.channels)
        if not channels:
            click.echo(
                click.style(
                    f"  {'│' if multi else '└─'} No valid alert channels available",
                    fg="yellow",
                )
            )
            return

        results = orchestrator.send_recovery(
            recovery_data, channels, template=alerting_config.template_recovery
        )
        recovery_sent = sum(1 for ok in results.values() if ok)
        for channel_name, ok in results.items():
            mark = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
            click.echo(f"  │   {mark} {channel_name}")

        click.echo(
            click.style(
                f"  {'│' if multi else '└─'} Sent {recovery_sent}/{len(channels)} "
                "recovery notifications",
                fg="green",
            )
        )
