import json
data = json.load(open(r'C:\Users\David Wu\.openclaw\workspace\ruppert-backtest\data\kraken_ohlc_XBTUSD.json', encoding='utf-8'))
prices = [c['close'] for c in data]
pmin, pmax = min(prices), max(prices)
print(f"BTC candles: {len(data)}")
print(f"BTC price range: {pmin:.0f} - {pmax:.0f}")
print(f"In 75k-100k range: {75000 <= pmin and pmax <= 100000}")
print(f"First candle: {data[0]}")
print(f"Last candle: {data[-1]}")

# Also check Open-Meteo GFS keys
om = json.load(open(r'C:\Users\David Wu\.openclaw\workspace\ruppert-backtest\data\openmeteo_historical_forecasts.json', encoding='utf-8'))
nyc = om.get('KXHIGHNY', {})
print(f"\nNYC dates available: {list(nyc.keys())[:5]}")
print(f"NYC 2026-03-10: {nyc.get('2026-03-10')}")
print(f"NYC 2026-03-01: {nyc.get('2026-03-01')}")
# Count nulls across all series
null_count = 0
for series, days in om.items():
    for d, vals in days.items():
        for k, v in vals.items():
            if v is None:
                null_count += 1
print(f"\nTotal null values across all cities/days/models: {null_count}")
# Count per model
ecmwf_nulls = sum(1 for s,days in om.items() for d,v in days.items() if v.get('ecmwf_max') is None)
gfs_nulls   = sum(1 for s,days in om.items() for d,v in days.items() if v.get('gfs_max') is None)
icon_nulls  = sum(1 for s,days in om.items() for d,v in days.items() if v.get('icon_max') is None)
print(f"ECMWF nulls: {ecmwf_nulls}, GFS nulls: {gfs_nulls}, ICON nulls: {icon_nulls}")
