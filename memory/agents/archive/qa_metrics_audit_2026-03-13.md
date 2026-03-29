# QA Metrics Audit — Dashboard
**Date:** 2026-03-13  
**Auditor:** SA-4 (QA)  
**Status:** PASS WITH WARNINGS (plus one ❌ accounting bug)

---

## Data Ingested

| File | Contents |
|---|---|
| `logs/demo_deposits.jsonl` | 2 deposits: $200 + $200 = $400 starting capital |
| `logs/pnl_cache.json` | `{"closed_pnl": 87.33}` — bot-only closed P&L |
| `logs/trades_2026-03-10.jsonl` | 16 raw entries (duplicates included) |
| `logs/trades_2026-03-11.jsonl` | 6 opens + 11 exits (8 bot, 3 manual) |

### Unique Bot Trades (after deduplication)
| # | Ticker | Side | Source | Module | Has Exit? | Entry Price |
|---|---|---|---|---|---|---|
| 1 | KXHIGHMIA-26MAR10-B84.5 | NO | bot | weather | No | 5¢ (mp=0.95) |
| 2 | KXHIGHMIA-26MAR11-B83.5 | NO | bot | weather | No | 50¢ (mp=0.50) |
| 3 | KXHIGHMIA-26MAR11-B85.5 | NO | bot | weather | Yes | 67¢ (mp=0.33) |
| 4 | KXHIGHNY-26MAR11-B66.5 | NO | bot | weather | Yes | 69¢ (mp=0.31) |
| 5 | KXHIGHCHI-26MAR11-B52.5 | NO | bot | weather | Yes | 81¢ (mp=0.19) |
| 6 | KXHIGHCHI-26MAR11-B50.5 | NO | bot | weather | Yes | 81¢ (mp=0.19) |
| 7 | KXHIGHCHI-26MAR11-B48.5 | NO | bot | weather | Yes | **81¢** (mp=0.19) ⚠️ |
| 8 | KXETH-26MAR1117-B2030 | NO | bot | crypto | No | 25¢ (mp=0.75) |
| 9 | KXETH-26MAR1117-B2070 | NO | bot | crypto | No | 16¢ (mp=0.84) |
| 10 | KXETH-26MAR1217-B2100 | NO | crypto | crypto | Yes | 21¢ (mp=0.79) |
| 11 | KXXRP-26MAR1217-B1.4099500 | NO | crypto | crypto | Yes | 10¢ (mp=0.90) |
| 12 | KXETH-26MAR1217-B2140 | NO | crypto | crypto | Yes | 11¢ (mp=0.89) |

**Manual trades (excluded from bot P&L):** KXCPI-26JUN, KXCPI-26NOV, KXCPI-26AUG — all exited, total manual P&L = -$6.70.

---

## Account Level Bar

### 1. Account Value
**Formula (frontend `updateAccountValue()`):**
```js
dollar(window._kalshiBalance + window._openPnl + window._closedPnl)
```
- `_kalshiBalance` = `acct.starting_capital` = sum of `demo_deposits.jsonl` = **$400.00** ✅
- `_closedPnl` = `pnl.closed_pnl` = bot-only closed P&L from `/api/pnl` ✅
- `_openPnl` = `botPnl + manPnl` from `loadLivePrices()` ⚠️ (see below)

**Verdict: ⚠️ APPROXIMATE**

Starting capital is correctly sourced from demo_deposits.jsonl ($400). Closed P&L is correctly bot-only. **However**, `window._openPnl` is computed as `botPnl + manPnl` (total open P&L from ALL sources), while `window._closedPnl` is bot-only. This means Account Value includes manual trade unrealized P&L but excludes manual closed P&L. **Currently not visible** because all manual (CPI) positions are exited — `manPnl = $0`. If future manual positions are open, Account Value will be inflated by their unrealized P&L inconsistently.

---

### 2. Open P&L

**Entry price formula** (used in `get_active_positions()`, `get_pnl_history()`, `get_trades()`):
```python
entry_p = int((1 - mp) * 100)   # for NO side
entry_p = int(mp * 100)          # for YES side
```

