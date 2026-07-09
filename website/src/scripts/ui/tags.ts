// Tag rollup strip: one chip per tag with a rolled-up alert count, clickable
// to filter the metrics table. An "All" chip resets the filter. Metrics with
// no tags roll up under a synthetic "untagged" bucket.

import { esc, fmtPerDay } from './format';
import type { OverviewMetric } from './payload';

export const UNTAGGED = 'untagged';

interface TagBucket {
  tag: string;
  count: number;
  alerts: number;
  perDaySum: number;
  havePerDay: boolean;
}

function rollup(metrics: OverviewMetric[]): TagBucket[] {
  const byTag = new Map<string, TagBucket>();
  const bump = (tag: string, m: OverviewMetric): void => {
    let b = byTag.get(tag);
    if (!b) {
      b = { tag, count: 0, alerts: 0, perDaySum: 0, havePerDay: false };
      byTag.set(tag, b);
    }
    b.count++;
    b.alerts += m.alerts.anomaly;
    if (m.alerts.per_day !== null) {
      b.perDaySum += m.alerts.per_day;
      b.havePerDay = true;
    }
  };
  for (const m of metrics) {
    if (m.tags.length === 0) bump(UNTAGGED, m);
    else for (const t of m.tags) bump(t, m);
  }
  return [...byTag.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

/**
 * Build the tag strip. `active` is the currently-selected tag filter (`null`
 * = All). `onSelect` is invoked with the tag to filter by, or `null` for All.
 */
export function buildTags(
  metrics: OverviewMetric[],
  active: string | null,
  onSelect: (tag: string | null) => void,
): HTMLElement {
  const wrap = document.createElement('div');
  wrap.className = 'dtk-ui-tags';

  const allBtn = document.createElement('button');
  allBtn.type = 'button';
  allBtn.className = 'dtk-ui-tag' + (active === null ? ' on' : '');
  allBtn.innerHTML = `<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${metrics.length}</span>`;
  allBtn.onclick = (): void => onSelect(null);
  wrap.appendChild(allBtn);

  for (const b of rollup(metrics)) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dtk-ui-tag' + (active === b.tag ? ' on' : '');
    const sub = b.havePerDay ? ` · ${fmtPerDay(b.perDaySum)}` : '';
    btn.innerHTML =
      `<span class="dtk-ui-tag-name">${esc(b.tag === UNTAGGED ? UNTAGGED : `#${b.tag}`)}</span>` +
      `<span class="dtk-ui-tag-n">${b.count} metric${b.count === 1 ? '' : 's'}</span>` +
      `<span class="dtk-ui-tag-n">${b.alerts} alert${b.alerts === 1 ? '' : 's'}</span>` +
      (sub ? `<span class="dtk-ui-tag-sub">${esc(sub)}</span>` : '');
    btn.onclick = (): void => onSelect(b.tag);
    wrap.appendChild(btn);
  }

  return wrap;
}
