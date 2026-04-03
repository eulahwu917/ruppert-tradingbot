"""
Trade Logger
Logs all bot activity, trades, and outcomes to files.
"""
import glob
import json
import logging
import os
import sys
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths, require_live_enabled, get_current_env  # noqa: E402

_PDT = ZoneInfo('America/Los_Angeles')

def _pdt_today() -> date:
    """Return the current date in America/Los_Angeles (PDT/PST)."""
    return datetime.now(_PDT).date()

_env_paths = _get_paths()
LOG_DIR = str(_env_paths['logs'])
TRADES_DIR = str(_env_paths['trades'])  # P0-1 fix: trade files go to logs/trades/
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TRADES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Log rotation - called once per cycle from ruppert_cycle.py
# ---------------------------------------------------------------------------

LOG_RETENTION_DAYS = 90  # keep 90 days of trade + activity logs

def rotate_logs(retention_days: int = LOG_RETENTION_DAYS) -> int:
    """
    Delete trade and activity log files older than retention_days.
    Returns count of files deleted.

    Safe: only removes files matching trades_YYYY-MM-DD.jsonl and
    activity_YYYY-MM-DD.log patterns - never touches other files.
    """
    cutoff = date.today() - timedelta(days=retention_days)
    patterns = [
        os.path.join(TRADES_DIR, 'trades_*.jsonl'),  # P0-1 fix: trades in logs/trades/
        os.path.join(LOG_DIR, 'activity_*.log'),
    ]
    deleted = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            fname = os.path.basename(path)
            # Extract date portion: trades_YYYY-MM-DD.jsonl → YYYY-MM-DD
            try:
                date_str = fname.split('_', 1)[1].rsplit('.', 1)[0]
                file_date = date.fromisoformat(date_str)
                if file_date < cutoff:
                    os.remove(path)
                    deleted += 1
            except Exception:
                pass  # skip files that don't match expected date format
    if deleted:
        print(f"[Logger] Rotated {deleted} log file(s) older than {retention_days} days")
    return deleted


def _today_log_path():
    return os.path.join(TRADES_DIR, f"trades_{_pdt_today().isoformat()}.jsonl")

def _activity_log_path():
    return os.path.join(LOG_DIR, f"activity_{_pdt_today().isoformat()}.log")


_portalocker_warned = False

def _append_jsonl(log_path, record: dict) -> None:
    """Atomically append a single JSON record to a JSONL file.
    Uses portalocker for cross-process safety on Windows.
    Falls back to plain append if portalocker unavailable.
    """
    global _portalocker_warned
    line = json.dumps(record) + '\n'
    try:
        import portalocker
        with open(log_path, 'a', encoding='utf-8') as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            try:
                f.write(line)
            finally:
                portalocker.unlock(f)
    except ImportError:
        if not _portalocker_warned:
            _portalocker_warned = True
            logger.warning('[Logger] portalocker not available — falling back to plain file append (no cross-process lock)')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line)


def _build_ensemble_components(opportunity: dict) -> dict | None:
    """Extract per-model probabilities and divergence from opportunity dict."""
    models_used = opportunity.get('models_used')
    if not models_used:
        return None
    model_map = {m['model']: m for m in models_used}
    ecmwf = model_map.get('ecmwf_ifs025', {})
    gfs   = model_map.get('gfs_seamless', {})
    icon  = model_map.get('icon_global', {})
    means = [m.get('mean_f') for m in models_used if m.get('mean_f') is not None]
    divergence_f = round(max(means) - min(means), 1) if len(means) >= 2 else None
    return {
        'ecmwf_prob':   ecmwf.get('prob'),
        'gfs_prob':     gfs.get('prob'),
        'icon_prob':    icon.get('prob'),
        'divergence_f': divergence_f,
    }


