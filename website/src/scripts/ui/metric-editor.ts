// Metric editor overlay: create/edit/delete one metric's YAML in place.
//
// Two tabs share one draft: **Builder** (the structured form in metric-form.ts —
// SQL pane, parameter sections, OSI import) and **YAML** (the raw textarea kept
// for experts who paste whole configs). The last-edited tab wins, never
// silently: switching away from a dirty Builder re-emits the YAML text;
// switching away from a dirty YAML tab first parses it server-side
// (POST /api/metric-parse) and blocks the switch on error, so the two views can
// never hold diverging state. Saving posts through the same
// create/update seam as before (detectkit/ui/metric_files.py) — the Builder
// only changes *what text* is posted (a deterministic re-emit, comments
// dropped; the previous file is archived to metrics/.history/ exactly like a
// dtk tune Apply), while a YAML-tab save still writes the text verbatim.
// Server-side validation errors (pydantic/YAML, possibly multi-line) come back
// as plain-text bodies and are shown verbatim in a monospace error pane — the
// editor stays open so the user can fix and retry. A debounced validation chip
// runs the same parse endpoint while editing, so most errors surface before
// Save is ever clicked.

import { esc } from './format';
import {
  postMetricCreate,
  postMetricDelete,
  postMetricParse,
  postMetricUpdate,
  postOsiImport,
  postOsiInspect,
} from './api';
import { openOverlay } from './overlay';
import { buildMetricForm } from './metric-form';
import type { MetricFormHandle } from './metric-form';
import type { FormMeta, MetricMutationResponse } from './payload';

export type EditorMode = 'create' | 'edit';
type EditorTab = 'builder' | 'yaml';

/** Starter YAML seeded into a new metric's YAML tab — validates against MetricConfig as-is.
 * Kept semantically in sync with metric-form.ts's create-mode defaults, so the two tabs of a
 * fresh editor describe the same metric. */
export const NEW_METRIC_TEMPLATE = `# New metric — edit the query and name, then Create.
# Template variables available in query:
#   {{ dtk_start_time }} / {{ dtk_end_time }} — load window bounds
#   {{ interval_seconds }} — metric interval in seconds
name: my_metric
description: ""

query: |
  SELECT
    toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
    count() AS value
  FROM my_table
  WHERE event_time >= '{{ dtk_start_time }}'
    AND event_time < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

interval: 1h

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100

# Alerting (optional) — channels are names from profiles.yml alert_channels
# alerting:
#   enabled: true
#   channels: [my_channel]
#   consecutive_anomalies: 3
`;

export interface MetricEditorSeed {
  mode: EditorMode;
  /** edit mode only: the metric's current name. */
  name?: string;
  /** edit mode only: the file path, shown as a subtitle. */
  file?: string;
  /** the YAML tab's initial content — the starter template (create) or the fetched source (edit). */
  text: string;
  /** edit mode only: the source response's optimistic-concurrency token, echoed back on save. */
  digest?: string;
  /** the parsed metric mapping seeding the Builder; null/undefined ⇒ YAML-only (unparseable file). */
  data?: Record<string, unknown> | null;
  /** why `data` is null — shown as the disabled Builder tab's tooltip. */
  parseError?: string | null;
  /** boot form_meta: alert channel + profile names for the Builder's pickers. */
  meta: FormMeta;
}

export interface MetricEditorCallbacks {
  onSaved(res: MetricMutationResponse, mode: EditorMode): void;
  onDeleted(res: MetricMutationResponse): void;
  onClose(): void;
}

export interface MetricEditorHandle {
  /** Unconditional close — tears the overlay down even with unsaved edits. */
  close(): void;
  /**
   * Confirm-guarded close: prompts to discard unsaved edits (like Esc/backdrop/✕)
   * and returns whether the editor actually closed — hosts navigating away must
   * use this and abort when it returns false, so programmatic navigation can't
   * silently throw away a dirty editor.
   */
  requestClose(): boolean;
}

