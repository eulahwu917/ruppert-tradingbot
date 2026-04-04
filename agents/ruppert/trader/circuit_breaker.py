"""
circuit_breaker.py — Unified circuit breaker state management.

Single source of truth for all module-level and global circuit breaker state.
State file: environments/demo/logs/circuit_breaker_state.json

Replaces:
  - logs/crypto_15m_circuit_breaker.json (retired)
  - logs/crypto_1h_circuit_breaker.json (retired)
  - check_loss_circuit_breaker() gross-loss logic in strategy.py

Module keys:
  crypto_dir_15m_btc, crypto_dir_15m_eth, crypto_dir_15m_sol,
  crypto_dir_15m_xrp, crypto_dir_15m_doge  — per-asset 15m directional
  crypto_band_daily_btc, crypto_band_daily_eth                — daily band
  crypto_threshold_daily_btc, crypto_threshold_daily_eth      — daily threshold
  global                                                       — net loss CB
"""

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import portalocker
import pytz

logger = logging.getLogger(__name__)

# ── Path resolution ────────────────────────────────────────────────────────────
_AGENTS_ROOT    = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent                  # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import config

from agents.ruppert.env_config import get_paths as _get_paths

_PDT = pytz.timezone('America/Los_Angeles')

# ── Default per-module state template ────────────────────────────────────────

def _default_module_state(today_str: str) -> dict:
    return {
        "consecutive_losses": 0,
        "last_window_ts": "",
        "last_window_result": "win",
        "date": today_str,
    }


def _default_global_state(today_str: str) -> dict:
    return {
        "net_loss_today": 0.0,
        "tripped": False,
        "date": today_str,
    }


_ALL_MODULE_KEYS = [
    "crypto_dir_15m_btc",
    "crypto_dir_15m_eth",
    "crypto_dir_15m_sol",
    "crypto_dir_15m_xrp",
    "crypto_dir_15m_doge",
    "crypto_band_daily_btc",
    "crypto_band_daily_eth",
    "crypto_threshold_daily_btc",
    "crypto_threshold_daily_eth",
]


def _state_path() -> Path:
    return _get_paths()['logs'] / 'circuit_breaker_state.json'


def _today_pdt() -> str:
    return datetime.now(_PDT).strftime('%Y-%m-%d')


# ── Atomic read/write helpers ─────────────────────────────────────────────────

def _read_full_state() -> dict:
    """Read the full state file. Returns empty dict on missing/corrupt."""
    path = _state_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_full_state(state: dict) -> None:
    """Atomically write the full state dict to disk."""
    path = _state_path()
    tmp  = str(path) + '.tmp'
    os.makedirs(str(path.parent), exist_ok=True)
    try:
        Path(tmp).unlink(missing_ok=True)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, str(path))
    except Exception as e:
        logger.error('[circuit_breaker] State file write failed: %s', e)
        raise


def _rw_locked(path: Path, fn) -> None:
    """Open the state file under an exclusive lock, call fn(state) to modify, then write back.

    Uses 'r+' mode so existing content is preserved; falls back to 'w+' on cold start
    (FileNotFoundError — file does not exist yet).  fn(state) receives the parsed dict
    and should mutate it in place (return value is ignored).
    """
    os.makedirs(str(path.parent), exist_ok=True)
    try:
        fh = open(path, 'r+', encoding='utf-8')
    except FileNotFoundError:
        fh = open(path, 'w+', encoding='utf-8')

    with fh:
        portalocker.lock(fh, portalocker.LOCK_EX)
        try:
            content = fh.read()
            try:
                state = json.loads(content) if content.strip() else {}
            except json.JSONDecodeError:
                state = {}

            fn(state)

            fh.seek(0)
            fh.truncate()
            json.dump(state, fh, indent=2)
        finally:
            portalocker.unlock(fh)


# ── Public API ────────────────────────────────────────────────────────────────

def get_module_state(module: str) -> dict:
    """
    Read state for a specific module key.
    Auto-resets on new day (date mismatch → returns fresh default and writes it).

    Returns dict with keys: consecutive_losses, last_window_ts,
                            last_window_result, date
    """
    today = _today_pdt()
    state = _read_full_state()
    mod   = state.get(module, {})

    if not mod or mod.get('date') != today:
        # New day or missing — reset
        fresh = _default_module_state(today)
        state[module] = fresh
        try:
            _write_full_state(state)
        except Exception:
            pass
        return fresh

    return dict(mod)


def set_module_state(module: str, new_mod_state: dict) -> None:
    """
    Write state for a specific module key (atomic).
    Merges into the full state file.
    """
    state = _read_full_state()
    state[module] = new_mod_state
    _write_full_state(state)


