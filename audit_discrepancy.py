
"""
Investigate P&L discrepancy and impossible P&L records
"""
import json
import os
from collections import defaultdict, Counter

base = 'C:/Users/David Wu/.openclaw/workspace/environments/demo/logs/trades'
all_records = []
for fn in sorted(os.listdir(base)):
    if fn.endswith('.jsonl'):
        with open(os.path.join(base, fn)) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_records.append((fn, json.loads(line)))
                    except: pass

settles = [(fn, t) for fn, t in all_records if t.get('action') == 'settle']
exits = [(fn, t) for fn, t in all_records if t.get('action') == 'exit']
corrections = [(fn, t) for fn, t in all_records if t.get('action') == 'exit_correction']
buys = [(fn, t) for fn, t in all_records if t.get('action') == 'buy']
closes = settles + exits

# 1. Investigate the raw P&L discrepancy ($12,817 vs pnl_cache $12,583)
print('=== P&L DISCREPANCY INVESTIGATION ===')
print()
# pnl_cache.json: $12,583.26
# Our calculation: $12,817.12
# Difference: $233.86
diff = 12817.12 - 12583.26
print(f'Discrepancy: ${diff:.2f}')
print()

# Is there a .tmp file with recent exits?
# pnl_cache.json removed — P&L computed live from logs
import os.path
print('pnl_cache.json removed — use compute_closed_pnl_from_logs()')
print()