**Verified consistency:** The same formula is used in all three calculation paths. For all 8 exit records with `entry_price` fields, 7 of 8 match the Python `int()` derivation from `market_prob`. The one exception (KXHIGHCHI-26MAR11-B48.5) is the duplicate-entry bug described in Metric #3 below.

**Current price source (frontend):** Uses `no_bid` (bid price, realizable sale value), falling back to `100 - yes_ask`, then `100 - last_price`. This is the correct mid-to-bid approach for mark-to-market — does NOT use ask price (cost to buy more). ✅

**Currently:** All positions are settled or exited → open_pnl = $0. No live API prices to verify.

**Verdict: ✅ CORRECT** (formula consistent, correct bid-side pricing; current value unavoidably $0 pending live positions)

---

### 3. Closed P&L

**Source:** `pnl_cache.json` → `$87.33`. Written by `/api/pnl` as `closed_by_source['bot']` (bot-only). ✅

**Period selector (frontend `loadClosedPnl()`):**
```js
window._cpnlData = {
    all:   pnl.closed_pnl,            // closed_by_source['bot'] — bot-only ✅
    month: pnl.bot_closed_pnl_month,   // bot-only, exit date in current month ✅
    year:  pnl.bot_closed_pnl_year,    // bot-only, exit date in current year ✅
    day:   pnl.closed_pnl_day,         // ALL sources (not bot-only) ⚠️
}
```

Period selector uses bot-only figures for month/year/all. The `day` bucket uses all-source P&L but "This Day" is not a dashboard option, so no user-facing impact.

**Verification of P&L from exit records:**
| Ticker | ep | xp | ct | Calc | Stated | Match |
|---|---|---|---|---|---|---|
| KXHIGHMIA-26MAR11-B85.5 | 67¢ | 98¢ | 37 | $11.47 | $11.47 | ✅ |
| KXHIGHNY-26MAR11-B66.5 | 69¢ | 98¢ | 36 | $10.44 | $10.44 | ✅ |
| KXHIGHCHI-26MAR11-B52.5 | 81¢ | 98¢ | 30 | $5.10 | $5.10 | ✅ |
| KXHIGHCHI-26MAR11-B50.5 | 81¢ | 98¢ | 30 | $5.10 | $5.10 | ✅ |
| **KXHIGHCHI-26MAR11-B48.5** | **8¢** | **98¢** | **30** | **$27.00** | **$27.00** | **❌ entry_price WRONG** |
| KXETH-26MAR1217-B2100 | 21¢ | 79¢ | 31 | $17.98 | $17.98 | ✅ |
| KXXRP-26MAR1217-B1.4099500 | 10¢ | 79¢ | 27 | $18.63 | $18.63 | ✅ |
| KXETH-26MAR1217-B2140 | 11¢ | 87¢ | 28 | $21.28 | $21.28 | ✅ |

**Sum from exit records: $117.00**  
**4 API-fetched trades (no exit records): $87.33 − $117.00 = −$29.67**

The 4 trades without exit records (KXHIGHMIA-26MAR10-B84.5, KXHIGHMIA-26MAR11-B83.5, KXETH-26MAR1117-B2030, KXETH-26MAR1117-B2070) collectively lost $29.67 per the last Kalshi API fetch. The Miami-26MAR10 trade with 500 contracts at 5¢ entry likely accounts for most of this (potential -$25 loss if YES resolved).

---

### ❌ KXHIGHCHI-26MAR11-B48.5 — Entry Price Bug

**This is the most significant finding in this audit.**

The trade log for `2026-03-10.jsonl` contains **duplicate entries** for this ticker:
- **11:05 AM entry:** `market_prob=0.19` → implied NO price = `int((1-0.19)×100)` = **81¢**
- **23:33 PM duplicate:** `market_prob=0.92` → implied NO price = `int((1-0.92)×100)` = **7-8¢**

The API's deduplication logic (`get_pnl_history()`, `get_trades()`) always picks the **first occurrence** — which is the 11:05 AM entry with `market_prob=0.19`, giving `entry_p = 81¢`.

But the **exit record** has `entry_price = 8` — which corresponds to the **duplicate** 23:33 PM entry (`market_prob=0.92`).

