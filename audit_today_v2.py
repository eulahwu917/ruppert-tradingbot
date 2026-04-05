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

print('=' * 60)
print('1. TRADE FILE INTEGRITY')
print('=' * 60)
print(f'Total records: {len(records)}')
print(f'Buy records: {len(buys)}')
print(f'Exit records: {len(exits)}')
print(f'Settle records: {len(settles)}')

# PNL field check
with_pnl = [r for r in records if r.get('pnl') is not None]
without_pnl = [r for r in records if r.get('pnl') is None]
print(f'Records with pnl set: {len(with_pnl)}')
print(f'Records without pnl (None/missing): {len(without_pnl)}')

# Note: trade_ids are unique per record (not shared between buy/exit)
# Link is via ticker+side
buy_ids = {r.get('trade_id') for r in buys}
exit_ids = {r.get('trade_id') for r in exits}
settle_ids = {r.get('trade_id') for r in settles}
all_ids = [r.get('trade_id') for r in records]
id_counts = Counter(all_ids)
dups = {k: v for k, v in id_counts.items() if v > 1}
print(f'Duplicate trade_ids (any record): {len(dups)}')
if dups:
    for tid, cnt in list(dups.items())[:5]:
        print(f'  {tid}: {cnt} times')

# Orphaned exits: exits with no matching buy by (ticker, side)
buy_keys = {(r.get('ticker'), r.get('side')) for r in buys}
exit_keys = [(r.get('ticker'), r.get('side'), r) for r in exits]
settle_keys = [(r.get('ticker'), r.get('side'), r) for r in settles]

orphaned_exits = [(t, s, r) for t, s, r in exit_keys if (t, s) not in buy_keys]
print(f'Orphaned exits (exit with no matching buy by ticker+side): {len(orphaned_exits)}')
if orphaned_exits:
    for t, s, r in orphaned_exits[:5]:
        print(f'  {t} ({s}) @ {r.get("timestamp")} | pnl={r.get("pnl")}')

# Open positions: buys with no exit or settle
closed_keys = {(r.get('ticker'), r.get('side')) for r in exits + settles}
open_buys = [r for r in buys if (r.get('ticker'), r.get('side')) not in closed_keys]
print(f'Open positions (buys with no exit/settle by ticker+side): {len(open_buys)}')

print()
print('=' * 60)
print('2. P&L CALCULATION')
print('=' * 60)
exit_pnl = sum(r['pnl'] for r in exits if r.get('pnl') is not None)
settle_pnl = sum(r['pnl'] for r in settles if r.get('pnl') is not None)
total_pnl = exit_pnl + settle_pnl
print(f'Exit P&L (sum of exit records with pnl): ${exit_pnl:.4f}')
print(f'Settle P&L (sum of settle records with pnl): ${settle_pnl:.4f}')
print(f'Total closed P&L: ${total_pnl:.4f}')

# Exits-only (canonical per task description)
print(f'Exits-only canonical total: ${exit_pnl:.4f}')

print()
print('=' * 60)
print('4. WIN/LOSS BREAKDOWN')
print('=' * 60)
closed_with_pnl = [(r, r['pnl']) for r in exits + settles if r.get('pnl') is not None]
pnls = [p for _, p in closed_with_pnl]
wins = [p for p in pnls if p > 0]
losses = [p for p in pnls if p < 0]
zeros = [p for p in pnls if p == 0]
print(f'Closed trades (with pnl): {len(pnls)}')
print(f'Wins (pnl > 0): {len(wins)}')
print(f'Losses (pnl < 0): {len(losses)}')
print(f'Zero pnl: {len(zeros)}')
if pnls:
    win_rate = len(wins) / len(pnls) * 100
    print(f'Win rate: {win_rate:.1f}%')
if wins:
    print(f'Avg win: ${sum(wins)/len(wins):.4f}')
    print(f'Largest win: ${max(wins):.4f}')
if losses:
    print(f'Avg loss: ${sum(losses)/len(losses):.4f}')
    print(f'Largest loss (worst): ${min(losses):.4f}')

