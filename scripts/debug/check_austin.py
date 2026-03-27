import requests

ticker = 'KXHIGHAUS-26MAR27-T86'

# Check REST endpoint
r = requests.get(f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}', timeout=5)
m = r.json().get('market', {})
print('REST:')
print('  status=' + str(m.get('status')) + ' result=' + str(m.get('result')))
print('  yes_ask=' + str(m.get('yes_ask')) + ' yes_bid=' + str(m.get('yes_bid')))
print('  no_ask=' + str(m.get('no_ask')) + ' no_bid=' + str(m.get('no_bid')))
print('  last_price=' + str(m.get('last_price')))
print('  volume=' + str(m.get('volume')) + ' open_interest=' + str(m.get('open_interest')))
print()

# Check orderbook
ob = requests.get(f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook', timeout=5)
obdata = ob.json().get('orderbook_fp', {})
print('Orderbook:')
print('  no_dollars=' + str(obdata.get('no_dollars')))
print('  yes_dollars=' + str(obdata.get('yes_dollars')))
