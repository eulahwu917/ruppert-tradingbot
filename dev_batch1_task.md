You are the Developer (SA-3) for the Ruppert Kalshi trading bot. Execute the following 3 phases exactly as specified. QA will verify after you finish. Do not skip steps. Do not modify files outside the scope below.

---

## PHASE 1 — Data Archive & Reset

1. Create folder: `logs/archive-pre-2026-03-26/`

2. MOVE (not copy) these files into the archive folder (skip any that don't exist):
   - trades_2026-03-10.jsonl, trades_2026-03-11.jsonl, trades_2026-03-13.jsonl
   - activity_2026-03-10.log, activity_2026-03-11.log, activity_2026-03-12.log, activity_2026-03-13.log, activity_2026-03-14.log, activity_2026-03-26.log
   - cycle_log.jsonl
   - best_bets.jsonl, highconviction_approved.jsonl
   - monitor.jsonl, position_monitor.jsonl
   - pnl_cache.json
   - step4_settled_raw.json, step5_backtest.json
   - backtest_2026-03-10.json
   - gaming_scout.jsonl

3. Reset pnl_cache.json in the ACTIVE logs folder to: `{}`

4. Create fresh empty cycle_log.jsonl in the ACTIVE logs folder (empty file)

---

## PHASE 2 — Strategy Parameter Changes

FILE: `bot/strategy.py`

1. Change weather edge: find `'weather': 0.30` → change to `'weather': 0.12`

2. Change confidence minimum: find `MIN_CONFIDENCE   = 0.50` → change to `MIN_CONFIDENCE   = 0.25`

3. Replace the entire `kelly_fraction_for_confidence` function body with a new 6-tier version:
   - confidence >= 0.80 → return 0.16
   - confidence >= 0.70 → return 0.14
   - confidence >= 0.60 → return 0.12
   - confidence >= 0.50 → return 0.10
   - confidence >= 0.40 → return 0.07
   - else (25-40% band) → return 0.05

   Update the docstring to describe the 6-tier structure and note "Post-Brier review: recalibrate all tiers against actual calibration data."

---

## PHASE 3 — YES Shadow Logging

### 3a. In `edge_detector.py`:
Add a module-level function `_shadow_log_yes_signal(signal: dict)` that:
- Appends to `logs/weather_yes_shadow.jsonl`
- Logs: ts (UTC ISO), ticker, predicted_prob, market_price, edge, direction='yes', note='counterfactual — direction filter blocked execution'
- Never raises an exception (try/except everything)

### 3b. In `ruppert_cycle.py`:
Find where the direction filter blocks YES weather trades and logs the count.
Iterate the blocked YES signals and call `_shadow_log_yes_signal()` for each one that had edge above min threshold.
Import the function from edge_detector if needed.

---

## VERIFICATION

Run this and report exact output:
```
python -c "import bot.strategy as s; print('Kelly 0.85:', s.kelly_fraction_for_confidence(0.85)); print('Kelly 0.55:', s.kelly_fraction_for_confidence(0.55)); print('Kelly 0.35:', s.kelly_fraction_for_confidence(0.35)); print('MIN_CONFIDENCE:', s.MIN_CONFIDENCE); print('Weather edge:', s.MIN_EDGE['weather'])"
```

Expected:
- Kelly 0.85: 0.16
- Kelly 0.55: 0.10
- Kelly 0.35: 0.05
- MIN_CONFIDENCE: 0.25
- Weather edge: 0.12

Also verify:
- python -c "import edge_detector; print('OK')"
- python -c "import ruppert_cycle; print('OK')"
- logs/archive-pre-2026-03-26/ exists with old files
- logs/cycle_log.jsonl exists and is empty
- logs/pnl_cache.json contains {}
