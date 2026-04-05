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

# === Check 7 settle mismatches deeper analysis ===
mismatch_indices = [
    ('file1', 218),
    ('file1', 388),
    ('file1', 410),
    ('file1', 419),
    ('file1', 534),
    ('file1', 704),
    ('file1', 717),
    ('file1', 828),
    ('file1', 960),
    ('file1', 1058),
    ('file2', 260),
    ('file2', 261),
    ('file2', 594),
]

print("=== SETTLE MISMATCH RECORDS ===")
for src, idx in mismatch_indices:
    if src == 'file1':
        r = records1[idx]
    else:
        r = records2[idx]
    
    entry = r.get('entry_price')
    exit_p = r.get('exit_price')
    contracts = r.get('contracts')
    pnl = r.get('pnl')
    side = r.get('side')
    
    if entry is not None and exit_p is not None and contracts is not None:
        computed = (exit_p - entry) * contracts / 100
    else:
        computed = None
    
    print(f"\n[{src}][{idx}] ticker={r.get('ticker')} side={side} action={r.get('action')}")
    print(f"  entry_price={entry} exit_price={exit_p} contracts={contracts}")
    print(f"  recorded_pnl={pnl} computed_pnl={computed}")
    print(f"  size_dollars={r.get('size_dollars')}")
    print(f"  settlement_result={r.get('settlement_result')}")
    print(f"  action_detail={r.get('action_detail')}")

print("\n\n=== CHECK 7: CORRECTED SETTLE FORMULA ===")
# For settle records:
# - When settlement_result = 'yes' and side = 'yes': pnl = (100 - entry_price) * contracts / 100
# - When settlement_result = 'no' and side = 'yes': pnl = (0 - entry_price) * contracts / 100 = -entry * c/100
# - When settlement_result = 'yes' and side = 'no': pnl = (0 - entry_price_no) * contracts / 100
# - When settlement_result = 'no' and side = 'no': pnl = (100 - entry_price_no) * contracts / 100

# But looking at exit records: entry_price in EXIT for NO-side = 100 - no_buy_price
# So for settle, same convention: entry_price is stored as (100 - NO_buy_price) for NO side
# Settle YES result, NO side: your NO contracts expire worthless, loss = entry_price * contracts / 100
# (stored as entry_price for YES side equivalent = 100-NO_buy_price)
# pnl = (0 - stored_entry_price) * contracts / 100 = -entry * c/100

# But wait, the mismatches showed:
# KXETH15M-26APR021045-45: entry=62, exit=0, contracts=358, computed=-222.18, recorded=-100.0
# -> The formula gives -222.18 but recorded is capped at -100.0
# -> 62 * 358 / 100 = 221.96... not 100
# -> But size_dollars for this trade is likely ~100

# Let me check actual size of these positions via buy records
print("\n=== FINDING BUY RECORDS FOR SETTLE MISMATCH TICKERS ===")
mismatch_tickers = [
    'KXETH15M-26APR021045-45',
    'KXDOGE15M-26APR021600-00',
    'KXDOGE15M-26APR021630-30',
    'KXDOGE15M-26APR021645-45',
    'KXDOGE15M-26APR021845-45',
    'KXDOGE15M-26APR022115-15',
    'KXDOGE15M-26APR022130-30',
    'KXETH15M-26APR022300-00',
    'KXDOGE15M-26APR030100-00',
    'KXDOGE15M-26APR030215-15',
    'KXBTC15M-26APR030700-00',
    'KXETH15M-26APR030700-00',
    'KXETH15M-26APR031200-00',
]