def build_trade_entry(opportunity, size, contracts, order_result, **extra_fields):
    """Build a standardized trade entry dict with all required fields.

    Enforces schema consistency for every trade written to JSONL logs.
    Adds a unique trade_id (uuid4) and ensures source, module, action,
    timestamp, and date are always present.

    extra_fields: any key/value pairs are merged into the entry after standard
    fields are set (overrides built-in values for exit_price, settlement_result, etc.).
    """
    # Infer module from source and ticker if not explicitly set
    source = opportunity.get('source', 'bot')
    module = opportunity.get('module', '')
    if not module:
        # Delegate to classify_module — single source of truth
        module = classify_module(source, opportunity.get('ticker', ''))

    raw_action = opportunity.get('action', 'buy')
    raw_lower = raw_action.strip().lower() if isinstance(raw_action, str) else str(raw_action).lower()
    if raw_lower.startswith('buy'):
        action = 'buy'
    elif raw_lower.startswith('exit'):
        action = 'exit'
    elif raw_lower.startswith('open'):
        action = 'open'
    else:
        action = raw_lower

    # Resolve entry_price: use explicit entry_price if set, else fall back to fill_price.
    # fill_price is set by trader.py before calling log_trade(), so this is always available
    # for new buys. Cast to float to normalize int/float/string variants.
    _fill = opportunity.get('fill_price')
    _entry = opportunity.get('entry_price')
    entry_price_val = None
    if _entry is not None:
        try:
            entry_price_val = float(_entry)
        except (TypeError, ValueError):
            entry_price_val = None
    if entry_price_val is None and _fill is not None:
        try:
            entry_price_val = float(_fill)
        except (TypeError, ValueError):
            entry_price_val = None

    entry = {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       action,
        'action_detail': raw_action,
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        # ── Weather ensemble audit fields (None for non-weather trades) ────────
        'ensemble_temp_forecast_f': opportunity.get('ensemble_mean'),
        'model_source':             opportunity.get('model_source'),
        'ensemble_components':      _build_ensemble_components(opportunity),
        'entry_price':  entry_price_val,          # ← NEW: was absent
        'size_dollars': size,
        'contracts':    contracts,
        'scan_contracts': opportunity.get('scan_contracts'),
        'fill_contracts': opportunity.get('fill_contracts'),
        'scan_price':   opportunity.get('scan_price'),
        'fill_price':   opportunity.get('fill_price'),
        'order_result': order_result,
        # ── Data quality tags (crypto_15m only; None for all other modules) ──
        'data_quality':          opportunity.get('data_quality'),
        'okx_volume_pct':        opportunity.get('okx_volume_pct'),
        'kalshi_book_depth_usd': opportunity.get('kalshi_book_depth_usd'),
        'kalshi_spread_cents':   opportunity.get('kalshi_spread_cents'),
        # ── Model probability (crypto_15m; None for other modules) ────────
        'model_prob':            opportunity.get('model_prob'),
    }
    # Merge extra fields (for exit_price, settlement_result, action_detail overrides, etc.)
    for k, v in extra_fields.items():
        entry[k] = v
    return entry


# Session-level dedup set: (ticker, side, date, entry_price, contracts)
# Resets on process restart by design — within-session guard only.
_logged_trade_fingerprints: set[tuple] = set()


def log_trade(opportunity, size, contracts, order_result):
    """Log a placed trade to today's trade log."""
    if get_current_env() == 'live':
        require_live_enabled()  # Raises RuntimeError if enabled=false in mode.json
    entry = build_trade_entry(opportunity, size, contracts, order_result)

    # Dedup: skip if an identical trade (same ticker/side/date/price/contracts) already logged this session
    fingerprint = (
        entry.get('ticker'),
        entry.get('side'),
        entry.get('date'),
        entry.get('entry_price'),
        entry.get('contracts'),
    )
    if fingerprint in _logged_trade_fingerprints:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            '[Logger] Duplicate trade suppressed: %s %s %s @ %s (%s contracts)',
            *fingerprint
        )
        return
    _logged_trade_fingerprints.add(fingerprint)

    _append_jsonl(_today_log_path(), entry)
    print(f"[Log] Trade logged: {entry['trade_id'][:8]}.. {entry['ticker']} {entry['side'].upper()} ${size:.2f}")


# Exit/settle dedup set — separate from buy fingerprints.
# Resets on process restart by design — within-session guard only.
_logged_exit_fingerprints: set[str] = set()


def log_exit(opportunity: dict, pnl: float, contracts: int, order_result: dict,
             exit_price: float = None, action_detail: str = None) -> None:
    """Log an exit record. Uses separate dedup fingerprint from buy records."""
    global _logged_exit_fingerprints
    try:
        _extra = {}
        if exit_price is not None:
            _extra['exit_price'] = exit_price
        if action_detail is not None:
            _extra['action_detail'] = action_detail

        entry = build_trade_entry(opportunity, pnl, contracts, order_result, **_extra)

        # Exit dedup: key on (ticker, side, date, action, exit_price) — not same as buy key
        _fp_key = f"{entry.get('ticker')}::{entry.get('side')}::{entry.get('date')}::exit::{exit_price}"
        if _fp_key in _logged_exit_fingerprints:
            logger.warning('[Logger] Duplicate exit suppressed: %s', _fp_key)
            return
        _logged_exit_fingerprints.add(_fp_key)
        entry['_exit_fp'] = _fp_key

        log_path = _today_log_path()
        _append_jsonl(log_path, entry)
        log_activity(f"[EXIT] {entry.get('ticker')} {entry.get('side','').upper()} | P&L=${pnl:+.2f}")
    except Exception as e:
        logger.error('[Logger] log_exit() failed: %s', e)


