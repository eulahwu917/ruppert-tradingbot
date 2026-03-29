# Autoresearch Program — Ruppert Backtest Optimization

## Purpose

This document defines the rules and constraints for `autoresearch.py`, the automated
parameter optimization loop. The loop proposes single-parameter changes, evaluates them
via `run_backtest.py`, and keeps improvements that pass statistical validation.

---

## Tunable Parameters

The autoresearch loop MAY modify these parameters (stored in `temp_config.json`):

| Parameter               | Current Default | Allowed Range   | Description                         |
|-------------------------|-----------------|-----------------|-------------------------------------|
| `min_edge_weather`      | 0.15            | 0.05 – 0.40     | Min edge to enter weather trade     |
| `min_edge_crypto`       | 0.12            | 0.05 – 0.30     | Min edge to enter crypto trade      |
| `min_confidence_weather`| 0.55            | 0.40 – 0.80     | Min confidence for weather signals  |
| `min_confidence_crypto` | 0.50            | 0.35 – 0.75     | Min confidence for crypto signals   |
| `fractional_kelly`      | 0.25            | 0.05 – 0.50     | Kelly fraction multiplier           |
| `pct_capital_cap`       | 0.025           | 0.01 – 0.05     | Max % of capital per trade          |
| `daily_cap_pct`         | 0.70            | 0.30 – 0.90     | Max daily capital deployment ratio  |
| `same_day_skip_hour`    | 14              | 10 – 18         | UTC hour cutoff for same-day skip   |
| `min_trade_size`        | 5.0             | 2.0 – 15.0      | Minimum trade size in dollars       |

---

## Immutable Parameters (NEVER TOUCH)

These MUST NOT be modified by the autoresearch loop under any circumstances:

- **API keys** — any key, token, or secret
- **File paths** — data directory, config paths, output paths
- **`max_position_cap`** — hard dollar cap per position ($50). Risk hard cap.
- **`DRY_RUN` flag** — must never be toggled by automation
- **`run_backtest.py`** — the eval harness itself is immutable
- **Data files** in `data/` — read-only

---

## Statistical Validation Rules

### Bonferroni Correction

After N experiments have been run (including discards), the improvement threshold
adjusts to prevent false positives from multiple comparisons:

```
significance_threshold = 0.05 / N
```

In practice for Sharpe ratio improvements, this means:
- Experiment 1: improvement must be > 0.05 Sharpe points
- Experiment 5: improvement must be > 0.01 Sharpe points
- Experiment 10: improvement must be > 0.005 Sharpe points
- Experiment 20: improvement must be > 0.0025 Sharpe points

### Minimum Trade Count

Both in-sample AND out-of-sample splits must contain **at least 30 trades** for
the result to be valid. If `run_backtest.py` outputs `METRIC: INVALID`, the
experiment is logged as `SKIP_INVALID` and the parameter change is discarded.

### Improvement Requirement

A parameter change is KEPT only if BOTH conditions hold:
1. `METRIC_IN` (in-sample Sharpe) improved over baseline
2. `METRIC_OUT` (out-of-sample Sharpe) improved over baseline
3. The improvement in BOTH exceeds the Bonferroni-adjusted threshold

If only one split improves, or neither exceeds the threshold, the change is DISCARDED.

---

## Output Format (for autoresearch.py parsing)

`run_backtest.py` outputs these lines to stdout:

```
METRIC_IN: <float or INVALID>
METRIC_OUT: <float or INVALID>
METRIC: <float or INVALID>
```

The autoresearch loop parses these via regex: `^METRIC(_IN|_OUT)?: (.+)$`

---

## Logging Format

All experiments are logged to `results.tsv` with these columns:

```
timestamp	experiment_num	param_changed	old_value	new_value	metric_in_old	metric_in_new	metric_out_old	metric_out_new	metric_combined_old	metric_combined_new	bonferroni_threshold	verdict
```

Verdict values: `KEEP`, `DISCARD`, `SKIP_INVALID`

---

## Git Branching Convention

When a parameter change is KEPT:
- Create branch: `autoresearch/<timestamp>-<param_name>`
  - Example: `autoresearch/20260326-143022-min_edge_weather`
- Commit the updated config with message: `autoresearch: <param> <old> -> <new> (sharpe in: X, out: Y)`
- Do NOT merge to main — Optimizer reviews and approves merges

When a change is DISCARDED:
- No git operations
- Log to results.tsv only

---

## Safety Constraints

- Maximum experiments per run: configurable via `--max-experiments` (default 20)
- Sleep 30 seconds between experiments (rate limit for LLM calls)
- If 5 consecutive experiments are INVALID, stop the loop and report
- The loop MUST be stoppable via Ctrl+C (graceful shutdown)
- All state is in `results.tsv` and git branches — the loop is stateless and restartable
