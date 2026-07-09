// Detail overlay: a full-screen modal (shared chrome from overlay.ts) wrapping
// the existing per-metric HTML report in an <iframe
// src="/metric/<name>?token=&window=">. ESC or a backdrop click closes it; the
// window preset can be swapped in place (the header's window control stays
// live while the overlay is open) without tearing the modal down.

import { esc } from './format';
import { metricUrl } from './api';
import { openOverlay } from './overlay';

export interface DetailHandle {
  /** Point the iframe at a new window preset without closing the overlay. */
  setWindow(windowPreset: string): void;
  close(): void;
}

export interface DetailCallbacks {
  onTune(name: string): void;
  onClose(): void;
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

  const head = document.createElement('div');
  head.className = 'dtk-ui-overlay-head';
  head.innerHTML =
    `<span><span class="dtk-ui-overlay-title">${esc(metric)}</span>` +
    `<span class="dtk-ui-overlay-sub">window: ${esc(windowPreset)}</span></span>`;
  const actions = document.createElement('div');
  actions.className = 'dtk-ui-overlay-actions';
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
  actions.append(tuneBtn, closeBtn);
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

  function close(): void {
    overlay.close();
    cb.onClose();
  }
  closeBtn.onclick = close;

  return {
    setWindow(w: string): void {
      const sub = head.querySelector('.dtk-ui-overlay-sub');
      if (sub) sub.textContent = `window: ${w}`;
      loading.style.display = '';
      iframe.style.visibility = 'hidden';
      iframe.src = metricUrl(metric, w);
    },
    close,
  };
}
