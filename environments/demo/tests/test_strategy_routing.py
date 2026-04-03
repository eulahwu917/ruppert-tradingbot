"""Tests that strategy routing uses should_enter and avoids hardcoded sizing."""
import pathlib

# environments/demo/ root (for ruppert_cycle.py)
_DEMO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# workspace root (for agents/ruppert/trader/main.py)
_WORKSPACE_ROOT = _DEMO_ROOT.parent.parent


def _read(name: str) -> str:
    """Read a file from environments/demo/."""
    return (_DEMO_ROOT / name).read_text(encoding='utf-8')


def _read_trader(name: str) -> str:
    """Read a file from agents/ruppert/trader/ (main.py relocated here after refactor)."""
    return (_WORKSPACE_ROOT / 'agents' / 'ruppert' / 'trader' / name).read_text(encoding='utf-8')


# ── main.py (agents/ruppert/trader/main.py) ──────────────────────────────────

def test_main_py_uses_should_enter():
    """main.py must call should_enter() for strategy gating."""
    # main.py was moved from environments/demo/ to agents/ruppert/trader/ during refactor
    source = _read_trader('main.py')
    assert 'should_enter' in source, "agents/ruppert/trader/main.py does not reference should_enter"


def test_main_py_uses_log_trade():
    """main.py must call log_trade() to record executions."""
    # main.py was moved from environments/demo/ to agents/ruppert/trader/ during refactor
    source = _read_trader('main.py')
    assert 'log_trade' in source, "agents/ruppert/trader/main.py does not reference log_trade"


# ── ruppert_cycle.py ─────────────────────────────────────────────────────────

def test_ruppert_cycle_uses_should_enter():
    """ruppert_cycle.py must call should_enter() for strategy gating."""
    source = _read('ruppert_cycle.py')
    assert 'should_enter' in source, "ruppert_cycle.py does not reference should_enter"


# ── No hardcoded position sizing ─────────────────────────────────────────────

def test_no_hardcoded_position_sizing():
    """Neither main.py nor ruppert_cycle.py should contain hardcoded 'size = 25'."""
    # main.py lives in agents/ruppert/trader/ after refactor; ruppert_cycle.py stays in demo/
    sources = {
        'agents/ruppert/trader/main.py': _read_trader('main.py'),
        'ruppert_cycle.py':              _read('ruppert_cycle.py'),
    }
    for label, source in sources.items():
        assert 'size = 25' not in source,     f"{label} contains hardcoded 'size = 25'"
        assert 'size = min(25' not in source, f"{label} contains hardcoded 'size = min(25'"
