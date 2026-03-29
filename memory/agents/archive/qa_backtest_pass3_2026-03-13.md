# QA Pass 3 Report — Backtest Engine Final Gate
**SA-4 QA | 2026-03-13 | Session: qa-backtest-p3**
**Overall Verdict: ⚠️ NEEDS MORE FIXES — CRITICAL DATA BUG**

---

## CHECK 1: Format Fixes — ✅ PASS

All three format fixes from previous QA passes were confirmed in code:

| Fix | File | Status |
|-----|------|--------|
| `last_price >= 0.50` (not 50) in `compute_pnl()` | `strategy_simulator.py` | ✅ Confirmed |
| `yes_ask * 100.0` for `entry_cents` (not raw) | `strategy_simulator.py` + `backtest_engine.py` | ✅ Confirmed |
| Status filter accepts `'settled'` AND `'finalized'` | `backtest_engine.py` | ✅ Confirmed |
| `ast.parse()` both files | Both | ✅ No syntax errors |

---

## CHECK 2: End-to-End Sanity Run — ⚠️ WARNING

**Command run:**
```
python backtest.py --start 2026-03-10 --end 2026-03-13
```

**Result:** Backtest completed, returncode=0. 17 trades produced.

**Minor issue (non-blocking):** Unicode encoding error when running on Windows without `PYTHONIOENCODING=utf-8`. The `→` character in `backtest.py` line:
```python
print(f"[backtest] Period    : {args.start} → {args.end}")
```
…crashes on Windows default cp1252 encoding. Workaround: set `PYTHONIOENCODING=utf-8` in environment. **Fix needed** to either replace `→` with `->` or add `sys.stdout.reconfigure(encoding='utf-8')` at startup.

**17 trades produced (not 0)** — pipeline is reaching market data and generating trades. However, a critical data bug (see CHECK 3) makes the P&L results meaningless.

---

## CHECK 3: P&L Sanity Check — ❌ FAIL (CRITICAL DATA BUG)

**Reported results:**
```
Total P&L  : $-84.41
Win rate   : 0.0%
Trades     : 17
Capital    : $400.00 → $315.59
```

**FAIL: Win rate 0.0%** — outside acceptable range (20%–80%).

**Root Cause: `yes_ask = 1.0` in ALL settled market data**

Every record in `kalshi_settled_weather.json` and `kalshi_settled_crypto.json` has `yes_ask: 1.0`. Example:
```json
{"ticker": "KXHIGHNY-26MAR12-T64", "status": "finalized", "yes_ask": 1.0, "last_price": 0.99}
{"ticker": "KXBTC-26MAR1321-T78999.99", "status": "finalized", "yes_ask": 1.0, "last_price": 0.0}
```

This is the **post-settlement asking price** (after market resolves, the ask is always 1.0). The data fetcher stored the market's post-settlement state, **not the pre-settlement trading price**.

**Consequence of this bug:**
- Every trade enters at `entry_price_cents = 100¢` ($1.00 per contract)
- If YES wins: profit = contracts × ($1.00 - $1.00) = **$0**
- If NO wins: loss = full position size
- Result: every "win" nets $0, every loss nets -$N → **0% profitable win rate is guaranteed**

**This makes every P&L number in this backtest numerically invalid.**

**Required fix (SA-3 Developer):** The data fetcher must capture and store the pre-settlement `yes_ask` price — what the market was trading at *before* expiry (e.g., 12–48 hours prior), not the post-settlement clearing price. This likely requires either:
1. Pulling historical order book/OHLC data from Kalshi's market history API, OR
2. Storing market snapshots at regular intervals during live operation and using those for backtest replay

**Secondary note:** `last_price` (0.01, 0.99, 0.0) correctly reflects settlement outcome — that field is fine.

---

## CHECK 4: Results File Written — ⚠️ WARNING

**File written:** `results/20260313_185220_report.txt` + `.json` ✅

**Field presence in JSON:**

| Required Field | Present | Location |
|----------------|---------|----------|
| `total_pnl` | ✅ | `data['summary']['total_pnl']` = -84.41 |
| `win_rate` | ✅ | `data['summary']['win_rate']` = 0.0 |
| `total_trades` | ✅ | `data['summary']['total_trades']` = 17 |
| `capital_curve` | ✅ | `data['capital_curve']` (4 items) |

**Warning:** `total_pnl`, `win_rate`, and `total_trades` are nested under `data['summary']`, not at the root level of the JSON. `capital_curve` is at root. If downstream optimizer reads these fields with `results['total_pnl']` it will get a KeyError. Recommend flattening or documenting the schema consistently.

---

## Summary

| Check | Status |
|-------|--------|
| CHECK 1: Format fixes | ✅ PASS |
| CHECK 2: End-to-end run | ⚠️ WARNING (Unicode issue) |
| CHECK 3: P&L sanity | ❌ FAIL — 0% win rate, data bug |
| CHECK 4: Results file | ⚠️ WARNING (fields nested in summary) |

## Overall: ❌ NEEDS MORE FIXES

**BLOCKING issue — must fix before optimizer:**
- `yes_ask = 1.0` in all stored market data. The data fetcher needs to store pre-settlement prices, not post-settlement. Without real pre-settlement prices, the backtest P&L, win rate, and capital curve are all meaningless.

**Non-blocking (fix in same batch):**
- Replace `→` with `->` (or set UTF-8 encoding) in `backtest.py` to avoid Windows crash
- Flatten `total_pnl`/`win_rate`/`total_trades` to JSON root or ensure optimizer reads from `['summary']`

**Sending back to SA-3 Developer** for data fetcher fix. QA Pass 4 required after fix.

---
*Written by SA-4 QA | 2026-03-13*
