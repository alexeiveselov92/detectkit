// The Builder form: a structured, section-by-section editor for one metric's
// config, living inside the metric editor overlay next to the raw YAML tab
// (see metric-editor.ts). It is fed a *parsed* metric mapping (the same shape
// `POST /api/metric-parse` / `GET /api/metric-source` return — snake_case
// keys straight off `yaml.safe_load` + `unwrap_metric_mapping`, NOT the tune
// cockpit's camelCased detector shape) and hands one back via `toData()` /
// `toYaml()`.
//
// Guiding invariant — nothing the form doesn't model is ever lost:
//  - Every detector row keeps the params IT doesn't render (smoothing,
//    seasonality_components, start_time, weighting, …) in `extraParams` and
//    merges them back on emit (see `seedDetectorRow` / `detectorRowToData`).
//    A detector whose `type` isn't in the picker (prophet/timesfm/a future
//    type) round-trips its whole entry verbatim — the row is read-only.
//  - The alerting block keeps every subkey the rail doesn't render (the four
//    `template_*` strings — multi-line message bodies that belong in the YAML
//    tab — and any future key) in `extraAlerting` and merges it back the same
//    way. A seed with more than one alerting entry is treated as
//    verbatim-passthrough end to end (edit it in the YAML tab instead).
//  - Any top-level key the form doesn't model at all (`autotune`, `tables`,
//    `false_alert_budget`, an unknown key) is carried in `topExtras` and
//    re-emitted untouched, in its original seed order, right before `enabled`.
// Every one of these merges filters its passthrough bag against the *current*
// modeled-key set at emit time (not just at seed time) — cheap insurance
// against a stale key colliding with a value the user actually set after
// switching, say, a detector's type.
//
// OSI apply rule (the "From OSI" sub-tab, see `buildQueryPane`): a successful
// compile always replaces the query and always offers `description` /
// `ai_context` / `seasonality_columns` from the compiled body (only when the
// body actually carries them — an absent key leaves the current form value
// untouched, it is never cleared); `name` is filled ONLY in create mode and
// ONLY when the user hasn't typed one yet, and NEVER in edit mode. Detector
// config is deliberately excluded from that list: the importer always
// fabricates a starter `{type: mad, params: {threshold: 3.0}}`, but the
// user's own Detectors section is "the metric's other form state" the spec
// says to keep — so `body.detectors` is read by no one here.
//
// Every user-facing control here calls `cb.onDirty()` on change; `setFromData`
// (a full reseed, e.g. after a YAML-tab edit round-trips through
// `postMetricParse`) deliberately does NOT — the shell already knows it's
// dirty from whatever edit triggered the reseed.

import type {
  FormMeta,
  OsiImportRequest,
  OsiImportResponse,
  OsiInspectModel,
  OsiInspectResponse,
} from './payload';
import { emitYamlDoc } from './yaml-emit';
import { createSqlEditor } from './sql-editor';
import { debounce } from './format';

export interface MetricFormCallbacks {
  /** Fires on ANY user edit — the shell tracks dirtiness + debounced revalidation. */
  onDirty(): void;
  osiInspect(text: string): Promise<OsiInspectResponse>;
  osiImport(req: OsiImportRequest): Promise<OsiImportResponse>;
}

export interface MetricFormHandle {
  /** The whole Builder pane. */
  el: HTMLElement;
  /** (Re)seed every control from a parsed metric mapping — a full rebuild. */
  setFromData(data: Record<string, unknown>): void;
  /** Ordered plain object ready for `emitYamlDoc` (see the key-order comment on `toData`). */
  toData(): Record<string, unknown>;
  toYaml(): string;
  /** Quick client-side checks (empty = ok); the shell renders these next to Save. */
  clientIssues(): string[];
  focusFirst(): void;
}

// -----------------------------------------------------------------------
// Small DOM helpers
// -----------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
}

/** A `.dtk-ui-field` wrapper: label + control (+ optional muted hint line). */
function field(labelText: string, control: HTMLElement, hint?: string): HTMLElement {
  const wrap = el('div', 'dtk-ui-field');
  const label = el('span', 'dtk-ui-field-label');
  label.textContent = labelText;
  wrap.append(label, control);
  if (hint) {
    const h = el('div', 'dtk-ui-editor-hint');
    h.textContent = hint;
    wrap.appendChild(h);
  }
  return wrap;
}

/** A rail section: a titled `.dtk-ui-form-sec` card; callers append into `body`. */
function section(title: string): { root: HTMLElement; body: HTMLElement } {
  const root = el('div', 'dtk-ui-form-sec');
  const head = el('div', 'dtk-ui-form-sec-head');
  const h = el('span', 'dtk-ui-form-sec-title');
  h.textContent = title;
  head.appendChild(h);
  root.appendChild(head);
  const body = el('div', 'dtk-ui-form-sec-body');
  root.appendChild(body);
  return { root, body };
}

/** A collapsible `<details>` chunk within (or as) a section — "advanced" params. */
function advancedGroup(summaryText: string): { details: HTMLDetailsElement; body: HTMLElement } {
  const details = document.createElement('details');
  details.className = 'dtk-ui-form-adv';
  const summary = document.createElement('summary');
  summary.className = 'dtk-ui-form-adv-summary';
  summary.textContent = summaryText;
  details.appendChild(summary);
  const body = el('div', 'dtk-ui-form-adv-body');
  details.appendChild(body);
  return { details, body };
}

interface ChipInputHandle {
  el: HTMLElement;
  get(): string[];
  set(values: string[]): void;
}

/** A tag/mention/synonym-style chip list: type + Enter (or blur) adds, ✕ removes. */
function buildChipInput(initial: string[], placeholder: string, onChange: () => void): ChipInputHandle {
  const wrap = el('div', 'dtk-ui-chipinput');
  const chipsRow = el('div', 'dtk-ui-chipinput-chips');
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'dtk-ui-chipinput-field';
  input.placeholder = placeholder;
  wrap.append(chipsRow, input);

  let values = [...initial];

  function renderChips(): void {
    chipsRow.innerHTML = '';
    for (const v of values) {
      const chip = el('span', 'dtk-ui-chip');
      const label = document.createElement('span');
      label.textContent = v;
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'dtk-ui-chip-x';
      x.textContent = '✕';
      x.title = `remove ${v}`;
      x.onclick = (): void => {
        values = values.filter((existing) => existing !== v);
        renderChips();
        onChange();
      };
      chip.append(label, x);
      chipsRow.appendChild(chip);
    }
  }
  renderChips();

  function addFromInput(): void {
    const v = input.value.trim();
    input.value = '';
    if (!v || values.includes(v)) return;
    values.push(v);
    renderChips();
    onChange();
  }

  input.addEventListener('keydown', (e: KeyboardEvent): void => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addFromInput();
    }
  });
  input.addEventListener('blur', addFromInput);

  return {
    el: wrap,
    get: () => [...values],
    set: (v: string[]): void => {
      values = [...v];
      renderChips();
    },
  };
}

interface PairInputHandle {
  el: HTMLElement;
  /** Only fully-filled rows; a half-typed row is simply not emitted. */
  get(): Record<string, string>;
}

/**
 * A `{label: url}` map editor — one removable row per entry plus an "Add link"
 * button. Rows are the state (not the emitted object), so two entries can share a
 * blank label mid-typing without one silently clobbering the other.
 */
function buildPairInput(
  initial: Record<string, string>,
  keyPlaceholder: string,
  valuePlaceholder: string,
  onChange: () => void,
): PairInputHandle {
  const wrap = el('div', 'dtk-ui-pairs');
  const rows: { key: HTMLInputElement; value: HTMLInputElement }[] = [];

  function addRow(k: string, v: string): void {
    const row = el('div', 'dtk-ui-pairrow');
    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.className = 'dtk-ui-input dtk-ui-pairkey';
    keyInput.placeholder = keyPlaceholder;
    keyInput.value = k;
    keyInput.oninput = onChange;
    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.className = 'dtk-ui-input';
    valueInput.placeholder = valuePlaceholder;
    valueInput.value = v;
    valueInput.oninput = onChange;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'dtk-ui-detrow-remove';
    remove.textContent = '✕';
    remove.title = 'remove link';
    const entry = { key: keyInput, value: valueInput };
    remove.onclick = (): void => {
      const at = rows.indexOf(entry);
      if (at >= 0) rows.splice(at, 1);
      row.remove();
      onChange();
    };
    row.append(keyInput, valueInput, remove);
    rows.push(entry);
    wrap.insertBefore(row, addBtn);
  }

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'dtk-ui-chip-preset';
  addBtn.textContent = '+ Add link';
  addBtn.onclick = (): void => {
    addRow('', '');
    onChange();
  };
  wrap.appendChild(addBtn);
  for (const [k, v] of Object.entries(initial)) addRow(k, v);

  return {
    el: wrap,
    get: (): Record<string, string> => {
      const out: Record<string, string> = {};
      for (const r of rows) {
        const k = r.key.value.trim();
        const v = r.value.value.trim();
        if (k && v) out[k] = v;
      }
      return out;
    },
  };
}

