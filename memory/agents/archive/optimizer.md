# SA-1: Optimizer Memory
_Accumulated learnings from trade settlements and algo tuning._
_Updated after each review cycle._

---

## Mandate

Review settled trades after each settlement cycle. Identify what worked and what didn't.
Propose parameter adjustments to CEO. Never change live params without CEO approval.

## How to Run

1. Read `team_context.md` first
2. Read recent trade logs: `logs/trades_YYYY-MM-DD.jsonl`
3. Check settled positions (status: finalized on Kalshi)
4. Compute: hit rate per module, avg edge at entry, edge decay over hold period
5. Compare model probability vs actual settlement outcome → calibration check
6. Propose changes → report to CEO

---

## Performance Log

### 2026-03-11 (first review)
**Settled trades:**
- KXHIGHMIA-26MAR10-B84.5 NO × 2 — LOSS (settled YES, temp exceeded 84.5°F)
  - Entry edge: ~18% (model said ~82% NO, market ~64% NO)
  - Outcome: model was wrong — Miami was warmer than expected
  - Note: Miami +4°F bias may be insufficient; actual temp exceeded threshold

**Open positions (11 active, not yet settled)**
- NY/Chicago March 11 weather: no_bid=99¢ → near-certain wins pending settlement
- Miami March 11 mixed: one winning, one losing

**Calibration note:**
- Miami bias correction (+4°F) is based on 1 backtest day only — insufficient
- Need 10+ settlements to validate bias per city
- Chicago/NY performing well on first cycle

**Proposed changes:** None yet — too early (1 settled trade). Review after Friday.

---

## Optimization Queue (pending Friday review)

- [ ] Validate Miami +4°F bias (need more settlements)
- [ ] Compute Brier Skill Score once 5+ weather trades settle
- [ ] Review crypto edge thresholds after first crypto settlement
- [ ] Check if 95¢ rule would have been triggered on NY/Chicago positions (would save settlement wait time)
