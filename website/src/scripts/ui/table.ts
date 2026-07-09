// Metrics table, grouped by `dir` (the metric YAML's folder under metrics/).
//
// A pure-ish builder: given the overview rows + current sort/filter state and
// a handful of row-action callbacks, returns the table element plus a
// `paint()` you must call once it's attached to the live DOM (fills in the
// per-row sparklines — see spark.ts for why that's a separate step).

import { esc, fmtAgo, fmtInterval, fmtLag, fmtPct, fmtPerDay, fmtStamp, groupBy } from './format';
import { paintSpark } from './spark';
import type { BootMetric, OverviewMetric } from './payload';

/** Muted stand-in for a stat cell whose per-metric fetch hasn't landed yet. */
const PENDING_CELL = '<span class="dtk-ui-pending">···</span>';

/**
 * A full-shape placeholder row for a metric whose `GET /api/stats/<name>`
 * fetch is still in flight — mirrors the server's own `_empty_row` (see
 * `detectkit/ui/overview.py`): every boot-known field (name/dir/file/tags/
 * interval_seconds/enabled) is filled in immediately so the table, tiles and
 * tag rollup all render at once, while every DB-driven stat field stays at
 * its "no data yet" default until the real row lands.
 */
export function buildPendingRow(bm: BootMetric): OverviewMetric {
  return {
    name: bm.name,
    dir: bm.dir,
    file: bm.file,
    tags: bm.tags,
    enabled: bm.enabled,
    interval_seconds: bm.interval_seconds,
    detectors: [],
    alert_rule: null,
    last_point: null,
    first_point_in_window: null,
    lag_seconds: null,
    locked: false,
    points: 0,
    flagged: 0,
    anomaly_rate: null,
    alerts: { anomaly: 0, recovery: 0, no_data: 0, per_day: null, last_ts: null },
    quality: null,
    budget: 0,
    spark: [],
    spark_anoms: [],
    error: null,
    pending: true,
  };
}

export type SortKey = 'alerts' | 'name' | 'rate' | 'freshness';
export interface SortState {
  key: SortKey;
  dir: 'asc' | 'desc';
}

export const DEFAULT_SORT_DIR: Record<SortKey, 'asc' | 'desc'> = {
  alerts: 'desc',
  name: 'asc',
  rate: 'desc',
  freshness: 'desc',
};

export interface TableCallbacks {
  onOpen(name: string): void;
  onTune(name: string): void;
  onRun(name: string): void;
  onEdit(name: string): void;
  onSortChange(key: SortKey): void;
}

interface Freshness {
  color: string;
  title: string;
  /** sort key: lower = fresher; Infinity for "no data"/disabled-agnostic worst. */
  rank: number;
}

function freshness(m: OverviewMetric): Freshness {
  if (m.pending) {
    return { color: 'var(--faint)', title: 'loading…', rank: 0 };
  }
  if (!m.enabled) {
    return { color: 'var(--faint)', title: 'disabled', rank: -1 };
  }
  if (m.last_point === null) {
    return { color: 'var(--st-anomaly)', title: 'no datapoints loaded yet', rank: Infinity };
  }
  const lag = m.lag_seconds ?? 0;
  const ratio = m.interval_seconds > 0 ? lag / m.interval_seconds : 0;
  const title = `lag ${fmtLag(Math.max(0, lag))} (${ratio.toFixed(1)}× interval) · last point ${fmtStamp(m.last_point)} UTC`;
  if (ratio < 2) return { color: 'var(--st-recovery)', title, rank: lag };
  if (ratio < 6) return { color: 'var(--st-nodata)', title, rank: lag };
  return { color: 'var(--st-anomaly)', title, rank: lag };
}

function tagChips(tags: string[]): string {
  if (tags.length === 0) return '';
  return `<div class="dtk-ui-tagchips">${tags
    .map((t) => `<span class="dtk-ui-tagchip">${esc(t)}</span>`)
    .join('')}</div>`;
}

function qualityCell(m: OverviewMetric): string {
  const q = m.quality;
  if (!q) return `<span class="dtk-ui-quality empty">—</span>`;
  const title =
    `Incidents: ${q.incidents} (${q.incidents_in_window} in window) · caught ${q.caught} · ` +
    `false alerts ${q.false_alerts} · reviewed ${q.reviewed} (valid ${q.reviewed_valid}, false ${q.reviewed_false}) · ` +
    `${q.labels_file}`;
  return (
    `<span class="dtk-ui-quality" title="${esc(title)}">` +
    `<span class="dtk-ui-quality-chip">R <b>${esc(fmtPct(q.recall))}</b></span> · ` +
    `<span class="dtk-ui-quality-chip">FDR <b>${esc(fmtPct(q.fdr))}</b></span> · ` +
    `<span class="dtk-ui-quality-chip">✓${q.reviewed_valid}</span>` +
    `</span>`
  );
}

