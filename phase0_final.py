import json
from collections import defaultdict, Counter

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

all_records = [(r, 'file1', i) for i, r in enumerate(records1)] + [(r, 'file2', i) for i, r in enumerate(records2)]

# Categorize by action
action_counts = Counter(r.get('action','') for r, src, idx in all_records)
print(f"Action distribution: {dict(action_counts)}")

buy_records = defaultdict(list)
close_records = defaultdict(list)

for r, src, idx in all_records:
    action = r.get('action', '')
    ticker = r.get('ticker') or r.get('symbol', '')
    if action == 'buy':
        buy_records[ticker].append((r, src, idx))
    elif action in ('exit', 'settle'):
        close_records[ticker].append((r, src, idx))

all_tickers = set(list(buy_records.keys()) + list(close_records.keys()))

print(f"\n=== FINAL: 0-buy/1-close tickers (reverse orphans) ===")
reverse_orphan_tickers = []
for ticker in all_tickers:
    b = len(buy_records.get(ticker, []))
    c = len(close_records.get(ticker, []))
    if b == 0 and c > 0:
        reverse_orphan_tickers.append(ticker)
        closes = close_records[ticker]
        for r, src, idx in closes:
            print(f"  Ticker: {ticker}")
            print(f"    [{src}][{idx}] action={r.get('action')} ts={r.get('timestamp')} pnl={r.get('pnl')}")
            print(f"    entry={r.get('entry_price')} exit={r.get('exit_price')} contracts={r.get('contracts')}")

print(f"\n=== CHECK 7 DETAILED: ALL settle records vs formula ===")
settle_records = [(r, src, idx) for r, src, idx in all_records if r.get('action') == 'settle']
exit_records = [(r, src, idx) for r, src, idx in all_records if r.get('action') == 'exit']

settle_pass = 0
settle_fail = 0
settle_fail_list = []

for r, src, idx in settle_records:
    entry = r.get('entry_price')
    exit_p = r.get('exit_price')
    contracts = r.get('contracts')
    pnl = r.get('pnl')
    
    if entry is None or exit_p is None or contracts is None or pnl is None:
        continue
    
    computed = (exit_p - entry) * contracts / 100
    delta = abs(computed - pnl)
    
    if delta > 0.01:
        settle_fail += 1
        settle_fail_list.append((r, src, idx, computed, delta))
    else:
        settle_pass += 1

print(f"Settle records total (with all fields): {settle_pass + settle_fail}")
print(f"  Formula PASS: {settle_pass}")
print(f"  Formula FAIL (mismatch >$0.01): {settle_fail}")

# Verify: for each settle fail, check if pnl = -size_dollars (economically correct)
print("\nFor each settle formula mismatch - verify pnl = -size_dollars:")
for r, src, idx, computed_formula, delta in settle_fail_list:
    ticker = r.get('ticker')
    side = r.get('side')
    settle_result = r.get('settlement_result')
    entry = r.get('entry_price')
    contracts = r.get('contracts')
    pnl = r.get('pnl')
    # Look up buy record for size_dollars
    buys = buy_records.get(ticker, [])
    total_size = sum(buy_r.get('size_dollars', 0) for buy_r, bs, bi in buys)
    # Correct NO formula: -(100 - entry) * contracts / 100
    no_buy_price = 100 - entry if entry else None
    correct_formula = -(100 - entry) * contracts / 100 if entry is not None else None
    pnl_vs_size = round(abs(pnl) - abs(total_size), 2)
    print(f"  {ticker} | side={side} sr={settle_result} | entry={entry} exit={r.get('exit_price')} c={contracts}")
    print(f"    pnl={pnl}, formula={round(computed_formula,2)}, alt_formula(-(100-e)*c/100)={round(correct_formula,2) if correct_formula else 'N/A'}")
    print(f"    size_dollars={round(total_size,2)}, pnl vs -size: {pnl_vs_size}")
    print()

print("\n=== VERDICT FOR SETTLE RECORDS ===")
# Pattern check: all mismatches should be NO-side, result=yes, exit=0
patterns = defaultdict(int)
for r, src, idx, comp, d in settle_fail_list:
    key = f"side={r.get('side')} result={r.get('settlement_result')} exit={r.get('exit_price')}"
    patterns[key] += 1
print("Mismatch patterns:", dict(patterns))

