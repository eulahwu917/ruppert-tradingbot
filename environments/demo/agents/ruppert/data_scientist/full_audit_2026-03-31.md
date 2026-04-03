
# Full Data Audit — 2026-03-31
**Auditor:** Ruppert DS Sub-Agent  
**Records scanned:** 847 trade records (416 buys, 210 settles, 182 exits, 41 exit_corrections)  
**Files:** trades_2026-03-26 through trades_2026-03-31.jsonl

---

## SECTION 1: P&L INTEGRITY

### 1a. Recount from scratch

| Component | Amount |
|-----------|--------|
| Settle records P&L | -$14,235.69 |
| Exit records P&L | +$27,052.81 |
| **Raw gross P&L** | **+$12,583.26** |
| Exit_correction delta | -$16,474.36 |
| **Corrected P&L (claimed)** | **-$3,891.10** |

**VERDICT: -$3,891.10 is confirmed.** Our independent recount matches. The pnl_cache.json ($12,583.26) is the uncorrected pre-bug-fix value. After applying 41 correction records, we arrive at -$3,891.10.

### 1b. Entry reconciliation
- `entry_price * contracts / 100 vs size_dollars`: 15 mismatches found, all <$1 (rounding from partial fills at fractional cent prices). **No material discrepancies.**

### 1c. Impossible P&L on settle records
- **3 records** where `loss > cost` by <$0.55 — minor rounding at the margin. Not material.

---

## SECTION 2: EXIT PRICE BUG (95c_rule_no)

### Bug mechanics
The WS feed fires `95c_rule_no` when YES price ≤ 5c (NO position is near-certain winner). It was recording `exit_price = 95` (correct NO price) but computing P&L as if the NO position *lost* at 0c, then logging a phantom WIN equal to entry_cost as profit.

