# Dev Tasks — 2026-03-28d
_Issued by CEO. Build the Data Agent. This runs after every scan cycle and on startup. Zero bad data tolerance — we are in critical DEMO data-gathering phase._

---

## Overview

New file: `data_agent.py`

Runs automatically:
1. **After every full/crypto/weather scan** — hooked as last step in `ruppert_cycle.py`
2. **Once per day at startup** — full historical audit from 2026-03-26 forward
3. **Manually** — `python data_agent.py --full` / `--today` / `--details`

Pings David via `send_telegram()` immediately on any finding. Cleans up what it can automatically.

---

## Check Tiers

### 🔴 Critical — Run after EVERY cycle

**1. Duplicate trade IDs**
```python
def check_duplicate_trade_ids(trades: list) -> list[str]:
    seen = set()
    dupes = []
    for t in trades:
        tid = t.get('trade_id') or t.get('id')
        if tid in seen:
            dupes.append(tid)
        seen.add(tid)
    return dupes
```
**Cleanup:** Delete the duplicate entry (keep first occurrence). Log deletion.

**2. Missing required fields**
Required: `ticker`, `side`, `size_dollars`, `entry_price`, `confidence`, `edge`, `module`, `ts`
```python
REQUIRED_FIELDS = ['ticker', 'side', 'size_dollars', 'entry_price', 'module', 'ts']
def check_missing_fields(trade: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not trade.get(f)]
```
**Cleanup:** Add `_invalid: true` and `_invalid_reason: "missing: [fields]"` to the record. Do NOT delete.

**3. Dry run mismatch** (DEMO critical)
```python
def check_dry_run_mismatch(trade: dict) -> bool:
    # If trade has order_id that looks real (not 'simulated') in DEMO mode
    order = trade.get('order_result', {})
    if isinstance(order, dict):
        status = order.get('status', '')
        return status not in ('simulated', 'dry_run', '') and not order.get('dry_run')
    return False
```
**Cleanup:** Mark `_invalid: true`, `_invalid_reason: "live_order_in_demo"`. Alert David immediately.

**4. Module/ticker mismatch**
```python
TICKER_MODULE_MAP = {
    'KXHIGHT': 'weather', 'KXHIGHNY': 'weather', 'KXHIGHMI': 'weather',
    'KXHIGHCH': 'weather', 'KXHIGHDE': 'weather', 'KXHIGHLAX': 'weather',
    'KXHIGHAUS': 'weather', 'KXHIGHSE': 'weather', 'KXHIGHSF': 'weather',
    'KXHIGHPH': 'weather', 'KXHIGHLV': 'weather', 'KXHIGHSA': 'weather',
    'KXHIGHMIA': 'weather', 'KXHIGHAT': 'weather',
    'KXBTC': 'crypto', 'KXETH': 'crypto', 'KXXRP': 'crypto',
    'KXDOGE': 'crypto', 'KXSOL': 'crypto',
    'KXBTC15M': 'crypto_15m', 'KXETH15M': 'crypto_15m',
    'KXXRP15M': 'crypto_15m', 'KXDOGE15M': 'crypto_15m',
    'KXCPI': 'econ', 'KXPCE': 'econ', 'KXJOBS': 'econ',
    'KXFED': 'fed', 'KXFOMC': 'fed',
    'KXBTCMAX': 'crypto_long', 'KXBTCMIN': 'crypto_long',
    'KXETHMAXM': 'crypto_long', 'KXETHMINY': 'crypto_long',
}

def check_module_mismatch(trade: dict) -> tuple[bool, str | None]:
    ticker = trade.get('ticker', '').upper()
    recorded_module = trade.get('module', '')
    for prefix, expected_module in TICKER_MODULE_MAP.items():
        if ticker.startswith(prefix):
            if recorded_module != expected_module:
                return True, expected_module
    return False, None
```
**Cleanup:** AUTO-FIX — update `module` field to correct value. Log the correction.

