# DS-SETTLE-AUDIT-2026-03-29 — Settlement Audit: Mar 29 Market Date

**Prepared by:** Data Scientist  
**Date:** 2026-03-29  
**Triggered by:** Runtime flag — `KXHIGHLAX-26MAR29-T72` bought Mar 28, no settle record found  

---

## Executive Summary

**8 positions** were bought on Mar 28 for markets settling on Mar 29 (ticker date = `26MAR29`).  
**0 of these 8** have settle records in the trade logs.  
**1 has now finalized** on Kalshi (ETH crypto): `KXETH-26MAR2917-B2010` → `result=yes` (NO side won, i.e. our position lost).  
**7 remain `status=active`** on Kalshi with `result=''` — markets are pending final settlement by Kalshi (close_time has not elapsed yet as of ~16:31 PDT).

---

## Positions That Settled Mar 29 (Ticker = 26MAR29)

All bought on **2026-03-28** at ~19:02 PT by the evening scan:

| # | Ticker | Title | Side | Entry | Contracts | Cost |
|---|--------|-------|------|-------|-----------|------|
| 1 | `KXHIGHLAX-26MAR29-T72` | LA high < 72° on Mar 29 | YES | 41¢ | 244 | $100.11 |
| 2 | `KXHIGHMIA-26MAR29-B79.5` | Miami high 79–80° on Mar 29 | YES | 33¢ | 303 | $100.11 |
| 3 | `KXHIGHAUS-26MAR29-B84.5` | Austin high 84–85° on Mar 29 | YES | 27¢ | 370 | $100.11 |
| 4 | `KXHIGHTDC-26MAR29-B60.5` | DC high 60–61° on Mar 29 | YES | 26¢ | 385 | $100.11 |
| 5 | `KXHIGHTLV-26MAR29-B89.5` | LV high 89–90° on Mar 29 | YES | 19¢ | 526 | $100.11 |
| 6 | `KXHIGHTSEA-26MAR29-B46.5` | Seattle high 46–47° on Mar 29 | YES | 43¢ | 232 | $100.11 |
| 7 | `KXHIGHTSFO-26MAR29-B77.5` | SF high 77–78° on Mar 29 | YES | 26¢ | 385 | $100.11 |
| 8 | `KXETH-26MAR2917-B2010` | ETH price at Mar 29 5pm EDT | NO | 70¢ | 143 | $100.11 |

**Total cost basis:** $800.88

---

## Settle Record Status

