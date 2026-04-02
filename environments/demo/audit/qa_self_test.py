"""
qa_self_test.py — QA self-test script (no API calls).

Run monthly. QA owns this.
Usage: python qa_self_test.py
Exit code 0 = PASS, 1 = FAIL
"""

import sys
import os
from pathlib import Path

if __name__ != '__main__':
    raise ImportError("qa_self_test.py is a standalone script — do not import it")

ROOT = Path(__file__).parent
_DEMO_DIR       = ROOT.parent
_WORKSPACE_ROOT = _DEMO_DIR.parent.parent  # audit -> demo -> environments -> workspace
for _p in (_WORKSPACE_ROOT, _DEMO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

results = []


def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# ── 1. Import key modules without API calls ──────────────────────────────────
print("\n=== Module Imports ===")

try:
    import config
    check("import config", True)
except Exception as e:
    check("import config", False, str(e))

try:
    from agents.ruppert.strategist import strategy
    check("import agents.ruppert.strategist.strategy", True)
except Exception as e:
    check("import agents.ruppert.strategist.strategy", False, str(e))

try:
    from agents.ruppert.data_scientist.capital import get_capital
    check("import capital", True)
except Exception as e:
    check("import capital", False, str(e))

try:
    from agents.ruppert.data_scientist import logger
    check("import logger", True)
except Exception as e:
    check("import logger", False, str(e))

try:
    from agents.ruppert.strategist import edge_detector
    check("import edge_detector", True)
except Exception as e:
    check("import edge_detector", False, str(e))

# ── 2. Config value range checks ─────────────────────────────────────────────
print("\n=== Config Range Checks ===")

try:
    min_conf = config.MIN_CONFIDENCE
    if isinstance(min_conf, dict):
        for module, val in min_conf.items():
            ok = 0.1 <= val <= 1.0
            check(f"MIN_CONFIDENCE[{module}] in [0.1, 1.0]", ok, f"{val}")
    else:
        ok = 0.1 <= min_conf <= 1.0
        check("MIN_CONFIDENCE in [0.1, 1.0]", ok, f"{min_conf}")
except Exception as e:
    check("MIN_CONFIDENCE range", False, str(e))

try:
    kelly = strategy.KELLY_FRACTION
    ok = 0.1 <= kelly <= 0.5
    check("KELLY_FRACTION in [0.1, 0.5]", ok, f"{kelly}")
except Exception as e:
    check("KELLY_FRACTION range", False, str(e))

# ── 3. Required files exist ──────────────────────────────────────────────────
print("\n=== Required Files ===")

secrets_config = Path(r"C:\Users\David Wu\.openclaw\workspace\secrets\kalshi_config.json")
check("secrets/kalshi_config.json exists", secrets_config.exists())

logs_dir = ROOT.parent / "logs"
check("logs/ directory exists", logs_dir.exists())


# ── 4. Deprecated/deleted files must NOT exist ───────────────────────────────
# NOTE: These are intentional existence guards — checking deleted files have NOT come back.
# code_audit.py may flag these as "dead code references" — that is a false positive.
# Do NOT remove these entries; they are safety checks, not stale references.
print("\n=== Deprecated Files (should not exist) ===")

DEPRECATED = [
    "test_modules.py",
    "gaming_scout.py",
    "execute_cpi.py",
    "execute_trades.py",
    "close_cpi.py",
]

for fname in DEPRECATED:
    gone = not (ROOT / fname).exists()
    check(f"{fname} removed", gone, "still present!" if not gone else "")

# ── 5. Summary ───────────────────────────────────────────────────────────────
print("\n=== SUMMARY ===")
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

if failed == 0:
    print(f"PASS — {passed}/{total} checks passed")
    sys.exit(0)
else:
    print(f"FAIL — {passed}/{total} passed, {failed} failed")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name}" + (f" — {detail}" if detail else ""))
    sys.exit(1)



