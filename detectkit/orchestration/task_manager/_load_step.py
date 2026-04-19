"""LOAD pipeline step: pulls metric data and writes ``_dtk_datapoints``."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

import click

from detectkit.config.metric_config import MetricConfig
from detectkit.loaders.metric_loader import MetricLoader
from detectkit.orchestration.task_manager._base import _TaskManagerBase
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _LoadStepMixin(_TaskManagerBase):
    def _run_load_step(
        self,
        config: MetricConfig,
        from_date: Optional[datetime],
        to_date: Optional[datetime],
        full_refresh: bool,
    ) -> Dict[str, int]:
        """Execute the LOAD step end-to-end (resume → batch → save)."""
        loader = MetricLoader(
            config=config,
            db_manager=self.db_manager,
            internal_manager=self.internal,
        )

        if full_refresh:
            click.echo("  │ Deleting existing datapoints...")
            self.internal.delete_datapoints(
                metric_name=config.name,
                from_timestamp=from_date,
                to_timestamp=to_date,
            )

        actual_from = from_date
        actual_to = to_date

        if actual_from is None:
            last_ts = self.internal.get_last_datapoint_timestamp(config.name)
            if last_ts:
                interval = config.get_interval()
                actual_from = last_ts + timedelta(seconds=interval.seconds)
                click.echo(
                    f"  │ Resuming from last saved: "
                    f"{last_ts.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            elif config.loading_start_time:
                actual_from = datetime.strptime(
                    config.loading_start_time, "%Y-%m-%d %H:%M:%S"
                )  # naive UTC by config convention
                click.echo(
                    f"  │ Starting fresh from: {config.loading_start_time}"
                )
            else:
                raise ValueError(
                    "No existing data and no loading_start_time configured. "
                    "Please specify from_date or set loading_start_time in config."
                )

        actual_to = to_naive_utc(actual_to) if actual_to is not None else now_utc_naive()
        actual_from = to_naive_utc(actual_from)

        if actual_from >= actual_to:
            click.echo(
                f"  │ Next interval at {actual_from.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"now {actual_to.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            click.echo(click.style(
                "  └─ Nothing to load yet, waiting for next interval", fg="yellow"
            ))
            return {"points_loaded": 0}

        interval = config.get_interval()
        total_seconds = (actual_to - actual_from).total_seconds()
        total_points = int(total_seconds / interval.seconds)

        if total_points < 1:
            next_interval = actual_from + timedelta(seconds=interval.seconds)
            click.echo(
                f"  │ Next interval at {next_interval.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"now {actual_to.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            click.echo(click.style(
                "  └─ Nothing to load yet, waiting for next interval", fg="yellow"
            ))
            return {"points_loaded": 0}

        # Snap actual_to back to the last complete interval boundary.
        actual_to = actual_from + timedelta(seconds=total_points * interval.seconds)
        batch_size = config.loading_batch_size

        click.echo(
            f"  │ Loading from {actual_from.strftime('%Y-%m-%d %H:%M:%S')} "
            f"to {actual_to.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        click.echo(
            f"  │ Total points: ~{total_points:,} | Batch size: {batch_size:,}"
        )

        if total_points <= batch_size:
            click.echo("  │ Loading in single batch...")
            rows_inserted = loader.load_and_save(
                from_date=actual_from, to_date=actual_to
            )
            click.echo(click.style(
                f"  └─ Loaded {rows_inserted:,} datapoints", fg="green"
            ))
            return {"points_loaded": rows_inserted}

        total_loaded = 0
        current_from = actual_from
        num_batches = int(total_points / batch_size) + 1
        batch_num = 0
        click.echo(f"  │ Loading in {num_batches} batches...")

        while current_from < actual_to:
            batch_num += 1
            batch_seconds = batch_size * interval.seconds
            batch_to = current_from + timedelta(seconds=batch_seconds)
            if batch_to > actual_to:
                batch_to = actual_to

            rows = loader.load_and_save(from_date=current_from, to_date=batch_to)
            total_loaded += rows
            click.echo(
                f"  │   Batch {batch_num}/{num_batches}: "
                f"+{rows:,} points (total: {total_loaded:,})"
            )
            current_from = batch_to

        click.echo(click.style(
            f"  └─ Loaded {total_loaded:,} datapoints", fg="green"
        ))
        return {"points_loaded": total_loaded}