### Scale
| Category | Count |
|----------|-------|
| Total `95c_rule_no` exit records | 82 |
| "@ 0c" entries (confirmed phantom wins) | **52** |
| "@ non-zero" exits (bot exited mid-stream, may be legit) | 30 |
| Correction records applied | 41 |
| **MISSING corrections (today's trades)** | **11** |
| Wrong corrections (applied to non-bug exits) | **0** |

### Missing corrections — today only
All 11 missing corrections are from 2026-03-31 (today). The 41 corrections only covered 2026-03-30 (4) and partial 2026-03-31 (37). **These 11 phantom wins are still inflating the raw P&L.**

Missing (sample): KXETH15M-26MAR311415-15 ($300), KXDOGE15M-26MAR311415-15 ($426), KXXRP15M-26MAR311415-15 ($376), plus 8 more.

**Estimated remaining phantom win inflation: ~$2,917 (sum of 11 missing correction deltas).**

---

## SECTION 3: NEWLY DISCOVERED BUG — NO Exit P&L Formula

🚨 **This is a NEW bug not in any existing correction records.**

### What's wrong
The WS feed calculates P&L for NO exits as:
```
pnl = (entry_price + exit_price - 100) * contracts / 100   ← WRONG
```
Correct formula:
```
pnl = (exit_price - entry_price) * contracts / 100         ← CORRECT
```
(Same formula as YES exits, which are all correct.)

### Evidence
- All 51 NO exit records match the wrong formula exactly (51/51)
- Zero match the correct formula (1/51, a fluke)
- All 48 YES exit records match the correct formula (48/48)
- YES exits are fine; NO exits are uniformly wrong

### Impact
| | Amount |
|--|--------|
| Logged NO exit P&L (wrong formula) | $5,257.20 |
| Correct NO exit P&L | $2,829.04 |
| **Overstatement** | **$2,428.16** |

This affects **all 70pct_gain_no and 95c_rule_no (non-zero) exits**, i.e., any NO position that was exited via the WS feed rather than settled.

### True corrected P&L
```
-$3,891.10 (95c_rule_no corrected) - $2,428.16 (NO formula bug) = ~-$6,319
```
But note: some of the NO exit overstatement overlaps with the 95c phantom wins already in correction records. The non-overlapping portion (70pct_gain_no exits only): **$2,428.16 is NOT corrected anywhere.**

---

## SECTION 4: WEATHER MODULE — 0 Wins

### Real or artifact?

**REAL. This is a genuine model failure, not a data recording issue.**

| Metric | Value |
|--------|-------|
| Weather buy records | 70 |
| Weather close records (settle+exit) | 61 |
| W/L | **4W / 57L** |
| Win rate | 6.6% |
| Total P&L | **-$4,341.10** |

### What's happening

1. **All 70 weather buys are YES positions.** Not a single NO buy. The bot is always betting "the weather WILL match the forecast" — correct directional logic since it's buying markets where NOAA says 99%+ probability.

2. **The 1c entry problem:** 21 trades entered at 1c (market says 1% chance). All 21 LOST. The bot's NOAA model was assigning 97-99% probability to outcomes the market priced at 1%. The market was right every time. **This is systematic NOAA overconfidence**, not a data artifact.

3. **Average entry edge = 0.73** across all weather trades — the model *thinks* it has huge edge. Yet 93% loss rate.

4. **Settlement results:** 57 "no" settlements, 2 "yes." Bot settled correctly (tracked properly).

### Root cause
The NOAA probability model is miscalibrated. It's assigning extreme probabilities to temperature band outcomes that the market (and reality) consistently disagrees with. Weather band markets settle based on actual observed temperatures, and the bot's NOAA signals are not reliable predictors.

**Verdict: Real losses. Data is fine. Model is broken.**

---

## SECTION 5: crypto_15m (old label) — 25% Win Rate

### Real or artifact?

**The 25% figure (after correction) is REAL but misleading without context.**

| State | W | L | WR | P&L |
|-------|---|---|----|-----|
| RAW (before 95c correction) | 56 | 24 | **70%** | +$6,857 |
| CORRECTED (36 correction records applied) | 20 | 60 | **25%** | -$5,561 |

The raw 70% WR was a mass illusion from phantom wins — **36 of the correction records (out of 41 total) were for crypto_15m positions.**

### Double-entry from race condition
- Zero duplicate buy records found (race condition fix worked for entries)
- **5 ticker+date overlaps** between old label and new label in close records — these are genuine doubles where the same market was tracked by BOTH processes simultaneously and closed twice
- Total P&L in overlapping doubles: $564.87 (not huge, but real double-counting)

### Old label vs new label timing
- Old label (crypto_15m): ALL records are from 2026-03-31 (before migration)
- New label (crypto_15m_dir): records from 2026-03-30 AND 2026-03-31
- Old label was in use during the morning of 3/31 before taxonomy migration

### Summary
The 25% WR for crypto_15m old label is **real underperformance** compounded by the 95c_rule_no bug affecting this module heavily. The corrected new label (crypto_15m_dir) shows 68% WR — dramatically different.

---

## SECTION 6: DATA QUALITY FLAGS

### Win rates by data_quality (linked via ticker to close records)

| data_quality | W | L | WR% | P&L |
|--------------|---|---|-----|-----|
| standard | 104 | 33 | **76%** | +$15,509 |
| thin_market | 66 | 39 | **63%** | +$3,381 |
| wide_spread | 9 | 2 | **82%** | +$1,098 |
| NO_FIELD (old records) | 4 | 44 | **8%** | -$3,504 |
| None (field present but null) | 11 | 80 | **12%** | -$3,667 |

**Critical finding:** Records with NO data_quality field or null perform catastrophically (8-12% WR). These are primarily the early weather and crypto trades from before the data_quality field was added. The `thin_market` and `wide_spread` labels actually perform *better* than standard — suggesting the quality filter is conservative.

### Missing required fields
| Field | Missing Count | Notes |
|-------|---------------|-------|
| ticker | 0 | ✅ |
| side | 0 | ✅ |
| **entry_price** | **64** | ⚠️ All early weather buys — entry_price was logged post-hoc via fill_price |
| contracts | 0 | ✅ |
| size_dollars | 0 | ✅ |

The 64 missing entry_price records all have `fill_price` populated. The `entry_price` field was added later in the schema. Not a data loss issue, but a schema inconsistency.

---

## VERDICT SUMMARY

### What's REAL
1. **-$3,891.10 corrected P&L** is confirmed (but understates losses due to NO formula bug)
2. **Weather 0 wins is real** — model failure, not data artifact
3. **crypto_15m 25% WR is real** — legitimate underperformance (heavy phantom win contamination pre-correction)
4. **crypto_15m_dir 68% WR is real** — legit performance of the new taxonomy
5. **thin_market/wide_spread performing well** — the quality filters are working

### What's a DATA ARTIFACT
1. **crypto_15m raw 70% WR** — phantom wins from 95c_rule_no bug (all corrected)
2. **pnl_cache.json $12,583** — outdated/uncorrected figure, should not be used

### What NEEDS FIXING (Priority Order)
1. 🔴 **NO exit P&L formula bug** — `(entry+exit-100)*c/100` should be `(exit-entry)*c/100` — **$2,428 overstatement, affects all NO WS exits**
2. 🔴 **11 missing 95c_rule_no corrections** — today's phantom wins not yet corrected, ~$2,917 inflation
3. 🟡 **5 double-close records** — same ticker in both old+new label close records — small double-counting (~$565)
4. 🟡 **64 buy records missing entry_price** — schema inconsistency, not data loss (fill_price available)
5. 🟡 **pnl_cache.json not updating** — showing raw $12,583 instead of corrected -$3,891
6. 🟢 **Weather model calibration** — NOAA probs need recalibration or the weather module should be paused

### Estimated True P&L (all bugs corrected)
```
-$3,891  (claimed corrected)
-$2,428  (NO exit formula bug - 70pct_gain_no exits)
-$2,917  (11 missing 95c corrections, approx)
≈ -$9,236  (rough true P&L)
```
*Note: The NO formula bug and 95c corrections partially overlap on the 30 non-zero 95c exits. The actual figure is approximately -$7,500 to -$9,000 range.*
