// Detail overlay: a fixed full-screen modal wrapping the existing per-metric
// HTML report in an <iframe src="/metric/<name>?token=&window=">. ESC or a
// backdrop click closes it; the window preset can be swapped in place (the
// header's window control stays live while the overlay is open) without
// tearing the modal down.

import { esc } from './format';
import { metricUrl } from './api';

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
  const backdrop = document.createElement('div');
  backdrop.className = 'dtk-ui-overlay';

  const modal = document.createElement('div');
  modal.className = 'dtk-ui-overlay-modal';
  backdrop.appendChild(modal);

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
  const iframe = document.createElement('iframe');
  iframe.src = metricUrl(metric, windowPreset);
  iframe.title = `detectkit report — ${metric}`;
  body.appendChild(iframe);
  modal.appendChild(body);

  root.appendChild(backdrop);

  function close(): void {
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
    cb.onClose();
  }
  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') close();
  }
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) close();
  });
  closeBtn.onclick = close;
  document.addEventListener('keydown', onKey);

  return {
    setWindow(w: string): void {
      const sub = head.querySelector('.dtk-ui-overlay-sub');
      if (sub) sub.textContent = `window: ${w}`;
      iframe.src = metricUrl(metric, w);
    },
    close,
  };
}
