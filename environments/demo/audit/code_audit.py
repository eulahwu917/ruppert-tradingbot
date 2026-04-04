"""
code_audit.py — Static codebase audit for anti-patterns.

Checks for:
- Hardcoded dollar amounts that should come from capital.py
- Duplicate threshold definitions
- Single-source-of-truth violations
- Dead code / stale references
- Security issues (secrets in code, LIVE mode safety)

Run after every dev cycle. QA owns this.
Usage: python code_audit.py
Exit code 0 = clean, 1 = issues found
"""

import re
import sys
from pathlib import Path

AUDIT_DIR = Path(__file__).parent
ROOT = AUDIT_DIR.parent   # audit/ -> demo/
PYTHON_FILES = [f for f in ROOT.glob("*.py") if f.name not in (
    "code_audit.py", "config_audit.py", "data_integrity_check.py"
)]
BOT_FILES = list((ROOT / "bot").glob("*.py"))
AUDIT_FILES = list(AUDIT_DIR.glob("*.py"))
ALL_FILES = PYTHON_FILES + BOT_FILES + AUDIT_FILES

issues = []
warnings = []


def check_hardcoded_capital():
    """Detect hardcoded dollar amounts that should use capital.py."""
    BAD_PATTERNS = [
        (r'\b400\.0\b', "$400.0 fallback — use capital.get_capital()"),
        (r'\b400\.00\b', "$400.00 hardcode — use capital.get_capital()"),
        (r'STARTING_CAPITAL\s*=\s*\d', "STARTING_CAPITAL hardcoded — use capital.get_capital()"),
    ]
    SKIP_FILES = {"capital.py", "demo_deposits.jsonl"}
    for f in ALL_FILES:
        if f.name in SKIP_FILES:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pattern, msg in BAD_PATTERNS:
            for match in re.finditer(pattern, text):
                line_num = text[:match.start()].count("\n") + 1
                line = text.splitlines()[line_num - 1].strip()
                if line.startswith("#"):
                    continue
                issues.append(f"{f.name}:{line_num} — {msg}\n  > {line}")


def check_duplicate_thresholds():
    """Detect MIN_EDGE or MIN_CONFIDENCE defined outside strategy.py and config.py."""
    ALLOWED = {"strategy.py", "config.py", "code_audit.py"}
    for f in ALL_FILES:
        if f.name in ALLOWED:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pattern in [r'^MIN_EDGE\s*=', r'^MIN_CONFIDENCE\s*=']:
            for match in re.finditer(pattern, text, re.MULTILINE):
                line_num = text[:match.start()].count("\n") + 1
                line = text.splitlines()[line_num - 1].strip()
                if not line.startswith("#"):
                    warnings.append(f"{f.name}:{line_num} — Duplicate threshold definition (should centralise in strategy.py/config.py)\n  > {line}")


def check_sot_violations():
    """Detect files not using capital.py for financial calculations."""
    PATTERNS = [
        (r'get_computed_capital\(\)', "Still using get_computed_capital() — migrate to capital.get_capital()"),
        (r'\*\s*0\.70\b', "Multiplying by 0.70 for BP — use capital.get_buying_power()"),
        (r'\*\s*DAILY_CAP_RATIO\b', "Using DAILY_CAP_RATIO for BP — use capital.get_buying_power()"),
    ]
    SKIP = {"capital.py", "logger.py", "code_audit.py"}
    for f in ALL_FILES:
        if f.name in SKIP:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for pattern, msg in PATTERNS:
            for match in re.finditer(pattern, text):
                line_num = text[:match.start()].count("\n") + 1
                line = text.splitlines()[line_num - 1].strip()
                if not line.startswith("#"):
                    warnings.append(f"{f.name}:{line_num} — {msg}\n  > {line}")


def check_dead_code():
    """Detect references to removed modules."""
    DEAD_REFS = [
        ("gaming_scout", "gaming scout module was removed"),
        ("execute_cpi", "execute_cpi.py was removed"),
        ("execute_trades", "execute_trades.py was removed"),
        ("close_cpi", "close_cpi.py was removed"),
        ("manual_trade", "manual trade functions were removed"),
    ]
    for f in ALL_FILES:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for ref, msg in DEAD_REFS:
            if ref in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if ref in line and not line.strip().startswith("#"):
                        warnings.append(f"{f.name}:{i} — Dead code reference: {msg}\n  > {line.strip()}")


def check_security():
    """Detect secrets hardcoded in source files."""
    SECRET_PATTERNS = [
        (r'api_key\s*=\s*["\'][a-zA-Z0-9_\-]{20,}["\']', "Possible hardcoded API key"),
        (r'password\s*=\s*["\'][^"\']{8,}["\']', "Possible hardcoded password"),
        (r'LIVE.*=.*True', "LIVE mode may be enabled — verify intentional"),
    ]
    SKIP = {"code_audit.py", "kalshi_client.py"}
    for f in ALL_FILES:
        if f.name in SKIP:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        # Strip docstrings so patterns inside triple-quoted strings don't trigger
        code_text = re.sub(r'"""[\s\S]*?"""', '', text)
        code_text = re.sub(r"'''[\s\S]*?'''", '', code_text)
        for pattern, msg in SECRET_PATTERNS:
            for match in re.finditer(pattern, code_text, re.IGNORECASE):
                line_num = code_text[:match.start()].count("\n") + 1
                line = code_text.splitlines()[line_num - 1].strip()
                if not line.startswith("#"):
                    issues.append(f"{f.name}:{line_num} — SECURITY: {msg}\n  > {line}")


def check_live_safety():
    """Confirm LIVE mode is off."""
    config_file = ROOT / "config.py"
    if config_file.exists():
        text = config_file.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if "DEMO_MODE" in line and "False" in line and not line.strip().startswith("#"):
                issues.append(f"config.py:{i} — LIVE SAFETY: DEMO_MODE is False — LIVE trading enabled!\n  > {line.strip()}")


def main():
    print("=== Ruppert Code Audit ===\n")

    check_hardcoded_capital()
    check_duplicate_thresholds()
    check_sot_violations()
    check_dead_code()
    check_security()
    check_live_safety()

    if issues:
        print(f"❌ ISSUES ({len(issues)} — must fix):")
        for issue in issues:
            print(f"  {issue}")
        print()

    if warnings:
        print(f"⚠️  WARNINGS ({len(warnings)} — review):")
        for w in warnings:
            print(f"  {w}")
        print()

    if not issues and not warnings:
        print("✅ All checks passed — codebase clean")
        return 0

    if issues:
        print(f"RESULT: FAIL ({len(issues)} issues, {len(warnings)} warnings)")
        return 1

    print(f"RESULT: PASS WITH WARNINGS ({len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