/**
 * A handful of config fields accept either an int (seconds) or a unit-suffixed
 * duration string ("10min", "1h") — but `detectkit.core.interval.Interval`'s
 * string branch REQUIRES a unit suffix (`^\d+[a-z]+$`); a bare numeric STRING
 * ("600") fails it, even though the same value as a real int works fine.
 * `yaml-emit.ts` quotes any digit-leading string, so a bare-digit value typed
 * into a text input must become a genuine YAML number, not a quoted string, or
 * the server round-trip rejects it on save. A unit-suffixed string ("10min")
 * passes through untouched (quoted by the emitter, which round-trips fine).
 */
function coerceDurationValue(raw: string): number | string {
  const trimmed = raw.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed;
}

// -----------------------------------------------------------------------
// Top-level field bookkeeping
// -----------------------------------------------------------------------

/** Every top-level metric-YAML key the form models directly (see `toData`'s key order). */
const MODELED_TOP_KEYS = new Set([
  'name',
  'description',
  'tags',
  'profile',
  'source_profile',
  'ai_context',
  'query',
  'query_file',
  'query_columns',
  'interval',
  'loading_start_time',
  'loading_delay',
  'loading_batch_size',
  'seasonality_columns',
  'detectors',
  'alerting',
  'enabled',
]);

/** Top-level keys the form doesn't model (autotune, tables, false_alert_budget, unknown keys, …). */
function computeTopExtras(data: Record<string, unknown> | null): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!data) return out;
  for (const [k, v] of Object.entries(data)) {
    if (!MODELED_TOP_KEYS.has(k)) out[k] = v;
  }
  return out;
}

/** "Preserved fields" rail section — shown only when non-empty, never editable. */
function buildPreservedSection(topExtras: Record<string, unknown>): HTMLElement {
  const { root, body } = section('Preserved fields');
  const hint = el('div', 'dtk-ui-editor-hint');
  hint.textContent =
    "These config keys aren't editable in the Builder — they round-trip untouched. Use the YAML tab to change them.";
  body.appendChild(hint);
  const chips = el('div', 'dtk-ui-preschips');
  for (const key of Object.keys(topExtras)) {
    const chip = el('span', 'dtk-ui-preschip');
    chip.textContent = key;
    chips.appendChild(chip);
  }
  body.appendChild(chips);
  return root;
}

// -----------------------------------------------------------------------
// Basics
// -----------------------------------------------------------------------

// Mirrors the server rule (MetricConfig.validate_name: unicode isalnum or _/-),
// so a client-side block never rejects a name the server would accept.
const NAME_RE = /^[\p{L}\p{N}_-]+$/u;

interface BasicsSection {
  el: HTMLElement;
  getName(): string;
  getDescription(): string;
  getTags(): string[];
  getEnabled(): boolean;
  getProfile(): string;
  getSourceProfile(): string;
  /** Used only by the OSI-apply flow (create mode, name still blank). */
  setName(v: string): void;
  setDescription(v: string): void;
  focusName(): void;
  issues(): string[];
}

/**
 * A profile picker seeded from `form_meta.profiles`. A seeded name the server
 * didn't list (a profile added to profiles.yml after the page booted, or one the
 * boot payload omits) is prepended so opening the editor can never silently drop it.
 */
function buildProfileSelect(seed: unknown, meta: FormMeta, emptyLabel: string, cb: MetricFormCallbacks): HTMLSelectElement {
  const select = document.createElement('select');
  select.className = 'dtk-ui-select';
  const emptyOpt = document.createElement('option');
  emptyOpt.value = '';
  emptyOpt.textContent = emptyLabel;
  select.appendChild(emptyOpt);
  const seeded = typeof seed === 'string' ? seed : '';
  const names = seeded && !meta.profiles.includes(seeded) ? [seeded, ...meta.profiles] : meta.profiles;
  for (const p of names) {
    const o = document.createElement('option');
    o.value = p;
    o.textContent = p;
    select.appendChild(o);
  }
  select.value = seeded;
  select.onchange = (): void => cb.onDirty();
  return select;
}

function buildBasicsSection(data: Record<string, unknown> | null, meta: FormMeta, cb: MetricFormCallbacks): BasicsSection {
  const { root, body } = section('Basics');

  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'dtk-ui-input';
  nameInput.placeholder = 'my_metric';
  // Create mode starts with the same starter NAME the YAML template uses — a
  // blank name made every partial create draft invalid ("name — field
  // required"), turning the YAML tab into a trap: its live-validation chip
  // 400s and the way back to the Builder is gated on a valid parse.
  nameInput.value = typeof data?.name === 'string' ? data.name : data === null ? 'my_metric' : '';
  const nameErr = el('div', 'dtk-ui-form-err-inline');
  function validateName(): void {
    const v = nameInput.value.trim();
    nameErr.textContent = v === '' || NAME_RE.test(v) ? '' : 'letters, digits, _ and - only';
  }
  nameInput.oninput = (): void => {
    validateName();
    cb.onDirty();
  };
  validateName();
  const nameField = field('Name', nameInput);
  nameField.appendChild(nameErr);
  body.appendChild(nameField);

  const descInput = document.createElement('textarea');
  descInput.className = 'dtk-ui-input dtk-ui-textarea';
  descInput.rows = 3;
  descInput.value = typeof data?.description === 'string' ? data.description : '';
  descInput.oninput = (): void => cb.onDirty();
  body.appendChild(field('Description', descInput));

  const tagsInitial = Array.isArray(data?.tags) ? (data!.tags as unknown[]).map(String) : [];
  const tagsChips = buildChipInput(tagsInitial, 'add tag, Enter', () => cb.onDirty());
  body.appendChild(field('Tags', tagsChips.el));

  const profileSelect = buildProfileSelect(data?.profile, meta, '(project default)', cb);
  body.appendChild(field('Profile', profileSelect));

  // Hybrid mode: the metric's load SQL runs on this profile's database while every
  // `_dtk_*` table stays on the state profile above. Source-only backends
  // (Snowflake/BigQuery) are valid HERE and nowhere else, which is exactly why the
  // Builder has to model it — a YAML-only field can't be set on a new metric.
  const sourceSelect = buildProfileSelect(data?.source_profile, meta, '(same as profile)', cb);
  body.appendChild(
    field(
      'Source profile',
      sourceSelect,
      'Hybrid mode: run this metric’s load SQL against another profile’s database. State stays on the profile above.',
    ),
  );

  const enabledLabel = document.createElement('label');
  enabledLabel.className = 'dtk-ui-check';
  const enabledBox = document.createElement('input');
  enabledBox.type = 'checkbox';
  enabledBox.checked = data?.enabled !== false;
  enabledBox.onchange = (): void => cb.onDirty();
  enabledLabel.append(enabledBox, document.createTextNode('Enabled'));
  body.appendChild(enabledLabel);

  return {
    el: root,
    getName: () => nameInput.value.trim(),
    getDescription: () => descInput.value,
    getTags: () => tagsChips.get(),
    getEnabled: () => enabledBox.checked,
    getProfile: () => profileSelect.value.trim(),
    getSourceProfile: () => sourceSelect.value.trim(),
    setName: (v: string): void => {
      nameInput.value = v;
      validateName();
    },
    setDescription: (v: string): void => {
      descInput.value = v;
    },
    focusName: () => nameInput.focus(),
    issues: () => {
      const v = nameInput.value.trim();
      if (v === '') return ['name is required'];
      if (!NAME_RE.test(v)) return ['name has invalid characters (use letters, digits, _ or -)'];
      return [];
    },
  };
}

// -----------------------------------------------------------------------
// Schedule & loading
// -----------------------------------------------------------------------

const INTERVAL_PRESETS = ['10min', '1h', '1d'];
const INTERVAL_RE =
  /^\d+(s|sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hour|hours|d|day|days)?$/i;

interface ScheduleSection {
  el: HTMLElement;
  getInterval(): string;
  getLoadingStartTime(): string;
  getLoadingDelay(): string;
  getLoadingBatchSize(): number | null;
  getQueryColumns(): Record<string, unknown> | null;
  issues(): string[];
}

