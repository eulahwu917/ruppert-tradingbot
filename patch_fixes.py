import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
api = Path('dashboard/api.py').read_text(encoding='utf-8')
idx = api.find('lp = m.get(\'last_price\')')
print(repr(api[idx-100:idx+300]))
