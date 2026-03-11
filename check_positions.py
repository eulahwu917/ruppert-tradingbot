"""
Cross-check open positions against new ensemble + bias-corrected algorithm.
Bias is ALREADY baked into tomorrow_high_f from get_current_conditions().
"""
import sys, requests
sys.stdout.reconfigure(encoding='utf-8')
from openmeteo_client import get_current_conditions, get_ensemble_probability
from datetime import date, timedelta

BASE = 'https://api.elections.kalshi.com/trade-api/v2/markets'
TARGET = date.today() + timedelta(days=1)  # Mar 11

POSITIONS = [
    {"ticker": "KXHIGHMIA-26MAR11-B83.5", "side": "NO", "entry_c": 42, "contracts": 59,  "cost": 25.0},
    {"ticker": "KXHIGHMIA-26MAR11-B85.5", "side": "NO", "entry_c": 67, "contracts": 37,  "cost": 25.0},
    {"ticker": "KXHIGHNY-26MAR11-B66.5",  "side": "NO", "entry_c": 69, "contracts": 36,  "cost": 25.0},
    {"ticker": "KXHIGHCHI-26MAR11-B52.5", "side": "NO", "entry_c": 81, "contracts": 30,  "cost": 25.0},
    {"ticker": "KXHIGHCHI-26MAR11-B50.5", "side": "NO", "entry_c": 81, "contracts": 30,  "cost": 25.0},
    {"ticker": "KXHIGHCHI-26MAR11-B48.5", "side": "NO", "entry_c": 81, "contracts": 30,  "cost": 25.0},
]

print("\n" + "="*72)
print("  POSITION VALIDATION  (bias-corrected forecasts)")
print("="*72)

# 1. Fetch conditions + ensemble per city
print("\n  Fetching weather data...")
city_data = {}
for series in ["KXHIGHMIA", "KXHIGHNY", "KXHIGHCHI"]:
    cond = get_current_conditions(series)
    tmrw = cond.get('tomorrow_high_f')
    bias = cond.get('bias_applied_f', 0)
    raw  = round(tmrw - bias, 1) if tmrw and bias else tmrw
    city_data[series] = {
        'tomorrow_biased': tmrw,
        'raw_forecast': raw,
        'bias': bias,
        'current': cond.get('current_temp_f'),
    }
    print(f"    {series}: raw={raw}F  +{bias}F bias  => biased={tmrw}F  (current={cond.get('current_temp_f')}F)")

# 2. Also pull ensemble for each band threshold
print("\n  Pulling ensemble probabilities...")
ensemble_cache = {}
for pos in POSITIONS:
    parts = pos['ticker'].split('-')
    series = parts[0]
    threshold = float(parts[2][1:])  # B83.5 -> 83.5
    cache_key = f"{series}_{threshold}"
    if cache_key not in ensemble_cache:
        ens = get_ensemble_probability(series, threshold, TARGET)
        ensemble_cache[cache_key] = ens
        prob = ens.get('prob')
        med  = ens.get('ensemble_median')
        tot  = ens.get('total_members')
        abv  = ens.get('members_above')
        print(f"    {series} >{threshold}F: {abv}/{tot} members above => prob={prob:.0%}  median={med}F")

# 3. Cross-check each position
print()
print("-"*72)
print(f"  {'Position':<28} {'Fore':>6} {'Band':>14} {'Ens%':>5} {'Mkt%':>5} {'Entry':>5} {'Cur':>5} {'P&L':>8}  Action")
print(f"  {'-'*68}")

actions = []
total_pnl = 0

