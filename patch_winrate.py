import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

old = "  $('ts').textContent = 'Updated ' + new Date().toLocaleTimeString();\n}"
new = """  // Win Rate: populates once contracts settle
  const wrEl = document.getElementById('winrate');
  if (wrEl && acct.win_rate !== undefined) {
    wrEl.style.color = acct.win_rate >= 50 ? '#4ade80' : '#f87171';
    wrEl.textContent = acct.win_rate.toFixed(1) + '%';
  }

  $('ts').textContent = 'Updated ' + new Date().toLocaleTimeString();
}"""

if old in content:
    content = content.replace(old, new)
    print("Win Rate JS: OK")
else:
    print("NOT FOUND")

open(path, 'w', encoding='utf-8').write(content)