| Source | entry_price | P&L |
|---|---|---|
| First BUY (11:05 AM, mp=0.19) | 81¢ | **(98-81)×30/100 = $5.10** |
| Exit record (using dup entry) | 8¢ | **(98-8)×30/100 = $27.00** |
| **Overstatement** | | **$21.90** |

**Impact on account-level Closed P&L:** `get_pnl_history()` reads `exit_records[ticker].realized_pnl = 27.00` directly, so the $27.00 flows into the account-level bot closed P&L. The correct value should be $5.10 based on the first BUY record. **Account Closed P&L is overstated by ~$21.90 for this trade.**

**Impact on pnl_cache:** $87.33 includes this $21.90 overstatement. Correct bot closed P&L (absent the bug) should be approximately **$65.43**, not $87.33.

**Verdict: ❌ WRONG** — Exit record used wrong (duplicate) opening entry to compute entry_price. Bot closed P&L overstated by ~$21.90. Buying power and Account Value are inflated by the same amount.

---

### 4. Win Rate

**Formula:**
```python
"closed_win_rate": round(bot_wins / closed_count_by_source['bot'] * 100, 1)
```
Where `bot_wins = count of bot trades with pnl > 0`, counting only bot-source closed trades (excludes manual). ✅

From exit records: 8 bot wins out of 8. From API (4 trades): based on $-29.67 total, likely all 4 are losses (KXHIGHMIA-26MAR10 high-probability loss with 500 contracts dominates). Estimated win rate: **8/12 = 66.7%**.

**Formula is correct:** bot-only, `pnl > 0`, properly excludes manual trades.

**Verdict: ✅ CORRECT** (formula logic sound; actual displayed value depends on live Kalshi API results)

---

### 5. Buying Power

**API formula (demo mode):**
```python
buying_power = max(STARTING_CAPITAL + _bot_closed_cached - total_deployed, 0)
              = max($400 + $87.33 - $0, 0) = $487.33
```

**Frontend override:**
```js
const realBuyingPower = (acct.starting_capital || 400) + (window._closedPnl || 0) - (acct.total_deployed || 0);
```
= $400 + $87.33 − $0 = **$487.33**

Frontend does NOT use the API's `buying_power` field — it recomputes independently using `window._closedPnl` (always-fresh from `/api/pnl`). `loadClosedPnl()` runs first in `loadAll()` before `loadAccount()`, so `window._closedPnl` is set before buying power is computed. ✅

`total_deployed` = sum of `size_dollars` for open (non-settled, non-exited) positions. Currently $0 (all positions closed). ✅ Formula only includes open positions.

**Note:** The buying power figure of $487.33 inherits the $21.90 overstatement from the entry_price bug above. Correct buying power should be ~$465.43.

**Verdict: ⚠️ APPROXIMATE** — Formula and sourcing are correct, but inherits the $21.90 entry_price overstatement from Metric #3.

---

## Module Cards

### 6. Module Closed P&L

**How computed:** `get_pnl_history()` calls `get_trades()` to build module P&L. `get_trades()` uses:
- `is_manually_exited AND NOT is_settled` → uses exit record directly
- All other closed trades (settled markets, even with exit records) → **Kalshi API call**

Since ALL our bot trades are settled by now (Mar10/Mar11/Mar12 before today Mar13), **ALL** module closed P&Ls are computed via Kalshi API calls, not exit records. This is **intentionally different** from account-level closed P&L (which uses exit records).

Manual trades are excluded from `get_trades()` output:
```python
_MANUAL_EXCL = ('manual', 'economics', 'geo')
closed = [t for t in closed if t.get('source', 'bot') not in _MANUAL_EXCL]
```
✅ Manual trades correctly excluded.

**Module classification is consistent** between `get_pnl_history()` and the frontend `classifyModule()`:
- All KXHIGH* tickers → weather ✅
- All KXETH* / KXXRP* tickers → crypto ✅
- KXCPI* → fed (excluded as manual) ✅

**Verdict: ⚠️ APPROXIMATE** — Module closed P&L uses Kalshi API settlement values while account-level uses exit records. Expected gap explained in Cross-check #13.

---

### 7. Module Open P&L