print("\n=== CHECK 6 FINAL: TIMESTAMP DETAILS ===")
# Count by format
import re
format_counts = defaultdict(int)
for r, src, idx in all_records:
    ts = r.get('timestamp', '')
    if not ts:
        format_counts['missing'] += 1
    elif ts.endswith('Z') or '+00:00' in ts or ts.endswith('+0000'):
        format_counts['explicit_UTC'] += 1
    elif re.search(r'T\d{2}:\d{2}:\d{2}\.\d+$', ts):  # ISO with microseconds but no TZ
        format_counts['naive_iso_with_microseconds'] += 1
    elif re.search(r'T\d{2}:\d{2}:\d{2}$', ts):
        format_counts['naive_iso_seconds'] += 1
    elif re.search(r' \d{2}:\d{2}:\d{2}$', ts):
        format_counts['naive_space_separated'] += 1
    else:
        format_counts[f'other: {ts[:30]}'] += 1

print("Timestamp format breakdown:")
for fmt, count in sorted(format_counts.items(), key=lambda x: -x[1]):
    print(f"  {fmt}: {count}")

print("\n=== CHECK 2 FINAL: exit_correction schema analysis ===")
# exit_correction records - are they a legitimate schema extension?
corr = [r for r, src, idx in all_records if r.get('action') == 'exit_correction']
print(f"Total exit_correction records: {len(corr)}")
print(f"All from same source: {len(set(r.get('source') for r in corr)) == 1}")
print(f"Source: {set(r.get('source') for r in corr)}")
print(f"All same timestamp: {len(set(r.get('timestamp') for r in corr)) == 1}")
print(f"Fields present in all: {set.intersection(*[set(r.keys()) for r in corr[:20]])}")
print(f"Fields present in sample record: {list(corr[0].keys())}")
print(f"\nAre they missing 'required' fields contracts/price?")
for field in ['contracts', 'price', 'fill_price', 'entry_price']:
    count_missing = sum(1 for r in corr if r.get(field) is None)
    print(f"  {field}: {count_missing}/{len(corr)} missing")
print(f"\nNote: ISSUE-042 = known NO-side audit correction applied {corr[0].get('timestamp')}")
print(f"Total PnL correction: ${sum(r.get('pnl',0) for r in corr):.2f}")

print("\n\n=== TOTAL PnL VERIFICATION (including corrections) ===")
# PnL from trade exits/settles
raw_pnl = sum(r.get('pnl', 0) for r, src, idx in all_records if r.get('action') in ('exit', 'settle') and r.get('pnl') is not None)
correction_pnl = sum(r.get('pnl', 0) for r, src, idx in all_records if r.get('action') == 'exit_correction' and r.get('pnl') is not None)
total_pnl = raw_pnl + correction_pnl
print(f"PnL from exit/settle records: ${raw_pnl:.2f}")
print(f"PnL from exit_correction records: ${correction_pnl:.2f}")
print(f"Total PnL: ${total_pnl:.2f}")
print(f"Starting capital: $10,000.00")
print(f"Computed capital: ${10000 + total_pnl:.2f}")
print(f"Baseline: $10,347.42")
print(f"Delta from baseline (with corrections): ${10000 + total_pnl - 10347.42:.4f}")
print(f"Delta from baseline (WITHOUT corrections): ${10000 + raw_pnl - 10347.42:.4f}")

print("\n=== DOUBLE-BUY PATTERN IN FILE2 ===")
# All the orphaned pairs are in file2, 2 buys/1 close
# Check if this is systematic in file2
file2_tickers = defaultdict(lambda: {'buys': 0, 'closes': 0})
for r, src, idx in all_records:
    if src != 'file2':
        continue
    action = r.get('action', '')
    ticker = r.get('ticker', '')
    if action == 'buy':
        file2_tickers[ticker]['buys'] += 1
    elif action in ('exit', 'settle'):
        file2_tickers[ticker]['closes'] += 1

doubles = sum(1 for t in file2_tickers.values() if t['buys'] == 2 and t['closes'] == 1)
singles = sum(1 for t in file2_tickers.values() if t['buys'] == 1 and t['closes'] == 1)
zero_buy_close = sum(1 for t in file2_tickers.values() if t['buys'] == 0 and t['closes'] > 0)
two_buy_two_close = sum(1 for t in file2_tickers.values() if t['buys'] == 2 and t['closes'] == 2)
print(f"File2 ticker patterns (buy:close):")
print(f"  1:1 (normal): {singles}")
print(f"  2:1 (orphan): {doubles}")
print(f"  2:2 (double handled): {two_buy_two_close}")
print(f"  0:1 (phantom close): {zero_buy_close}")
# Distribution
dist = defaultdict(int)
for t in file2_tickers.values():
    dist[f"{t['buys']}:{t['closes']}"] += 1
for k in sorted(dist.keys()):
    print(f"  {k}: {dist[k]} tickers")
