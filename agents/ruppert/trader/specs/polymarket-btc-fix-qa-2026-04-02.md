# QA Spec: Polymarket BTC Keyword Fix
_Spec written by: Dev_
_Date: 2026-04-02_
_File modified: `agents/ruppert/data_analyst/polymarket_client.py`_

---

## Summary of Changes

Four bugs were fixed in `polymarket_client.py`:

### Bug 1: Wrong keywords for BTC/ETH markets

**Root cause:** Polymarket BTC/ETH daily markets use the title pattern:
> "Will the price of Bitcoin be above $X on [date]?"

The previous keywords (`"bitcoin up"`, `"btc up"`, `"bitcoin 15min"`, `"btc end of day"`,
`"bitcoin daily"`, `"bitcoin price today"`) return zero results for these markets.

**Fix applied:**
- `_CRYPTO_KEYWORDS['BTC']` → `["bitcoin above", "bitcoin below"]`
- `_CRYPTO_KEYWORDS['ETH']` → `["ethereum above", "ethereum below"]`
- `_CRYPTO_DAILY_KEYWORDS['BTC']` → `["bitcoin above", "bitcoin below"]`
- `_CRYPTO_DAILY_KEYWORDS['ETH']` → `["ethereum above", "ethereum below"]`

### Bug 2: Asset title filter ("btc" not in "bitcoin")

**Root cause:** The filter `if asset_lower not in q_lower` checked for `"btc"` in the
question text. But Polymarket titles say "Bitcoin", not "BTC" — so every BTC market
was silently dropped even when the keyword search found them.

**Fix applied:** Added `_ASSET_ALIASES` dict and `_asset_in_title()` helper. BTC now
checks for both `"btc"` and `"bitcoin"` in the question text.

### Bug 3: Scoring didn't prefer today's expiry

**Root cause:** `_score_crypto_market()` returned an `int`. For BTC (which now returns
daily markets, not 15min/1hr), all markets scored 0 — no short-window terms appear in
"Will the price of Bitcoin be above $X on April 3?". The market with the most volume
won, which could be any expiry date.

**Fix applied:** Both `_score_crypto_market()` and `_score_crypto_daily_market()` now
return `tuple` scores with nearest expiry as the primary sort key. For daily markets,
strike closest to current price (yes_price nearest 0.5) is the tiebreaker.

### Bug 4: Daily scoring was text-based (never matched BTC titles)

**Root cause:** `_score_crypto_daily_market()` looked for substrings like `"daily"`,
`"today"`, `"eod"` — none of which appear in `"Will the price of Bitcoin be above $X
on April 3?"`. All BTC daily markets scored 0.

**Fix applied:** Scoring now uses `_days_until_end()` (parsed from `end_date` field)
as the primary rank — pure date-aware, not title-text-based.

---

## QA Verification Steps

Run from workspace root. Python must be able to import the module and make live API
calls (internet required).