Computed via `get_pnl_history()` → `module_open_stats[mod]['open_pnl']`. Uses live Kalshi API prices for open positions (same no_bid/yes_bid logic as account-level Open P&L). Manual trades excluded from the open loop. Currently all positions closed → open_pnl = $0 for all modules.

**Verdict: ✅ CORRECT** (formula matches spec; currently zero because no open positions)

---

### 8. Module Win Rate

```python
wr = round(ms['wins'] / ms['trade_count'] * 100, 1) if ms['trade_count'] > 0 else None
```
Where `ms['wins']` = count of `realized_pnl > 0` from `get_trades()` for that module. Correctly excludes manual. Bot-only.

**Verdict: ✅ CORRECT** (formula matches spec)

---

### 9. Module Open Trades

`module_open_stats[mod]['open_trades']` = count of `open_tickers` for each module. Manual trades excluded. Currently all positions closed → all modules show 0 open trades.

**Verdict: ✅ CORRECT**

---

### 10. Module Total Trades (frontend)

```js
totalTrEl.textContent = (d.trade_count || 0) + (d.open_trades || 0);
```
`trade_count` = closed trades count from `get_trades()`. `open_trades` = open trade count. Total = closed + open. ✅

**Verdict: ✅ CORRECT**

---

### 11. Period Selector (Module Closed P&L)

```js
const pnl = period === 'month' ? d.closed_pnl_month : period === 'year' ? d.closed_pnl_year : d.closed_pnl;
```

Module period buckets are computed using **entry date** (`_date` field from trade log filename):
```python
_date_str = (_ct.get('_date') or _ct.get('date', ''))[:10]
if _rdate.year == _today.year and _rdate.month == _today.month:
    _ms['closed_pnl_month'] += _rpnl
```

Account-level period uses **exit date** (exit record timestamp) or ticker settlement date:
```python
sdate = fromisoformat(exit_records[ticker]['timestamp']).date()  # exit date
```

This is a latent inconsistency: a trade entered in February but exited in March would appear in February's module P&L (entry date) but March's account P&L (exit date). **Currently no impact** because all trades were entered AND exited in March 2026.

**Verdict: ⚠️ APPROXIMATE** — Period selector logic is inconsistent between account-level (exit date) and module-level (entry date). No visible discrepancy now. Bug will surface when trades span month boundaries.

---

## Cross-Checks

### 12. Sum of Module Closed P&Ls = Total Table P&L

By construction in `get_pnl_history()`:
```python
_closed_trades = get_trades()
for _ct in _closed_trades:
    _ms['closed_pnl'] += _ct['realized_pnl']
```

Sum of all modules = sum of all realized_pnl from `get_trades()` = total table P&L. This is an identity — the same dataset, partitioned.

**Verdict: ✅ CORRECT** (mathematical identity; both computed from same `get_trades()` call)

---

### 13. Account Closed P&L ($87.33) vs Sum of Module P&Ls — Gap Analysis

**Two different calculation paths:**

| Path | Method | Affected Trades |
|---|---|---|
| Account-level (`closed_by_source['bot']`) | Exit records where available, else Kalshi API | 8 exit-record trades + 4 API trades |
| Module-level (via `get_trades()`) | Kalshi API for ALL settled trades | 12 API trades |

**Expected gap sources:**
1. For 95¢-rule exits (5 weather trades): exit at ~98¢. If Kalshi settles at 100¢ (NO won completely), module P&L is slightly higher than account P&L by 2¢/contract. Small gap.
2. For 70%-gain exits (3 crypto trades): exited at 79-87¢. Final Kalshi settlement at 100¢ (if NO won) or 0¢ (if NO lost) will be dramatically different from the exit price. **Potentially large gap for these trades.**
3. **KXHIGHCHI-26MAR11-B48.5 entry_price bug:** Account-level uses exit record entry_price=8¢ (overstated). Module-level uses Kalshi API with first-BUY market_prob=0.19 (entry_p=81¢). This alone creates a ~$21.90 gap for this one trade.

**The stated ~$1.96 gap is likely understated.** For the crypto exit trades where final settlement diverges significantly from the 70%-gain exit price, the actual gap between account and module P&L could be $20-$50+.

