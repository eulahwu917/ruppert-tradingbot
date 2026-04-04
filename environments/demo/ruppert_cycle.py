"""
Ruppert Autonomous Trading Cycle
Runs on schedule via Windows Task Scheduler.
Modes:
  full          — scan + positions + smart money + execute (7am, 3pm)
  check         — positions only (10pm)
  crypto_only   — position check + crypto scan only (10am, 6pm)
  crypto_1d     — daily crypto above/below scan only (09:30 ET, 13:30 ET)
  report        — 7am P&L summary + loss detection
"""
import sys, json
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass, field

# Ensure env root is on path (for 'import config', scripts/, etc.)
_ENV_ROOT = Path(__file__).parent
if str(_ENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENV_ROOT))
# Ensure workspace root is on path (for 'agents.ruppert.*')
_WORKSPACE_ROOT = _ENV_ROOT.parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

sys.stdout.reconfigure(encoding='utf-8')

LOGS = Path(__file__).parent / 'logs'
LOGS.mkdir(exist_ok=True)
ALERT_LOG   = LOGS / 'cycle_log.jsonl'

import config
from scripts.event_logger import log_event
from agents.ruppert.data_analyst.kalshi_client import KalshiClient
from agents.ruppert.data_scientist.logger import log_trade, log_activity, get_daily_exposure, send_telegram, rotate_logs, normalize_entry_price, acquire_exit_lock, release_exit_lock
from agents.ruppert.strategist.strategy import check_daily_cap, check_open_exposure, should_enter, check_loss_circuit_breaker
from agents.ruppert.data_scientist.capital import get_capital, get_buying_power


def _get_local_tz():
    """Return the America/Los_Angeles timezone."""
    from zoneinfo import ZoneInfo
    return ZoneInfo('America/Los_Angeles')


def _normalize_side(s: str) -> str:
    s = (s or '').lower()
    return 'yes' if s in ('yes', 'buy') else 'no'


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
    """Log alert candidate event. Data Scientist decides if it's alertworthy."""
    log_event('ALERT_CANDIDATE', {
        'level': level,
        'message': message,
        'ticker': ticker,
        'pnl': pnl,
    })


