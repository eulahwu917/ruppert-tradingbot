# setup_sports_odds_scheduler.ps1
# Ruppert Trading Bot — Register Ruppert-SportsOdds Task Scheduler task
# Run as Administrator

$PythonExe  = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$WorkDir    = "C:\Users\David Wu\.openclaw\workspace"
$TaskName   = "Ruppert-SportsOdds"

Write-Host "=== Ruppert-SportsOdds Scheduler Setup ===" -ForegroundColor Cyan

# Remove existing task if present (idempotent)
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

# Action: python agents/ruppert/researcher/sports_odds_collector.py
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "agents/ruppert/researcher/sports_odds_collector.py" `
    -WorkingDirectory $WorkDir

# Triggers: hourly from 8:00 AM to 8:00 PM PDT (13 triggers: 8am through 8pm)
# Note: Task Scheduler uses local machine time. Ensure host is set to PDT.
$triggers = @()
for ($hour = 8; $hour -le 20; $hour++) {
    $timeStr = "{0:D2}:00" -f $hour
    $triggers += New-ScheduledTaskTrigger -Daily -At "$timeStr"
}

# Settings: restart on failure (3 retries, 2-minute interval), run highest privilege
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)

# Register with all hourly triggers (8am–8pm PDT)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Ruppert sports odds collector: hourly NBA/MLB Vegas-Kalshi gap scan, 8AM-8PM PDT." `
    -RunLevel Highest

Write-Host "  Created: $TaskName" -ForegroundColor Green
Write-Host "    Hourly triggers: 8:00 AM through 8:00 PM PDT" -ForegroundColor White
Write-Host ""
Write-Host "Manual run:" -ForegroundColor Yellow
Write-Host "  cd $WorkDir"
Write-Host "  python agents/ruppert/researcher/sports_odds_collector.py"
Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
