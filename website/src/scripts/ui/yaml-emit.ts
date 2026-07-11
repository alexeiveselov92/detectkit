// Minimal, correctness-first YAML emitter for JSON-ish objects (maps / arrays /
// scalars only) — used by the metric Builder form's `toYaml()` to turn the
// structured form state back into a metric config file. There is no YAML
// library in the frontend bundle (esbuild ships with zero npm runtime deps),
// so this hand-rolls just enough of the block/flow scalar grammar to be
// **provably** round-trip-safe through Python's `yaml.safe_load` — the server
// (`detectkit/ui/metric_files.py`) validates every save with a real parser
// anyway, so a slightly-too-cautious quote here is harmless; a wrong unquoted
// emission would silently corrupt a metric. Prefer `JSON.stringify`'s
// double-quoted form (a strict subset of YAML's double-quoted scalar escapes)
// whenever a plain or block-scalar form isn't unambiguously safe.

/** Reserved scalars that read as non-string types in YAML 1.1 — must be quoted to stay a string. */
const RESERVED_WORDS = /^(true|false|null|yes|no|on|off|~)$/i;
/** Conservative "looks like a bare identifier" shape — see `isPlainSafeString`. */
const PLAIN_SAFE = /^[A-Za-z0-9_][A-Za-z0-9_.\-]*$/;
/** A leading digit/sign/dot risks being read back as a number ("1h", "2024-01-01 …"). */
const LOOKS_NUMERIC_START = /^[-+.]?\d/;

/** Whether `s` can render unquoted as a YAML plain scalar without changing its type on parse. */
function isPlainSafeString(s: string): boolean {
  if (!PLAIN_SAFE.test(s)) return false;
  if (RESERVED_WORDS.test(s)) return false;
  if (!Number.isNaN(Number(s))) return false;
  if (LOOKS_NUMERIC_START.test(s)) return false;
  return true;
}

/** JSON's double-quoted string escaping is a valid YAML double-quoted scalar — always exact. */
function quoteString(s: string): string {
  return JSON.stringify(s);
}

/**
 * Whether a multiline string can render as a `|`/`|-` block scalar without
 * indentation/chomping ambiguity. Two guards:
 *  - the first line must have content and no leading whitespace of its own
 *    (otherwise YAML's auto-detected block indentation swallows that
 *    whitespace as structural, misaligning every other line);
 *  - no line anywhere may be blank/whitespace-only — YAML's clip/strip
 *    chomping treats a whitespace-only line as "blank" for trimming
 *    purposes, which can silently drop trailing spaces a blank-looking line
 *    actually carries as content. Falling back to a quoted one-liner sidesteps
 *    the whole class of block-scalar edge cases rather than reproducing them.
 */
function isBlockScalarSafe(s: string): boolean {
  const endsWithNewline = s.endsWith('\n');
  const body = endsWithNewline ? s.slice(0, -1) : s;
  const lines = body.split('\n');
  const first = lines[0] ?? '';
  if (first.length === 0 || /^\s/.test(first)) return false;
  if (lines.some((l) => l.trim().length === 0)) return false;
  return true;
}

/** Render a (block-scalar-safe) multiline string's `|`/`|-` indicator + indented body lines. */
function blockScalarBody(s: string, indent: string): { indicator: string; lines: string[] } {
  const endsWithNewline = s.endsWith('\n');
  const body = endsWithNewline ? s.slice(0, -1) : s;
  const lines = body.split('\n').map((l) => indent + l);
  return { indicator: endsWithNewline ? '|' : '|-', lines };
}

