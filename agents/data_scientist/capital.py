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
from pathlib import Path

# Ensure project root is on sys.path when running standalone
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

_LOGS_DIR = _PROJECT_ROOT / "logs"
_DEPOSITS_FILE = _LOGS_DIR / "demo_deposits.jsonl"
_PNL_CACHE_FILE = _LOGS_DIR / "pnl_cache.json"
_DEFAULT_CAPITAL = 10000.0  # Fresh start 2026-03-26


def get_capital() -> float:
    """
    Return total available capital.
    DEMO: sum of demo_deposits.jsonl + realized P&L from pnl_cache.json
    LIVE: Kalshi API balance (falls back to deposits if API unavailable)
    """
    try:
        # Try Kalshi API first (LIVE mode)
        import config
        if getattr(config, 'DRY_RUN', True) is False:
            try:
                from agents.data_analyst.kalshi_client import KalshiClient
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

        # Add realized P&L from pnl_cache
        closed_pnl = get_pnl().get('closed', 0.0)
        return round(total + closed_pnl, 2)

    except Exception as e:
        logger.warning(f"[Capital] get_capital() failed: {e} — using ${_DEFAULT_CAPITAL:.0f} default")
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
        from agents.data_scientist.logger import get_daily_exposure as _get_daily_exposure
        return _get_daily_exposure()
    except Exception as e:
        logger.warning(f"[Capital] get_daily_exposure() failed: {e}")
        return 0.0


def get_pnl() -> dict:
    """
    Return P&L summary: {'closed': float, 'open': float, 'total': float}
    Reads from pnl_cache.json (written by dashboard).
    """
    result = {'closed': 0.0, 'open': 0.0, 'total': 0.0}
    try:
        if _PNL_CACHE_FILE.exists():
            data = json.loads(_PNL_CACHE_FILE.read_text(encoding='utf-8'))
            # P3-2 fix: wrap individual float() casts in try/except to handle
            # corrupted or non-numeric values in pnl_cache.json gracefully.
            try:
                result['closed'] = round(float(data.get('closed_pnl', 0.0)), 2)
            except (TypeError, ValueError) as _e:
                logger.warning(f"[Capital] get_pnl(): invalid closed_pnl value — {_e}")
            try:
                result['open'] = round(float(data.get('open_pnl', 0.0)), 2)
            except (TypeError, ValueError) as _e:
                logger.warning(f"[Capital] get_pnl(): invalid open_pnl value — {_e}")
            result['total'] = round(result['closed'] + result['open'], 2)
    except Exception as e:
        logger.warning(f"[Capital] get_pnl() failed: {e}")
    return result
