"""
data_agent.py — Post-scan auditor + dashboard consistency checks.

Runs automatically:
  1. After every scan cycle (hooked in ruppert_cycle.py)
  2. Once per day at startup (historical audit from 2026-03-26)
  3. Manually: python data_agent.py --full / --today / --details

Zero bad data tolerance during DEMO data-gathering phase.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths
from agents.ruppert.data_scientist.logger import log_activity, send_telegram
from agents.ruppert.trader import position_tracker

logger = logging.getLogger(__name__)

_paths = _get_paths()
LOGS_DIR = _paths['logs']
TRADES_DIR = _paths['trades']  # P0-1 fix: trade files live in logs/trades/
TRUTH_DIR = _paths['truth']
LOGS_DIR.mkdir(exist_ok=True)
TRADES_DIR.mkdir(parents=True, exist_ok=True)
TRUTH_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = LOGS_DIR / 'data_audit_state.json'
PNL_CACHE_FILE = TRUTH_DIR / 'pnl_cache.json'   # truth dir — same file capital.py reads
TRACKER_FILE = LOGS_DIR / 'tracked_positions.json'

REQUIRED_FIELDS = ['ticker', 'side', 'size_dollars', 'module', 'ts_or_timestamp']

# ts_or_timestamp is a virtual field — we accept either 'ts' or 'timestamp'
_REAL_REQUIRED = ['ticker', 'side', 'size_dollars', 'module']

TICKER_MODULE_MAP = {
    'KXHIGHT': 'weather', 'KXHIGHNY': 'weather', 'KXHIGHMI': 'weather',
    'KXHIGHCH': 'weather', 'KXHIGHDE': 'weather', 'KXHIGHLAX': 'weather',
    'KXHIGHAUS': 'weather', 'KXHIGHSE': 'weather', 'KXHIGHSF': 'weather',
    'KXHIGHPH': 'weather', 'KXHIGHLV': 'weather', 'KXHIGHSA': 'weather',
    'KXHIGHMIA': 'weather', 'KXHIGHAT': 'weather',
    'KXBTC': 'crypto', 'KXETH': 'crypto', 'KXXRP': 'crypto',
    'KXDOGE': 'crypto', 'KXSOL': 'crypto',
    'KXBTC15M': 'crypto_15m', 'KXETH15M': 'crypto_15m',
    'KXXRP15M': 'crypto_15m', 'KXDOGE15M': 'crypto_15m',
    'KXCPI': 'econ', 'KXPCE': 'econ', 'KXJOBS': 'econ',
    'KXFED': 'fed', 'KXFOMC': 'fed',
    'KXBTCMAX': 'crypto_long', 'KXBTCMIN': 'crypto_long',
    'KXETHMAXM': 'crypto_long', 'KXETHMINY': 'crypto_long',
    'KXBTCMAXY': 'crypto_long', 'KXBTCMINY': 'crypto_long',
    'KXETHMAXY': 'crypto_long', 'KXBTC2026': 'crypto_long',
    'KXBTCMAX1': 'crypto_long',
}

ALERT_DEDUP_SECONDS = 4 * 3600  # 4 hours


# ─────────────────────────────── State management ─────────────────────────────


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'last_full_audit': None,
        'last_post_scan_audit': None,
        'alerted_issues': {},
        'cumulative_stats': {
            'total_issues_found': 0,
            'auto_fixed': 0,
            'flagged': 0,
            'alerts_sent': 0,
        },
    }


def _save_state(state: dict):
    try:
        tmp = STATE_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
        tmp.replace(STATE_FILE)
    except Exception as e:
        print(f'[DataAgent] State save failed: {e}')


def _issue_hash(issue_type: str, detail: str) -> str:
    return hashlib.md5(f'{issue_type}:{detail}'.encode()).hexdigest()[:12]


def _should_alert(state: dict, issue_hash: str) -> bool:
    """Return True if this issue hasn't been alerted within ALERT_DEDUP_SECONDS."""
    last_alert = state.get('alerted_issues', {}).get(issue_hash)
    if not last_alert:
        return True
    try:
        last_ts = datetime.fromisoformat(last_alert)
        return (datetime.now() - last_ts).total_seconds() > ALERT_DEDUP_SECONDS
    except Exception:
        return True


def _mark_alerted(state: dict, issue_hash: str):
    state.setdefault('alerted_issues', {})[issue_hash] = datetime.now().isoformat()


def _purge_old_alerts(state: dict):
    """Remove alert hashes older than 24 hours."""
    cutoff = datetime.now() - timedelta(hours=24)
    alerted = state.get('alerted_issues', {})
    to_remove = []
    for h, ts_str in alerted.items():
        try:
            if datetime.fromisoformat(ts_str) < cutoff:
                to_remove.append(h)
        except Exception:
            to_remove.append(h)
    for h in to_remove:
        alerted.pop(h, None)


# ─────────────────────────────── Trade log I/O ────────────────────────────────


def _read_trades_file(path: Path) -> list[dict]:
    trades = []
    if not path.exists():
        return trades
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            trades.append(json.loads(line))
        except Exception:
            pass
    return trades


def _write_trades_file(path: Path, trades: list[dict]):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        for t in trades:
            f.write(json.dumps(t) + '\n')
    tmp.replace(path)


def _get_trade_files(since_date: str = '2026-03-26') -> list[Path]:
    """Return sorted list of trade log files from since_date forward."""
    files = []
    for p in sorted(TRADES_DIR.glob('trades_*.jsonl')):  # P0-1 fix: scan logs/trades/
        try:
            file_date = p.stem.replace('trades_', '')
            if file_date >= since_date:
                files.append(p)
        except Exception:
            pass
    return files


