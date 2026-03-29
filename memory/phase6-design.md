# Phase 6 Design Document — Workspace Restructure

**Author:** Strategist  
**Date:** 2026-03-28  
**Status:** Ready for Dev implementation

---

## 1. Executive Summary

Phase 6 transforms Ruppert from a single-environment prototype into a production-ready dual-environment system. Core changes:

1. Rename `projects/` → `environments/`
2. Extract agents to workspace-level (`~/.openclaw/workspace/agents/ruppert/`)
3. Agents become environment-agnostic — pointed at demo or live via config
4. Live environment is read-only until David explicitly flips the switch
5. CEO hardened to trading-only role
6. ws_feed.py gets a watchdog that auto-restarts on failure

---

## 2. Target Folder Structure

After Phase 6 completion:

```
C:\Users\David Wu\.openclaw\workspace\
├── AGENTS.md
├── SOUL.md
├── USER.md
├── TOOLS.md
├── IDENTITY.md
├── MEMORY.md
├── PIPELINE.md
├── RULES.md
├── HEARTBEAT.md
│
├── agents/
│   └── ruppert/                          # <-- NEW: extracted from demo
│       ├── __init__.py
│       ├── env_config.py                 # <-- NEW: environment resolver
│       ├── ceo/
│       │   ├── __init__.py
│       │   └── brief_generator.py
│       ├── data_analyst/
│       │   ├── __init__.py
│       │   ├── fetch_smart_money.py
│       │   ├── ghcnd_client.py
│       │   ├── kalshi_client.py
│       │   ├── market_cache.py
│       │   ├── openmeteo_client.py
│       │   ├── wallet_updater.py
│       │   └── ws_feed.py
│       ├── data_scientist/
│       │   ├── __init__.py
│       │   ├── capital.py
│       │   ├── data_agent.py
│       │   ├── logger.py
│       │   └── synthesizer.py
│       ├── researcher/
│       │   ├── __init__.py
│       │   ├── market_scanner.py
│       │   └── research_agent.py
│       ├── strategist/
│       │   ├── __init__.py
│       │   ├── edge_detector.py
│       │   ├── optimizer.py
│       │   └── strategy.py
│       └── trader/
│           ├── __init__.py
│           ├── crypto_15m.py
│           ├── crypto_client.py
│           ├── crypto_long_horizon.py
│           ├── main.py
│           ├── position_monitor.py
│           ├── position_tracker.py
│           ├── post_trade_monitor.py
│           └── trader.py
│
├── environments/                         # <-- RENAMED from projects/
│   ├── demo/                             # <-- RENAMED from ruppert-tradingbot-demo
│   │   ├── mode.json                     # {"mode": "demo"}
│   │   ├── env.json                      # <-- NEW: environment metadata
│   │   ├── config.py                     # <-- MODIFIED: adds ENV_ROOT
│   │   ├── main.py
│   │   ├── ruppert_cycle.py
│   │   ├── ws_feed.py                    # <-- thin shim → agents/ruppert/
│   │   ├── [other .py files...]
│   │   ├── config/
│   │   │   └── fomc_slugs.json
│   │   ├── logs/
│   │   │   ├── raw/
│   │   │   ├── trades/
│   │   │   ├── truth/
│   │   │   ├── audits/
│   │   │   ├── executions/
│   │   │   ├── proposals/
│   │   │   └── archive/
│   │   ├── reports/
│   │   ├── memory/
│   │   │   └── agents/
│   │   ├── specs/
│   │   ├── tests/
│   │   ├── scripts/
│   │   ├── dashboard/
│   │   ├── docs/
│   │   ├── audit/
│   │   ├── bot/
│   │   ├── ws/
│   │   └── ruppert-backtest/
│   │
│   └── live/                             # <-- RENAMED from ruppert-tradingbot-live
│       ├── mode.json                     # {"mode": "live", "enabled": false}  <-- NEW enabled flag
│       ├── env.json                      # environment metadata
│       ├── config.py
│       ├── main.py
│       ├── ruppert_cycle.py
│       ├── [other .py files...]
│       ├── config/
│       │   ├── fomc_slugs.json
│       │   └── live_env.json
│       ├── logs/
│       │   └── truth/
│       ├── secrets/                      # <-- stays in live only
│       │   ├── kalshi_config.json
│       │   ├── kalshi_private_key.pem
│       │   └── kalshi_private_key_pkcs8.pem
│       ├── reports/
│       ├── memory/
│       │   └── agents/
│       ├── dashboard/
│       └── bot/
│
├── memory/                               # Ruppert's own memory (at workspace level)
│   ├── YYYY-MM-DD.md
│   └── heartbeat-state.json
│
├── secrets/                              # <-- SHARED secrets (Kalshi, Telegram, etc.)
│   ├── kalshi_config.json
│   ├── kalshi_private_key.pem
│   ├── kalshi_private_key_pkcs8.pem
│   ├── telegram_config.json
│   └── noaa_config.json
│
├── config/
│   └── cme_config.json
│
├── skills/
│   └── xiucheng-self-improving-agent/
│
└── archive/                              # Passive income research goes here → then deleted
```