def log_settle(opportunity: dict, pnl: float, contracts: int, order_result: dict,
               exit_price: float = None, settlement_result: str = None,
               action_detail: str = None) -> None:
    """Log a settle record. Uses separate dedup fingerprint from buy records."""
    global _logged_exit_fingerprints
    try:
        _extra = {}
        if exit_price is not None:
            _extra['exit_price'] = exit_price
        if settlement_result is not None:
            _extra['settlement_result'] = settlement_result
        if action_detail is not None:
            _extra['action_detail'] = action_detail

        entry = build_trade_entry(opportunity, pnl, contracts, order_result, **_extra)

        _fp_key = f"{entry.get('ticker')}::{entry.get('side')}::{entry.get('date')}::settle::{settlement_result}"
        if _fp_key in _logged_exit_fingerprints:
            logger.warning('[Logger] Duplicate settle suppressed: %s', _fp_key)
            return
        _logged_exit_fingerprints.add(_fp_key)
        entry['_exit_fp'] = _fp_key

        log_path = _today_log_path()
        _append_jsonl(log_path, entry)
        log_activity(f"[SETTLE] {entry.get('ticker')} {entry.get('side','').upper()} {settlement_result} | P&L=${pnl:+.2f}")
    except Exception as e:
        logger.error('[Logger] log_settle() failed: %s', e)


def log_opportunity(opportunity):
    """Log a detected opportunity (even if not traded)."""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'type': 'opportunity',
        'ticker': opportunity['ticker'],
        'edge': opportunity['edge'],
        'action': opportunity['action'],
    }
    with open(_activity_log_path(), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


def log_activity(message):
    """Log general bot activity."""
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    print(entry)
    with open(_activity_log_path(), 'a', encoding='utf-8') as f:
        f.write(entry + '\n')


def get_daily_exposure(module: str = None, asset: str = None) -> float:
    """Calculate total $ exposure from all open positions (any age).

    Reads all trade files from START_DATE forward — the same window used by
    data_agent.get_open_positions_from_logs() — so multi-day positions entered
    2+ days ago are correctly counted. Only sums entries (buys) that have no
    corresponding exit/settle record.

    Args:
        module: If provided, only sum exposure for positions whose module field
                equals this value OR starts with '{module}_' (e.g. 'crypto' matches
                'crypto' and 'crypto_15m', 'crypto_long').
        asset:  If provided (e.g. 'BTC'), only sum exposure for positions whose
                ticker contains this string (case-insensitive). Applied IN ADDITION
                to the module filter — both conditions must match when both are given.

    No existing callers break: both kwargs default to None.
    """
    START_DATE = '2026-03-26'  # bot launch date; matches _get_trade_files() default

    entries   = {}   # key: (ticker, side) → accumulated size_dollars
    exit_keys = set()

    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.startswith('trades_') or not fname.endswith('.jsonl'):
            continue
        try:
            file_date = fname[len('trades_'):-len('.jsonl')]
            if file_date < START_DATE:
                continue
        except Exception:
            continue
        log_path = os.path.join(TRADES_DIR, fname)
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker', '')
                    side   = entry.get('side', '')
                    action = entry.get('action', 'buy')
                    key    = (ticker, side)
                    if action in ('exit', 'settle'):
                        exit_keys.add(key)
                        entries.pop(key, None)  # clear accumulated entry on exit
                    elif action == 'failed_order':
                        continue  # ISSUE-029/099: failed orders have zero cost, skip entirely
                    else:
                        if module is not None:
                            entry_module = entry.get('module', '')
                            if not (entry_module == module or
                                    entry_module.startswith(module + '_')):
                                continue
                        # --- asset filter ---
                        if asset is not None:
                            if asset.upper() not in ticker.upper():
                                continue
                        # Skip tickers whose settlement time has already passed (aligns with dashboard)
                        try:
                            from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker as _is_settled
                            if _is_settled(ticker):
                                continue
                        except Exception:
                            pass  # on import failure, include position (conservative)
                        entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)
                except Exception:
                    pass

    # Sum positions that have an entry but no corresponding exit
    return sum(size for key, size in entries.items() if key not in exit_keys)


