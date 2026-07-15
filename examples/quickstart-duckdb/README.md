# Quickstart — a caught anomaly on one local DuckDB file

The self-contained project behind the landing quickstart. No server, no
account, no credentials: DuckDB runs in-process, and the one metric
**synthesizes its own series in SQL** (a smooth wave with one injected dip),
so `dtk run` has data to detect on a fresh machine.

```bash
pip install "detectkit[duckdb]"
cd examples/quickstart-duckdb
dtk run --select signups --report
# → reports/signups.html — open it: the dip, the expected band, and the
#   alerts it fires, fully offline.
```

`--report` **replays** the fired alerts into a self-contained HTML file — no
channel is contacted, so this runs with zero credentials. To receive the
notification on a live run, the metric already references an `ntfy` channel
(`detectkit_project.yml`): pick your own public topic and subscribe at
`https://ntfy.sh/<topic>` (or the ntfy app) — ntfy needs no token. Any other
channel (Slack/Mattermost `webhook_url`, Telegram, …) works too.

Swap the DuckDB profile for ClickHouse, Postgres, MySQL — or a
[hybrid warehouse](https://dtk.pipelab.dev/guides/hybrid-mode/) — and the same
four commands keep working.