function nameTitle(m: OverviewMetric): string {
  const rule = m.alert_rule
    ? `min_detectors=${m.alert_rule.min_detectors} · direction=${m.alert_rule.direction} · ` +
      `consecutive=${m.alert_rule.consecutive} (${m.alert_rule.enabled}/${m.alert_rule.configs} config(s) enabled)`
    : 'no alerting configured';
  return `detectors: ${m.detectors.join(', ') || '—'}\nalert rule: ${rule}\nfile: ${m.file}`;
}

interface SparkJob {
  canvas: HTMLCanvasElement;
  points: { t: number; v: number | null }[];
  anoms: number[];
}

function buildRow(
  m: OverviewMetric,
  now: number,
  cb: TableCallbacks,
  sparkQueue: SparkJob[],
): HTMLTableRowElement {
  const tr = document.createElement('tr');
  tr.className =
    'dtk-ui-row' +
    (m.enabled ? '' : ' disabled') +
    (m.error ? ' errored' : '') +
    (m.pending ? ' pending' : '');

  const fresh = freshness(m);
  const tdDot = document.createElement('td');
  tdDot.className = 'dtk-ui-dotcell';
  tdDot.innerHTML = `<span class="dtk-ui-dot" style="background:${fresh.color}" title="${esc(fresh.title)}"></span>`;
  tr.appendChild(tdDot);

  const tdName = document.createElement('td');
  tdName.className = 'dtk-ui-namecell';
  const errBadge = m.error
    ? `<span class="dtk-ui-err-badge" title="${esc(m.error)}">!</span>`
    : '';
  tdName.title = nameTitle(m);
  tdName.innerHTML = `<span class="dtk-ui-name">${esc(m.name)}</span>${errBadge}${tagChips(m.tags)}`;
  tr.appendChild(tdName);

  const tdInterval = document.createElement('td');
  tdInterval.innerHTML = `<span class="dtk-ui-interval">${esc(fmtInterval(m.interval_seconds))}</span>`;
  tr.appendChild(tdInterval);

  const tdSpark = document.createElement('td');
  tdSpark.className = 'dtk-ui-sparkcell';
  if (m.pending) {
    tdSpark.innerHTML = '<span class="dtk-ui-spark-loading">loading…</span>';
  } else if (m.spark.length === 0) {
    tdSpark.innerHTML = '<span class="dtk-ui-spark-empty">no data yet</span>';
  } else {
    const canvas = document.createElement('canvas');
    canvas.className = 'dtk-spark';
    tdSpark.appendChild(canvas);
    // deferred: caller paints after the table is attached to the live DOM
    sparkQueue.push({ canvas, points: m.spark.map(([t, v]) => ({ t, v })), anoms: m.spark_anoms });
  }
  tr.appendChild(tdSpark);

  const tdAlerts = document.createElement('td');
  tdAlerts.className = 'dtk-ui-alertscell';
  if (m.pending) {
    tdAlerts.innerHTML = PENDING_CELL;
  } else {
    const overBudget = m.quality !== null && m.quality.fdr !== null && m.quality.fdr > m.budget;
    const nCls = 'dtk-ui-alerts-n' + (m.alerts.anomaly > 0 ? ' hasany' : '') + (overBudget ? ' overbudget' : '');
    const sub = m.alerts.per_day !== null ? `<span class="dtk-ui-alerts-sub">· ${esc(fmtPerDay(m.alerts.per_day))}</span>` : '';
    tdAlerts.innerHTML = `<span class="${nCls}">${m.alerts.anomaly}</span>${sub}`;
  }
  tr.appendChild(tdAlerts);

  const tdLast = document.createElement('td');
  if (m.pending) {
    tdLast.innerHTML = PENDING_CELL;
  } else if (m.alerts.last_ts !== null) {
    tdLast.innerHTML = `<span class="dtk-ui-lastalert" title="${esc(fmtStamp(m.alerts.last_ts))} UTC">${esc(
      fmtAgo(now, m.alerts.last_ts),
    )}</span>`;
  } else {
    tdLast.innerHTML = '<span class="dtk-ui-lastalert">—</span>';
  }
  tr.appendChild(tdLast);

  const tdRate = document.createElement('td');
  tdRate.innerHTML = m.pending ? PENDING_CELL : `<span class="dtk-ui-rate">${esc(fmtPct(m.anomaly_rate))}</span>`;
  tr.appendChild(tdRate);

  const tdQuality = document.createElement('td');
  tdQuality.innerHTML = m.pending ? PENDING_CELL : qualityCell(m);
  tr.appendChild(tdQuality);

  const tdLock = document.createElement('td');
  tdLock.innerHTML = m.locked
    ? '<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>'
    : '';
  tr.appendChild(tdLock);

  const tdActions = document.createElement('td');
  tdActions.className = 'dtk-ui-actionscell';
  const openBtn = document.createElement('button');
  openBtn.type = 'button';
  openBtn.className = 'dtk-ui-actionbtn';
  openBtn.textContent = 'Open';
  openBtn.onclick = (): void => cb.onOpen(m.name);
  const tuneBtn = document.createElement('button');
  tuneBtn.type = 'button';
  tuneBtn.className = 'dtk-ui-actionbtn';
  tuneBtn.textContent = 'Tune';
  tuneBtn.onclick = (): void => cb.onTune(m.name);
  const runBtn = document.createElement('button');
  runBtn.type = 'button';
  runBtn.className = 'dtk-ui-actionbtn';
  runBtn.textContent = 'Run';
  runBtn.onclick = (): void => cb.onRun(m.name);
  const editBtn = document.createElement('button');
  editBtn.type = 'button';
  editBtn.className = 'dtk-ui-actionbtn';
  editBtn.textContent = 'Edit';
  editBtn.onclick = (): void => cb.onEdit(m.name);
  tdActions.append(openBtn, tuneBtn, runBtn, editBtn);
  tr.appendChild(tdActions);

  return tr;
}