# Largest win record
if wins:
    max_win = max(pnls)
    win_rec = next(r for r, p in closed_with_pnl if p == max_win)
    print(f'Largest win details: {win_rec.get("ticker")} @ {win_rec.get("timestamp")} | exit_price={win_rec.get("exit_price")}')

if losses:
    min_loss = min(pnls)
    loss_rec = next(r for r, p in closed_with_pnl if p == min_loss)
    print(f'Largest loss details: {loss_rec.get("ticker")} @ {loss_rec.get("timestamp")} | exit_price={loss_rec.get("exit_price")}')

print()
print('=' * 60)
print('5. SANITY CHECKS')
print('=' * 60)

# Exit prices
all_exit_prices = [r.get('exit_price') for r in exits + settles if r.get('exit_price') is not None]
zero_prices = [p for p in all_exit_prices if p == 0]
over_100 = [p for p in all_exit_prices if p > 100]
print(f'Exit price range: min={min(all_exit_prices) if all_exit_prices else "N/A"}c, max={max(all_exit_prices) if all_exit_prices else "N/A"}c')
print(f'Zero exit prices: {len(zero_prices)}')
print(f'Exit prices > 100 (invalid for Kalshi): {len(over_100)}')

# Zero-price exits with pnl check
zero_price_exits = [r for r in exits + settles if r.get('exit_price') == 0]
print(f'Zero-price exits: {len(zero_price_exits)}')
for r in zero_price_exits[:3]:
    print(f'  {r.get("ticker")} | pnl={r.get("pnl")} | action_detail={r.get("action_detail")}')

# PNL range
all_pnls = [r['pnl'] for r in records if r.get('pnl') is not None]
print(f'PNL range: min=${min(all_pnls):.4f}, max=${max(all_pnls):.4f}')

# Absurdly large pnl check (>$500 or <-$500 would be suspect for ~$100 positions)
absurd_pnl = [(r, r['pnl']) for r in records if r.get('pnl') is not None and abs(r['pnl']) > 500]
print(f'Absurdly large pnl (>|$500|): {len(absurd_pnl)}')

# Timestamps
now_utc = datetime.now(timezone.utc)
now_pdt = now_utc.astimezone(PDT)
print(f'Current time (PDT): {now_pdt.strftime("%Y-%m-%d %H:%M:%S %Z")}')

future_records = []
bad_ts = []
for r in records:
    ts_str = r.get('timestamp', '')
    try:
        if 'T' in ts_str:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        if ts > now_utc + timedelta(minutes=5):
            future_records.append((r, ts))
    except Exception as e:
        bad_ts.append((r, str(e)))

print(f'Future timestamps: {len(future_records)}')
print(f'Unparseable timestamps: {len(bad_ts)}')

# Old open positions (open for > 6h - may be stale from yesterday)
old_open = []
for r in open_buys:
    ts_str = r.get('timestamp', '')
    try:
        if 'T' in ts_str:
            ts = datetime.fromisoformat(ts_str)
        else:
            ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now_utc - ts).total_seconds() / 3600
        if age_hours > 6:
            old_open.append((r, age_hours))
    except:
        pass

print(f'Open positions older than 6h: {len(old_open)}')
for r, age in sorted(old_open, key=lambda x: -x[1])[:5]:
    print(f'  {r.get("ticker")} | age={age:.1f}h | entry={r.get("entry_price")}c | ts={r.get("timestamp")}')

print()
print('=' * 60)
print('6. CURRENT OPEN POSITIONS')
print('=' * 60)
print(f'Open positions: {len(open_buys)}')
total_invested = sum(r.get('size_dollars', 0) for r in open_buys)
print(f'Total dollars invested (open): ${total_invested:.2f}')
print()

# Group by module/asset
by_module = defaultdict(list)
for r in open_buys:
    module = r.get('module', 'unknown')
    by_module[module].append(r)
for mod, recs in sorted(by_module.items()):
    invested = sum(r.get('size_dollars', 0) for r in recs)
    print(f'  {mod}: {len(recs)} positions | ${invested:.2f} invested')
