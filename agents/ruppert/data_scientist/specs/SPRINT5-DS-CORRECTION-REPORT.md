# SPRINT5 DS Correction Report: ISSUE-042 Part B
**Date:** 2026-04-03  
**Task:** NO-side Entry Price Flip P&L Correction  
**Executed by:** Data Scientist subagent (DS-Sprint5-PartB)

---

## Summary

Inserted `exit_correction` records into trade logs for all NO-side trades affected by the ISSUE-042 entry price flip bug. All 125 confirmed-affected trades were corrected with a total P&L delta of **+$8,060.37**.

---

## Correction Records Inserted

| Metric | Value |
|---|---|
| Total records inserted | **125** |
| Records in `trades_2026-04-02.jsonl` | 88 |
| Records in `trades_2026-04-03.jsonl` | 37 |
| Total P&L correction applied | **+$8,060.37** |
| Source tag | `ds_no_side_audit_2026-04-03` |

---

## Capital Before & After

| Metric | Value |
|---|---|
| Pre-correction capital | $2,767.69 |
| Post-correction capital | **$10,828.06** |
| Increase | +$8,060.37 |

---

## Reconciliation to Expected $21,009.61

**Post-correction capital does NOT reconcile to ~$21,009.61.** The difference is **-$10,181.55**.

### Root Cause Analysis

The audit document's expected capital of ~$21,009.61 was computed incorrectly:
- The audit referenced `~$13,146` as the current capital (from `MEMORY.md` EOD figure dated **2026-03-31**)
- However, the **actual** capital baseline on 2026-04-02 is **$10,000** (fresh deposit — clean slate after data cleanup on Apr 2)
- The March 31 figure was from a different capital context and is no longer relevant

**Actual reconciliation breakdown:**

| Component | Amount |
|---|---|
| Deposits (Apr 2 fresh start) | +$10,000.00 |
| Exit P&L (all exits, Apr 2–3) | +$4,644.55 |
| Settle P&L (daily modules, Apr 2–3) | −$11,876.86 |
| Correction P&L (125 exit_correction records) | +$8,060.37 |
| **Total Capital** | **$10,828.06** |

The settle P&L of −$11,876.86 represents heavy losses in the daily band/threshold modules (crypto_threshold_daily_*, crypto_band_daily_*). These are legitimate losses — not a bug — but are why capital is much lower than the March 31 estimate.

---

## Anomalies Found

### 1. Audit Count Discrepancy (115 vs 125)
The audit document identified 115 affected trades. I found **125** confirmed-affected trades (where exit record `entry_price` = `100 - actual_ep`, confirming the flip was applied). The additional 10 trades are Apr 3 trades that were completed **after the audit was written** (trades between 09:02–10:32 on Apr 3). All 125 were legitimately affected and have been corrected.

### 2. Duplicate Buy Records
Two tickers had 2 identical buy records each:
- `KXDOGE15M-26APR030530-30` (identical: ep=36, 121 contracts, Apr 3)
- `KXXRP15M-26APR030630-30` (identical: ep=44, 92 contracts, Apr 3)

Each was counted once (1 exit → 1 correction). The duplicate buy records themselves are a pre-existing data quality issue — **not addressed here**. This should be flagged as a separate investigation (ISSUE-043 or equivalent).

### 3. Duplicate Settle Records
The capital audit tool flagged **17 (ticker, side) pairs** with duplicate settle records, contributing approximately **−$737.15** in double-counted losses. This is a pre-existing issue separate from ISSUE-042. Key duplicates:
- Multiple BTC/ETH daily band tickers from Apr 3–4 show identical settle records
- This explains additional ~$737 gap below expected capital

This should be filed as a separate issue.

### 4. Expected Capital Calculation Was Stale
The audit document's target of `~$21,009.61` was based on `$13,146 + $7,864 = $21,009.61`, but:
- `$13,146` was a stale March 31 capital figure
- The actual fresh-start deposit on Apr 2 was $10,000
- The correct expected post-correction capital, given the actual trade data, is **~$10,828.06**

---

## Actions Taken

1. ✅ Read `memory/agents/ds-no-side-audit-2026-04-03.md`
2. ✅ Identified 125 confirmed-affected trades from trade logs
3. ✅ Inserted 125 `exit_correction` records (88 in Apr 2 file, 37 in Apr 3 file)
4. ✅ Called `circuit_breaker.update_global_state(capital)` — CB state refreshed to $10,828.06
5. ✅ Ran full DS capital audit via `ds_capital_audit.py`
6. ✅ Did **NOT** add any records to `demo_deposits.jsonl`

---

## Recommended Follow-up Issues

| Issue | Description | Priority |
|---|---|---|
| ISSUE-043 | Duplicate buy records for KXDOGE15M and KXXRP Apr 3 | Low |
| ISSUE-044 | Duplicate settle records (17 tickers, ~−$737 double-counted) | Medium |
| ISSUE-042-C | Audit expected capital ($21,009.61) was based on stale baseline — update MEMORY.md | Low |
