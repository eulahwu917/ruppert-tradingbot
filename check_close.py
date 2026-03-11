import sys, requests
sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://api.elections.kalshi.com/trade-api/v2/markets'
tickers = [
    'KXXRP-26MAR1103-B1.3899500',
    'KXXRP-26MAR1103-B1.3699500',
    'KXETH-26MAR1117-B2030',
    'KXETH-26MAR1117-B2070',
]
for ticker in tickers:
    r = requests.get(f'{BASE}/{ticker}', timeout=5)
    m = r.json().get('market', {})
    close = m.get('close_time') or m.get('expiration_time') or '?'
    status = m.get('status','?')
    ya = m.get('yes_ask')
    na = m.get('no_ask')
    print(f'{ticker}')
    print(f'  close={close}  status={status}  yes_ask={ya}  no_ask={na}')
    print()
