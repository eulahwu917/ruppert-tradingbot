import json, os, glob
log_dir = r'C:\Users\David Wu\.openclaw\workspace\ruppert-tradingbot-demo\logs'
files = sorted(glob.glob(os.path.join(log_dir, 'trades_*.jsonl')))
if files:
    print(f"Log: {files[-1]}")
    for line in open(files[-1], encoding='utf-8'):
        t = json.loads(line)
        if t.get('action') == 'buy':
            print(f"  {t['ticker']} {t.get('side','?').upper()} @ {t.get('entry_price')}c | edge={t.get('edge')} | ${t.get('size_dollars')}")
else:
    print("No trade logs found")
