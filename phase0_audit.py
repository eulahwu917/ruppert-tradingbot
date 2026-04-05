import json
import re
from collections import defaultdict

# Load both files
file1 = r"C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades\trades_2026-04-02.jsonl"
file2 = r"C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades\trades_2026-04-03.jsonl"

records1 = []
records2 = []

with open(file1, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            records1.append(json.loads(line))

with open(file2, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line:
            records2.append(json.loads(line))

print(f"File 1 record count: {len(records1)}")
print(f"File 2 record count: {len(records2)}")
print(f"Total records: {len(records1) + len(records2)}")

all_records = [(r, 'file1', i) for i, r in enumerate(records1)] + [(r, 'file2', i) for i, r in enumerate(records2)]

print("\n========================================")
print("CHECK 1 — DUPLICATE TRADE IDs")
print("========================================")

# Within file1
ids1 = [r['trade_id'] for r in records1]
ids2 = [r['trade_id'] for r in records2]

from collections import Counter
count1 = Counter(ids1)
count2 = Counter(ids2)
all_ids = ids1 + ids2
count_all = Counter(all_ids)

dupes_within1 = {k: v for k, v in count1.items() if v > 1}
dupes_within2 = {k: v for k, v in count2.items() if v > 1}
dupes_across = {k: v for k, v in count_all.items() if v > 1}

print(f"Duplicates within file1: {len(dupes_within1)}")
print(f"Duplicates within file2: {len(dupes_within2)}")
print(f"Total duplicate trade_ids across both files: {len(dupes_across)}")

if dupes_within1:
    print(f"File1 dupes: {dupes_within1}")
if dupes_within2:
    print(f"File2 dupes: {dupes_within2}")
if dupes_across:
    for tid, cnt in dupes_across.items():
        print(f"  Duplicate ID: {tid} (count: {cnt})")
        matching = [(r, src, idx) for r, src, idx in all_records if r.get('trade_id') == tid]
        for mr, msrc, midx in matching:
            print(f"    [{msrc}][idx={midx}] action={mr.get('action')} ticker={mr.get('ticker')} ts={mr.get('timestamp')}")

print("\n========================================")
print("CHECK 2 — SCHEMA VIOLATIONS")
print("========================================")

required_checks = {
    'trade_id': lambda r: r.get('trade_id') and isinstance(r['trade_id'], str) and len(r['trade_id']) > 0,
    'timestamp': lambda r: r.get('timestamp') and isinstance(r['timestamp'], str) and len(r['timestamp']) > 0,
    'symbol_or_ticker': lambda r: r.get('symbol') or r.get('ticker'),
    'side': lambda r: r.get('side') in ('yes', 'no'),
    'action': lambda r: r.get('action') and isinstance(r['action'], str),
    'contracts_or_qty': lambda r: r.get('contracts') is not None or r.get('qty') is not None,
    'price': lambda r: (r.get('price') is not None or r.get('fill_price') is not None or 
                        r.get('cost') is not None or r.get('entry_price') is not None),
}

violations = []
for r, src, idx in all_records:
    for field, check in required_checks.items():
        try:
            if not check(r):
                violations.append((src, idx, field, r.get('trade_id', 'MISSING'), r.get('action')))
        except Exception as e:
            violations.append((src, idx, f"{field}_error:{e}", r.get('trade_id', 'MISSING'), r.get('action')))

print(f"Total schema violations: {len(violations)}")
if violations:
    for src, idx, field, tid, action in violations[:50]:
        print(f"  [{src}][idx={idx}] field={field} trade_id={tid} action={action}")

print("\n========================================")
print("CHECK 3 & 4 — ORPHANED RECORDS / POSITION RECONCILIATION")
print("========================================")

# Separate buys and exits/settles by ticker
buy_records = defaultdict(list)
close_records = defaultdict(list)  # exit or settle

for r, src, idx in all_records:
    action = r.get('action', '')
    ticker = r.get('ticker') or r.get('symbol', '')
    if action == 'buy':
        buy_records[ticker].append((r, src, idx))
    elif action in ('exit', 'settle'):
        close_records[ticker].append((r, src, idx))

# For each ticker, count net positions
# buy = open position, exit/settle = close position
orphaned = []
net_open = {}

all_tickers = set(list(buy_records.keys()) + list(close_records.keys()))

for ticker in all_tickers:
    buys = buy_records.get(ticker, [])
    closes = close_records.get(ticker, [])
    
    num_buys = len(buys)
    num_closes = len(closes)
    
    # Net open = buys - closes (by count)
    net = num_buys - num_closes
    if net != 0:
        net_open[ticker] = {
            'buys': num_buys,
            'closes': num_closes,
            'net': net,
            'buy_records': buys,
            'close_records': closes
        }

print(f"Total unique tickers: {len(all_tickers)}")
print(f"Tickers with net open (buys != closes): {len(net_open)}")

orphaned_buys = 0
for ticker, data in net_open.items():
    net = data['net']
    print(f"\n  Ticker: {ticker}")
    print(f"    Buys: {data['buys']}, Closes: {data['closes']}, Net: {net}")
    if net > 0:
        orphaned_buys += net
        # Show the buy records that are orphaned
        extra_buys = data['buy_records']  # all buys if more buys than closes
        print(f"    ORPHANED BUY(s):")
        for r, src, idx in extra_buys[:5]:
            print(f"      [{src}][{idx}] trade_id={r.get('trade_id')} ts={r.get('timestamp')}")

print(f"\nTotal orphaned buy records (net unmatched): {orphaned_buys}")
print("tracked_positions.json is empty {}. Any net_open > 0 is an orphan.")

print("\n========================================")
print("CHECK 5 — CAPITAL RE-VERIFICATION")
print("========================================")

starting_capital = 10000.0
baseline = 10347.42

# Sum all PnL from records that have 'pnl' field (exit/settle records)
total_pnl = 0.0
pnl_count = 0
pnl_records = []

for r, src, idx in all_records:
    if 'pnl' in r and r['pnl'] is not None:
        total_pnl += r['pnl']
        pnl_count += 1
        pnl_records.append((r, src, idx))

computed_capital = starting_capital + total_pnl
delta = computed_capital - baseline

print(f"Records with PnL field: {pnl_count}")
print(f"Sum of all PnL values: ${total_pnl:.2f}")
print(f"Computed capital: ${starting_capital:.2f} + ${total_pnl:.2f} = ${computed_capital:.2f}")
print(f"Known baseline: ${baseline:.2f}")
print(f"Delta: ${delta:.2f}")
print(f"Match within $0.01: {abs(delta) <= 0.01}")

print("\n========================================")
print("CHECK 6 — TIMESTAMP/TZ CONSISTENCY")
print("========================================")

naive_count = 0
explicit_utc = 0
other_tz = 0
ambiguous_examples = []

for r, src, idx in all_records:
    ts = r.get('timestamp', '')
    if not ts:
        continue
    if ts.endswith('Z') or '+00:00' in ts or ts.endswith('+0000'):
        explicit_utc += 1
    elif re.search(r'[+-]\d{2}:\d{2}', ts) or re.search(r'[+-]\d{4}$', ts):
        other_tz += 1
    else:
        # No timezone info
        naive_count += 1
        if len(ambiguous_examples) < 10:
            ambiguous_examples.append((src, idx, ts))

total_ts = naive_count + explicit_utc + other_tz
print(f"Total timestamps checked: {total_ts}")
print(f"Explicit UTC (Z or +00:00): {explicit_utc}")
print(f"Other explicit TZ: {other_tz}")
print(f"Naive (no TZ): {naive_count}")
print(f"Examples of naive timestamps:")
for src, idx, ts in ambiguous_examples[:10]:
    print(f"  [{src}][idx={idx}] {ts}")

print("\n========================================")
print("CHECK 7 — P&L CROSS-CHECK")
print("========================================")

# Match buys with exits/settles by ticker and verify PnL
# Group by ticker, match in order
mismatches = []
verified = 0
checked_pairs = []

for ticker in all_tickers:
    buys = sorted(buy_records.get(ticker, []), key=lambda x: x[0].get('timestamp', ''))
    closes = sorted(close_records.get(ticker, []), key=lambda x: x[0].get('timestamp', ''))
    
    for i, (close_r, close_src, close_idx) in enumerate(closes):
        if i >= len(buys):
            break
        buy_r, buy_src, buy_idx = buys[i]
        
        if verified >= 50:
            break
            
        close_action = close_r.get('action')
        if close_action not in ('exit', 'settle'):
            continue
            
        # Get values
        side = buy_r.get('side') or close_r.get('side')
        contracts = close_r.get('contracts')
        entry_price = close_r.get('entry_price') or buy_r.get('entry_price') or buy_r.get('fill_price')
        exit_price = close_r.get('exit_price')
        recorded_pnl = close_r.get('pnl')
        
        if contracts is None or entry_price is None or exit_price is None or recorded_pnl is None:
            continue
        
        # Convert cents to dollars if needed (prices appear to be in cents, pnl in dollars)
        # entry_price is in cents (e.g., 58 = $0.58), exit_price in cents, contracts = number of contracts
        # PnL = (exit_price - entry_price) * contracts / 100  for YES side
        # PnL = (entry_price - exit_price) * contracts / 100  for NO side
        
        if side == 'yes':
            computed_pnl = (exit_price - entry_price) * contracts / 100
        elif side == 'no':
            computed_pnl = (entry_price - exit_price) * contracts / 100
        else:
            continue
        
        delta = abs(computed_pnl - recorded_pnl)
        verified += 1
        
        if delta > 0.01:
            mismatches.append({
                'ticker': ticker,
                'close_src': close_src,
                'close_idx': close_idx,
                'trade_id': close_r.get('trade_id'),
                'side': side,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'contracts': contracts,
                'computed_pnl': computed_pnl,
                'recorded_pnl': recorded_pnl,
                'delta': delta
            })
        
        if len(checked_pairs) < 35:
            checked_pairs.append({
                'ticker': ticker,
                'side': side,
                'entry': entry_price,
                'exit': exit_price,
                'contracts': contracts,
                'computed': round(computed_pnl, 2),
                'recorded': recorded_pnl,
                'delta': round(delta, 4),
                'match': delta <= 0.01
            })

print(f"Total pairs verified: {verified}")
print(f"PnL mismatches (>$0.01): {len(mismatches)}")

print("\nSample of verified pairs (first 35):")
for p in checked_pairs[:35]:
    status = "OK" if p['match'] else "MISMATCH"
    print(f"  {status} | {p['ticker'][:40]} | side={p['side']} | entry={p['entry']} exit={p['exit']} contracts={p['contracts']} | computed=${p['computed']} recorded=${p['recorded']} delta=${p['delta']}")

if mismatches:
    print("\nMISMATCHED records:")
    for m in mismatches:
        print(f"  {m}")

print("\n========================================")
print("PHASE 0 SUMMARY")
print("========================================")
