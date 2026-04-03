# Daily Module Shadow Analysis Plan
_Written: 2026-04-03 | Author: Strategist_

---

## Context

`crypto_band_daily` and `crypto_threshold_daily` are currently paused from live trading. Before re-enabling, we need a win rate baseline over 50+ decisions to confirm the signals are performing above the 45% floor required for positive EV at our typical edge margins.

This document defines how to run shadow mode, what to collect, and how to report.

---

## Current Shadow Infrastructure

### crypto_threshold_daily.py

**No explicit `SHADOW_MODE` flag exists.** However, the module already reads `config.DRY_RUN`:

```python
dry_run = config.DRY_RUN
result = Trader(dry_run=dry_run).execute_opportunity(trade_opp)
```

When `DRY_RUN = True` in `config.py`, `Trader` logs the trade but does **not** place the actual order. The decision log (`decisions_1d.jsonl`) is written regardless.

**Conclusion: `crypto_threshold_daily` already has shadow mode via `DRY_RUN = True`.**

### crypto_band_daily.py

Same pattern — `run_crypto_scan()` accepts a `dry_run` parameter:

```python
def run_crypto_scan(dry_run=True, ...):
    ...
    trader = Trader(dry_run=dry_run)
```

The caller (presumably `ruppert_cycle.py`) passes `dry_run` from config. The decision log (`decisions_band.jsonl`) is written regardless of `dry_run` value.

**Conclusion: `crypto_band_daily` already has shadow mode via `dry_run=True`.**

---

## How to Enable Shadow Mode

### Step 1 — Confirm config.py setting

In `config.py` (or the active environment config), set:

```python
DRY_RUN = True
```

This ensures both modules log decisions without placing real orders.

### Step 2 — Confirm the modules are scheduled to run

The Windows Task Scheduler task (`Ruppert-Crypto1D`) must still be active. Shadow mode only works if the modules are actually running on schedule — they just won't place orders.

Check with:
```
schtasks /query /tn "Ruppert-Crypto1D" /fo list
```

If the task is disabled, re-enable it (in DRY_RUN mode).

### Step 3 — Confirm decision logs are being written

After the first run, check:
- `environments/demo/logs/decisions_1d.jsonl` — threshold_daily decisions
- `environments/demo/logs/decisions_band.jsonl` — band_daily decisions

Each run should append SKIP and ENTER records. ENTER records in shadow mode mean "would have traded here."

---

## What Data to Collect

Both decision logs already capture the fields we need. The key fields for win rate analysis:

### Per-decision fields (decisions_1d.jsonl)

| Field | What it tells us |
|---|---|
| `ts` | When the decision was made |
| `asset` | BTC or ETH |
| `decision` | ENTER or SKIP |
| `side` | yes or no (direction of the trade) |
| `P_above` | Model's predicted probability of price being above strike |
| `confidence` | Signal confidence (0–1) |
| `edge` | Model edge over market price |
| `ticker` | Kalshi market ID — used to look up settlement outcome |
| `poly_daily_yes_price` | Polymarket daily consensus at decision time |
| `signals.S1.regime` | Momentum regime |
| `signals.S2.regime` | Funding regime |
| `composite` | Raw composite score |

### Per-decision fields (decisions_band.jsonl)

| Field | What it tells us |
|---|---|
| `ts` | When the decision was made |
| `series` | KXBTC, KXETH, etc. |
| `decision` | ENTER or SKIP |
| `side` | yes or no |
| `model_prob` | Log-normal P(in-band) |
| `confidence` | Composite confidence |
| `edge` | Best edge (no or yes) |
| `ticker` | Kalshi market ID for settlement lookup |
| `poly_daily_yes_price` | Polymarket daily consensus |

### Settlement outcome lookup

To determine win/loss for each ENTER decision:
1. Use the `ticker` field to query Kalshi settlement outcome after market closes
2. The `scripts/data_toolkit.py` may already support this — check if `winrate --module crypto_threshold_daily` pulls from decision log vs trade log
3. If not, write a small resolution script: `scripts/shadow_resolve.py` that reads `decisions_1d.jsonl`, filters `decision == 'ENTER'`, and matches each `ticker` against the Kalshi settled markets endpoint to tag win/loss

---

## Weekly WR Reporting to David

Every **Monday morning** (first heartbeat after 08:00 PDT), Strategist will:

1. Run analysis against both decision logs for the prior 7 days:
   - Count ENTER decisions
   - Resolve outcomes (via `data_toolkit.py winrate` or manual lookup)
   - Compute overall WR, WR by asset, WR by side (yes vs no)

2. Report to David via Telegram in this format:

```
📊 Weekly Shadow WR Report — crypto_band_daily / crypto_threshold_daily
Period: [Mon] to [Sun]

crypto_threshold_daily:
  BTC: X/Y wins (WR: Z%)
  ETH: X/Y wins (WR: Z%)
  Combined: X/Y (WR: Z%)

crypto_band_daily:
  BTC: X/Y wins (WR: Z%)
  ETH: X/Y wins (WR: Z%)
  Combined: X/Y (WR: Z%)

Cumulative (all shadow trades to date):
  Total decisions: N
  Overall WR: Z%
  Status: [BELOW THRESHOLD / APPROACHING THRESHOLD / THRESHOLD MET]
```

3. If cumulative N < 50, flag: "⚠️ Insufficient data — need 50+ decisions before recommendation."

---

## Re-Enable Threshold

**Recommendation to re-enable live trading triggers when ALL of the following are met:**

| Condition | Threshold |
|---|---|
| Cumulative shadow decisions | ≥ 50 ENTER decisions |
| Overall shadow WR | > 45% |
| No single asset below | > 40% (neither BTC nor ETH can be dragging hard) |
| No active circuit breaker trip | 0 consecutive losses at trigger point |

When threshold is met, Strategist will send David a recommendation message:

> "Shadow WR hit [X]% over [N] decisions (threshold: 45% / 50 trades). Both BTC and ETH above floor. Recommend re-enabling live mode. Your call — reply APPROVE to proceed."

David's explicit approval is required before changing `DRY_RUN = False` in config.

---

## What Triggers Continued Pause

If after 100+ shadow decisions the WR is still below 45%, Strategist will:

1. Flag it to David: "Shadow WR at [X]% over [N] decisions — below 45% threshold. Recommend keeping daily modules paused."
2. Run a segment analysis: WR by asset, by window (primary vs secondary), by momentum regime
3. Form a hypothesis about what's dragging WR
4. Write a spec if a signal-level fix is warranted

No code changes without a spec → Dev → QA pipeline.

---

## Spec for SHADOW_MODE Flag (If DRY_RUN Can't Be Used)

If it turns out `DRY_RUN` controls more than just order placement (e.g. it also suppresses logging or alters signal computation), we need a dedicated `SHADOW_MODE` flag. In that case, Dev should implement:

### In config.py:
```python
SHADOW_MODE = True  # Log decisions but skip order placement; does not affect signal computation
```

### In crypto_threshold_daily.py — evaluate_crypto_1d_entry():
```python
# Replace the Trader() call:
shadow_mode = getattr(config, 'SHADOW_MODE', False)
if not shadow_mode:
    result = Trader(dry_run=config.DRY_RUN).execute_opportunity(trade_opp)
else:
    result = True  # Treat as successful "would-have-traded" for logging purposes
    log_activity(f'[Crypto1D] SHADOW: would have entered {market_id} {side} {contracts}@{cost_cents}c')
```

### In crypto_band_daily.py — run_crypto_scan():
```python
# Replace the trader.execute_opportunity() call:
shadow_mode = getattr(config, 'SHADOW_MODE', False)
if not shadow_mode:
    result = trader.execute_opportunity(opp)
else:
    result = True
    print(f'  [Shadow] Would have traded {t["ticker"]} {t["side"]} @ {t["price"]}c')
```

All logging (`_log_band_decision`, `_log_decision`) continues unchanged in both modes.

**Note:** Only implement this if DRY_RUN proves insufficient. Current read of the code suggests DRY_RUN alone is enough.

---

## Summary

| Item | Status |
|---|---|
| Shadow mode mechanism | **Exists** — `DRY_RUN = True` in both modules |
| Decision logs | **Exist** — `decisions_1d.jsonl`, `decisions_band.jsonl` |
| Required fields | **Present** — ticker, side, edge, confidence, P_above all logged |
| WR reporting | **Needs setup** — weekly Strategist heartbeat task |
| Re-enable trigger | WR > 45% over 50+ ENTER decisions, David approval required |

**Immediate action:** Confirm `DRY_RUN = True` in config, confirm Task Scheduler task is running, check first decision log entries appear. No code changes needed to start shadow collection.
