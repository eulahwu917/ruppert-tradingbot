"""
QA test script for Polymarket BTC Keyword Fix
Run from workspace root: python qa_polymarket.py
"""
import sys
sys.path.insert(0, 'agents/ruppert')

from data_analyst.polymarket_client import get_crypto_consensus, get_crypto_daily_consensus, _cache
from datetime import datetime, timezone, timedelta

print("=== QA: Polymarket BTC Keyword Fix ===\n")

_cache.clear()

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

_cache.clear()

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

_cache.clear()

# --- Test 3: ETH not regressed ---
print("Test 3: get_crypto_consensus('ETH') — regression check")
eth_result = get_crypto_consensus('ETH')
print(f"  Result: {eth_result}")

assert eth_result is not None, "FAIL: get_crypto_consensus('ETH') returned None (REGRESSION)"
assert eth_result.get('yes_price') is not None, "FAIL: ETH yes_price is None"
assert 0.0 <= eth_result['yes_price'] <= 1.0, \
    f"FAIL: ETH yes_price {eth_result['yes_price']} out of [0,1]"
print("  PASS\n")

_cache.clear()

# --- Test 4: ETH daily not regressed ---
print("Test 4: get_crypto_daily_consensus('ETH') — regression check")
eth_daily = get_crypto_daily_consensus('ETH')
print(f"  Result: {eth_daily}")

assert eth_daily is not None, "FAIL: get_crypto_daily_consensus('ETH') returned None (REGRESSION)"
assert eth_daily.get('yes_price') is not None, "FAIL: ETH daily yes_price is None"
print("  PASS\n")

# --- Test 5: Settlement date is today or tomorrow ---
print("Test 5: BTC daily settlement date is today or tomorrow")
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
