"""
bot/strategy.py — Backward-compatible shim.
Forwards all imports to agents/strategist/strategy.py (Phase 3 location).
"""
from agents.strategist.strategy import *  # noqa: F401, F403
from agents.strategist.strategy import (
    calculate_position_size, check_daily_cap, check_open_exposure,
    should_enter, should_add, should_exit, get_strategy_summary,
    check_loss_circuit_breaker, apply_market_impact_ceiling,
    kelly_fraction_for_confidence,
)
