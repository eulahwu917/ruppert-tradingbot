"""
bot/wallet_updater.py — Backward-compatible shim.
Forwards all imports to agents/data_analyst/wallet_updater.py (Phase 3 location).
"""
from agents.data_analyst.wallet_updater import *  # noqa: F401, F403
from agents.data_analyst.wallet_updater import update_wallet_list
