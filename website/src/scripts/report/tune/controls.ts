// ---------------------------------------------------------------------------
// Small DOM helpers
// ---------------------------------------------------------------------------

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

export interface SegSpec {
  label: string;
  value: string;
}

/** A control label carrying an optional tooltip (native title + a faint ⓘ). */
export function ctlLabel(text: string, hint?: string): HTMLElement {
  const lab = el('label', 'dtk-ctl-label', text);
  if (hint) {
    lab.title = hint;
    const q = el('span', 'dtk-ctl-info', 'ⓘ');
    q.title = hint;
    lab.appendChild(document.createTextNode(' '));
    lab.appendChild(q);
  }
  return lab;
}

/** A segmented button group. Returns the row element + a getter/setter. */
export function segControl(
  label: string,
  options: SegSpec[],
  initial: string,
  onChange: (v: string) => void,
  hint?: string,
): { row: HTMLElement; get: () => string; set: (v: string) => void } {
  const row = el('div', 'dtk-ctl');
  row.appendChild(ctlLabel(label, hint));
  const group = el('div', 'dtk-seg');
  let current = initial;
  const buttons: HTMLButtonElement[] = [];
  const paint = (): void => {
    buttons.forEach((b) => b.classList.toggle('on', b.dataset.v === current));
  };
  options.forEach((opt) => {
    const b = el('button', 'dtk-seg-btn', opt.label);
    b.type = 'button';
    b.dataset.v = opt.value;
    b.onclick = (): void => {
      current = opt.value;
      paint();
      onChange(current);
    };
    buttons.push(b);
    group.appendChild(b);
  });
  paint();
  row.appendChild(group);
  return {
    row,
    get: () => current,
    set: (v: string) => {
      current = v;
      paint();
    },
  };
}

/** A labeled range slider with a live value echo. */
export function rangeControl(
  label: string,
  opts: {
    min: number;
    max: number;
    step: number;
    value: number;
    fmt?: (v: number) => string;
    hint?: string;
  },
  onChange: (v: number) => void,
): {
  row: HTMLElement;
  get: () => number;
  set: (v: number) => void;
  setMax: (m: number) => void;
  setMin: (m: number) => void;
} {
  const row = el('div', 'dtk-ctl');
  const head = el('div', 'dtk-ctl-head');
  const lab = ctlLabel(label, opts.hint);
  const out = el('span', 'dtk-ctl-val');
  const fmt = opts.fmt ?? ((v: number): string => String(v));
  head.appendChild(lab);
  head.appendChild(out);
  row.appendChild(head);
  const input = el('input', 'dtk-range');
  input.type = 'range';
  input.min = String(opts.min);
  input.max = String(opts.max);
  input.step = String(opts.step);
  input.value = String(opts.value);
  out.textContent = fmt(opts.value);
  // Live value echo WHILE dragging (cheap), but fire the (expensive) onChange only
  // on `change` — i.e. when the drag is released — so pausing mid-drag with the
  // button still held doesn't kick off a recompute. Keyboard arrows fire both.
  input.oninput = (): void => {
    out.textContent = fmt(Number(input.value));
  };
  input.onchange = (): void => {
    const v = Number(input.value);
    out.textContent = fmt(v);
    onChange(v);
  };
  row.appendChild(input);
  return {
    row,
    get: () => Number(input.value),
    // Programmatic set (e.g. re-seeding from an autotune result). Updates the echo
    // but, like a chart-driven change, does NOT fire onChange — the caller drives
    // the recompute once after re-seeding every control.
    set: (v: number) => {
      input.value = String(v);
      out.textContent = fmt(Number(input.value));
    },
    setMax: (m: number) => {
      input.max = String(m);
      if (Number(input.value) > m) {
        input.value = String(m);
        out.textContent = fmt(m);
      }
    },
    // Raise the slider floor (e.g. IQR's min_samples_per_group floor of 4).
    // Nudges the value up if it now sits below the new min, but — like a
    // chart-driven change — does NOT fire onChange; the caller drives one
    // recompute after re-seeding.
    setMin: (m: number) => {
      input.min = String(m);
      if (Number(input.value) < m) {
        input.value = String(m);
        out.textContent = fmt(m);
      }
    },
  };
}
