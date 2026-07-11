// Detail overlay: a full-screen modal (shared chrome from overlay.ts) wrapping
// the existing per-metric HTML report in an <iframe
// src="/metric/<name>?token=&window=">. ESC or a backdrop click closes it; the
// window preset can be swapped in place (the header's window control stays
// live while the overlay is open) without tearing the modal down.
//
// The header also carries the "Clean stale" action: preview (exact counts from
// GET /api/clean-preview) → an amber confirm strip between the head and the
// report → the real `dtk clean --select <metric> --execute` as a pipeline job
// → the report iframe reloads so only the current config's series remain.

import { esc } from './format';
import { metricUrl } from './api';
import { openOverlay } from './overlay';
import type { CleanPreviewResponse } from './payload';

export interface DetailHandle {
  /** Point the iframe at a new window preset without closing the overlay. */
  setWindow(windowPreset: string): void;
  /** Re-fetch the report iframe in place (e.g. after a clean pruned rows). */
  reload(): void;
  close(): void;
}

export interface DetailCallbacks {
  onTune(name: string): void;
  onClose(): void;
  /**
   * What a clean would delete, for the confirm strip. Resolves `null` when
   * there is nothing to show (nothing stale / pipeline busy / fetch error —
   * the callback owns toasting those).
   */
  onCleanPreview(name: string): Promise<CleanPreviewResponse | null>;
  /** Spawn the clean job and resolve once it finishes; `true` = success. */
  onCleanExecute(name: string): Promise<boolean>;
}

/** Open the full-screen metric detail overlay, appended under `root`. */
export function openDetailOverlay(
  root: HTMLElement,
  metric: string,
  windowPreset: string,
  cb: DetailCallbacks,
): DetailHandle {
  const overlay = openOverlay(root, { onRequestClose: (): void => close() });
  const { modal } = overlay;
  let currentWindow = windowPreset;

  const head = document.createElement('div');
  head.className = 'dtk-ui-overlay-head';
  head.innerHTML =
    `<span><span class="dtk-ui-overlay-title">${esc(metric)}</span>` +
    `<span class="dtk-ui-overlay-sub">window: ${esc(windowPreset)}</span></span>`;
  const actions = document.createElement('div');
  actions.className = 'dtk-ui-overlay-actions';
  const cleanBtn = document.createElement('button');
  cleanBtn.type = 'button';
  cleanBtn.className = 'dtk-ui-btn';
  cleanBtn.textContent = 'Clean stale';
  cleanBtn.title =
    'Remove stored detections/alert state from superseded detector configs (dtk clean)';
  const tuneBtn = document.createElement('button');
  tuneBtn.type = 'button';
  tuneBtn.className = 'dtk-ui-btn';
  tuneBtn.textContent = 'Tune';
  tuneBtn.onclick = (): void => cb.onTune(metric);
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'dtk-ui-overlay-close';
  closeBtn.textContent = '✕';
  closeBtn.title = 'Close (Esc)';
  actions.append(cleanBtn, tuneBtn, closeBtn);
  head.appendChild(actions);
  modal.appendChild(head);

  const body = document.createElement('div');
  body.className = 'dtk-ui-overlay-body';

  // The report is built server-side on demand — the iframe stays hidden (and
  // a visible loading state fills the dark body) until its document lands,
  // instead of a blank white pane that reads as "nothing is happening".
  const loading = document.createElement('div');
  loading.className = 'dtk-ui-overlay-loading';
  loading.innerHTML =
    `<span class="dtk-ui-overlay-spinner"></span>` +
    `<span>Building the report for <b>${esc(metric)}</b>…</span>`;
  body.appendChild(loading);

  const iframe = document.createElement('iframe');
  iframe.title = `detectkit report — ${metric}`;
  iframe.style.visibility = 'hidden';
  iframe.addEventListener('load', () => {
    loading.style.display = 'none';
    iframe.style.visibility = 'visible';
  });
  iframe.src = metricUrl(metric, windowPreset);
  body.appendChild(iframe);
  modal.appendChild(body);

  function reloadReport(): void {
    loading.style.display = '';
    iframe.style.visibility = 'hidden';
    iframe.src = metricUrl(metric, currentWindow);
  }

  // ---- clean-stale confirm strip -------------------------------------------
  let strip: HTMLElement | null = null;
  function removeStrip(): void {
    strip?.remove();
    strip = null;
  }

  function showStrip(p: CleanPreviewResponse): void {
    removeStrip();
    strip = document.createElement('div');
    strip.className = 'dtk-ui-cleanstrip';

    const parts: string[] = [];
    if (p.stale_detectors.length > 0) {
      const rows = p.stale_detectors.reduce((acc, d) => acc + d.rows, 0);
      parts.push(
        `<b>${p.stale_detectors.length}</b> superseded detector generation(s) — ` +
          `<b>${rows.toLocaleString()}</b> detection row(s)`,
      );
    }
    if (p.stale_alert_states.length > 0) {
      parts.push(`<b>${p.stale_alert_states.length}</b> stale alert state(s)`);
    }
    const warn = p.warnings.length
      ? `<div class="dtk-ui-cleanstrip-warn">${p.warnings.map(esc).join(' · ')}</div>`
      : '';
    const text = document.createElement('div');
    text.className = 'dtk-ui-cleanstrip-text';
    text.innerHTML =
      `Permanently delete ${parts.join(' and ')}? ` +
      `The report will then show only the current config's detectors.${warn}`;

    const stripActions = document.createElement('div');
    stripActions.className = 'dtk-ui-cleanstrip-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'dtk-ui-btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = (): void => removeStrip();
    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.className = 'dtk-ui-btn danger';
    confirmBtn.textContent = 'Delete stale data';
    confirmBtn.onclick = async (): Promise<void> => {
      confirmBtn.disabled = true;
      cancelBtn.disabled = true;
      confirmBtn.textContent = 'Cleaning…';
      // The job (and its completion handling) outlive this overlay: the host's
      // onCleanExecute drives the report reload through the LIVE detail handle
      // (see ui.ts), so a user who closes and re-opens this metric mid-clean
      // still gets the fresh report. Here we only tidy our own strip, and only
      // if this overlay is still the attached one.
      await cb.onCleanExecute(metric);
      if (modal.isConnected) removeStrip();
    };
    stripActions.append(cancelBtn, confirmBtn);
    strip.append(text, stripActions);
    modal.insertBefore(strip, body);
  }

  cleanBtn.onclick = async (): Promise<void> => {
    if (strip) {
      removeStrip(); // a re-click toggles an open confirm away
      return;
    }
    cleanBtn.disabled = true;
    cleanBtn.textContent = 'Checking…';
    const preview = await cb.onCleanPreview(metric);
    cleanBtn.disabled = false;
    cleanBtn.textContent = 'Clean stale';
    if (preview) showStrip(preview);
  };

  function close(): void {
    overlay.close();
    cb.onClose();
  }
  closeBtn.onclick = close;

  return {
    setWindow(w: string): void {
      currentWindow = w;
      const sub = head.querySelector('.dtk-ui-overlay-sub');
      if (sub) sub.textContent = `window: ${w}`;
      loading.style.display = '';
      iframe.style.visibility = 'hidden';
      iframe.src = metricUrl(metric, w);
    },
    reload: reloadReport,
    close,
  };
}
