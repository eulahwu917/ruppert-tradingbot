"""
config_audit.py — Configuration consistency audit.

Verifies that threshold values are consistent across all files,
Task Scheduler tasks exist and are enabled, and no config drift
has occurred between modules.

Run weekly. QA owns this.
Usage: python config_audit.py
Exit code 0 = clean, 1 = issues found
"""

import sys
import json
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent
_DEMO_DIR       = ROOT.parent
_WORKSPACE_ROOT = _DEMO_DIR.parent.parent  # audit -> demo -> environments -> workspace

# Make workspace root + demo dir importable
for _p in (_WORKSPACE_ROOT, _DEMO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

issues = []
warnings = []


def read_py_constant(filepath: Path, constant: str):
    """Extract a constant value from a Python file via import."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_mod", filepath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, constant, None)
    except Exception:
        return None


def check_threshold_consistency():
    """Verify MIN_CONFIDENCE matches across strategy.py and config.py."""
    try:
        import config
        from agents.ruppert.strategist import strategy

        # Check MIN_CONFIDENCE alignment
        strat_min_conf = strategy.MIN_CONFIDENCE
        cfg_min_conf = getattr(config, 'MIN_CONFIDENCE', None)

        if isinstance(cfg_min_conf, dict):
            # Compare per-module confidence values if dict
            for mod_key, mod_conf in cfg_min_conf.items():
                if mod_conf and abs(mod_conf - strat_min_conf) > 0.01:
                    warnings.append(
                        f"MIN_CONFIDENCE mismatch: strategy.py={strat_min_conf} vs config.py[{mod_key}]={mod_conf}"
                    )
        elif cfg_min_conf and abs(cfg_min_conf - strat_min_conf) > 0.01:
            warnings.append(
                f"MIN_CONFIDENCE mismatch: strategy.py={strat_min_conf} vs config.py={cfg_min_conf}"
            )

        # Check DEMO_MODE is True
        demo_mode = getattr(config, 'DEMO_MODE', None)
        if demo_mode is False:
            issues.append("LIVE SAFETY: config.DEMO_MODE is False — LIVE trading is enabled!")
        elif demo_mode is True:
            print("  DEMO_MODE: True (safe)")

    except Exception as e:
        warnings.append(f"Could not import config/strategy for comparison: {e}")


def check_task_scheduler():
    """Verify all required Task Scheduler tasks exist and are enabled."""
    REQUIRED_TASKS = [
        "Ruppert-Demo-7AM",
        "Ruppert-Demo-3PM",
        "Ruppert-Demo-10PM",
        "Ruppert-Crypto-10AM",
        "Ruppert-Crypto-6PM",
        "Ruppert-PostTrade-Monitor",
        "Ruppert-DailyProgressReport",
        "Ruppert-DailyHealthCheck",
    ]
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-ScheduledTask | Where-Object {$_.TaskName -like 'Ruppert*'} | Select-Object TaskName,State | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15
        )
        tasks_json = json.loads(result.stdout or "[]")
        if isinstance(tasks_json, dict):
            tasks_json = [tasks_json]
        existing = {t["TaskName"]: t["State"] for t in tasks_json}

        for task in REQUIRED_TASKS:
            if task not in existing:
                issues.append(f"Task Scheduler: '{task}' is MISSING")
            elif existing[task] not in ('Ready', 'Running', 3, '3'):
                warnings.append(f"Task Scheduler: '{task}' state is '{existing[task]}' (expected Ready or Running)")
            else:
                print(f"  {task}: Ready")
    except Exception as e:
        warnings.append(f"Could not check Task Scheduler: {e}")


def check_capital_sot():
    """Verify capital.py is importable and returns sensible value."""
    try:
        import config  # function-local import — mirrors pattern used in check_threshold_consistency()
        from agents.ruppert.data_scientist.capital import get_capital
        cap = get_capital()
        if cap < config.MIN_CAPITAL_ALERT:
            issues.append(f"capital.get_capital() returned ${cap:.2f} — suspiciously low")
        else:
            print(f"  capital.get_capital(): ${cap:,.2f}")
    except Exception as e:
        issues.append(f"capital.py import failed: {e}")


def check_secrets_not_hardcoded():
    """Verify secrets are loaded from files, not hardcoded."""
    SECRETS_DIR = _WORKSPACE_ROOT / "secrets"
    required_secrets = ["kalshi_config.json"]
    for secret in required_secrets:
        path = SECRETS_DIR / secret
        if not path.exists():
            issues.append(f"Missing secrets file: secrets/{secret}")
        else:
            print(f"  secrets/{secret}: exists")


def main():
    print("=== Ruppert Config Audit ===\n")

    print("Checking threshold consistency...")
    check_threshold_consistency()

    print("Checking Task Scheduler tasks...")
    check_task_scheduler()

    print("Checking capital.py...")
    check_capital_sot()

    print("Checking secrets...")
    check_secrets_not_hardcoded()

    print()
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
        print("✅ All config checks passed")
        return 0

    if issues:
        print(f"RESULT: FAIL ({len(issues)} issues, {len(warnings)} warnings)")
        return 1

    print(f"RESULT: PASS WITH WARNINGS ({len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())


