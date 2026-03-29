# setup_watchdog_schedule.ps1
# Create Task Scheduler entry for ws_feed watchdog (demo environment)
# Run this script AFTER Phase 6 migration is complete.

$pythonExe = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$watchdogScript = "C:\Users\David Wu\.openclaw\workspace\scripts\ws_feed_watchdog.py"
$envRoot = "C:\Users\David Wu\.openclaw\workspace\environments\demo"

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument $watchdogScript `
    -WorkingDirectory $envRoot

$trigger = New-ScheduledTaskTrigger -AtStartup

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# Set RUPPERT_ENV environment variable for the task
$envVars = [Microsoft.Win32.TaskScheduler.EnvironmentSettings]::new()

Register-ScheduledTask `
    -TaskName "Ruppert-WsFeed-Watchdog-Demo" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force

Write-Host "Watchdog task registered: Ruppert-WsFeed-Watchdog-Demo"
Write-Host "NOTE: Manually set the RUPPERT_ENV=demo environment variable in Task Scheduler if needed."
