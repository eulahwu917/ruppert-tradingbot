"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full          — scan + positions + smart money + execute (7am, 3pm)
  check         — positions only (10pm)
  smart         — smart money refresh only (lightweight)
  econ_prescan  — position check + econ scan only, skip if no release today (5am)
  weather_only  — position check + weather scan only (7pm)
  crypto_only   — position check + crypto scan only (10am, 6pm)
  report        — 7am P&L summary + loss detection
"""
import sys, json, time, math, requests
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

sys.stdout.reconfigure(encoding='utf-8')

LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
ALERTS_FILE = LOGS / 'pending_alerts.json'
ALERT_LOG   = LOGS / 'cycle_log.jsonl'

import config
from kalshi_client import KalshiClient
from logger import log_trade, log_activity, get_daily_exposure, get_computed_capital, send_telegram, rotate_logs, normalize_entry_price, acquire_exit_lock, release_exit_lock
from bot.strategy import check_daily_cap, check_open_exposure, should_enter, check_loss_circuit_breaker
from capital import get_capital, get_buying_power


@dataclass
class CycleState:
    """Mutable state bag passed through the cycle."""
    mode: str
    dry_run: bool
    logs_dir: Path
    traded_tickers: set = field(default_factory=set)
    open_position_value: float = 0.0
    actions_taken: list = field(default_factory=list)
    capital: float = 0.0
    buying_power: float = 0.0
    direction: str = 'neutral'


def ts():
    """Return current timestamp string."""
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


def log_cycle(mode, event, data=None):
    """Append structured event to cycle log."""
    entry = {'ts': ts(), 'mode': mode, 'event': event}
    if data: entry.update(data)
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


def save_state(logs_dir, traded_tickers, mode):
    """Write traded_tickers + metadata to logs/state.json for cross-cycle persistence."""
    try:
        _state_path = logs_dir / 'state.json'
        _state_data = {
            'traded_tickers': sorted(traded_tickers),
            'last_cycle_ts': ts(),
            'last_cycle_mode': mode,
        }
        _state_path.write_text(json.dumps(_state_data, indent=2), encoding='utf-8')
    except Exception as _e:
        print(f"  [State] Could not write state.json: {_e}")


def run_post_cycle_exposure_check():
    """Monitoring-only: log a warning if total deployed capital exceeds 70% of portfolio."""
    try:
        total_deployed = get_daily_exposure()
        total_capital  = get_capital()
        if total_capital <= 0:
            log_activity('[RiskCheck] Skipped — total_capital is zero or unavailable')
            return
        exposure_pct = total_deployed / total_capital
        if exposure_pct > 0.70:
            log_activity(f'[RiskCheck] \u26a0\ufe0f Post-cycle exposure at {exposure_pct:.1%} — above 70% cap')
            send_telegram(
                f'\u26a0\ufe0f Ruppert exposure check: {exposure_pct:.1%} of capital deployed '
                f'(above 70% soft cap). Review positions.'
            )
        else:
            log_activity(f'[RiskCheck] Post-cycle exposure: {exposure_pct:.1%} — within cap')
    except Exception as _e:
        log_activity(f'[RiskCheck] Error during exposure check: {_e}')


def load_traded_tickers(logs_dir):
    """Load traded tickers from today's trade log + state.json.

    Returns set of ticker strings that have been traded today.
    Merges from both trades_YYYY-MM-DD.jsonl and state.json (if same-day).
    """
    traded_tickers = set()

    # Populate from today's trade log
    _trade_log_path = logs_dir / f'trades_{date.today().isoformat()}.jsonl'
    if _trade_log_path.exists():
        try:
            for _line in _trade_log_path.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if not _line:
                    continue
                _rec = json.loads(_line)
                _action = _rec.get('action', '')
                _tk = _rec.get('ticker', '')
                if not _tk:
                    continue
                if _action in ('buy', 'open'):
                    traded_tickers.add(_tk)
                elif _action in ('exit', 'settle'):
                    traded_tickers.discard(_tk)
            if traded_tickers:
                print(f"  [Init] Loaded {len(traded_tickers)} open ticker(s) from today's log: {traded_tickers}")
        except Exception as _tl_err:
            print(f"  [Init] Could not read trade log (non-blocking): {_tl_err}")

    # Merge from persistent state.json
    STATE_FILE = logs_dir / 'state.json'
    try:
        if STATE_FILE.exists():
            _state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            _state_ts = _state.get('last_cycle_ts', '')
            if _state_ts[:10] == date.today().isoformat():
                _state_tickers = set(_state.get('traded_tickers', []))
                _before = len(traded_tickers)
                traded_tickers |= _state_tickers
                _added = len(traded_tickers) - _before
                if _added:
                    print(f"  [Init] Merged {_added} ticker(s) from state.json")
            else:
                print(f"  [Init] state.json is from {_state_ts[:10]} (stale) — skipped")
    except Exception as _sf_err:
        print(f"  [Init] Could not read state.json (non-blocking): {_sf_err}")

    return traded_tickers


def check_circuit_breaker(logs_dir, capital):
    """Run loss circuit breaker check.

    Returns None if OK, or dict with 'tripped', 'reason', 'loss_today' if tripped.
    Prints status to stdout.
    """
    try:
        _cb = check_loss_circuit_breaker(str(logs_dir), capital)
        if _cb['tripped']:
            print(f"  [CIRCUIT BREAKER] {_cb['reason']}")
            push_alert('warning', _cb['reason'])
            return _cb
        elif _cb['loss_today'] > 0:
            print(f"  [LossCheck] Today's losses: ${_cb['loss_today']:.2f} — within threshold")
        return None
    except Exception as _cb_err:
        print(f"  [LossCheck] Circuit breaker check failed (non-blocking): {_cb_err}")
        return None


def compute_open_exposure(capital, buying_power):
    """Compute open position value from capital - buying_power.

    Returns max(0.0, capital - buying_power).
    """
    try:
        return max(0.0, capital - buying_power)
    except Exception:
        return 0.0


def run_orphan_reconciliation(client, logs_dir):
    """Compare Kalshi positions against trade log. Push alerts for orphans.

    Prints reconciliation summary. Non-blocking on errors.
    """
    print("\n[0] Orphan position reconciliation...")
    try:
        from post_trade_monitor import load_open_positions as _load_log_positions
        _kalshi_positions = client.get_positions()
        _logged_positions = _load_log_positions()
        _logged_keys = {(p.get('ticker', ''), p.get('side', '')) for p in _logged_positions}

        for _kpos in _kalshi_positions:
            try:
                if isinstance(_kpos, dict):
                    _ticker = _kpos.get('ticker', '') or ''
                    _raw_pos = _kpos.get('position', 0) or 0
                else:
                    _ticker = getattr(_kpos, 'ticker', None) or ''
                    _raw_pos = getattr(_kpos, 'position', None)
                    if _raw_pos is None:
                        _raw_pos = 0
                _raw_pos = int(_raw_pos)
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


def run_exposure_reconciliation(logs_dir, capital, buying_power):
    """Compare log-based exposure vs API-based exposure.

    Pushes alert if divergence > $50 and > 5%. Non-blocking on errors.
    """
    print('\n[0b] Log vs API exposure reconciliation...')
    try:
        _log_exposure = get_daily_exposure()
        _api_exposure = max(0.0, capital - buying_power) if capital > 0 else 0.0
        _divergence = abs(_log_exposure - _api_exposure)
        _divergence_pct = (_divergence / capital * 100) if capital > 0 else 0
        print(f'  Log exposure: ${_log_exposure:.2f} | API exposure: ${_api_exposure:.2f} | Divergence: ${_divergence:.2f} ({_divergence_pct:.1f}%)')
        if _divergence > 50 and _divergence_pct > 5:
            _recon_msg = f'Exposure divergence: logs=${_log_exposure:.2f} vs API=${_api_exposure:.2f} (${_divergence:.2f} gap). Review positions.'
            print(f'  [WARNING] {_recon_msg}')
            push_alert('warning', _recon_msg)
        else:
            print('  Reconciliation OK')
    except Exception as _recon2_err:
        print(f'  [Reconciliation] Log vs API check failed (non-blocking): {_recon2_err}')


def run_position_check(client, state):
    """Check all open positions, trigger weather alerts, execute auto-exits.

    Mutates state.traded_tickers (adds auto-exited tickers).
    Returns list of (action, ticker, side, price, contracts, pnl) tuples for actions taken.
    """
    print("\n[1] Position check...")
    actions_taken = []
    try:
        from openmeteo_client import get_full_weather_signal
        from edge_detector import parse_date_from_ticker, parse_threshold_from_ticker

        trade_log = state.logs_dir / f"trades_{date.today().isoformat()}.jsonl"
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
            if ticker in state.traded_tickers: continue

            # Get current market price
            try:
                m = client.get_market(ticker)
                if not m: continue
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
                                # NO wins if forecast OUTSIDE band — check if forecast moved inside
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
                                    state.traded_tickers.add(ticker)
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
                    if state.dry_run:
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

    return actions_taken


def run_check_mode(state):
    """Check-only mode: just position check, then exit.
    Returns {'actions': int}.
    """
    print(f"\nCheck-only cycle done. {ts()}")
    return {'actions': len(state.actions_taken)}


def run_econ_prescan_mode(client, state):
    """Econ prescan: check releases, trade if any today.
    Returns {'econ_trades': int, 'reason': str (optional)}.
    """
    print("\n[econ_prescan] Checking for econ releases today...")
    _econ_trades = 0
    try:
        from economics_client import get_upcoming_releases as _get_upcoming
        from economics_scanner import find_econ_opportunities as _find_econ
        from logger import get_computed_capital as _get_cap_econ

        _releases_today = [r for r in _get_upcoming() if r.get('days_away') == 0]
        if not _releases_today:
            print("  No econ release today — skipping scan")
            return {'econ_trades': 0, 'reason': 'no_release_today'}

        print(f"  {len(_releases_today)} release(s) today: {[r['event'] for r in _releases_today]}")
        _econ_opps = _find_econ()
        print(f"  {len(_econ_opps)} econ opportunity(ies) found")

        _econ_capital  = _get_cap_econ()
        _econ_deployed = get_daily_exposure()
        _econ_daily_cap = _econ_capital * getattr(config, 'ECON_DAILY_CAP_PCT', 0.04)
        _econ_spent = 0.0

        for opp in _econ_opps:
            ticker = opp.get('ticker', '')
            if ticker in state.traded_tickers:
                print(f"  Already traded {ticker} — skipping")
                continue

            side = opp.get('bet_direction', 'yes')
            mkt_price = int(opp.get('yes_ask', 50) if side == 'yes' else opp.get('no_ask', 50))
            bet_price = mkt_price if side == 'yes' else 100 - mkt_price
            hours_left = max(1.0, opp.get('hours_to_settlement', 48))

            if not check_open_exposure(_econ_capital, state.open_position_value):
                print(f"  [GlobalCap] STOP: open exposure ${state.open_position_value:.2f} >= 70% of capital")
                break

            _cap_ok = check_daily_cap(_econ_capital, _econ_deployed + _econ_spent)
            if _cap_ok <= 0:
                print(f"  [DailyCap] Daily cap reached — stopping econ trades")
                break

            signal = {
                'edge': opp.get('edge', 0),
                'win_prob': opp.get('model_prob', 0.5),
                'confidence': opp.get('confidence', 0),
                'hours_to_settlement': hours_left,
                'module': 'econ',
                'vol_ratio': 1.0,
                'side': side,
                'yes_ask': int(opp.get('yes_ask', 50)),
                'yes_bid': int(opp.get('yes_bid', 50)),
                'open_position_value': state.open_position_value,
            }
            decision = should_enter(signal, _econ_capital, _econ_deployed + _econ_spent)
            if not decision['enter']:
                print(f"  [Strategy] SKIP {ticker}: {decision['reason']}")
                continue
            if decision['size'] > _econ_daily_cap - _econ_spent:
                print(f"  [DailyCap] SKIP {ticker}: would exceed econ daily cap")
                continue

            size = min(decision['size'], _cap_ok)
            contracts = max(1, int(size / bet_price * 100))
            actual_cost = round(contracts * bet_price / 100, 2)

            trade = {
                'ticker': ticker,
                'title': opp.get('title', ticker),
                'side': side,
                'action': 'buy',
                'yes_price': int(opp.get('yes_ask', 50)),
                'market_prob': opp.get('market_prob', 0.5),
                'noaa_prob': None,
                'edge': opp.get('edge'),
                'confidence': opp.get('confidence'),
                'size_dollars': actual_cost,
                'contracts': contracts,
                'source': 'econ',
                'note': opp.get('reasoning', '')[:200],
                'timestamp': ts(),
                'date': str(date.today()),
            }

            if state.dry_run:
                log_trade(trade, actual_cost, contracts, {'dry_run': True})
                log_activity(f'[ECON-PRESCAN] BUY {side.upper()} {ticker} {contracts}@{bet_price}c ${actual_cost:.2f}')
                print(f"  [DEMO] BUY {side.upper()} {ticker} {contracts}@{bet_price}c ${actual_cost:.2f}")
            else:
                try:
                    result = client.place_order(ticker, side, bet_price, contracts)
                    log_trade(trade, actual_cost, contracts, result)
                    log_activity(f'[ECON-PRESCAN] EXECUTED {ticker} {side.upper()} {contracts}@{bet_price}c')
                    print(f"  [LIVE] EXECUTED econ trade: {ticker}")
                except Exception as _ex:
                    print(f"  ERROR executing econ trade {ticker}: {_ex}")
                    continue

            state.traded_tickers.add(ticker)
            _econ_spent += actual_cost
            _econ_trades += 1

    except Exception as _e:
        print(f"  econ_prescan error: {_e}")
        import traceback; traceback.print_exc()

    print(f"\necon_prescan done — {_econ_trades} trade(s). {ts()}")
    return {'econ_trades': _econ_trades}


def run_weather_only_mode(state):
    """Weather-only scan mode.
    Returns {'weather_trades': int}.
    """
    print("\n[weather_only] Running weather scan...")
    _weather_count = 0
    try:
        from main import run_weather_scan as _run_weather
        _weather_results = _run_weather(dry_run=state.dry_run)
        _weather_count = len(_weather_results) if _weather_results else 0
        if _weather_count:
            print(f"  {_weather_count} weather trade(s) executed")
        else:
            print("  No weather opportunities above threshold")
    except Exception as _e:
        print(f"  weather_only error: {_e}")
        import traceback; traceback.print_exc()

    print(f"\nweather_only done — {_weather_count} trade(s). {ts()}")

    # Scan summary notification
    try:
        import time as _time
        _is_dst = _time.daylight and _time.localtime().tm_isdst > 0
        _offset = -7 if _is_dst else -8
        _tz_pdt = timezone(timedelta(hours=_offset))
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        try:
            _capital  = get_computed_capital()
            _deployed = get_daily_exposure()
            _bp       = max(0.0, round(_capital * 0.70 - _deployed, 2))
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'
        _scan_msg = (
            f'\U0001f4ca Ruppert Scan \u2014 {_time_str} PDT\n\n'
            f'\U0001f324 Weather-only scan\n'
            f'{_weather_count} trade(s) placed\n\n'
            f'\U0001f4b0 Capital: {_cap_line}'
        )
        push_alert('warning', _scan_msg)
        send_telegram(_scan_msg)
        log_activity('[SCAN NOTIFY] weather_only summary sent via Telegram')
        print('  Scan summary sent via Telegram.')
    except Exception as _notify_ex:
        print(f'  Scan notify error (non-fatal): {_notify_ex}')

    return {'weather_trades': _weather_count}


def run_crypto_only_mode(state):
    """Crypto-only scan mode.
    Returns {'crypto_trades': int}.
    """
    print("\n[crypto_only] Running crypto scan...")
    _crypto_count = 0
    try:
        from main import run_crypto_scan as _run_crypto
        _crypto_results = _run_crypto(dry_run=state.dry_run, direction=None, traded_tickers=state.traded_tickers, open_position_value=state.open_position_value)
        _crypto_count = len(_crypto_results) if _crypto_results else 0
        if _crypto_count:
            print(f"  {_crypto_count} crypto trade(s) executed")
        else:
            print("  No crypto opportunities above threshold")
    except Exception as _e:
        print(f"  crypto_only error: {_e}")
        import traceback; traceback.print_exc()

    print(f"\ncrypto_only done — {_crypto_count} trade(s). {ts()}")

    # Scan summary notification
    try:
        import time as _time
        _is_dst = _time.daylight and _time.localtime().tm_isdst > 0
        _offset = -7 if _is_dst else -8
        _tz_pdt = timezone(timedelta(hours=_offset))
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        try:
            _capital  = get_computed_capital()
            _deployed = get_daily_exposure()
            _bp       = max(0.0, round(_capital * 0.70 - _deployed, 2))
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'
        _scan_msg = (
            f'\U0001f4ca Ruppert Scan \u2014 {_time_str} PDT\n\n'
            f'\u20bf Crypto-only scan\n'
            f'{_crypto_count} trade(s) placed\n\n'
            f'\U0001f4b0 Capital: {_cap_line}'
        )
        push_alert('warning', _scan_msg)
        send_telegram(_scan_msg)
        log_activity('[SCAN NOTIFY] crypto_only summary sent via Telegram')
        print('  Scan summary sent via Telegram.')
    except Exception as _notify_ex:
        print(f'  Scan notify error (non-fatal): {_notify_ex}')

    return {'crypto_trades': _crypto_count}


def run_report_mode(state):
    """7am P&L summary + loss detection + optimizer review.
    Returns {'exit_count': int, 'losses': int}.
    """
    print("\n[7AM REPORT] P&L Summary + Loss Detection...")

    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    # Load all trades: today + yesterday
    all_records: list = []
    for day_str in [yesterday_str, today_str]:
        log_path = state.logs_dir / f'trades_{day_str}.jsonl'
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

    # Group records: latest entry per ticker, all exits
    entries_by_ticker: dict = {}
    exit_records: list = []

    for rec in all_records:
        action = rec.get('action', 'buy')
        ticker = rec.get('ticker')
        if not ticker:
            continue
        if action in ('buy', 'open'):
            entries_by_ticker[ticker] = rec
        elif action in ('exit', 'settle'):
            exit_records.append(rec)

    # Compute high-level P&L summary
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

    # Scan for losses: explicit exits with negative realized_pnl
    losses: list = []

    for exit_rec in exit_records:
        ticker = exit_rec.get('ticker')

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

    # Write optimizer review file if losses exist
    if losses:
        total_loss = round(sum(l['realized_pnl'] for l in losses), 2)

        review_file = state.logs_dir / 'pending_optimizer_review.json'
        review_data = {
            'date':       today_str,
            'losses':     losses,
            'total_loss': total_loss,
        }
        review_file.write_text(json.dumps(review_data, indent=2), encoding='utf-8')
        print(f"  Wrote pending_optimizer_review.json \u2014 "
              f"{len(losses)} loss(es) totaling ${total_loss:.2f}")

        # Append optimizer alert
        alert_msg = (
            f"Loss review ready: {len(losses)} losing trade(s) totaling "
            f"${abs(total_loss):.2f}. Optimizer review needed."
        )
        push_alert('optimizer', alert_msg)
        print(f"  Alert queued: {alert_msg}")
    else:
        print("  No losses detected \u2014 skipping optimizer review file")

    print(f"\n7am report complete. {ts()}")
    return {'mode': 'report', 'exit_count': len(exit_records), 'losses': len(losses)}


def run_full_mode(client, state):
    """Full cycle: wallet refresh, smart money, weather, crypto, fed, security audit, notification.
    Returns {'weather_trades': int, 'crypto_trades': int, 'fed_trades': int,
             'smart_money': str, 'auto_exits': int}.
    """
    # STEP 1b: WALLET LIST REFRESH
    print("\n[1b] Refreshing smart money wallet list from Polymarket leaderboard...")
    try:
        from bot.wallet_updater import update_wallet_list as _update_wallets
        _wallets_updated = _update_wallets()
        if not _wallets_updated:
            print("  Wallet refresh skipped \u2014 API unavailable, using existing list")
    except Exception as e:
        print(f"  Wallet refresh error (non-fatal): {e}")

    # STEP 2: SMART MONEY REFRESH
    print("\n[2] Refreshing smart money signal...")
    direction = 'neutral'
    try:
        import subprocess, sys as _sys
        r = subprocess.run(
            [_sys.executable, 'fetch_smart_money.py'],
            capture_output=True, text=True, timeout=45,
            cwd=str(Path(__file__).parent)
        )
        if r.returncode == 0:
            sm_cache = state.logs_dir / 'crypto_smart_money.json'
            sm = json.loads(sm_cache.read_text(encoding='utf-8')) if sm_cache.exists() else {}
            direction = sm.get('direction', 'neutral')
            bull_pct  = sm.get('bull_pct', 0.5)
            print(f"  Smart money: {direction.upper()} ({bull_pct:.0%} bull)")
        else:
            print(f"  Smart money fetch failed \u2014 using neutral")
    except Exception as e:
        print(f"  Smart money error: {e}")

    state.direction = direction

    # STEP 3: WEATHER OPPORTUNITY SCAN
    print("\n[3] Scanning for new weather opportunities...")
    new_weather = []
    try:
        from main import run_weather_scan
        new_weather = run_weather_scan(dry_run=state.dry_run)
        if new_weather:
            print(f"  {len(new_weather)} new weather trade(s) executed")
            for t in new_weather:
                print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
        else:
            print("  No new weather opportunities above threshold")
    except Exception as e:
        print(f"  Weather scan error: {e}")

    # Refresh global exposure cap after weather trades before passing to next scan
    state.open_position_value += sum(t.get('size_dollars', 0) for t in new_weather)

    # STEP 4: CRYPTO OPPORTUNITY SCAN
    print("\n[4] Scanning for new crypto opportunities...")
    new_crypto = []
    try:
        from main import run_crypto_scan
        new_crypto = run_crypto_scan(dry_run=state.dry_run, direction=direction, traded_tickers=state.traded_tickers, open_position_value=state.open_position_value)
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
    state.open_position_value += sum(t.get('size_dollars', 0) for t in new_crypto)

    # STEP 4b: FED RATE DECISION SCAN
    print("\n[4b] Scanning for Fed rate decision opportunities...")
    new_fed = []
    try:
        from main import run_fed_scan as _run_fed_scan_cycle
        new_fed = _run_fed_scan_cycle(dry_run=state.dry_run, traded_tickers=state.traded_tickers, open_position_value=state.open_position_value)
        if new_fed:
            print(f"  {len(new_fed)} Fed trade(s) executed")
        else:
            print("  No Fed opportunities this cycle")
    except Exception as e:
        print(f"  Fed scan error: {e}")
        import traceback; traceback.print_exc()

    # STEP 5: SECURITY AUDIT (weekly — Sunday only)
    if datetime.now().weekday() == 6:  # Sunday
        print("\n[5] Weekly security audit...")
        try:
            import subprocess, sys as _sys
            r = subprocess.run([_sys.executable, 'security_audit.py'],
                              capture_output=True, text=True, timeout=30,
                              cwd=str(Path(__file__).parent))
            if 'WARNING' in r.stdout:
                push_alert('security', 'Security audit found issues \u2014 review security_audit output')
                print("  ALERT: issues found \u2014 check logs")
            else:
                print("  Clean \u2014 no issues found")
        except Exception as e:
            print(f"  Audit error: {e}")

    # DONE — summary + notification
    summary = {
        'weather_trades': len(new_weather) if new_weather else 0,
        'crypto_trades':  len(new_crypto) if new_crypto else 0,
        'fed_trades':     len(new_fed) if new_fed else 0,
        'smart_money':    direction,
        'auto_exits':     len(state.actions_taken),
    }
    run_post_cycle_exposure_check()

    print(f"\n{'='*60}")
    print(f"  CYCLE COMPLETE  {ts()}")
    print(f"  Weather: {summary['weather_trades']} new | Crypto: {summary['crypto_trades']} new | Fed: {summary['fed_trades']} new")
    print(f"  Auto-exits: {summary['auto_exits']} | Signal: {direction.upper()}")
    print(f"{'='*60}\n")

    # SCAN SUMMARY NOTIFICATION
    try:
        import time as _time
        is_dst = _time.daylight and _time.localtime().tm_isdst > 0
        offset = -7 if is_dst else -8
        tz_pdt = timezone(timedelta(hours=offset))
        _time_str = datetime.now(tz_pdt).strftime('%I:%M %p')

        # Fed status
        _fed_status = 'no signal (outside window)'
        try:
            _fed_latest_path = state.logs_dir / 'fed_scan_latest.json'
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

        # Capital
        try:
            _capital  = get_computed_capital()
            _deployed = get_daily_exposure()
            _bp       = max(0.0, round(_capital * 0.70 - _deployed, 2))
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'

        # Build message
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

        push_alert('warning', _scan_msg)
        send_telegram(_scan_msg)
        log_activity('[SCAN NOTIFY] Cycle summary sent directly via Telegram')
        print('  Scan summary sent via Telegram.')

    except Exception as _scan_ex:
        print(f'  Scan notify error (non-fatal): {_scan_ex}')

    return summary


def run_cycle(mode):
    """Main entry point. Sets up state, runs common init, dispatches to mode handler.

    Steps:
    1. Print banner, rotate logs
    2. Init KalshiClient
    3. Load traded_tickers
    4. Circuit breaker check (exit if tripped)
    5. Compute open exposure
    6. Run orphan + exposure reconciliation
    7. Run position check (all modes)
    8. Dispatch to mode handler
    9. save_state() + log_cycle('done', summary)
    """
    print(f"\n{'='*60}")
    print(f"  RUPPERT CYCLE  mode={mode.upper()}  {ts()}")
    print(f"{'='*60}")
    log_cycle(mode, 'start')

    try:
        rotate_logs()
    except Exception as e:
        print(f"[Logger] Log rotation skipped: {e}")

    client = KalshiClient()
    logs_dir = Path(__file__).parent / 'logs'
    logs_dir.mkdir(exist_ok=True)

    traded_tickers = load_traded_tickers(logs_dir)

    # Circuit breaker
    capital = get_capital()
    cb = check_circuit_breaker(logs_dir, capital)
    if cb and cb.get('tripped'):
        save_state(logs_dir, traded_tickers, mode)
        log_cycle(mode, 'circuit_breaker', cb)
        sys.exit(0)

    buying_power = get_buying_power()
    open_exposure = compute_open_exposure(capital, buying_power)

    state = CycleState(
        mode=mode,
        dry_run=config.DRY_RUN,
        logs_dir=logs_dir,
        traded_tickers=traded_tickers,
        open_position_value=open_exposure,
        capital=capital,
        buying_power=buying_power,
    )

    # Reconciliation (all modes)
    run_orphan_reconciliation(client, logs_dir)
    run_exposure_reconciliation(logs_dir, capital, buying_power)

    # Position check (all modes)
    state.actions_taken = run_position_check(client, state)

    # Dispatch
    if mode == 'check':
        summary = run_check_mode(state)
    elif mode == 'econ_prescan':
        summary = run_econ_prescan_mode(client, state)
    elif mode == 'weather_only':
        summary = run_weather_only_mode(state)
    elif mode == 'crypto_only':
        summary = run_crypto_only_mode(state)
    elif mode == 'report':
        summary = run_report_mode(state)
    elif mode in ('full', 'smart'):
        summary = run_full_mode(client, state)
    else:
        raise ValueError(f'Unknown mode: {mode}')

    save_state(logs_dir, state.traded_tickers, mode)
    log_cycle(mode, 'done', summary)


if __name__ == '__main__':
    _mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    run_cycle(_mode)