**5. Position tracker drift**
```python
def check_tracker_drift(trades: list, tracked: dict) -> dict:
    # Positions in tracker but no matching open trade
    trade_tickers = {t['ticker'] for t in trades if t.get('action') != 'exit'}
    orphan_tickers = set(tracked.keys()) - trade_tickers
    # Open trades not in tracker
    missing_tickers = trade_tickers - set(tracked.keys())
    return {'orphans': list(orphan_tickers), 'missing': list(missing_tickers)}
```
**Cleanup:** Remove orphan entries from tracker. Log missing positions (don't auto-add — requires entry_price context).

---

### 🟡 Important — Run after FULL cycles only

**6. Entry price outside spread**
```python
def check_entry_price_spread(trade: dict) -> bool:
    ep = trade.get('entry_price', 0)  # in cents
    yes_ask = trade.get('yes_ask') or trade.get('market_ask')
    yes_bid = trade.get('yes_bid') or trade.get('market_bid')
    if yes_ask and yes_bid:
        # Allow 2c slippage tolerance
        return not (yes_bid - 2 <= ep <= yes_ask + 2)
    return False
```
**Cleanup:** Flag only — add `_price_anomaly: true`. Do NOT modify entry price.

**7. Daily cap violations**
Check sum of `size_dollars` per module per day doesn't exceed configured cap.
```python
def check_daily_cap_violations(trades_today: list) -> list[dict]:
    from config import WEATHER_DAILY_CAP_PCT, CRYPTO_DAILY_CAP_PCT, get_capital
    caps = {
        'weather': get_capital() * WEATHER_DAILY_CAP_PCT,
        'crypto': get_capital() * CRYPTO_DAILY_CAP_PCT,
        'econ': get_capital() * getattr(config, 'ECON_DAILY_CAP_PCT', 0.04) * get_capital(),
        'fed': get_capital() * getattr(config, 'FED_DAILY_CAP_PCT', 0.04) * get_capital(),
    }
    violations = []
    by_module = {}
    for t in trades_today:
        m = t.get('module', 'unknown')
        by_module[m] = by_module.get(m, 0) + t.get('size_dollars', 0)
    for module, total in by_module.items():
        cap = caps.get(module)
        if cap and total > cap * 1.05:  # 5% tolerance for rounding
            violations.append({'module': module, 'total': total, 'cap': cap})
    return violations
```
**Cleanup:** Mark violating trades with `_cap_violation: true`. Alert David.

**8. Dashboard P&L consistency**
```python
def check_pnl_consistency() -> tuple[bool, float, float]:
    # Compare pnl_cache.json vs computed from trade logs
    import json
    from pathlib import Path
    cached = json.loads(Path('logs/pnl_cache.json').read_text()).get('closed_pnl', 0)
    computed = compute_pnl_from_logs()  # sum entry/exit pairs
    delta = abs(cached - computed)
    return delta > 0.10, cached, computed  # >10c discrepancy = problem
```
**Cleanup:** If mismatch, regenerate `pnl_cache.json` from trade logs. Log the correction.

**9. Decision log orphans** (decision logged, no trade)
Only flag — don't clean. Decision logs are valuable even for blocked trades.
Add `_no_matching_trade: true` annotation for post-analysis.

---

### 🟢 Periodic — Daily at 7AM (historical audit)

**10. WS cache stale trades**
Scan trades from last 7 days for `price_source: 'rest'` on entry. Flag for review — means WS cache was stale at trade time.

**11. Exit price discrepancies**
Compare exit prices in trade log vs position_tracker exit log. >5c difference = flag.

**12. Historical audit**
Audit all `trades_*.jsonl` from 2026-03-26 forward. Run all critical checks. Generate summary report to `logs/data_audit_YYYY-MM-DD.json`.

---

## Alert Format

**Single issue:**
```
⚠️ Data Agent: [ISSUE_TYPE]
Ticker: KXBTC-26MAR28-B87500
Detail: Entry price 45c outside spread (bid=38c ask=42c)
Action: Flagged as _price_anomaly
```

**Multiple issues (5+):**
```
⚠️ Data Agent: 7 issues found in post-scan audit
- 2x missing fields (marked invalid)
- 3x module mismatch (auto-fixed)
- 1x P&L mismatch ($3.21 delta, cache regenerated)
- 1x daily cap violation (crypto: $742 vs $700 cap)
Details: logs/data_audit_2026-03-28.json
```

**Clean scan:**
No alert. Log to activity log only: `[DataAgent] Post-scan audit: clean (0 issues)`

**Deduplication:** Track alerted issue hashes in `logs/data_audit_state.json`. Don't re-alert same issue within 4 hours.

---

## State File

`logs/data_audit_state.json`:
```json
{
  "last_full_audit": "2026-03-28T07:00:00",
  "last_post_scan_audit": "2026-03-28T09:05:00",
  "alerted_issues": {
    "hash_abc123": "2026-03-28T09:05:00"
  },
  "cumulative_stats": {
    "total_issues_found": 12,
    "auto_fixed": 8,
    "flagged": 3,
    "alerts_sent": 2
  }
}
```

---

## Integration into ruppert_cycle.py

```python
# At end of run_full_cycle(), run_crypto_only_mode(), run_weather_only_mode():
try:
    from data_agent import run_post_scan_audit
    run_post_scan_audit(mode='post_cycle')
except Exception as e:
    log_activity(f'[DataAgent] Post-scan audit failed: {e}')  # non-fatal

# At startup (once per day):
try:
    from data_agent import run_historical_audit
    run_historical_audit(since_date='2026-03-26')
except Exception as e:
    log_activity(f'[DataAgent] Historical audit failed: {e}')
```

---

## Cleanup Rules Summary

| Issue | Action |
|-------|--------|
| Duplicate trade ID | DELETE duplicate (keep first) |
| Missing required fields | MARK `_invalid: true` (never delete) |
| Dry run mismatch in DEMO | MARK + ALERT immediately |
| Wrong module recorded | AUTO-FIX module field |
| Tracker orphan | REMOVE from tracker |
| Missing from tracker | LOG only (no auto-add) |
| Entry price outside spread | FLAG `_price_anomaly: true` |
| Daily cap violation | FLAG + ALERT |
| P&L mismatch | REGENERATE pnl_cache.json |
| Decision with no trade | FLAG `_no_matching_trade: true` |
| WS stale at entry | FLAG for review |

**NEVER auto-delete:** Executed order records, decision logs, exit records, historical audit files.

---

## Two-Tier Cleanup: Auto-Fix vs Escalate to Ruppert

### Tier 1 — Auto-fix (derived/cached data only)
Safe to fix automatically because the source data is unchanged:
- Duplicate trade IDs (delete duplicate, keep original)
- Wrong module field (auto-correct from ticker prefix)
- `pnl_cache.json` (regenerated from trade logs — it's a cache, not source)
- Tracker orphans (remove from position_tracker, not from trade log)
- Dashboard ghost positions (mark `_dashboard_ghost: true` in state file)

### Tier 2 — Escalate to Ruppert (accounting/financial records)
**DO NOT auto-edit. Alert Ruppert with full details and wait for instruction.**

These are the Single Source of Truth — the actual trade logs:
- `trades_YYYY-MM-DD.jsonl` — any edit to entry/exit price, size, or timestamps
- `demo_deposits.jsonl` — capital accounting
- Any discrepancy where it's unclear which record is wrong (dashboard vs log vs tracker all disagree)
- P&L discrepancy where auto-regenerating the cache would hide a real accounting error
- Exit records where the logged exit price doesn't match position_tracker

**Alert format for Tier 2:**
```
🔍 Data Agent: Needs your review (not auto-fixed)
Issue: P&L discrepancy in trade log — source unclear
Trade: KXBTC-26MAR28-B87500
Log entry_price: 34c | Tracker entry_price: 38c | Dashboard shows: 34c
Action needed: Tell Ruppert which is correct.
```

Ruppert reviews, confirms correct value, then manually applies the fix with a log entry explaining the correction.

---

## Dashboard Validation (add to Important tier)

**10. Dashboard numbers vs trade log**

After every full cycle, hit the dashboard API endpoints and compare against computed values from trade logs:

```python
def check_dashboard_consistency() -> list[dict]:
    import requests
    issues = []
    base = 'http://localhost:8765'

    # --- Open positions ---
    api_positions = requests.get(f'{base}/api/positions', timeout=5).json()
    log_open = get_open_positions_from_logs()  # from trades_*.jsonl
    api_count = len(api_positions)
    log_count = len(log_open)
    if abs(api_count - log_count) > 0:
        issues.append({
            'check': 'open_position_count',
            'dashboard': api_count,
            'log': log_count,
            'delta': api_count - log_count,
        })

    # --- Closed P&L ---
    api_pnl = requests.get(f'{base}/api/pnl', timeout=5).json().get('closed_pnl', 0)
    log_pnl = compute_pnl_from_logs()
    if abs(api_pnl - log_pnl) > 0.10:
        issues.append({
            'check': 'closed_pnl',
            'dashboard': api_pnl,
            'log': log_pnl,
            'delta': round(api_pnl - log_pnl, 2),
        })

    # --- Win rate per module ---
    api_stats = requests.get(f'{base}/api/stats', timeout=5).json()
    for module in ['weather', 'crypto', 'econ', 'fed', 'crypto_15m', 'crypto_long']:
        api_wr = api_stats.get(module, {}).get('win_rate')
        log_wr = compute_win_rate_from_logs(module)
        if api_wr is not None and log_wr is not None:
            if abs(api_wr - log_wr) > 0.02:  # >2% discrepancy
                issues.append({
                    'check': f'win_rate_{module}',
                    'dashboard': api_wr,
                    'log': log_wr,
                    'delta': round(api_wr - log_wr, 3),
                })

    # --- Capital deployed ---
    api_capital = requests.get(f'{base}/api/capital', timeout=5).json()
    api_deployed = api_capital.get('deployed', 0)
    log_deployed = sum(t.get('size_dollars', 0) for t in log_open)
    if abs(api_deployed - log_deployed) > 1.0:  # >$1 discrepancy
        issues.append({
            'check': 'capital_deployed',
            'dashboard': api_deployed,
            'log': log_deployed,
            'delta': round(api_deployed - log_deployed, 2),
        })

    # --- Open position tickers match ---
    api_tickers = {p.get('ticker') for p in api_positions}
    log_tickers = {p.get('ticker') for p in log_open}
    ghost_positions = api_tickers - log_tickers  # shown on dashboard but not in logs
    missing_positions = log_tickers - api_tickers  # in logs but not on dashboard
    if ghost_positions:
        issues.append({'check': 'ghost_positions', 'tickers': list(ghost_positions)})
    if missing_positions:
        issues.append({'check': 'missing_from_dashboard', 'tickers': list(missing_positions)})

    return issues
```

**Cleanup:**
- P&L mismatch → regenerate `pnl_cache.json` (dashboard reads from this)
- Ghost positions → mark in log as `_dashboard_ghost: true`, alert David
- Missing positions → alert David (manual review needed)
- Win rate / capital discrepancies → alert David with delta

**Alert example:**
```
⚠️ Data Agent: Dashboard inconsistency
- Closed P&L: dashboard=$+84.52 vs logs=$+81.31 (delta=$3.21) → cache regenerated
- Weather win rate: dashboard=91% vs logs=88% (delta=3%) → flag
- Open positions: dashboard=5 vs logs=4 (1 ghost position: KXBTC-26MAR28-B87500)
```

---

## QA Checklist

- [ ] `data_agent.py` passes `ast.parse`
- [ ] `run_post_scan_audit()` runs in <5 seconds
- [ ] `run_historical_audit()` processes all files from 2026-03-26
- [ ] Alert fires via Telegram on real issue (inject a bad trade record to test)
- [ ] Clean scan produces NO Telegram message (only activity log entry)
- [ ] Dedup: same issue doesn't alert twice within 4 hours
- [ ] Auto-fix: wrong module field corrected in place
- [ ] Duplicate deletion: only duplicate removed, original preserved
- [ ] P&L regeneration: pnl_cache.json updated correctly
- [ ] Integration: hooks fire after full cycle in ruppert_cycle.py
- [ ] `python data_agent.py --today` works from CLI
- [ ] DRY_RUN mode respected (no live order checks needed in DEMO)
- [ ] Commit and push

---
## Bug Fix: Exit P&L always null when position_tracker fires WS exit

**File:** position_tracker.py

**Problem:**
When position_tracker.py fires a WS-triggered exit, it computes P&L using ntry_price from the in-memory tracker. But if the tracker was loaded from disk after a restart (or the position was added without an entry_price), ntry_price is 0 or missing, resulting in null/wrong P&L in the trade log.

The DOGE exit on 2026-03-27 logged pnl: null and size_dollars: 211.12 (gross exit value) instead of net gain (+.36).

**Fix:**
In xecute_exit() in position_tracker.py:
1. If ntry_price is missing or 0 in the tracked position, look it up from the trade log before computing P&L
2. Add a helper: get_entry_price_from_log(ticker) -> float | None that searches trades_*.jsonl for the most recent buy entry for that ticker
3. P&L formula (already correct in position_tracker, just needs reliable entry_price):
   - YES side: pnl = (exit_price - entry_price) * contracts / 100
   - NO side: pnl = ((100 - exit_price) - (100 - entry_price)) * contracts / 100
4. If entry_price still can't be found after log lookup: log warning, record pnl=null with _pnl_lookup_failed: true (so Data Agent can flag it)

**Also fix:** Data Agent's P&L computation should handle null pnl fields by looking up entry/exit prices from the same record to recompute. Currently it skips null P&L records, leading to understated closed P&L.

**QA:** Simulate a WS exit after restart (clear tracker, reload, trigger exit) — verify P&L is computed correctly from log lookup.

---

## Bug Fix: Scheduled-scan trades not registered with position tracker

**Problem:**
When uppert_cycle.py executes trades via scheduled scan (7AM, 3PM, crypto_only, weather_only modes), those trades are logged to 	rades_*.jsonl but never added to position_tracker.py. This means:
1. Data Agent correctly flags them as "missing from tracker"
2. Post-trade monitor / WS position tracker can't watch them for exits
3. 95c rule and 70% gain exits won't fire for scheduled-scan trades

Only WS-triggered entries (via ws_feed.py) currently register with the tracker.

**Fix:**
In main.py (and any other module that executes trades via scheduled scan) — after a successful trade execution, call position_tracker.add_position():

`python
from position_tracker import add_position

# After trade logged successfully:
add_position(
    ticker=ticker,
    quantity=contracts,
    side=side,
    entry_price=entry_price_cents / 100,  # dollars
    holding_type='standard',  # or 'long_horizon' for long-horizon module
)
`

**Files to update:**
- main.py — un_weather_scan(), un_crypto_scan(), un_fed_scan(), un_econ_scan()
- crypto_long_horizon.py — xecute_long_horizon_trade() with holding_type='long_horizon'
- geo_scanner.py (if applicable)

**Also update position_tracker.add_position():**
- Accept optional dry_run: bool parameter
- In DEMO/dry_run mode, still add to tracker (we want to track dry-run positions for exit monitoring)
- Mark position with dry_run: True in the tracker entry

**QA:**
- After 7AM scan, verify all executed trades appear in position_tracker state
- Verify Data Agent no longer flags them as missing from tracker
- Verify post-trade monitor / WS feed watches them for 95c / 70% gain exits
- Verify P&L is computed correctly on exit for tracked scheduled-scan trades

---

## Bug Fix: Switch crypto_15m.py from Binance Futures to OKX (Binance geo-blocked in US)

**Problem:**
All 15M crypto signal fetches use Binance Futures API which returns HTTP 451 (geo-restricted) from US IPs. Every evaluation hits TFI_STALE, OBI_STALE blocks. Zero trades have fired from 15M module despite 1,290+ evaluations.

OKX is confirmed accessible from US and has all required endpoints.

**OKX base URL:** https://www.okx.com/api/v5

**Endpoint mapping (Binance → OKX):**

| Signal | Binance endpoint | OKX endpoint | Notes |
|--------|-----------------|--------------|-------|
| TFI (taker flow) | /fapi/v1/takeLongShortRatio | /market/trades?instId=BTC-USDT-SWAP&limit=200 | Compute buy/sell vol from raw trades |
| OBI (orderbook) | /fapi/v1/depth | /market/books?instId=BTC-USDT-SWAP&sz=10 | Same structure, different field names |
| MACD 5m candles | /fapi/v1/klines?interval=5m | /market/candles?bar=5m | Different field order |
| OI delta | /futures/data/openInterestHist | /public/open-interest?instId=BTC-USDT-SWAP | OKX is snapshot, not history — compute delta vs cached previous value |
| Price | /fapi/v1/ticker/price | /market/ticker?instId=BTC-USDT-SWAP | last field |

**OKX instrument ID mapping:**
`python
OKX_SYMBOL_MAP = {
    'BTC': 'BTC-USDT-SWAP',
    'ETH': 'ETH-USDT-SWAP',
    'XRP': 'XRP-USDT-SWAP',
    'DOGE': 'DOGE-USDT-SWAP',
}
`

**TFI from raw trades (OKX doesn't have pre-bucketed taker vol like Binance):**
`python
# GET /market/trades?instId=BTC-USDT-SWAP&limit=200
trades = resp.json()['data']  # list of {side: 'buy'/'sell', sz: '0.5', ts: '...'}
# Group by 5-min buckets using ts field
# For each bucket: TFI = (buy_vol - sell_vol) / (buy_vol + sell_vol)
`

**OI delta (OKX snapshot only):**
`python
# Cache previous OI value, compute delta on each fetch
# GET /public/open-interest?instId=BTC-USDT-SWAP
# Returns: oiCcy (OI in coin terms)
prev_oi = cache.get('prev_oi_BTC')
curr_oi = float(data['oiCcy'])
oi_delta_pct = (curr_oi - prev_oi) / prev_oi if prev_oi else 0
cache.set('prev_oi_BTC', curr_oi)
`

**Also update:** etch_binance_price() → etch_okx_price(), and update etch_coinbase_price() to use Coinbase Advanced Trade API (current endpoint returns 404):
`python
# Coinbase spot price (for settlement basis check)
GET https://api.coinbase.com/v2/prices/BTC-USD/spot
# Returns: {"data": {"amount": "87500.00", "currency": "USD"}}
`

**Files:** crypto_15m.py only. Replace all Binance Futures calls with OKX equivalents.

**QA:**
- All 4 fetch functions return valid data without TFI_STALE/OBI_STALE blocks
- TFI z-score is non-zero and varies over time
- At least one 15M evaluation reaches the edge calculation step (not blocked by stale data)
- Check decisions_15m.jsonl — should see evaluations with real signals, not just SKIP:EARLY_WINDOW or SKIP:TFI_STALE
- Commit and push