for ticker in mismatch_tickers:
    buys = [(r, src, idx) for r, src, idx in all_records 
            if r.get('ticker') == ticker and r.get('action') == 'buy']
    settles = [(r, src, idx) for r, src, idx in all_records 
               if r.get('ticker') == ticker and r.get('action') == 'settle']
    
    print(f"\nTicker: {ticker}")
    for r, src, idx in buys:
        print(f"  BUY  [{src}][{idx}] side={r.get('side')} entry={r.get('entry_price')} contracts={r.get('contracts')} size_dollars={r.get('size_dollars')}")
    for r, src, idx in settles:
        entry = r.get('entry_price')
        exit_p = r.get('exit_price')
        contracts = r.get('contracts')
        computed = (exit_p - entry) * contracts / 100 if all(x is not None for x in [entry, exit_p, contracts]) else None
        print(f"  SETT [{src}][{idx}] side={r.get('side')} entry={entry} exit={exit_p} contracts={contracts} pnl={r.get('pnl')} computed={computed} settle_result={r.get('settlement_result')}")

print("\n\n=== CHECK 2: exit_correction RECORDS ANALYSIS ===")
# Are exit_correction records a valid schema extension?
# They have: trade_id, timestamp, date, ticker, side, action, source, module, pnl, pnl_correction, note
# They're missing: contracts, fill_price/price
# This is intentional -- they are correction records, not standard trade records

# Count by source
correction_records = [(r, src, idx) for r, src, idx in all_records if r.get('action') == 'exit_correction']
sources = defaultdict(int)
for r, src, idx in correction_records:
    sources[r.get('source', 'unknown')] += 1
print(f"Total exit_correction records: {len(correction_records)}")
print(f"Sources: {dict(sources)}")

# All from same batch?
timestamps = set()
for r, src, idx in correction_records[:10]:
    timestamps.add(r.get('timestamp'))
print(f"Timestamps on first 10: {timestamps}")

# Check what issue they reference
notes = set()
for r, src, idx in correction_records[:20]:
    note = r.get('note', '')
    # Extract pattern
    import re
    m = re.search(r'ISSUE-\w+', note)
    if m:
        notes.add(m.group())
print(f"Issue references: {notes}")

# Total PnL from exit_corrections
total_correction_pnl = sum(r.get('pnl', 0) for r, src, idx in correction_records)
print(f"Total PnL from exit_corrections: ${total_correction_pnl:.2f}")

print("\n\n=== FINAL CHECK 7 VERDICT ===")
# The settle mismatch pattern: NO-side settles where contracts > original position
# Let me check if the contracts in settle records are inflated 

# Example: KXETH15M-26APR021045-45
# Buy: contracts=?, entry=?
# Settle: entry=62, exit=0, contracts=358, computed=-222.18, recorded=-100.0

# Let me check if 100/entry_price * contracts_settle ≈ size_dollars
# If entry=62c, contracts=358: 62*358/100 = 221.96 (doesn't match 100)
# But if buy was at different price: 
# For NO side settle with 100% loss, pnl = -size_dollars
# size_dollars = entry_NO * contracts_buy / 100
# 
# The settle record might be storing a different contracts value (yes-equivalent contracts)
# Let's check if (100 - exit_entry_price) * settle_contracts / 100 matches size_dollars

for ticker in mismatch_tickers[:5]:
    buys = [(r, src, idx) for r, src, idx in all_records 
            if r.get('ticker') == ticker and r.get('action') == 'buy']
    settles = [(r, src, idx) for r, src, idx in all_records 
               if r.get('ticker') == ticker and r.get('action') == 'settle']
    
    print(f"\n{ticker}:")
    total_size = sum(r.get('size_dollars', 0) for r, src, idx in buys)
    for r, src, idx in settles:
        ep = r.get('entry_price')
        xp = r.get('exit_price')
        c = r.get('contracts')
        pnl = r.get('pnl')
        sr = r.get('settlement_result')
        no_buy_price = 100 - ep if ep else None
        print(f"  Settle: entry={ep} exit={xp} contracts={c} pnl={pnl} settlement_result={sr}")
        print(f"  no_buy_price (100-entry)={no_buy_price}")
        if no_buy_price and c:
            print(f"  no_buy_price * contracts / 100 = {no_buy_price * c / 100:.2f}")
        print(f"  Total buy size_dollars across all buys: {total_size:.2f}")
        print(f"  pnl / total_size = {pnl/total_size:.3f}" if total_size else "  no buys found")