function buildScheduleSection(data: Record<string, unknown> | null, cb: MetricFormCallbacks): ScheduleSection {
  const { root, body } = section('Schedule & loading');

  const intervalInput = document.createElement('input');
  intervalInput.type = 'text';
  intervalInput.className = 'dtk-ui-input';
  intervalInput.placeholder = '1h';
  intervalInput.value = data?.interval !== undefined && data?.interval !== null ? String(data.interval) : '1h';
  const intervalErr = el('div', 'dtk-ui-form-err-inline');
  function validateInterval(): void {
    const v = intervalInput.value.trim();
    intervalErr.textContent = v === '' || INTERVAL_RE.test(v) ? '' : 'looks unusual — the server validates on save';
  }
  intervalInput.oninput = (): void => {
    validateInterval();
    cb.onDirty();
  };
  validateInterval();
  const intervalField = field('Interval', intervalInput);
  const presetsRow = el('div', 'dtk-ui-chip-presets');
  for (const p of INTERVAL_PRESETS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dtk-ui-chip-preset';
    btn.textContent = p;
    btn.onclick = (): void => {
      intervalInput.value = p;
      validateInterval();
      cb.onDirty();
    };
    presetsRow.appendChild(btn);
  }
  intervalField.appendChild(presetsRow);
  intervalField.appendChild(intervalErr);
  body.appendChild(intervalField);

  const startInput = document.createElement('input');
  startInput.type = 'text';
  startInput.className = 'dtk-ui-input';
  startInput.placeholder = 'YYYY-MM-DD HH:MM:SS';
  startInput.value = typeof data?.loading_start_time === 'string' ? data.loading_start_time : '';
  startInput.oninput = (): void => cb.onDirty();
  body.appendChild(field('Loading start time', startInput));

  const qcSeed = data?.query_columns && typeof data.query_columns === 'object' ? (data.query_columns as Record<string, unknown>) : {};
  const seedBatch = typeof data?.loading_batch_size === 'number' ? data.loading_batch_size : null;
  const hasAdvSeed =
    data?.loading_delay !== undefined ||
    (seedBatch !== null && seedBatch !== 10000) ||
    Object.keys(qcSeed).length > 0;

  const adv = advancedGroup('Advanced');
  adv.details.open = hasAdvSeed;
  body.appendChild(adv.details);

  const delayInput = document.createElement('input');
  delayInput.type = 'text';
  delayInput.className = 'dtk-ui-input';
  delayInput.placeholder = 'e.g. 10min (optional)';
  delayInput.value = data?.loading_delay !== undefined && data?.loading_delay !== null ? String(data.loading_delay) : '';
  delayInput.oninput = (): void => cb.onDirty();
  adv.body.appendChild(field('Loading delay', delayInput, 'Data-maturity delay before the newest interval is trusted complete.'));

  const batchInput = document.createElement('input');
  batchInput.type = 'number';
  batchInput.min = '1';
  batchInput.className = 'dtk-ui-input';
  batchInput.placeholder = '10000';
  batchInput.value = seedBatch !== null && seedBatch !== 10000 ? String(seedBatch) : '';
  batchInput.oninput = (): void => cb.onDirty();
  adv.body.appendChild(field('Loading batch size', batchInput));

  const tsColInput = document.createElement('input');
  tsColInput.type = 'text';
  tsColInput.className = 'dtk-ui-input';
  tsColInput.placeholder = 'timestamp';
  tsColInput.value = typeof qcSeed.timestamp === 'string' ? qcSeed.timestamp : '';
  tsColInput.oninput = (): void => cb.onDirty();
  const metricColInput = document.createElement('input');
  metricColInput.type = 'text';
  metricColInput.className = 'dtk-ui-input';
  metricColInput.placeholder = 'value';
  metricColInput.value = typeof qcSeed.metric === 'string' ? qcSeed.metric : '';
  metricColInput.oninput = (): void => cb.onDirty();
  const qcRow = el('div', 'dtk-ui-row2');
  qcRow.append(field('Timestamp column', tsColInput), field('Value column', metricColInput));
  adv.body.appendChild(qcRow);

  const seasColsInitial = Array.isArray(qcSeed.seasonality) ? (qcSeed.seasonality as unknown[]).map(String) : [];
  const seasColsChips = buildChipInput(seasColsInitial, 'add query column name, Enter', () => cb.onDirty());
  adv.body.appendChild(field('Seasonality columns (in query results)', seasColsChips.el));

  return {
    el: root,
    getInterval: () => intervalInput.value.trim(),
    getLoadingStartTime: () => startInput.value.trim(),
    getLoadingDelay: () => delayInput.value.trim(),
    getLoadingBatchSize: () => {
      const raw = batchInput.value.trim();
      if (!raw) return null;
      const n = Math.round(Number(raw));
      return Number.isFinite(n) && n !== 10000 ? n : null;
    },
    getQueryColumns: () => {
      const ts = tsColInput.value.trim();
      const mc = metricColInput.value.trim();
      const sc = seasColsChips.get();
      if (!ts && !mc && sc.length === 0) return null;
      const out: Record<string, unknown> = {};
      if (ts) out.timestamp = ts;
      if (mc) out.metric = mc;
      if (sc.length > 0) out.seasonality = sc;
      return out;
    },
    issues: () => (intervalInput.value.trim() === '' ? ['interval is required'] : []),
  };
}

// -----------------------------------------------------------------------
// Seasonality
// -----------------------------------------------------------------------

const SEASONALITY_COLUMNS: Array<{ key: string; label: string }> = [
  { key: 'hour', label: 'Hour' },
  { key: 'day_of_week', label: 'Day of week' },
  { key: 'day_of_month', label: 'Day of month' },
  { key: 'month', label: 'Month' },
  { key: 'is_weekend', label: 'Weekend' },
  { key: 'is_holiday', label: 'Holiday' },
];

interface SeasonalitySection {
  el: HTMLElement;
  getColumns(): string[];
  /** Used only by the OSI-apply flow. */
  setColumns(cols: string[]): void;
}

function buildSeasonalitySection(data: Record<string, unknown> | null, cb: MetricFormCallbacks): SeasonalitySection {
  const { root, body } = section('Seasonality');
  const seed = new Set(Array.isArray(data?.seasonality_columns) ? (data!.seasonality_columns as unknown[]).map(String) : []);
  const boxes: Record<string, HTMLInputElement> = {};
  const wrap = el('div', 'dtk-ui-checks');
  for (const { key, label } of SEASONALITY_COLUMNS) {
    const lbl = document.createElement('label');
    lbl.className = 'dtk-ui-check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = seed.has(key);
    box.onchange = (): void => cb.onDirty();
    lbl.append(box, document.createTextNode(label));
    wrap.appendChild(lbl);
    boxes[key] = box;
  }
  body.appendChild(wrap);

  return {
    el: root,
    getColumns: () => SEASONALITY_COLUMNS.filter((c) => boxes[c.key].checked).map((c) => c.key),
    setColumns: (cols: string[]): void => {
      const set = new Set(cols);
      for (const { key } of SEASONALITY_COLUMNS) boxes[key].checked = set.has(key);
    },
  };
}

// -----------------------------------------------------------------------
// Detectors
// -----------------------------------------------------------------------

const DETECTOR_TYPES = ['mad', 'zscore', 'iqr', 'autoreg', 'manual_bounds'] as const;
type KnownDetectorType = (typeof DETECTOR_TYPES)[number];

function isKnownDetectorType(t: string): t is KnownDetectorType {
  return (DETECTOR_TYPES as readonly string[]).includes(t);
}

/** The params each detector type's row renders as real controls — everything else is passthrough. */
const MODELED_KEYS: Record<KnownDetectorType, string[]> = {
  mad: ['threshold', 'window_size'],
  zscore: ['threshold', 'window_size'],
  iqr: ['threshold', 'window_size'],
  autoreg: ['threshold', 'window_size', 'lags'],
  manual_bounds: ['lower_bound', 'upper_bound'],
};

const FIELD_LABELS: Record<string, string> = {
  threshold: 'Threshold',
  window_size: 'Window size',
  lags: 'Lags',
  lower_bound: 'Lower bound',
  upper_bound: 'Upper bound',
};

const FIELD_PLACEHOLDERS: Record<KnownDetectorType, Record<string, string>> = {
  mad: { threshold: '3.0', window_size: '100' },
  zscore: { threshold: '3.0', window_size: '100' },
  iqr: { threshold: '3.0', window_size: '100' },
  autoreg: { threshold: '3.0', window_size: '200', lags: '5' },
  manual_bounds: {},
};

interface DetectorRowState {
  /** The detector's `type`. For an unknown type (prophet/timesfm/future), never changes. */
  type: string;
  /** The whole original entry (type + params + anything else) — the unknown-type verbatim fallback. */
  raw: Record<string, unknown>;
  /** Params the seeded type didn't model — carried through untouched while the type stays put. */
  extraParams: Record<string, unknown>;
  /**
   * The type `extraParams` belong to (the seeded type). Extras are emitted only while
   * `type === extrasOwner`: an unmodeled param like `smoothing` is meaningful to the detector it
   * was written for, and emitting it under a switched type (mad → manual_bounds) would just make
   * the save fail validation. Switching back restores them — nothing is dropped.
   */
  extrasOwner: string;
  /** Modeled param values as typed (strings straight off the inputs; parsed to number on emit). */
  fields: Record<string, string>;
}

