import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

# Add b-bot and b-manual after b-sim
idx = content.find('.b-sim{')
end = content.find('}', idx) + 1
b_sim_block = content[idx:end]
print("b-sim block:", repr(b_sim_block))

new_badges = b_sim_block + '\n.b-bot{background:#1a1a2e;color:#818cf8;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;margin-left:5px;vertical-align:middle}\n.b-manual{background:#2e2a1a;color:#fbbf24;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;margin-left:5px;vertical-align:middle}'

content = content.replace(b_sim_block, new_badges, 1)
open(path, 'w', encoding='utf-8').write(content)
print("badge CSS: OK")
