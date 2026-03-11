"""
Omnibus dashboard patch:
1. White font on all trade/position titles
2. Move Crypto tab to position #2 (after Weather)
3. Fix Trade History table layout (unstick right-side columns)
4. Fix Crypto tab rendering (wire to api)
"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()
orig_size = len(content)

# ─── 1. White font on trade titles everywhere ──────────────────────────────────
# Position table: the <a> link in the title cell
# Currently likely inherits or has a colored style — set explicitly to #fff
# Fix .col-title a color
if '.col-title a' in content:
    content = re.sub(r'(\.col-title a\s*\{[^}]*?)(color\s*:\s*[^;]+;)', r'\1color: #fff;', content)
    print("Fixed .col-title a color")
else:
    # Add rule
    content = content.replace(
        '.col-title { display:flex; align-items:center; gap:6px; }',
        '.col-title { display:flex; align-items:center; gap:6px; }\n.col-title a { color: #fff !important; text-decoration: none; }'
    )
    if '.col-title {' in content:
        content = re.sub(
            r'(\.col-title\s*\{[^}]*?\})',
            r'\1\n.col-title a { color: #fff !important; text-decoration: none; }',
            content, count=1
        )
        print("Added .col-title a rule")

# Also fix any inline color on title links
content = content.replace(
    'style="color:#818cf8;text-decoration:none;"',
    'style="color:#fff;text-decoration:none;"'
)

# Fix bb-title color (Best Bets card titles)
content = re.sub(r'(\.bb-title\s*\{[^}]*?)(color\s*:\s*[^;]+;)', r'\1color: #fff;', content)
print("Fixed .bb-title color")

# Trade history title links — handled by general tbl a rule below
# Add global rule for table title links
tbl_link_rule = '\n.tbl td a { color: #fff !important; text-decoration: none; }\n'
if '.tbl td a' not in content:
    # Insert after .tbl definition
    content = re.sub(r'(\.tbl\s*\{[^}]*?\})', r'\1' + tbl_link_rule, content, count=1)
    print("Added .tbl td a rule")

# ─── 2. Move Crypto tab to position #2 (after Weather) ───────────────────────
# Current order: Weather | Best Bets | Geo | Crypto
# Target order:  Weather | Crypto | Best Bets | Geo

WEATHER_BTN = "      <button class=\"tab on\" onclick=\"swS('weather',this)\">&#x1F327; Weather</button>"
BESTBETS_BTN = "      <button class=\"tab\" onclick=\"swS('bestbets',this)\">&#x2B50; Best Bets</button>"
GEO_BTN = "      <button class=\"tab\" onclick=\"swS('geo',this)\">&#x1F30D; Geopolitical</button>"
CRYPTO_BTN = "      <button class=\"tab\" onclick=\"swS('crypto',this)\">&#x20BF; Crypto</button>"

old_order = f"{WEATHER_BTN}\n{BESTBETS_BTN}\n{GEO_BTN}\n{CRYPTO_BTN}"
new_order = f"{WEATHER_BTN}\n{CRYPTO_BTN}\n{BESTBETS_BTN}\n{GEO_BTN}"

if old_order in content:
    content = content.replace(old_order, new_order)
    print("Reordered tabs: Weather > Crypto > Best Bets > Geo")
else:
    print("WARNING: Tab order string not found — check spacing")

# ─── 3. Fix Trade History table ───────────────────────────────────────────────
# Find the history table and ensure it has same resizable/fixed layout as positions
# Look for the history table
hist_idx = content.find('id="hist-tbl"')
if hist_idx < 0:
    # Find history section by looking for the pane
    hist_idx = content.find('id="p-hist"')
    print(f"History pane at: {hist_idx}")
    # Show context
    print(content[hist_idx:hist_idx+600])
else:
    print(f"hist-tbl at: {hist_idx}")

# Find the history table thead
# Look for common history column headers
hist_table_start = content.find('<table', hist_idx) if hist_idx > 0 else -1
if hist_table_start > 0:
    hist_table_end = content.find('</table>', hist_table_start) + 8
    hist_table = content[hist_table_start:hist_table_end]
    print("History table found, length:", len(hist_table))
    print("First 400 chars:", hist_table[:400])

    # Replace the history table with a properly structured one
    new_hist_table = '''<div class="t-scroll"><table class="tbl" id="hist-tbl" style="table-layout:fixed;width:100%">
          <thead><tr>
            <th class="l" style="width:260px;min-width:180px">Trade<div class="resize-h"></div></th>
            <th class="ca" style="width:70px">Date<div class="resize-h"></div></th>
            <th class="ca" style="width:55px">Side<div class="resize-h"></div></th>
            <th class="ra" style="width:55px">Qty<div class="resize-h"></div></th>
            <th class="ra" style="width:55px">Entry<div class="resize-h"></div></th>
            <th class="ra" style="width:55px">Exit<div class="resize-h"></div></th>
            <th class="ra" style="width:70px">Cost<div class="resize-h"></div></th>
            <th class="ra" style="width:90px">P&amp;L<div class="resize-h"></div></th>
            <th class="ca" style="width:70px">Result<div class="resize-h"></div></th>
          </tr></thead>
          <tbody id="hist-b"><tr><td colspan="9" class="loading">Loading history...</td></tr></tbody>
        </table></div>'''

    content = content[:hist_table_start] + new_hist_table + content[hist_table_end:]
    print("History table replaced with fixed layout")

# ─── 4. Update loadTrades() JS to render new history columns ────────────────
# Find the loadTrades/renderHistory function
hist_js_idx = content.find('function loadTrades')
if hist_js_idx < 0:
    hist_js_idx = content.find('hist-b')
    print(f"hist-b reference at: {hist_js_idx}")
    print(content[max(0,hist_js_idx-200):hist_js_idx+600])

print(f"\nFinal size: {len(content)} (was {orig_size})")
open(path, 'w', encoding='utf-8').write(content)
print("Saved.")