function seedDetectorRow(raw: unknown): DetectorRowState {
  const obj: Record<string, unknown> = raw && typeof raw === 'object' ? { ...(raw as Record<string, unknown>) } : {};
  const type = typeof obj.type === 'string' ? obj.type : '';
  if (!isKnownDetectorType(type)) {
    return { type, raw: obj, extraParams: {}, extrasOwner: type, fields: {} };
  }
  const paramsRaw: Record<string, unknown> = obj.params && typeof obj.params === 'object' ? (obj.params as Record<string, unknown>) : {};
  const modeled = new Set(MODELED_KEYS[type]);
  const extraParams: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(paramsRaw)) if (!modeled.has(k)) extraParams[k] = v;
  const fields: Record<string, string> = {};
  for (const k of MODELED_KEYS[type]) {
    const v = paramsRaw[k];
    if (v !== undefined && v !== null) fields[k] = String(v);
  }
  return { type, raw: obj, extraParams, extrasOwner: type, fields };
}

/** Row -> emitted detector entry. Extras ride along only under the type they were seeded for. */
function detectorRowToData(row: DetectorRowState): Record<string, unknown> {
  if (!isKnownDetectorType(row.type)) return row.raw;
  const modeledKeys = MODELED_KEYS[row.type];
  const modeledSet = new Set(modeledKeys);
  const params: Record<string, unknown> = {};
  if (row.type === row.extrasOwner) {
    for (const [k, v] of Object.entries(row.extraParams)) if (!modeledSet.has(k)) params[k] = v;
  }
  for (const k of modeledKeys) {
    const raw = row.fields[k];
    if (raw === undefined || raw.trim() === '') continue;
    const num = Number(raw);
    params[k] = Number.isFinite(num) ? num : raw;
  }
  return { type: row.type, params };
}

interface DetectorsSection {
  el: HTMLElement;
  getData(): unknown[];
  issues(): string[];
}

function buildDetectorsSection(
  data: Record<string, unknown> | null,
  cb: MetricFormCallbacks,
  mode: 'create' | 'edit',
): DetectorsSection {
  const { root, body } = section('Detectors');

  const hint = el('div', 'dtk-ui-editor-hint');
  hint.textContent =
    'Defaults are a fine start — load data, then fine-tune in the tune cockpit (Tune button on the metric row).';
  body.appendChild(hint);

  const rowsWrap = el('div', 'dtk-ui-detrows');
  body.appendChild(rowsWrap);

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'dtk-ui-btn';
  addBtn.textContent = '+ Add detector';
  body.appendChild(addBtn);

  const seedList = Array.isArray(data?.detectors) ? (data!.detectors as unknown[]) : [];
  let rows: DetectorRowState[] =
    seedList.length > 0
      ? seedList.map(seedDetectorRow)
      : mode === 'create'
        ? [seedDetectorRow({ type: 'mad', params: { threshold: 3.0, window_size: 100 } })]
        : [];

  function buildRowEl(row: DetectorRowState): HTMLElement {
    const rowEl = el('div', 'dtk-ui-detrow');
    const head = el('div', 'dtk-ui-detrow-head');

    if (isKnownDetectorType(row.type)) {
      const typeSelect = document.createElement('select');
      typeSelect.className = 'dtk-ui-select';
      for (const t of DETECTOR_TYPES) {
        const o = document.createElement('option');
        o.value = t;
        o.textContent = t;
        typeSelect.appendChild(o);
      }
      typeSelect.value = row.type;
      typeSelect.onchange = (): void => {
        const newType = typeSelect.value;
        if (!isKnownDetectorType(newType)) return; // unreachable — every option is a known type
        const kept: Record<string, string> = {};
        for (const k of MODELED_KEYS[newType]) if (row.fields[k] !== undefined) kept[k] = row.fields[k];
        row.type = newType;
        row.fields = kept;
        cb.onDirty();
        renderRows();
      };
      head.appendChild(typeSelect);
    } else {
      const badge = el('span', 'dtk-ui-detrow-readonly');
      badge.textContent = `${row.type || 'unknown type'} — preserved as-is, edit in the YAML tab`;
      head.appendChild(badge);
    }

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'dtk-ui-detrow-remove';
    removeBtn.textContent = '✕';
    removeBtn.title = 'Remove detector';
    removeBtn.onclick = (): void => {
      rows = rows.filter((r) => r !== row);
      cb.onDirty();
      renderRows();
    };
    head.appendChild(removeBtn);
    rowEl.appendChild(head);

    if (isKnownDetectorType(row.type)) {
      const fieldsRow = el('div', 'dtk-ui-detrow-fields');
      const keys = MODELED_KEYS[row.type];
      for (const k of keys) {
        const input = document.createElement('input');
        input.type = 'number';
        input.step = 'any';
        input.className = 'dtk-ui-input';
        input.placeholder = FIELD_PLACEHOLDERS[row.type][k] ?? '';
        input.value = row.fields[k] ?? '';
        input.oninput = (): void => {
          row.fields[k] = input.value;
          cb.onDirty();
        };
        fieldsRow.appendChild(field(FIELD_LABELS[k] ?? k, input));
      }
      rowEl.appendChild(fieldsRow);

      const modeledSet = new Set(keys);
      const extraCount = Object.keys(row.extraParams).filter((k) => !modeledSet.has(k)).length;
      if (extraCount > 0) {
        const chip = el('span', 'dtk-ui-preschip');
        chip.textContent =
          row.type === row.extrasOwner
            ? `+${extraCount} params preserved`
            : `${extraCount} ${row.extrasOwner} param(s) withheld — switch the type back to restore`;
        rowEl.appendChild(chip);
      }
    }

    return rowEl;
  }

  function renderRows(): void {
    rowsWrap.innerHTML = '';
    for (const row of rows) rowsWrap.appendChild(buildRowEl(row));
  }
  renderRows();

  addBtn.onclick = (): void => {
    rows.push(seedDetectorRow({ type: 'mad', params: { threshold: 3.0, window_size: 100 } }));
    cb.onDirty();
    renderRows();
  };

  return {
    el: root,
    getData: () => rows.map(detectorRowToData),
    issues: () => {
      const out: string[] = [];
      for (const row of rows) {
        if (row.type === 'manual_bounds') {
          const lo = row.fields.lower_bound;
          const hi = row.fields.upper_bound;
          if ((!lo || lo.trim() === '') && (!hi || hi.trim() === '')) {
            out.push('a manual_bounds detector needs at least a lower or upper bound');
          }
        }
      }
      return out;
    },
  };
}

// -----------------------------------------------------------------------
// Alerting
// -----------------------------------------------------------------------

const ALERTING_MODELED_KEYS = new Set([
  'enabled',
  'suppress_until',
  'timezone',
  'channels',
  'consecutive_anomalies',
  'direction',
  'no_data_alert',
  'notify_on_recovery',
  'alert_cooldown',
  'cooldown_reset_on_recovery',
  'min_detectors',
  'anomaly_window',
  'min_anomaly_share',
  'mentions',
  'dashboard_url',
  'links',
]);

// Mirrors `parse_suppress_until` (config/metric_config.py) — the server rejects
// anything else, so the form flags it inline instead of on save.
const SUPPRESS_UNTIL_RE = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$/;

interface SeededAlerting {
  mode: 'none' | 'single' | 'verbatim';
  block: Record<string, unknown>;
  verbatim?: unknown;
}

function seedAlerting(data: Record<string, unknown> | null): SeededAlerting {
  const raw = data?.alerting;
  if (raw === undefined || raw === null) return { mode: 'none', block: {} };
  if (Array.isArray(raw)) {
    if (raw.length > 1) return { mode: 'verbatim', block: {}, verbatim: raw };
    if (raw.length === 1 && raw[0] && typeof raw[0] === 'object') {
      return { mode: 'single', block: raw[0] as Record<string, unknown> };
    }
    return { mode: 'none', block: {} };
  }
  if (typeof raw === 'object') return { mode: 'single', block: raw as Record<string, unknown> };
  return { mode: 'none', block: {} };
}

interface AlertingSection {
  el: HTMLElement;
  /** `undefined` = omit the `alerting` key entirely. */
  getData(): unknown;
  issues(): string[];
}

