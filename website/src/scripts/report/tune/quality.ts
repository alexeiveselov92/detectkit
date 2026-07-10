// quality.ts — live alert-quality metrics: recall / false-alert rate (FDR) /
// review progress, matched on anomaly STREAK SPANS vs the ground-truth
// incident set (hand-marked + confirmed-valid alerts). Pure: the cockpit
// passes the current window/state in explicitly.

import type { Incident } from '../../demo/types';

export type ReviewVerdict = 'valid' | 'false';

// ---- live alert-quality metrics ------------------------------------------
export interface Quality {
  realIncidents: number;
  caught: number;
  recall: number;
  totalAlerts: number;
  correctAlerts: number;
  falseAlerts: number;
  fdr: number;
  /** alerts the user confirmed valid. */
  validated: number;
  /** alerts with any verdict (valid or false) — review progress. */
  reviewed: number;
}

export interface QualityContext {
  /** timestamps of the ACTIVE (possibly trimmed) series. */
  timestamps: number[];
  /** ±½ interval grid tolerance (ms). */
  tol: number;
  /** hand-marked incidents (the full set; window-filtered inside). */
  incidents: Incident[];
  /** confirmed-valid alert spans (validatedSpans()). */
  validatedSpans: Incident[];
  reviewFor: (s: number, e: number) => ReviewVerdict | null;
}

export function computeQuality(spans: Array<[number, number]>, ctx: QualityContext): Quality {
  const tol = ctx.tol; // ±½ interval grid tolerance
  // Only score incidents that overlap the active (possibly trimmed) series — an
  // incident outside the loaded window can never be caught, so counting it would
  // wrongly drag recall down. The list still shows every marked incident. The
  // ground-truth set is the hand-marked incidents PLUS the confirmed-valid alert
  // spans (a confirmed alert is the user asserting "a real incident happened
  // here"), deduped by overlap so neither is double-counted.
  const ts = ctx.timestamps;
  const lo = (ts.length ? ts[0] : 0) - tol;
  const hi = (ts.length ? ts[ts.length - 1] : 0) + tol;
  const inWindow = (iv: { start: number; end: number }): boolean => iv.end >= lo && iv.start <= hi;
  const overlapIv = (
    a: { start: number; end: number },
    b: { start: number; end: number },
  ): boolean => a.end >= b.start - tol && a.start <= b.end + tol;
  // Build the ground truth from the IN-WINDOW incidents, then dedup the confirmed
  // spans against THOSE — not the full set. Deduping against an out-of-window manual
  // incident (which is itself window-filtered away here) would drop an in-window
  // confirmed span too, silently losing a real region from recall. (The list and
  // Save keep the full-set dedup via groundTruth() — they show/save everything.)
  const manualIn = ctx.incidents.filter(inWindow);
  const validatedIn = ctx.validatedSpans
    .filter(inWindow)
    .filter((v) => !manualIn.some((iv) => overlapIv(v, iv)));
  const ivs = [...manualIn, ...validatedIn];
  // An alert is "for" an incident when its anomaly STREAK overlaps the span (not
  // just the fire point, which sits consecutive-1 intervals into the streak).
  const overlaps = (sp: [number, number], iv: Incident): boolean =>
    sp[1] >= iv.start - tol && sp[0] <= iv.end + tol;
  let correct = 0;
  let validated = 0;
  let reviewed = 0;
  for (const sp of spans) {
    const v = ctx.reviewFor(sp[0], sp[1]);
    if (v) reviewed++;
    if (v === 'valid') validated++;
    // 'false' stays a false alarm even if it grazes an incident; 'valid' is always
    // correct (it overlaps its own virtual incident); else by incident overlap.
    if (v === 'valid' || (v !== 'false' && ivs.some((iv) => overlaps(sp, iv)))) correct++;
  }
  let caught = 0;
  for (const iv of ivs) if (spans.some((sp) => overlaps(sp, iv))) caught++;
  const total = spans.length;
  return {
    realIncidents: ivs.length,
    caught,
    recall: ivs.length ? caught / ivs.length : NaN,
    totalAlerts: total,
    correctAlerts: correct,
    falseAlerts: total - correct,
    fdr: total ? (total - correct) / total : NaN,
    validated,
    reviewed,
  };
}

