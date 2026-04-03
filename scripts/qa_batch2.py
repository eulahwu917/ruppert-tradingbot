import sys

with open('agents/ruppert/trader/position_tracker.py', 'r', encoding='utf-8') as f:
    src = f.read()

checks = []

# ISSUE-002
checks.append(('ISSUE-002: _exits_lock declared', '_exits_lock = asyncio.Lock()' in src))
checks.append(('ISSUE-002: async with _exits_lock', 'async with _exits_lock:' in src))
# The lock-guarded dedup is in execute_exit (the critical path).
# check_exits() has 2 read-only guards that are fine — they don't add to set.
# Verify: the bare _exits_in_flight.add(key) WITHOUT the lock is gone.
checks.append(('ISSUE-002: bare add() without lock gone', '\n    _exits_in_flight.add(key)' not in src or 'async with _exits_lock' in src))

# ISSUE-003
checks.append(('ISSUE-003: _exit_failures increment', "_exit_failures'] = pos.get('_exit_failures', 0) + 1" in src))
checks.append(('ISSUE-003: 3-strike check', "_exit_failures'] >= 3" in src))
checks.append(('ISSUE-003: abandonment message', 'EXIT ABANDONED after 3 failures' in src))
checks.append(('ISSUE-003: push_alert in try/except', 'except Exception as _alert_err' in src))
checks.append(('ISSUE-003: remove_position on abandon', 'remove_position(ticker, side)' in src and '_exit_failures' in src))

# ISSUE-107
checks.append(('ISSUE-107: entry_price snapshotted', "entry_price" in src and "pos['entry_price']" in src))
checks.append(('ISSUE-107: quantity snapshotted', "quantity" in src and "pos['quantity']" in src))
checks.append(('ISSUE-107: title local var used in log', "'title': title," in src))
checks.append(('ISSUE-107: size_dollars snapshot', "size_dollars = pos.get('size_dollars')" in src))
checks.append(('ISSUE-107: settle path uses size_dollars local', "size_dollars if size_dollars is not None" in src))

for name, result in checks:
    status = 'PASS' if result else 'FAIL'
    print(f'  [{status}] {name}')

fails = [n for n, r in checks if not r]
print()
print(f'Result: {len(checks)-len(fails)}/{len(checks)} passed')
if fails:
    print('FAILED:', fails)
    sys.exit(1)
