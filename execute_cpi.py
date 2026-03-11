"""
Execute high-conviction CPI trades (demo mode).
David's thesis: tariffs push CPI higher through mid-2026.
Top 3 picks from economics scanner.
"""
import sys, json, time, requests
from pathlib import Path
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')

from kalshi_client import KalshiClient
from logger import log_trade, log_activity
import config

DRY_RUN = True
client  = KalshiClient()
LOGS    = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)

def place(ticker, side, price_cents, contracts, size_dollars, title, note, edge):
    opp = {
        'ticker': ticker, 'title': title, 'side': side, 'action': 'buy',
        'yes_price': price_cents if side == 'yes' else (100 - price_cents),
        'market_prob': price_cents / 100, 'noaa_prob': None, 'edge': edge,
        'size_dollars': round(size_dollars, 2), 'contracts': contracts,
        'source': 'economics', 'note': note,
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'date': str(date.today()),
    }
    if DRY_RUN:
        log_trade(opp, size_dollars, contracts, {'dry_run': True, 'status': 'simulated'})
        log_activity(f"[DEMO-ECON] BUY {side.upper()} {ticker} | {contracts}@{price_cents}c | ${size_dollars:.2f} | edge={edge*100:.0f}%")
        print(f"  [DEMO] BUY {side.upper()} {ticker:40} {contracts:3}@{price_cents:2}c  ${size_dollars:.2f}  edge={edge*100:.0f}%")
    else:
        try:
            result = client.place_order(ticker, side, price_cents, contracts)
            log_trade(opp, size_dollars, contracts, result)
            print(f"  [LIVE] BUY {side.upper()} {ticker} executed")
        except Exception as e:
            print(f"  ERROR {ticker}: {e}")

print("=" * 65)
print("  CPI TRADES — David thesis: tariffs push CPI > 0.3%/mo")
print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}  |  Mode: {'DEMO' if DRY_RUN else 'LIVE'}")
print("=" * 65)

# Verify markets are still open + prices haven't moved much
BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"

trades = [
    # Highest conviction: June CPI > 0.0% YES — nearly certain with tariffs
    {
        'ticker': 'KXCPI-26JUN-T0.0',
        'side':   'yes',
        'target_price': 77,
        'title':  'CPI Jun 2026 - Above 0.0% MoM',
        'note':   'Tariff thesis: CPI stays positive. Model 95%+ vs market 77%. Edge=18%',
        'edge':   0.18,
        'size':   25.00,
    },
    # Nov 0.3% — 6mo tariff impact priced in
    {
        'ticker': 'KXCPI-26NOV-T0.3',
        'side':   'yes',
        'target_price': 37,
        'title':  'CPI Nov 2026 - Above 0.3% MoM',
        'note':   'Tariff thesis: sustained inflation. Model 60%+ vs market 37%. Edge=23%',
        'edge':   0.23,
        'size':   25.00,
    },
    # Aug 0.3% — medium term tariff pressure
    {
        'ticker': 'KXCPI-26AUG-T0.3',
        'side':   'yes',
        'target_price': 33,
        'title':  'CPI Aug 2026 - Above 0.3% MoM',
        'note':   'Tariff thesis: sustained inflation. Model 58%+ vs market 33%. Edge=25%',
        'edge':   0.25,
        'size':   25.00,
    },
]

executed = 0
for t in trades:
    try:
        r = requests.get(f"{BASE}/{t['ticker']}", timeout=5)
        if r.status_code != 200:
            print(f"  SKIP {t['ticker']} — market not found (status {r.status_code})")
            continue
        m = r.json().get('market', {})
        if m.get('status') not in ('open', 'active', None):
            print(f"  SKIP {t['ticker']} — status={m.get('status')}")
            continue
        live_price = m.get('yes_ask') if t['side'] == 'yes' else m.get('no_ask')
        if not live_price:
            live_price = t['target_price']
        # Accept if price hasn't moved more than 5c against us
        if abs(live_price - t['target_price']) > 5:
            print(f"  SKIP {t['ticker']} — price moved too much: target={t['target_price']}c live={live_price}c")
            continue
        contracts = max(1, int(t['size'] / live_price * 100))
        actual    = round(contracts * live_price / 100, 2)
        place(t['ticker'], t['side'], live_price, contracts, actual,
              t['title'], t['note'], t['edge'])
        executed += 1
    except Exception as e:
        print(f"  ERROR {t['ticker']}: {e}")

print(f"\n  {executed}/{len(trades)} CPI trades logged")
print("=" * 65)
