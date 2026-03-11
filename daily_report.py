"""
Daily report — sends Account Value + P&L to David via Telegram.
Runs at 7am and 7pm via Task Scheduler.
Writes to pending_alerts.json for heartbeat to forward.
"""
import sys, json, requests, time
from pathlib import Path
from datetime import date, datetime

sys.stdout.reconfigure(encoding='utf-8')

LOGS    = Path(__file__).parent / 'logs'
SECRETS = Path(__file__).parent.parent / 'secrets'
ALERTS  = LOGS / 'pending_alerts.json'
LOGS.mkdir(exist_ok=True)

STARTING_CAPITAL = 400.00
DASHBOARD_URL    = "http://localhost:8765"

# ── Pull numbers from dashboard API (already correct) ────────────────────────
open_pnl = closed_pnl = total_pnl = deployed = buying_pw = 0.0
acct_val = STARTING_CAPITAL

try:
    acct = requests.get(f"{DASHBOARD_URL}/api/account", timeout=4).json()
    deployed  = acct.get('total_deployed', 0)
    buying_pw = acct.get('buying_power', 0)
except Exception:
    pass

try:
    prices = requests.get(f"{DASHBOARD_URL}/api/positions/prices", timeout=8).json()
    for ticker, p in prices.items():
        # Get matching trade from today's log
        today_log = LOGS / f"trades_{date.today().isoformat()}.jsonl"
        if not today_log.exists(): continue
        for line in today_log.read_text(encoding='utf-8', errors='ignore').splitlines():
            try:
                t = json.loads(line)
                if t.get('ticker') != ticker or t.get('action') == 'exit': continue
                side      = t.get('side', 'no')
                contracts = t.get('contracts', 0)
                mp        = t.get('market_prob', 0.5)
                entry_p   = 100 - round(mp * 100) if side == 'no' else round(mp * 100)
                cur_p     = p.get('no_ask', entry_p) if side == 'no' else p.get('yes_ask', entry_p)
                pnl       = (cur_p - entry_p) * contracts / 100
                if p.get('settled'):
                    closed_pnl += pnl
                else:
                    open_pnl += pnl
            except Exception:
                pass
except Exception:
    pass

total_pnl = open_pnl + closed_pnl
acct_val  = STARTING_CAPITAL + total_pnl

# ── Format message ────────────────────────────────────────────────────────────
hour   = datetime.now().hour
period = 'Morning' if hour < 12 else 'Evening'
emoji  = 'GM' if hour < 12 else 'GE'

def fmt(v):
    sign = '+' if v >= 0 else ''
    return f"{sign}${v:.2f}"

msg = (
    f"{emoji} {period} Report\n"
    f"\n"
    f"Account Value: ${acct_val:.2f}\n"
    f"Total P&L:     {fmt(total_pnl)}\n"
    f"  Open P&L:    {fmt(open_pnl)}\n"
    f"  Closed P&L:  {fmt(closed_pnl)}\n"
    f"Buying Power:  ${buying_pw:.2f}\n"
    f"Deployed:      ${deployed:.2f}"
)

print(msg)

# ── Write to pending_alerts for heartbeat to forward ─────────────────────────
alerts = []
if ALERTS.exists():
    try: alerts = json.loads(ALERTS.read_text(encoding='utf-8'))
    except: pass

alerts.append({
    'level':     'report',
    'message':   msg,
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
})
ALERTS.write_text(json.dumps(alerts, indent=2), encoding='utf-8')
print(f"\nReport queued for delivery.")
