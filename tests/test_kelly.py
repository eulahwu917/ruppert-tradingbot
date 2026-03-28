"""Tests for Kelly / position-sizing logic in bot.strategy."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.strategist.strategy import calculate_position_size


def test_kelly_win_prob_1_0():
    """win_prob=1.0 must return size > 0 (clamped to 0.999, not crash)."""
    size = calculate_position_size(edge=0.20, win_prob=1.0, capital=1000.0)
    assert size > 0, f"Expected size > 0 for win_prob=1.0, got {size}"


def test_kelly_win_prob_0_999():
    """win_prob=0.999 must return size > 0."""
    size = calculate_position_size(edge=0.20, win_prob=0.999, capital=1000.0)
    assert size > 0, f"Expected size > 0 for win_prob=0.999, got {size}"


def test_kelly_negative_edge():
    """Negative edge must return 0."""
    size = calculate_position_size(edge=-0.10, win_prob=0.60, capital=1000.0)
    assert size == 0.0, f"Expected 0 for negative edge, got {size}"


def test_kelly_zero_edge():
    """Zero edge must return 0."""
    size = calculate_position_size(edge=0.0, win_prob=0.60, capital=1000.0)
    assert size == 0.0, f"Expected 0 for zero edge, got {size}"


def test_kelly_zero_capital():
    """Zero capital must return 0."""
    size = calculate_position_size(edge=0.20, win_prob=0.60, capital=0.0)
    assert size == 0.0, f"Expected 0 for zero capital, got {size}"