function buildAlertingSection(data: Record<string, unknown> | null, meta: FormMeta, cb: MetricFormCallbacks): AlertingSection {
  const { root, body } = section('Alerting');
  const seeded = seedAlerting(data);

  if (seeded.mode === 'verbatim') {
    const notice = el('div', 'dtk-ui-form-warn');
    notice.textContent = 'Multiple alerting configs — edit them in the YAML tab.';
    body.appendChild(notice);
    return { el: root, getData: () => seeded.verbatim, issues: () => [] };
  }

  const blockSeed = seeded.block;
  const extraAlerting: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(blockSeed)) if (!ALERTING_MODELED_KEYS.has(k)) extraAlerting[k] = v;

  const masterLabel = document.createElement('label');
  masterLabel.className = 'dtk-ui-check';
  const masterBox = document.createElement('input');
  masterBox.type = 'checkbox';
  masterBox.checked = seeded.mode === 'single';
  masterLabel.append(masterBox, document.createTextNode('Alerting'));
  body.appendChild(masterLabel);

  const fieldsWrap = el('div', 'dtk-ui-alerting-fields');
  body.appendChild(fieldsWrap);

  const enabledLabel = document.createElement('label');
  enabledLabel.className = 'dtk-ui-check';
  const enabledBox = document.createElement('input');
  enabledBox.type = 'checkbox';
  enabledBox.checked = blockSeed.enabled !== false;
  enabledBox.onchange = (): void => cb.onDirty();
  enabledLabel.append(enabledBox, document.createTextNode('Enabled (uncheck to keep the config but pause sending)'));
  fieldsWrap.appendChild(enabledLabel);

  const metaNames = new Set(meta.channels.map((c) => c.name));
  const seedChannels = Array.isArray(blockSeed.channels) ? (blockSeed.channels as unknown[]).map(String) : [];
  const checkedKnown = new Set(seedChannels.filter((n) => metaNames.has(n)));
  const customInitial = seedChannels.filter((n) => !metaNames.has(n));

  const channelsField = el('div', 'dtk-ui-field');
  const channelsLabel = el('span', 'dtk-ui-field-label');
  channelsLabel.textContent = 'Channels';
  channelsField.appendChild(channelsLabel);
  const knownWrap = el('div', 'dtk-ui-checks');
  for (const c of meta.channels) {
    const lbl = document.createElement('label');
    lbl.className = 'dtk-ui-check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = checkedKnown.has(c.name);
    box.onchange = (): void => {
      if (box.checked) checkedKnown.add(c.name);
      else checkedKnown.delete(c.name);
      cb.onDirty();
    };
    const typeSpan = el('span', 'dtk-ui-check-type');
    typeSpan.textContent = `(${c.type})`;
    lbl.append(box, document.createTextNode(c.name + ' '), typeSpan);
    knownWrap.appendChild(lbl);
  }
  channelsField.appendChild(knownWrap);
  const customChips = buildChipInput(customInitial, 'add channel name, Enter', () => cb.onDirty());
  channelsField.appendChild(customChips.el);
  fieldsWrap.appendChild(channelsField);

  const consInput = document.createElement('input');
  consInput.type = 'number';
  consInput.min = '1';
  consInput.step = '1';
  consInput.className = 'dtk-ui-input';
  consInput.value = String(typeof blockSeed.consecutive_anomalies === 'number' ? blockSeed.consecutive_anomalies : 3);
  consInput.oninput = (): void => cb.onDirty();
  fieldsWrap.appendChild(field('Consecutive anomalies', consInput));

  const dirSelect = document.createElement('select');
  dirSelect.className = 'dtk-ui-select';
  for (const d of ['same', 'any', 'up', 'down']) {
    const o = document.createElement('option');
    o.value = d;
    o.textContent = d;
    dirSelect.appendChild(o);
  }
  dirSelect.value = typeof blockSeed.direction === 'string' ? blockSeed.direction : 'same';
  dirSelect.onchange = (): void => cb.onDirty();
  fieldsWrap.appendChild(field('Direction', dirSelect));

  const noDataLabel = document.createElement('label');
  noDataLabel.className = 'dtk-ui-check';
  const noDataBox = document.createElement('input');
  noDataBox.type = 'checkbox';
  noDataBox.checked = blockSeed.no_data_alert === true;
  noDataBox.onchange = (): void => cb.onDirty();
  noDataLabel.append(noDataBox, document.createTextNode('Alert on missing data'));
  fieldsWrap.appendChild(noDataLabel);

  const recoveryLabel = document.createElement('label');
  recoveryLabel.className = 'dtk-ui-check';
  const recoveryBox = document.createElement('input');
  recoveryBox.type = 'checkbox';
  recoveryBox.checked = blockSeed.notify_on_recovery === true;
  recoveryBox.onchange = (): void => cb.onDirty();
  recoveryLabel.append(recoveryBox, document.createTextNode('Notify on recovery'));
  fieldsWrap.appendChild(recoveryLabel);

  const cooldownInput = document.createElement('input');
  cooldownInput.type = 'text';
  cooldownInput.className = 'dtk-ui-input';
  cooldownInput.placeholder = 'e.g. 30min (optional)';
  cooldownInput.value = blockSeed.alert_cooldown !== undefined && blockSeed.alert_cooldown !== null ? String(blockSeed.alert_cooldown) : '';
  cooldownInput.oninput = (): void => cb.onDirty();
  fieldsWrap.appendChild(field('Alert cooldown', cooldownInput));

  // The operational "mute" lever — kept out of Advanced on purpose: it's what you
  // reach for during a known incident, and an expired value is harmless.
  const suppressInput = document.createElement('input');
  suppressInput.type = 'text';
  suppressInput.className = 'dtk-ui-input';
  suppressInput.placeholder = 'YYYY-MM-DD HH:MM:SS (optional)';
  suppressInput.value = typeof blockSeed.suppress_until === 'string' ? blockSeed.suppress_until : '';
  const suppressErr = el('div', 'dtk-ui-form-err-inline');
  function validateSuppress(): void {
    const v = suppressInput.value.trim();
    suppressErr.textContent = v === '' || SUPPRESS_UNTIL_RE.test(v) ? '' : 'use YYYY-MM-DD HH:MM:SS (UTC) or YYYY-MM-DD';
  }
  suppressInput.oninput = (): void => {
    validateSuppress();
    cb.onDirty();
  };
  validateSuppress();
  const suppressField = field(
    'Suppress until',
    suppressInput,
    'UTC. Load and detect keep running; only this config’s alerts are skipped until then, and resume automatically.',
  );
  suppressField.appendChild(suppressErr);
  fieldsWrap.appendChild(suppressField);

  const hasAdvSeed =
    blockSeed.min_detectors !== undefined ||
    blockSeed.anomaly_window !== undefined ||
    blockSeed.min_anomaly_share !== undefined ||
    blockSeed.timezone !== undefined ||
    blockSeed.cooldown_reset_on_recovery === false ||
    (blockSeed.links !== undefined && Object.keys(blockSeed.links as object).length > 0) ||
    (Array.isArray(blockSeed.mentions) && blockSeed.mentions.length > 0) ||
    !!blockSeed.dashboard_url;
  const adv = advancedGroup('Advanced');
  adv.details.open = hasAdvSeed;
  fieldsWrap.appendChild(adv.details);

  const minDetInput = document.createElement('input');
  minDetInput.type = 'number';
  minDetInput.min = '1';
  minDetInput.step = '1';
  minDetInput.className = 'dtk-ui-input';
  minDetInput.value = String(typeof blockSeed.min_detectors === 'number' ? blockSeed.min_detectors : 1);
  minDetInput.oninput = (): void => cb.onDirty();
  adv.body.appendChild(field('Min detectors', minDetInput));

  const windowRow = el('div', 'dtk-ui-row2');
  const windowInput = document.createElement('input');
  windowInput.type = 'text';
  windowInput.className = 'dtk-ui-input';
  windowInput.placeholder = 'e.g. 30min';
  windowInput.value = blockSeed.anomaly_window !== undefined && blockSeed.anomaly_window !== null ? String(blockSeed.anomaly_window) : '';
  windowInput.oninput = (): void => cb.onDirty();
  const shareInput = document.createElement('input');
  shareInput.type = 'number';
  shareInput.min = '0';
  shareInput.max = '1';
  shareInput.step = '0.05';
  shareInput.className = 'dtk-ui-input';
  shareInput.placeholder = 'e.g. 0.3';
  shareInput.value = typeof blockSeed.min_anomaly_share === 'number' ? String(blockSeed.min_anomaly_share) : '';
  shareInput.oninput = (): void => cb.onDirty();
  windowRow.append(field('Anomaly window', windowInput), field('Min anomaly share', shareInput));
  adv.body.appendChild(windowRow);

  const mentionsInitial = Array.isArray(blockSeed.mentions) ? (blockSeed.mentions as unknown[]).map(String) : [];
  const mentionsChips = buildChipInput(mentionsInitial, 'add mention, Enter', () => cb.onDirty());
  adv.body.appendChild(field('Mentions', mentionsChips.el));

  const dashUrlInput = document.createElement('input');
  dashUrlInput.type = 'text';
  dashUrlInput.className = 'dtk-ui-input';
  dashUrlInput.placeholder = 'https://…';
  dashUrlInput.value = typeof blockSeed.dashboard_url === 'string' ? blockSeed.dashboard_url : '';
  dashUrlInput.oninput = (): void => cb.onDirty();
  adv.body.appendChild(field('Dashboard URL', dashUrlInput));

  const linksSeed: Record<string, string> = {};
  if (blockSeed.links && typeof blockSeed.links === 'object' && !Array.isArray(blockSeed.links)) {
    for (const [k, v] of Object.entries(blockSeed.links as Record<string, unknown>)) linksSeed[k] = String(v);
  }
  const linksPairs = buildPairInput(linksSeed, 'Runbook', 'https://…', () => cb.onDirty());
  adv.body.appendChild(field('Extra links', linksPairs.el, 'Rendered next to the dashboard URL as clickable labels.'));

  const tzInput = document.createElement('input');
  tzInput.type = 'text';
  tzInput.className = 'dtk-ui-input';
  tzInput.placeholder = 'e.g. Europe/Moscow';
  tzInput.value = typeof blockSeed.timezone === 'string' ? blockSeed.timezone : '';
  tzInput.oninput = (): void => cb.onDirty();
  adv.body.appendChild(field('Timezone', tzInput, 'Display timezone for timestamps in this config’s messages (UTC when unset).'));

  // Default-true, so the checkbox is "on" unless the config says otherwise and only
  // an explicit `false` is emitted (keeping untouched configs byte-stable).
  const cooldownResetLabel = document.createElement('label');
  cooldownResetLabel.className = 'dtk-ui-check';
  const cooldownResetBox = document.createElement('input');
  cooldownResetBox.type = 'checkbox';
  cooldownResetBox.checked = blockSeed.cooldown_reset_on_recovery !== false;
  cooldownResetBox.onchange = (): void => cb.onDirty();
  cooldownResetLabel.append(cooldownResetBox, document.createTextNode('Reset cooldown on recovery'));
  adv.body.appendChild(cooldownResetLabel);

  if (Object.keys(extraAlerting).length > 0) {
    const chip = el('span', 'dtk-ui-preschip');
    chip.textContent = `+${Object.keys(extraAlerting).length} fields preserved`;
    fieldsWrap.appendChild(chip);
  }

  function refreshVisibility(): void {
    fieldsWrap.style.display = masterBox.checked ? '' : 'none';
  }
  masterBox.onchange = (): void => {
    refreshVisibility();
    cb.onDirty();
  };
  refreshVisibility();

  return {
    el: root,
    getData: () => {
      if (!masterBox.checked) return undefined;
      const out: Record<string, unknown> = { enabled: enabledBox.checked };
      const channels = [...meta.channels.filter((c) => checkedKnown.has(c.name)).map((c) => c.name), ...customChips.get()];
      if (channels.length > 0) out.channels = channels;
      // NOT `Number(x) || 3`: a typed "0" is falsy and would silently become 3
      // instead of clamping to the real minimum of 1.
      const cons = Number(consInput.value);
      out.consecutive_anomalies =
        consInput.value.trim() !== '' && Number.isFinite(cons) ? Math.max(1, Math.round(cons)) : 3;
      out.direction = dirSelect.value;
      out.no_data_alert = noDataBox.checked;
      out.notify_on_recovery = recoveryBox.checked;
      const cooldown = cooldownInput.value.trim();
      if (cooldown) out.alert_cooldown = coerceDurationValue(cooldown);
      if (!cooldownResetBox.checked) out.cooldown_reset_on_recovery = false;
      const suppress = suppressInput.value.trim();
      if (suppress) out.suppress_until = suppress;
      const tz = tzInput.value.trim();
      if (tz) out.timezone = tz;
      const minDetRaw = Number(minDetInput.value);
      const minDet =
        minDetInput.value.trim() !== '' && Number.isFinite(minDetRaw)
          ? Math.max(1, Math.round(minDetRaw))
          : 1;
      if (minDet !== 1) out.min_detectors = minDet;
      const win = windowInput.value.trim();
      const share = shareInput.value.trim();
      if (win && share) {
        out.anomaly_window = coerceDurationValue(win);
        out.min_anomaly_share = Number(share);
      }
      const mentions = mentionsChips.get();
      if (mentions.length > 0) out.mentions = mentions;
      const dash = dashUrlInput.value.trim();
      if (dash) out.dashboard_url = dash;
      const links = linksPairs.get();
      if (Object.keys(links).length > 0) out.links = links;
      // Passthrough LAST, filtered against the modeled-key set again (defensive —
      // seed-time filtering already excludes these, this just guards against drift).
      for (const [k, v] of Object.entries(extraAlerting)) if (!ALERTING_MODELED_KEYS.has(k)) out[k] = v;
      return out;
    },
    issues: () => {
      if (!masterBox.checked) return [];
      const out: string[] = [];
      const win = windowInput.value.trim();
      const share = shareInput.value.trim();
      if ((win === '') !== (share === '')) out.push('anomaly window and min anomaly share must be set together');
      const suppress = suppressInput.value.trim();
      if (suppress && !SUPPRESS_UNTIL_RE.test(suppress)) {
        out.push('suppress until must be a UTC datetime (YYYY-MM-DD HH:MM:SS) or a date');
      }
      const badLink = Object.entries(linksPairs.get()).find(([, url]) => !/^https?:\/\//.test(url));
      if (badLink) out.push(`links['${badLink[0]}'] must be an http:// or https:// URL`);
      return out;
    },
  };
}

