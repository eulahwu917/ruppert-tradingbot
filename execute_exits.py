"""
One-time exit execution script — approved by David 2026-03-11
Executes all strategy-flagged exits across weather, crypto, and CPI positions.
"""
import time
import sys
sys.path.insert(0, '.')

from kalshi_client import KalshiClient

client = KalshiClient()

# ── Exits to execute ─────────────────────────────────────────────────────────
# Format: (ticker, side, contracts, price_cents, reason)
# For NO side: price_cents = no_bid you want to sell at
# For YES side: price_cents = yes_bid you want to sell at

exits = [
    # Weather — 95¢ rule
    ('KXHIGHMIA-26MAR11-B85.5', 'no',  37, 98, '95c_rule'),
    ('KXHIGHNY-26MAR11-B66.5',  'no',  36, 98, '95c_rule'),
    ('KXHIGHCHI-26MAR11-B52.5', 'no',  30, 98, '95c_rule'),
    ('KXHIGHCHI-26MAR11-B50.5', 'no',  30, 98, '95c_rule'),
    ('KXHIGHCHI-26MAR11-B48.5', 'no',  30, 98, '95c_rule'),
    # Crypto — 70%+ gain rule
    ('KXETH-26MAR1217-B2100',        'no', 31, 79, '70pct_gain'),
    ('KXXRP-26MAR1217-B1.4099500',   'no', 27, 79, '70pct_gain'),
    ('KXETH-26MAR1217-B2140',        'no', 28, 87, '70pct_gain'),
    # CPI — David approved trims
    ('KXCPI-26NOV-T0.3', 'yes', 17, 29, 'reversal_trim_25pct'),
    ('KXCPI-26AUG-T0.3', 'yes', 38, 24, 'reversal_half_50pct'),
]

print(f"\n=== Ruppert Exit Execution — {len(exits)} orders ===\n")

results = []
for ticker, side, contracts, price_cents, reason in exits:
    try:
        print(f"Selling {contracts}x {ticker} {side.upper()} @ {price_cents}¢ [{reason}]...")
        result = client.sell_position(
            ticker=ticker,
            side=side,
            price_cents=price_cents,
            count=contracts,
        )
        print(f"  OK Order placed: {getattr(result, 'order', result)}")
        results.append((ticker, 'OK', reason))
    except Exception as e:
        print(f"  FAILED: {e}")
        results.append((ticker, f'ERROR: {e}', reason))
    time.sleep(0.5)  # avoid rate limiting

print("\n=== Summary ===")
for ticker, status, reason in results:
    print(f"  {ticker}: {status} ({reason})")
