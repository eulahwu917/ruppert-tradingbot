# Spec: Register Ruppert-Crypto1D Task Scheduler Task

**Date:** 2026-03-30  
**Author:** Trader (subagent)  
**Status:** PENDING DEV  
**Priority:** HIGH — `crypto_1d` module will never fire without this fix

---

## Problem

The `crypto_1d` module (daily crypto above/below: KXBTCD, KXETHD, KXSOLD) has no registered
Windows Task Scheduler task. Despite having full config, edge detection, and execution code, it
is silently skipped every day. It is also absent from `REQUIRED_TASKS` in `config_audit.py`,
so the health check does not flag its absence.

---

## Existing Pattern (Reference)

`setup_settlement_checker.ps1` demonstrates the canonical pattern for multi-trigger tasks:

```powershell
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m environments.demo.settlement_checker" `
    -WorkingDirectory $WorkspaceRoot

$trigger11pm = New-ScheduledTaskTrigger -Daily -At 11:00PM
$trigger8am  = New-ScheduledTaskTrigger -Daily -At 8:00AM

Register-ScheduledTask `
    -TaskName "Ruppert-SettlementChecker" `
    -Action $action `
    -Trigger @($trigger11pm, $trigger8am) `
    -Description "..." `
    -RunLevel Highest
```

Restart-on-failure must be set post-registration via `Set-ScheduledTask` with a settings object,
as `Register-ScheduledTask` does not expose retry parameters directly.

---

## Fix 1A — PowerShell: Register Ruppert-Crypto1D

**File to create:** `scripts/setup/setup_crypto_1d_scheduler.ps1`

```powershell
# setup_crypto_1d_scheduler.ps1
# Ruppert Trading Bot — Register crypto_1d Task Scheduler task
# Run as Administrator

$PythonExe  = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$WorkDir    = "C:\Users\David Wu\.openclaw\workspace"
$TaskName   = "Ruppert-Crypto1D"

Write-Host "=== Ruppert-Crypto1D Scheduler Setup ===" -ForegroundColor Cyan

# Remove existing task if present (idempotent)
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# Action: python -m environments.demo.ruppert_cycle crypto_1d
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m environments.demo.ruppert_cycle crypto_1d" `
    -WorkingDirectory $WorkDir

# Triggers: 06:30 AM PDT and 10:30 AM PDT (= 09:30 ET / 13:30 ET)
# Note: Task Scheduler uses local machine time. Ensure host is set to PDT.
$trigger0630 = New-ScheduledTaskTrigger -Daily -At 6:30AM
$trigger1030 = New-ScheduledTaskTrigger -Daily -At 10:30AM

# Settings: restart on failure (3 retries, 2-minute interval), run highest privilege
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)

# Register with both triggers
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($trigger0630, $trigger1030) `
    -Settings $settings `
    -Description "Ruppert crypto_1d scanner: daily crypto above/below (KXBTCD/KXETHD/KXSOLD). Runs 06:30 AM + 10:30 AM PDT." `
    -RunLevel Highest

Write-Host "  Created: $TaskName" -ForegroundColor Green
Write-Host "    06:30 AM PDT  Primary window (09:30 ET open)"
Write-Host "    10:30 AM PDT  Secondary window (13:30 ET)"
Write-Host ""
Write-Host "Manual run:" -ForegroundColor Yellow
Write-Host "  cd $WorkDir"
Write-Host "  python -m environments.demo.ruppert_cycle crypto_1d"
Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
```

---

## Fix 1B — config_audit.py: Add to REQUIRED_TASKS

**File:** `environments/demo/scripts/config_audit.py`

### BEFORE

```python
REQUIRED_TASKS = [
    {"name": "Ruppert-Crypto-10AM", "description": "Crypto scanner — 10AM daily"},
    {"name": "Ruppert-Crypto-12PM", "description": "Crypto scanner — 12PM daily"},
    {"name": "Ruppert-Crypto-2PM",  "description": "Crypto scanner — 2PM daily"},
    {"name": "Ruppert-Crypto-4PM",  "description": "Crypto scanner — 4PM daily"},
    {"name": "Ruppert-Crypto-6PM",  "description": "Crypto scanner — 6PM daily"},
    {"name": "Ruppert-Crypto-8AM",  "description": "Crypto scanner — 8AM daily"},
    {"name": "Ruppert-Crypto-8PM",  "description": "Crypto scanner — 8PM daily"},
    ...
]
```

### AFTER

Insert `Ruppert-Crypto1D` entry in alphabetical order within the list (after the
`Ruppert-Crypto-8PM` block):

```python
REQUIRED_TASKS = [
    {"name": "Ruppert-Crypto-10AM",  "description": "Crypto scanner — 10AM daily"},
    {"name": "Ruppert-Crypto-12PM",  "description": "Crypto scanner — 12PM daily"},
    {"name": "Ruppert-Crypto-2PM",   "description": "Crypto scanner — 2PM daily"},
    {"name": "Ruppert-Crypto-4PM",   "description": "Crypto scanner — 4PM daily"},
    {"name": "Ruppert-Crypto-6PM",   "description": "Crypto scanner — 6PM daily"},
    {"name": "Ruppert-Crypto-8AM",   "description": "Crypto scanner — 8AM daily"},
    {"name": "Ruppert-Crypto-8PM",   "description": "Crypto scanner — 8PM daily"},
    {"name": "Ruppert-Crypto1D",     "description": "Crypto 1D scanner — 06:30 AM + 10:30 AM PDT"},  # ← ADD
    ...
]
```

---

## Acceptance Criteria

1. `schtasks /query /fo LIST /tn "Ruppert-Crypto1D"` returns the task without error
2. Task shows two triggers: 06:30 and 10:30
3. Task action contains `-m environments.demo.ruppert_cycle crypto_1d`
4. Working directory is `C:\Users\David Wu\.openclaw\workspace`
5. Restart count = 3, restart interval = PT2M (visible in task XML)
6. `python environments/demo/scripts/config_audit.py` exits 0 with `Ruppert-Crypto1D` present
7. Manual run `python -m environments.demo.ruppert_cycle crypto_1d` completes without import error

---

## Rollback

```powershell
Unregister-ScheduledTask -TaskName "Ruppert-Crypto1D" -Confirm:$false
```

Remove the `Ruppert-Crypto1D` entry from `REQUIRED_TASKS`.