/** Single-line scalar rendering: strings/numbers/booleans (null and multiline strings handled by callers). */
function emitScalar(value: unknown): string {
  if (typeof value === 'string') {
    return isPlainSafeString(value) ? value : quoteString(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return quoteString(String(value));
    const s = String(value);
    // PyYAML's float resolver demands a '.' in the mantissa: a bare "5e-7"
    // parses as a *string*, silently changing the value's type server-side.
    // JS always signs the exponent (5e-7, 1e+21), so only the dot can be missing.
    const e = s.indexOf('e');
    if (e > 0 && !s.slice(0, e).includes('.')) {
      return `${s.slice(0, e)}.0${s.slice(e)}`;
    }
    return s;
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false';
  }
  if (value === null) return 'null';
  return quoteString(String(value)); // shouldn't happen for JSON-ish input
}

/** Map/array keys follow the same plain-vs-quoted rule as string values. */
function emitKey(key: string): string {
  return isPlainSafeString(key) ? key : quoteString(key);
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function withoutUndefined(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) if (v !== undefined) out[k] = v;
  return out;
}

/** Emit one multiline-string field's `key: |`/`key: |-` header + indented body, or its quoted fallback. */
function emitMultilineString(keyPrefix: string, value: string, childIndent: string): string[] {
  if (isBlockScalarSafe(value)) {
    const { indicator, lines } = blockScalarBody(value, childIndent);
    return [`${keyPrefix}${indicator}`, ...lines];
  }
  return [`${keyPrefix}${quoteString(value)}`];
}

function emitMapEntries(obj: Record<string, unknown>, indent: string): string[] {
  const lines: string[] = [];
  const childIndent = indent + '  ';
  for (const [key, value] of Object.entries(obj)) {
    if (value === undefined) continue;
    const keyStr = emitKey(key);
    if (value === null) {
      lines.push(`${indent}${keyStr}: null`);
    } else if (Array.isArray(value)) {
      if (value.length === 0) {
        lines.push(`${indent}${keyStr}: []`);
      } else {
        lines.push(`${indent}${keyStr}:`);
        lines.push(...emitArrayItems(value, childIndent));
      }
    } else if (isPlainObject(value)) {
      const filtered = withoutUndefined(value);
      if (Object.keys(filtered).length === 0) {
        lines.push(`${indent}${keyStr}: {}`);
      } else {
        lines.push(`${indent}${keyStr}:`);
        lines.push(...emitMapEntries(filtered, childIndent));
      }
    } else if (typeof value === 'string' && value.includes('\n')) {
      lines.push(...emitMultilineString(`${indent}${keyStr}: `, value, childIndent));
    } else {
      lines.push(`${indent}${keyStr}: ${emitScalar(value)}`);
    }
  }
  return lines;
}

function emitArrayItems(arr: unknown[], indent: string): string[] {
  const lines: string[] = [];
  const childIndent = indent + '  ';
  for (const item of arr) {
    if (item === null) {
      lines.push(`${indent}- null`);
    } else if (Array.isArray(item)) {
      if (item.length === 0) {
        lines.push(`${indent}- []`);
      } else {
        lines.push(`${indent}-`);
        lines.push(...emitArrayItems(item, childIndent));
      }
    } else if (isPlainObject(item)) {
      const filtered = withoutUndefined(item);
      if (Object.keys(filtered).length === 0) {
        lines.push(`${indent}- {}`);
      } else {
        // First key rides on the "- " line; continuation keys align two
        // spaces in (standard 2-space indent), i.e. under the first key.
        const subLines = emitMapEntries(filtered, childIndent);
        lines.push(`${indent}- ${subLines[0].slice(childIndent.length)}`);
        lines.push(...subLines.slice(1));
      }
    } else if (typeof item === 'string' && item.includes('\n')) {
      lines.push(...emitMultilineString(`${indent}- `, item, childIndent));
    } else {
      lines.push(`${indent}- ${emitScalar(item)}`);
    }
  }
  return lines;
}

/**
 * Emit a YAML document from a JSON-ish object (maps/arrays/scalars only).
 * `headerComments` (if given) are emitted first, one `# `-prefixed line each.
 * Map keys keep insertion order; `undefined` values are skipped entirely
 * (the caller's way to omit a field); `null` renders as the YAML `null`.
 */
export function emitYamlDoc(obj: Record<string, unknown>, headerComments?: string[]): string {
  const out: string[] = [];
  if (headerComments) {
    // Split embedded newlines so every physical line keeps the `# ` prefix — a
    // comment built from untrusted text (an OSI metric name, say) must never
    // break out of the comment context and inject top-level YAML keys.
    for (const c of headerComments) {
      for (const line of c.split('\n')) out.push(`# ${line}`);
    }
  }
  const filtered = withoutUndefined(obj);
  if (Object.keys(filtered).length === 0) {
    out.push('{}');
  } else {
    out.push(...emitMapEntries(filtered, ''));
  }
  return out.join('\n') + '\n';
}
