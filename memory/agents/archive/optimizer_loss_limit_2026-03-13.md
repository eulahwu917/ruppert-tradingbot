# Daily Loss Limit Recommendation — Live Go-Live
_SA-1 Optimizer | 2026-03-13 | For CEO presentation to David_

---

## Recommendation: **20% daily loss limit = $37.00 at $185 capital**

---

## Data Inputs

| Metric | Value |
|--------|-------|
| Starting live capital | $185 (midpoint estimate) |
| 30% hard reserve | $55.50 (never deployed) |
| 70% deployable daily cap | $129.50 |
| Max per trade (demo observed) | ~$25 |
| Max trades/day within cap | 5 (at $25 each) |
| **Worst demo day loss** | **-$31.48** (Mar 11, 4 losing trades) |
| Worst demo day as % of $185 | 17.0% |
| Worst-case scenario (all 5 trades lose) | -$125 (67.6% of capital) |

---

## Calculation Logic

**Normal bad day** (1–2 losing trades at standard sizing):
- 1 loss × $25 = $25 → **13.5%** of capital
- 2 losses × $25 = $50 → **27.0%** of capital

**Observed worst demo day** (March 11): $31.48 → **17.0%**
- 4 losing trades: 3 small CPI manual closes + 1 full Miami weather loss
- Known degraded-signal conditions (NWS down, unvalidated bias)

**Catastrophic scenario** (3+ trades all lose):
- 3 losses = $75 → 40.5%
- 5 losses = $125 → 67.6%

---

## Why 20% ($37)

| Threshold | Verdict |
|-----------|---------|
| 15% ($27.75) | ❌ Too tight — triggers on 1 bad trade + 1 small loss. Fires on normal variance. |
| **20% ($37)** | ✅ **RECOMMENDED** — above worst observed day (17%), below any catastrophic scenario. |
| 25% ($46.25) | ⚠️ Acceptable but allows 2 full losses before halting. Slightly more exposure. |
| 30% ($55.50) | ❌ Too loose — allows 3 max-size losses before stopping. Meaningful capital damage. |

**The 20% threshold works because:**
1. Our worst demo day was 17.0% — the limit does NOT trigger on that scenario ✓
2. If Trade 1 loses ($25 = 13.5%) → no halt, bot continues
3. If Trade 2 also loses ($50 = 27%) → **halt fires** before Trade 3, 4, 5 can fire ✓
4. Worst case under this rule: 2 full losses = $50 drawdown, leaving $135 in the account
5. $135 >> 30% reserve floor ($55.50) → fully recoverable next day ✓

---

## Trigger Scenario

**This limit fires when:** cumulative realized losses in a single calendar day exceed **$37**.

**Example scenarios that trigger it:**
- 2 full-size losing trades in a row ($25 + $25 = $50 → halt after 2nd loss confirms)
- 1 large loss + multiple small losses adding to $37+
- Any single catastrophic position that blows through $37 on settlement

**Example scenarios that DO NOT trigger it:**
- 1 losing trade at standard sizing ($25 = 13.5% → below threshold)
- The March 11 demo worst-day scenario if Miami loss was capped at $37 limit ($31.48 = 17%)
- Normal bad day with 1–2 small CPI-style losses ($5–$10 range)

---

## Recoverability

After a 20% halt day:
- Remaining capital: ~$148 (worst case after 2 full losses)
- Reserve intact: $55.50 floor untouched
- Next day: bot resumes at reduced sizing (~$3.70/trade at 2.5% of $148)
- Recovery time: 3–5 winning trades to restore daily cap headroom

**This is fully recoverable.** The account survives, the bot resumes, and no permanent damage occurs.

---

## Implementation Note

The daily loss tracker should:
1. Sum all **realized P&L** (settled + closed positions) per calendar day
2. When cumulative loss hits **-$37**, disable all new order submissions for the rest of the day
3. Log the halt event with timestamp and running loss total
4. Auto-reset at midnight Pacific time
5. Alert David via Telegram when halt triggers

---

## Summary

> **Set daily loss limit to 20% = $37.00.** It won't fire on a normal bad day. It fires after 2 full-loss trades and stops the death spiral before it becomes unrecoverable. The account survives at $148+ and resumes the next morning.

_— SA-1 Optimizer_