def _today_trades_path() -> Path:
    return TRADES_DIR / f'trades_{date.today().isoformat()}.jsonl'  # P0-1 fix


# ─────────────────────────────── Check functions ──────────────────────────────


def check_duplicate_trade_ids(trades: list[dict]) -> list[str]:
    seen = set()
    dupes = []
    for t in trades:
        tid = t.get('trade_id') or t.get('id')
        if not tid:
            continue
        if tid in seen:
            dupes.append(tid)
        seen.add(tid)
    return dupes


def check_missing_fields(trade: dict) -> list[str]:
    missing = [f for f in _REAL_REQUIRED if not trade.get(f)]
    # Check timestamp: accept either 'ts' or 'timestamp'
    if not trade.get('ts') and not trade.get('timestamp'):
        missing.append('ts/timestamp')
    return missing


def check_dry_run_mismatch(trade: dict) -> bool:
    order = trade.get('order_result', {})
    if isinstance(order, dict):
        status = order.get('status', '')
        return status not in ('simulated', 'dry_run', '') and not order.get('dry_run')
    return False


def check_module_mismatch(trade: dict) -> tuple:
    """Returns (is_mismatch, expected_module_or_None)."""
    ticker = (trade.get('ticker') or '').upper()
    recorded_module = trade.get('module', '')
    # Sort prefixes longest-first so KXBTCMAX matches before KXBTC
    for prefix in sorted(TICKER_MODULE_MAP.keys(), key=len, reverse=True):
        if ticker.startswith(prefix):
            expected = TICKER_MODULE_MAP[prefix]
            if recorded_module != expected:
                return True, expected
            return False, None
    return False, None


def check_tracker_drift(tracked: dict, open_positions: list = None) -> dict:
    """Compare open trades vs position tracker. Uses all-time logs for multi-day positions.

    Comparison is done on (ticker, side) pairs to correctly detect side-specific
    orphans (e.g. KXBTC::yes closed while KXBTC::no remains open).
    Returns both orphan_pairs (for precise cleanup) and orphans (ticker list for
    backward-compat with _remove_tracker_orphans).
    """
    if open_positions is None:
        open_positions = get_open_positions_from_logs()
    # Build set of (ticker, side) pairs from logs
    open_keys = {(t.get('ticker', ''), t.get('side', '')) for t in open_positions}
    open_tickers = {ticker for ticker, side in open_keys}
    # Build set of (ticker, side) pairs from tracker
    tracked_pairs = set()
    for k in tracked.keys():
        if '::' in k:
            parts = k.split('::', 1)
            tracked_pairs.add((parts[0], parts[1]))
        else:
            tracked_pairs.add((k, ''))
    tracked_tickers = {ticker for ticker, side in tracked_pairs}

    # Pair-level orphan detection (catches side-specific orphans)
    orphan_pairs = list(tracked_pairs - open_keys)
    # Derive ticker list for _remove_tracker_orphans (which operates on tickers)
    orphan_tickers = list({t for t, s in orphan_pairs})

    return {
        'orphans': orphan_tickers,           # ticker list — used by _remove_tracker_orphans
        'orphan_pairs': orphan_pairs,        # (ticker, side) pairs — for diagnostics/logging
        'missing': list(open_tickers - tracked_tickers),
    }


def check_entry_price_spread(trade: dict) -> bool:
    ep = trade.get('entry_price') or trade.get('scan_price') or trade.get('fill_price')
    if ep is None:
        return False
    ep = float(ep)
    yes_ask = trade.get('yes_ask') or trade.get('market_ask')
    yes_bid = trade.get('yes_bid') or trade.get('market_bid')
    if yes_ask and yes_bid:
        return not (float(yes_bid) - 2 <= ep <= float(yes_ask) + 2)
    return False


def check_daily_cap_violations(trades_today: list[dict]) -> list[dict]:
    try:
        from agents.ruppert.data_scientist.capital import get_capital
        import importlib.util as _ilu
        from agents.ruppert.env_config import get_env_root as _get_env_root
        _cfg_path = _get_env_root() / 'config.py'
        if not _cfg_path.exists():
            return []
        _spec = _ilu.spec_from_file_location('config', _cfg_path)
        cfg = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(cfg)
        capital = get_capital()
    except Exception:
        return []

    caps = {
        'weather': capital * getattr(cfg, 'WEATHER_DAILY_CAP_PCT', 0.07),
        'crypto': capital * getattr(cfg, 'CRYPTO_DAILY_CAP_PCT', 0.07),
        'econ': capital * getattr(cfg, 'ECON_DAILY_CAP_PCT', 0.04),
        'fed': capital * getattr(cfg, 'FED_DAILY_CAP_PCT', 0.03),
        'crypto_15m': capital * getattr(cfg, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04),
        'crypto_long': capital * getattr(cfg, 'LONG_HORIZON_DAILY_CAP_PCT', 0.10),
        'geo': capital * getattr(cfg, 'GEO_DAILY_CAP_PCT', 0.04),
    }

    by_module = {}
    for t in trades_today:
        if t.get('action') in ('exit', 'settle'):
            continue
        m = t.get('module', 'unknown')
        by_module[m] = by_module.get(m, 0) + (t.get('size_dollars') or 0)

    violations = []
    for module, total in by_module.items():
        cap = caps.get(module)
        if cap and total > cap * 1.05:
            violations.append({'module': module, 'total': round(total, 2), 'cap': round(cap, 2)})
    return violations