def log_cycle(mode, event, data=None):
    """Append structured event to cycle log."""
    entry = {'ts': ts(), 'mode': mode, 'event': event}
    if data: entry.update(data)
    with open(ALERT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


_LOCK_FILE = Path(__file__).parent / 'logs' / 'ruppert_cycle.lock'

def _acquire_cycle_lock(mode: str) -> bool:
    """Try to acquire cycle lock. Returns True if acquired, False if already running."""
    import os
    if _LOCK_FILE.exists():
        try:
            locked_pid = int(_LOCK_FILE.read_text(encoding='utf-8').strip())
            # Check if that process is still alive
            try:
                os.kill(locked_pid, 0)  # Signal 0 = existence check, no actual signal
                print(f'  [Lock] Cycle already running (PID {locked_pid}) — aborting {mode}')
                log_activity(f'[CycleLock] Aborted {mode}: PID {locked_pid} still running')
                return False
            except (ProcessLookupError, PermissionError):
                # Process is dead — stale lock, remove it
                print(f'  [Lock] Stale lock (PID {locked_pid} dead) — clearing')
                _LOCK_FILE.unlink(missing_ok=True)
        except Exception as _le:
            print(f'  [Lock] Could not read lock file: {_le} — proceeding without lock')
            return True
    _LOCK_FILE.write_text(str(os.getpid()), encoding='utf-8')
    return True

def _release_cycle_lock():
    """Release the cycle lock file."""
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def save_state(logs_dir, traded_tickers, mode):
    """Write traded_tickers + metadata to logs/state.json for cross-cycle persistence.
    Also logs a STATE_UPDATE event so Data Scientist can synthesize state.
    """
    try:
        _state_path = logs_dir / 'state.json'
        _state_data = {
            'traded_tickers': sorted(traded_tickers),
            'last_cycle_ts': ts(),
            'last_cycle_mode': mode,
        }
        _tmp_path = _state_path.with_suffix('.tmp')
        _tmp_path.write_text(json.dumps(_state_data, indent=2), encoding='utf-8')
        _tmp_path.replace(_state_path)
        log_event('STATE_UPDATE', {
            'traded_tickers': sorted(traded_tickers),
            'mode': mode,
        })
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
    from agents.ruppert.env_config import get_paths as _get_env_paths
    _trade_log_path = _get_env_paths()['trades'] / f'trades_{date.today().isoformat()}.jsonl'
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
                # Note: exits do NOT remove from dedup — once traded, blocked for the day
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
        _cb = check_loss_circuit_breaker(capital)
        if _cb['tripped']:
            print(f"  [CIRCUIT BREAKER] {_cb['reason']}")
            log_event('CIRCUIT_BREAKER', {
                'reason': _cb['reason'],
                'loss_today': _cb.get('loss_today', 0),
            })
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
        from agents.ruppert.trader.post_trade_monitor import load_open_positions as _load_log_positions
        _kalshi_positions = client.get_positions()
        _logged_positions = _load_log_positions()
        _logged_keys = {(p.get('ticker', ''), _normalize_side(p.get('side', ''))) for p in _logged_positions}

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
                log_event('ANOMALY_DETECTED', {
                    'check': 'orphan_position',
                    'ticker': _ticker,
                    'detail': _msg,
                })
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
    """Check all open positions.

    Mutates state.traded_tickers (adds auto-exited tickers).
    Returns list of (action, ticker, side, price, contracts, pnl) tuples for actions taken.
    """
    # NOTE: auto-exits for positions are handled by position_monitor.py (scheduled).
    # This function is display-only — actions_taken reflects manual overrides only.
    print("\n[1] Position check...")
    actions_taken = []
    try:
        from agents.ruppert.env_config import get_paths as _get_paths_pc
        # Load last N days of trade records to catch multi-day open positions
        _LOOKBACK_DAYS = getattr(config, 'POSITION_CHECK_LOOKBACK_DAYS', 7)
        open_positions_by_ticker: dict = {}
        for _day_offset in range(_LOOKBACK_DAYS, -1, -1):
            _day_str = (datetime.now(_get_local_tz()).date() - timedelta(days=_day_offset)).isoformat()
            _log = _get_paths_pc()['trades'] / f"trades_{_day_str}.jsonl"
            if not _log.exists():
                continue
            for line in _log.read_text(encoding='utf-8').splitlines():
                try:
                    rec = json.loads(line.strip())
                except Exception:
                    continue
                ticker = rec.get('ticker', '')
                if not ticker:
                    continue
                if rec.get('action') in ('buy', 'open'):
                    open_positions_by_ticker[ticker] = rec
                elif rec.get('action') in ('exit', 'settle'):
                    open_positions_by_ticker.pop(ticker, None)
        open_positions = list(open_positions_by_ticker.values())

        print(f"  {len(open_positions)} open position(s)")

        for pos in open_positions:
            ticker = pos.get('ticker', '')
            source = pos.get('source', 'bot')
            if source not in ('bot', 'crypto'): continue
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
                _yb = m.get('yes_bid')
                _nb = m.get('no_bid')
                yes_bid = _yb if _yb is not None else yes_ask
                no_bid  = _nb if _nb is not None else no_ask
                cur_p   = no_bid if side == 'no' else yes_bid
                contracts = pos.get('contracts', 0)
                pnl     = round((cur_p - entry_p) * contracts / 100, 2)

                print(f'  {ticker:38} {side.upper()} entry={entry_p}c cur={cur_p}c P&L=${pnl:+.2f}')
            except Exception as e:
                print(f'  Error checking {ticker}: {e}')

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


def run_crypto_only_mode(state):
    """Crypto-only scan mode.
    Returns {'crypto_trades': int}.
    """
    print("\n[crypto_only] Running crypto scan...")
    _crypto_count = 0
    try:
        from agents.ruppert.trader.main import run_crypto_scan as _run_crypto
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
        _tz_pdt = _get_local_tz()
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        _tz_abbr = datetime.now(_tz_pdt).strftime('%Z')
        try:
            _capital  = get_capital()
            _deployed = get_daily_exposure()
            _bp       = get_buying_power()
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'
        _15m_block = _build_crypto_15m_block()
        _scan_msg = (
            f'\U0001f4ca Ruppert Scan \u2014 {_time_str} {_tz_abbr}\n\n'
            f'\u20bf Crypto-only scan\n'
            f'{_crypto_count} trade(s) placed'
            f'{_15m_block}\n\n'
            f'\U0001f4b0 Capital: {_cap_line}'
        )
        log_event('SCAN_COMPLETE', {
            'mode': 'crypto_only',
            'crypto_trades': _crypto_count,
            'summary': _scan_msg,
        })
        if _crypto_count > 0:
            send_telegram(_scan_msg)
            log_activity('[SCAN NOTIFY] crypto_only summary sent via Telegram')
        push_alert('info', _scan_msg)
        print('  Scan summary sent via Telegram.')
    except Exception as _notify_ex:
        print(f'  Scan notify error (non-fatal): {_notify_ex}')

    return {'crypto_trades': _crypto_count}


def _build_crypto_15m_block() -> str:
    """Build the 15m crypto summary block for Telegram scan notifications.
    Reads from logs/decisions_15m.jsonl. Returns '' if file is missing/empty.
    """
    try:
        log_path = LOGS / 'decisions_15m.jsonl'
        if not log_path.exists():
            return ''

        from datetime import date as _date
        today_prefix = _date.today().isoformat()

        entries = []
        with open(log_path, encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    rec = json.loads(_line)
                    if str(rec.get('ts', '')).startswith(today_prefix):
                        entries.append(rec)
                except Exception:
                    pass

        if not entries:
            return ''

        total_evals = len(entries)
        entries_count = 0
        late_skips = 0
        other_skips = 0
        last_entry_rec = None
        for rec in entries:
            decision = rec.get('decision', '')
            if decision == 'ENTER':
                entries_count += 1
                ts_val = rec.get('ts', '')
                if last_entry_rec is None or ts_val > last_entry_rec.get('ts', ''):
                    last_entry_rec = rec
            elif decision == 'SKIP_LATE' or rec.get('skip_reason') == 'LATE_WINDOW':
                late_skips += 1
            elif decision and decision != 'ENTER':
                other_skips += 1

        if entries_count > 0:
            entries_line = f'Entries: {entries_count} | Late skips: {late_skips} | Other skips: {other_skips}'
        else:
            entries_line = 'Entries: 0 (no trades placed yet today)'

        last_entry_line = ''
        if last_entry_rec:
            market_id = last_entry_rec.get('market_id', last_entry_rec.get('ticker', ''))
            price = last_entry_rec.get('entry_price', last_entry_rec.get('price'))
            edge = last_entry_rec.get('edge')
            price_str = f'@ {price}¢' if price is not None else ''
            edge_str = f' (edge: +{round(float(edge)*100):.0f}%)' if edge is not None else ''
            last_entry_line = f'\n  Last entry: {market_id} {price_str}{edge_str}'

        return (
            f'\n\n\U0001f4ca Crypto 15m (today):\n'
            f'  Evaluated: {total_evals} windows\n'
            f'  {entries_line}{last_entry_line}'
        )
    except Exception:
        return ''


def run_crypto_1d_mode(state):
    """
    crypto_1d mode: daily above/below scan for KXBTCD / KXETHD.
    Runs at 09:30 ET (primary window) and 13:30 ET (secondary window, gated by exposure).
    Returns {'crypto_1d_trades': int}.
    """
    print("\n[crypto_1d] Running daily crypto above/below scan...")
    _1d_count = 0
    try:
        from agents.ruppert.trader.main import run_crypto_1d_scan as _run_1d
        _1d_results = _run_1d(
            dry_run=state.dry_run,
            traded_tickers=state.traded_tickers,
            open_position_value=state.open_position_value,
        )
        _1d_count = len(_1d_results) if _1d_results else 0
        if _1d_count:
            print(f"  {_1d_count} crypto_1d trade(s) executed")
            for t in _1d_results:
                print(f"    {t.get('asset')} {t.get('ticker')} ${t.get('size_dollars', 0):.2f}")
        else:
            print("  No crypto_1d entries placed this window")
    except Exception as _e:
        print(f"  crypto_1d error: {_e}")
        import traceback; traceback.print_exc()

    print(f"\ncrypto_1d done — {_1d_count} trade(s). {ts()}")

    # Scan summary notification
    try:
        _tz_pdt = _get_local_tz()
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        _tz_abbr = datetime.now(_tz_pdt).strftime('%Z')
        try:
            _capital  = get_capital()
            _deployed = get_daily_exposure()
            _bp       = get_buying_power()
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'
        _scan_msg = (
            f'\U0001f4ca Ruppert Scan \u2014 {_time_str} {_tz_abbr}\n\n'
            f'\u20bf Crypto 1D (daily above/below)\n'
            f'{_1d_count} trade(s) placed\n\n'
            f'\U0001f4b0 Capital: {_cap_line}'
        )
        log_event('SCAN_COMPLETE', {
            'mode': 'crypto_1d',
            'crypto_1d_trades': _1d_count,
            'summary': _scan_msg,
        })
        if _1d_count > 0:
            send_telegram(_scan_msg)
            log_activity('[SCAN NOTIFY] crypto_1d summary sent via Telegram')
        push_alert('info', _scan_msg)
        print('  Scan summary sent via Telegram.')
    except Exception as _notify_ex:
        print(f'  Scan notify error (non-fatal): {_notify_ex}')

    return {'crypto_1d_trades': _1d_count}


def run_report_mode(state):
    """7am P&L summary + loss detection + optimizer review.
    Returns {'exit_count': int, 'losses': int}.
    """
    print("\n[7AM REPORT] P&L Summary + Loss Detection...")

    today_str = date.today().isoformat()

    # Load all trades: rolling 7-day window (matches run_position_check lookback)
    all_records: list = []
    from agents.ruppert.env_config import get_paths as _get_paths_rpt
    _rpt_trades_dir = _get_paths_rpt()['trades']
    _lookback_days = 7
    _day_strs = [
        (date.today() - timedelta(days=i)).isoformat()
        for i in range(_lookback_days - 1, -1, -1)
    ]
    for day_str in _day_strs:
        log_path = _rpt_trades_dir / f'trades_{day_str}.jsonl'
        if log_path.exists():
            for line in log_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    all_records.append(json.loads(line))
                except Exception:
                    pass

    print(f"  Loaded {len(all_records)} record(s) from past {_lookback_days} days")

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
    _missing_pnl_count = sum(1 for r in exit_records if r.get('realized_pnl') is None)
    if _missing_pnl_count > 0:
        print(f"  [ReportWarn] {_missing_pnl_count} exit record(s) missing realized_pnl — P&L approximated from size_dollars")
        log_activity(f"[Report] WARNING: {_missing_pnl_count} exit(s) missing realized_pnl field")
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

        log_event('OPTIMIZER_REVIEW_NEEDED', {
            'date': today_str,
            'losses': losses,
            'total_loss': total_loss,
        })
        print(f"  Emitted OPTIMIZER_REVIEW_NEEDED — {len(losses)} loss(es) totaling ${total_loss:.2f}")

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
    """Full cycle: wallet refresh, smart money, crypto, security audit, notification.
    Returns {'crypto_trades': int, 'long_horizon_trades': int,
             'smart_money': str, 'auto_exits': int}.
    """
    # STEP 1b: WALLET LIST REFRESH
    print("\n[1b] Refreshing smart money wallet list from Polymarket leaderboard...")
    try:
        from agents.ruppert.data_analyst.wallet_updater import update_wallet_list as _update_wallets
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
            [_sys.executable, '-m', 'agents.ruppert.data_analyst.fetch_smart_money'],
            capture_output=True, text=True, timeout=45,
            cwd=str(Path(__file__).parent.parent.parent),  # workspace root
            env={**__import__('os').environ, 'PYTHONPATH': str(Path(__file__).parent.parent.parent)},
        )
        if r.returncode == 0:
            from agents.ruppert.env_config import get_paths as _get_paths_sm
            sm_cache = _get_paths_sm()['truth'] / 'crypto_smart_money.json'
            sm = json.loads(sm_cache.read_text(encoding='utf-8')) if sm_cache.exists() else {}
            direction = sm.get('direction', 'neutral')
            bull_pct  = sm.get('bull_pct', 0.5)
            print(f"  Smart money: {direction.upper()} ({bull_pct:.0%} bull)")
        else:
            print(f"  Smart money fetch failed \u2014 using neutral")
    except Exception as e:
        print(f"  Smart money error: {e}")

    state.direction = direction

    # STEP 3: CRYPTO OPPORTUNITY SCAN
    print("\n[3] Scanning for new crypto opportunities...")
    new_crypto = []
    try:
        from agents.ruppert.trader.main import run_crypto_scan
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

    # STEP 4a: LONG-HORIZON CRYPTO SCAN (daily, 7AM)
    print("\n[4a] Scanning for long-horizon crypto opportunities...")
    new_long_horizon = []
    try:
        from agents.ruppert.trader.crypto_long_horizon import run_long_horizon_scan
        new_long_horizon = run_long_horizon_scan(
            client, dry_run=state.dry_run,
            traded_tickers=state.traded_tickers,
            open_position_value=state.open_position_value,
        )
        if new_long_horizon:
            print(f"  {len(new_long_horizon)} long-horizon trade(s) executed")
            for t in new_long_horizon:
                print(f"    {t.get('ticker')} {t.get('side','').upper()} edge={t.get('edge',0)*100:.0f}%")
        else:
            print("  No long-horizon opportunities above threshold")
    except Exception as e:
        print(f"  Long-horizon scan error: {e}")
        import traceback; traceback.print_exc()

    state.open_position_value += sum(t.get('size_dollars', 0) for t in new_long_horizon)

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
        'crypto_trades':  len(new_crypto) if new_crypto else 0,
        'long_horizon_trades': len(new_long_horizon) if new_long_horizon else 0,
        'smart_money':    direction,
        'auto_exits':     len(state.actions_taken),
    }
    run_post_cycle_exposure_check()

    print(f"\n{'='*60}")
    print(f"  CYCLE COMPLETE  {ts()}")
    print(f"  Crypto: {summary['crypto_trades']} new | LongHorizon: {summary['long_horizon_trades']} new")
    print(f"  Auto-exits: {summary['auto_exits']} | Signal: {direction.upper()}")
    print(f"{'='*60}\n")

    # SCAN SUMMARY NOTIFICATION
    try:
        _tz_pdt = _get_local_tz()
        _time_str = datetime.now(_tz_pdt).strftime('%I:%M %p')
        _tz_abbr = datetime.now(_tz_pdt).strftime('%Z')

        # Capital
        try:
            _capital  = get_capital()
            _deployed = get_daily_exposure()
            _bp       = get_buying_power()
            _cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
        except Exception:
            _cap_line = 'N/A'

        # Build message
        _c_opps   = len(new_crypto) if isinstance(new_crypto, list) else 0
        _c_trades = summary['crypto_trades']
        _c_dir    = direction.upper() if direction else 'NEUTRAL'

        _15m_block = _build_crypto_15m_block()
        _scan_msg = (
            f"\U0001f4ca Ruppert Scan \u2014 {_time_str} {_tz_abbr}\n\n"
            f"\u20bf Crypto: {_c_dir} | {_c_opps} opportunities | {_c_trades} trades placed"
            f"{_15m_block}\n\n"
            f"\U0001f4b0 Capital: {_cap_line}"
        )

        log_event('SCAN_COMPLETE', {
            'mode': 'full',
            'crypto_trades': summary['crypto_trades'],
            'long_horizon_trades': summary.get('long_horizon_trades', 0),
            'smart_money': summary['smart_money'],
            'summary': _scan_msg,
        })
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
    if not _acquire_cycle_lock(mode):
        sys.exit(0)
    try:
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

        # Only run historical audit on substantive modes — skip for lightweight check/report
        if mode == 'full':
            try:
                from agents.ruppert.data_scientist.data_agent import run_historical_audit
                run_historical_audit(since_date=(date.today() - timedelta(days=30)).isoformat())
            except Exception as _ha_err:
                log_activity(f'[DataAgent] Historical audit failed: {_ha_err}')

        # Reconciliation (all modes)
        run_orphan_reconciliation(client, logs_dir)
        run_exposure_reconciliation(logs_dir, capital, buying_power)

        # Position check (all modes)
        state.actions_taken = run_position_check(client, state)

        # Dispatch
        if mode == 'check':
            summary = run_check_mode(state)
        elif mode == 'crypto_only':
            summary = run_crypto_only_mode(state)
        elif mode == 'report':
            summary = run_report_mode(state)
        elif mode == 'crypto_1d':
            summary = run_crypto_1d_mode(state)
        elif mode == 'full':
            summary = run_full_mode(client, state)
        else:
            raise ValueError(f'Unknown mode: {mode}')

        # ── Save state FIRST so synthesizer reads current cycle's STATE_UPDATE ──────
        save_state(logs_dir, state.traded_tickers, mode)

        # ── Data Scientist: post-scan audit (non-fatal) ─────────────────────────────
        if mode in ('full', 'crypto_only', 'crypto_1d'):
            try:
                from agents.ruppert.data_scientist.data_agent import run_post_scan_audit
                _audit = run_post_scan_audit(mode='post_cycle')
                _iss = _audit.get('issues_found', 0)
                if _iss:
                    print(f'  [DataAgent] {_iss} issue(s) found and handled')
            except Exception as _da_err:
                log_activity(f'[DataAgent] Post-scan audit failed: {_da_err}')

        log_cycle(mode, 'done', summary)

    finally:
        _release_cycle_lock()


if __name__ == '__main__':
    _mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    run_cycle(_mode)
