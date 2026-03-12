import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
html = Path('dashboard/templates/index.html').read_text(encoding='utf-8')
idx = html.find("body: JSON.stringify({ticker, side, price_cents: priceCents})")
print(repr(html[idx:idx+80]))