def compute_pnl_from_logs() -> float:
    """Compute closed P&L from all trade logs (exit records with pnl field)."""
    total_pnl = 0.0
    for path in _get_trade_files():
        for t in _read_trades_file(path):
            if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
                try:
                    total_pnl += float(t['pnl'])
                except (ValueError, TypeError):
                    pass
    return round(total_pnl, 2)


def check_pnl_consistency() -> tuple:
    """Returns (is_mismatch, cached_pnl, computed_pnl)."""
    cached = 0.0
    if PNL_CACHE_FILE.exists():
        try:
            data = json.loads(PNL_CACHE_FILE.read_text(encoding='utf-8'))
            cached = float(data.get('closed_pnl', 0))
        except Exception:
            pass
    computed = compute_pnl_from_logs()
    delta = abs(cached - computed)
    return delta > 0.10, cached, computed


def get_open_positions_from_logs() -> list[dict]:
    """Get open positions by scanning all trade files.

    Scale-in fix: aggregate cost_basis and contracts across all buy legs
    per (ticker, side). Stop aggregating when an exit/settle record is
    encountered for that (ticker, side) key.

    Key type aligned with logger.get_daily_exposure() — both use (ticker, side)
    tuple to correctly handle separate YES and NO legs on the same ticker.
    """
    entries = {}   # (ticker, side) -> aggregated record (based on first buy leg)
    exits = set()  # set of (ticker, side) tuples

    for path in _get_trade_files():
        for t in _read_trades_file(path):
            ticker = t.get('ticker', '')
            side = t.get('side', '')
            if not ticker:
                continue
            key = (ticker, side)
            action = t.get('action', 'buy')
            if action in ('exit', 'settle'):
                exits.add(key)
                entries.pop(key, None)  # clear any accumulated entry
            else:
                if key not in entries:
                    # First buy leg: store a copy as the base record
                    entries[key] = dict(t)
                else:
                    # Scale-in: accumulate size_dollars and contracts,
                    # and update entry_price to the weighted average cost basis.
                    old_contracts = int(entries[key].get('contracts') or 0)
                    new_contracts = int(t.get('contracts') or 0)
                    old_price     = float(entries[key].get('entry_price') or 0)
                    new_price     = float(t.get('entry_price') or 0)
                    entries[key]['size_dollars'] = (
                        float(entries[key].get('size_dollars') or 0)
                        + float(t.get('size_dollars') or 0)
                    )
                    total_contracts = old_contracts + new_contracts
                    entries[key]['contracts'] = total_contracts
                    if total_contracts > 0:
                        entries[key]['entry_price'] = round(
                            (old_price * old_contracts + new_price * new_contracts) / total_contracts, 2
                        )

    return [rec for key, rec in entries.items() if key not in exits]


def compute_win_rate_from_logs(module: str) -> float | None:
    """Compute win rate for a module from exit records."""
    wins = 0
    total = 0
    for path in _get_trade_files():
        for t in _read_trades_file(path):
            if t.get('action') != 'exit':
                continue
            if t.get('module') != module:
                continue
            pnl = t.get('pnl')
            if pnl is not None:
                total += 1
                if float(pnl) > 0:
                    wins += 1
    if total == 0:
        return None
    return round(wins / total, 3)


def check_dashboard_consistency(open_positions: list = None) -> list[dict]:
    """Compare dashboard API responses against trade log computations.

    Only runs if the dashboard is reachable (non-blocking).
    """
    if open_positions is None:
        open_positions = get_open_positions_from_logs()
    log_open = open_positions
    issues = []
    try:
        import requests
        base = 'http://localhost:8765'
        # Quick connectivity check
        try:
            requests.get(f'{base}/api/mode', timeout=2)
        except Exception:
            return []  # dashboard not running — skip

        # --- Open positions ---
        try:
            api_positions_resp = requests.get(f'{base}/api/account', timeout=5).json()
            api_count = api_positions_resp.get('open_trade_count', 0)
            log_count = len(log_open)
            if abs(api_count - log_count) > 0:
                issues.append({
                    'check': 'open_position_count',
                    'dashboard': api_count,
                    'log': log_count,
                    'delta': api_count - log_count,
                })
        except Exception:
            pass

        # --- Closed P&L ---
        try:
            pnl_data = requests.get(f'{base}/api/pnl', timeout=5).json()
            api_pnl = pnl_data.get('closed_pnl', 0)
            log_pnl = compute_pnl_from_logs()
            if abs(api_pnl - log_pnl) > 0.10:
                issues.append({
                    'check': 'closed_pnl',
                    'dashboard': api_pnl,
                    'log': log_pnl,
                    'delta': round(api_pnl - log_pnl, 2),
                })
        except Exception:
            pass

        # --- Capital deployed ---
        try:
            api_deployed = api_positions_resp.get('total_deployed', 0)
            log_deployed = sum(t.get('size_dollars', 0) for t in log_open)
            if abs(api_deployed - log_deployed) > 1.0:
                issues.append({
                    'check': 'capital_deployed',
                    'dashboard': api_deployed,
                    'log': log_deployed,
                    'delta': round(api_deployed - log_deployed, 2),
                })
        except Exception:
            pass

    except ImportError:
        pass  # requests not available

    return issues


