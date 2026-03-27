import sys
sys.path.insert(0, r'C:\Users\David Wu\.openclaw\workspace\ruppert-tradingbot-demo')
from kalshi_client import KalshiClient
import requests

client = KalshiClient()

# Check a few of the high-edge YES markets directly
tickers = [
    'KXHIGHNY-26MAR27-T62',
    'KXHIGHCHI-26MAR27-T37',
    'KXHIGHTDC-26MAR27-T67',
    'KXHIGHMIA-26MAR27-T77',
    'KXHIGHTSEA-26MAR27-T53',
]

print("=== Market Reality Check ===")
for t in tickers:
    try:
        m = client.get_market(t)
        print(f"{t}")
        print(f"  yes_ask={m.get('yes_ask')}c  yes_bid={m.get('yes_bid')}c  no_ask={m.get('no_ask')}c  status={m.get('status')}")
        print(f"  volume={m.get('volume')}  open_interest={m.get('open_interest')}")
    except Exception as e:
        print(f"{t}: ERROR - {e}")

# Also check what NOAA/OpenMeteo actually says for NYC tomorrow
print("\n=== OpenMeteo check for NYC tomorrow ===")
from openmeteo_client import get_ensemble_forecast
try:
    result = get_ensemble_forecast('New York', '2026-03-27')
    if result:
        print(f"  forecast_high={result.get('forecast_high_f')}F  confidence={result.get('confidence')}")
    else:
        print("  No result returned")
except Exception as e:
    print(f"  ERROR: {e}")