export function pctOrDash(v: number): string {
  return Number.isFinite(v) ? `${Math.round(v * 100)}%` : '—';
}

export function metricChip(
  value: string,
  label: string,
  sub: string,
  color: string,
  opts?: { cls?: string; title?: string },
): string {
  return (
    `<span class="dtk-m-chip${opts?.cls ? ' ' + opts.cls : ''}"${opts?.title ? ` title="${opts.title}"` : ''}>` +
    `<span class="dtk-m-dot" style="background:${color}"></span>` +
    `<span class="dtk-m-v">${value}</span><span class="dtk-m-l">${label}</span>` +
    (sub ? `<span class="dtk-m-sub">${sub}</span>` : '') +
    `</span>`
  );
}

export function renderMetricsBar(bar: HTMLElement, q: Quality, budget: number | null): void {
  // Without any marked incidents there is no ground truth, so catch-rate and
  // false-alert rate are undefined (not "100% false") — prompt to mark some.
  const haveTruth = q.realIncidents > 0;
  // Over budget = we have ground truth, alerts fired, and the false-alert rate
  // exceeds the configured budget. A gentle, optional signal — it only colours an
  // already-computed number; labeling and tuning are never blocked by it.
  const budgetPct = budget != null ? `${Math.round(budget * 100)}%` : '';
  const overBudget =
    haveTruth && q.totalAlerts > 0 && budget != null && Number.isFinite(q.fdr) && q.fdr > budget;
  let falseSub: string;
  if (!haveTruth) falseSub = 'mark incidents to measure';
  else if (q.totalAlerts === 0) falseSub = 'no alerts';
  else if (q.falseAlerts === 0) falseSub = `${pctOrDash(q.fdr)} · all correct`;
  else {
    // "≈1 in N false": N = alerts / false-alerts (≥1). Keep a decimal below 10 so
    // a 73%-false rate reads "≈1 in 1.4 false", not a misleading round-down to 1.
    const ratio = q.totalAlerts / q.falseAlerts;
    const nStr = ratio >= 9.5 ? String(Math.round(ratio)) : String(Math.round(ratio * 10) / 10);
    falseSub = `${pctOrDash(q.fdr)} · ≈1 in ${nStr} false`;
  }
  // Append the budget verdict (non-intrusive: only flag when over).
  if (overBudget) falseSub += ` · ▲ over ${budgetPct} budget`;
  // Review progress: how many fired alerts you've confirmed/dismissed, and how
  // many you confirmed valid (the green markers).
  const reviewSub =
    q.totalAlerts === 0
      ? 'no alerts'
      : `${q.validated} valid${q.totalAlerts > q.reviewed ? ` · ${q.totalAlerts - q.reviewed} left` : ' · all reviewed'}`;
  const falseTitle = budget
    ? `Budget: at most ${budgetPct} of fired alerts false (false-alert rate / FDR). ` +
      'Set per metric or project via false_alert_budget. Labeling is optional — this just ' +
      'flags when you exceed the budget.'
    : '';
  bar.innerHTML =
    metricChip(String(q.realIncidents), 'real incidents', '', 'var(--c)') +
    metricChip(
      haveTruth ? `${q.caught}/${q.realIncidents}` : '—',
      'caught',
      haveTruth ? `recall ${pctOrDash(q.recall)}` : 'mark or confirm',
      'var(--green)',
    ) +
    metricChip(String(q.totalAlerts), 'alerts', '', 'var(--c)') +
    metricChip(haveTruth ? String(q.falseAlerts) : '—', 'false alerts', falseSub, 'var(--anom)', {
      cls: overBudget ? 'over' : '',
      title: falseTitle,
    }) +
    metricChip(`${q.reviewed}/${q.totalAlerts}`, 'reviewed', reviewSub, 'var(--green)');
}