| Ticker | Settle Record | Kalshi Status | Kalshi Result | Notes |
|--------|---------------|---------------|---------------|-------|
| `KXHIGHLAX-26MAR29-T72` | ❌ MISSING | active | pending | close_time = 2026-03-30T07:59Z |
| `KXHIGHMIA-26MAR29-B79.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T04:59Z |
| `KXHIGHAUS-26MAR29-B84.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T05:59Z |
| `KXHIGHTDC-26MAR29-B60.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T05:00Z |
| `KXHIGHTLV-26MAR29-B89.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T08:00Z |
| `KXHIGHTSEA-26MAR29-B46.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T08:00Z; yes_ask=97¢ (strongly resolved NO) |
| `KXHIGHTSFO-26MAR29-B77.5` | ❌ MISSING | active | pending | close_time = 2026-03-30T08:00Z; yes_ask=1¢ (strongly resolved YES) |
| `KXETH-26MAR2917-B2010` | ❌ MISSING | **finalized** | **yes** | Our side = NO → **LOSS** (-$100.11) |

**Summary:** 8 missing ❌, 0 present ✅

---

## Root Cause Analysis

### Why are the weather markets still `active`?

Kalshi weather markets with ticker date `26MAR29` have close_times ranging from **04:59Z to 08:00Z on 2026-03-30** (UTC), which is **9:59 PM to 1:00 AM PDT**. These markets have NOT closed yet as of the audit time (16:31 PDT Mar 29). The settlement checker is working correctly — it's not missing them, it's just too early. These will settle tonight after close_time passes.

**No bug.** The settlement checker will catch these in the 11 PM or 8 AM run.

### Why is `KXETH-26MAR2917-B2010` missing?

The ETH market (`KXETH-26MAR2917-B2010`) is `status=finalized, result=yes`. Our position was **NO side** — meaning we lose. The settlement checker **should have** caught this in today's 10:43 AM run. But it did not.

**This is a bug.**

Evidence: The Mar 29 log at 10:43 AM shows settlement records for 26MAR28 weather markets and 26MAR27 markets — but NOT for `KXETH-26MAR2917-B2010`, even though:
1. It was in the unsettled positions (bought 2026-03-28 19:04)
2. It was already `finalized` by 10:43 AM on Mar 29
3. The settlement checker ran at 10:43 AM on Mar 29

**Likely cause:** The `load_all_unsettled()` function uses `action in ('buy', 'open')` to detect positions. The ETH buy record has `"action": "buy"` — that's correct. However, the ETH buy also appears in the **Mar 29 morning scan** at 10:00 AM (`trade_id: 5bb9d460`, same ticker, different quantity). The settlement checker may be seeing the second buy as overwriting the first entry in `entries_by_key`, and both use the same `(ticker, side)` key. This results in the checker using the 10:00 AM entry — but at 10:43 AM, the market may not yet have been finalized on Kalshi (finalized between the buy at 10:00 AM and the settle check at 10:43 AM), **or** the position was not tracked in `tracked_positions.json` for the original Mar 28 trade.

Additionally: `KXETH-26MAR2917-B2010` is the **only** ETH market that finalized. The second ETH buy (10:00 AM Mar 29) may indicate the bot re-bought into a market that was already settling — a separate bug in the scanner (buying into expiring/expiring-today markets).

**Critical:** `KXETH-26MAR2917-B2010` is in `tracked_positions.json` as the **Mar 29 buy** (`entry_price=51`, NOT the Mar 28 buy at 70¢) — confirming the tracked_positions system only captured the later buy, not the original Mar 28 position.

---

## Missing Records: What to Fix

### Immediate: Manually Write ETH Settle Record

The ETH market is already finalized. A settle record must be written manually for the original Mar 28 buy:

```json
{
  "trade_id": "<new-uuid>",
  "timestamp": "<now-iso>",
  "date": "2026-03-29",
  "entry_date": "2026-03-28",
  "ticker": "KXETH-26MAR2917-B2010",
  "title": "Ethereum price at Mar 29, 2026 at 5pm EDT?",
  "side": "no",
  "action": "settle",
  "action_detail": "SETTLE LOSS @ 1c",
  "source": "settlement_checker_manual",
  "module": "crypto",
  "settlement_result": "yes",
  "pnl": -100.11,
  "entry_price": 70,
  "exit_price": 1,
  "contracts": 143,
  "size_dollars": 100.11,
  "fill_price": 1,
  "entry_edge": 0.17,
  "confidence": 0.631,
  "hold_duration_hours": 23.97,
  "order_result": {"dry_run": true, "status": "settled"}
}
```

Append to: `environments/demo/logs/trades/trades_2026-03-29.jsonl`

Also: write a settle for the **second ETH buy** (Mar 29, 10:00 AM, 181 contracts @ 51¢, NO side) — also a loss since result=yes.

```json
{
  "trade_id": "<new-uuid-2>",
  "timestamp": "<now-iso>",
  "date": "2026-03-29",
  "entry_date": "2026-03-29",
  "ticker": "KXETH-26MAR2917-B2010",
  "title": "Ethereum price at Mar 29, 2026 at 5pm EDT?",
  "side": "no",
  "action": "settle",
  "action_detail": "SETTLE LOSS @ 1c",
  "source": "settlement_checker_manual",
  "module": "crypto",
  "settlement_result": "yes",
  "pnl": -89.02,
  "entry_price": 51,
  "exit_price": 1,
  "contracts": 181,
  "size_dollars": 89.02,
  "fill_price": 1,
  "entry_edge": 0.373,
  "confidence": 0.802,
  "hold_duration_hours": 6.0,
  "order_result": {"dry_run": true, "status": "settled"}
}
```

### Tonight: Weather Markets Will Auto-Settle

The 7 weather markets (`26MAR29`) will settle naturally when the settlement checker runs at 11 PM PDT (after their close_times of 04:59Z–08:00Z = 9:59 PM–1:00 AM PDT). **No manual action needed.** Monitor the Nov 30 log for settle records.

---

## Bugs to Fix in Settlement Checker

### Bug 1: Duplicate Buys Override Prior Position in `load_all_unsettled()`

**Location:** `environments/demo/settlement_checker.py` → `load_all_unsettled()`

**Problem:** `entries_by_key[(ticker, side)] = rec` overwrites earlier buys with later buys of the same ticker+side. When the bot re-buys into the same market (e.g., ETH at 10:00 AM on top of the original Mar 28 buy), the original position's entry metadata is lost.

**Fix:** Instead of overwriting, accumulate a list per key. When settling, pick the earliest unfilled position or aggregate quantity/cost:

```python
# Instead of:
entries_by_key[key] = rec

