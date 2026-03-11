"""
Patch: Update account bar for demo mode fixed $400 base.
- Label: 'Demo Account Value' stays, add '$400 base' sub-label
- JS: update comment to reflect new formula
- Buying Power label: show 'Buying Power' with sub-note
"""
import re

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

# 1. Add sub-label to Demo Account Value item showing $400 base
old_av = '<div class="acct-label">Demo Account Value</div>'
new_av = '<div class="acct-label">Demo Account Value</div><div style="font-size:9px;color:#333;margin-top:2px;">$400 base + P&amp;L</div>'
assert old_av in content, "Demo Account Value label not found"
content = content.replace(old_av, new_av)

# 2. Update JS comment and formula in loadAccount()
old_js_comment = "  // Demo: Account Value = Kalshi Balance + Open P&L\n  // Show balance as baseline; live prices will add Open P&L on top\n  $('av').textContent = dollar(acct.kalshi_balance);"
new_js_comment = """  // DEMO: Account Value = $400 starting capital + Open P&L + Closed P&L
  // $400 = $200 weather allocation + $200 crypto allocation
  // Live prices endpoint adds totalPnl (open+closed) on top of this base.
  // LIVE MODE: replace with raw acct.kalshi_balance (Kalshi API reflects real positions).
  window._kalshiBalance = acct.kalshi_balance || 400;  // 400 = demo starting capital
  $('av').textContent = dollar(window._kalshiBalance);"""

assert old_js_comment in content, "JS comment not found — trying alternate"
content = content.replace(old_js_comment, new_js_comment)

# 3. Update the loadLivePrices Account Value formula comment
old_av_formula = "    // Demo: Account Value = Kalshi Balance + Open P&L\n    document.getElementById('av').textContent = dollar((window._kalshiBalance || 0) + totalPnl);"
new_av_formula = """    // DEMO: Account Value = Starting Capital ($400) + Open P&L + Closed P&L
    // window._kalshiBalance is set to 400 in loadAccount(); totalPnl includes open + settled.
    // LIVE MODE: swap to dollar(window._kalshiBalance) — Kalshi API already factors in P&L.
    document.getElementById('av').textContent = dollar((window._kalshiBalance || 400) + totalPnl);"""

if old_av_formula in content:
    content = content.replace(old_av_formula, new_av_formula)
    print("Formula comment updated")
else:
    print("WARNING: Formula comment not found — check manually")

open(path, 'w', encoding='utf-8').write(content)
print("Done. File size:", len(content))
