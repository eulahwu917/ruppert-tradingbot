import json
from collections import defaultdict

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

print("=== INVESTIGATING exit_correction RECORDS (Check 2) ===")
correction_records = [(r, src, idx) for r, src, idx in all_records if r.get('action') == 'exit_correction']
print(f"Total exit_correction records: {len(correction_records)}")
# Show first few
for r, src, idx in correction_records[:5]:
    print(f"\n[{src}][{idx}] trade_id={r.get('trade_id')}")
    print(json.dumps(r, indent=2))

print("\n\n=== CHECK 7 CORRECTED: (exit_price - entry_price) * contracts / 100 FOR ALL SIDES ===")
print("For NO exits: exit record stores entry_price=100-NO_buy, exit_price=100-yes_bid\n")

# The correct formula for both YES and NO is:
# pnl = (exit_price - entry_price) * contracts / 100
# where entry_price and exit_price come from the EXIT/SETTLE record

exit_records = [(r, src, idx) for r, src, idx in all_records 
                if r.get('action') in ('exit', 'settle') and r.get('pnl') is not None
                and r.get('entry_price') is not None and r.get('exit_price') is not None
                and r.get('contracts') is not None]

mismatches = []
verified = 0
sample = []

for r, src, idx in exit_records:
    entry_price = r.get('entry_price')
    exit_price = r.get('exit_price')
    contracts = r.get('contracts')
    recorded_pnl = r.get('pnl')
    side = r.get('side')
    
    computed_pnl = (exit_price - entry_price) * contracts / 100
    delta = abs(computed_pnl - recorded_pnl)
    
    verified += 1
    if delta > 0.01:
        mismatches.append({
            'ticker': r.get('ticker'),
            'src': src, 'idx': idx,
            'trade_id': r.get('trade_id'),
            'action': r.get('action'),
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'contracts': contracts,
            'computed_pnl': round(computed_pnl, 4),
            'recorded_pnl': recorded_pnl,
            'delta': round(delta, 4)
        })
    
    if len(sample) < 40:
        sample.append({
            'ticker': r.get('ticker', '')[:40],
            'side': side,
            'action': r.get('action'),
            'entry': entry_price,
            'exit': exit_price,
            'contracts': contracts,
            'computed': round(computed_pnl, 2),
            'recorded': recorded_pnl,
            'delta': round(delta, 4),
            'ok': delta <= 0.01
        })

print(f"Total exit/settle records with pnl verified: {verified}")
print(f"Mismatches (>$0.01): {len(mismatches)}")
print()
print("Sample of 40 pairs:")
for p in sample:
    status = "OK" if p['ok'] else "MISMATCH"
    print(f"  {status} | {p['ticker']:<40} | side={p['side']} action={p['action']:<7} | e={p['entry']} x={p['exit']} c={p['contracts']} | comp=${p['computed']} rec=${p['recorded']} delta=${p['delta']}")

if mismatches:
    print(f"\nAll mismatches:")
    for m in mismatches:
        print(f"  [{m['src']}][{m['idx']}] {m['ticker']} | {m['action']} side={m['side']} | computed=${m['computed_pnl']} recorded=${m['recorded_pnl']} delta=${m['delta']}")

print("\n\n=== INVESTIGATING ORPHANED RECORDS (Check 3/4 deep dive) ===")

# Pattern: 2 buys per ticker, 1 close -> likely double-entry buys on file2
# Let's check a specific case
orphan_ticker = 'KXDOGE15M-26APR030315-15'
ticker_buys = [(r, src, idx) for r, src, idx in all_records if r.get('ticker') == orphan_ticker and r.get('action') == 'buy']
ticker_exits = [(r, src, idx) for r, src, idx in all_records if r.get('ticker') == orphan_ticker and r.get('action') in ('exit', 'settle')]

print(f"\nTicker: {orphan_ticker}")
print(f"Buy records ({len(ticker_buys)}):")
for r, src, idx in ticker_buys:
    print(f"  [{src}][{idx}] trade_id={r.get('trade_id')} ts={r.get('timestamp')} entry={r.get('entry_price')} contracts={r.get('contracts')}")
