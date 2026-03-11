from pathlib import Path
import re

code = Path('dashboard/templates/index.html').read_text(encoding='utf-8', errors='ignore')

# Check if opnl, dpnl, bot-pnl, man-pnl IDs exist in HTML
for target_id in ['opnl', 'opnl-pct', 'dpnl', 'dpnl-pct', 'bot-pnl', 'bot-pnl-pct', 'man-pnl', 'man-pnl-pct', 'winrate', 'av', 'bp']:
    found = f'id="{target_id}"' in code or f"id='{target_id}'" in code
    print(f"  id={target_id:20} {'FOUND' if found else 'MISSING'}")