// -----------------------------------------------------------------------
// AI context
// -----------------------------------------------------------------------

interface SeededAiContext {
  instructions: string;
  synonyms: string[];
  examples: string[];
}

function seedAiContext(raw: unknown): SeededAiContext {
  if (typeof raw === 'string') return { instructions: raw, synonyms: [], examples: [] };
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>;
    return {
      instructions: typeof o.instructions === 'string' ? o.instructions : '',
      synonyms: Array.isArray(o.synonyms) ? o.synonyms.map(String) : [],
      examples: Array.isArray(o.examples) ? o.examples.map(String) : [],
    };
  }
  return { instructions: '', synonyms: [], examples: [] };
}

interface AiContextSection {
  el: HTMLElement;
  getData(): Record<string, unknown> | undefined;
  /** Used only by the OSI-apply flow. */
  setData(v: Record<string, unknown> | undefined): void;
}

function buildAiContextSection(data: Record<string, unknown> | null, cb: MetricFormCallbacks): AiContextSection {
  const seeded = seedAiContext(data?.ai_context);
  const { root, body } = section('AI context');

  const details = document.createElement('details');
  details.className = 'dtk-ui-form-adv';
  details.open = !!(seeded.instructions || seeded.synonyms.length > 0 || seeded.examples.length > 0);
  const summary = document.createElement('summary');
  summary.className = 'dtk-ui-form-adv-summary';
  summary.textContent = 'Instructions / synonyms / examples';
  details.appendChild(summary);
  const inner = el('div', 'dtk-ui-form-adv-body');
  details.appendChild(inner);
  body.appendChild(details);

  const instrInput = document.createElement('textarea');
  instrInput.className = 'dtk-ui-input dtk-ui-textarea';
  instrInput.rows = 3;
  instrInput.placeholder = 'Business meaning / how to interpret this metric';
  instrInput.value = seeded.instructions;
  instrInput.oninput = (): void => cb.onDirty();
  inner.appendChild(field('Instructions', instrInput));

  const synChips = buildChipInput(seeded.synonyms, 'add synonym, Enter', () => cb.onDirty());
  inner.appendChild(field('Synonyms', synChips.el));

  const exChips = buildChipInput(seeded.examples, 'add example, Enter', () => cb.onDirty());
  inner.appendChild(field('Examples', exChips.el));

  return {
    el: root,
    getData: () => {
      const instructions = instrInput.value.trim();
      const synonyms = synChips.get();
      const examples = exChips.get();
      if (!instructions && synonyms.length === 0 && examples.length === 0) return undefined;
      const out: Record<string, unknown> = {};
      if (instructions) out.instructions = instructions;
      if (synonyms.length > 0) out.synonyms = synonyms;
      if (examples.length > 0) out.examples = examples;
      return out;
    },
    setData: (v: Record<string, unknown> | undefined): void => {
      const reseeded = seedAiContext(v ?? null);
      instrInput.value = reseeded.instructions;
      synChips.set(reseeded.synonyms);
      exChips.set(reseeded.examples);
      if (reseeded.instructions || reseeded.synonyms.length > 0 || reseeded.examples.length > 0) details.open = true;
    },
  };
}

// -----------------------------------------------------------------------
// Query pane (SQL | From OSI)
// -----------------------------------------------------------------------

// Mirrors metric-editor.ts's NEW_METRIC_TEMPLATE query body — kept as an
// independent literal here (Builder create-mode only needs the query text,
// not the surrounding YAML/comments the YAML-tab template also carries).
const DEFAULT_QUERY = `SELECT
  toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
  count() AS value
FROM my_table
WHERE event_time >= '{{ dtk_start_time }}'
  AND event_time < '{{ dtk_end_time }}'
GROUP BY timestamp
ORDER BY timestamp
`;

interface OsiProvenance {
  fingerprint: string;
  target: string;
  metric: string;
}

interface QueryPaneSection {
  el: HTMLElement;
  getMode(): 'inline' | 'file';
  getQuery(): string;
  getFilePath(): string;
  getOsiProvenance(): OsiProvenance | null;
  issues(): string[];
}

/** A bare-digit interval ("600") needs a unit suffix for the SERVER's `Interval` parser too. */
function intervalRequestString(raw: string): string {
  const trimmed = raw.trim();
  return /^\d+$/.test(trimmed) ? `${trimmed}s` : trimmed;
}

