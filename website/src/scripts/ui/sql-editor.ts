// A minimal SQL syntax-highlighting text editor for the metric Builder's
// query pane — a classic "invisible textarea over a highlighted <pre>"
// overlay (no contenteditable, no external editor library — the bundle has
// zero npm runtime deps): the real edit surface is a transparent-text
// `<textarea>` stacked over a `<pre><code>` that renders the same text through
// a hand-rolled tokenizer. Every token's text is HTML-escaped before it is
// ever placed in `innerHTML` (never the raw input) — see `buildHighlightedHtml`.

import { esc } from './format';

export interface SqlEditorHandle {
  el: HTMLElement;
  getValue(): string;
  setValue(v: string): void;
  /** Grey out (native `disabled`) and show/hide an overlay note (the `query_file` case). */
  setDisabled(disabled: boolean, note?: string): void;
  focus(): void;
}

export interface SqlEditorOptions {
  value: string;
  onInput(v: string): void;
  ariaLabel?: string;
}

// Case-insensitive standard-SQL keyword set. Deliberately plain SQL — no
// ClickHouse-specific function names (those fall through to `dtk-sql-fn` via
// the word-followed-by-`(` rule instead of a maintained dialect keyword list).
const KEYWORDS = new Set(
  (
    'SELECT FROM WHERE GROUP BY ORDER HAVING JOIN LEFT RIGHT INNER OUTER FULL CROSS ON AS AND OR ' +
    'NOT IN IS BETWEEN LIKE CASE WHEN THEN ELSE END LIMIT OFFSET WITH UNION ALL DISTINCT INTERVAL ' +
    'SECOND MINUTE HOUR DAY CAST NULL TRUE FALSE INSERT UPDATE DELETE SET VALUES OVER PARTITION ' +
    'DESC ASC'
  ).split(/\s+/),
);

// Jinja placeholders are resolved in their own pass and then spliced back
// into the SQL tokenization (see `tokenize`) rather than folded into one
// combined alternation. A metric's real SQL routinely quotes a placeholder,
// e.g. `WHERE event_time >= '{{ dtk_start_time }}'` (the exact shape
// metric-editor.ts's own NEW_METRIC_TEMPLATE uses) — a single left-to-right
// scan would hit the opening `'` first and greedily swallow the whole
// `'{{ … }}'` as one string token, hiding the jinja span entirely. Instead,
// jinja spans are masked out with same-length filler before the SQL
// tokenizer runs (so a surrounding string/comment still closes exactly where
// it would around the real jinja text), then the real jinja text is spliced
// back into whichever resulting token(s) covered that span — carrying over
// that token's class (e.g. the bordering quote characters stay `dtk-sql-str`)
// for the real text immediately before/after the placeholder.
const JINJA_RE = /\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}/g;

// Ordered alternation — first match wins at a given position, so priority is
// comment > string > number > word; anything else falls through as untouched
// (still escaped) plain text between matches.
const SQL_TOKEN_RE =
  /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:''|[^'])*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)/g;

interface Token {
  text: string;
  cls: string | null;
}

interface Range {
  start: number;
  end: number;
  cls: string | null;
}

/** Partition `masked` into contiguous [start,end) ranges covering every character, classified. */
function scanSqlRanges(masked: string): Range[] {
  const ranges: Range[] = [];
  let lastIndex = 0;
  SQL_TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = SQL_TOKEN_RE.exec(masked))) {
    if (m.index > lastIndex) ranges.push({ start: lastIndex, end: m.index, cls: null });
    const start = m.index;
    const end = SQL_TOKEN_RE.lastIndex;
    if (m[1] !== undefined) {
      ranges.push({ start, end, cls: 'dtk-sql-cmt' });
    } else if (m[2] !== undefined) {
      ranges.push({ start, end, cls: 'dtk-sql-str' });
    } else if (m[3] !== undefined) {
      ranges.push({ start, end, cls: 'dtk-sql-num' });
    } else if (m[4] !== undefined) {
      const word = m[4];
      let cls: string | null;
      if (KEYWORDS.has(word.toUpperCase())) cls = 'dtk-sql-kw';
      else if (/^\s*\(/.test(masked.slice(end))) cls = 'dtk-sql-fn';
      else cls = null;
      ranges.push({ start, end, cls });
    }
    lastIndex = end;
  }
  if (lastIndex < masked.length) ranges.push({ start: lastIndex, end: masked.length, cls: null });
  return ranges;
}

