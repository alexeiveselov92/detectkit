# detectkit benchmark harness

Quantitative detection-quality evidence for detectkit's detectors on labeled
public anomaly-detection benchmarks. This is **dev tooling** — a top-level
directory outside the `detectkit` package, excluded from the built wheel
(`[tool.setuptools.packages.find]` only includes `detectkit*`). It never ships
to users and has no bearing on the library's runtime behavior.

It exists to answer, with numbers instead of intuition:

- How do `mad` / `zscore` / `iqr` actually compare on real labeled anomalies,
  not just synthetic unit-test fixtures?
- Does `stabilization: clamp` help or hurt on sustained real-world incidents?
- Is the `autoreg` detector (shipped in v0.52.0) actually better than the windowed
  statistical family on any of these benchmarks?
- Is a from-scratch **Spectral Residual** implementation (see
  `spectral_residual.py`) good enough to be worth shipping as a library
  detector — measured here *before* that decision is made?

## Quickstart (offline, no downloads)

```bash
pip install -e .   # from the repo root, if imports fail
python -m benchmarks.run --datasets synthetic
```

This runs in seconds against a deterministic, offline synthetic series set
(see "Datasets" below) and prints/writes a markdown summary table plus a full
JSON dump of every per-series score.

```bash
# Quick smoke test with fewer series
python -m benchmarks.run --datasets synthetic --max-series 6

# Restrict to a subset of detectors
python -m benchmarks.run --datasets synthetic --detectors mad,iqr,spectral_residual
```

## Datasets

### synthetic (offline, default)

`datasets.load_synthetic()` generates ~2000-point series, deterministically
(`np.random.default_rng(seed)`, default seed `7`), cycling through four
families:

- **spikes** — level + Gaussian noise with a handful of injected point spikes.
- **seasonal** — a daily sinusoid with a few sustained anomalous windows that
  break the seasonal pattern.
- **ar2** — AR(2) autoregressive dynamics with one segment whose coefficients
  change (a genuine dynamics break, not just a level/variance shift) —
  exercises the kind of series an `autoreg` detector is meant for.
- **clean** — no injected anomalies at all, to measure pure false-positive
  behavior.

No network access required; useful for CI-style smoke checks of the harness
itself, not for publishable results (real anomalies in production metrics
rarely look like textbook synthetic fixtures).

### NAB (Numenta Anomaly Benchmark)

MIT-licensed, ~50 real + synthetic labeled series (server metrics, Twitter
volume, traffic, etc.) with hand-labeled anomaly windows.

```bash
python -m benchmarks.run --datasets nab --download-nab
```

`--download-nab` fetches the NAB repo zip (~100MB) from
`https://github.com/numenta/NAB/archive/refs/heads/master.zip`, streams it to
disk, and extracts *only* `data/**` and `labels/combined_windows.json` into
`benchmarks/data/nab/` (the full repo, including its analysis code and
generated reports, is not needed and not kept). Re-run without
`--download-nab` on subsequent invocations once it's downloaded. All NAB
groups are kept, including `artificialNoAnomaly` (all-negative series) — those
measure false-positive behavior on clean data rather than recall, which is a
useful signal in its own right. Each series is named `"<group>/<file>.csv"` so
results can be sliced by group.

### Yahoo S5 (Webscope)

**License-gated** — Yahoo requires a request through the [Yahoo Webscope
program](https://webscope.sandbox.yahoo.com/) before you can download it; it
cannot be fetched automatically. Once you have the extracted archive, point
`--yahoo-dir` at it:

```bash
python -m benchmarks.run --datasets yahoo --yahoo-dir /path/to/ydata-labeled-time-series-anomalies-v1_0
```

The loader (`datasets.load_yahoo`) handles the standard S5 layout:
`A1Benchmark/real_*.csv` and `A2Benchmark/synthetic_*.csv`
(`timestamp,value,is_anomaly`, with an integer-index `timestamp` column
synthesized onto a 1-hour grid), and `A3Benchmark`/`A4Benchmark`
(`timestamps,value,anomaly[,changepoint]`). A CSV whose columns can't be
interpreted is skipped with a warning rather than aborting the whole load.

## Detector matrix

The default sweep (`runner.DEFAULT_DETECTOR_MATRIX`) evaluates:

- `mad`, `zscore`, `iqr` with library defaults;
- the same three with `stabilization: clamp`, to measure whether winsorizing
  flagged points in later trailing windows actually improves recall/precision
  on sustained real incidents (its intended purpose) rather than just being a
  plausible-sounding idea;
- `autoreg` — resolved through `DetectorFactory` (registered since v0.52.0;
  an unknown detector type is skipped with a warning instead of failing the
  sweep — see `runner.available_detector_matrix`);
- `spectral_residual` — the benchmark-local SR implementation
  (`spectral_residual.py`), threshold `3.0`.

Restrict the sweep with `--detectors mad,iqr,...` (matches either the
display label or the underlying detector type).

## Metrics

Reported per (dataset, detector), averaged over every series (`score.py`):

- **`f1` / `event_f1`** — the detector's *native* flags (`is_anomaly` at its
  configured/default threshold) scored pointwise (`f1`) and point-adjusted
  (`event_f1`). This is "what you get out of the box," not the best-case
  number.
- **`f1_best` / `event_f1_best`** — best achievable F1 over a threshold sweep
  on the detector's continuous anomaly score (band-relative distance for the
  windowed detectors, saliency score for Spectral Residual). This isolates
  *ranking quality* from *threshold choice* — useful for comparing detectors
  whose native thresholds aren't calibrated against each other.
- **`pr_auc`** — average precision (area under the precision-recall curve)
  over the continuous score, threshold-free.