def check_decision_log_orphans() -> list[dict]:
    """Check for decision log entries with no matching trade.

    Scans all known decision log files (crypto 15m, weather, econ, fed, crypto_long).
    """
    decision_paths = [
        LOGS_DIR / 'decisions_15m.jsonl',
        LOGS_DIR / 'decisions_weather.jsonl',
        LOGS_DIR / 'decisions_econ.jsonl',
        LOGS_DIR / 'decisions_fed.jsonl',
        LOGS_DIR / 'decisions_crypto_long.jsonl',
    ]
    decisions = []
    for decision_path in decision_paths:
        if decision_path.exists():
            decisions.extend(_read_trades_file(decision_path))
    if not decisions:
        return []
    today_trades = _read_trades_file(_today_trades_path())
    trade_tickers = {t.get('ticker') for t in today_trades}

    orphans = []
    for d in decisions:
        if d.get('decision', '').upper() in ('SKIP',):
            continue
        ticker = d.get('market_id', d.get('ticker', ''))
        d_date = str(d.get('ts', ''))[:10]
        if d_date == date.today().isoformat() and ticker not in trade_tickers:
            orphans.append(d)
    return orphans


def check_ws_stale_trades(trades: list[dict]) -> list[dict]:
    """Flag trades from last 7 days where price_source was 'rest' at entry."""
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    flagged = []
    for t in trades:
        t_date = t.get('date', '')
        if t_date < cutoff:
            continue
        if t.get('action') in ('exit', 'settle'):
            continue
        price_source = t.get('price_source', '')
        if price_source == 'rest':
            flagged.append(t)
    return flagged


def check_exit_price_discrepancies(trades: list[dict], tracked: dict) -> list[dict]:
    """Compare exit prices in trade log vs position tracker exit log."""
    discrepancies = []
    for t in trades:
        if t.get('action') != 'exit':
            continue
        ticker = t.get('ticker', '')
        log_exit_price = t.get('exit_price')
        if log_exit_price is None:
            continue
        # Check if tracker has a different record
        tracker_pos = tracked.get(ticker, {})
        tracker_exit = tracker_pos.get('exit_price')
        if tracker_exit is not None and abs(float(log_exit_price) - float(tracker_exit)) > 5:
            discrepancies.append({
                'ticker': ticker,
                'log_exit_price': log_exit_price,
                'tracker_exit_price': tracker_exit,
                'delta': round(abs(float(log_exit_price) - float(tracker_exit)), 1),
            })
    return discrepancies


# ─────────────────────────────── Cleanup actions ─────────────────────────────


def _cleanup_duplicates(path: Path, dupe_ids: list[str]) -> int:
    """Remove duplicate trade entries (keep first occurrence). Returns count removed."""
    trades = _read_trades_file(path)
    seen = set()
    cleaned = []
    removed = 0
    for t in trades:
        tid = t.get('trade_id') or t.get('id')
        if tid in dupe_ids and tid in seen:
            removed += 1
            continue
        if tid:
            seen.add(tid)
        cleaned.append(t)
    if removed:
        _write_trades_file(path, cleaned)
    return removed


def _mark_invalid(path: Path, trade_id: str, reason: str):
    """Add _invalid markers to a trade record."""
    trades = _read_trades_file(path)
    changed = False
    for t in trades:
        if (t.get('trade_id') or t.get('id')) == trade_id:
            t['_invalid'] = True
            t['_invalid_reason'] = reason
            changed = True
            break
    if changed:
        _write_trades_file(path, trades)


def _fix_module(path: Path, trade_id: str, correct_module: str):
    """Auto-fix module field on a trade record."""
    trades = _read_trades_file(path)
    changed = False
    for t in trades:
        if (t.get('trade_id') or t.get('id')) == trade_id:
            old_module = t.get('module', '')
            t['module'] = correct_module
            t['_module_corrected_from'] = old_module
            changed = True
            break
    if changed:
        _write_trades_file(path, trades)


def _flag_trade(path: Path, trade_id: str, flag_key: str, flag_value=True):
    """Add a flag to a trade record."""
    trades = _read_trades_file(path)
    changed = False
    for t in trades:
        if (t.get('trade_id') or t.get('id')) == trade_id:
            t[flag_key] = flag_value
            changed = True
            break
    if changed:
        _write_trades_file(path, trades)


def _register_missing_positions(missing_tickers: list, open_positions: list) -> int:
    """Reconstruct and register missing positions back into the tracker file.

    Mirrors _remove_tracker_orphans but writes entries instead of deleting them.
    Uses position_tracker.add_position() to ensure exit_thresholds are computed
    correctly (prevents WS crash on missing exit_thresholds).
    Each reconstructed entry is flagged with _reconstructed=True and a timestamp
    for auditability. Returns count of successfully registered positions.
    """
    if not missing_tickers or not open_positions:
        return 0
    try:
        # Build lookup: ticker -> list of open position records
        pos_by_ticker: dict = {}
        for pos in open_positions:
            t = pos.get('ticker', '')
            if t:
                pos_by_ticker.setdefault(t, []).append(pos)

        registered = 0
        reconstructed_at = datetime.now().isoformat()

        for ticker in missing_tickers:
            records = pos_by_ticker.get(ticker, [])
            if not records:
                continue
            for rec in records:
                side = rec.get('side', '')
                key = f'{ticker}::{side}' if side else ticker

                # Skip if already present (race condition guard)
                if position_tracker.is_tracked(ticker, side):
                    continue

                entry_price = rec.get('entry_price')
                quantity = rec.get('contracts')
                module = rec.get('module', TICKER_MODULE_MAP.get(ticker.upper(), 'unknown'))
                title = rec.get('title') or ticker

                # Guard: skip if entry_price is missing or zero — cannot compute exit thresholds
                if not entry_price:
                    logger.warning(
                        '[DataAgent] Skipping reconstruction for %s — entry_price is null, cannot compute exit thresholds',
                        ticker,
                    )
                    continue

                position_tracker.add_position(ticker, quantity, side, entry_price, module, title)

                # Preserve _reconstructed flag for observability after add_position() wrote the entry
                pos_key = (ticker, side)
                if pos_key in position_tracker._tracked:
                    position_tracker._tracked[pos_key]['_reconstructed'] = True
                    position_tracker._tracked[pos_key]['_reconstructed_at'] = reconstructed_at

                registered += 1

        if registered:
            position_tracker._persist()

        return registered
    except Exception as e:
        print(f'[DataAgent] Tracker missing-position registration failed: {e}')
        return 0


