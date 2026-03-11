"""
Update /api/pnl to return open_pnl, closed_pnl, total_pnl separately.
Update frontend loadPnlChart to populate Closed P&L in account bar.
"""
from pathlib import Path

# ── 1. Backend: return split P&L ─────────────────────────────────────────────
api_path = Path('dashboard/api.py')
code = api_path.read_text(encoding='utf-8')

start = code.find('@app.get("/api/pnl")')
end   = code.find('\n@app.', start + 10)

NEW_PNL = '''@app.get("/api/pnl")
def get_pnl_history():
    """
    Real P&L split into open (unrealized) and closed (realized/settled).
    Settled = past-date tickers that already resolved on Kalshi.
    Open    = current positions still trading.
    """
    import requests as req
    from collections import defaultdict

    all_trades = read_all_trades()
    settled_tickers = {}
    open_tickers    = {}
    seen = set()
    for t in all_trades:
        ticker = t.get('ticker', '')
        if not ticker or ticker in seen: continue
        if t.get('action') == 'exit': continue
        seen.add(ticker)
        if is_settled_ticker(ticker):
            settled_tickers[ticker] = t
        else:
            open_tickers[ticker] = t

    closed_pnl_total = 0.0
    closed_by_source = {'bot': 0.0, 'manual': 0.0}
    closed_wins = 0
    closed_total = 0

    # ── Settled positions ────────────────────────────────────────────────────
    for ticker, t in settled_tickers.items():
        try:
            r = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if r.status_code != 200: continue
            m = r.json().get('market', {})
            lp = m.get('last_price')
            if lp is None: continue

            side      = t.get('side', 'no')
            mp        = t.get('market_prob', 0.5) or 0.5
            entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
            cost      = t.get('size_dollars', 25)
            contracts = t.get('contracts', 0) or 0
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            cur_p = (100 - lp) if side == 'no' else lp
            pnl   = round((cur_p - entry_p) * contracts / 100, 2)
            closed_pnl_total += pnl
            closed_total += 1
            if pnl > 0: closed_wins += 1

            src = t.get('source', 'bot')
            if src in ('geo', 'gaming', 'manual'):
                closed_by_source['manual'] += pnl
            else:
                closed_by_source['bot'] += pnl
        except Exception:
            pass

    # ── Open positions ───────────────────────────────────────────────────────
    open_pnl_total = 0.0
    open_by_source = {'bot': 0.0, 'manual': 0.0}
    open_wins = 0
    open_total = 0

    for ticker, t in open_tickers.items():
        try:
            r = req.get(
                f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}',
                timeout=4
            )
            if r.status_code != 200: continue
            m = r.json().get('market', {})

            side      = t.get('side', 'no')
            mp        = t.get('market_prob', 0.5) or 0.5
            entry_p   = int((1 - mp) * 100) if side == 'no' else int(mp * 100)
            cost      = t.get('size_dollars', 25)
            contracts = t.get('contracts', 0) or 0
            if contracts > 0 and cost > 0:
                contracts = min(contracts, int(cost / max(entry_p, 1) * 100) + 2)

            cur_p = m.get('no_ask', entry_p) if side == 'no' else m.get('yes_ask', entry_p)
            if not cur_p: cur_p = entry_p
            pnl = round((cur_p - entry_p) * contracts / 100, 2)
            open_pnl_total += pnl
            open_total += 1
            if pnl > 0: open_wins += 1

            src = t.get('source', 'bot')
            if src in ('geo', 'gaming', 'manual'):
                open_by_source['manual'] += pnl
            else:
                open_by_source['bot'] += pnl
        except Exception:
            pass

    total_pnl = open_pnl_total + closed_pnl_total

    # Build chart time-series
    from datetime import date as date_cls
    today = str(date_cls.today())
    points = []
    if closed_pnl_total != 0:
        points.append({"date": "2026-03-10", "pnl": round(closed_pnl_total, 2)})
    points.append({"date": today, "pnl": round(total_pnl, 2)})

    return {
        "open_pnl":   round(open_pnl_total, 2),
        "closed_pnl": round(closed_pnl_total, 2),
        "total_pnl":  round(total_pnl, 2),
        "bot_closed_pnl":    round(closed_by_source['bot'], 2),
        "manual_closed_pnl": round(closed_by_source['manual'], 2),
        "bot_open_pnl":      round(open_by_source['bot'], 2),
        "manual_open_pnl":   round(open_by_source['manual'], 2),
        "closed_win_rate": round(closed_wins / closed_total * 100, 1) if closed_total else None,
        "points": points,
        "total":  round(total_pnl, 2),
    }

'''

code = code[:start] + NEW_PNL + code[end:]
api_path.write_text(code, encoding='utf-8')
print("Backend /api/pnl updated")

# ── 2. Frontend: wire closed P&L into account bar ────────────────────────────
html_path = Path('dashboard/templates/index.html')
html = html_path.read_text(encoding='utf-8', errors='ignore')

OLD_LOAD = '''async function loadPnlChart() {
  try {
    const pnl = await api('/api/pnl');
    if (!pnl || !pnl.points || !pnl.points.length) return;
    renderPnlChart(pnl.points);
  } catch(e) {}
}'''

NEW_LOAD = '''async function loadPnlChart() {
  try {
    const pnl = await api('/api/pnl');
    if (!pnl) return;

    // Populate Closed P&L in account bar
    setPnl('cpnl', 'cpnl-pct', pnl.closed_pnl || 0, Math.abs(pnl.closed_pnl || 1));

    // BOT card: closed P&L for bot trades
    setSplitPnl('bot-pnl', 'bot-pnl-pct', pnl.bot_closed_pnl || 0, Math.abs(pnl.bot_closed_pnl || 1));

    // Update Account Value = $400 + open_pnl + closed_pnl
    window._closedPnl = pnl.closed_pnl || 0;
    const base = window._kalshiBalance || 400;
    const openPnl = parseFloat((document.getElementById('opnl') || {}).textContent) || 0;
    document.getElementById('av').textContent = dollar(base + (window._openPnl || 0) + window._closedPnl);

    // Win rate from closed trades if available
    if (pnl.closed_win_rate != null) {
      const wrEl = document.getElementById('winrate');
      if (wrEl && wrEl.textContent === '--') {
        wrEl.textContent = pnl.closed_win_rate.toFixed(0) + '%';
        wrEl.style.color = pnl.closed_win_rate >= 50 ? '#4ade80' : '#f87171';
      }
    }

    // Render chart
    if (pnl.points && pnl.points.length) renderPnlChart(pnl.points);
  } catch(e) {}
}'''

html = html.replace(OLD_LOAD, NEW_LOAD)

# Also update loadLivePrices to store _openPnl and update account value correctly
OLD_AV = '''    document.getElementById('av').textContent = dollar((window._kalshiBalance || 400) + totalPnl);'''
NEW_AV = '''    window._openPnl = totalPnl;
    document.getElementById('av').textContent = dollar((window._kalshiBalance || 400) + totalPnl + (window._closedPnl || 0));'''

html = html.replace(OLD_AV, NEW_AV)

html_path.write_text(html, encoding='utf-8')
print("Frontend loadPnlChart updated")
print("Frontend Account Value formula updated")
