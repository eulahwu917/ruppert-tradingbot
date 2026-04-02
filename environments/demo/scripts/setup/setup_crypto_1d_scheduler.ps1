# setup_crypto_1d_scheduler.ps1
# Ruppert Trading Bot — Register crypto_threshold_daily Task Scheduler task
# Run as Administrator

$PythonExe  = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$WorkDir    = "C:\Users\David Wu\.openclaw\workspace"
$TaskName   = "Ruppert-CryptoThresholdDaily"

Write-Host "=== Ruppert-CryptoThresholdDaily Scheduler Setup ===" -ForegroundColor Cyan

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
    -Description "Ruppert crypto_threshold_daily scanner: daily crypto above/below (KXBTCD/KXETHD/KXSOLD). Runs 06:30 AM + 10:30 AM PDT." `
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