def _read_trades_for_module(module: str) -> list:
    """Internal helper: read all trade records for a given module from all trade log files.

    Returns a flat list of trade record dicts (all dates, all actions).
    Silently skips missing or malformed files.
    """
    records = []
    if not os.path.isdir(TRADES_DIR):
        return records
    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.startswith('trades_') or not fname.endswith('.jsonl'):
            continue
        log_path = os.path.join(TRADES_DIR, fname)
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get('module') == module:
                            records.append(rec)
                    except Exception:
                        pass
        except Exception:
            pass
    return records


def get_daily_wager(module: str) -> float:
    """
    Returns the total dollars wagered (all buy entries) for the given module today,
    regardless of whether positions have settled or been exited.

    Used for the Tier 2 daily wager backstop in crypto_15m.

    Args:
        module: Module name string (e.g. 'crypto_15m')

    Returns:
        Total size_dollars of all buy actions logged today for this module.
    """
    today = _pdt_today().isoformat()   # 'YYYY-MM-DD'
    total = 0.0
    trades = _read_trades_for_module(module)
    for trade in trades:
        if trade.get('date') == today and trade.get('action') == 'buy':
            total += float(trade.get('size_dollars', 0.0))
    return total


def get_window_exposure(module: str, window_open_ts: str) -> float:
    """
    Returns the total dollars placed (buy entries) for the given module
    within a specific 15-minute window, identified by its open timestamp.

    Used for Tier 1 window cap enforcement and startup re-hydration
    of the in-memory _window_exposure counter.

    Args:
        module:          Module name string (e.g. 'crypto_15m')
        window_open_ts:  ISO timestamp string of the window open
                         (e.g. '2026-03-30T13:15:00') — same key used
                         in _window_exposure dict in crypto_15m.py

    Returns:
        Total size_dollars of all buy actions logged for this module
        in the specified window.
    """
    total = 0.0
    trades = _read_trades_for_module(module)
    for trade in trades:
        if (trade.get('action') == 'buy'
                and trade.get('window_open_ts') == window_open_ts):
            total += float(trade.get('size_dollars', 0.0))
    return total


def normalize_entry_price(pos: dict) -> float:
    """Return entry_price in cents from a position record.

    Falls back to market_prob if entry_price is missing. Handles
    probability-formatted values (0-1) by converting to cents.
    Uses the NO-side convention: market_prob represents YES probability,
    so NO entry cost = (1 - market_prob) * 100.
    """
    side        = pos.get('side', 'no')
    raw_ep      = pos.get('entry_price')
    entry_price = raw_ep if raw_ep is not None else pos.get('market_prob', 0.5) * 100
    if side == 'no':
        entry_price = entry_price if isinstance(entry_price, (int, float)) else 50
        # Normalize: if value looks like a probability (0-1), convert to cents
        if 0 < entry_price < 1:
            entry_price = round((1 - entry_price) * 100)
    return entry_price


def acquire_exit_lock(ticker: str, side: str) -> bool:
    """Create a file-based lock for exit operations on (ticker, side).

    Returns True if the lock was acquired, False if another process already
    holds it. Lock files older than 5 minutes are treated as stale and
    automatically removed so a crashed process can't block exits forever.
    """
    import time
    lock_path = os.path.join(LOG_DIR, f'.exit_lock_{ticker}_{side}')
    if os.path.exists(lock_path):
        try:
            age = time.time() - os.path.getmtime(lock_path)
            if age < 300:   # 5 minutes
                return False
            os.remove(lock_path)  # stale lock - remove and re-acquire
        except Exception:
            return False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_exit_lock(ticker: str, side: str) -> None:
    """Remove the exit lock file for (ticker, side). Safe to call even if absent."""
    lock_path = os.path.join(LOG_DIR, f'.exit_lock_{ticker}_{side}')
    try:
        os.remove(lock_path)
    except Exception:
        pass


def get_parent_module(module_name: str) -> str:
    """Map detailed subcategory → display parent category.

    Single source of truth for display grouping. Used by api.py to populate
    the parent_module field on every position/trade dict so the frontend
    never needs its own classification logic.

    Mapping:
        weather_band, weather_threshold              → 'weather'
        crypto_dir_15m_*, crypto_threshold_daily_*,
          crypto_band_daily_*                        → 'crypto'
        econ_cpi, econ_unemployment,
          econ_fed_rate, econ_recession              → 'econ'
        geo                                          → 'geo'
        sports_odds                                  → 'sports'
        manual, other                                → 'other'
    """
    m = (module_name or '').lower()
    if m.startswith('weather'):
        return 'weather'
    if m.startswith('crypto'):
        return 'crypto'
    if m.startswith('econ'):
        return 'econ'
    if m == 'geo':
        return 'geo'
    if m.startswith('sports'):
        return 'sports'
    return 'other'