function sortValue(m: OverviewMetric, key: SortKey): number | string {
  switch (key) {
    case 'alerts':
      return m.alerts.anomaly;
    case 'name':
      return m.name.toLowerCase();
    case 'rate':
      return m.anomaly_rate ?? -1;
    case 'freshness':
      return freshness(m).rank;
  }
}

function sortRows(rows: OverviewMetric[], sort: SortState): OverviewMetric[] {
  const enabled = rows.filter((m) => m.enabled);
  const disabled = rows.filter((m) => !m.enabled);
  const dir = sort.dir === 'asc' ? 1 : -1;
  enabled.sort((a, b) => {
    const va = sortValue(a, sort.key);
    const vb = sortValue(b, sort.key);
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return a.name.localeCompare(b.name);
  });
  disabled.sort((a, b) => a.name.localeCompare(b.name));
  return [...enabled, ...disabled];
}

const HEADERS: Array<{ label: string; key: SortKey | null }> = [
  { label: '●', key: 'freshness' },
  { label: 'Name', key: 'name' },
  { label: 'Interval', key: null },
  { label: 'Trend', key: null },
  { label: 'Alerts', key: 'alerts' },
  { label: 'Last alert', key: null },
  { label: 'Rate', key: 'rate' },
  { label: 'Quality', key: null },
  { label: '', key: null },
  { label: '', key: null },
];

function buildHeaderRow(sort: SortState, cb: TableCallbacks): HTMLTableRowElement {
  const tr = document.createElement('tr');
  for (const h of HEADERS) {
    const th = document.createElement('th');
    if (h.key) {
      th.className = 'dtk-ui-th';
      const arrow = sort.key === h.key ? `<span class="dtk-ui-th-arrow">${sort.dir === 'asc' ? '▵' : '▾'}</span>` : '';
      th.innerHTML = `${esc(h.label)}${arrow}`;
      th.onclick = (): void => cb.onSortChange(h.key as SortKey);
    } else {
      th.textContent = h.label;
    }
    tr.appendChild(th);
  }
  return tr;
}

function groupLabel(dir: string): string {
  return dir === '' ? 'metrics/' : `metrics/${dir}/`;
}

/**
 * Build the metrics table grouped by `dir`. Returns the wrapper element and a
 * `paint()` you must call after appending it to the live document (it fills
 * in every row's sparkline canvas).
 */
export function buildMetricsTable(
  metrics: OverviewMetric[],
  sort: SortState,
  now: number,
  cb: TableCallbacks,
): { el: HTMLElement; paint: () => void } {
  const sparkQueue: SparkJob[] = [];
  const wrap = document.createElement('div');
  wrap.className = 'dtk-ui-table-wrap';

  if (metrics.length === 0) {
    wrap.innerHTML = '<div class="dtk-ui-empty">No metrics match the current filter.</div>';
    return { el: wrap, paint: () => {} };
  }

  const groups = groupBy(metrics, (m) => m.dir);
  const keys = [...groups.keys()].sort((a, b) => {
    if (a === b) return 0;
    if (a === '') return -1;
    if (b === '') return 1;
    return a.localeCompare(b);
  });

  for (const key of keys) {
    const rows = groups.get(key) ?? [];
    const groupWrap = document.createElement('div');
    groupWrap.className = 'dtk-ui-group';

    const alertsSum = rows.reduce((acc, m) => acc + m.alerts.anomaly, 0);
    const head = document.createElement('div');
    head.className = 'dtk-ui-group-head';
    head.innerHTML =
      `<span class="dtk-ui-group-name">${esc(groupLabel(key))}</span>` +
      `<span class="dtk-ui-group-sub">${rows.length} metric${rows.length === 1 ? '' : 's'} · ${alertsSum} alert${alertsSum === 1 ? '' : 's'}</span>`;
    groupWrap.appendChild(head);

    const table = document.createElement('table');
    table.className = 'dtk-ui-table';
    const thead = document.createElement('thead');
    thead.appendChild(buildHeaderRow(sort, cb));
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    for (const m of sortRows(rows, sort)) tbody.appendChild(buildRow(m, now, cb, sparkQueue));
    table.appendChild(tbody);

    groupWrap.appendChild(table);
    wrap.appendChild(groupWrap);
  }

  return {
    el: wrap,
    paint: () => {
      for (const s of sparkQueue) paintSpark(s.canvas, s.points, s.anoms);
    },
  };
}