def _remove_tracker_orphans(orphan_tickers: list, open_positions: list = None):
    """Remove orphan tickers from position tracker file.

    orphan_tickers is a list of plain ticker strings. To avoid deleting valid
    sibling-side entries (e.g., KXBTC::no is still open when KXBTC::yes is orphaned),
    we cross-check each compound key against the current open positions before removing.
    """
    if not TRACKER_FILE.exists():
        return
    try:
        tracked = json.loads(TRACKER_FILE.read_text(encoding='utf-8'))
        # Get currently open (ticker, side) pairs from logs to avoid over-deletion
        if open_positions is None:
            open_positions = get_open_positions_from_logs()
        open_keys = {(t.get('ticker', ''), t.get('side', '')) for t in open_positions}
        changed = False
        for ticker in orphan_tickers:
            keys_to_remove = []
            for k in list(tracked.keys()):
                if k == ticker:
                    # Plain key — remove if ticker has no open position at all
                    if not any(t == ticker for t, s in open_keys):
                        keys_to_remove.append(k)
                elif k.startswith(ticker + '::'):
                    # Compound key — only remove if (ticker, side) has no open position
                    side = k.split('::', 1)[1]
                    if (ticker, side) not in open_keys:
                        keys_to_remove.append(k)
            for k in keys_to_remove:
                del tracked[k]
                changed = True
        if changed:
            tmp = TRACKER_FILE.with_suffix('.tmp')
            tmp.write_text(json.dumps(tracked, indent=2), encoding='utf-8')
            tmp.replace(TRACKER_FILE)
    except Exception as e:
        print(f'[DataAgent] Tracker orphan cleanup failed: {e}')


def _regenerate_pnl_cache():
    """Regenerate pnl_cache.json from trade logs.

    Writes closed_pnl only. open_pnl is not persisted here — the
    synthesizer computes it from live prices on the next synthesis run.
    (The open_pnl preservation block was dead code: synthesize_pnl_cache()
    always overwrites pnl_cache.json immediately after this function runs.)
    """
    computed = compute_pnl_from_logs()
    cache_data = {'closed_pnl': computed}
    tmp = PNL_CACHE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(cache_data), encoding='utf-8')
    tmp.replace(PNL_CACHE_FILE)
    return computed


# ─────────────────────────────── Alert formatting ─────────────────────────────


def _format_single_alert(issue_type: str, ticker: str, detail: str, action: str) -> str:
    lines = [f'\u26a0\ufe0f Data Scientist: {issue_type}']
    if ticker:
        lines.append(f'Ticker: {ticker}')
    lines.append(f'Detail: {detail}')
    lines.append(f'Action: {action}')
    return '\n'.join(lines)


def _format_batch_alert(issues: list[dict], audit_file: str = '') -> str:
    lines = [f'\u26a0\ufe0f Data Scientist: {len(issues)} issues found in post-scan audit']
    # Group by type, tracking first-seen action per type
    by_type = {}
    by_action = {}
    for iss in issues:
        t = iss.get('type', 'unknown')
        by_type[t] = by_type.get(t, 0) + 1
        if t not in by_action:
            by_action[t] = iss.get('action', '')
    for t, count in sorted(by_type.items()):
        action = by_action.get(t, '')
        lines.append(f'- {count}x {t} ({action})')
    if audit_file:
        lines.append(f'Details: {audit_file}')
    return '\n'.join(lines)


def _format_escalation_alert(issue_type: str, ticker: str, detail: str) -> str:
    lines = [
        '\U0001f50d Data Scientist: Needs your review (not auto-fixed)',
        f'Issue: {issue_type}',
    ]
    if ticker:
        lines.append(f'Trade: {ticker}')
    lines.append(detail)
    lines.append('Action needed: Tell Ruppert which is correct.')
    return '\n'.join(lines)


# ─────────────────────────────── Main audit logic ─────────────────────────────