function tokenize(sql: string): Token[] {
  const spans: Array<{ start: number; end: number; text: string }> = [];
  JINJA_RE.lastIndex = 0;
  let jm: RegExpExecArray | null;
  while ((jm = JINJA_RE.exec(sql))) {
    spans.push({ start: jm.index, end: JINJA_RE.lastIndex, text: jm[0] });
  }
  if (spans.length === 0) {
    return scanSqlRanges(sql).map((r) => ({ text: sql.slice(r.start, r.end), cls: r.cls }));
  }

  // Mask every jinja span with same-length filler (a plain identifier char —
  // never a quote/comment delimiter/digit, so it can't spuriously open or
  // close a string/comment) before tokenizing, so the ranges around it come
  // out exactly as they would around the real jinja text.
  let masked = sql;
  for (const s of spans) masked = masked.slice(0, s.start) + '_'.repeat(s.end - s.start) + masked.slice(s.end);
  const ranges = scanSqlRanges(masked);

  const tokens: Token[] = [];
  let spanIdx = 0;
  for (const r of ranges) {
    let cursor = r.start;
    while (spanIdx < spans.length && spans[spanIdx].start < r.end) {
      const s = spans[spanIdx];
      if (s.start > cursor) tokens.push({ text: sql.slice(cursor, s.start), cls: r.cls });
      tokens.push({ text: s.text, cls: 'dtk-sql-jinja' });
      cursor = s.end;
      spanIdx++;
    }
    if (cursor < r.end) tokens.push({ text: sql.slice(cursor, r.end), cls: r.cls });
  }
  return tokens;
}

/** Build the `<code>` innerHTML for `sql` — every token is escaped, never raw. */
function buildHighlightedHtml(sql: string): string {
  const html = tokenize(sql)
    .map((t) => (t.cls ? `<span class="${t.cls}">${esc(t.text)}</span>` : esc(t.text)))
    .join('');
  // Trailing-newline quirk: a `<pre>` visually collapses a final empty line
  // that a `<textarea>` still reserves room for, which would desync the two
  // layers' heights/scroll range. Appending a sentinel newline keeps them
  // matched regardless of whether `sql` itself ends with one.
  return html + '\n';
}

/** Build the query editor. `opts.onInput` fires on every user edit (typing, Tab-insert). */
export function createSqlEditor(opts: SqlEditorOptions): SqlEditorHandle {
  const el = document.createElement('div');
  el.className = 'dtk-ui-sqled';

  const pre = document.createElement('pre');
  pre.className = 'dtk-ui-sqled-hl';
  pre.setAttribute('aria-hidden', 'true');
  const code = document.createElement('code');
  pre.appendChild(code);

  const textarea = document.createElement('textarea');
  textarea.className = 'dtk-ui-sqled-ta';
  textarea.spellcheck = false;
  textarea.autocapitalize = 'off';
  if (opts.ariaLabel) textarea.setAttribute('aria-label', opts.ariaLabel);

  el.append(pre, textarea);

  function renderHighlight(v: string): void {
    code.innerHTML = buildHighlightedHtml(v);
  }

  function syncScroll(): void {
    pre.scrollTop = textarea.scrollTop;
    pre.scrollLeft = textarea.scrollLeft;
  }

  textarea.value = opts.value;
  renderHighlight(opts.value);

  textarea.addEventListener('input', (): void => {
    renderHighlight(textarea.value);
    syncScroll();
    opts.onInput(textarea.value);
  });
  textarea.addEventListener('scroll', syncScroll);
  textarea.addEventListener('keydown', (e: KeyboardEvent): void => {
    // Ctrl/Cmd+S is deliberately left alone here — it must bubble up to the
    // editor shell's own save shortcut, not get swallowed by this pane.
    if (e.key !== 'Tab') return;
    e.preventDefault();
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const v = textarea.value;
    textarea.value = `${v.slice(0, start)}  ${v.slice(end)}`;
    textarea.selectionStart = textarea.selectionEnd = start + 2;
    renderHighlight(textarea.value);
    syncScroll();
    opts.onInput(textarea.value);
  });

  let noteEl: HTMLElement | null = null;

  return {
    el,
    getValue: (): string => textarea.value,
    setValue: (v: string): void => {
      textarea.value = v;
      renderHighlight(v);
      syncScroll();
    },
    setDisabled: (disabled: boolean, note?: string): void => {
      textarea.disabled = disabled;
      if (disabled && note) {
        if (!noteEl) {
          noteEl = document.createElement('div');
          noteEl.className = 'dtk-ui-sqled-note';
          el.appendChild(noteEl);
        }
        noteEl.textContent = note;
        noteEl.hidden = false;
      } else if (noteEl) {
        noteEl.hidden = true;
      }
    },
    focus: (): void => textarea.focus(),
  };
}