---

## 3. Environment Configuration Pattern

### 3.1 New File: `agents/ruppert/env_config.py`

This is the single source of truth for environment resolution. Every agent module imports paths from here.

```python
"""
env_config.py — Environment resolver for Ruppert agents.

Agents import paths from here. At runtime:
  1. Check RUPPERT_ENV environment variable
  2. If not set, default to 'demo'
  3. Resolve all paths relative to that environment root

Usage in agent code:
    from agents.ruppert.env_config import get_paths
    paths = get_paths()
    truth_dir = paths['truth']
    logs_dir = paths['logs']
"""

import os
import json
from pathlib import Path

# Workspace root (fixed)
WORKSPACE_ROOT = Path(os.environ.get(
    'OPENCLAW_WORKSPACE',
    Path.home() / '.openclaw' / 'workspace'
))

ENVIRONMENTS_DIR = WORKSPACE_ROOT / 'environments'
SECRETS_DIR = WORKSPACE_ROOT / 'secrets'

# Default environment
_DEFAULT_ENV = 'demo'


def get_current_env() -> str:
    """
    Return the active environment name.
    Priority:
      1. RUPPERT_ENV environment variable
      2. 'demo' (default)
    """
    return os.environ.get('RUPPERT_ENV', _DEFAULT_ENV)


def get_env_root(env: str = None) -> Path:
    """Get the root path for an environment."""
    env = env or get_current_env()
    return ENVIRONMENTS_DIR / env


def is_live_enabled() -> bool:
    """
    Check if live trading is explicitly enabled.
    Reads environments/live/mode.json → {"enabled": true|false}
    Default: False (read-only)
    """
    live_mode_file = ENVIRONMENTS_DIR / 'live' / 'mode.json'
    if not live_mode_file.exists():
        return False
    try:
        data = json.loads(live_mode_file.read_text(encoding='utf-8'))
        return data.get('enabled', False) is True
    except Exception:
        return False


def get_paths(env: str = None) -> dict:
    """
    Return a dict of all standard paths for the given environment.
    Agents should use this to locate logs, truth files, reports, etc.
    """
    env = env or get_current_env()
    root = get_env_root(env)

    return {
        'env': env,
        'root': root,
        'logs': root / 'logs',
        'raw': root / 'logs' / 'raw',
        'trades': root / 'logs' / 'trades',
        'truth': root / 'logs' / 'truth',
        'audits': root / 'logs' / 'audits',
        'proposals': root / 'logs' / 'proposals',
        'reports': root / 'reports',
        'memory': root / 'memory',
        'config': root / 'config',
        'specs': root / 'specs',
        'mode_file': root / 'mode.json',
        # Shared secrets (workspace-level)
        'secrets': SECRETS_DIR,
    }


def get_both_truth_paths() -> dict:
    """
    Return truth paths for BOTH environments.
    Used by Data Scientist for cross-environment comparison.
    """
    return {
        'demo': ENVIRONMENTS_DIR / 'demo' / 'logs' / 'truth',
        'live': ENVIRONMENTS_DIR / 'live' / 'logs' / 'truth',
    }


def is_dry_run() -> bool:
    """
    Check if current environment is in dry-run mode.
    - demo → always dry run
    - live → dry run unless enabled=true
    """
    env = get_current_env()
    if env == 'demo':
        return True
    if env == 'live':
        return not is_live_enabled()
    return True  # default safe


def require_live_enabled():
    """
    Gate function — call before any live write operation.
    Raises RuntimeError if live is not enabled.
    """
    if get_current_env() == 'live' and not is_live_enabled():
        raise RuntimeError(
            "LIVE TRADING DISABLED. "
            "Set 'enabled': true in environments/live/mode.json to proceed."
        )
```

