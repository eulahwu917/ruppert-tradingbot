"""Quick test to verify market price fields come through correctly."""
import sys
sys.path.insert(0, '.')
from agents.data_analyst.kalshi_client import KalshiClient

client = KalshiClient()
markets = client.get_markets('KXHIGHNY')
if markets:
    m = markets[0]
    print(f"ticker={m.get('ticker')}")
    print(f"yes_ask={m.get('yes_ask')}  yes_bid={m.get('yes_bid')}")
    print(f"no_ask={m.get('no_ask')}  no_bid={m.get('no_bid')}")
    print(f"volume={m.get('volume')}  open_interest={m.get('open_interest')}")
    print(f"status={m.get('status')}")
    none_fields = [k for k,v in m.items() if v is None]
    print(f"None fields: {none_fields}")
else:
    print("No markets returned")
