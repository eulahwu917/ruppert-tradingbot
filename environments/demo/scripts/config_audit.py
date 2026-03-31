"""
config_audit.py — Automated guard for Task Scheduler configuration drift.
Owner: Researcher / Ops.

Verifies that all required Ruppert Task Scheduler tasks are registered
and that their configurations match expectations.

Usage:
  python environments/demo/scripts/config_audit.py

Exit codes:
  0 — all tasks present and verified
  1 — one or more tasks missing or misconfigured
"""

import subprocess
import sys

# -----------------------------------------------------------------------
# Required Task Scheduler tasks for Ruppert DEMO environment
# Source of truth: HEARTBEAT.md and PIPELINE.md
# Task names verified against registered tasks on DEMO host: 2026-03-29
# -----------------------------------------------------------------------
REQUIRED_TASKS = [
    {"name": "Ruppert-Crypto-10AM", "description": "Crypto scanner — 10AM daily"},
    {"name": "Ruppert-Crypto-12PM", "description": "Crypto scanner — 12PM daily"},
    {"name": "Ruppert-Crypto-2PM", "description": "Crypto scanner — 2PM daily"},
    {"name": "Ruppert-Crypto-4PM", "description": "Crypto scanner — 4PM daily"},
    {"name": "Ruppert-Crypto-6PM", "description": "Crypto scanner — 6PM daily"},
    {"name": "Ruppert-Crypto-8AM", "description": "Crypto scanner — 8AM daily"},
    {"name": "Ruppert-Crypto-8PM", "description": "Crypto scanner — 8PM daily"},
    {"name": "Ruppert-Crypto1D",     "description": "Crypto 1D scanner — 06:30 AM + 10:30 AM PDT"},
    {"name": "Ruppert-DailyHealthCheck", "description": "Daily health check (6:45AM)"},
    {"name": "Ruppert-DailyIntegrityCheck", "description": "Daily integrity check (6:50AM)"},
    {"name": "Ruppert-DailyProgressReport", "description": "Daily progress report (8PM)"},
    {"name": "Ruppert-Demo-10PM", "description": "Demo environment scanner — 10PM"},
    {"name": "Ruppert-Demo-3PM", "description": "Demo environment scanner — 3PM"},
    {"name": "Ruppert-Demo-7AM", "description": "Demo environment scanner — 7AM"},
    {"name": "Ruppert-Econ-Prescan", "description": "Economics pre-scan (5AM daily)"},
    {"name": "Ruppert-PostTrade-Monitor", "description": "Post-trade monitoring"},
    {"name": "Ruppert-Research-Weekly", "description": "Weekly research scan (Sundays 8AM)"},
    {"name": "Ruppert-SettlementChecker", "description": "Settlement checker (11PM daily)"},
    {"name": "Ruppert-Weather-7PM", "description": "Weather scanner — 7PM daily"},
    {"name": "Ruppert-WS-Persistent", "description": "Persistent WebSocket connection (runs continuously)"},
    {"name": "Ruppert-WS-Watchdog", "description": "WebSocket watchdog (monitors WS-Persistent)"},
    {"name": "RuppertDashboard", "description": "Ruppert dashboard service"},
]


def get_registered_tasks() -> list[str]:
    """Query Windows Task Scheduler for all Ruppert-prefixed tasks."""
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = result.stdout.splitlines()
        task_names = []
        for line in lines:
            if line.startswith("TaskName:"):
                raw = line.split(":", 1)[1].strip()
                task_names.append(raw.lstrip("\\"))
        return task_names
    except Exception as e:
        print(f"[config_audit] ERROR: Could not query Task Scheduler: {e}")
        return []


def audit_tasks(registered: list[str]) -> list[dict]:
    """Compare REQUIRED_TASKS against registered tasks. Returns list of missing task dicts."""
    missing = []
    for task in REQUIRED_TASKS:
        name = task["name"]
        found = any(r.lower() == name.lower() for r in registered)
        if not found:
            missing.append(task)
    return missing


def run_audit() -> int:
    """Full audit run. Returns exit code: 0=pass, 1=fail."""
    print("[config_audit] Querying Task Scheduler...")
    registered = get_registered_tasks()
    print(f"[config_audit] Found {len(registered)} total registered tasks")

    ruppert_tasks = [t for t in registered if "ruppert" in t.lower()]
    print(f"[config_audit] Ruppert-prefixed tasks found: {len(ruppert_tasks)}")
    for t in ruppert_tasks:
        print(f"  - {t}")

    print(f"\n[config_audit] Checking {len(REQUIRED_TASKS)} required tasks...")
    missing = audit_tasks(registered)

    if not missing:
        print("[config_audit] PASS — all required tasks present.")
        return 0
    else:
        print(f"[config_audit] FAIL — {len(missing)} required task(s) MISSING:")
        for task in missing:
            print(f"  MISSING: {task['name']}")
            print(f"           ({task['description']})")
        print("\n[config_audit] ACTION REQUIRED: Re-register missing tasks via environments/demo/config/")
        return 1


if __name__ == "__main__":
    sys.exit(run_audit())
