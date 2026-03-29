"""
position_tracker.py — Backward-compatible shim.
Forwards all imports to agents/trader/position_tracker.py (Phase 3 location).
"""
from agents.ruppert.trader.position_tracker import *  # noqa: F401, F403
from agents.ruppert.trader.position_tracker import (
    add_position, remove_position, get_tracked, is_tracked,
    check_exits, execute_exit, recovery_poll_positions,
)