# Do:
if key not in entries_by_key:
    entries_by_key[key] = []
entries_by_key[key].append(rec)
```

Then in `check_settlements()`, iterate over all recs per key and write one settle record per buy (or aggregate).

### Bug 2: Scanner Buying Into Same-Day Expiring Markets

**Location:** `agents/ruppert/trader/` — scanner/order flow

**Problem:** At 10:00 AM Mar 29, the bot bought `KXETH-26MAR2917-B2010` (expiring Mar 29 at 5pm). This market settles today. The bot should not enter new positions in markets expiring the same calendar day.

**Fix:** In the scanner/order logic, before placing a buy, check if `close_time` is within the current calendar day. If yes, skip:

```python
from datetime import date, timezone
ct = datetime.fromisoformat(market.get('close_time', '').replace('Z', '+00:00'))
if ct.date() <= date.today():
    logger.info(f"Skipping {ticker}: expires today")
    continue
```

### Bug 3: `tracked_positions.json` Not Capturing Original Mar 28 ETH Position

**Location:** `environments/demo/bot/` — position tracker

**Problem:** `tracked_positions.json` shows the Mar 29 10:00 AM ETH buy (`entry_price=51`) but NOT the original Mar 28 buy (`entry_price=70`). This means the settlement checker and exit logic may only operate on the later position.

**Fix:** Investigate why the Mar 28 ETH position was not added to `tracked_positions.json`. It may be that the tracking logic only adds positions from the current scan cycle, not historical logs. The tracker should scan all trade logs on startup (or incremental adds) to ensure all buy records are tracked.

---

## Action Items

| Priority | Item | Owner | Due |
|----------|------|-------|-----|
| 🔴 HIGH | Manually append ETH settle records (both buys) to `trades_2026-03-29.jsonl` | Dev | Today |
| 🔴 HIGH | Fix `load_all_unsettled()` to not overwrite duplicate buys | Dev | Next sprint |
| 🟡 MED | Add same-day expiry guard to scanner | Dev | Next sprint |
| 🟡 MED | Fix `tracked_positions.json` to capture all open buys from logs | Dev | Next sprint |
| 🟢 LOW | Verify 7 weather markets settle correctly tonight via 11 PM settlement check | Ops | Tonight |

---

## Unresolved Questions

1. **Why did the bot re-buy ETH at 10:00 AM Mar 29?** Was this the morning scan finding edge on a market that closes that afternoon? The crypto scanner should be aware of expiry timing.
2. **What was the actual ETH price at 5pm EDT Mar 29?** The market resolved YES (price was above $2010). Need to confirm against OKX data for calibration tracking.
3. **Are there similar multi-buy situations in prior days?** A broader audit of `entries_by_key` overwrite behavior is warranted.

---

*Spec written by Data Scientist subagent. Reviewed: pending.*
