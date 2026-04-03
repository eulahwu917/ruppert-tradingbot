with open('agents/ruppert/data_analyst/ws_feed.py', 'r', encoding='utf-8') as f:
    src = f.read()

checks = [
    ('Patch A: DAILY_CAP_RATIO monitoring comment', 'Monitor daily exposure closely for first 3 live days' in src),
    ('Patch B: import error log fixed', 'window IS marked evaluated, REST fallback also blocked' in src),
    ('Patch B: old lying log removed', 'window NOT marked evaluated so REST fallback can recover' not in src),
    ('Patch C: log_trade thread-safety warning', 'WARNING: log_trade() runs in a thread executor here' in src),
    ('Core Fix 1: DAILY_CAP_RATIO still in use', 'DAILY_CAP_RATIO' in src and 'getattr(config,' in src),
    ('Core Fix 2: _window_eval_lock present', '_window_eval_lock = asyncio.Lock()' in src),
    ('Core Fix 3: fallback uses lock', src.count('async with _window_eval_lock:') >= 2),
    ('Core Fix 4: run_in_executor present', 'run_in_executor' in src),
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
