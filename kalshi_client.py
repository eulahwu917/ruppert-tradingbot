"""
kalshi_client.py — Backward-compatible shim.
Forwards all imports to agents/data_analyst/kalshi_client.py (Phase 3 location).
"""
from agents.ruppert.data_analyst.kalshi_client import *  # noqa: F401, F403
from agents.ruppert.data_analyst.kalshi_client import KalshiClient, KalshiMarket
