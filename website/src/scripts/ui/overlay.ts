// Shared full-screen overlay chrome for the cockpit's modals — the detail
// report (detail.ts) and the metric editor (metric-editor.ts) previously each
// hand-built the same backdrop/modal skeleton, Esc + backdrop-click close
// wiring and teardown bookkeeping, and neither trapped focus (Tab could walk
// onto the covered page's buttons and Enter would fire them blind). One
// primitive fixes all of that once for every overlay.

export interface OverlayOptions {
  /** Extra class on the modal (e.g. 'dtk-ui-editor-modal'). */
  modalClass?: string;
  /**
   * Invoked on the user's close gestures (Esc / backdrop click). The host
   * decides whether to actually close — a dirty editor may prompt and keep
   * the overlay open — by calling (or not calling) the handle's `close()`.
   */
  onRequestClose(): void;
}

export interface OverlayHandle {
  backdrop: HTMLElement;
  modal: HTMLElement;
  /** Unconditional teardown: listeners + DOM removed, prior focus restored. Idempotent. */
  close(): void;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), ' +
  'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Open the shared overlay skeleton (backdrop + modal) appended under `root`. */
export function openOverlay(root: HTMLElement, opts: OverlayOptions): OverlayHandle {
  const backdrop = document.createElement('div');
  backdrop.className = 'dtk-ui-overlay';
  const modal = document.createElement('div');
  modal.className = 'dtk-ui-overlay-modal' + (opts.modalClass ? ` ${opts.modalClass}` : '');
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  backdrop.appendChild(modal);

  const previouslyFocused =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;

  function trapTab(e: KeyboardEvent): void {
    // Keep keyboard focus cycling inside the modal — without this, Tab
    // escapes to the covered page and Enter can fire a hidden button.
    const focusables = Array.from(modal.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null,
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    const inside = active instanceof HTMLElement && modal.contains(active);
    if (e.shiftKey && (!inside || active === first)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (!inside || active === last)) {
      e.preventDefault();
      first.focus();
    }
  }

  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
      opts.onRequestClose();
    } else if (e.key === 'Tab') {
      trapTab(e);
    }
  }

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) opts.onRequestClose();
  });
  document.addEventListener('keydown', onKey);
  root.appendChild(backdrop);

  let closed = false;
  function close(): void {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey);
    backdrop.remove();
    previouslyFocused?.focus();
  }

  return { backdrop, modal, close };
}
