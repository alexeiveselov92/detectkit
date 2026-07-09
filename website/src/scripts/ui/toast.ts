// Bottom-right toast stack — error/info variants, auto-dismiss after 5s.

export type ToastKind = 'error' | 'info';

let container: HTMLElement | null = null;

function ensureContainer(root: HTMLElement): HTMLElement {
  if (container && container.isConnected) return container;
  container = document.createElement('div');
  container.className = 'dtk-toasts';
  root.appendChild(container);
  return container;
}

/** Show a toast anchored to `root` (the page root, so it survives re-renders of other sections). */
export function toast(root: HTMLElement, kind: ToastKind, message: string): void {
  const wrap = ensureContainer(root);
  const el = document.createElement('div');
  el.className = `dtk-toast dtk-toast-${kind}`;
  el.textContent = message;
  wrap.appendChild(el);
  window.setTimeout(() => {
    el.classList.add('dtk-toast-out');
    window.setTimeout(() => el.remove(), 220);
  }, 5000);
}