The comment in `api.py` acknowledges the gap is intentional:
```python
# Note: account-level closed_pnl still comes from pnl_cache / Kalshi settled positions above.
# A small gap between the two is expected and acceptable.
```

**Verdict: ⚠️ APPROXIMATE** — Gap is explained structurally but is potentially much larger than $1.96. The entry_price bug in #3 contributes ~$21.90 to the account-level overstatement, making the gap harder to reason about.

---

### 14. Win Rate: Account Bar vs Module Cards

**Account win rate:** computed in `get_pnl_history()` from `exit_records` pnl values (for settled trades with exits, uses exit record P&L → all 8 are wins).

**Module win rates:** computed from `get_trades()` → Kalshi API settlement result. A trade that was exited at a profit (e.g., 70% gain exit) may show as a larger profit OR a loss in the module calculation depending on final Kalshi settlement vs exit price.

For weather trades (95¢ rule exits): if final settlement is same direction as the exit, win count matches. 
For crypto trades (70% gain exits at 79-87¢): if the market subsequently reversed after our exit, Kalshi API could show a loss even though we profited at exit. The win counts could diverge.

**Currently:** All 8 bot exit records show pnl > 0 (all wins). The 4 API-fetched trades without exits are likely all losses. So account win rate ≈ 8/12 = 66.7%.

Module win rates depend on live Kalshi API data — could differ from account win rate.

**Verdict: ⚠️ APPROXIMATE** — Win rate calculation formula is correct in isolation, but the two sources (exit records vs Kalshi API) can give different win/loss determinations for the same trade.

---

## Summary Table

| # | Metric | Verdict | Notes |
|---|---|---|---|
| 1 | Account Value | ⚠️ APPROXIMATE | Open P&L includes manual trades; currently zero impact |
| 2 | Open P&L | ✅ CORRECT | Consistent formula; correct bid-side pricing |
| 3 | Closed P&L (pnl_cache) | ❌ WRONG | **$21.90 overstatement** — KXHIGHCHI-26MAR11-B48.5 exit record uses wrong entry_price (8¢ from duplicate entry vs correct 81¢ from first BUY) |
| 4 | Win Rate | ✅ CORRECT | Formula correct; bot-only, pnl>0; actual displayed value depends on Kalshi API |
| 5 | Buying Power | ⚠️ APPROXIMATE | Formula correct; inherits $21.90 overstatement from Metric #3 |
| 6 | Module Closed P&L | ⚠️ APPROXIMATE | Uses Kalshi API for all settled trades (not exit records); intentional design |
| 7 | Module Open P&L | ✅ CORRECT | Formula correct; currently $0 (no open positions) |
| 8 | Module Win Rate | ✅ CORRECT | Formula correct; may diverge from account-level due to different P&L source |
| 9 | Module Open Trades | ✅ CORRECT | Correct count; currently 0 |
| 10 | Module Total Trades | ✅ CORRECT | closed + open by construction |
| 11 | Period Selector (modules) | ⚠️ APPROXIMATE | Uses entry date; account-level uses exit date — latent cross-month bug |
| 12 | Sum module P&Ls = table P&L | ✅ CORRECT | Mathematical identity by construction |
| 13 | Account vs module P&L gap | ⚠️ APPROXIMATE | Gap explained; but likely ~$21.90+ not ~$1.96 |
| 14 | Account win rate vs modules | ⚠️ APPROXIMATE | Both correct by formula; diverge when exit price ≠ settlement price |

---

## Issues Requiring Fix

### ❌ CRITICAL: KXHIGHCHI-26MAR11-B48.5 Exit Record entry_price Wrong

**File:** `logs/trades_2026-03-11.jsonl`  
**Root cause:** The position monitor wrote `entry_price=8` into the exit record, corresponding to the **duplicate** buy entry at 23:33 PM (`market_prob=0.92`, NO costs ~8¢). The deduplication logic in `get_pnl_history()` picks the **first** BUY record at 11:05 AM (`market_prob=0.19`, NO costs 81¢). These are inconsistent.

