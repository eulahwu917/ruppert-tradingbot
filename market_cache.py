"""
market_cache.py — Backward-compatible shim.
Forwards all imports to agents/data_analyst/market_cache.py (Phase 3 location).
"""
from agents.ruppert.data_analyst.market_cache import *  # noqa: F401, F403
from agents.ruppert.data_analyst.market_cache import (
    update, get, get_with_staleness, purge_stale, snapshot,
    persist, load, get_market_price,
)
