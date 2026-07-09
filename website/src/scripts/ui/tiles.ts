// Stat tiles row — client-side aggregates computed from the overview rows.
// Mirrors the "dataviz-tile" look used across the report/tune pages: a big
// JetBrains Mono number, a muted label, on a thin-bordered dark surface card.

import { esc, fmtInt, fmtLag, fmtPct, fmtPerDay } from './format';
import type { OverviewMetric } from './payload';

function tile(value: string, label: string, sub?: string, opts?: { warn?: boolean; err?: boolean }): string {
  const cls = 'dtk-ui-tile' + (opts?.err ? ' err' : '');
  const subCls = opts?.warn ? 'dtk-ui-tile-sub warn' : 'dtk-ui-tile-sub';
  return (
    `<div class="${cls}">` +
    `<div class="dtk-ui-tile-val">${esc(value)}</div>` +
    `<div class="dtk-ui-tile-label">${esc(label)}</div>` +
    (sub ? `<div class="${subCls}">${esc(sub)}</div>` : '') +
    `</div>`
  );
}

/**
 * Build the stat tiles row from the overview metric rows that have landed so
 * far (the cockpit fetches stats incrementally — see ui.ts's `loadOverview` —
 * so this is called on every landing with a growing/shrinking `rows`, not
 * once with a complete monolithic payload).
 */
export function buildTiles(rows: OverviewMetric[]): HTMLElement {
  const wrap = document.createElement('div');
  wrap.className = 'dtk-ui-tiles';

  // enabled/total is config-derived and correct even for rows whose stats are
  // still loading; every OTHER aggregate must only count landed rows (a
  // pending row's zeroed stats would read as "fresh metric with no alerts",
  // and its null last_point would wrongly count as stale).
  const total = rows.length;
  const enabled = rows.filter((m) => m.enabled).length;
  const landed = rows.filter((m) => !m.pending);

  let anomalySum = 0;
  let noDataSum = 0;
  let alertingCount = 0;
  let perDaySum = 0;
  let havePerDay = false;
  for (const m of landed) {
    anomalySum += m.alerts.anomaly;
    noDataSum += m.alerts.no_data;
    if (m.alerts.anomaly > 0) alertingCount++;
    if (m.alerts.per_day !== null) {
      perDaySum += m.alerts.per_day;
      havePerDay = true;
    }
  }

  // Stale = enabled metric whose freshness reads amber/red (lag > 2x interval,
  // or no datapoint at all yet). Disabled metrics are intentionally quiet and
  // don't count.
  const stale: Array<{ m: OverviewMetric; lag: number }> = [];
  for (const m of landed) {
    if (!m.enabled) continue;
    if (m.last_point === null) {
      stale.push({ m, lag: Infinity });
      continue;
    }
    if (m.lag_seconds !== null && m.interval_seconds > 0 && m.lag_seconds > 2 * m.interval_seconds) {
      stale.push({ m, lag: m.lag_seconds });
    }
  }
  stale.sort((a, b) => b.lag - a.lag);
  const staleSub =
    stale.length === 0
      ? undefined
      : `worst: ${stale[0].m.name}${Number.isFinite(stale[0].lag) ? ` (${fmtLag(stale[0].lag)})` : ' (no data)'}`;

  wrap.innerHTML =
    tile(`${enabled}/${total}`, 'Metrics', 'enabled / total') +
    tile(fmtInt(anomalySum), 'Alerts in window', havePerDay ? fmtPerDay(perDaySum) : undefined) +
    tile(fmtInt(noDataSum), 'No-data events') +
    tile(fmtInt(alertingCount), 'Metrics alerting') +
    tile(fmtInt(stale.length), 'Stale metrics', staleSub, { warn: stale.length > 0, err: stale.length > 0 });

  // Labeled quality aggregates — only shown when at least one metric carries
  // ground-truth incidents.
  const labeled = landed.filter((m) => m.quality !== null);
  if (labeled.length > 0) {
    let caughtSum = 0;
    let inWindowSum = 0;
    let falseSum = 0;
    let anomalyEventSum = 0;
    let maxBudget = 0;
    for (const m of labeled) {
      const q = m.quality;
      if (!q) continue;
      caughtSum += q.caught;
      inWindowSum += q.incidents_in_window;
      falseSum += q.false_alerts;
      anomalyEventSum += m.alerts.anomaly;
      if (m.budget > maxBudget) maxBudget = m.budget;
    }
    const recall = inWindowSum > 0 ? caughtSum / inWindowSum : null;
    const fdr = anomalyEventSum > 0 ? falseSum / anomalyEventSum : null;
    const overBudget = fdr !== null && maxBudget > 0 && fdr > maxBudget;
    wrap.innerHTML +=
      tile(fmtPct(recall), 'Labeled recall', `${labeled.length} metric(s) labeled`) +
      tile(fmtPct(fdr), 'False-alert rate', overBudget ? `▲ over ${fmtPct(maxBudget)} budget` : undefined, {
        warn: overBudget,
      });
  }

  return wrap;
}
