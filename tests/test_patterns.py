"""
Static analysis tests — no API calls, just text scanning of .py files.
Ensures architectural invariants hold across the codebase.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {'tests', 'archive', '__pycache__', '.git', 'node_modules', 'venv', '.venv'}


def _repo_py_files():
    """Yield all .py files under repo root, skipping SKIP_DIRS."""
    for entry in REPO_ROOT.rglob('*.py'):
        # Skip if any parent directory is in SKIP_DIRS
        if any(part in SKIP_DIRS for part in entry.relative_to(REPO_ROOT).parts[:-1]):
            continue
        yield entry


# ── Test 1: No direct Kalshi API calls outside allowed modules ───────────────

ALLOWED_KALSHI_API_FILES = {'kalshi_client.py', 'kalshi_market_search.py', 'check_markets.py', 'check_austin.py', 'backtest_weather.py', 'qa_health_check.py', 'security_audit.py', 'api.py'}


def test_no_direct_kalshi_api_calls():
    """No file outside the allowed list should contain the raw Kalshi API host."""
    violations = []
    for py_file in _repo_py_files():
        if py_file.name in ALLOWED_KALSHI_API_FILES:
            continue
        text = py_file.read_text(encoding='utf-8', errors='replace')
        if 'api.elections.kalshi.com' in text:
            violations.append(py_file.relative_to(REPO_ROOT).as_posix())

    assert violations == [], (
        f"Direct Kalshi API URL found outside allowed files: {violations}"
    )


# ── Test 2: All scanners route through strategy ─────────────────────────────

def test_all_scanners_route_through_strategy():
    """Any file that calls log_trade or place_order must also call should_enter."""
    gate_required_files = ['main.py', 'ruppert_cycle.py']
    violations = []

    for fname in gate_required_files:
        fpath = REPO_ROOT / fname
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding='utf-8', errors='replace')
        has_trade_action = 'log_trade' in text or 'place_order' in text
        has_strategy_gate = 'should_enter' in text
        if has_trade_action and not has_strategy_gate:
            violations.append(fname)

    assert violations == [], (
        f"Files place trades without strategy gate (should_enter): {violations}"
    )


# ── Test 3: All modes handled in ruppert_cycle.py ───────────────────────────

REQUIRED_MODES = ['check', 'econ_prescan', 'weather_only', 'crypto_only']


def test_all_modes_handled():
    """ruppert_cycle.py must contain an explicit branch for each required mode."""
    cycle_path = REPO_ROOT / 'ruppert_cycle.py'
    text = cycle_path.read_text(encoding='utf-8', errors='replace')

    missing = [mode for mode in REQUIRED_MODES if mode not in text]
    assert missing == [], (
        f"ruppert_cycle.py is missing handler for mode(s): {missing}"
    )