const EMPTY_META: FormMeta = { channels: [], profiles: [], default_profile: null };

/** Open the full-screen metric editor overlay, appended under `root`. */
export function openMetricEditor(
  root: HTMLElement,
  seed: MetricEditorSeed,
  cb: MetricEditorCallbacks,
): MetricEditorHandle {
  const isCreate = seed.mode === 'create';
  const meta = seed.meta ?? EMPTY_META;
  // Builder is available for create (seeded with defaults) and for any edit
  // whose on-disk text parsed; a broken file degrades to YAML-only with the
  // parse error as the disabled tab's tooltip.
  const builderAvailable = isCreate || (seed.data !== null && seed.data !== undefined);

  let dirty = false;
  let saving = false;
  // Per-tab "edited since the two views last agreed" flags — they drive the
  // sync-on-switch rules and decide which representation Save posts, so an
  // untouched Builder never rewrites a hand-formatted file.
  let formDirtySinceSync = false;
  let yamlDirtySinceSync = false;
  let tab: EditorTab = builderAvailable ? 'builder' : 'yaml';

  // ---- chrome: the shared overlay skeleton (Esc/backdrop close + focus trap) --
  const overlay = openOverlay(root, {
    modalClass: 'dtk-ui-editor-modal',
    onRequestClose: (): void => {
      requestClose();
    },
  });
  const { modal } = overlay;

  const head = document.createElement('div');
  head.className = 'dtk-ui-editor-head';
  const titleWrap = document.createElement('div');
  titleWrap.className = 'dtk-ui-editor-titlewrap';
  const title = document.createElement('span');
  title.className = 'dtk-ui-editor-title';
  title.textContent = isCreate ? 'New metric' : `Edit ${seed.name ?? ''}`;
  titleWrap.appendChild(title);
  if (!isCreate && seed.file) {
    const sub = document.createElement('span');
    sub.className = 'dtk-ui-editor-sub';
    sub.textContent = seed.file;
    titleWrap.appendChild(sub);
  }
  head.appendChild(titleWrap);

  // ---- tab strip: Builder | YAML ----------------------------------------------
  const tabsEl = document.createElement('div');
  tabsEl.className = 'dtk-ui-edtabs';
  const builderTabBtn = document.createElement('button');
  builderTabBtn.type = 'button';
  builderTabBtn.className = 'dtk-ui-edtab';
  builderTabBtn.textContent = 'Builder';
  if (!builderAvailable) {
    builderTabBtn.disabled = true;
    builderTabBtn.title = seed.parseError
      ? `This file doesn't parse as a metric config — fix it in YAML first.\n${seed.parseError}`
      : 'Builder unavailable for this file';
  }
  builderTabBtn.onclick = (): void => void setTab('builder');
  const yamlTabBtn = document.createElement('button');
  yamlTabBtn.type = 'button';
  yamlTabBtn.className = 'dtk-ui-edtab';
  yamlTabBtn.textContent = 'YAML';
  yamlTabBtn.onclick = (): void => void setTab('yaml');
  tabsEl.append(builderTabBtn, yamlTabBtn);
  head.appendChild(tabsEl);

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'dtk-ui-overlay-close';
  closeBtn.textContent = '✕';
  closeBtn.title = 'Close (Esc)';
  closeBtn.onclick = (): void => {
    requestClose();
  };
  head.appendChild(closeBtn);
  modal.appendChild(head);

  const body = document.createElement('div');
  body.className = 'dtk-ui-editor-body';
  modal.appendChild(body);

  // ---- folder field (create mode only, common to both tabs) -------------------
  let folderInput: HTMLInputElement | null = null;
  if (isCreate) {
    const folderField = document.createElement('div');
    folderField.className = 'dtk-ui-editor-field';
    folderField.innerHTML = '<span class="dtk-ui-field-label">Folder</span>';
    folderInput = document.createElement('input');
    folderInput.type = 'text';
    folderInput.className = 'dtk-ui-input';
    folderInput.placeholder = 'optional subfolder under metrics/';
    folderField.appendChild(folderInput);
    const hint = document.createElement('div');
    hint.className = 'dtk-ui-editor-hint';
    hint.textContent =
      'The file is written as metrics/[folder/]<name>.yml — <name> comes from the metric name below.';
    folderField.appendChild(hint);
    body.appendChild(folderField);
  }

  // ---- comments-dropped note (edit mode, Builder tab, commented source only) ---
  // A Builder save re-emits the YAML deterministically; hand-written comments
  // don't survive that. Only worth saying when the file actually has some.
  const sourceHasComments = !isCreate && /(^|\n)\s*#/.test(seed.text);
  const commentsNote = document.createElement('div');
  commentsNote.className = 'dtk-ui-editor-note';
  commentsNote.textContent =
    'Saving from Builder re-writes the YAML — comments are dropped ' +
    '(the previous file is archived to metrics/.history/).';
  commentsNote.style.display = 'none';
  body.appendChild(commentsNote);

  // ---- panes: Builder form + YAML textarea -------------------------------------
  const panes = document.createElement('div');
  panes.className = 'dtk-ui-editor-panes';
  body.appendChild(panes);

  const textarea = document.createElement('textarea');
  textarea.className = 'dtk-ui-editor-textarea';
  textarea.spellcheck = false;
  textarea.autocapitalize = 'off';
  textarea.value = seed.text;
  textarea.addEventListener('input', (): void => {
    dirty = true;
    yamlDirtySinceSync = true;
    scheduleValidate();
  });
  textarea.addEventListener('keydown', (e: KeyboardEvent): void => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      textarea.value = `${textarea.value.slice(0, start)}  ${textarea.value.slice(end)}`;
      textarea.selectionStart = textarea.selectionEnd = start + 2;
      dirty = true;
      yamlDirtySinceSync = true;
      scheduleValidate();
    }
  });

  let form: MetricFormHandle | null = null;
  if (builderAvailable) {
    form = buildMetricForm(
      isCreate ? null : (seed.data as Record<string, unknown>),
      meta,
      {
        onDirty: (): void => {
          dirty = true;
          formDirtySinceSync = true;
          scheduleValidate();
        },
        osiInspect: (text: string) => postOsiInspect(text),
        osiImport: (req) => postOsiImport(req),
      },
      { mode: seed.mode },
    );
    panes.appendChild(form.el);
  }
  panes.appendChild(textarea);

  // Ctrl/Cmd+S saves from either tab (bound on the modal, not the textarea).
  modal.addEventListener('keydown', (e: KeyboardEvent): void => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void save();
    }
  });

  // ---- error pane (above the footer, hidden by default) ------------------------
  const errorPane = document.createElement('div');
  errorPane.className = 'dtk-ui-editor-error';
  errorPane.style.display = 'none';
  modal.appendChild(errorPane);

  function showError(message: string): void {
    errorPane.textContent = message; // plain text — pre-wrap in CSS, no HTML to escape
    errorPane.style.display = '';
  }
  function hideError(): void {
    errorPane.style.display = 'none';
    errorPane.textContent = '';
  }

  // ---- footer: left = delete (edit mode), right = validation chip + save -------
  const footer = document.createElement('div');
  footer.className = 'dtk-ui-editor-foot';
  const leftSlot = document.createElement('div');
  leftSlot.className = 'dtk-ui-editor-foot-left';
  const rightSlot = document.createElement('div');
  rightSlot.className = 'dtk-ui-editor-foot-right';
  footer.append(leftSlot, rightSlot);
  modal.appendChild(footer);

  const validChip = document.createElement('span');
  validChip.className = 'dtk-ui-validchip';
  validChip.style.display = 'none';
  rightSlot.appendChild(validChip);

  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'dtk-ui-btn primary';
  const saveLabel = isCreate ? 'Create metric' : 'Save changes';
  saveBtn.textContent = saveLabel;
  saveBtn.onclick = (): void => void save();
  rightSlot.appendChild(saveBtn);

  // ---- live validation chip -----------------------------------------------------
  // Debounced, generation-guarded: quick client checks first (no round trip),
  // then the authoritative POST /api/metric-parse on the current draft text.
  // Purely advisory — Save always posts and surfaces its own errors.
  let validateTimer: number | undefined;
  let validateGeneration = 0;

  function setChip(kind: 'ok' | 'warn' | 'err' | 'checking', text: string, fullText?: string): void {
    validChip.className = `dtk-ui-validchip ${kind}`;
    validChip.innerHTML = '<span class="dtk-ui-validchip-dot"></span>';
    validChip.appendChild(document.createTextNode(text));
    validChip.title = fullText ?? text;
    validChip.style.display = '';
  }

  function scheduleValidate(): void {
    if (validateTimer !== undefined) window.clearTimeout(validateTimer);
    validateTimer = window.setTimeout((): void => {
      validateTimer = undefined;
      void runValidate();
    }, 600);
  }

  async function runValidate(): Promise<void> {
    const generation = ++validateGeneration;
    let text: string;
    if (tab === 'builder' && form) {
      const issues = form.clientIssues();
      if (issues.length > 0) {
        setChip('warn', issues[0], issues.join('\n'));
        return;
      }
      text = form.toYaml();
    } else {
      text = textarea.value;
    }
    setChip('checking', 'checking…');
    try {
      await postMetricParse(text);
      if (generation !== validateGeneration) return;
      setChip('ok', '✓ valid config');
    } catch (e) {
      if (generation !== validateGeneration) return;
      const msg = (e as Error).message;
      setChip('err', msg.split('\n')[0], msg);
    }
  }

  // ---- tab switching: the last-edited tab wins, never silently ------------------
  function applyTabVisuals(): void {
    builderTabBtn.classList.toggle('on', tab === 'builder');
    yamlTabBtn.classList.toggle('on', tab === 'yaml');
    if (form) form.el.style.display = tab === 'builder' ? '' : 'none';
    textarea.style.display = tab === 'yaml' ? '' : 'none';
    commentsNote.style.display = tab === 'builder' && sourceHasComments ? '' : 'none';
  }

  let tabSwitchInFlight = false;

  async function setTab(next: EditorTab): Promise<void> {
    // Reentrancy guard: the YAML→Builder branch awaits a parse round trip, and a
    // second click during it would re-enter with stale `tab` state and could
    // seed the form from an outdated response.
    if (next === tab || saving || tabSwitchInFlight) return;
    if (next === 'builder' && !form) return;
    tabSwitchInFlight = true;
    try {
      await doSetTab(next);
    } finally {
      tabSwitchInFlight = false;
    }
  }

  async function doSetTab(next: EditorTab): Promise<void> {
    if (next === 'yaml') {
      // Builder → YAML: re-emit only when the form actually changed, so just
      // looking at the YAML of an untouched metric still shows the on-disk
      // text, comments intact.
      if (formDirtySinceSync && form) {
        textarea.value = form.toYaml();
        formDirtySinceSync = false;
        yamlDirtySinceSync = false;
      }
    } else if (yamlDirtySinceSync && form) {
      // YAML → Builder: the YAML edits must parse before the form can adopt
      // them; on failure stay on the YAML tab with the error visible.
      hideError();
      try {
        const res = await postMetricParse(textarea.value);
        form.setFromData(res.data);
        yamlDirtySinceSync = false;
        formDirtySinceSync = false;
      } catch (e) {
        showError(`Fix the YAML before switching to Builder:\n${(e as Error).message}`);
        return;
      }
    }
    hideError();
    tab = next;
    applyTabVisuals();
    scheduleValidate();
  }

  // ---- delete (edit mode) --------------------------------------------------------
  function buildDeleteButton(): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dtk-ui-btn danger';
    btn.textContent = 'Delete metric…';
    btn.onclick = (): void => showDeleteConfirm();
    return btn;
  }

  if (!isCreate) leftSlot.appendChild(buildDeleteButton());

  function showDeleteConfirm(): void {
    const name = seed.name ?? '';
    const file = seed.file ?? '';
    leftSlot.innerHTML = '';
    const strip = document.createElement('div');
    strip.className = 'dtk-ui-editor-confirm';
    const text = document.createElement('span');
    text.className = 'dtk-ui-editor-confirm-text';
    text.innerHTML =
      `Delete <b>${esc(name)}</b>? The file <code>${esc(file)}</code> is archived to ` +
      `<code>metrics/.history/</code> and removed. Data rows in the <code>_dtk_*</code> ` +
      `tables remain until <code>dtk clean</code>.`;
    strip.appendChild(text);
    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'dtk-ui-btn danger';
    confirmBtn.textContent = 'Delete metric';
    confirmBtn.onclick = (): void => void doDelete(name, confirmBtn, cancelBtn);
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'dtk-ui-btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = (): void => {
      leftSlot.innerHTML = '';
      leftSlot.appendChild(buildDeleteButton());
    };
    strip.append(confirmBtn, cancelBtn);
    leftSlot.appendChild(strip);
  }

  function setSaving(on: boolean): void {
    saving = on;
    saveBtn.disabled = on;
    saveBtn.textContent = on ? 'Saving…' : saveLabel;
  }

  /** The YAML text a save should post: the active tab's representation. */
  function draftText(): string {
    if (tab === 'builder' && form && formDirtySinceSync) return form.toYaml();
    return textarea.value;
  }

  async function save(): Promise<void> {
    if (saving) return;
    hideError();
    if (tab === 'builder' && form) {
      const issues = form.clientIssues();
      if (issues.length > 0) {
        showError(`Fix before saving:\n- ${issues.join('\n- ')}`);
        return;
      }
    }
    setSaving(true);
    try {
      const text = draftText();
      const res = isCreate
        ? await postMetricCreate({ text, folder: folderInput?.value.trim() || undefined })
        : await postMetricUpdate(seed.name ?? '', { text, digest: seed.digest });
      dirty = false;
      cb.onSaved(res, seed.mode);
      close();
    } catch (e) {
      showError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function doDelete(
    name: string,
    confirmBtn: HTMLButtonElement,
    cancelBtn: HTMLButtonElement,
  ): Promise<void> {
    if (saving) return;
    hideError();
    saving = true;
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    confirmBtn.textContent = 'Deleting…';
    try {
      const res = await postMetricDelete(name);
      dirty = false;
      cb.onDeleted(res);
      close();
    } catch (e) {
      showError((e as Error).message);
      confirmBtn.disabled = false;
      cancelBtn.disabled = false;
      confirmBtn.textContent = 'Delete metric';
    } finally {
      saving = false;
    }
  }

  // ---- close handling: Esc / backdrop click / ✕, confirming on unsaved edits --
  function close(): void {
    overlay.close();
    cb.onClose();
  }
  function requestClose(): boolean {
    if (dirty && !window.confirm('Discard unsaved changes?')) return false;
    close();
    return true;
  }

  applyTabVisuals();
  if (tab === 'builder' && form) form.focusFirst();
  else textarea.focus();
  scheduleValidate(); // seed the chip immediately — an invalid open state should show before any edit

  // `close()` is the unconditional teardown (mirrors detail.ts);
  // `requestClose()` is the same confirm-guarded path Esc / backdrop / ✕ use,
  // exposed so the host's navigation (opening another editor / the detail
  // overlay) also can't silently discard unsaved edits.
  return { close, requestClose };
}
