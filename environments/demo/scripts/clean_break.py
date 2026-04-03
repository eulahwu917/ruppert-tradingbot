"""
clean_break.py — Strip contaminated pre-clean-slate settle records from trades_2026-04-02.jsonl
                  and remove the corrective deposit from demo_deposits.jsonl
"""
import json, os, shutil
from pathlib import Path

demo = Path(r'C:\Users\David Wu\.openclaw\workspace\environments\demo')
log = demo / 'logs/trades/trades_2026-04-02.jsonl'
archive_dir = demo / 'logs/archive'
archive_dir.mkdir(exist_ok=True)

# Read all records
records = [json.loads(l) for l in log.read_text().strip().split('\n') if l.strip()]

# Build set of buy (ticker, side) pairs that exist in today's log
buys = {(r.get('ticker'), r.get('side')) for r in records if r.get('action') == 'buy'}

contaminated = []
clean = []

for r in records:
    if r.get('action') == 'settle':
        ticker = r.get('ticker', '')
        side = r.get('side', '')
        entry_date = r.get('entry_date') or r.get('date') or ''
        is_march = 'MAR31' in ticker or 'APR01' in ticker
        is_old_date = entry_date < '2026-04-02' if entry_date else False
        is_orphan = (ticker, side) not in buys
        if is_march or is_old_date or is_orphan:
            contaminated.append(r)
        else:
            clean.append(r)
    else:
        clean.append(r)

contam_pnl = round(sum(r.get('pnl', 0) or 0 for r in contaminated), 2)
print('Contaminated records removed:', len(contaminated))
print('Contaminated P&L stripped:', contam_pnl)
print('Clean records kept:', len(clean))

# 1. Archive original
archive_path = archive_dir / 'trades_2026-04-02.poisoned.jsonl'
shutil.copy2(log, archive_path)
print('Archived original to:', archive_path)

# 2. Write clean file atomically
tmp = str(log) + '.tmp'
with open(tmp, 'w') as f:
    for r in clean:
        f.write(json.dumps(r) + '\n')
os.replace(tmp, log)
print('Clean trade log written.')

# 3. Remove corrective deposit from demo_deposits.jsonl
deposits_path = demo / 'logs/demo_deposits.jsonl'
deposits = [json.loads(l) for l in deposits_path.read_text().strip().split('\n') if l.strip()]
original_count = len(deposits)
# Remove the corrective deposit entry
clean_deposits = [d for d in deposits if 'corrective' not in d.get('note', '').lower() and 'clean-slate' not in d.get('note', '').lower()]
removed_deposits = original_count - len(clean_deposits)
tmp_d = str(deposits_path) + '.tmp'
with open(tmp_d, 'w') as f:
    for d in clean_deposits:
        f.write(json.dumps(d) + '\n')
os.replace(tmp_d, deposits_path)
print('Deposits cleaned. Removed', removed_deposits, 'corrective deposit(s).')
print('Remaining deposits:')
for d in clean_deposits:
    print(' ', d)

print()
print('Done. Clean break complete.')

# ── CB state refresh (DS recommendation) ─────────────────────────────────────
# After any trade log mutation, the CB's cached global state goes stale.
# Refresh it now so the CB reflects the true post-cleanup capital.
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    import agents.ruppert.trader.circuit_breaker as _cb
    from agents.ruppert.data_scientist.capital import get_capital as _get_capital
    _cb.update_global_state(_get_capital())
    print('[CB] Global state refreshed after cleanup.')
except Exception as _cb_refresh_err:
    print(f'[CB] State refresh failed (non-fatal): {_cb_refresh_err}')
# ── End CB state refresh ──────────────────────────────────────────────────────
