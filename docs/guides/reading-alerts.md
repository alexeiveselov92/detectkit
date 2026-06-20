# Reading a detectkit alert

*You probably landed here by clicking **"How to read this alert"** at the bottom
of a notification in Slack, Mattermost, Telegram, or email. This page explains —
in plain language — what that alert is telling you and what to do about it. No
detectkit setup knowledge required.*

## In 10 seconds

- A **detectkit** alert means one of your team's metrics (an order count, an
  error rate, a signup number, …) just **moved outside its normal range** for
  long enough that it's worth a human look.
- The colored circle at the start of the title tells you the kind at a glance:
  **🔴 something looks wrong**, **🟢 it's back to normal**, **🟡 the data
  stopped arriving**, **🔵 the monitoring itself failed**.
- The alert shows the **current value** and the **expected range**. If the value
  is far outside the range, that's the thing to look into.
- You don't need to fix detectkit — it's just the messenger. Look at the metric
  it names and decide whether the business/system needs attention.

That's enough to triage. The rest of this page explains each piece if you want
to understand *why* it fired.

## What am I actually looking at?

detectkit watches metrics over time and learns what "normal" looks like for each
one — including daily and weekly rhythms (mornings are busier, weekends are
quieter, and so on). When recent points fall outside that learned normal range,
it sends one of these notifications. It is **not** a guess from a single weird
data point: by default an alert only fires after several points in a row look
abnormal *and* more than one independent check agrees (see
[Why did it fire?](#why-did-it-fire) below).

The notification leads with **the alert and the rule it fired on**; the actual
anomalous number is supporting evidence underneath.

## The status colors

Every alert title starts with a colored circle so you can read the status from
color alone:

| Circle | Status | What it means |
|---|---|---|
| 🔴 | **Anomaly** | A metric moved outside its expected range and stayed there. This is the "please look" signal. |
| 🟢 | **Recovered** | A previously-alerting metric is back inside its expected range. The incident is over — no action needed. |
| 🟡 | **No data** | The metric's data stopped arriving for the latest period. Often a broken pipeline/job upstream, not the business metric itself. |
| 🔵 | **Pipeline error** | detectkit's own monitoring run failed (e.g. the database was unreachable). The metric might be fine — the *monitor* couldn't check it. |

The same colors are used on dashboards and accent bars, so 🔴 in chat, a red bar
in email, and a red marker on a chart all mean the same thing.

## Anatomy of an alert

A typical anomaly alert carries these fields. You don't need all of them to
triage — **Value** and **Expected** are usually enough — but here's what each
one means.

| Field | Plain-language meaning |
|---|---|
| **Metric** (the title) | Which metric fired. This is the thing to investigate. Often a clickable link to a dashboard. |
| **Value** | The actual measured value at the flagged time. |
| **Expected** | The range detectkit considered normal for that moment. `[12.0, 40.0]` means "we expected somewhere between 12 and 40". `>= 100` / `<= 5` are one-sided limits. |
| **Detected at** | The timestamp of the flagged point, in the configured timezone. |
| **Severity** | Roughly *how far* outside normal the value was — bigger means more extreme. Use it to prioritize between several alerts, not as an exact unit. |
| **Quorum** | How many independent checks agreed it was abnormal (e.g. `2/2`), and in which direction (up/down). More agreement = more confidence. |
| **Rule** | The condition that fired, shown as a chip: `min_detectors=… · direction=… · consecutive=…` — *how many checks had to agree, in which direction, for how many points in a row*. It appears on both 🔴 anomalies and 🟢 recoveries. |
| **Detectors / Parameters** | The technical checks that flagged it and their settings. Safe to ignore unless you're tuning the monitoring. |
| **[name] prefix** | If the title starts with `[something]`, that's the **project** the alert came from — useful when several projects post to the same channel. |

### Value vs Expected — the one comparison that matters

The fastest read is **Value against Expected**:

- Value **above** the expected range → the metric spiked (e.g. errors jumped,
  latency rose).
- Value **below** the expected range → the metric dropped (e.g. orders fell,
  signups stalled).
- The further outside the range, and the higher the **Severity**, the more
  likely it's real and worth acting on.

## Why did it fire?

detectkit is deliberately conservative to avoid crying wolf. By default an
anomaly alert requires **several consecutive points** to each look abnormal, and
a **quorum** of independent checks to agree — so a single noisy reading won't
page anyone. The alert spells out the rule it fired on (for example:
*min_detectors=2, direction=same, consecutive=3* — "at least two checks agreed
on the same direction, three points in a row"). If you see a 🔴, it cleared that
bar.

A **🟢 recovery** is sent once the metric comes back inside the expected range,
so you know the incident closed without having to check yourself.

## What should I do when I get one?

1. **Read the color.** 🟢 means it's already over. 🔵/🟡 point at the data
   pipeline, not (necessarily) the business.
2. **Look at Value vs Expected** for a 🔴. How far out is it? Is the direction
   (up/down) good or bad for this metric?
3. **Open the dashboard** if the alert links one (the title, an "Open dashboard"
   button/link) to see the trend around the flagged point.
4. **Decide and route.** If it's a real problem, loop in whoever owns that
   metric or system. If it's expected (a launch, a known spike, a planned
   outage), you can ignore it — and the metric's owner can tune the thresholds.
5. **You can't break anything by ignoring it.** detectkit keeps watching and
   will send a 🟢 when things normalize.

## Frequently asked

**Is this an outage / does it page someone?** Not by itself — it's a heads-up
that a watched number looks unusual. Whether it's urgent depends on the metric
and your team's process.

**The value looks fine to me — why did it alert?** "Normal" is learned per
metric and per time-of-day/week. A value that looks ordinary can still be
unusual *for that moment* (e.g. very low traffic at peak hour).

**Can I make these stop / change them?** The person who set up detectkit for
your team controls which metrics alert, how sensitive they are, and where they
post. Share the alert with them.

---

*For the people who configure these alerts: see the
[Alerting guide](alerting.md) and [Alert channels](alerting-channels.md). The
"How to read this alert" link points here by default and can be redirected to
your own runbook (or hidden) with `alert_help_url` in `detectkit_project.yml` —
see [Configuration](configuration.md#alert_help_url-string--bool-optional).*