def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth - imported by dashboard/api.py to stay in sync.

    Module taxonomy (2026-04-01 — Phase A rename):
      weather_band              KXHIGH*-B*  (ticker contains '-B')
      weather_threshold         KXHIGH*-T*  (ticker contains '-T')
      crypto_dir_15m_btc        KXBTC15M
      crypto_dir_15m_eth        KXETH15M
      crypto_dir_15m_sol        KXSOL15M
      crypto_dir_15m_xrp        KXXRP15M
      crypto_dir_15m_doge       KXDOGE15M
      crypto_threshold_daily_btc  KXBTCD*
      crypto_threshold_daily_eth  KXETHD*
      crypto_threshold_daily_sol  KXSOLD*  (future)
      crypto_threshold_daily_xrp  KXXRPD*
      crypto_threshold_daily_doge KXDOGED*
      crypto_band_daily_btc     KXBTC (band, no D/15M suffix)
      crypto_band_daily_eth     KXETH (band, no D/15M suffix)
      crypto_band_daily_xrp     KXXRP
      crypto_band_daily_doge    KXDOGE
      crypto_band_daily_sol     KXSOL
      econ_cpi                  KXCPI*
      econ_unemployment         KXJOBLESSCLAIMS, KXECONSTATU3, KXUE
      econ_fed_rate             KXFED, KXFOMC
      econ_recession            KXWRECSS
      geo                       geopolitical series (unchanged)
    """
    t = (ticker or '').upper()

    # ── Weather ───────────────────────────────────────────────────────────
    if t.startswith('KXHIGH'):
        if '-T' in t:
            return 'weather_threshold'
        return 'weather_band'  # default: B-type band

    # ── Crypto 15-min direction ───────────────────────────────────────────
    # NOTE: 15M prefixes (KXBTC15M) must be checked BEFORE base prefixes (KXBTC)
    if t.startswith('KXBTC15M') or src == 'crypto_15m' and t.startswith('KXBTC'):
        return 'crypto_dir_15m_btc'
    if t.startswith('KXETH15M'):
        return 'crypto_dir_15m_eth'
    if t.startswith('KXSOL15M'):
        return 'crypto_dir_15m_sol'
    if t.startswith('KXXRP15M'):
        return 'crypto_dir_15m_xrp'
    if t.startswith('KXDOGE15M'):
        return 'crypto_dir_15m_doge'
    # Fallback for src='crypto_15m' with unrecognised asset
    if src == 'crypto_15m':
        return 'crypto_dir_15m_btc'

    # ── Crypto threshold daily (above/below binary) ───────────────────────
    # NOTE: D-suffix series (KXBTCD) must be checked BEFORE base prefixes (KXBTC)
    if t.startswith('KXBTCD') or (src == 'crypto_1d' and t.startswith('KXBTC')):
        return 'crypto_threshold_daily_btc'
    if t.startswith('KXETHD') or (src == 'crypto_1d' and t.startswith('KXETH')):
        return 'crypto_threshold_daily_eth'
    if t.startswith('KXSOLD') or (src == 'crypto_1d' and t.startswith('KXSOL')):
        return 'crypto_threshold_daily_sol'
    if t.startswith('KXXRPD') or (src == 'crypto_1d' and t.startswith('KXXRP')):
        return 'crypto_threshold_daily_xrp'
    if t.startswith('KXDOGED') or (src == 'crypto_1d' and t.startswith('KXDOGE')):
        return 'crypto_threshold_daily_doge'
    # Fallback for src='crypto_1d' with unrecognised asset
    if src == 'crypto_1d':
        return 'crypto_threshold_daily_btc'

    # ── Crypto band daily (range prediction) ─────────────────────────────
    if t.startswith('KXBTC'):
        return 'crypto_band_daily_btc'
    if t.startswith('KXETH'):
        return 'crypto_band_daily_eth'
    if t.startswith('KXXRP'):
        return 'crypto_band_daily_xrp'
    if t.startswith('KXDOGE'):
        return 'crypto_band_daily_doge'
    if t.startswith('KXSOL'):
        return 'crypto_band_daily_sol'
    if src == 'crypto':
        return 'crypto_band_daily_btc'

    # ── Econ subcategories ────────────────────────────────────────────────
    if t.startswith('KXCPI'):
        return 'econ_cpi'
    if any(t.startswith(p) for p in ('KXJOBLESSCLAIMS', 'KXECONSTATU3', 'KXUE')):
        return 'econ_unemployment'
    if src == 'fed' or any(t.startswith(p) for p in ('KXFED', 'KXFOMC')):
        return 'econ_fed_rate'
    if t.startswith('KXWRECSS'):
        return 'econ_recession'
    if src == 'econ':
        return 'econ_cpi'  # fallback for unknown econ tickers

    # ── Geo ───────────────────────────────────────────────────────────────
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'

    # ── Sports ─────────────────────────────────────────────────────────────
    if src == 'sports' or any(
        t.startswith(p) for p in ('KXSPORT', 'KXML', 'KXNBA', 'KXNFL')
    ):
        return 'sports_odds'

    if src == 'manual':
        return 'manual'

    return 'other'


def send_telegram(message: str) -> bool:
    """Send a message to David via the openclaw CLI (routes through gateway)."""
    import subprocess
    try:
        # Use node to invoke openclaw.mjs directly — avoids cmd.exe newline
        # truncation bug where multiline -m args are split at \n by the shell.
        oc_mjs = r'C:\Users\David Wu\AppData\Roaming\npm\node_modules\openclaw\openclaw.mjs'
        result = subprocess.run(
            ['node', oc_mjs, 'message', 'send',
             '--channel', 'telegram',
             '-t', '5003590611',
             '-m', message],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[WARN] send_telegram failed: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"[WARN] send_telegram failed: {e}")
        return False


# In-process mtime cache for compute_closed_pnl_from_logs().
# Never written to disk. Recomputes the instant any log file changes.
_pnl_mtime_cache = {'mtime': None, 'value': None}


def compute_closed_pnl_from_logs() -> float:
    """Compute closed P&L by scanning all trade log files live.

    THIS IS THE SINGLE SOURCE OF TRUTH for closed P&L.
    Sums all three record types:
      1. action='exit'            — pnl field
      2. action='settle'          — pnl field
      3. action='exit_correction' — pnl_correction field
    Do NOT remove any of these — all three are required for correct P&L.

    Uses an in-memory mtime cache: recomputes only when any log file changes.
    """
    import json
    from pathlib import Path

    try:
        from agents.ruppert.env_config import get_paths as _get_paths
        _paths = _get_paths()
        trades_dir = _paths['trades']

        # Gather all log files and compute max mtime for cache invalidation
        # No date filter needed — trades/ only contains clean files (poisoned/archived files
        # are in trades/archive/ which is not matched by this glob pattern)
        log_files = sorted(trades_dir.glob('trades_*.jsonl'))

        if not log_files:
            return 0.0

        import os
        current_mtime = max(os.path.getmtime(str(f)) for f in log_files)
        if _pnl_mtime_cache['mtime'] == current_mtime:
            return _pnl_mtime_cache['value']

        # Recompute from scratch
        total_pnl = 0.0
        for p in log_files:
            for line in p.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                    # All 3 record types: exit, settle, exit_correction
                    if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
                        total_pnl += float(t['pnl'])
                    elif t.get('action') == 'exit_correction' and t.get('pnl_correction') is not None:
                        total_pnl += float(t['pnl_correction'])
                except Exception:
                    pass

        result = round(total_pnl, 2)
        _pnl_mtime_cache['mtime'] = current_mtime
        _pnl_mtime_cache['value'] = result
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[Logger] compute_closed_pnl_from_logs() failed: {e}')
        return 0.0


def get_daily_summary():
    """Return a summary of today's trading activity."""
    log_path = _today_log_path()  # already uses TRADES_DIR via _today_log_path()
    if not os.path.exists(log_path):
        return {'trades': 0, 'total_exposure': 0.0}

    trades = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                trades.append(json.loads(line))
            except Exception:
                pass

    buys = [t for t in trades if t.get('action') not in ('exit', 'settle')]
    return {
        'date': date.today().isoformat(),
        'trades': len(buys),
        'total_exposure': sum(t.get('size_dollars', 0) for t in buys),
        'markets': list(dict.fromkeys(t['ticker'] for t in buys)),  # deduplicated, order-preserving
        'exits_today': len(trades) - len(buys),  # informational — count of exit/settle records
    }
