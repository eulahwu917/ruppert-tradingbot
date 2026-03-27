"""
Phase 2 — Tests for mode handling in ruppert_cycle.py.
Verifies that each mode has a proper handler branch, calls sys.exit(0),
and that the mode list in the docstring stays in sync with actual handlers.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CYCLE_PATH = REPO_ROOT / 'ruppert_cycle.py'

REQUIRED_MODES = ['check', 'econ_prescan', 'weather_only', 'crypto_only']


def _read_cycle():
    return CYCLE_PATH.read_text(encoding='utf-8', errors='replace')


# ── Test 1: Every required mode has an explicit `if MODE == '<mode>'` branch ──

def test_all_modes_have_explicit_handler():
    """Each required mode must have an `if MODE == '<mode>':` guard."""
    text = _read_cycle()
    missing = []
    for mode in REQUIRED_MODES:
        pattern = rf"""if\s+MODE\s*==\s*['"]""" + re.escape(mode) + r"""['"]"""
        if not re.search(pattern, text):
            missing.append(mode)
    assert missing == [], (
        f"ruppert_cycle.py missing explicit `if MODE == ...` for: {missing}"
    )


# ── Test 2: Every mode handler ends with sys.exit(0) ─────────────────────────

def test_mode_handlers_call_sys_exit():
    """Each mode branch must call sys.exit(0) so it doesn't fall through."""
    text = _read_cycle()
    lines = text.splitlines()

    for mode in REQUIRED_MODES:
        # Find the line with `if MODE == '<mode>':`
        handler_line = None
        for i, line in enumerate(lines):
            if re.search(rf"""if\s+MODE\s*==\s*['"]""" + re.escape(mode) + r"""['"]""", line):
                handler_line = i
                break
        assert handler_line is not None, (
            f"Could not find handler for mode '{mode}'"
        )

        # Scan forward from the handler to the next top-level `if MODE ==` or EOF
        block = []
        for j in range(handler_line + 1, len(lines)):
            if re.search(r"""^if\s+MODE\s*==\s*['"]""", lines[j]):
                break
            block.append(lines[j])

        block_text = '\n'.join(block)
        assert 'sys.exit(0)' in block_text, (
            f"Mode '{mode}' handler does not call sys.exit(0) — "
            f"may fall through to later modes"
        )


# ── Test 3: Docstring mode list matches actual handlers ──────────────────────

def test_docstring_modes_match_handlers():
    """Modes listed in the module docstring must match actual if-MODE branches.

    'full' and 'smart' are fallthrough modes (no explicit guard) — they run
    the main body after all early-exit modes have called sys.exit(0).
    """
    text = _read_cycle()

    # Extract modes from the docstring (lines like `  full  — ...`)
    docstring_match = re.search(r'"""(.*?)"""', text, re.DOTALL)
    assert docstring_match, "Could not find module docstring in ruppert_cycle.py"
    docstring = docstring_match.group(1)

    doc_modes = set()
    for line in docstring.splitlines():
        m = re.match(r'\s+(\w+)\s+—', line)
        if m:
            doc_modes.add(m.group(1))

    # Extract modes from actual `if MODE == '...'` branches
    handler_modes = set(re.findall(r"""if\s+MODE\s*==\s*['"](\w+)['"]""", text))

    # 'full' and 'smart' are fallthrough modes — no explicit guard needed
    FALLTHROUGH_MODES = {'full', 'smart'}

    # Docstring modes that have no handler (excluding fallthrough)
    doc_only = doc_modes - handler_modes - FALLTHROUGH_MODES
    # Handler modes not documented
    handler_only = handler_modes - doc_modes

    assert doc_only == set(), (
        f"Modes in docstring but missing handler: {doc_only}"
    )
    assert handler_only == set(), (
        f"Modes with handler but missing from docstring: {handler_only}"
    )


# ── Test 4: No duplicate mode handlers ───────────────────────────────────────

def test_no_duplicate_mode_handlers():
    """Each mode should have exactly one `if MODE ==` branch."""
    text = _read_cycle()
    all_modes = re.findall(r"""if\s+MODE\s*==\s*['"](\w+)['"]""", text)
    seen = {}
    duplicates = []
    for mode in all_modes:
        seen[mode] = seen.get(mode, 0) + 1
    for mode, count in seen.items():
        if count > 1:
            duplicates.append(f"{mode} ({count}x)")
    assert duplicates == [], (
        f"Duplicate mode handlers in ruppert_cycle.py: {duplicates}"
    )
