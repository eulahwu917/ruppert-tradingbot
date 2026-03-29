"""Tests that strategy routing uses should_enter and avoids hardcoded sizing."""
import pathlib


def _read(name: str) -> str:
    return (pathlib.Path(__file__).resolve().parent.parent / name).read_text(encoding='utf-8')


# ── main.py ──────────────────────────────────────────────────────────────────

def test_main_py_uses_should_enter():
    """main.py must call should_enter() for strategy gating."""
    source = _read('main.py')
    assert 'should_enter' in source, "main.py does not reference should_enter"


def test_main_py_uses_log_trade():
    """main.py must call log_trade() to record executions."""
    source = _read('main.py')
    assert 'log_trade' in source, "main.py does not reference log_trade"


# ── ruppert_cycle.py ─────────────────────────────────────────────────────────

def test_ruppert_cycle_uses_should_enter():
    """ruppert_cycle.py must call should_enter() for strategy gating."""
    source = _read('ruppert_cycle.py')
    assert 'should_enter' in source, "ruppert_cycle.py does not reference should_enter"


# ── No hardcoded position sizing ─────────────────────────────────────────────

def test_no_hardcoded_position_sizing():
    """Neither main.py nor ruppert_cycle.py should contain hardcoded 'size = 25'."""
    for name in ('main.py', 'ruppert_cycle.py'):
        source = _read(name)
        assert 'size = 25' not in source, f"{name} contains hardcoded 'size = 25'"
        assert 'size = min(25' not in source, f"{name} contains hardcoded 'size = min(25'"
