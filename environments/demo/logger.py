"""
logger.py — Backward-compatible shim.
Forwards all imports to agents/data_scientist/logger.py (Phase 3 location).
"""
from agents.ruppert.data_scientist.logger import *  # noqa: F401, F403
from agents.ruppert.data_scientist.logger import (
    log_trade, log_opportunity, log_activity, get_daily_exposure,
    normalize_entry_price, acquire_exit_lock, release_exit_lock,
    classify_module, send_telegram,
    get_daily_summary, rotate_logs, build_trade_entry,
)
