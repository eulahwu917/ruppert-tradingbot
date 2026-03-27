"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full   ΓÇö scan + positions + smart money + execute (7am, 3pm)
  check  ΓÇö positions only (12pm, 10pm)
  smart  ΓÇö smart money refresh only (lightweight)
"""
import sys, json, time, math, requests
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

MODE = sys.argv[1] if len(sys.argv) > 1 else 'full'
LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
ALERTS_FILE = LOGS / 'pending_alerts.json'
ALERT_LOG   = LOGS / 'cycle_log.jsonl'

import config
from kalshi_client import KalshiClient
from logger import log_trade, log_activity, get_daily_exposure, get_computed_capital, send_telegram, rotate_logs, normalize_entry_price, acquire_exit_lock, release_exit_lock
from bot.strategy import check_daily_cap, check_open_exposure, should_enter
from capital import get_capital, get_buying_power

DRY_RUN = config.DRY_RUN  # Derived from mode.json: demo=True, live=False

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def push_alert(level, message, ticker=None, pnl=None):
    """Write alert for heartbeat to pick up and forward to David."""
    alerts = []
    if ALERTS_FILE.exists():
        try: alerts = json.loads(ALERTS_FILE.read_text(encoding='utf-8'))
        except: pass
    alerts.append({
        'level': level, 'message': message,
        'ticker': ticker, 'pnl': pnl,
        'timestamp': ts(),
    })
    ALERTS_FILE.write_text(json.dumps(alerts, indent=2), encoding='utf-8')

def log_cycle(event, data=None):
    entry = {'ts': ts(), 'mode': MODE, 'event': event}
    if data: entry.update(data)
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


# ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
print(f"\n{'='*60}")
print(f"  RUPPERT CYCLE  mode={MODE.upper()}  {ts()}")
print(f"{'='*60}")
log_cycle('start')

# Rotate logs once per cycle (keeps last 90 days, deletes older files)
try:
    rotate_logs()
except Exception as _e:
    print(f"[Logger] Log rotation skipped: {_e}")

client = KalshiClient()
BASE   = "https://api.elections.kalshi.com/trade-api/v2/markets"
HDR    = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
traded_tickers = set()

# Compute open exposure once per cycle — used by global 70% cap check in should_enter()
try:
    _cycle_capital      = get_capital()
    _cycle_buying_power = get_buying_power()
    OPEN_POSITION_VALUE = max(0.0, _cycle_capital - _cycle_buying_power)
except Exception:
    OPEN_POSITION_VALUE = 0.0  # safe default: won't block entry

# ── STARTUP: ORPHAN POSITION RECONCILIATION ────────────────────────────────
print("\n[0] Orphan position reconciliation...")
try:
    from post_trade_monitor import load_open_positions as _load_log_positions
    _kalshi_positions = client.get_positions()
    _logged_positions = _load_log_positions()
    _logged_keys = {(p.get('ticker', ''), p.get('side', '')) for p in _logged_positions}

    for _kpos in _kalshi_positions:
        try:
            _ticker = _kpos.ticker if hasattr(_kpos, 'ticker') else _kpos.get('ticker', '')
            _raw_pos = getattr(_kpos, 'position', None)
            if _raw_pos is None:
                _raw_pos = _kpos.get('position', 0)
            _side = 'yes' if _raw_pos > 0 else 'no'
            _contracts = abs(_raw_pos)
        except Exception as _e:
            print(f"  [Orphan] Could not parse position record: {_e}")
            continue

        if not _ticker or _contracts == 0:
            continue
        if (_ticker, _side) not in _logged_keys:
            _msg = (f"Orphan position detected: {_ticker} {_side} {_contracts} contracts"
                    " — not in trade log. Manual review required.")
            print(f"  [WARNING] {_msg}")
            push_alert('warning', _msg, ticker=_ticker)

    print(f"  Reconciliation complete — {len(_kalshi_positions)} Kalshi position(s),"
          f" {len(_logged_positions)} log position(s)")
except Exception as _recon_err:
    print(f"  [Orphan] Reconciliation failed (non-blocking): {_recon_err}")

# ΓöÇΓöÇ STEP 1: POSITION CHECK (every run) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
print("\n[1] Position check...")
# P0-3 fix: initialize actions_taken BEFORE the try block so it's always in scope.
# Was previously defined inside try, causing NameError if STEP 1 raised early.
actions_taken = []
try:
    from openmeteo_client import get_full_weather_signal
    from edge_detector import parse_date_from_ticker, parse_threshold_from_ticker

    trade_log = LOGS / f"trades_{date.today().isoformat()}.jsonl"
    open_positions = []
    if trade_log.exists():
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            try: open_positions.append(json.loads(line))
            except: pass
    open_positions = [p for p in open_positions if p.get('action') != 'exit']

    print(f"  {len(open_positions)} open position(s)")

    for pos in open_positions:
        ticker = pos.get('ticker', '')
        source = pos.get('source', 'bot')
        if source not in ('weather', 'bot'): continue
        if ticker in traded_tickers: continue

        # Get current market price
        try:
            r = requests.get(f'{BASE}/{ticker}', timeout=5)
            if r.status_code != 200: continue
            m = r.json().get('market', {})
            status = m.get('status', '')
            if status in ('finalized', 'settled'): continue

            yes_ask = m.get('yes_ask', 50) or 50
            no_ask  = m.get('no_ask', 50) or 50
            side    = pos.get('side', 'no')
            entry_p = normalize_entry_price(pos)
            cur_p   = no_ask if side == 'no' else yes_ask
            contracts = pos.get('contracts', 0)
            pnl     = round((cur_p - entry_p) * contracts / 100, 2)

            # Weather: check ensemble if close to expiry
            alert_msg = None
            if 'KXHIGH' in ticker:
                try:
                    # Derive correct args for get_full_weather_signal from the ticker
                    series_ticker = ticker.split('-')[0].upper()  # e.g. KXHIGHMIA
                    threshold_f = parse_threshold_from_ticker(ticker)   # e.g. 85.5
                    target_date = parse_date_from_ticker(ticker)        # e.g. date(2026,3,12)
                    if threshold_f is not None:
                        sig = get_full_weather_signal(series_ticker, threshold_f, target_date)
                        # forecast: use tomorrow_high if not same-day, else today_high
                        conditions = sig.get('conditions', {})
                        if sig.get('is_same_day'):
                            forecast = conditions.get('today_high_f') or 0
                        else:
                            forecast = conditions.get('tomorrow_high_f') or 0
                        margin = abs(forecast - threshold_f) if forecast else 999
                        ens_prob = sig.get('final_prob', 0.5) or 0.5

                        if side == 'no':
                            # NO wins if forecast OUTSIDE band ΓÇö check if forecast moved inside
                            if margin < 1.0:
                                alert_msg = f'WARNING: {ticker} forecast {forecast:.1f}F only {margin:.1f}F from band edge {threshold_f}F | P&L ${pnl:+.2f}'
                                push_alert('warning', alert_msg, ticker=ticker, pnl=pnl)
                            elif ens_prob > 0.80:
                                alert_msg = f'EXIT SIGNAL: {ticker} ensemble {ens_prob:.0%} against NO position | P&L ${pnl:+.2f}'
                                push_alert('exit', alert_msg, ticker=ticker, pnl=pnl)

                            # Auto-exit if gain > $4 and margin tight
                            if pnl > 4.0 and margin < 2.0:
                                print(f'  AUTO-EXIT: {ticker} P&L=${pnl:+.2f} margin={margin:.1f}F')
                                actions_taken.append(('exit', ticker, side, cur_p, contracts, pnl))
                                traded_tickers.add(ticker)
                except Exception as e:
                    print(f'  Weather check error for {ticker}: {e}')

            print(f'  {ticker:38} {side.upper()} entry={entry_p}c cur={cur_p}c P&L=${pnl:+.2f}' +
                  (f' [ALERT]' if alert_msg else ''))
        except Exception as e:
            print(f'  Error checking {ticker}: {e}')

    # Execute auto-exits
    if actions_taken:
        for action, ticker, side, price, contracts, pnl in actions_taken:
            if not acquire_exit_lock(ticker, side):
                print(f'  SKIP: {ticker} exit already in progress (lock held)')
                continue
            try:
                opp = {'ticker': ticker, 'title': ticker, 'side': side, 'action': 'exit',
                       'yes_price': price if side=='yes' else 100-price,
                       'market_prob': price/100, 'noaa_prob': None, 'edge': None,
                       'size_dollars': round(contracts*price/100, 2), 'contracts': contracts,
                       'source': 'weather', 'timestamp': ts(), 'date': str(date.today())}
                if DRY_RUN:
                    log_trade(opp, opp['size_dollars'], contracts, {'dry_run': True})
                    log_activity(f'[AUTO-EXIT] {ticker} {side.upper()} @ {price}c P&L=${pnl:+.2f}')
                    print(f'  [DEMO] AUTO-EXIT logged: {ticker}')
                else:
                    try:
                        result = client.sell_position(ticker, side, price, contracts)
                        log_trade(opp, opp['size_dollars'], contracts, result)
                        print(f'  [LIVE] AUTO-EXIT executed: {ticker}')
                    except Exception as e:
                        print(f'  EXIT ERROR {ticker}: {e}')
            finally:
                release_exit_lock(ticker, side)

except Exception as e:
    print(f'  Position check error: {e}')
    import traceback; traceback.print_exc()

if MODE == 'check':
    log_cycle('done', {'actions': len(actions_taken) if 'actions_taken' in dir() else 0})
    print(f"\nCheck-only cycle done. {ts()}")
    sys.exit(0)

# ΓöÇΓöÇ REPORT MODE: 7am P&L summary + loss detection ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
if MODE == 'report':
    print("\n[7AM REPORT] P&L Summary + Loss Detection...")
    from datetime import timedelta

    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    # ΓöÇΓöÇ Load all trades: today + yesterday ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    all_records: list = []
    for day_str in [yesterday_str, today_str]:
        log_path = LOGS / f'trades_{day_str}.jsonl'
        if log_path.exists():
            for line in log_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    all_records.append(json.loads(line))
                except Exception:
                    pass

    print(f"  Loaded {len(all_records)} record(s) from today + yesterday")

    # ΓöÇΓöÇ Group records: latest entry per ticker, all exits ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    entries_by_ticker: dict = {}
    exit_records: list = []

    for rec in all_records:
        action = rec.get('action', 'buy')
        ticker = rec.get('ticker')
        if not ticker:
            continue
        if action in ('buy', 'open'):
            entries_by_ticker[ticker] = rec   # keep latest entry per ticker
        elif action == 'exit':
            exit_records.append(rec)

    # ΓöÇΓöÇ Compute high-level P&L summary ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    total_deployed = sum(
        r.get('size_dollars', 0.0)
        for r in all_records
        if r.get('action') in ('buy', 'open')
    )
    total_exited = sum(r.get('size_dollars', 0.0) for r in exit_records)
    net_pnl_approx = round(total_exited - total_deployed, 2)

    print(f"  Deployed: ${total_deployed:.2f}  "
          f"Exited: ${total_exited:.2f}  "
          f"Net approx: ${net_pnl_approx:+.2f}")

    # ΓöÇΓöÇ Scan for losses: explicit exits with negative realized_pnl ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    # A loss = action=="exit" AND realized_pnl < 0.
    # If realized_pnl is not stored in the record, compute it from
    # size_dollars: exit_value - entry_cost (cost basis from the open record).
    losses: list = []

    for exit_rec in exit_records:
        ticker = exit_rec.get('ticker')

        # Prefer a logged realized_pnl field; fall back to size_dollars diff
        realized_pnl = exit_rec.get('realized_pnl')
        if realized_pnl is None:
            entry = entries_by_ticker.get(ticker)
            if entry:
                exit_value   = float(exit_rec.get('size_dollars') or 0.0)
                entry_cost   = float(entry.get('size_dollars') or 0.0)
                realized_pnl = round(exit_value - entry_cost, 2)

        if realized_pnl is not None and realized_pnl < 0:
            entry = entries_by_ticker.get(ticker)
            losses.append({
                'ticker':       ticker,
                'side':         exit_rec.get('side', ''),
                'realized_pnl': realized_pnl,
                'entry_edge':   entry.get('edge') if entry else None,
                'source':       exit_rec.get('source') or (entry.get('source') if entry else ''),
                'timestamp':    exit_rec.get('timestamp', ''),
            })

    print(f"  Losses found: {len(losses)}")

    # ΓöÇΓöÇ Write optimizer review file if losses exist ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    if losses:
        total_loss = round(sum(l['realized_pnl'] for l in losses), 2)

        review_file = LOGS / 'pending_optimizer_review.json'
        review_data = {
            'date':       today_str,
            'losses':     losses,
            'total_loss': total_loss,
        }
        review_file.write_text(json.dumps(review_data, indent=2), encoding='utf-8')
        print(f"  Wrote pending_optimizer_review.json ΓÇö "
              f"{len(losses)} loss(es) totaling ${total_loss:.2f}")

        # ΓöÇΓöÇ Append optimizer alert ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        alert_msg = (
            f"Loss review ready: {len(losses)} losing trade(s) totaling "
            f"${abs(total_loss):.2f}. Optimizer review needed."
        )
        push_alert('optimizer', alert_msg)
        print(f"  Alert queued: {alert_msg}")
    else:
        print("  No losses detected ΓÇö skipping optimizer review file")

    log_cycle('done', {'mode': 'report', 'exit_count': len(exit_records), 'losses': len(losses)})
    print(f"\n7am report complete. {ts()}")
    sys.exit(0)

# ΓöÇΓöÇ STEP 1b: WALLET LIST REFRESH (full mode ΓÇö once daily before scans) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
print("\n[1b] Refreshing smart money wallet list from Polymarket leaderboard...")
try:
    from bot.wallet_updater import update_wallet_list as _update_wallets
    _wallets_updated = _update_wallets()
    if not _wallets_updated:
        print("  Wallet refresh skipped ΓÇö API unavailable, using existing list")
except Exception as e:
    print(f"  Wallet refresh error (non-fatal): {e}")

# ΓöÇΓöÇ STEP 2: SMART MONEY REFRESH (full mode only) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
print("\n[2] Refreshing smart money signal...")
try:
    import subprocess, sys as _sys
    r = subprocess.run(
        [_sys.executable, 'fetch_smart_money.py'],
        capture_output=True, text=True, timeout=45,
        cwd=str(Path(__file__).parent)
    )
    if r.returncode == 0:
        sm_cache = LOGS / 'crypto_smart_money.json'
        sm = json.loads(sm_cache.read_text(encoding='utf-8')) if sm_cache.exists() else {}
        direction = sm.get('direction', 'neutral')
        bull_pct  = sm.get('bull_pct', 0.5)
        print(f"  Smart money: {direction.upper()} ({bull_pct:.0%} bull)")
    else:
        direction = 'neutral'
        print(f"  Smart money fetch failed ΓÇö using neutral")
except Exception as e:
    direction = 'neutral'
    print(f"  Smart money error: {e}")

# ΓöÇΓöÇ STEP 3: WEATHER OPPORTUNITY SCAN (full mode only) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
print("\n[3] Scanning for new weather opportunities...")
new_weather = []
try:
    from main import run_weather_scan
    new_weather = run_weather_scan(dry_run=DRY_RUN)
    if new_weather:
        print(f"  {len(new_weather)} new weather trade(s) executed")
        for t in new_weather:
            print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
    else:
        print("  No new weather opportunities above threshold")
except Exception as e:
    print(f"  Weather scan error: {e}")

# Refresh global exposure cap after weather trades before passing to next scan
OPEN_POSITION_VALUE += sum(t.get('size_dollars', 0) for t in new_weather)

# ── STEP 4: CRYPTO OPPORTUNITY SCAN (full mode only) ─────────────────────────
print("\n[4] Scanning for new crypto opportunities...")
new_crypto = []
try:
    from main import run_crypto_scan
    new_crypto = run_crypto_scan(dry_run=DRY_RUN, direction=direction, traded_tickers=traded_tickers, open_position_value=OPEN_POSITION_VALUE)
    if new_crypto:
        print(f"  {len(new_crypto)} crypto trade(s) executed")
        for t in new_crypto:
            print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
    else:
        print("  No new crypto opportunities above threshold")
except Exception as e:
    print(f"  Crypto scan error: {e}")
    import traceback; traceback.print_exc()

# Refresh global exposure cap after crypto trades before passing to next scan
OPEN_POSITION_VALUE += sum(t.get('size_dollars', 0) for t in new_crypto)

# ── STEP 4b: FED RATE DECISION SCAN (full mode only) ─────────────────────
print("\n[4b] Scanning for Fed rate decision opportunities...")
new_fed = []
try:
    from main import run_fed_scan as _run_fed_scan_cycle
    new_fed = _run_fed_scan_cycle(dry_run=DRY_RUN, traded_tickers=traded_tickers, open_position_value=OPEN_POSITION_VALUE)
    if new_fed:
        print(f"  {len(new_fed)} Fed trade(s) executed")
    else:
        print("  No Fed opportunities this cycle")
except Exception as e:
    print(f"  Fed scan error: {e}")
    import traceback; traceback.print_exc()

# ΓöÇΓöÇ STEP 5: SECURITY AUDIT (weekly ΓÇö Sunday only) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
if datetime.now().weekday() == 6:  # Sunday
    print("\n[5] Weekly security audit...")
    try:
        import subprocess, sys as _sys
        r = subprocess.run([_sys.executable, 'security_audit.py'],
                          capture_output=True, text=True, timeout=30,
                          cwd=str(Path(__file__).parent))
        if 'WARNING' in r.stdout:
            push_alert('security', 'Security audit found issues ΓÇö review security_audit output')
            print("  ALERT: issues found ΓÇö check logs")
        else:
            print("  Clean ΓÇö no issues found")
    except Exception as e:
        print(f"  Audit error: {e}")

# ΓöÇΓöÇ DONE ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
summary = {
    'weather_trades': len(new_weather) if new_weather else 0,
    'crypto_trades':  len(new_crypto) if new_crypto else 0,
    'fed_trades':     len(new_fed) if new_fed else 0,
    'smart_money':    direction,
    'auto_exits':     len(actions_taken) if 'actions_taken' in dir() else 0,
}
log_cycle('done', summary)

print(f"\n{'='*60}")
print(f"  CYCLE COMPLETE  {ts()}")
print(f"  Weather: {summary['weather_trades']} new | Crypto: {summary['crypto_trades']} new | Fed: {summary['fed_trades']} new")
print(f"  Auto-exits: {summary['auto_exits']} | Signal: {direction.upper()}")
print(f"{'='*60}\n")

# ΓöÇΓöÇ SCAN SUMMARY NOTIFICATION ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
# Sends a Telegram message to David via pending_alerts.json (heartbeat forwards it).
# Level 'warning' is used so it always forwards without additional filtering.
try:
    import time as _time
    is_dst = _time.daylight and _time.localtime().tm_isdst > 0
    offset = -7 if is_dst else -8
    tz_pdt = timezone(timedelta(hours=offset))
    _time_str = datetime.now(tz_pdt).strftime('%I:%M %p')

    # ΓöÇΓöÇ Fed status ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    _fed_status = 'no signal (outside window)'
    try:
        _fed_latest_path = LOGS / 'fed_scan_latest.json'
        if _fed_latest_path.exists():
            _fed_data = json.loads(_fed_latest_path.read_text(encoding='utf-8'))
            _skip = _fed_data.get('skip_reason')
            if _skip:
                _fed_status = f'no signal ({_skip})'
            elif _fed_data.get('direction'):
                _fed_dir  = _fed_data['direction'].upper()
                _fed_edge = round(_fed_data.get('edge', 0) * 100)
                _fed_conf = round(_fed_data.get('confidence', 0) * 100)
                _fed_status = f'{_fed_dir} edge={_fed_edge}% conf={_fed_conf}%'
            else:
                _fed_status = 'no signal'
    except Exception:
        _fed_status = 'error reading fed data'

    # ΓöÇΓöÇ Capital ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    try:
        _capital  = get_computed_capital()
        _deployed = get_daily_exposure()
        _bp       = max(0.0, round(_capital * 0.70 - _deployed, 2))
        _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
    except Exception:
        _cap_line = 'N/A'

    # ΓöÇΓöÇ Build message ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
    _w_opps   = len(new_weather) if isinstance(new_weather, list) else 0
    _w_trades = summary['weather_trades']
    _c_opps   = len(new_crypto) if isinstance(new_crypto, list) else 0
    _c_trades = summary['crypto_trades']
    _c_dir    = direction.upper() if direction else 'NEUTRAL'

    _scan_msg = (
        f"\U0001f4ca Ruppert Scan \u2014 {_time_str} PDT\n\n"
        f"\U0001f324 Weather: {_w_opps} opportunities | {_w_trades} trades placed\n"
        f"\u20bf Crypto: {_c_dir} | {_c_opps} opportunities | {_c_trades} trades placed\n"
        f"\U0001f3db Fed: {_fed_status}\n\n"
        f"\U0001f4b0 Capital: {_cap_line}"
    )

    push_alert('warning', _scan_msg)  # backup: pending_alerts.json for heartbeat
    send_telegram(_scan_msg)          # direct: send immediately via Bot API
    log_activity('[SCAN NOTIFY] Cycle summary sent directly via Telegram')
    print('  Scan summary sent via Telegram.')

except Exception as _scan_ex:
    print(f'  Scan notify error (non-fatal): {_scan_ex}')
