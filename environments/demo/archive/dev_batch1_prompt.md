You are the Developer (SA-3) for the Ruppert Kalshi trading bot. Execute the following 3 phases exactly as specified. QA will verify after you finish. Do not skip steps. Do not modify files outside the scope below.

---

## PHASE 1 — Data Archive & Reset

1. Create folder: `logs/archive-pre-2026-03-26/`

2. MOVE (not copy) these files into the archive folder (skip any that don't exist):
   - trades_2026-03-10.jsonl
   - trades_2026-03-11.jsonl
   - trades_2026-03-13.jsonl
   - activity_2026-03-10.log
   - activity_2026-03-11.log
   - activity_2026-03-12.log
   - activity_2026-03-13.log
   - activity_2026-03-14.log
   - activity_2026-03-26.log
   - cycle_log.jsonl
   - best_bets.jsonl
   - highconviction_approved.jsonl
   - monitor.jsonl
   - position_monitor.jsonl
   - pnl_cache.json
   - step4_settled_raw.json
   - step5_backtest.json
   - backtest_2026-03-10.json
   - gaming_scout.jsonl

3. Create fresh `pnl_cache.json` in active logs folder containing: `{}`

4. Create fresh empty `cycle_log.jsonl` in active logs folder (empty file)

---

## PHASE 2 — Strategy Parameter Changes

FILE: `bot/strategy.py`

Make these 3 changes:

CHANGE 1: Find the line `'weather': 0.30,` and change to `'weather': 0.12,`

CHANGE 2: Find the line `MIN_CONFIDENCE   = 0.50` and change to `MIN_CONFIDENCE   = 0.25`

CHANGE 3: Replace the entire `kelly_fraction_for_confidence` function with:

```python
def kelly_fraction_for_confidence(confidence: float) -> float:
    """
    Return the fractional Kelly multiplier appropriate for a given confidence level.

    Higher confidence -> larger fraction of the Kelly-optimal bet.
    6-tier structure for DEMO data accumulation phase (2026-03-26).
    Low confidence tiers (25-50%) added to maximize trade volume in DEMO.

    Tiers:
        80%+    -> 0.16  (compressed from 0.25 -- unvalidated calibration)
        70-80%  -> 0.14
        60-70%  -> 0.12
        50-60%  -> 0.10
        40-50%  -> 0.07
        25-40%  -> 0.05  (minimum -- data accumulation only)

    Post-Brier review: recalibrate all tiers against actual calibration data.
    """
    if confidence >= 0.80:
        return 0.16
    if confidence >= 0.70:
        return 0.14
    if confidence >= 0.60:
        return 0.12
    if confidence >= 0.50:
        return 0.10
    if confidence >= 0.40:
        return 0.07
    return 0.05  # 25-40% confidence band
```

---

## PHASE 3 — YES Shadow Logging

### 3a. Add this function to `edge_detector.py` at the module level (near top, after imports):

```python
def _shadow_log_yes_signal(signal: dict):
    """Log YES weather signals as counterfactuals -- never executed, observation only."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    shadow_file = Path(__file__).parent / 'logs' / 'weather_yes_shadow.jsonl'
    try:
        shadow_file.parent.mkdir(exist_ok=True)
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'ticker': signal.get('ticker', ''),
            'predicted_prob': signal.get('win_prob', signal.get('prob')),
            'market_price': signal.get('market_price', signal.get('yes_ask')),
            'edge': signal.get('edge'),
            'direction': 'yes',
            'note': 'counterfactual -- direction filter blocked execution'
        }
        with open(shadow_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass  # Never crash on shadow logging
```

### 3b. In `ruppert_cycle.py`:

Find the weather direction filter section -- where YES signals are blocked and a count is logged (look for WEATHER_DIRECTION_FILTER check and the log message about blocked YES trades).

At that point, before or after logging the count, iterate through the blocked YES signals and call `edge_detector._shadow_log_yes_signal(signal)` for each one that had edge above the minimum threshold.

---

## VERIFICATION

Run these checks and report the exact output of each:

Check 1:
```
python -c "import bot.strategy as s; print('Kelly 0.85:', s.kelly_fraction_for_confidence(0.85)); print('Kelly 0.55:', s.kelly_fraction_for_confidence(0.55)); print('Kelly 0.35:', s.kelly_fraction_for_confidence(0.35)); print('MIN_CONFIDENCE:', s.MIN_CONFIDENCE); print('Weather edge:', s.MIN_EDGE['weather'])"
```

Expected:
```
Kelly 0.85: 0.16
Kelly 0.55: 0.10
Kelly 0.35: 0.05
MIN_CONFIDENCE: 0.25
Weather edge: 0.12
```

Check 2: `python -c "import edge_detector; print('OK')"`
Check 3: `python -c "import ruppert_cycle; print('OK')"`
Check 4: Confirm archive folder exists with files moved: `dir logs\archive-pre-2026-03-26\`

Report results of all 4 checks.
