import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

old = """    const dir = sm.direction || 'neutral';
    const pct = sm.bull_pct ? Math.round(sm.bull_pct * 100) : '--';
    const colors = {bullish:'#4ade80', bearish:'#f87171', neutral:'#888'};
    smBadge.style.background = dir === 'bullish' ? '#1a2e1a' : dir === 'bearish' ? '#2e1a1a' : '#1e1e1e';
    smBadge.style.color = colors[dir] || '#888';
    smBadge.textContent = dir.toUpperCase() + ' (' + pct + '% bull, ' + sm.traders_sampled + ' traders)';"""

new = """    const dir = sm.direction || 'neutral';
    const colors = {bullish:'#4ade80', bearish:'#f87171', neutral:'#aaa'};
    smBadge.style.background = dir === 'bullish' ? '#1a2e1a' : dir === 'bearish' ? '#2e1a1a' : '#1e1e1e';
    smBadge.style.color = colors[dir] || '#aaa';
    const active = sm.active_positions != null ? sm.active_positions : sm.traders_sampled;
    const note = sm.active_positions === 0 ? 'sidelines' : (Math.round((sm.bull_pct||0.5)*100) + '% bull');
    smBadge.textContent = dir.toUpperCase() + ' — ' + note + ' (' + sm.traders_sampled + ' traders tracked)';"""

assert old in content, "SM badge JS not found"
content = content.replace(old, new)
open(path, 'w', encoding='utf-8').write(content)
print("Done")