def increment_consecutive_losses(module: str, window_ts: str) -> None:
    """Increment consecutive loss counter and record window_ts + result='loss'."""
    today = _today_pdt()
    path  = _state_path()
    _new_count = [0]  # mutable cell so inner fn can report final count

    def _mutate(state):
        mod = state.get(module, {})
        if not mod or mod.get('date') != today:
            mod = _default_module_state(today)
        mod['consecutive_losses']  = mod.get('consecutive_losses', 0) + 1
        mod['last_window_ts']      = window_ts
        mod['last_window_result']  = 'loss'
        mod['date']                = today
        state[module]              = mod
        _new_count[0]              = mod['consecutive_losses']

    _rw_locked(path, _mutate)

    # Resolve CB threshold N based on module prefix
    if module.startswith('crypto_dir_15m_'):
        cb_n = getattr(config, 'CRYPTO_15M_CIRCUIT_BREAKER_N', 3)
    elif module.startswith('crypto_band_daily_') or module.startswith('crypto_threshold_daily_'):
        cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N', 5)
    else:
        cb_n = 3  # hardcoded fallback for unknown modules
    if _new_count[0] >= cb_n:
        logger.warning(
            '[circuit_breaker] TRIP: %s consecutive_losses=%d hit threshold=%d (window=%s)',
            module, _new_count[0], cb_n, window_ts,
        )
    else:
        logger.info(
            '[circuit_breaker] %s: consecutive_losses=%d (window=%s)',
            module, _new_count[0], window_ts,
        )


def reset_consecutive_losses(module: str, window_ts: str) -> None:
    """Reset consecutive loss counter to 0 and record window_ts + result='win'."""
    today = _today_pdt()
    path  = _state_path()

    def _mutate(state):
        mod = state.get(module, {})
        if not mod or mod.get('date') != today:
            mod = _default_module_state(today)
        mod['consecutive_losses']  = 0
        mod['last_window_ts']      = window_ts
        mod['last_window_result']  = 'win'
        mod['date']                = today
        state[module]              = mod

    _rw_locked(path, _mutate)

    logger.info('[circuit_breaker] %s: reset to 0 (window=%s)', module, window_ts)


def get_consecutive_losses(module: str) -> int:
    """Convenience: return current consecutive loss count for a module."""
    return int(get_module_state(module).get('consecutive_losses', 0))


# ── Global net-loss CB ────────────────────────────────────────────────────────

def check_global_net_loss(capital: float) -> dict:
    """
    Compute today's net P&L from the trade log and check against threshold.

    Net P&L = sum of ALL pnl fields on 'exit' and 'settle' records (wins + losses).
    Trips if net loss exceeds LOSS_CIRCUIT_BREAKER_PCT of capital.

    Returns: {'tripped': bool, 'reason': str, 'net_loss_today': float}
    """
    if capital <= 0:
        return {
            'tripped': True,
            'reason': f'Capital is non-positive ({capital}) — trading halted until P&L is reconciled',
            'net_loss_today': 0.0,
        }

    threshold_pct     = getattr(config, 'LOSS_CIRCUIT_BREAKER_PCT', 0.05)
    threshold_dollars = capital * threshold_pct

    trade_log = _get_paths()['trades'] / f'trades_{date.today().isoformat()}.jsonl'
    if not trade_log.exists():
        return {'tripped': False, 'reason': 'no_trade_log', 'net_loss_today': 0.0}

    net_pnl = 0.0
    try:
        for line in trade_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get('action') not in ('exit', 'settle'):
                continue
            pnl = rec.get('pnl')
            if pnl is not None:
                net_pnl += float(pnl)
    except Exception as e:
        logger.error('[circuit_breaker] Failed to read trade log: %s — failing closed', e)
        return {
            'tripped': True,
            'reason': f'log_read_error (fail-closed): {e}',
            'net_loss_today': 0.0,
        }

    # net_loss_today is the magnitude of the net loss (positive number when losing)
    net_loss_today = -net_pnl if net_pnl < 0 else 0.0

    if net_loss_today > threshold_dollars:
        return {
            'tripped': True,
            'reason': (
                f'Loss circuit breaker tripped: net loss ${net_loss_today:.2f} today '
                f'exceeds {threshold_pct:.0%} of capital (${threshold_dollars:.2f})'
            ),
            'net_loss_today': round(net_loss_today, 2),
        }

    return {
        'tripped': False,
        'reason': 'within_threshold',
        'net_loss_today': round(net_loss_today, 2),
    }


def update_global_state(capital: float) -> None:
    """
    Recompute global net loss and write to the 'global' key in state file.
    """
    result = check_global_net_loss(capital)
    today  = _today_pdt()
    path   = _state_path()

    def _mutate(state):
        state['global'] = {
            'net_loss_today': result['net_loss_today'],
            'tripped':        result['tripped'],
            'date':           today,
        }

    try:
        _rw_locked(path, _mutate)
    except Exception as e:
        logger.error('[circuit_breaker] update_global_state write failed: %s', e)
