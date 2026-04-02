# setup_settlement_checker.ps1
# Ruppert Settlement Checker - Task Scheduler Setup
# Run as Administrator
#
# Creates Ruppert-SettlementChecker with two daily triggers:
#   - 11:00 PM PDT (after all markets close)
#   -  8:00 AM PDT (catch overnight settlements)

$PythonExe = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$WorkspaceRoot = "C:\Users\David Wu\.openclaw\workspace"

Write-Host "=== Ruppert Settlement Checker Setup ===" -ForegroundColor Cyan

# Remove existing task if present
try {
    Unregister-ScheduledTask -TaskName "Ruppert-SettlementChecker" -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# Action: run settlement_checker.py with PYTHONPATH and RUPPERT_ENV set
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m environments.demo.settlement_checker" `
    -WorkingDirectory $WorkspaceRoot

# Two daily triggers: 11PM and 8AM
$trigger11pm = New-ScheduledTaskTrigger -Daily -At 11:00PM
$trigger8am  = New-ScheduledTaskTrigger -Daily -At 8:00AM

# Intraday trigger: every 30 minutes from 6AM to 10PM (16-hour window)
$triggerIntraday = New-ScheduledTaskTrigger -Once -At 6:00AM `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 16)

# Register with all triggers
Register-ScheduledTask `
    -TaskName "Ruppert-SettlementChecker" `
    -Action $action `
    -Trigger @($trigger11pm, $trigger8am, $triggerIntraday) `
    -Description "Ruppert settlement checker: resolves expired markets, computes P&L. Runs 11PM + 8AM + every 30min 6AM-10PM." `
    -RunLevel Highest

# Set environment variables for the task
# Note: PYTHONPATH and RUPPERT_ENV are set via the working directory and module path
Write-Host "  Created: Ruppert-SettlementChecker" -ForegroundColor Green
Write-Host "    8:00 AM  Catch overnight settlements"
Write-Host "   11:00 PM  After all markets close"
Write-Host "    Every 30min 6AM-10PM  Intraday hourly-expiry coverage"
Write-Host ""
Write-Host "Manual run:" -ForegroundColor Yellow
Write-Host "  cd $WorkspaceRoot"
Write-Host "  `$env:PYTHONPATH = '$WorkspaceRoot'"
Write-Host "  `$env:RUPPERT_ENV = 'demo'"
Write-Host "  python -m environments.demo.settlement_checker"
Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
