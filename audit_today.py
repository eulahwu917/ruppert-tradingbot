import json
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

PDT = timezone(timedelta(hours=-7))
trades_file = 'environments/demo/logs/trades/trades_2026-04-04.jsonl'

records = []
with open(trades_file) as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

buys = [r for r in records if r.get('action') == 'buy']
exits = [r for r in records if r.get('action') == 'exit']
settles = [r for r in records if r.get('action') == 'settle']

print(f'Total records: {len(records)}')
print(f'Buy records: {len(buys)}')
print(f'Exit records: {len(exits)}')
print(f'Settle records: {len(settles)}')

# PNL on exits
exits_with_pnl = [r for r in exits if r.get('pnl') is not None]
exits_no_pnl = [r for r in exits if r.get('pnl') is None]
settles_with_pnl = [r for r in settles if r.get('pnl') is not None]
print(f'Exits with pnl: {len(exits_with_pnl)}')
print(f'Exits without pnl: {len(exits_no_pnl)}')
print(f'Settles with pnl: {len(settles_with_pnl)}')

# Duplicate trade_ids
all_ids = [r.get('trade_id') for r in records]
id_counts = Counter(all_ids)
dups = {k: v for k, v in id_counts.items() if v > 1}
print(f'Duplicate trade_ids: {len(dups)}')
if dups:
    for tid, cnt in list(dups.items())[:5]:
        print(f'  {tid}: {cnt} times')

# Orphaned exits
buy_ids = {r.get('trade_id') for r in buys}
exit_ids = {r.get('trade_id') for r in exits}
settle_ids = {r.get('trade_id') for r in settles}
orphaned = exit_ids - buy_ids
print(f'Orphaned exits (exit with no matching buy by trade_id): {len(orphaned)}')
if orphaned:
    for oid in list(orphaned)[:5]:
        ex = next(r for r in exits if r.get('trade_id') == oid)
        ticker = ex.get('ticker')
        ts = ex.get('timestamp')
        print(f'  {oid}: {ticker} @ {ts}')

# Buys with no exit/settle
unmatched_buys = buy_ids - exit_ids - settle_ids
print(f'Open positions (buys with no exit/settle): {len(unmatched_buys)}')

print()
print('=== P&L CALCULATION ===')
# Canonical: sum pnl on exits where pnl is not None
total_pnl = sum(r['pnl'] for r in exits if r.get('pnl') is not None)
print(f'Total closed P&L (exit records, pnl not None): ${total_pnl:.4f}')

# Include settles
settle_pnl = sum(r['pnl'] for r in settles if r.get('pnl') is not None)
print(f'Settle P&L: ${settle_pnl:.4f}')
print(f'Total P&L (exits + settles): ${total_pnl + settle_pnl:.4f}')

print()
print('=== WIN/LOSS BREAKDOWN ===')
closed_pnls = [r['pnl'] for r in exits + settles if r.get('pnl') is not None]
wins = [p for p in closed_pnls if p > 0]
losses = [p for p in closed_pnls if p < 0]
zeros = [p for p in closed_pnls if p == 0]
print(f'Closed trades: {len(closed_pnls)}')
print(f'Wins (pnl > 0): {len(wins)}')
print(f'Losses (pnl < 0): {len(losses)}')
print(f'Zero pnl: {len(zeros)}')
if len(closed_pnls) > 0:
    win_rate = len(wins) / len(closed_pnls) * 100
    print(f'Win rate: {win_rate:.1f}%')
if wins:
    print(f'Avg win: ${sum(wins)/len(wins):.4f}')
    print(f'Largest win: ${max(wins):.4f}')
if losses:
    print(f'Avg loss: ${sum(losses)/len(losses):.4f}')
    print(f'Largest loss: ${min(losses):.4f}')

print()
print('=== SANITY CHECKS ===')
# Exit prices
all_exit_prices = [r.get('exit_price') for r in exits + settles if r.get('exit_price') is not None]
zero_prices = [p for p in all_exit_prices if p == 0]
over_dollar = [p for p in all_exit_prices if p > 100]  # prices in cents
print(f'Exit prices: min={min(all_exit_prices) if all_exit_prices else "N/A"}, max={max(all_exit_prices) if all_exit_prices else "N/A"}')
print(f'Zero exit prices: {len(zero_prices)}')
print(f'Exit prices > 100 (>$1.00): {len(over_dollar)}')

# PNL range check
all_pnls = [r['pnl'] for r in records if r.get('pnl') is not None]
print(f'PNL range: min=${min(all_pnls):.4f}, max=${max(all_pnls):.4f}')

# Timestamps
now_utc = datetime.now(timezone.utc)
future_records = []
for r in records:
    ts_str = r.get('timestamp', '')
    try:
        if 'T' in ts_str:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        if ts > now_utc + timedelta(minutes=5):
            future_records.append(r)
    except Exception as e:
        print(f'  TS parse error: {e} for {ts_str}')

print(f'Future timestamps: {len(future_records)}')

# Check for positions open > 24h
print()
print('=== OPEN POSITIONS DETAIL ===')
for tid in sorted(unmatched_buys):
    buy = next(r for r in buys if r.get('trade_id') == tid)
    ticker = buy.get('ticker', '')
    ts_str = buy.get('timestamp', '')
    entry = buy.get('entry_price')
    contracts = buy.get('contracts')
    size = buy.get('size_dollars')
    print(f'  OPEN: {ticker} | entry={entry}c | contracts={contracts} | ${size} | ts={ts_str}')

print()
print('=== EXITS WITH NO PNL (may indicate bug) ===')
for r in exits_no_pnl[:10]:
    print(f'  {r.get("trade_id")[:8]}... | {r.get("ticker")} | action_detail={r.get("action_detail")} | ts={r.get("timestamp")}')
