import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('logs/trades_2026-03-10.jsonl', encoding='utf-8') as f:
    trades = [json.loads(l) for l in f]
print(f'Total trades: {len(trades)}')
for t in trades:
    side = t.get('side','?')
    mp = t.get('market_prob', 0)
    entry = round((1 - mp) * 100) if side == 'no' else round(mp * 100)
    print(f"{t['ticker'][:35]} | {side} | entry={entry}c | contracts={t.get('contracts')} | ${t.get('size_dollars')}")
