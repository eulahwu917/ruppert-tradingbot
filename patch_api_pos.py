import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/api.py'
c = open(path, encoding='utf-8').read()

old = """            'open_pnl':      0,
            'open_pnl_pct':  0,
            'pos_ratio':     pos_ratio,
            'source':        t.get('source','bot'),"""
new = """            'open_pnl':      0,
            'open_pnl_pct':  0,
            'pos_ratio':     pos_ratio,
            'noaa_prob':     t.get('noaa_prob'),
            'market_prob':   t.get('market_prob'),
            'edge':          t.get('edge'),
            'source':        t.get('source','bot'),"""

if old in c:
    c = c.replace(old, new)
    print("OK")
else:
    print("NOT FOUND")
    idx = c.find('open_pnl')
    print(repr(c[idx:idx+200]))

open(path, 'w', encoding='utf-8').write(c)
