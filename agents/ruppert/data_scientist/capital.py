"""
capital.py — Single source of truth for all financial calculations.

Every module that needs capital, buying power, exposure, or P&L
imports from here. Never hardcode $400 or $10,000 anywhere else.

Usage:
    from capital import get_capital, get_buying_power, get_daily_exposure, get_pnl
"""

import os
import json
import logging
import sys
import time
from pathlib import Path

# Resolve workspace root and add to path for env_config
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from agents.ruppert.env_config import get_paths as _get_paths  # noqa: E402

logger = logging.getLogger(__name__)

_env_paths = _get_paths()
_LOGS_DIR = _env_paths['logs']
_DEPOSITS_FILE = _LOGS_DIR / "demo_deposits.jsonl"
_DEFAULT_CAPITAL = 10000.0  # Fresh start 2026-03-26
_CAPITAL_FALLBACK_ALERT_FILE = _LOGS_DIR / 'capital_fallback_last_alert.json'
_CAPITAL_FALLBACK_ALERT_COOLDOWN_SECS = 4 * 3600  # 4 hours


def get_capital() -> float:
    """
    Return total available capital.
    DEMO: sum of demo_deposits.jsonl + realized P&L from compute_closed_pnl_from_logs()
    LIVE: Kalshi API balance (falls back to deposits if API unavailable)
    """
    try:
        # Try Kalshi API first (LIVE mode)
        import importlib.util as _ilu
        from agents.ruppert.env_config import get_env_root as _get_env_root
        _cfg_path = _get_env_root() / 'config.py'
        if not _cfg_path.exists():
            return _DEFAULT_CAPITAL
        _spec = _ilu.spec_from_file_location('config', _cfg_path)
        config = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(config)
        if getattr(config, 'DRY_RUN', True) is False:
            try:
                from agents.ruppert.data_analyst.kalshi_client import KalshiClient
                return KalshiClient().get_balance()
            except Exception:
                pass

        # DEMO mode: sum deposits
        total = 0.0
        if _DEPOSITS_FILE.exists():
            for line in _DEPOSITS_FILE.read_text(encoding='utf-8').strip().splitlines():
                try:
                    total += json.loads(line).get('amount', 0)
                except Exception:
                    continue

        if total <= 0:
            logger.warning(f"[Capital] deposits file empty or missing — using ${_DEFAULT_CAPITAL:.0f} default")
            return _DEFAULT_CAPITAL

        # Add realized P&L — read LIVE from trade logs (same path as dashboard display)
        # Do NOT use pnl_cache.json here: it lags behind trade logs until synthesizer runs,
        # causing Account Value to diverge from the dashboard Closed P&L panel.
        from agents.ruppert.data_scientist.logger import compute_closed_pnl_from_logs
        closed_pnl = compute_closed_pnl_from_logs()
        return round(total + closed_pnl, 2)

    except Exception as e:
        logger.warning(f"[Capital] get_capital() failed: {e} — using ${_DEFAULT_CAPITAL:.0f} default")
        try:
            _should_alert = True
            if _CAPITAL_FALLBACK_ALERT_FILE.exists():
                _last = json.loads(_CAPITAL_FALLBACK_ALERT_FILE.read_text(encoding='utf-8'))
                _elapsed = time.time() - _last.get('ts', 0)
                if _elapsed < _CAPITAL_FALLBACK_ALERT_COOLDOWN_SECS:
                    _should_alert = False
            if _should_alert:
                from agents.ruppert.data_scientist.logger import send_telegram as _send_tg, log_activity as _log_act
                _err_str = str(e)[:500]
                _send_tg(f'🚨 CAPITAL ERROR: get_capital() failed — using ${_DEFAULT_CAPITAL:.0f} fallback. All sizing may be wrong. Reason: {_err_str}')
                _log_act(f'[Capital] FALLBACK ALERT: get_capital() failed — using ${_DEFAULT_CAPITAL:.0f} default. Reason: {_err_str}')
                _CAPITAL_FALLBACK_ALERT_FILE.write_text(
                    json.dumps({'ts': time.time(), 'reason': _err_str}), encoding='utf-8'
                )
        except Exception as _alert_err:
            logger.warning(f'[Capital] Could not send fallback alert: {_alert_err}')
        return _DEFAULT_CAPITAL


def get_buying_power(deployed: float = None) -> float:
    """
    Return current buying power = capital - open deployed.
    BP is NOT capped by daily limit — that's an internal risk gate, not displayed BP.

    Args:
        deployed: Open deployed dollars. If None, reads from get_daily_exposure().
    """
    capital = get_capital()
    if deployed is None:
        deployed = get_daily_exposure()
    return round(max(0.0, capital - deployed), 2)


def get_daily_exposure() -> float:
    """
    Return total dollars deployed today across all open positions.
    Reads from logger.get_daily_exposure() — single implementation.
    """
    try:
        from agents.ruppert.data_scientist.logger import get_daily_exposure as _get_daily_exposure
        return _get_daily_exposure()
    except Exception as e:
        logger.warning(f"[Capital] get_daily_exposure() failed: {e}")
        return 0.0


def get_pnl() -> dict:
    """
    Return P&L summary: {'closed': float, 'open': float, 'total': float}
    Closed P&L computed live from trade logs via compute_closed_pnl_from_logs().
    No disk cache — single source of truth.
    """
    result = {'closed': 0.0, 'open': 0.0, 'total': 0.0}
    try:
        from agents.ruppert.data_scientist.logger import compute_closed_pnl_from_logs
        result['closed'] = compute_closed_pnl_from_logs()
        result['total'] = result['closed'] + result['open']
    except Exception as e:
        logger.warning(f"[Capital] get_pnl() failed: {e}")
    return result