**Effect:** Bot closed P&L overstated by **$21.90** ($27.00 recorded vs correct $5.10). Propagates to pnl_cache, Buying Power, and Account Value.

**Fix options:**
1. The position monitor should resolve entry_price at time of position opening, using the SAME deduplication logic (first BUY per ticker). It currently appears to have used the last/most-recent entry instead.
2. Alternatively, remove or consolidate the duplicate buy entries in the trade log.
3. In `get_pnl_history()`, when a trade is in exit_records, use the `realized_pnl` from the exit record only if it was computed with the same entry_price that the API would derive from market_prob. Add a cross-check.

---

## Warnings (Discretionary)

### ⚠️ W1: Account Value Open P&L Scope Mismatch
`window._openPnl` = all open P&L (bot + manual). `window._closedPnl` = bot-only. Inconsistency will inflate Account Value if manual positions are open. Currently harmless. Fix: use `botPnl` not `totalPnl` for `window._openPnl`.

### ⚠️ W2: Period Bucket Date Inconsistency
Account-level period uses exit date. Module-level period uses entry date (`_date` filename). Will bucket the same trade differently if entry and exit span a month boundary. Fix: use consistent date source in both paths.

### ⚠️ W3: pnl_cache Staleness Risk
`get_account()` reads pnl_cache from disk (possibly stale). Frontend independently calls `/api/pnl` for buying power. A startup race condition (if pnl_cache hasn't been written yet) would show $0 closed P&L in buying power from API but correct value from frontend. Low risk in practice (auto-refresh runs quickly), but worth noting.

### ⚠️ W4: ~$1.96 Gap Comment Misleading
The comment in `api.py` says "expect a small gap (~$1.96) due to Kalshi API vs trade log difference." This underestimates the potential gap. For 70%-gain exits, the exit price (79-87¢) can differ dramatically from final settlement (0¢ or 100¢). The actual gap can be $20-$50+, depending on final Kalshi results. Update the comment to say "small to moderate gap" with a better explanation.

### ⚠️ W5: Duplicate Buy Entries in Trade Logs
`trades_2026-03-10.jsonl` contains multiple entries for the same tickers (including 3 separate sets of entries for KXHIGHMIA-26MAR11-B83.5 and KXHIGHCHI-26MAR11-B48.5 at different timestamps). The dedup logic handles this, but it's a log hygiene issue that enabled the entry_price bug above. The position monitor / bot should ideally not re-log tickers it has already logged.

---

## Appendix: Raw Calculation Verification

```
demo_deposits.jsonl → STARTING_CAPITAL:
  $200 (Weather, 2026-03-10) + $200 (Crypto, 2026-03-10) = $400.00 ✅

Exit record math (all pass Python int() check):
  KXHIGHMIA-26MAR11-B85.5: (98-67)×37/100 = $11.47 ✅
  KXHIGHNY-26MAR11-B66.5:  (98-69)×36/100 = $10.44 ✅
  KXHIGHCHI-26MAR11-B52.5: (98-81)×30/100 = $5.10  ✅
  KXHIGHCHI-26MAR11-B50.5: (98-81)×30/100 = $5.10  ✅
  KXHIGHCHI-26MAR11-B48.5: (98-8)×30/100  = $27.00 ❌ (entry_price=8 is wrong)
  KXETH-26MAR1217-B2100:   (79-21)×31/100 = $17.98 ✅
  KXXRP-26MAR1217-B1.4099500: (79-10)×27/100 = $18.63 ✅
  KXETH-26MAR1217-B2140:   (87-11)×28/100 = $21.28 ✅

  Sum exit-record bot P&L: $117.00
  pnl_cache total: $87.33
  Implied API-fetched P&L (4 trades): -$29.67

Manual exit math (all correct, all excluded from bot P&L):
  KXCPI-26AUG-T0.3:  (24-33)×38/100 = -$3.42 ✅
  KXCPI-26NOV-T0.3:  (29-37)×17/100 = -$1.36 ✅
  KXCPI-26JUN-T0.0:  (71-77)×32/100 = -$1.92 ✅
  Manual total: -$6.70

Buying power: $400 + $87.33 - $0 deployed = $487.33
  (inflated by ~$21.90 due to entry_price bug)
```