for pos in POSITIONS:
    ticker = pos['ticker']
    parts  = ticker.split('-')
    series = parts[0]
    threshold = float(parts[2][1:])
    band_lo = threshold
    band_hi = threshold + 2
    ens_above_lo = ensemble_cache.get(f"{series}_{threshold}", {})

    # Live market price
    try:
        r = requests.get(f'{BASE}/{ticker}', timeout=6)
        m = r.json().get('market', {})
        no_ask  = m.get('no_ask')
        yes_ask = m.get('yes_ask')
    except:
        no_ask = yes_ask = None

    cur_c   = no_ask
    open_pnl = ((cur_c - pos['entry_c']) * pos['contracts'] / 100) if cur_c else 0
    total_pnl += open_pnl

    # Forecast vs band
    forecast = city_data.get(series, {}).get('tomorrow_biased', 0) or 0
    margin_from_lo = forecast - band_lo  # positive = above lower bound
    margin_from_hi = forecast - band_hi  # positive = above upper bound (outside band)

    # Ensemble: prob that high > band lower bound
    ens_prob_above_lo = ens_above_lo.get('prob', None)  # prob HIGH > band_lo
    # Rough in-band probability: P(high in band) = P(>lo) - P(>hi)
    ens_above_hi = ensemble_cache.get(f"{series}_{band_hi}", {})
    ens_prob_above_hi = ens_above_hi.get('prob') if ens_above_hi else None

    if ens_prob_above_lo is not None and ens_prob_above_hi is not None:
        ens_in_band = ens_prob_above_lo - ens_prob_above_hi
        ens_no_wins = 1 - ens_in_band   # P(NOT in band) = our NO wins
    elif ens_prob_above_lo is not None:
        ens_no_wins = None  # can't compute without both
        ens_in_band = None
    else:
        ens_no_wins = None
        ens_in_band = None

    mkt_yes_pct = yes_ask or 0   # market prob of YES (in band)
    mkt_no_pct  = no_ask or 0    # market prob of NO (not in band)

    # Decide action
    if forecast > band_hi + 1:
        # Forecast clearly ABOVE band → NO almost certain
        action = "HOLD STRONG"
        flag = "+"
    elif forecast < band_lo - 1:
        # Forecast clearly BELOW band → NO almost certain
        action = "HOLD STRONG"
        flag = "+"
    elif abs(margin_from_lo) <= 1.5 or abs(margin_from_hi) <= 1.5:
        # Forecast within 1.5F of band edge → risky
        if open_pnl > 0:
            action = "EXIT (lock gain)"
            flag = "!"
        else:
            action = "WATCH (marginal)"
            flag = "~"
    else:
        action = "HOLD"
        flag = "+"

    actions.append({"ticker": ticker, "action": action, "pnl": open_pnl, "flag": flag})

    fore_str = f"{forecast:.1f}F"
    band_str = f"{band_lo}-{band_hi}F"
    ens_str  = f"{ens_in_band:.0%}" if ens_in_band is not None else "--"
    cur_str  = f"{cur_c}c" if cur_c else "--"
    pnl_str  = f"${open_pnl:+.2f}"

    print(f"  {flag} {ticker:<26} {fore_str:>6}  {band_str:>12}  {ens_str:>4}  {mkt_yes_pct:>4}%  {pos['entry_c']:>4}c  {cur_str:>5}  {pnl_str:>7}  {action}")

print(f"\n  Total Open P&L: ${total_pnl:+.2f}\n")

# Summary
print("="*72)
print("  RECOMMENDATIONS")
print("="*72)
exits = [a for a in actions if 'EXIT' in a['action']]
holds = [a for a in actions if 'HOLD' in a['action']]
watches = [a for a in actions if 'WATCH' in a['action']]

if exits:
    print(f"\n  EXIT (lock in gains before resolution):")
    for a in exits:
        print(f"    {a['ticker']}  P&L={a['pnl']:+.2f}")

if watches:
    print(f"\n  WATCH (marginal — could go either way):")
    for a in watches:
        print(f"    {a['ticker']}  P&L={a['pnl']:+.2f}")

if holds:
    print(f"\n  HOLD (algorithm supports position):")
    for a in holds:
        print(f"    {a['ticker']}  ({a['action']})")

print()
