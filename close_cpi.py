"""Close all remaining CPI positions + cancel resting CPI orders."""
import time, sys
sys.path.insert(0, '.')
from kalshi_client import KalshiClient

client = KalshiClient()

# Cancel any resting CPI orders first
print("Checking for resting CPI orders...")
try:
    orders = client.get_orders()
    for o in orders:
        if 'KXCPI' in str(getattr(o, 'ticker', '')) and getattr(o, 'status', '') == 'resting':
            print(f"  Cancelling resting order: {o.ticker} {o.side} x{o.remaining_count}")
            try:
                client.client.cancel_order(o.order_id)
                print(f"  Cancelled.")
            except Exception as e:
                print(f"  Cancel failed: {e}")
except Exception as e:
    print(f"  Could not fetch orders: {e}")

# Get current CPI positions
print("\nFetching current CPI positions...")
positions = client.get_positions()
cpi_positions = [p for p in positions if 'KXCPI' in str(getattr(p, 'ticker', ''))]

if not cpi_positions:
    print("No open CPI positions found.")
else:
    for p in cpi_positions:
        ticker = p.ticker
        side = 'yes' if getattr(p, 'position', 0) > 0 else 'no'
        contracts = abs(getattr(p, 'position', 0))
        if contracts == 0:
            continue

        # Get current bid to set limit price
        try:
            market = client.get_market(ticker)
            if side == 'yes':
                price = getattr(market, 'yes_bid', 1) or 1
            else:
                price = getattr(market, 'no_bid', 1) or 1
            # Use 1c below bid to ensure fill, minimum 1c
            sell_price = max(price - 1, 1)
        except Exception:
            sell_price = 1  # fallback: sell at 1c to guarantee fill

        print(f"Closing {contracts}x {ticker} {side.upper()} @ {sell_price}c...")
        try:
            result = client.sell_position(ticker, side, sell_price, contracts)
            status = getattr(result.order, 'status', result) if hasattr(result, 'order') else getattr(result, 'status', result)
            print(f"  OK: {status}")
        except Exception as e:
            print(f"  FAILED: {e}")
        time.sleep(0.5)

print("\nAll CPI positions closed.")
