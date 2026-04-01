"""
DS Definitive Capital Audit
Replicates compute_closed_pnl_from_logs() + deposit sum exactly.
"""
import json
from pathlib import Path
from collections import defaultdict

TRADES_DIR = Path(r"C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\trades")
DEPOSITS_FILE = Path(r"C:\Users\David Wu\.openclaw\workspace\environments\demo\logs\demo_deposits.jsonl")
SINCE = '2026-03-26'

# === STEP 1: Read all records, categorized ===
all_records = []
for p in sorted(TRADES_DIR.glob('trades_*.jsonl')):
    file_date = p.stem.replace('trades_', '')
    if file_date < SINCE:
        continue
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
            t['_file'] = p.name
            all_records.append(t)
        except Exception:
            pass

print(f"=== TOTAL RAW RECORDS ACROSS ALL FILES: {len(all_records)} ===\n")

# === STEP 2: Categorize by action ===
buys = [t for t in all_records if t.get('action') not in ('exit', 'settle', 'exit_correction')]
exits = [t for t in all_records if t.get('action') == 'exit']
settles = [t for t in all_records if t.get('action') == 'settle']
corrections = [t for t in all_records if t.get('action') == 'exit_correction']

print(f"--- BUY/OPEN records ---")
print(f"  Count: {len(buys)}")
buy_cost = sum(float(t.get('size_dollars', 0) or 0) for t in buys)
print(f"  Total cost (size_dollars): ${buy_cost:.2f}")

print(f"\n--- EXIT records ---")
print(f"  Count (all): {len(exits)}")
exits_valid = [t for t in exits if t.get('pnl') is not None]
exits_invalid = [t for t in exits if t.get('pnl') is None]
print(f"  Count (pnl not None): {len(exits_valid)}")
print(f"  Count (pnl is None / _invalid): {len(exits_invalid)}")
exit_pnl = sum(float(t['pnl']) for t in exits_valid)
print(f"  Sum of pnl: ${exit_pnl:.2f}")
# Show any with pnl=None
if exits_invalid:
    for t in exits_invalid:
        print(f"    [SKIPPED] ticker={t.get('ticker')} action={t.get('action')} pnl={t.get('pnl')}")

print(f"\n--- SETTLE records ---")
print(f"  Count (all): {len(settles)}")
settles_valid = [t for t in settles if t.get('pnl') is not None]
settles_invalid = [t for t in settles if t.get('pnl') is None]
print(f"  Count (pnl not None): {len(settles_valid)}")
print(f"  Count (pnl is None / _invalid): {len(settles_invalid)}")
settle_pnl = sum(float(t['pnl']) for t in settles_valid)
print(f"  Sum of pnl: ${settle_pnl:.2f}")
if settles_invalid:
    for t in settles_invalid:
        print(f"    [SKIPPED] ticker={t.get('ticker')} action={t.get('action')} pnl={t.get('pnl')}")

print(f"\n--- EXIT_CORRECTION records ---")
print(f"  Count (all): {len(corrections)}")
corrections_valid = [t for t in corrections if t.get('pnl_correction') is not None]
print(f"  Count (pnl_correction not None): {len(corrections_valid)}")
correction_pnl = sum(float(t['pnl_correction']) for t in corrections_valid)
print(f"  Sum of pnl_correction: ${correction_pnl:.2f}")
for t in corrections_valid:
    print(f"    ticker={t.get('ticker')} pnl_correction={t.get('pnl_correction')} logged_pnl={t.get('logged_pnl')} reason={t.get('reason','')[:60]}")

# === STEP 3: Compute closed P&L (exact replica of compute_closed_pnl_from_logs) ===
print(f"\n=== CLOSED P&L COMPUTATION (replicating compute_closed_pnl_from_logs) ===")
total_pnl = 0.0
for t in all_records:
    action = t.get('action')
    if action in ('exit', 'settle') and t.get('pnl') is not None:
        total_pnl += float(t['pnl'])
    elif action == 'exit_correction' and t.get('pnl_correction') is not None:
        total_pnl += float(t['pnl_correction'])

closed_pnl = round(total_pnl, 2)
print(f"  exits pnl:       ${exit_pnl:.2f}")
print(f"  settles pnl:     ${settle_pnl:.2f}")
print(f"  corrections pnl: ${correction_pnl:.2f}")
print(f"  TOTAL closed P&L: ${closed_pnl:.2f}")

# === STEP 4: Deposits ===
print(f"\n=== DEPOSITS ===")
deposits = []
if DEPOSITS_FILE.exists():
    for line in DEPOSITS_FILE.read_text(encoding='utf-8').strip().splitlines():
        try:
            d = json.loads(line)
            deposits.append(d)
        except Exception:
            pass

total_deposits = sum(d.get('amount', 0) for d in deposits)
print(f"  Deposit records: {len(deposits)}")
for d in deposits:
    print(f"    {d.get('date')} | ${d.get('amount')} | {d.get('note','')}")
print(f"  Total deposits: ${total_deposits:.2f}")

# === STEP 5: Capital ===
print(f"\n=== FINAL CAPITAL ===")
capital = round(total_deposits + closed_pnl, 2)
print(f"  Deposits:    ${total_deposits:.2f}")
print(f"  Closed P&L:  ${closed_pnl:.2f}")
print(f"  CAPITAL:     ${capital:.2f}")

# === STEP 6: Check for _invalid markers in the data ===
print(f"\n=== CHECKING FOR _INVALID MARKERS ===")
invalid_records = [t for t in all_records if '_invalid' in str(t.get('action','')) or t.get('invalid') == True]
print(f"  Records with '_invalid' in action or invalid=True: {len(invalid_records)}")
for t in invalid_records[:10]:
    print(f"    ticker={t.get('ticker')} action={t.get('action')} pnl={t.get('pnl')} file={t.get('_file')}")

# === STEP 7: Duplicate (ticker, side) settle analysis (matches dashboard accumulation logic) ===
print(f"\n=== DASHBOARD DE-DUP ANALYSIS (ticker, side) for settle/exit ===")
close_by_key = defaultdict(list)
for t in all_records:
    if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
        key = (t.get('ticker',''), t.get('side',''))
        close_by_key[key].append(float(t['pnl']))

dupes = {k: v for k, v in close_by_key.items() if len(v) > 1}
if dupes:
    print(f"  Found {len(dupes)} (ticker, side) pairs with MULTIPLE close records:")
    for k, vs in dupes.items():
        print(f"    {k[0]} | side={k[1]} | pnls={vs} | sum={sum(vs):.2f}")
    print(f"  NOTE: dashboard accumulates these — result is same as raw sum")
else:
    print(f"  No duplicates — all (ticker, side) pairs are unique. Raw sum = de-dup sum.")

# === STEP 8: pnl_cache.json removed — P&L computed live from logs ===
print(f"\n=== pnl_cache.json REMOVED — single source of truth is compute_closed_pnl_from_logs() ===")

print(f"\n{'='*60}")
print(f"ONE NUMBER: Capital = ${capital:.2f}")
print(f"{'='*60}")
