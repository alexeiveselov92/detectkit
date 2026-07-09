// Metric editor overlay: create/edit/delete one metric's YAML in place.
//
// Structurally mirrors detail.ts's full-screen overlay (backdrop + modal +
// head + body, Esc/backdrop/✕ close) but hosts a plain <textarea> instead of
// an iframe — the source is edited in the browser and posted back through
// detectkit/ui/metric_files.py's create/update/delete seam (see server.py's
// `_handle_metric_create` / `_handle_metric_update` / `_handle_metric_delete`)
// rather than rendered read-only. Server-side validation errors (pydantic/YAML,
// possibly multi-line) come back as plain-text bodies (api.ts's `readError`
// surfaces them via `Error.message`) and are shown verbatim in a monospace
// error pane — the editor stays open so the user can fix and retry.

import { esc } from './format';
import { postMetricCreate, postMetricDelete, postMetricUpdate } from './api';
import type { MetricMutationResponse } from './payload';

export type EditorMode = 'create' | 'edit';

/** Starter YAML seeded into a new metric's textarea — validates against MetricConfig as-is. */
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
  /** the textarea's initial content — the starter template (create) or the fetched source (edit). */
  text: string;
  /** edit mode only: the source response's optimistic-concurrency token, echoed back on save. */
  digest?: string;
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

/** Open the full-screen metric editor overlay, appended under `root`. */
export function openMetricEditor(
  root: HTMLElement,
  seed: MetricEditorSeed,
  cb: MetricEditorCallbacks,
): MetricEditorHandle {
  const isCreate = seed.mode === 'create';
  let dirty = false;
  let saving = false;

  // ---- chrome: reuse the detail overlay's backdrop/modal, own classes below --
  const backdrop = document.createElement('div');
  backdrop.className = 'dtk-ui-overlay';

  const modal = document.createElement('div');
  modal.className = 'dtk-ui-overlay-modal dtk-ui-editor-modal';
  backdrop.appendChild(modal);

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
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'dtk-ui-overlay-close';
  closeBtn.textContent = '✕';
  closeBtn.title = 'Close (Esc)';
  closeBtn.onclick = (): void => requestClose();
  head.appendChild(closeBtn);
  modal.appendChild(head);

  const body = document.createElement('div');
  body.className = 'dtk-ui-editor-body';
  modal.appendChild(body);

  // ---- folder field (create mode only) ---------------------------------------
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
      'The file is written as metrics/[folder/]<name>.yml — <name> comes from the YAML below.';
    folderField.appendChild(hint);
    body.appendChild(folderField);
  }

  // ---- textarea ---------------------------------------------------------------
  const textarea = document.createElement('textarea');
  textarea.className = 'dtk-ui-editor-textarea';
  textarea.spellcheck = false;
  textarea.autocapitalize = 'off';
  textarea.value = seed.text;
  textarea.addEventListener('input', (): void => {
    dirty = true;
  });
  textarea.addEventListener('keydown', (e: KeyboardEvent): void => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      textarea.value = `${textarea.value.slice(0, start)}  ${textarea.value.slice(end)}`;
      textarea.selectionStart = textarea.selectionEnd = start + 2;
      dirty = true;
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      void save();
    }
  });
  body.appendChild(textarea);

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

  // ---- footer: left = delete (edit mode), right = save -------------------------
  const footer = document.createElement('div');
  footer.className = 'dtk-ui-editor-foot';
  const leftSlot = document.createElement('div');
  leftSlot.className = 'dtk-ui-editor-foot-left';
  const rightSlot = document.createElement('div');
  rightSlot.className = 'dtk-ui-editor-foot-right';
  footer.append(leftSlot, rightSlot);
  modal.appendChild(footer);

  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'dtk-ui-btn primary';
  const saveLabel = isCreate ? 'Create metric' : 'Save changes';
  saveBtn.textContent = saveLabel;
  saveBtn.onclick = (): void => void save();
  rightSlot.appendChild(saveBtn);

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

  async function save(): Promise<void> {
    if (saving) return;
    hideError();
    setSaving(true);
    try {
      const text = textarea.value;
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
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
    cb.onClose();
  }
  function requestClose(): boolean {
    if (dirty && !window.confirm('Discard unsaved changes?')) return false;
    close();
    return true;
  }
  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') requestClose();
  }
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) requestClose();
  });
  document.addEventListener('keydown', onKey);

  root.appendChild(backdrop);
  textarea.focus();

  // `close()` is the unconditional teardown (mirrors detail.ts);
  // `requestClose()` is the same confirm-guarded path Esc / backdrop / ✕ use,
  // exposed so the host's navigation (opening another editor / the detail
  // overlay) also can't silently discard unsaved edits.
  return { close, requestClose };
}
