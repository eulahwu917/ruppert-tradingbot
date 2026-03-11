import sys
sys.stdout.reconfigure(encoding='utf-8')
content = open('dashboard/templates/index.html', encoding='utf-8').read()
# Show the full p-trades pane
idx = content.find('id="p-trades"')
print(content[idx:idx+1200])
print('\n--- loadTrades JS ---')
idx2 = content.find('async function loadTrades')
print(content[idx2:idx2+1000])