### 3.2 How Agents Use This

Every agent that reads/writes files updates its imports:

**Before (hardcoded paths):**
```python
LOGS_DIR = Path(__file__).parent.parent.parent / 'logs'
TRUTH_DIR = LOGS_DIR / 'truth'
```

**After (environment-aware):**
```python
from agents.ruppert.env_config import get_paths

paths = get_paths()
LOGS_DIR = paths['logs']
TRUTH_DIR = paths['truth']
```

### 3.3 Environment File: `environments/{demo,live}/env.json`

Each environment gets a metadata file:

**demo/env.json:**
```json
{
  "name": "demo",
  "description": "Paper trading environment — no real money",
  "dashboard_port": 8765,
  "logs_subdir": "logs"
}
```

**live/env.json:**
```json
{
  "name": "live",
  "description": "Real trading environment — REAL MONEY",
  "dashboard_port": 8766,
  "logs_subdir": "logs",
  "warning": "Do not modify mode.json.enabled without David's explicit approval"
}
```

### 3.4 Mode File Updates

**demo/mode.json:**
```json
{
  "mode": "demo"
}
```

**live/mode.json:**
```json
{
  "mode": "live",
  "enabled": false,
  "enabled_at": null,
  "enabled_by": null
}
```

When David flips live on:
```json
{
  "mode": "live",
  "enabled": true,
  "enabled_at": "2026-03-28T15:30:00-07:00",
  "enabled_by": "david"
}
```

---

## 4. Live Read-Only Enforcement

### 4.1 The Pattern

Every function that writes to the live environment must call `require_live_enabled()`:

```python
from agents.ruppert.env_config import get_current_env, require_live_enabled

def log_trade(trade_data):
    if get_current_env() == 'live':
        require_live_enabled()  # Raises if not enabled
    
    # ... write trade to file
```

### 4.2 Where To Add Guards

These files write to environment-specific paths and need the guard:

| File | Function(s) to guard |
|------|---------------------|
| `data_scientist/logger.py` | `log_trade()`, `log_activity()`, `write_truth_file()` |
| `trader/trader.py` | `execute_opportunity()` |
| `trader/position_tracker.py` | `add_position()`, `remove_position()` |
| `ceo/brief_generator.py` | `write_brief_to_file()` |
| `data_analyst/wallet_updater.py` | `update_wallet()` |

### 4.3 Read vs Write

- **Reads:** Always allowed from both environments
- **Writes:** 
  - Demo: Always allowed
  - Live: Only if `enabled: true` in mode.json

This lets Data Scientist compare demo vs live truth files for calibration even when live is disabled.

---

## 5. ws_feed.py Watchdog Design

### 5.1 Overview

The watchdog runs as a separate process alongside ws_feed.py. It checks if ws_feed.py is alive and restarts it if dead.

### 5.2 Implementation: `scripts/ws_feed_watchdog.py`