function buildQueryPane(
  data: Record<string, unknown> | null,
  cb: MetricFormCallbacks,
  getInterval: () => string,
  getSeasonalityColumns: () => string[],
  applyOsiFields: (body: Record<string, unknown>, metricName: string) => void,
): QueryPaneSection {
  const root = el('div', 'dtk-ui-form-query');

  const subtabs = el('div', 'dtk-ui-subtabs');
  const sqlTabBtn = document.createElement('button');
  sqlTabBtn.type = 'button';
  sqlTabBtn.className = 'dtk-ui-subtab on';
  sqlTabBtn.textContent = 'SQL';
  const osiTabBtn = document.createElement('button');
  osiTabBtn.type = 'button';
  osiTabBtn.className = 'dtk-ui-subtab';
  osiTabBtn.textContent = 'From OSI';
  subtabs.append(sqlTabBtn, osiTabBtn);
  root.appendChild(subtabs);

  const panes = el('div', 'dtk-ui-subtab-panes');
  root.appendChild(panes);
  const sqlPane = el('div', 'dtk-ui-subtab-pane');
  const osiPane = el('div', 'dtk-ui-subtab-pane');
  osiPane.style.display = 'none';
  panes.append(sqlPane, osiPane);

  function activate(tab: 'sql' | 'osi'): void {
    sqlTabBtn.classList.toggle('on', tab === 'sql');
    osiTabBtn.classList.toggle('on', tab === 'osi');
    sqlPane.style.display = tab === 'sql' ? '' : 'none';
    osiPane.style.display = tab === 'osi' ? '' : 'none';
  }
  sqlTabBtn.onclick = (): void => activate('sql');
  osiTabBtn.onclick = (): void => activate('osi');

  // ---- SQL pane -------------------------------------------------------------
  const queryFile = typeof data?.query_file === 'string' ? (data.query_file as string) : null;
  let mode: 'inline' | 'file' = queryFile ? 'file' : 'inline';
  let filePath = queryFile ?? '';
  const initialQuery =
    typeof data?.query === 'string' ? (data.query as string) : data === null && !queryFile ? DEFAULT_QUERY : '';

  let fileInfoWrap: HTMLElement | null = null;
  if (queryFile) {
    fileInfoWrap = document.createElement('div');
    const fileInput = document.createElement('input');
    fileInput.type = 'text';
    fileInput.className = 'dtk-ui-input';
    fileInput.readOnly = true;
    fileInput.value = queryFile;
    fileInfoWrap.appendChild(field('Query file (read-only)', fileInput));
    sqlPane.appendChild(fileInfoWrap);
  }

  const sqlEditor = createSqlEditor({
    value: initialQuery,
    onInput: () => cb.onDirty(),
    ariaLabel: 'Metric SQL query',
  });
  sqlPane.appendChild(sqlEditor.el);
  if (queryFile) {
    sqlEditor.setDisabled(
      true,
      `SQL lives in ${queryFile} — edit it on disk, or switch this metric to an inline query in the YAML tab.`,
    );
  }

  // ---- OSI pane ---------------------------------------------------------------
  const osiTextarea = document.createElement('textarea');
  osiTextarea.className = 'dtk-ui-input dtk-ui-textarea';
  osiTextarea.rows = 8;
  osiTextarea.placeholder = 'Paste an OSI semantic model (YAML)';
  osiPane.appendChild(field('OSI model', osiTextarea));

  const inspectStatus = el('div', 'dtk-ui-form-hint-status');
  osiPane.appendChild(inspectStatus);

  const metricSelect = document.createElement('select');
  metricSelect.className = 'dtk-ui-select';
  metricSelect.disabled = true;
  osiPane.appendChild(field('Metric', metricSelect));

  const targetSelect = document.createElement('select');
  targetSelect.className = 'dtk-ui-select';
  for (const t of ['clickhouse', 'cube']) {
    const o = document.createElement('option');
    o.value = t;
    o.textContent = t;
    targetSelect.appendChild(o);
  }
  osiPane.appendChild(field('Target', targetSelect));

  const datasetSelect = document.createElement('select');
  datasetSelect.className = 'dtk-ui-select';
  const datasetField = field('Dataset (optional)', datasetSelect);
  osiPane.appendChild(datasetField);

  const timeFieldInput = document.createElement('input');
  timeFieldInput.type = 'text';
  timeFieldInput.className = 'dtk-ui-input';
  timeFieldInput.placeholder = 'time column (auto-detected if omitted)';
  const timeFieldField = field('Time field (optional)', timeFieldInput);
  osiPane.appendChild(timeFieldField);

  const whereInput = document.createElement('input');
  whereInput.type = 'text';
  whereInput.className = 'dtk-ui-input';
  whereInput.placeholder = 'extra WHERE condition (optional)';
  osiPane.appendChild(field('Where (optional)', whereInput));

  const cubeInput = document.createElement('input');
  cubeInput.type = 'text';
  cubeInput.className = 'dtk-ui-input';
  cubeInput.placeholder = 'cube name';
  const cubeField = field('Cube (optional)', cubeInput);
  osiPane.appendChild(cubeField);

  const cubeMeasureInput = document.createElement('input');
  cubeMeasureInput.type = 'text';
  cubeMeasureInput.className = 'dtk-ui-input';
  cubeMeasureInput.placeholder = 'measure name (defaults to the metric name)';
  const cubeMeasureField = field('Cube measure (optional)', cubeMeasureInput);
  osiPane.appendChild(cubeMeasureField);

  const timeDimensionInput = document.createElement('input');
  timeDimensionInput.type = 'text';
  timeDimensionInput.className = 'dtk-ui-input';
  timeDimensionInput.placeholder = 'time dimension';
  const timeDimensionField = field('Time dimension (cube)', timeDimensionInput);
  osiPane.appendChild(timeDimensionField);

  function refreshTargetFields(): void {
    const isCube = targetSelect.value === 'cube';
    datasetField.style.display = isCube ? 'none' : '';
    timeFieldField.style.display = isCube ? 'none' : '';
    cubeField.style.display = isCube ? '' : 'none';
    cubeMeasureField.style.display = isCube ? '' : 'none';
    timeDimensionField.style.display = isCube ? '' : 'none';
  }
  // Browsing the OSI pane is NOT an edit: none of these controls feed toData()
  // until a Compile succeeds (which fires its own onDirty). Marking dirty here
  // would make a mere look at the pane re-emit the YAML (dropping comments) and
  // trip the unsaved-changes prompt.
  targetSelect.onchange = (): void => {
    refreshTargetFields();
  };
  refreshTargetFields();

  const compileBtn = document.createElement('button');
  compileBtn.type = 'button';
  compileBtn.className = 'dtk-ui-btn primary';
  compileBtn.textContent = 'Compile';
  osiPane.appendChild(compileBtn);

  const osiError = el('div', 'dtk-ui-form-err');
  osiPane.appendChild(osiError);
  const osiWarnings = el('div', 'dtk-ui-form-warn');
  osiPane.appendChild(osiWarnings);

  let models: OsiInspectModel[] = [];
  let osiProvenance: OsiProvenance | null = null;

  function currentModelIndex(): number {
    const idx = metricSelect.value.indexOf('::');
    return idx === -1 ? -1 : Number(metricSelect.value.slice(0, idx));
  }
  function currentMetricName(): string {
    const idx = metricSelect.value.indexOf('::');
    return idx === -1 ? metricSelect.value : metricSelect.value.slice(idx + 2);
  }

  function populateDatasetSelect(): void {
    datasetSelect.innerHTML = '';
    const autoOpt = document.createElement('option');
    autoOpt.value = '';
    autoOpt.textContent = '(auto)';
    datasetSelect.appendChild(autoOpt);
    const m = models[currentModelIndex()];
    for (const ds of m?.datasets ?? []) {
      const o = document.createElement('option');
      o.value = ds;
      o.textContent = ds;
      datasetSelect.appendChild(o);
    }
  }

  function populateMetricSelect(): void {
    metricSelect.innerHTML = '';
    if (models.length === 0) {
      metricSelect.disabled = true;
      populateDatasetSelect();
      return;
    }
    metricSelect.disabled = false;
    const useGroups = models.length > 1;
    models.forEach((m, mi) => {
      const container = useGroups ? document.createElement('optgroup') : null;
      if (container) {
        container.label = m.name;
        metricSelect.appendChild(container);
      }
      for (const metricName of m.metrics) {
        const o = document.createElement('option');
        o.value = `${mi}::${metricName}`;
        o.textContent = metricName;
        (container ?? metricSelect).appendChild(o);
      }
    });
    populateDatasetSelect();
  }
  metricSelect.onchange = (): void => {
    populateDatasetSelect(); // view-only until Compile — see the dirty note above
  };

  const runInspect = debounce(() => {
    const text = osiTextarea.value;
    if (text.trim() === '') {
      models = [];
      populateMetricSelect();
      inspectStatus.textContent = '';
      osiError.textContent = '';
      return;
    }
    inspectStatus.textContent = 'Inspecting…';
    cb
      .osiInspect(text)
      .then((res) => {
        models = res.models;
        populateMetricSelect();
        const total = models.reduce((n, m) => n + m.metrics.length, 0);
        inspectStatus.textContent = total > 0 ? `Found ${total} metric(s) across ${models.length} model(s).` : 'No metrics found.';
        osiError.textContent = '';
      })
      .catch((e: Error) => {
        models = [];
        populateMetricSelect();
        inspectStatus.textContent = '';
        osiError.textContent = e.message;
      });
  }, 400);
  osiTextarea.addEventListener('input', (): void => {
    runInspect(); // pasting a model to look at it is view-only until Compile
  });

  compileBtn.onclick = (): void => {
    osiError.textContent = '';
    osiWarnings.innerHTML = '';
    const text = osiTextarea.value;
    if (text.trim() === '') {
      osiError.textContent = 'paste an OSI model first';
      return;
    }
    if (metricSelect.value === '') {
      osiError.textContent = 'pick a metric to import';
      return;
    }
    const interval = getInterval();
    if (!interval) {
      osiError.textContent = 'set an interval in Schedule & loading first';
      return;
    }
    const target = targetSelect.value as 'clickhouse' | 'cube';
    const req: OsiImportRequest = {
      text,
      metric: currentMetricName(),
      interval: intervalRequestString(interval),
      target,
    };
    // Fold in whatever the user has already checked in Seasonality, so the
    // compiled body's seasonality_columns round-trips through — an empty
    // selection sends nothing, and applying the (then-absent) response field
    // back is a no-op, never a silent clear (see `applyOsiFields`'s caller).
    const seasonalityCols = getSeasonalityColumns();
    if (seasonalityCols.length > 0) req.seasonality = seasonalityCols;
    if (target === 'clickhouse') {
      if (datasetSelect.value) req.dataset = datasetSelect.value;
      if (timeFieldInput.value.trim()) req.time_field = timeFieldInput.value.trim();
      if (whereInput.value.trim()) req.where = whereInput.value.trim();
    } else {
      if (cubeInput.value.trim()) req.cube = cubeInput.value.trim();
      if (cubeMeasureInput.value.trim()) req.cube_measure = cubeMeasureInput.value.trim();
      if (timeDimensionInput.value.trim()) req.time_dimension = timeDimensionInput.value.trim();
      if (whereInput.value.trim()) req.where = whereInput.value.trim();
    }
    const metricName = currentMetricName();
    compileBtn.disabled = true;
    compileBtn.textContent = 'Compiling…';
    cb
      .osiImport(req)
      .then((res: OsiImportResponse) => {
        const sql = typeof res.body.query === 'string' ? (res.body.query as string) : res.sql;
        sqlEditor.setValue(sql);
        sqlEditor.setDisabled(false);
        if (fileInfoWrap) fileInfoWrap.style.display = 'none';
        mode = 'inline';
        filePath = '';
        activate('sql');
        osiProvenance = { fingerprint: res.fingerprint, target: res.target, metric: metricName };
        applyOsiFields(res.body, res.name || metricName);
        if (res.warnings.length > 0) {
          for (const w of res.warnings) {
            const line = document.createElement('div');
            line.textContent = `⚠ ${w}`;
            osiWarnings.appendChild(line);
          }
        }
        cb.onDirty();
      })
      .catch((e: Error) => {
        osiError.textContent = e.message;
      })
      .finally(() => {
        compileBtn.disabled = false;
        compileBtn.textContent = 'Compile';
      });
  };

  return {
    el: root,
    getMode: () => mode,
    getQuery: () => sqlEditor.getValue(),
    getFilePath: () => filePath,
    getOsiProvenance: () => osiProvenance,
    issues: () => (mode === 'inline' && sqlEditor.getValue().trim() === '' ? ['query is empty'] : []),
  };
}

