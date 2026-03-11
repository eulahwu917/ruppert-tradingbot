import sys
sys.stdout.reconfigure(encoding='utf-8')
# Test is_settled_ticker directly
import re
from datetime import date

def is_settled_ticker(ticker):
    today = date.today()
    months = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
              'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
    parts = ticker.upper().split('-')
    for part in parts:
        m = re.match(r'^(\d{2})([A-Z]{3})(\d{2})$', part)
        if m:
            yy, mon, dd = m.groups()
            month_num = months.get(mon)
            if month_num:
                try:
                    mkt_date = date(2000 + int(yy), month_num, int(dd))
                    if mkt_date < today:
                        return True
                except Exception:
                    pass
    return False

tests = ['KXHIGHMIA-26MAR10-B84.5','KXHIGHMIA-26MAR11-B83.5','KXCPI-26JUN-T0.0','KXETH-26MAR1117-B2030']
for t in tests:
    print(f"  {t:40} settled={is_settled_ticker(t)}")

# Now test positions endpoint directly
import sys; sys.path.insert(0,'.')
sys.path.insert(0, 'dashboard')
try:
    from dashboard.api import get_active_positions
    result = get_active_positions()
    print(f"\nPositions: {len(result)}")
    for p in result:
        print(f"  {p['ticker']}")
except Exception as e:
    import traceback; traceback.print_exc()
