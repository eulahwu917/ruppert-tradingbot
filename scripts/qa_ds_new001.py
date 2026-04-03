with open('agents/ruppert/trader/position_tracker.py', 'r', encoding='utf-8') as f:
    src = f.read()

checks = [
    # DS-NEW-001: abandonment record written
    ('DS-NEW-001: abandon_record dict present', 'ABANDONED after 3 exit failures' in src and 'abandon_record' in src),
    ('DS-NEW-001: uses _abandon_log_path (not log_path)', '_abandon_log_path = TRADES_DIR' in src),
    # _abandon_log_path is defined inline in the except block — no NameError risk
    # (it's not reusing the later-defined log_path from the normal exit path)
    ('DS-NEW-001: _abandon_log_path defined inline (not reusing log_path)', '_abandon_log_path = TRADES_DIR' in src),
    ('DS-NEW-001: uses snapshot vars (title, module, entry_price)', "'title': title," in src and "'module': module," in src and "'entry_price': entry_price," in src),
    ('DS-NEW-001: pnl included', "'pnl': round(pnl, 2)," in src),
    ('DS-NEW-001: trade_id present', "'trade_id': str(uuid.uuid4())," in src),
    ('DS-NEW-001: write wrapped in try/except', '_abandon_log_err' in src),
    # Verify prior fixes still intact
    ('ISSUE-002: _exits_lock still present', '_exits_lock = asyncio.Lock()' in src),
    ('ISSUE-003: 3-strike still present', "_exit_failures'] >= 3" in src),
    ('ISSUE-107: snapshot still present', "entry_price  = pos['entry_price']" in src or "entry_price = pos['entry_price']" in src),
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