# Check trades_2026-03-31.tmp vs .jsonl
# The .tmp might be in-progress records
tmp_path = 'C:/Users/David Wu/.openclaw/workspace/environments/demo/logs/trades/trades_2026-03-31.tmp'
tmp_records = []
if os.path.exists(tmp_path):
    with open(tmp_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    tmp_records.append(json.loads(line))
                except: pass
print(f'trades_2026-03-31.tmp records: {len(tmp_records)}')
tmp_actions = Counter(t.get('action') for t in tmp_records)
print(f'TMP actions: {dict(tmp_actions)}')
tmp_close_pnl = sum(t.get('pnl', 0) for t in tmp_records if t.get('action') in ['settle', 'exit'])
tmp_corr_pnl = sum(t.get('pnl', 0) for t in tmp_records if t.get('action') == 'exit_correction')
print(f'TMP close P&L: ${tmp_close_pnl:,.2f}')
print(f'TMP correction P&L: ${tmp_corr_pnl:,.2f}')
print()

# 2. Investigate impossible P&L records (WIN_EXCEEDS_POSSIBLE = phantom wins)
print('=== IMPOSSIBLE P&L RECORDS (WIN_EXCEEDS_POSSIBLE) ===')
print()
impossible = []
for fn, t in closes:
    pnl = t.get('pnl', 0)
    ep = t.get('entry_price')
    contracts = t.get('contracts')
    if ep is not None and contracts is not None and ep > 0:
        max_win = (100 - ep) * contracts / 100
        if pnl > max_win + 1.0:
            impossible.append((fn, t, max_win, pnl - max_win))

print(f'Total impossible (WIN > MAX_WIN) records: {len(impossible)}')
print()

# Are these all 95c_rule_no bug exits?
bug_impossible = [(fn, t, mw, ov) for fn, t, mw, ov in impossible if '95c_rule_no' in str(t.get('action_detail',''))]
non_bug_impossible = [(fn, t, mw, ov) for fn, t, mw, ov in impossible if '95c_rule_no' not in str(t.get('action_detail',''))]
print(f'Impossible records that ARE 95c_rule_no bug: {len(bug_impossible)}')
print(f'Impossible records that are NOT 95c_rule_no bug: {len(non_bug_impossible)}')

if non_bug_impossible:
    print('\nNon-bug impossible records:')
    for fn, t, mw, ov in non_bug_impossible[:10]:
        print(f'  {t["ticker"]}: pnl=${t.get("pnl"):.2f}, max_win=${mw:.2f}, overshoot=${ov:.2f}, action_detail={t.get("action_detail")}, module={t.get("module")}')
print()

# What fraction of 95c_rule_no exits appear in impossible records?
bug_exits_95c = [(fn, t) for fn, t in exits if '95c_rule_no' in str(t.get('action_detail', ''))]
print(f'All 95c_rule_no exit records: {len(bug_exits_95c)}')
print(f'Of which are WIN_EXCEEDS_POSSIBLE: {len(bug_impossible)}')
bug_impossible_tids = {t.get('trade_id') for fn, t, mw, ov in bug_impossible}
bug_at_0c = [(fn, t) for fn, t in bug_exits_95c if '@ 0c' in str(t.get('action_detail',''))]
print(f'Of which are @ 0c: {len(bug_at_0c)}')
# @ 0c with pnl > 0 (phantom wins, the actual bug)
phantom_wins_at_0c = [(fn, t) for fn, t in bug_at_0c if t.get('pnl', 0) > 0]
real_losses_at_0c = [(fn, t) for fn, t in bug_at_0c if t.get('pnl', 0) <= 0]
print(f'  @ 0c phantom wins (pnl > 0): {len(phantom_wins_at_0c)}')
print(f'  @ 0c real losses (pnl <= 0): {len(real_losses_at_0c)}')
print()

# The phantom win logic: side=no, exit at 0c but market settled YES
# Win means (entry_price - exit_price) * contracts / 100 for NO
# NO position: win if market goes below entry, i.e. settles NO
# At 0c exit: pnl = entry_price * contracts / 100 (the gain)
# But if market settled YES (win for YES buyers), NO holders LOSE
# So phantom win = recorded as profit but should be loss
print('--- Sample phantom wins at 0c ---')
for fn, t in phantom_wins_at_0c[:3]:
    print(json.dumps(t, indent=2))
    print()

# 3. How many corrections are truly needed (missing)
correction_map = {}
for fn, c in corrections:
    orig = c.get('original_trade_id')
    if orig:
        correction_map[orig] = c

# All "@ 0c" exits with pnl > 0 that are missing corrections
missing_corr = [(fn, t) for fn, t in phantom_wins_at_0c 
                if t.get('trade_id') not in correction_map]
print(f'Phantom wins at 0c missing corrections: {len(missing_corr)}')
for fn, t in missing_corr:
    print(f'  {t["ticker"]}: date={t["date"]}, pnl=${t.get("pnl"):.2f}, module={t.get("module")}')
print()

# Calculate uncorrected P&L from these missing corrections
missing_pnl_impact = sum(t.get('pnl', 0) * 2 for fn, t in missing_corr)  # *2 because need to flip
print(f'P&L impact of missing corrections: ${-missing_pnl_impact/2 - sum(t.get("pnl",0) for fn,t in missing_corr):,.2f}')
print(f'If true_pnl = -logged_pnl, delta = ${sum(-2*t.get("pnl",0) for fn,t in missing_corr):,.2f}')
print()

# 4. Weather module: understand what's happening
print('=== WEATHER MODULE: WHY 0W/57L? ===')
print()

weather_closes = [(fn, t) for fn, t in closes if t.get('module') in ['weather_band', 'weather']]

# All weather closes settled "no"?
# Our bot always buys YES
# Pattern: bought YES at various prices, market settled NO every time
# Were these bad markets (thin?) or was the model wrong?

# Check what tickers look like
weather_tickers = set(t.get('ticker') for fn, t in weather_closes)
print(f'Unique weather tickers closed: {len(weather_tickers)}')

# Sample some
sample_tickers = list(weather_tickers)[:5]
print(f'Sample: {sample_tickers}')
print()

# Were all these contracts 10000 at 1c?
# That would mean: cost = $100, potential win = $9,900
weather_by_ep = defaultdict(lambda: {'w':0,'l':0,'cost':0})
for fn, t in weather_closes:
    ep = t.get('entry_price', 0)
    cat = f'{ep}c'
    pnl = t.get('pnl', 0)
    cost = ep * t.get('contracts', 0) / 100
    if pnl > 0:
        weather_by_ep[cat]['w'] += 1
    else:
        weather_by_ep[cat]['l'] += 1
    weather_by_ep[cat]['cost'] += cost

# What was the average cost per trade?
total_cost = sum(ep * t.get('contracts', 0) / 100 
                 for fn, t in weather_closes 
                 if t.get('entry_price') is not None)
avg_cost = total_cost / max(len(weather_closes), 1)
print(f'Average cost per weather trade: ${avg_cost:.2f}')
print(f'Total weather cost: ${total_cost:.2f}')
print()

# What's the issue: look at NOAA prob vs actual settlement
weather_loses = [(fn, t) for fn, t in weather_closes if t.get('pnl', 0) <= 0]
# Get noaa_prob from close records
noaa_probs = [t.get('noaa_prob') for fn, t in weather_loses if t.get('noaa_prob') is not None]
if noaa_probs:
    print(f'Losing weather trades: noaa_prob range [{min(noaa_probs):.3f}, {max(noaa_probs):.3f}], avg={sum(noaa_probs)/len(noaa_probs):.3f}')
else:
    print('No noaa_prob in close records')

# Check entry_edge on close records
entry_edges = [t.get('entry_edge', t.get('edge', 0)) for fn, t in weather_loses if t.get('entry_edge') or t.get('edge')]
if entry_edges:
    print(f'Losing weather entry edges: avg={sum(entry_edges)/len(entry_edges):.3f}')
print()

# Check if it's a calibration issue: buy at 1c = market says 1% chance but NOAA says 99%?
# Buying YES at 1c on high-edge bets should pay off IF noaa is right
# 0W/57L means noaa is systematically wrong, or these markets already priced it differently
one_c_closes = [(fn, t) for fn, t in weather_closes if t.get('entry_price') == 1.0]
print(f'Weather closes at 1c entry: {len(one_c_closes)}')
if one_c_closes:
    # These markets said 1% chance of YES
    # Our model said 99%+ chance
    # They ALL settled NO -- means our model was overconfident
    one_c_wins = [t for fn, t in one_c_closes if t.get('pnl', 0) > 0]
    print(f'  1c trades W/L: {len(one_c_wins)}W / {len(one_c_closes)-len(one_c_wins)}L')
    print(f'  These trades: market price=1%, NOAA says ~99%+, they ALL lost')
    print('  VERDICT: Model systematically overconfident OR wrong direction/market')
print()

# Check the weather band tickers - what were we predicting?
# KXHIGHX = high temperature markets
# Are these "will temp be ABOVE X" or "will temp be in range X"?
band_pattern = Counter()
for fn, t in weather_closes:
    ticker = t.get('ticker', '')
    if '-B' in ticker:
        band_pattern['ABOVE'] += 1  # B = above bound
    elif '-T' in ticker:
        band_pattern['BELOW'] += 1  # T = below bound
    else:
        band_pattern['OTHER'] += 1
print(f'Weather ticker direction pattern: {dict(band_pattern)}')

# Side breakdown
side_dist = Counter(t.get('side') for fn, t in weather_closes)
print(f'Side distribution: {dict(side_dist)}')
print()

# 5. crypto_15m double entry: investigate the 5 overlapping ticker+dates
print('=== CRYPTO_15M: Double Entry Investigation ===')
print()

old_closes = [(fn, t) for fn, t in closes if t.get('module') == 'crypto_15m']
new_closes = [(fn, t) for fn, t in closes if t.get('module') == 'crypto_15m_dir']

old_by_td = defaultdict(list)
for fn, t in old_closes:
    key = (t.get('ticker'), t.get('date'))
    old_by_td[key].append(t)

new_by_td = defaultdict(list)
for fn, t in new_closes:
    key = (t.get('ticker'), t.get('date'))
    new_by_td[key].append(t)

overlap = set(old_by_td.keys()) & set(new_by_td.keys())
print(f'Ticker+date in both old and new labels: {len(overlap)}')
total_dup_pnl = 0
for key in overlap:
    old_trades = old_by_td[key]
    new_trades = new_by_td[key]
    old_pnl = sum(t.get('pnl', 0) for t in old_trades)
    new_pnl = sum(t.get('pnl', 0) for t in new_trades)
    print(f'  {key[0]} ({key[1]}):')
    print(f'    OLD ({key[1]}): {len(old_trades)} records, P&L=${old_pnl:.2f}, action_detail={[t.get("action_detail") for t in old_trades]}')
    print(f'    NEW ({key[1]}): {len(new_trades)} records, P&L=${new_pnl:.2f}, action_detail={[t.get("action_detail") for t in new_trades]}')
    # Are these truly double-entered (same position, different module label)?
    if len(old_trades) == 1 and len(new_trades) == 1:
        ot = old_trades[0]
        nt = new_trades[0]
        print(f'    contracts: old={ot.get("contracts")}, new={nt.get("contracts")}')
        print(f'    entry_price: old={ot.get("entry_price")}, new={nt.get("entry_price")}')
        print(f'    exit_price: old={ot.get("exit_price")}, new={nt.get("exit_price")}')
        total_dup_pnl += old_pnl + new_pnl
print(f'Total P&L in overlapping records: ${total_dup_pnl:.2f}')
print()

# Count ALL crypto_15m old label records per day
old_by_date = Counter(t.get('date') for fn, t in old_closes)
print(f'Old label closes by date: {dict(sorted(old_by_date.items()))}')
# They're ALL on 2026-03-31! Check when old label was used
print()

# Check if old label on 3/31 was from the morning before taxonomy migration
old_31 = [(fn, t) for fn, t in old_closes if t.get('date') == '2026-03-31']
if old_31:
    timestamps = sorted(t.get('timestamp', '') for fn, t in old_31)
    print(f'Old label 3/31 timestamps: first={timestamps[0]}, last={timestamps[-1]}')
new_31 = [(fn, t) for fn, t in new_closes if t.get('date') == '2026-03-31']
if new_31:
    timestamps = sorted(t.get('timestamp', '') for fn, t in new_31)
    print(f'New label 3/31 timestamps: first={timestamps[0]}, last={timestamps[-1]}')
print()