print(f"Exit/settle records ({len(ticker_exits)}):")
for r, src, idx in ticker_exits:
    print(f"  [{src}][{idx}] trade_id={r.get('trade_id')} ts={r.get('timestamp')} exit={r.get('exit_price')} pnl={r.get('pnl')} contracts={r.get('contracts')}")

# Check XRP ticker with net=-1 (0 buys, 1 close)
orphan_ticker2 = 'KXXRP15M-26APR031200-00'
ticker_buys2 = [(r, src, idx) for r, src, idx in all_records if r.get('ticker') == orphan_ticker2 and r.get('action') == 'buy']
ticker_exits2 = [(r, src, idx) for r, src, idx in all_records if r.get('ticker') == orphan_ticker2 and r.get('action') in ('exit', 'settle')]

print(f"\nTicker: {orphan_ticker2}")
print(f"Buy records ({len(ticker_buys2)}):")
for r, src, idx in ticker_buys2:
    print(f"  [{src}][{idx}] trade_id={r.get('trade_id')} ts={r.get('timestamp')}")
print(f"Exit/settle records ({len(ticker_exits2)}):")
for r, src, idx in ticker_exits2:
    print(f"  [{src}][{idx}] trade_id={r.get('trade_id')} ts={r.get('timestamp')} pnl={r.get('pnl')}")
    print(f"  Full: {json.dumps(r, indent=4)}")

# Now count: how many tickers have 2 buys, 1 close vs 0 buys, 1 close vs 2 buys, 0 closes
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
net_open_positive = 0
net_open_negative = 0
double_buy_single_close = 0
zero_buy_single_close = 0
for ticker in all_tickers:
    b = len(buy_records.get(ticker, []))
    c = len(close_records.get(ticker, []))
    net = b - c
    if net > 0:
        net_open_positive += net
        if b == 2 and c == 1:
            double_buy_single_close += 1
    elif net < 0:
        net_open_negative += abs(net)
        if b == 0 and c == 1:
            zero_buy_single_close += 1

print(f"\n\nNet-open summary:")
print(f"  Net-open positive (buys > closes): {net_open_positive} across various tickers")
print(f"  Net-open negative (closes > buys): {net_open_negative} across various tickers")
print(f"  Pattern 2-buys/1-close: {double_buy_single_close} tickers")
print(f"  Pattern 0-buys/1-close: {zero_buy_single_close} tickers")
print()
print("  Net +42 open positions detected, tracker is empty -> these are unrecorded open positions")
print("  Note: file2 has dual buy entries per cycle (two buy records per ticker per cycle)")
print("  Exit records only close one of the two buys, leaving the second orphaned")

print("\n\n=== VERIFYING NO-SIDE PnL FORMULA (3 examples from mismatches) ===")
# Look at buy + exit for KXBTC first trade (NO side)
btc_no_buy = records1[1]
btc_no_exit = records1[4]
print("BTC NO buy:", json.dumps({k: btc_no_buy.get(k) for k in ['ticker','side','action','entry_price','fill_price','contracts','timestamp']}, indent=2))
print("BTC NO exit:", json.dumps({k: btc_no_exit.get(k) for k in ['ticker','side','action','entry_price','exit_price','contracts','pnl','action_detail','timestamp']}, indent=2))
print(f"Formula check: ({btc_no_exit['exit_price']} - {btc_no_exit['entry_price']}) * {btc_no_exit['contracts']} / 100 = {(btc_no_exit['exit_price'] - btc_no_exit['entry_price']) * btc_no_exit['contracts'] / 100}")
print(f"Recorded pnl: {btc_no_exit['pnl']}")
print(f"Note: buy entry_price={btc_no_buy['entry_price']} but exit entry_price={btc_no_exit['entry_price']} (= 100 - NO_buy_price = 100 - {btc_no_buy['entry_price']} = {100 - btc_no_buy['entry_price']})")
