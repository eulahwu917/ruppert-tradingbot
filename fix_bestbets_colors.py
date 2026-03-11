import sys
sys.stdout.reconfigure(encoding='utf-8')

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

# 1. Fix CSS classes
old_css = ".bb-rationale { font-size: 11px; color: #2a2a2a; line-height: 1.5; }"
new_css = ".bb-rationale { font-size: 11px; color: #666; line-height: 1.5; }"
assert old_css in content, "bb-rationale CSS not found"
content = content.replace(old_css, new_css)

# 2. Fix inline colors in renderBestBets()
# "Ruppert's est." label — was #2a2a2a (invisible)
content = content.replace(
    '<span style="font-size:10px;color:#2a2a2a">Ruppert\'s est.</span>',
    '<span style="font-size:10px;color:#555">Ruppert\'s est.</span>'
)
# "Mkt: xx%" label — was #444 (barely visible)
content = content.replace(
    '<span style="font-size:10px;color:#444">Mkt: ${(b.market_prob*100||0).toFixed(0)}%</span>',
    '<span style="font-size:10px;color:#888">Mkt: ${(b.market_prob*100||0).toFixed(0)}%</span>'
)

# 3. Fix empty-state message colors (was #1a1a1a = invisible)
content = content.replace(
    "'<div class=\"loading\" style=\"color:#1a1a1a;padding:32px;\">No Best Bets found yet.<br><span style=\"color:#1a1a1a;font-size:10px;\">Best Bets appear when Ruppert finds 60%+ confidence + 15%+ edge on geo or economics markets.<br>Run the bot to populate.</span></div>'",
    "'<div class=\"loading\" style=\"color:#888;padding:32px;\">No Best Bets found yet.<br><span style=\"color:#555;font-size:10px;\">Best Bets appear when Ruppert finds 60%+ confidence + 15%+ edge on geo or economics markets.<br>Run the bot to populate.</span></div>'"
)

# 4. Also fix bb-title color if it's missing or dark
if '.bb-title {' in content:
    import re
    content = re.sub(
        r'(\.bb-title \{[^}]*?)(color\s*:\s*#[0-9a-fA-F]{3,6}\s*;)',
        lambda m: m.group(1) + 'color: #e0e0e0;',
        content
    )
else:
    # Add bb-title color to CSS
    content = content.replace(
        '.bb-rationale { font-size: 11px; color: #666; line-height: 1.5; }',
        '.bb-title { color: #e0e0e0; font-size: 13px; font-weight: 600; margin-bottom: 6px; line-height: 1.4; }\n.bb-rationale { font-size: 11px; color: #666; line-height: 1.5; }'
    )

open(path, 'w', encoding='utf-8').write(content)
print("Fixed. Size:", len(content))
