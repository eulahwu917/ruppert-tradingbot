"""
Position Monitor — Ruppert Weather Position Watcher
====================================================
Runs on a schedule, checks all open positions against the latest ensemble
forecast, and sends Telegram alerts when action is needed.

Schedule (run via Windows Task Scheduler or run_monitor.bat):
  - 10:00 PM (T-1 evening): Full ensemble re-check before resolution
  -  7:00 AM (T-0 morning): Morning check with current conditions
  - 12:00 PM (T-0 noon):    Final intraday check
  - Every 2h (same-day):    Same-day contract monitoring

Alert thresholds:
  - SAFE:   forecast >=3°F outside band edge  → no alert
  - WATCH:  forecast 1-3°F outside band edge  → Telegram warning
  - DANGER: forecast <1°F from band edge      → Telegram urgent alert
  - FLIP:   forecast has moved INTO band      → Telegram exit recommendation
"""

import sys, json, requests, os
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── Config ────────────────────────────────────────────────────────────────────
BOT_DIR  = Path(__file__).parent
LOGS_DIR = BOT_DIR / "logs"
SECRETS  = BOT_DIR.parent / "secrets"
TG_CFG   = SECRETS / "telegram_config.json"

SAFE_MARGIN_F  = 3.0   # >=3F outside band → safe, no alert
WATCH_MARGIN_F = 1.0   # 1-3F outside band → warning
# <1F from edge → urgent; <0F (inside band) → exit recommended

# ── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    """
    Write alert to pending_alerts.json for OpenClaw to pick up and forward via Telegram.
    OpenClaw's cron reads this file and sends it — no separate bot token needed.
    """
    alert_file = LOGS_DIR / "pending_alerts.json"
    LOGS_DIR.mkdir(exist_ok=True)

    # Read existing alerts
    alerts = []
    if alert_file.exists():
        try:
            alerts = json.loads(alert_file.read_text(encoding='utf-8'))
        except Exception:
            alerts = []

    # Append new alert
    alerts.append({
        "message":   message,
        "timestamp": datetime.now().isoformat(),
        "sent":      False,
    })
    alert_file.write_text(json.dumps(alerts, indent=2), encoding='utf-8')
    print(f"[Monitor] Alert queued for OpenClaw → Telegram delivery")
    return True

# ── Trade log ─────────────────────────────────────────────────────────────────

def load_open_positions():
    """Load all positions from trade logs that haven't settled yet."""
    positions = []
    for log_path in sorted(LOGS_DIR.glob("trades_*.jsonl")):
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try:
                    t = json.loads(line.strip())
                    if not t.get('ticker'):
                        continue
                    # Check if market is still active
                    positions.append(t)
                except Exception:
                    pass

    # Filter to only active (non-settled) markets
    active = []
    seen = set()
    for p in positions:
        ticker = p['ticker']
        if ticker in seen:
            continue
        seen.add(ticker)
        try:
            r = requests.get(
                f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                timeout=5
            )
            if r.status_code == 200:
                m = r.json().get('market', {})
                status = m.get('status', '')
                if status == 'active':
                    p['_market'] = m
                    active.append(p)
                else:
                    print(f"  [Monitor] {ticker} is {status} — skipping")
        except Exception as e:
            print(f"  [Monitor] Could not check {ticker}: {e}")
    return active

# ── Core logic ────────────────────────────────────────────────────────────────

def parse_position(trade):
    """Extract series, threshold, band lo/hi from ticker."""
    parts = trade['ticker'].split('-')
    if len(parts) < 3:
        return None
    series    = parts[0]
    raw       = parts[2]              # e.g. B83.5
    kind      = raw[0]                # B or T
    try:
        threshold = float(raw[1:])
    except ValueError:
        return None
    band_lo = threshold
    band_hi = threshold + 2 if kind == 'B' else None
    return {
        "ticker":    trade['ticker'],
        "series":    series,
        "kind":      kind,
        "threshold": threshold,
        "band_lo":   band_lo,
        "band_hi":   band_hi,
        "side":      trade.get('side', 'no').upper(),
        "entry_c":   round((1 - trade.get('market_prob', 0)) * 100) if trade.get('side', 'no') == 'no'
                     else round(trade.get('market_prob', 0) * 100),
        "contracts": trade.get('contracts', 0),
        "cost":      trade.get('size_dollars', 0),
    }


def assess_position(pos, forecast_f):
    """
    Given a bias-corrected forecast and band, determine risk level.
    For NO bets on B-bands: we win if actual is OUTSIDE [band_lo, band_hi].
    """
    band_lo = pos['band_lo']
    band_hi = pos['band_hi']

    if band_hi is None:
        return "UNKNOWN", 999  # T-markets handled differently

    # Distance from nearest band edge
    if forecast_f < band_lo:
        margin = band_lo - forecast_f   # positive = how far below lower edge
        position_vs_band = "BELOW"
    elif forecast_f > band_hi:
        margin = forecast_f - band_hi   # positive = how far above upper edge
        position_vs_band = "ABOVE"
    else:
        margin = 0  # inside band → NO bet at risk
        position_vs_band = "INSIDE"

    if position_vs_band == "INSIDE":
        status = "DANGER_INSIDE"
    elif margin < WATCH_MARGIN_F:
        status = "DANGER_CLOSE"
    elif margin < SAFE_MARGIN_F:
        status = "WATCH"
    else:
        status = "SAFE"

    return status, margin, position_vs_band