```python
"""
ws_feed_watchdog.py — Watchdog for ws_feed.py
Checks every 5 minutes. Restarts if:
  1. Process is not running
  2. Process is hung (no heartbeat in 10 min)
  
Run via Task Scheduler at system startup.
"""

import subprocess
import sys
import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

# Config
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
HEARTBEAT_STALE_SECONDS = 600  # 10 minutes — if no heartbeat, assume hung
HEARTBEAT_FILE = None  # Set at runtime based on environment

# Environment
WORKSPACE_ROOT = Path(os.environ.get(
    'OPENCLAW_WORKSPACE',
    Path.home() / '.openclaw' / 'workspace'
))


def get_env():
    return os.environ.get('RUPPERT_ENV', 'demo')


def get_env_root():
    return WORKSPACE_ROOT / 'environments' / get_env()


def get_heartbeat_file():
    return get_env_root() / 'logs' / 'ws_feed_heartbeat.json'


def get_ws_feed_script():
    return get_env_root() / 'ws_feed.py'


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[Watchdog {ts}] {msg}")
    
    # Also write to log file
    log_file = get_env_root() / 'logs' / 'watchdog.log'
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"[{ts}] {msg}\n")


def is_process_running() -> bool:
    """Check if ws_feed.py is running via process list."""
    try:
        # Windows: use tasklist
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=10
        )
        # Check if ws_feed.py appears in command lines
        # This is imperfect — better approach is to check heartbeat file
        return 'python' in result.stdout.lower()
    except Exception as e:
        log(f"Process check failed: {e}")
        return False


def is_heartbeat_fresh() -> bool:
    """Check if ws_feed.py has written a recent heartbeat."""
    hb_file = get_heartbeat_file()
    if not hb_file.exists():
        return False
    
    try:
        data = json.loads(hb_file.read_text(encoding='utf-8'))
        last_ts = data.get('last_heartbeat')
        if not last_ts:
            return False
        
        last_dt = datetime.fromisoformat(last_ts)
        stale_threshold = datetime.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
        return last_dt > stale_threshold
    except Exception as e:
        log(f"Heartbeat check failed: {e}")
        return False


def kill_stale_ws_feed():
    """Kill any stale ws_feed.py processes."""
    try:
        # Windows: use taskkill with /F (force)
        # This is a safety measure — kill before restarting
        subprocess.run(
            ['taskkill', '/F', '/IM', 'python.exe', '/FI', f'WINDOWTITLE eq *ws_feed*'],
            capture_output=True, timeout=10
        )
    except Exception:
        pass  # Best effort


def start_ws_feed():
    """Start ws_feed.py in a new process."""
    script = get_ws_feed_script()
    env_root = get_env_root()
    
    log(f"Starting ws_feed.py from {script}")
    
    # Start detached on Windows
    subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(env_root),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    log("ws_feed.py started")


def run_watchdog():
    """Main watchdog loop."""
    env = get_env()
    log(f"Watchdog starting for environment: {env}")
    log(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
    log(f"Heartbeat stale threshold: {HEARTBEAT_STALE_SECONDS}s")
    
    while True:
        try:
            if not is_heartbeat_fresh():
                log("Heartbeat stale or missing — ws_feed appears dead")
                kill_stale_ws_feed()
                time.sleep(2)  # Brief pause before restart
                start_ws_feed()
                log("Restarted ws_feed.py")
            else:
                # Heartbeat is fresh — ws_feed is alive
                pass
        except Exception as e:
            log(f"Watchdog error: {e}")
        
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == '__main__':
    run_watchdog()
```

### 5.3 ws_feed.py Heartbeat Updates

Add heartbeat writes to `ws_feed.py`:

```python
def _write_heartbeat():
    """Write heartbeat file so watchdog knows we're alive."""
    heartbeat_file = Path(__file__).parent / 'logs' / 'ws_feed_heartbeat.json'
    heartbeat_file.write_text(json.dumps({
        'last_heartbeat': datetime.now().isoformat(),
        'pid': os.getpid(),
        'status': 'running',
    }), encoding='utf-8')
```

Call `_write_heartbeat()` inside the existing heartbeat log in `run_ws_feed()`:

```python
# Periodic purge every 5 min
now = time.time()
if now - last_purge > 300:
    market_cache.purge_stale()
    _write_heartbeat()  # <-- ADD THIS
    # ... rest of heartbeat logging
```

### 5.4 Task Scheduler Setup

Create `scripts/setup/setup_watchdog_schedule.ps1`:

```powershell
# Create Task Scheduler entry for ws_feed watchdog
$action = New-ScheduledTaskAction -Execute "python" -Argument "scripts\ws_feed_watchdog.py" -WorkingDirectory "C:\Users\David Wu\.openclaw\workspace\environments\demo"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "Ruppert-WsFeed-Watchdog-Demo" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force

Write-Host "Watchdog task registered: Ruppert-WsFeed-Watchdog-Demo"
```

---

## 6. CEO Hardening

### 6.1 Current State

The CEO agent (`brief_generator.py`) currently:
- Generates daily briefs
- Sends via Telegram
- Reads truth files and logs

### 6.2 Hardening Changes

Add a role check to `brief_generator.py`:

```python
"""
brief_generator.py — CEO Daily Brief Generator.
Owner: CEO agent. Trading-only role — no general assistant tasks.

HARDENED ROLE:
- Generates trading briefs ONLY
- Does not respond to general queries
- Does not execute arbitrary tasks
- Reports to David via Telegram at 8PM daily
"""

# Add at top of file:
CEO_ALLOWED_TASKS = [
    'generate_brief',
    'send_brief',
    'summarize_trades',
    'report_pnl',
    'alert_anomaly',
]

def check_role_boundary(task: str):
    """
    Enforce CEO role boundary.
    CEO only handles trading-related tasks.
    """
    if task not in CEO_ALLOWED_TASKS:
        raise ValueError(
            f"CEO role violation: '{task}' is not a trading task. "
            f"CEO is hardened to trading-only. Use Ruppert main session for general tasks."
        )
```

### 6.3 Documentation Update

Add `agents/ruppert/ceo/ROLE.md`:

```markdown
# CEO Agent — Role Definition

## Purpose
Generate daily trading briefs and report to David.

## Allowed Tasks
- generate_brief — Build daily brief from truth files
- send_brief — Send via Telegram
- summarize_trades — Aggregate trade performance
- report_pnl — Calculate P&L snapshots
- alert_anomaly — Flag circuit breakers and errors

## NOT Allowed
- General assistant tasks
- Arbitrary code execution
- External API calls (except Telegram)
- Modifying trading parameters

## Trigger
Runs at 8PM PDT via Task Scheduler.

## Escalation
If CEO encounters issues outside its scope, it logs to:
  logs/raw/events_YYYY-MM-DD.jsonl
  
David reviews in next session.
```

---

## 7. Migration Plan

### 7.1 Order of Operations

**Phase 6A: Preparation (no bot downtime)**

1. **Create new structure (empty)**
   ```
   mkdir environments
   mkdir agents\ruppert
   ```

2. **Copy agents to workspace level**
   ```
   xcopy projects\ruppert-tradingbot-demo\agents\* agents\ruppert\ /E /I
   ```

3. **Create env_config.py**
   - Write the new environment resolver

4. **Update agent imports** (in `agents/ruppert/`)
   - Change all hardcoded paths to use `env_config.get_paths()`
   - This is the bulk of the work

5. **Test agents work from new location**
   ```
   set RUPPERT_ENV=demo
   python -m agents.ruppert.ceo.brief_generator
   ```

**Phase 6B: Switch (brief bot downtime)**

6. **Stop ws_feed.py and scheduled tasks**
   - Kill ws_feed.py
   - Disable Task Scheduler entries temporarily

7. **Move environments**
   ```powershell
   Move-Item projects\ruppert-tradingbot-demo environments\demo
   Move-Item projects\ruppert-tradingbot-live environments\live
   ```

8. **Delete old agents folder from demo**
   ```
   Remove-Item environments\demo\agents -Recurse
   ```

9. **Update environment config files**
   - Create `env.json` in each environment
   - Update `mode.json` in live (add `enabled: false`)

10. **Update live/mode.json for read-only default**
    ```json
    {"mode": "live", "enabled": false}
    ```

11. **Update demo shims**
    - `demo/ws_feed.py` becomes thin import shim:
    ```python
    from agents.ruppert.data_analyst.ws_feed import run
    if __name__ == '__main__':
        run()
    ```

12. **Test demo still works**
    ```
    cd environments\demo
    python ws_feed.py
    ```

13. **Restart tasks and ws_feed**

**Phase 6C: Cleanup**

14. **Delete passive-income-research**
    ```
    Remove-Item projects\passive-income-research -Recurse
    ```

15. **Remove projects folder** (now empty)
    ```
    Remove-Item projects
    ```

16. **Create watchdog task**
    - Run `setup_watchdog_schedule.ps1`

17. **Verify end-to-end**
    - Run full demo cycle
    - Check briefs generate
    - Verify watchdog starts

### 7.2 Rollback Plan

If something breaks during 6B:

```powershell
# Emergency rollback
Move-Item environments\demo projects\ruppert-tradingbot-demo
Move-Item environments\live projects\ruppert-tradingbot-live
# Re-copy agents back into demo
xcopy agents\ruppert\* projects\ruppert-tradingbot-demo\agents\ /E /I
```

Keep the new `agents/ruppert/` even after rollback — we can retry migration later.

---

## 8. Files To Modify

### 8.1 Agent Files Requiring Import Updates

All files in `agents/ruppert/` need path updates:

