---
name: dtk-feedback
description: >-
  Report a detectkit bug, request a feature, or send feedback to the maintainers
  as a GitHub issue on the upstream repo (alexeiveselov92/detectkit). Use when a
  dtk command errors or behaves unexpectedly and it looks like a detectkit defect
  (not the user's config), when the user wishes detectkit did something it
  doesn't, or when they ask to report/file an issue, send feedback, or contact
  the maintainers. Auto-collects diagnostic context, redacts all secrets, and
  never submits without explicit confirmation.
---

# Send feedback to the detectkit maintainers

Turn a problem, a wish, or a comment into a clear GitHub issue on the upstream
repo **`alexeiveselov92/detectkit`** — carrying the diagnostic context
maintainers need and **leaking no secrets**. You are filing a *public* issue on
the user's behalf: never submit anything without showing the exact text and
getting an explicit "yes".

This skill is the procedure; the reference for ruling out config problems lives
under `.claude/rules/detectkit/`.

## Step 0 — Decide whether this belongs upstream

- **Bug** — a `dtk` command errors or produces clearly wrong output, **and**
  you've ruled out a local config/usage mistake (Step 1).
- **Feature request** — the user needs detectkit to do something it doesn't.
- **Feedback / question** — a comment, confusion, or rough edge worth surfacing.

Do **not** open an issue for the user's own SQL, data, database, or
configuration mistakes — those are fixed locally with the rules files, not
reported as detectkit bugs. Only genuine detectkit behavior goes upstream.

## Step 1 — Rule out config first (for "it doesn't work")

Before calling something a bug, confirm it isn't a configuration or usage
problem. Read the matching `.claude/rules/detectkit/` file and check the usual
gotchas:

- the loading query filters on `{{ dtk_start_time }}` **and** `{{ dtk_end_time }}`;
- metric `name` is unique across the project;
- `profiles.yml` has the right location fields (`internal_database`/`data_database`,
  or Postgres schemas) and a `default_profile` that exists;
- `alert_cooldown` is set; channels referenced by metrics exist.

If a local fix exists, **do that and stop** — don't file an issue. Escalate only
what is genuinely a detectkit defect.

## Step 2 — Gather context (do this for the user, don't make them dig)

Collect automatically:

- `dtk --version` — the detectkit version (**always** include it).
- Python version (`python3 --version`) and OS.
- The database backend **type only** (`clickhouse` / `postgres` / `mysql`) from
  `profiles.yml`'s `type:` — never the host, port, or credentials.

For a **bug**, also gather:

- the exact command that was run;
- the full error message / traceback;
- what the user expected vs. what happened;
- a **minimal reproduction** — the failing metric YAML and/or SQL, with every
  secret stripped (Step 3).

## Step 3 — Redact secrets (mandatory — before anything is shown or sent)

This is a public issue. Strip from every snippet you include:

- passwords, tokens, `bot_token`, `smtp_password`, API keys;
- `webhook_url`s, `chat_id`s, email addresses;
- hostnames, IPs, ports, and real database / schema / table names;
- the resolved value of anything inside `{{ env_var('…') }}` or `${…}` — keep the
  `env_var(...)` shape, drop the value.

Replace with placeholders like `<redacted>`, `<your-host>`, `<your_table>` while
keeping the structure intact so the bug is still reproducible. **If you're not
sure whether something is sensitive, redact it.**

## Step 4 — Search for duplicates

```bash
gh issue list --repo alexeiveselov92/detectkit --search "<keywords>" --state all
```

If a matching issue already exists, offer to **add a comment** or a 👍 reaction
instead of opening a new one:

```bash
gh issue comment <number> --repo alexeiveselov92/detectkit --body "<note>"
```

This gives maintainers signal on frequency instead of a pile of duplicates.

## Step 5 — Draft the issue

Write a specific title (the actual symptom in a few words, not "bug"). Pick the
body template by type:

- **Bug** — `Summary` / `Environment` (detectkit version, Python, OS, backend) /
  `Steps to reproduce` / `Expected` / `Actual` (with the traceback in a fenced
  code block) / `Minimal config` (redacted).
- **Feature request** — `Problem` (the underlying need, not just the proposed
  fix) / `Proposed behavior` / `Alternatives considered`.
- **Feedback** — free-form, concrete and respectful.

End the body with an attribution marker so maintainers can see it came through
the assistant funnel and on which version:

```
_Filed via the dtk init-claude assistant (detectkit <version>)._
```

## Step 6 — Preview and confirm (no silent submits)

Show the user the **full** title and body exactly as they will be posted, and
the target repo. Ask them to confirm: secrets redacted? right repo? Proceed to
Step 7 only on an explicit "yes". If they want edits, revise and re-preview.

## Step 7 — Submit

**Preferred — `gh` CLI** (check it's installed and authenticated first with
`gh auth status`). Write the body to a temp file to avoid shell-escaping the
markdown/traceback:

```bash
gh issue create --repo alexeiveselov92/detectkit \
  --title "<title>" --body-file <tmpfile>
```

Tag the issue so maintainers can triage assistant-filed reports: add the type
label (`--label bug` / `--label enhancement`) **and** `--label "via:assistant"`.
Labels must already exist on the repo, so if `gh` reports an unknown label,
**retry without the failing label(s)** — never fail the report over a missing
label. (Attribution also lives in the Step 5 body marker, so maintainers can
filter with `in:body "Filed via the dtk init-claude assistant"` even before the
`via:assistant` label exists.) Return the issue URL to the user.

**Fallback — no `gh`, or not authenticated.** Build a prefilled "new issue" URL
and hand it to the user to open and submit in their browser:

```
https://github.com/alexeiveselov92/detectkit/issues/new?title=<url-encoded>&body=<url-encoded>
```

URL-encode both fields. If the body is too long for a URL, give the user the
title plus the body text to paste, and the plain link
`https://github.com/alexeiveselov92/detectkit/issues/new`.

## Step 8 — Close the loop

Give the user the issue URL (or the prefilled link), mention they can subscribe
for updates, and — if you also worked around the bug locally — restate that
local fix so they're unblocked right now, not just waiting on the issue.