def run_post_scan_audit(mode: str = 'post_cycle') -> dict:
    """Run after every scan cycle. Returns summary dict."""
    state = _load_state()
    _purge_old_alerts(state)
    issues = []
    auto_fixed = 0
    flagged = 0

    today_path = _today_trades_path()
    today_trades = _read_trades_file(today_path)

    # Load tracker
    tracked = {}
    if TRACKER_FILE.exists():
        try:
            tracked = json.loads(TRACKER_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass

    # Compute open positions once — passed to all sub-checks to avoid redundant file scans
    open_positions = get_open_positions_from_logs()

    # ── Critical checks (every cycle) ─────────────────────────────────────

    # 1. Duplicate trade IDs
    dupes = check_duplicate_trade_ids(today_trades)
    if dupes:
        removed = _cleanup_duplicates(today_path, dupes)
        auto_fixed += removed
        for d in dupes:
            issues.append({
                'type': 'duplicate_trade_id', 'trade_id': d,
                'action': f'deleted {removed} duplicate(s)',
            })
            log_activity(f'[DataAgent] Removed duplicate trade_id: {d}')
        # Reload after cleanup
        today_trades = _read_trades_file(today_path)

    # 2. Missing required fields (skip exit/settle records — different schema)
    for t in today_trades:
        if t.get('_invalid'):
            continue
        if t.get('action') in ('exit', 'settle'):
            continue
        missing = check_missing_fields(t)
        if missing:
            tid = t.get('trade_id', 'unknown')
            _mark_invalid(today_path, tid, f'missing: {missing}')
            flagged += 1
            issues.append({
                'type': 'missing_fields', 'trade_id': tid,
                'ticker': t.get('ticker', ''),
                'missing': missing,
                'action': 'marked _invalid',
            })
            log_activity(f'[DataAgent] Missing fields on {tid[:8]}: {missing}')

    # Reload after potential modifications
    today_trades = _read_trades_file(today_path)

    # 3. Dry run mismatch
    for t in today_trades:
        if t.get('_invalid'):
            continue
        if check_dry_run_mismatch(t):
            tid = t.get('trade_id', 'unknown')
            ticker = t.get('ticker', '')
            _mark_invalid(today_path, tid, 'live_order_in_demo')
            flagged += 1
            issue = {
                'type': 'dry_run_mismatch', 'trade_id': tid,
                'ticker': ticker, 'action': 'marked _invalid + ALERT',
            }
            issues.append(issue)
            # Immediate alert for dry run mismatch
            ih = _issue_hash('dry_run_mismatch', tid)
            if _should_alert(state, ih):
                send_telegram(_format_single_alert(
                    'LIVE ORDER IN DEMO MODE',
                    ticker,
                    f'Trade {tid[:8]} has non-simulated order_result',
                    'Marked _invalid. REVIEW IMMEDIATELY.',
                ))
                _mark_alerted(state, ih)
                state['cumulative_stats']['alerts_sent'] = state['cumulative_stats'].get('alerts_sent', 0) + 1
            log_activity(f'[DataAgent] DRY RUN MISMATCH: {tid[:8]} {ticker}')

    # 4. Module/ticker mismatch
    today_trades = _read_trades_file(today_path)
    for t in today_trades:
        if t.get('_invalid'):
            continue
        is_mismatch, expected = check_module_mismatch(t)
        if is_mismatch and expected:
            tid = t.get('trade_id', 'unknown')
            old_module = t.get('module', '')
            _fix_module(today_path, tid, expected)
            auto_fixed += 1
            issues.append({
                'type': 'module_mismatch', 'trade_id': tid,
                'ticker': t.get('ticker', ''),
                'old_module': old_module, 'new_module': expected,
                'action': f'auto-fixed: {old_module} -> {expected}',
            })
            log_activity(f'[DataAgent] Module fix: {tid[:8]} {old_module} -> {expected}')

    # 5. Position tracker drift
    drift = check_tracker_drift(tracked, open_positions=open_positions)
    if drift['orphans']:
        _remove_tracker_orphans(drift['orphans'], open_positions=open_positions)
        auto_fixed += len(drift['orphans'])
        issues.append({
            'type': 'tracker_orphans',
            'tickers': drift['orphans'],
            'action': f'removed {len(drift["orphans"])} orphan(s) from tracker',
        })
        log_activity(f'[DataAgent] Removed tracker orphans: {drift["orphans"]}')
    if drift['missing']:
        registered = _register_missing_positions(drift['missing'], open_positions)
        if registered > 0:
            auto_fixed += registered
            issues.append({
                'type': 'tracker_missing',
                'level': 'info',  # auto-healed — no alert needed
                'tickers': drift['missing'],
                'action': f'auto-registered {registered} missing position(s) into tracker',
            })
            log_activity(f'[DataAgent] Reconstructed {registered} missing tracker entries: {drift["missing"]}')
        else:
            # Reconstruction failed — fall back to logging only
            flagged += len(drift['missing'])
            issues.append({
                'type': 'tracker_missing',
                'level': 'warning',  # reconstruction failed — alert David
                'tickers': drift['missing'],
                'action': 'logged (no auto-add)',
            })
            log_activity(f'[DataAgent] Missing from tracker (reconstruction failed): {drift["missing"]}')

    # ── Important checks (full cycles only) ───────────────────────────────

    if mode in ('post_cycle', 'full'):
        # 6. Entry price outside spread
        for t in today_trades:
            if t.get('_invalid') or t.get('action') in ('exit', 'settle'):
                continue
            if check_entry_price_spread(t):
                tid = t.get('trade_id', 'unknown')
                _flag_trade(today_path, tid, '_price_anomaly')
                flagged += 1
                issues.append({
                    'type': 'price_anomaly', 'trade_id': tid,
                    'ticker': t.get('ticker', ''),
                    'action': 'flagged _price_anomaly',
                })

        # 7. Daily cap violations
        cap_violations = check_daily_cap_violations(today_trades)
        for v in cap_violations:
            flagged += 1
            issues.append({
                'type': 'daily_cap_violation',
                'module': v['module'],
                'total': v['total'],
                'cap': v['cap'],
                'action': 'flagged + ALERT',
            })
            ih = _issue_hash('daily_cap', f'{v["module"]}_{date.today().isoformat()}')
            if _should_alert(state, ih):
                send_telegram(_format_single_alert(
                    'Daily Cap Violation',
                    '',
                    f'{v["module"]}: ${v["total"]:.0f} vs ${v["cap"]:.0f} cap',
                    'Flagged. Review position sizes.',
                ))
                _mark_alerted(state, ih)
                state['cumulative_stats']['alerts_sent'] = state['cumulative_stats'].get('alerts_sent', 0) + 1

        # 8. P&L consistency
        pnl_mismatch, cached_pnl, computed_pnl = check_pnl_consistency()
        if pnl_mismatch:
            delta = round(cached_pnl - computed_pnl, 2)
            # Tier 1 auto-fix: regenerate cache from logs
            _regenerate_pnl_cache()
            auto_fixed += 1
            issues.append({
                'type': 'pnl_mismatch',
                'cached': cached_pnl,
                'computed': computed_pnl,
                'delta': delta,
                'action': 'cache regenerated',
            })
            log_activity(f'[DataAgent] P&L mismatch: cached=${cached_pnl} vs computed=${computed_pnl} (delta=${delta}). Cache regenerated.')

        # 9. Decision log orphans
        orphan_decisions = check_decision_log_orphans()
        if orphan_decisions:
            flagged += len(orphan_decisions)
            issues.append({
                'type': 'decision_orphans',
                'count': len(orphan_decisions),
                'action': 'flagged _no_matching_trade',
            })

        # 10. Dashboard consistency
        dash_issues = check_dashboard_consistency(open_positions=open_positions)
        for di in dash_issues:
            check_name = di.get('check', '')
            flagged += 1
            issues.append({
                'type': f'dashboard_{check_name}',
                'detail': di,
                'action': 'flagged',
            })
            if check_name == 'closed_pnl':
                # Already handled by P&L check above
                pass

    # ── Summary and alerting ──────────────────────────────────────────────

    stats = state['cumulative_stats']
    stats['total_issues_found'] = stats.get('total_issues_found', 0) + len(issues)
    stats['auto_fixed'] = stats.get('auto_fixed', 0) + auto_fixed
    stats['flagged'] = stats.get('flagged', 0) + flagged
    state['last_post_scan_audit'] = datetime.now().isoformat()

    if issues:
        # Write audit report
        audit_file = LOGS_DIR / f'data_audit_{date.today().isoformat()}.json'
        audit_report = {
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'issues': issues,
            'auto_fixed': auto_fixed,
            'flagged': flagged,
        }
        try:
            # Append to existing report if present
            existing_report = []
            if audit_file.exists():
                try:
                    existing_report = json.loads(audit_file.read_text(encoding='utf-8'))
                    if isinstance(existing_report, dict):
                        existing_report = [existing_report]
                except Exception:
                    existing_report = []
            existing_report.append(audit_report)
            audit_file.write_text(json.dumps(existing_report, indent=2), encoding='utf-8')
        except Exception as e:
            print(f'[DataAgent] Audit report write failed: {e}')

        # Count only warning-level (or unleveled) issues toward alert thresholds
        # Info-level issues are auto-healed and should not generate alerts
        alertable_issues = [iss for iss in issues if iss.get('level', 'warning') != 'info']

        # Send batch alert if 5+ alertable issues
        if len(alertable_issues) >= 5:
            batch_hash = _issue_hash('batch', f'{date.today().isoformat()}_{len(alertable_issues)}')
            if _should_alert(state, batch_hash):
                send_telegram(_format_batch_alert(alertable_issues, str(audit_file)))
                _mark_alerted(state, batch_hash)
                stats['alerts_sent'] = stats.get('alerts_sent', 0) + 1
        elif len(alertable_issues) > 0:
            # Send individual alerts for non-already-alerted issues
            for iss in alertable_issues:
                iss_type = iss.get('type', '')
                # Skip types that already sent their own alerts above
                if iss_type in ('dry_run_mismatch', 'daily_cap_violation'):
                    continue
                ticker = iss.get('ticker', '')
                ih = _issue_hash(iss_type, iss.get('trade_id', '') or str(iss.get('tickers', '')))
                if _should_alert(state, ih):
                    send_telegram(_format_single_alert(
                        iss_type.replace('_', ' ').title(),
                        ticker,
                        str(iss.get('detail', iss.get('action', ''))),
                        iss.get('action', 'flagged'),
                    ))
                    _mark_alerted(state, ih)
                    stats['alerts_sent'] = stats.get('alerts_sent', 0) + 1

        log_activity(f'[DataAgent] Post-scan audit: {len(issues)} issue(s), {auto_fixed} auto-fixed, {flagged} flagged')
    else:
        log_activity('[DataAgent] Post-scan audit: clean (0 issues)')

    _save_state(state)

    # ── Data Scientist synthesis ───────────────────────────────────────────
    # Synthesizer reads today's event log and updates truth files.
    # Must run after every scan cycle so truth files stay current.
    try:
        from agents.ruppert.data_scientist.synthesizer import run_synthesis
        synth_result = run_synthesis()
        log_activity(f'[DataAgent] Synthesis complete: {synth_result}')
    except Exception as e:
        log_activity(f'[DataAgent] Synthesis failed: {e}')

    return {
        'issues_found': len(issues),
        'auto_fixed': auto_fixed,
        'flagged': flagged,
        'issues': issues,
    }


def run_historical_audit(since_date: str = '2026-03-26') -> dict:
    """Full historical audit from since_date forward. Run once per day."""
    state = _load_state()

    # Check if already ran today
    last_full = state.get('last_full_audit')
    if last_full and last_full[:10] == date.today().isoformat():
        log_activity('[DataAgent] Historical audit already ran today — skipping')
        return {'skipped': True}

    _purge_old_alerts(state)
    all_issues = []
    total_auto_fixed = 0
    total_flagged = 0
    total_trades = 0

    for path in _get_trade_files(since_date):
        trades = _read_trades_file(path)
        total_trades += len(trades)

        # 1. Duplicates
        dupes = check_duplicate_trade_ids(trades)
        if dupes:
            removed = _cleanup_duplicates(path, dupes)
            total_auto_fixed += removed
            all_issues.append({
                'file': path.name, 'type': 'duplicate_trade_id',
                'count': len(dupes), 'action': f'removed {removed}',
            })

        # 2. Missing fields (skip exit/settle records)
        trades = _read_trades_file(path)  # reload
        for t in trades:
            if t.get('_invalid'):
                continue
            if t.get('action') in ('exit', 'settle'):
                continue
            missing = check_missing_fields(t)
            if missing:
                tid = t.get('trade_id', 'unknown')
                _mark_invalid(path, tid, f'missing: {missing}')
                total_flagged += 1
                all_issues.append({
                    'file': path.name, 'type': 'missing_fields',
                    'trade_id': tid, 'missing': missing,
                })

        # 3. Dry run mismatch
        trades = _read_trades_file(path)
        for t in trades:
            if t.get('_invalid'):
                continue
            if check_dry_run_mismatch(t):
                tid = t.get('trade_id', 'unknown')
                _mark_invalid(path, tid, 'live_order_in_demo')
                total_flagged += 1
                all_issues.append({
                    'file': path.name, 'type': 'dry_run_mismatch',
                    'trade_id': tid,
                })

        # 4. Module mismatch
        trades = _read_trades_file(path)
        for t in trades:
            if t.get('_invalid'):
                continue
            is_mismatch, expected = check_module_mismatch(t)
            if is_mismatch and expected:
                tid = t.get('trade_id', 'unknown')
                _fix_module(path, tid, expected)
                total_auto_fixed += 1
                all_issues.append({
                    'file': path.name, 'type': 'module_mismatch',
                    'trade_id': tid, 'fixed_to': expected,
                })

    # 10. WS stale trades (last 7 days)
    all_recent_trades = []
    for path in _get_trade_files(since_date):
        all_recent_trades.extend(_read_trades_file(path))
    stale = check_ws_stale_trades(all_recent_trades)
    if stale:
        total_flagged += len(stale)
        all_issues.append({
            'type': 'ws_stale_at_entry',
            'count': len(stale),
            'tickers': [t.get('ticker', '') for t in stale[:10]],
        })

    # P&L consistency
    pnl_mismatch, cached_pnl, computed_pnl = check_pnl_consistency()
    if pnl_mismatch:
        _regenerate_pnl_cache()
        total_auto_fixed += 1
        all_issues.append({
            'type': 'pnl_mismatch',
            'cached': cached_pnl, 'computed': computed_pnl,
            'action': 'cache regenerated',
        })

    # Write audit report
    report = {
        'timestamp': datetime.now().isoformat(),
        'since_date': since_date,
        'total_trades_audited': total_trades,
        'total_issues': len(all_issues),
        'auto_fixed': total_auto_fixed,
        'flagged': total_flagged,
        'issues': all_issues,
    }
    audit_file = LOGS_DIR / f'data_audit_{date.today().isoformat()}.json'
    try:
        audit_file.write_text(json.dumps(report, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'[DataAgent] Audit report write failed: {e}')

    state['last_full_audit'] = datetime.now().isoformat()
    stats = state['cumulative_stats']
    stats['total_issues_found'] = stats.get('total_issues_found', 0) + len(all_issues)
    stats['auto_fixed'] = stats.get('auto_fixed', 0) + total_auto_fixed
    stats['flagged'] = stats.get('flagged', 0) + total_flagged

    # Alert if issues found
    if all_issues:
        ih = _issue_hash('historical_audit', date.today().isoformat())
        if _should_alert(state, ih):
            msg = (
                f'\U0001f50d Data Agent: Historical audit complete\n'
                f'Period: {since_date} to {date.today().isoformat()}\n'
                f'Trades audited: {total_trades}\n'
                f'Issues: {len(all_issues)} ({total_auto_fixed} auto-fixed, {total_flagged} flagged)\n'
                f'Details: {audit_file}'
            )
            send_telegram(msg)
            _mark_alerted(state, ih)
            stats['alerts_sent'] = stats.get('alerts_sent', 0) + 1
        log_activity(f'[DataAgent] Historical audit: {len(all_issues)} issue(s) across {total_trades} trades')
    else:
        log_activity(f'[DataAgent] Historical audit: clean ({total_trades} trades, 0 issues)')

    _save_state(state)
    return report


# ─────────────────────────────── CLI entry point ──────────────────────────────


def main():
    parser = argparse.ArgumentParser(description='Ruppert Data Agent — post-scan auditor')
    parser.add_argument('--full', action='store_true', help='Run full historical audit')
    parser.add_argument('--today', action='store_true', help='Run post-scan audit on today\'s trades')
    parser.add_argument('--details', action='store_true', help='Print detailed results')
    parser.add_argument('--since', default='2026-03-26', help='Start date for historical audit')
    args = parser.parse_args()

    if args.full:
        print(f'[DataAgent] Running full historical audit from {args.since}...')
        result = run_historical_audit(since_date=args.since)
    elif args.today:
        print('[DataAgent] Running post-scan audit on today\'s trades...')
        result = run_post_scan_audit(mode='full')
    else:
        print('[DataAgent] Running post-scan audit (default)...')
        result = run_post_scan_audit(mode='post_cycle')

    if args.details or args.full:
        print(json.dumps(result, indent=2, default=str))
    else:
        issues = result.get('issues_found', result.get('total_issues', 0))
        auto = result.get('auto_fixed', 0)
        flag = result.get('flagged', 0)
        print(f'[DataAgent] Done: {issues} issue(s), {auto} auto-fixed, {flag} flagged')


if __name__ == '__main__':
    main()
