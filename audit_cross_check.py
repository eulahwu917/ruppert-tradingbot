import json

# Manual calc matching compute_closed_pnl_from_logs() logic but only for today's file
total = 0.0
file = 'environments/demo/logs/trades/trades_2026-04-04.jsonl'
records = []
with open(file) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        records.append(t)
        if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
            total += float(t['pnl'])
        elif t.get('action') == 'exit_correction' and t.get('pnl_correction') is not None:
            total += float(t['pnl_correction'])

print(f'Today P&L (canonical method, exits+settles+corrections): ${total:.2f}')

corrections = [r for r in records if r.get('action') == 'exit_correction']
print(f'exit_correction records today: {len(corrections)}')

# Break down by action type
exit_total = sum(float(r['pnl']) for r in records if r.get('action') == 'exit' and r.get('pnl') is not None)
settle_total = sum(float(r['pnl']) for r in records if r.get('action') == 'settle' and r.get('pnl') is not None)
print(f'  Exits subtotal: ${exit_total:.2f}')
print(f'  Settles subtotal: ${settle_total:.2f}')

# Also verify the timestamp issue - are open position timestamps UTC or local?
print()
print('=== TIMESTAMP TIMEZONE CHECK ===')
# The 3 open positions have timestamps like 23:46, 23:47, 23:48
# Current time ~23:57 PDT = 06:57 UTC next day... hmm
# Let me check: timestamps appear to be local PDT time
from datetime import datetime, timezone, timedelta
PDT = timezone(timedelta(hours=-7))
now_utc = datetime.now(timezone.utc)
now_pdt = now_utc.astimezone(PDT)
print(f'Current UTC: {now_utc.strftime("%Y-%m-%d %H:%M:%S")}')
print(f'Current PDT: {now_pdt.strftime("%Y-%m-%d %H:%M:%S")}')

# The open positions with ts like "2026-04-04 23:46:49" - are these UTC or PDT?
# If PDT, age = ~11 min (brand new - normal, contract just opened)
# If UTC, age = ~7h (would be problematic)
# Given contracts like KXBTC15M-26APR050300-00 (05:00 UTC, 22:00 PDT), entry at 23:46 PDT makes sense
open_buys = [r for r in records if r.get('action') == 'buy']
exits_set = {(r.get('ticker'), r.get('side')) for r in records if r.get('action') in ('exit', 'settle')}
truly_open = [r for r in open_buys if (r.get('ticker'), r.get('side')) not in exits_set]
print(f'Open positions: {len(truly_open)}')
for r in truly_open:
    ts_str = r.get('timestamp', '')
    ticker = r.get('ticker', '')
    # Parse timestamp - assume PDT (local)
    try:
        ts_local = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        ts_as_pdt = ts_local.replace(tzinfo=PDT)
        age_min = (now_pdt - ts_as_pdt).total_seconds() / 60
        print(f'  {ticker} | ts={ts_str} PDT | age={age_min:.0f} min | entry={r.get("entry_price")}c')
    except:
        print(f'  {ticker} | ts={ts_str} (parse failed)')

# Settle records detail
print()
print('=== SETTLE RECORDS DETAIL ===')
settles = [r for r in records if r.get('action') == 'settle']
for r in settles:
    print(f'  {r.get("ticker")} | pnl={r.get("pnl")} | exit_price={r.get("exit_price")} | ts={r.get("timestamp")}')
