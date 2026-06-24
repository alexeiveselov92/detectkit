// Contract for the library HTML report payload.
//
// This JSON object is produced by detectkit/reporting/ (Python: builder.py reads
// _dtk_datapoints + _dtk_detections and replays alerts) and baked into a
// self-contained HTML file. The report renderer (report.ts, bundled to
// detectkit/reporting/assets/report.js) consumes EXACTLY this shape. Keep the
// Python builder and this file in lockstep — same keys, same units.
//
// All timestamps are integer ms-epoch (UTC). Floats may be null where a value is
// a gap (datapoint) or the band is un-scored (detector warm-up / missing data).

export interface ReportPoint {
  /** ms epoch */
  t: number;
  /** metric value; null = gap-filled missing point */
  v: number | null;
}

export interface ReportDetectorPoint {
  t: number;
  /** confidence_lower / upper; null when the point was not scored */
  lo: number | null;
  hi: number | null;
  /** 1 if flagged anomalous at this point, else 0 */
  a: 0 | 1;
  /** severity (spread-units beyond the bound), null when not anomalous */
  sev: number | null;
  /** breach direction when anomalous */
  dir: 'above' | 'below' | null;
}

export interface ReportDetector {
  /** detector_id (16-hex) */
  id: string;
  /** class name, e.g. "MADDetector" */
  name: string;
  /** non-default params, e.g. { threshold: 3.0, window_size: 100 } */
  params: Record<string, unknown>;
  points: ReportDetectorPoint[];
  anomaly_count: number;
}

export type AlertKind = 'anomaly' | 'recovery' | 'no_data';

export interface ReportAlert {
  kind: AlertKind;
  /** grid timestamp the event fired at */
  t: number;
  /** first point of the incident streak (anomaly/recovery), else null */
  onset: number | null;
  /** true streak length (points) */
  consecutive: number;
  direction: 'up' | 'down' | 'mixed' | 'none';
  severity: number;
  value: number | null;
  /** detector label, e.g. "MADDetector" or "2 detectors" */
  detector: string;
  /** the rule that fired, e.g. "min_detectors=1 · direction=same · consecutive=3" */
  rule: string;
  /** alert_config_id this event belongs to */
  config_id: string;
}

export interface ReportSummary {
  anomalies: number;
  alerts: number;
  recoveries: number;
  no_data: number;
}

export interface ReportPayload {
  metric: string;
  project: string | null;
  interval_seconds: number;
  period: { start: number; end: number };
  /** human-readable stamp set by the caller (not by the pure renderer) */
  generated_at: string | null;
  /** optional context echoed in the header */
  description: string | null;
  points: ReportPoint[];
  detectors: ReportDetector[];
  alerts: ReportAlert[];
  summary: ReportSummary;
}

/** The report renderer's global entry, exposed by the bundled IIFE. */
export interface DtkReportGlobal {
  render(payload: ReportPayload, mount: HTMLElement): void;
}
