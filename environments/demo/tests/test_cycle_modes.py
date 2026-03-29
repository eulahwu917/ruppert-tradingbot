"""Tests for ruppert_cycle.py module structure and mode dispatch."""
import importlib
import importlib.util
import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MODES = ['check', 'econ_prescan', 'weather_only', 'crypto_only', 'report']
FALLTHROUGH_MODES = {'full', 'smart'}


def _import_cycle():
    """Import ruppert_cycle without executing the cycle."""
    # This should now be safe — no side effects at module level
    spec = importlib.util.spec_from_file_location(
        'ruppert_cycle', REPO_ROOT / 'ruppert_cycle.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Test 1: run_cycle exists and is callable
def test_run_cycle_exists():
    mod = _import_cycle()
    assert hasattr(mod, 'run_cycle'), "ruppert_cycle.py must export run_cycle()"
    assert callable(mod.run_cycle)


# Test 2: Each required mode has a dedicated handler function
def test_mode_handler_functions_exist():
    mod = _import_cycle()
    expected = {
        'check': 'run_check_mode',
        'econ_prescan': 'run_econ_prescan_mode',
        'weather_only': 'run_weather_only_mode',
        'crypto_only': 'run_crypto_only_mode',
        'report': 'run_report_mode',
    }
    missing = []
    for mode, func_name in expected.items():
        if not hasattr(mod, func_name) or not callable(getattr(mod, func_name)):
            missing.append(f"{mode} -> {func_name}")
    assert missing == [], f"Missing mode handler functions: {missing}"


# Test 3: run_full_mode exists (covers full + smart)
def test_full_mode_handler_exists():
    mod = _import_cycle()
    assert hasattr(mod, 'run_full_mode'), "ruppert_cycle.py must export run_full_mode()"
    assert callable(mod.run_full_mode)


# Test 4: run_cycle dispatches to correct handler (check source for mode strings)
def test_run_cycle_dispatches_all_modes():
    """Verify run_cycle source contains dispatch for all required modes."""
    mod = _import_cycle()
    source = inspect.getsource(mod.run_cycle)
    for mode in REQUIRED_MODES + list(FALLTHROUGH_MODES):
        assert f"'{mode}'" in source, (
            f"run_cycle() does not reference mode '{mode}'"
        )


# Test 5: No side effects on import (module-level code doesn't call KalshiClient)
def test_no_side_effects_on_import():
    """Importing ruppert_cycle should not instantiate KalshiClient or call APIs."""
    source = (REPO_ROOT / 'ruppert_cycle.py').read_text(encoding='utf-8')
    lines = source.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip lines inside function/class bodies (indented) and comments
        if stripped.startswith('#') or stripped.startswith('def ') or stripped.startswith('class '):
            continue
        if not line.startswith(' ') and not line.startswith('\t'):
            # Top-level line
            assert 'KalshiClient()' not in stripped, (
                f"Line {i}: KalshiClient() called at module level"
            )


# Test 6: Docstring modes match handler functions
def test_docstring_modes_match_handlers():
    """Modes in module docstring must match mode handler functions."""
    source = (REPO_ROOT / 'ruppert_cycle.py').read_text(encoding='utf-8')
    docstring_match = re.search(r'"""(.*?)"""', source, re.DOTALL)
    assert docstring_match, "Could not find module docstring"
    docstring = docstring_match.group(1)

    doc_modes = set()
    for line in docstring.splitlines():
        m = re.match(r'\s+(\w+)\s+\u2014', line)
        if m:
            doc_modes.add(m.group(1))

    # Every documented mode should have a handler or be in run_cycle dispatch
    mod = _import_cycle()
    run_cycle_source = inspect.getsource(mod.run_cycle)
    for mode in doc_modes:
        assert f"'{mode}'" in run_cycle_source, (
            f"Mode '{mode}' documented but not in run_cycle dispatch"
        )