| File | What Changes |
|------|--------------|
| `ceo/brief_generator.py` | LOGS_DIR, TRUTH_DIR, REPORTS_DIR |
| `data_scientist/logger.py` | LOG_FILE, TRUTH_DIR |
| `data_scientist/capital.py` | PNL_CACHE path |
| `data_analyst/kalshi_client.py` | CONFIG_FILE path |
| `data_analyst/ws_feed.py` | market_cache, position_tracker imports |
| `trader/trader.py` | config imports, log paths |
| `trader/position_tracker.py` | STATE_FILE path |
| `strategist/strategy.py` | config imports |

### 8.2 Environment Files To Create

| Path | Purpose |
|------|---------|
| `environments/demo/env.json` | Environment metadata |
| `environments/live/env.json` | Environment metadata |
| `agents/ruppert/env_config.py` | Environment resolver |
| `agents/ruppert/ceo/ROLE.md` | CEO role documentation |
| `scripts/ws_feed_watchdog.py` | Watchdog process |
| `scripts/setup/setup_watchdog_schedule.ps1` | Task scheduler setup |

### 8.3 Environment Files To Update

| Path | Change |
|------|--------|
| `environments/live/mode.json` | Add `"enabled": false` |
| `environments/demo/ws_feed.py` | Convert to import shim |
| `environments/demo/config.py` | Add ENV_ROOT reference |

---

## 9. Risks & David Decisions Needed

### 9.1 Risks

| Risk | Mitigation |
|------|------------|
| Import path breakage | Run full pytest suite after each file update |
| Task Scheduler paths break | Document old vs new paths; update all .bat/.xml files |
| Live accidentally enabled | `enabled: false` default + require_live_enabled() guards |
| Watchdog starts ws_feed when markets closed | ws_feed already has market hours check |
| Data Scientist can't find old truth files | Migration copies all logs — nothing deleted |

### 9.2 Decisions for David

1. **Secrets location:** Currently live has its own `secrets/` folder. Should we:
   - A) Keep live secrets separate (more isolation)
   - B) Move all secrets to workspace-level `secrets/` (single source of truth)
   
   **Recommendation:** B — single `secrets/` at workspace level. Both environments read from same credentials.

2. **Live enable flow:** When David wants to flip live on, should it be:
   - A) Edit mode.json manually
   - B) CLI command `python -m agents.ruppert.enable_live --confirm`
   - C) Telegram command to Ruppert
   
   **Recommendation:** A for now (simplest). We can add B/C later.

3. **Old demo code:** After migration, `environments/demo/` still has all the `.py` files from Phase 1-5. Should we:
   - A) Keep them (bot runs from there)
   - B) Convert to thin shims that import from `agents/ruppert/`
   
   **Recommendation:** A — keep them. Converting everything to shims is extra work with minimal benefit. The key is that `agents/` becomes the canonical codebase for future edits.

4. **Dashboard ports:** Demo uses 8765, live uses 8766. Keep as-is?
   
   **Recommendation:** Yes, keep. Allows running both dashboards simultaneously.

---

## 10. Verification Checklist

After Phase 6 completion, verify:

- [ ] `python environments\demo\ws_feed.py` starts correctly
- [ ] `python -m agents.ruppert.ceo.brief_generator` generates brief
- [ ] `pytest environments\demo\tests\` passes
- [ ] Watchdog starts on system boot
- [ ] Watchdog restarts ws_feed if killed
- [ ] Live mode.json has `enabled: false`
- [ ] Attempting live trade with enabled=false raises RuntimeError
- [ ] Data Scientist can read both demo and live truth files
- [ ] `projects\` folder no longer exists
- [ ] `passive-income-research` deleted

---

## 11. Summary for Dev

**What Dev needs to do:**

1. Create `agents/ruppert/env_config.py` (code provided above)
2. Copy agents from `projects/ruppert-tradingbot-demo/agents/` to `agents/ruppert/`
3. Update all imports in agent files to use `env_config.get_paths()`
4. Add `require_live_enabled()` guards to write functions
5. Create watchdog script (code provided above)
6. Move demo/live to environments/
7. Create env.json files
8. Update live/mode.json with `enabled: false`
9. Delete passive-income-research
10. Set up watchdog Task Scheduler entry
11. Test everything

**Estimated effort:** 2-3 hours for a careful migration.

**Critical path:** Step 3 (import updates) is the most tedious. Do it file by file, test after each.

---

*End of Phase 6 Design Document*
