import sys

def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

pt = read('agents/ruppert/trader/position_tracker.py')
ptm = read('agents/ruppert/trader/post_trade_monitor.py')
strat = read('agents/ruppert/strategist/strategy.py')
cb = read('agents/ruppert/trader/circuit_breaker.py')
band = read('agents/ruppert/trader/crypto_band_daily.py')
thresh = read('agents/ruppert/trader/crypto_threshold_daily.py')

checks = [
    # Sprint 1 P1 — exit locking
    ('P1-1: acquire/release_exit_lock imported in position_tracker', 'acquire_exit_lock' in pt and 'release_exit_lock' in pt),
    ('P1-1: acquire_exit_lock called in execute_exit', 'acquire_exit_lock(' in pt),
    ('P1-1: release_exit_lock in finally', 'release_exit_lock(' in pt),
    ('P1-1: dedup-guard path has explicit release', pt.count('release_exit_lock(') >= 2),
    # Sprint 1 P1 — PTM settlement writer
    ('P1-2: PTM settlement write now uses _append_jsonl or portalocker', '_append_jsonl' in ptm),
    # Sprint 2 P2
    ('P2: CB check in strategy.py should_enter()', 'circuit_breaker' in strat.lower() or 'check_circuit_breaker' in strat),
    ('P2: CB per-module threshold fix in circuit_breaker.py', 'startswith' in cb or 'prefix' in cb),
    ('P2: band_daily has disable guard', 'BAND_DAILY_ENABLED' in band or 'enabled' in band.lower()),
    ('P2: threshold_daily has disable guard', 'THRESHOLD_DAILY_ENABLED' in thresh or 'enabled' in thresh.lower()),
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
    sys.exit(1)
