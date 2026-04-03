# Settlement + WS Monitoring Gap for Hourly Band/Threshold Daily Positions

**Date:** 2026-04-02
**Author:** DS (Ruppert)
**Priority:** P0 — 19 positions expired with no settle records, no stop-loss coverage
**Status:** Spec complete — hand to Dev

---

## Problem

19 band/threshold daily positions entered between 02:30–07:00 UTC on 2026-04-02 have
**zero settle records**.  All expired between 06:00–11:00 UTC.  Neither the WS position
tracker nor the settlement checker wrote settlements.

Example tickers from today's logs:
- `KXBTCD-26APR0206-T66599.99` (threshold daily BTC, 06:00 expiry)
- `KXETH-26APR0207-B2050` (band daily ETH, 07:00 expiry)
- `KXBTCD-26APR0208-T66299.99` (threshold daily BTC, 08:00 expiry)

---

## Root Causes (3 bugs)

### Bug 1: `check_expired_positions()` can't parse hourly ticker dates

**File:** `agents/ruppert/trader/position_tracker.py` lines 697–722

The regex at line 704:
```python
m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
```

Expects 5 groups: **YY + MMM + DD + HH + MM** (e.g., `26APR011315` for 15m tickers).

Hourly band/threshold daily tickers encode only **YY + MMM + DD + HH** (no minutes):
- `KXBTCD-26APR0206-T66599.99` → date_part = `26APR0206` (8 digits, missing MM)
- `KXETH-26APR0207-B2050` → date_part = `26APR0207` (same)

**Result:** `re.match()` returns `None`, `close_dt` stays `None`, line 724 skips the
position entirely.  These positions are **never REST-verified for settlement**.

### Bug 2: WS entry path hardcodes `module='crypto'` → time-decay stop disabled

**File:** `agents/ruppert/data_analyst/ws_feed.py` lines 404–414, 498–499

`evaluate_crypto_entry()` builds the opportunity dict with:
```python
'module': 'crypto',           # line 414  ← WRONG
```
and registers the position with:
```python
position_tracker.add_position(..., module='crypto', ...)  # line 498–499  ← WRONG
```

The time-decay stop-loss in `position_tracker.check_exits()` (lines 400–401) requires:
```python
if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_'))
```

Since `module='crypto'`, this condition is **always False** for WS-entered positions.
Time-decay stop-loss **never fires** for these positions.

### Bug 3: Settlement checker runs only 2x/day

**File:** `environments/demo/settlement_checker.py`
**Schedule:** `scripts/setup/setup_settlement_checker.ps1` lines 26–27

Runs at **8:00 AM PDT (15:00 UTC)** and **11:00 PM PDT (06:00 UTC)**.

For hourly-expiry contracts:
- A contract expiring at 06:30 UTC and settling by 07:00 UTC won't be checked until
  15:00 UTC (8+ hour lag)
- If the Kalshi API shows `status='active'` at check time (not yet settled), the
  checker logs `[PENDING]` and skips — won't retry until 06:00 UTC next day (23h lag)

**Note:** The settlement checker itself has no filter bugs — it processes all tickers
equally.  The issue is purely scheduling frequency.

---

## Impact

| Impact | Detail |
|--------|--------|
| P&L tracking | 19 positions show no outcome — capital appears deployed but unresolved |
| Capital accounting | `get_capital()` / `get_buying_power()` may undercount available capital |
| Dashboard | Settlement P&L missing from daily rollup |
| Risk | No time-decay stop-loss means losing positions held to 0c without exit attempt |

---

## Fix Plan

### Fix 1: Extend ticker date regex to handle hourly format (position_tracker.py)

**File:** `agents/ruppert/trader/position_tracker.py` line 704

**Current:**
```python
m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})', date_part)
```

**New:** Support both HHMM (15m) and HH-only (hourly) formats:
```python
m = re.match(r'(\d{2})([A-Z]{3})(\d{2})(\d{2})(\d{2})?', date_part)
```

Make group 5 (minutes) optional.  If absent, default `mm = 0`:
```python
hh = int(m.group(4))
mm = int(m.group(5)) if m.group(5) else 0
```

This is the exact same hour with :00 minutes, which is correct for hourly contracts.

### Fix 2: Derive correct module ID in WS entry path (ws_feed.py)

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**Step A — line 414:** Replace `'module': 'crypto'` with per-asset module derivation:

```python
# Derive module from series + strike_type
_WS_MODULE_MAP = {
    ('BTC', 'between'): 'crypto_band_daily_btc',
    ('ETH', 'between'): 'crypto_band_daily_eth',
    ('XRP', 'between'): 'crypto_band_daily_xrp',
    ('DOGE', 'between'): 'crypto_band_daily_doge',
    ('SOL', 'between'): 'crypto_band_daily_sol',
    ('BTC', 'greater'): 'crypto_threshold_daily_btc',
    ('BTC', 'less'):    'crypto_threshold_daily_btc',
    ('ETH', 'greater'): 'crypto_threshold_daily_eth',
    ('ETH', 'less'):    'crypto_threshold_daily_eth',
    ('SOL', 'greater'): 'crypto_threshold_daily_sol',
    ('SOL', 'less'):    'crypto_threshold_daily_sol',
}
_ws_module = _WS_MODULE_MAP.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')
```

Then in the opp dict:
```python
'module': _ws_module,
```

**Step B — line 498:** Pass the correct module from the opp dict:
```python
position_tracker.add_position(ticker, fill_contracts, side, fill_price,
                              module=opp.get('module', 'crypto'),
                              title=opp.get('title', ''))
```

**Step C — line 430, 432:** Update `get_daily_exposure` and `should_enter` module
param to use the derived module instead of hardcoded `'crypto'`:
```python
_module_deployed = get_daily_exposure(_ws_module)
...
decision = should_enter(opp, capital, deployed_today, module=_ws_module, ...)
```

### Fix 3: Increase settlement checker frequency

**File:** `scripts/setup/setup_settlement_checker.ps1`

Add a third trigger that runs **every 30 minutes from 06:00–22:00 local time**
(covers all hourly expiry windows):

```powershell
$triggerIntraday = New-ScheduledTaskTrigger -Once -At 6:00AM `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 16)
```

Keep the existing 8AM + 11PM triggers as fallbacks.

Settlement checker is idempotent (skips already-settled), so more frequent runs are safe.

---

## Testing

1. **Regex fix:** Unit test with ticker `KXBTCD-26APR0206-T66599.99` — verify `close_dt`
   parses as `2026-04-02 10:00:00 UTC` (06:00 ET → UTC)
2. **Module fix:** Dry-run WS entry for a band ticker — verify trade log shows
   `module='crypto_band_daily_btc'` (not `'crypto'`).  Verify position_tracker
   stores the same module.
3. **Settlement frequency:** After scheduler update, verify settlement_checker runs
   intraday by checking log output timestamps.
4. **End-to-end:** Enter a band daily position via WS → let it expire → verify
   `check_expired_positions()` writes a settle record within 60s of expiry.

---

## Files Changed

| File | Change |
|------|--------|
| `agents/ruppert/trader/position_tracker.py:704` | Make minute group optional in regex |
| `agents/ruppert/data_analyst/ws_feed.py:414,430,432,498` | Derive module from asset+strike_type |
| `scripts/setup/setup_settlement_checker.ps1` | Add 30-min intraday trigger |