def run_monitor(mode="check"):
    """
    Main monitor run.
    mode: 'check' = full check + alerts
          'summary' = morning/evening summary regardless of status
    """
    from openmeteo_client import get_current_conditions

    now  = datetime.now()
    today_str = now.strftime("%Y-%m-%d %H:%M")
    print(f"\n[Monitor] Running at {today_str}  mode={mode}")

    positions = load_open_positions()
    if not positions:
        print("[Monitor] No active positions to monitor.")
        if mode == 'summary':
            send_telegram("📊 <b>Ruppert Position Check</b>\nNo open positions to monitor.")
        return

    print(f"[Monitor] {len(positions)} active position(s) found")

    # Fetch forecasts per city (deduplicated)
    forecasts = {}
    for trade in positions:
        p = parse_position(trade)
        if not p:
            continue
        series = p['series']
        if series not in forecasts:
            cond = get_current_conditions(series)
            if cond and not cond.get('error'):
                tmrw  = cond.get('tomorrow_high_f')
                bias  = cond.get('bias_applied_f', 0)
                raw   = round(tmrw - bias, 1) if tmrw and bias else tmrw
                forecasts[series] = {
                    'tomorrow_biased': tmrw,
                    'raw': raw,
                    'bias': bias,
                    'current': cond.get('current_temp_f'),
                }
                print(f"  {series}: raw={raw}F +{bias}F => {tmrw}F (current {cond.get('current_temp_f')}F)")
            else:
                forecasts[series] = None
                print(f"  {series}: forecast unavailable")

    # Assess each position
    alerts     = []
    watchlist  = []
    safe_list  = []

    for trade in positions:
        p = parse_position(trade)
        if not p:
            continue

        fc = forecasts.get(p['series'])
        if not fc or fc['tomorrow_biased'] is None:
            watchlist.append((p, None, "NO_FORECAST", 0))
            continue

        forecast_f = fc['tomorrow_biased']

        # Live P&L
        m = trade.get('_market', {})
        no_ask  = m.get('no_ask')
        yes_ask = m.get('yes_ask')
        cur_c   = no_ask if p['side'] == 'NO' else yes_ask
        open_pnl = ((cur_c - p['entry_c']) * p['contracts'] / 100) if cur_c else 0

        status, margin, band_pos = assess_position(p, forecast_f)

        entry = (p['ticker'], forecast_f, p['band_lo'], p['band_hi'],
                 status, margin, band_pos, open_pnl, cur_c)

        if status in ('DANGER_INSIDE', 'DANGER_CLOSE'):
            alerts.append(entry)
        elif status == 'WATCH':
            watchlist.append(entry)
        else:
            safe_list.append(entry)

    # ── Build Telegram message ──────────────────────────────────────────────
    lines = [f"<b>Ruppert Position Monitor</b> — {today_str}\n"]

    if alerts:
        lines.append("🚨 <b>ACTION NEEDED</b>")
        for ticker, fc, lo, hi, status, margin, pos, pnl, cur in alerts:
            if status == 'DANGER_INSIDE':
                lines.append(f"  ❌ {ticker}\n     Forecast {fc}F is INSIDE band {lo}-{hi}F\n     NO bet at risk! Consider EXIT. P&L: ${pnl:+.2f}")
            else:
                lines.append(f"  ⚠️ {ticker}\n     Forecast {fc}F — only {margin:.1f}F from {lo if pos=='BELOW' else hi}F edge\n     P&L: ${pnl:+.2f}")
        lines.append("")

    if watchlist:
        lines.append("👀 <b>WATCH</b>")
        for item in watchlist:
            if len(item) == 4:
                p, _, status, _ = item
                lines.append(f"  ~ {p['ticker']}  No forecast available")
            else:
                ticker, fc, lo, hi, status, margin, pos, pnl, cur = item
                lines.append(f"  ~ {ticker}  {margin:.1f}F buffer  P&L: ${pnl:+.2f}")
        lines.append("")

    if safe_list:
        lines.append("✅ <b>HOLDING STRONG</b>")
        for ticker, fc, lo, hi, status, margin, pos, pnl, cur in safe_list:
            lines.append(f"  + {ticker}  {margin:.1f}F buffer  P&L: ${pnl:+.2f}")

    total_pnl = sum(e[7] for e in alerts + safe_list) + sum(
        e[7] if len(e) > 4 else 0 for e in watchlist
    )
    lines.append(f"\n📈 Total Open P&L: <b>${total_pnl:+.2f}</b>")

    message = "\n".join(lines)
    print("\n" + message.replace("<b>","").replace("</b>",""))

    # Only send Telegram if there are alerts, or it's a summary run
    if alerts or mode == 'summary':
        send_telegram(message)
    else:
        print("[Monitor] All positions safe — no Telegram alert needed.")

    # Log run
    LOGS_DIR.mkdir(exist_ok=True)
    log_entry = {
        "timestamp":   now.isoformat(),
        "mode":        mode,
        "positions":   len(positions),
        "alerts":      len(alerts),
        "watches":     len(watchlist),
        "safe":        len(safe_list),
        "total_pnl":   round(total_pnl, 2),
        "sent_telegram": bool(alerts or mode == 'summary'),
    }
    with open(LOGS_DIR / "monitor.jsonl", "a", encoding='utf-8') as f:
        f.write(json.dumps(log_entry) + "\n")

    return log_entry


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    run_monitor(mode=mode)