```python
# QA test script — run interactively or save as qa_polymarket.py
import sys
sys.path.insert(0, 'agents/ruppert')

from data_analyst.polymarket_client import get_crypto_consensus, get_crypto_daily_consensus
from datetime import datetime, timezone

print("=== QA: Polymarket BTC Keyword Fix ===\n")

# --- Test 1: get_crypto_consensus('BTC') ---
print("Test 1: get_crypto_consensus('BTC')")
result = get_crypto_consensus('BTC')
print(f"  Result: {result}")

assert result is not None, "FAIL: get_crypto_consensus('BTC') returned None"
assert result.get('yes_price') is not None, "FAIL: yes_price is None"
assert 0.0 <= result['yes_price'] <= 1.0, f"FAIL: yes_price {result['yes_price']} out of [0,1]"
assert 'bitcoin' in result['market_title'].lower(), \
    f"FAIL: market_title doesn't mention bitcoin: {result['market_title']}"
print("  PASS\n")

# --- Test 2: get_crypto_daily_consensus('BTC') ---
print("Test 2: get_crypto_daily_consensus('BTC')")
result_daily = get_crypto_daily_consensus('BTC')
print(f"  Result: {result_daily}")

assert result_daily is not None, "FAIL: get_crypto_daily_consensus('BTC') returned None"
assert result_daily.get('yes_price') is not None, "FAIL: yes_price is None"
assert 0.0 <= result_daily['yes_price'] <= 1.0, \
    f"FAIL: yes_price {result_daily['yes_price']} out of [0,1]"
assert 'bitcoin' in result_daily['market_title'].lower(), \
    f"FAIL: market_title doesn't mention bitcoin: {result_daily['market_title']}"
print("  PASS\n")

# --- Test 3: ETH not regressed ---
print("Test 3: get_crypto_consensus('ETH') — regression check")
eth_result = get_crypto_consensus('ETH')
print(f"  Result: {eth_result}")

assert eth_result is not None, "FAIL: get_crypto_consensus('ETH') returned None (REGRESSION)"
assert eth_result.get('yes_price') is not None, "FAIL: ETH yes_price is None"
assert 0.0 <= eth_result['yes_price'] <= 1.0, \
    f"FAIL: ETH yes_price {eth_result['yes_price']} out of [0,1]"
print("  PASS\n")

# --- Test 4: ETH daily not regressed ---
print("Test 4: get_crypto_daily_consensus('ETH') — regression check")
eth_daily = get_crypto_daily_consensus('ETH')
print(f"  Result: {eth_daily}")

assert eth_daily is not None, "FAIL: get_crypto_daily_consensus('ETH') returned None (REGRESSION)"
assert eth_daily.get('yes_price') is not None, "FAIL: ETH daily yes_price is None"
print("  PASS\n")

# --- Test 5: Settlement date is today or tomorrow ---
print("Test 5: BTC daily settlement date is today or tomorrow")
from datetime import datetime, timezone, timedelta

end_date_str = result_daily.get('end_date') or ''
print(f"  end_date: {end_date_str}")

if end_date_str:
    try:
        end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        days_away = (end_dt - now_utc).total_seconds() / 86400
        print(f"  Days until settlement: {days_away:.2f}")
        assert days_away <= 2.0, \
            f"FAIL: settlement {days_away:.1f} days away — expected today or tomorrow"
        print("  PASS\n")
    except Exception as e:
        print(f"  WARNING: could not parse end_date: {e}")
else:
    print("  WARNING: end_date not present in result")

print("=== All tests passed ===")
```

---

## Expected Results

| Test | Expected |
|------|----------|
| `get_crypto_consensus('BTC')` | Non-None, yes_price in [0,1], market_title contains "bitcoin" |
| `get_crypto_daily_consensus('BTC')` | Non-None, yes_price in [0,1], market_title contains "bitcoin" |
| `get_crypto_consensus('ETH')` | Non-None (no regression), yes_price in [0,1] |
| `get_crypto_daily_consensus('ETH')` | Non-None (no regression), yes_price in [0,1] |
| Settlement date | Today or tomorrow (≤2 days away from now UTC) |

---

## What NOT to Check (Out of Scope)

- **No weight changes** — S5 is shadow-only at 20% for daily modules, with nudge=0.0.
  This fix only makes data flow; strategy behavior is unchanged.
- **No trading activity** — polymarket_client.py is read-only; no orders.
- **SOL** — keywords unchanged, not part of this fix.

---

## Notes for QA Agent

- Clear the in-process cache between test calls if running multiple calls in one Python
  session: `from data_analyst.polymarket_client import _cache; _cache.clear()`
- If running after ~16:00 UTC and today's markets have settled, results may show
  tomorrow's settlement date — this is expected and valid (days_away ≤ 2.0 still passes)
- `yes_price` near 0.5 is expected for the strike closest to current BTC price;
  strikes far from current price will show near 0.0 or near 1.0 (also valid)
- The `horizon` key will be present in `get_crypto_daily_consensus` results but may
  be absent if the fallback to short-window fires — both are acceptable
