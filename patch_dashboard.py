"""Fix Kalshi URLs, Trade History links, remove SIM tag, add BOT/MANUAL badge."""
import sys

path = 'dashboard/templates/index.html'
api_path = 'dashboard/api.py'

# ── 1. Fix kalshi_url in api.py ───────────────────────────────────────────────
api = open(api_path, encoding='utf-8').read()

old_url = "            'kalshi_url':    f\"https://kalshi.com/markets/{ticker"
new_url = "            'kalshi_url':    f\"https://kalshi.com/markets/{ticker.split('-')[0]}/{ticker"

if old_url in api:
    api = api.replace(old_url, new_url)
    print("api URL: OK")
else:
    print("api URL: NOT FOUND")
    idx = api.find('kalshi_url')
    print(repr(api[idx:idx+100]))

open(api_path, 'w', encoding='utf-8').write(api)

# ── 2. Patch HTML ─────────────────────────────────────────────────────────────
content = open(path, encoding='utf-8').read()

# 2a. Add BOT/MANUAL badge CSS
old_badge_css = '.b-yes { background: rgba(74,222,128,.12); color: #4ade80; }'
new_badge_css = '''.b-yes { background: rgba(74,222,128,.12); color: #4ade80; }
.b-bot { background: rgba(99,102,241,.12); color: #818cf8; font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; margin-left: 5px; vertical-align: middle; }
.b-manual { background: rgba(251,191,36,.12); color: #fbbf24; font-size: 9px; padding: 1px 5px; border-radius: 3px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; margin-left: 5px; vertical-align: middle; }'''

if old_badge_css in content:
    content = content.replace(old_badge_css, new_badge_css)
    print("badge CSS: OK")
else:
    print("badge CSS: NOT FOUND")

# 2b. Fix Trade History row renderer — find the trades tbody JS
old_tr = """  tb.innerHTML = trades.map(t => {
    const sim  = t.order_result?.dry_run ? '<span class="badge" style="background:rgba(251,191,36,.1);color:#fbbf24;font-size:9px">SIM</span>' : '';
    const side = t.side==='yes'||t.side==='YES' ? '<span class="b-yes">YES</span>' : '<span class="b-no">NO</span>';
    const edge = t.edge ? (t.edge*100).toFixed(1)+'%' : '--';
    const noaa = t.noaa_prob ? Math.round(t.noaa_prob*100)+'% vs '+Math.round(t.market_prob*100)+'%' : '--';
    return `<tr>
      <td class="l">${sim} ${(t.title||t.ticker||'').replace(/\*\*/g,'').substring(0,60)}</td>
      <td>${side}</td><td>${edge}</td><td>${noaa}</td><td>${dollar(t.size_dollars||0)}</td>
    </tr>`;
  }).join('');"""

new_tr = """  tb.innerHTML = trades.map(t => {
    const side   = t.side==='yes'||t.side==='YES' ? '<span class="b-yes">YES</span>' : '<span class="b-no">NO</span>';
    const src    = (t.source && ['geo','gaming','manual'].includes(t.source))
                   ? '<span class="b-manual">MANUAL</span>' : '<span class="b-bot">BOT</span>';
    const edge   = t.edge ? (t.edge*100).toFixed(1)+'%' : '--';
    const noaa   = t.noaa_prob ? Math.round(t.noaa_prob*100)+'% vs '+Math.round(t.market_prob*100)+'%' : '--';
    const ticker = t.ticker || '';
    const series = ticker.split('-')[0];
    const url    = `https://kalshi.com/markets/${series}/${ticker}`;
    const title  = (t.title||ticker).replace(/\*\*/g,'').substring(0,60);
    return `<tr>
      <td class="l"><a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;">${title}</a>${src}</td>
      <td>${side}</td><td>${edge}</td><td>${noaa}</td><td>${dollar(t.size_dollars||0)}</td>
    </tr>`;
  }).join('');"""

if old_tr in content:
    content = content.replace(old_tr, new_tr)
    print("Trade History rows: OK")
else:
    print("Trade History rows: NOT FOUND")
    idx = content.find('sim  = t.order_result')
    print(repr(content[idx-50:idx+200]))

open(path, 'w', encoding='utf-8').write(content)
print("Done")
