"""
capital.py — Backward-compatible shim.
Forwards all imports to agents/data_scientist/capital.py (Phase 3 location).
"""
from agents.ruppert.data_scientist.capital import *  # noqa: F401, F403
from agents.ruppert.data_scientist.capital import (
    get_capital, get_buying_power, get_daily_exposure, get_pnl,
)
