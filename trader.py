"""
trader.py — Backward-compatible shim.
Forwards all imports to agents/trader/trader.py (Phase 3 location).
"""
from agents.trader.trader import *  # noqa: F401, F403
from agents.trader.trader import Trader, contracts_from_size
