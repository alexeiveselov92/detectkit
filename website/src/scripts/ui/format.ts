// Pure formatting helpers for the `dtk ui` cockpit — no DOM, no state. Mirrors
// the small inline formatters report.ts / tune.ts use (esc, fmtVal-style
// magnitude scaling) so numbers read consistently across all three surfaces.

export const esc = (s: unknown): string =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

export const clamp = (x: number, a: number, b: number): number => Math.max(a, Math.min(b, x));

/** "10min" / "1h" / "1d" / "30s" — mirrors report.ts's buildHeader interval string. */
export function fmtInterval(seconds: number): string {
  const min = seconds / 60;
  if (seconds >= 86400 && seconds % 86400 === 0) return seconds / 86400 + 'd';
  if (seconds >= 3600 && seconds % 3600 === 0) return seconds / 3600 + 'h';
  if (min >= 1 && seconds % 60 === 0) return min + 'min';
  return seconds + 's';
}

/** Percentage, always 1 decimal (e.g. "66.7%"); "—" for null/non-finite. */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return (v * 100).toFixed(1) + '%';
}

/** Compact count formatter for stat tiles / chips (1234 -> "1,234"). */
export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return Math.round(v).toLocaleString('en-US');
}

/** "≈1.4/day" / "≈0.1/day"; "—" for null. */
export function fmtPerDay(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const r = v >= 9.5 ? v.toFixed(0) : v.toFixed(1);
  return `≈${r}/day`;
}

/**
 * "≈1 in N false" — N = totalEvents / falseEvents, kept to a decimal below 10
 * so a mostly-false rate doesn't round down to a misleading "1 in 1" (mirrors
 * the tune cockpit's metrics-bar phrasing).
 */
export function fmtFalseRatio(falseEvents: number, totalEvents: number): string {
  if (totalEvents <= 0) return '—';
  if (falseEvents <= 0) return 'all correct';
  const ratio = totalEvents / falseEvents;
  const n = ratio >= 9.5 ? String(Math.round(ratio)) : String(Math.round(ratio * 10) / 10);
  return `≈1 in ${n} false`;
}

/** Relative time from `nowMs` back to `tsMs`: "just now" / "12m ago" / "2h ago" / "3d ago" / "4mo ago". */
export function fmtAgo(nowMs: number, tsMs: number): string {
  const diff = Math.max(0, nowMs - tsMs);
  const mtot = Math.round(diff / 60000);
  if (mtot < 1) return 'just now';
  if (mtot < 60) return `${mtot}m ago`;
  const h = Math.floor(mtot / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  return `${mo}mo ago`;
}

/** Wall-clock duration between two ms timestamps: "45s" / "3m 12s" / "1h 05m". */
export function fmtDuration(fromMs: number, toMs: number): string {
  const s = Math.max(0, Math.round((toMs - fromMs) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m}m ${rs}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${String(rm).padStart(2, '0')}m`;
}

/** Full UTC stamp "YYYY-MM-DD HH:MM:SS" for tooltips (mirrors core/canvas fmtTs). */
export function fmtStamp(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19).replace('T', ' ');
}

/** Human duration from a second count (lag, staleness) — "45m" / "2h 30m" / "3d 4h". */
export function fmtLag(seconds: number): string {
  const mtot = Math.round(seconds / 60);
  if (mtot < 60) return `${mtot}m`;
  const h = Math.floor(mtot / 60);
  const mm = mtot % 60;
  if (h < 24) return h + 'h' + (mm ? ` ${mm}m` : '');
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return d + 'd' + (hh ? ` ${hh}h` : '');
}

/** Group an array by a string key, preserving first-seen key order. */
export function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item);
    const bucket = out.get(k);
    if (bucket) bucket.push(item);
    else out.set(k, [item]);
  }
  return out;
}

/** Debounce a zero-arg callback (used for the resize/refresh handlers). */
export function debounce(fn: () => void, ms: number): () => void {
  let handle: number | undefined;
  return () => {
    if (handle !== undefined) window.clearTimeout(handle);
    handle = window.setTimeout(fn, ms);
  };
}