- **event / point-adjusted metrics matter here specifically because
  detectkit is alert-centric**: an alert fires once per incident (a
  `consecutive_anomalies`-length streak), not once per anomalous point. A
  pointwise F1 punishes a detector that correctly identifies an entire
  10-point incident but misses 2 points inside it just as harshly as one that
  misses the incident completely — which is not how the product (or its
  users) actually experience detection quality. Point-adjusted scoring (`tp`
  = "this incident had at least one flagged point somewhere inside it")
  matches how a human reads an alert history and is the standard the
  NAB/Yahoo literature converged on for exactly this reason.

All metrics return `0.0` on empty/degenerate input, matching the conventions
in `detectkit/autotune/scoring.py` (the harness's `score.py` does not import
that module — see the note in its docstring — but mirrors its behavior
intentionally, so a detectkit contributor reading both files sees the same
mental model).

## Results — NAB, full run (v0.53.0)

The first full NAB run (58 series, every group kept incl. the all-negative
`artificialNoAnomaly` set), `python -m benchmarks.run --datasets nab` at
detectkit **v0.53.0**. Remember the version caveat above: these numbers are
bound to the detector behavior of that release.

| detector | event_f1_best | f1_best | pr_auc | native_event_f1 |
|---|---|---|---|---|
| zscore (clamp) | **0.244** | **0.206** | **0.140** | 0.061 |
| autoreg | 0.235 | 0.184 | 0.136 | 0.070 |
| mad (clamp) | 0.234 | 0.194 | 0.137 | 0.035 |
| iqr (clamp) | 0.224 | 0.198 | 0.137 | 0.031 |
| mad | 0.217 | 0.184 | 0.127 | 0.035 |
| iqr | 0.210 | 0.182 | 0.120 | 0.032 |
| zscore | 0.173 | 0.190 | 0.110 | 0.076 |
| spectral_residual | 0.147 | 0.142 | 0.097 | 0.123 |

What the numbers established (each of these was a live design question):

- **`stabilization: clamp` improves every windowed detector on real data** —
  zscore +0.071, mad +0.017, iqr +0.014 event_f1_best. The v0.51.0 feature
  does what it was built for outside synthetic fixtures.
- **`autoreg` is the best un-stabilized detector** (0.235, second overall)
  — *after* the v0.53.0 numerical hardening. Before it (v0.52.x), float64
  overflow in the AR normal equations on large-valued series (~1e9) capped
  it at 0.203; centering/scaling each fit window and capping the clamp
  substitution to the observed window range recovered the difference. The
  dynamics detector earns its place on real data, not just on the `ar2`
  synthetic family.
- **Spectral Residual is weaker than everything else on both synthetic and
  NAB** (0.147, last on every ranking metric). The measure-first gate below
  stays closed: it remains a documented negative result, not a shipped
  detector. Its one bright spot — the best `native_event_f1` (0.123) — only
  says its default threshold is better calibrated, not that it ranks
  anomalies better (`pr_auc` is threshold-free and it is last there too).

Absolute NAB scores in the 0.2-0.3 range are normal for point/threshold
detectors without per-series tuning — NAB's own scoreboard leaders sit far
from 1.0. The value here is in the *relative* ordering under one harness.

## MEDIFF: declined without implementation

The same Yandex article that motivated `stabilization: clamp` and the
`autoreg` detector also describes **MEDIFF** — a detector whose baseline is
conditioned on seasonal keys (compare against the median of *comparable*
past points, not all past points). It was declined without even a
benchmark-local implementation: detectkit's windowed detectors already have
exactly that mechanism as **per-group seasonality multipliers**
(`seasonality_components` in `WindowedStatDetector` — per-key center/scale
corrections on top of the global window statistics), so a MEDIFF port would
duplicate an existing, autotunable feature under a new name rather than add
detection power. Revisit only with evidence that the multiplier form
measurably underperforms a dedicated conditioned-baseline detector on a
labeled benchmark.

## Spectral Residual: a measure-first gate

`spectral_residual.py` implements the Spectral Residual saliency algorithm
(Ren et al., KDD 2019) in pure numpy. **It is not part of the detectkit
library** — it lives only in this benchmark directory, evaluated here to
decide *whether it should ever become one*. If it doesn't clear a meaningful
bar over `mad`/`zscore`/`iqr` (with or without `stabilization: clamp`) and the
`autoreg` detector, on real labeled benchmarks, it stays exactly
where it is: a documented negative (or marginal) result, not a shipped
feature. If it does show a real edge, that is the evidence needed to propose
it as a genuine `WindowedStatDetector`-style addition (see
`.claude/rules/contributing.md` → "Add a statistical detector").

## Output

Every run writes two files into `--out` (default `benchmarks/results/`,
gitignored):

- `<timestamp>-results.json` — full per-series rows plus per-(dataset,
  detector) aggregates, and `detectkit_version` (`detectkit.__version__`).
  **Results are only meaningful together with the version that produced
  them** — detector behavior changes across releases (this is explicitly
  allowed; see the project's "breaking changes OK" policy), so a results file
  from one version is not directly comparable to another without checking
  what changed in `CHANGELOG.md`.
- `<timestamp>-results.md` — the same aggregates as a markdown table per
  dataset (also printed to stdout).

## Files

- `datasets.py` — `LabeledSeries` + the three dataset providers.
- `score.py` — pure-numpy scoring metrics (no detectkit import — stands alone).
- `spectral_residual.py` — the benchmark-local SR implementation.
- `runner.py` — wires a `LabeledSeries` + detector config through
  `DetectorFactory`/`detectkit.autotune.crossval.predictions_from_results` (or
  the local SR module) into scored results, and aggregates them.
- `run.py` — the `python -m benchmarks.run` CLI.
