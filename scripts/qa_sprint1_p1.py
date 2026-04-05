with open('agents/ruppert/trader/position_tracker.py', 'r', encoding='utf-8') as f:
    pt = f.read()
with open('agents/ruppert/trader/post_trade_monitor.py', 'r', encoding='utf-8') as f:
    ptm = f.read()

checks = [
    # position_tracker.py
    ('PT: acquire_exit_lock imported', 'acquire_exit_lock, release_exit_lock,' in pt),
    ('PT: acquire_exit_lock called before asyncio guard', 'if not acquire_exit_lock(ticker, side):' in pt),
    ('PT: release_exit_lock on dedup-guard return', 'release_exit_lock(ticker, side)' in pt),
    ('PT: release_exit_lock in finally', pt.count('release_exit_lock(ticker, side)') >= 2),
    ('PT: _exits_lock asyncio guard still present', 'async with _exits_lock:' in pt),
    ('PT: _exits_in_flight guard still present', '_exits_in_flight' in pt),
    # post_trade_monitor.py
    ('PTM: acquire_exit_lock imported', 'acquire_exit_lock, release_exit_lock' in ptm),
    ('PTM: settlement write uses _append_jsonl', '_append_jsonl(log_path, settle_record)' in ptm),
    ('PTM: raw open+write for settle record gone', "with open(log_path, 'a'" not in ptm or '_append_jsonl' in ptm),
]

all_pass = True
for name, result in checks:
    status = 'PASS' if result else 'FAIL'
    if not result:
        all_pass = False
    print(f'  [{status}] {name}')

fails = [n for n, r in checks if not r]
print()
print(f'Result: {len(checks)-len(fails)}/{len(checks)} passed')
if not all_pass:
    import sys; sys.exit(1)