// -----------------------------------------------------------------------
// Orchestrator
// -----------------------------------------------------------------------

export function buildMetricForm(
  seed: Record<string, unknown> | null,
  meta: FormMeta,
  cb: MetricFormCallbacks,
  opts: { mode: 'create' | 'edit' },
): MetricFormHandle {
  const rootEl = document.createElement('div');
  rootEl.className = 'dtk-ui-form';

  let basics!: BasicsSection;
  let schedule!: ScheduleSection;
  let seasonalitySec!: SeasonalitySection;
  let detectorsSec!: DetectorsSection;
  let alertingSec!: AlertingSection;
  let aiContextSec!: AiContextSection;
  let queryPane!: QueryPaneSection;
  let topExtras: Record<string, unknown> = {};

  function render(data: Record<string, unknown> | null): void {
    rootEl.innerHTML = '';
    const rail = el('div', 'dtk-ui-form-rail');
    const main = el('div', 'dtk-ui-form-main');
    rootEl.append(rail, main);

    topExtras = computeTopExtras(data);

    basics = buildBasicsSection(data, meta, cb);
    schedule = buildScheduleSection(data, cb);
    seasonalitySec = buildSeasonalitySection(data, cb);
    detectorsSec = buildDetectorsSection(data, cb, opts.mode);
    alertingSec = buildAlertingSection(data, meta, cb);
    aiContextSec = buildAiContextSection(data, cb);

    rail.append(basics.el, schedule.el, seasonalitySec.el, detectorsSec.el, alertingSec.el, aiContextSec.el);
    if (Object.keys(topExtras).length > 0) rail.appendChild(buildPreservedSection(topExtras));

    queryPane = buildQueryPane(
      data,
      cb,
      () => schedule.getInterval(),
      () => seasonalitySec.getColumns(),
      (body, metricName) => {
        // The create-mode starter name counts as "not chosen yet" — an OSI
        // compile should still hand its metric name over.
        if (opts.mode === 'create' && (basics.getName() === '' || basics.getName() === 'my_metric'))
          basics.setName(metricName);
        if (typeof body.description === 'string') basics.setDescription(body.description);
        if (body.ai_context && typeof body.ai_context === 'object') {
          aiContextSec.setData(body.ai_context as Record<string, unknown>);
        }
        if (Array.isArray(body.seasonality_columns)) {
          seasonalitySec.setColumns((body.seasonality_columns as unknown[]).map(String));
        }
      },
    );
    main.appendChild(queryPane.el);
  }

  render(seed);

  // toData()'s key order (see the module header comment for the passthrough
  // rules): name, description, tags, profile, source_profile, ai_context, query|query_file,
  // query_columns, interval, loading_start_time, loading_delay,
  // loading_batch_size, seasonality_columns, detectors, alerting, then
  // preserved top-level extras in their original seed order, enabled last
  // (only when false). Empty/default values are omitted throughout.
  function toData(): Record<string, unknown> {
    const out: Record<string, unknown> = {};

    const name = basics.getName();
    if (name) out.name = name;
    const description = basics.getDescription().trim();
    if (description) out.description = description;
    const tags = basics.getTags();
    if (tags.length > 0) out.tags = tags;
    const profile = basics.getProfile();
    if (profile) out.profile = profile;
    const sourceProfile = basics.getSourceProfile();
    if (sourceProfile) out.source_profile = sourceProfile;
    const aiCtx = aiContextSec.getData();
    if (aiCtx) out.ai_context = aiCtx;

    if (queryPane.getMode() === 'file') out.query_file = queryPane.getFilePath();
    else out.query = queryPane.getQuery();

    const qc = schedule.getQueryColumns();
    if (qc) out.query_columns = qc;

    const interval = schedule.getInterval();
    if (interval) out.interval = coerceDurationValue(interval);
    const lst = schedule.getLoadingStartTime();
    if (lst) out.loading_start_time = lst;
    const delay = schedule.getLoadingDelay();
    if (delay) out.loading_delay = coerceDurationValue(delay);
    const batch = schedule.getLoadingBatchSize();
    if (batch !== null) out.loading_batch_size = batch;

    const seasCols = seasonalitySec.getColumns();
    if (seasCols.length > 0) out.seasonality_columns = seasCols;

    const dets = detectorsSec.getData();
    if (dets.length > 0) out.detectors = dets;

    const alerting = alertingSec.getData();
    if (alerting !== undefined) out.alerting = alerting;

    for (const [k, v] of Object.entries(topExtras)) out[k] = v;

    if (!basics.getEnabled()) out.enabled = false;

    return out;
  }

  function toYaml(): string {
    const data = toData();
    const prov = queryPane.getOsiProvenance();
    const header = prov
      ? [
          `Query compiled from OSI metric '${prov.metric}' (target: ${prov.target}, sql-fingerprint: ${prov.fingerprint}).`,
          'Review the SQL before saving — re-compiling after the OSI model changes is a visible diff.',
        ]
      : undefined;
    return emitYamlDoc(data, header);
  }

  function clientIssues(): string[] {
    return [
      ...basics.issues(),
      ...schedule.issues(),
      ...queryPane.issues(),
      ...detectorsSec.issues(),
      ...alertingSec.issues(),
    ];
  }

  return {
    el: rootEl,
    setFromData: (data: Record<string, unknown>): void => render(data),
    toData,
    toYaml,
    clientIssues,
    focusFirst: (): void => basics.focusName(),
  };
}
