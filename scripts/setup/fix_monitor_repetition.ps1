# fix_monitor_repetition.ps1
# Fixes the Ruppert-PostTrade-Monitor trigger to repeat every 30 min from 6am to 11pm
# Run as Administrator

$PythonExe = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$ScriptDir = "C:\Users\David Wu\.openclaw\workspace\ruppert-tradingbot-demo"

Write-Host "Fixing Ruppert-PostTrade-Monitor repetition trigger..." -ForegroundColor Cyan

try { Unregister-ScheduledTask -TaskName "Ruppert-PostTrade-Monitor" -Confirm:$false -ErrorAction SilentlyContinue } catch {}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "post_trade_monitor.py" -WorkingDirectory $ScriptDir

# Use CIM-based trigger with repetition (works on Windows 10/11)
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$task = New-ScheduledTask -Action $action -Trigger $trigger -Description "Ruppert post-trade monitor every 30min 6am-11pm"
$registeredTask = Register-ScheduledTask -TaskName "Ruppert-PostTrade-Monitor" -InputObject $task -RunLevel Highest

# Now set repetition via the COM object
$taskService = New-Object -ComObject Schedule.Service
$taskService.Connect()
$taskFolder = $taskService.GetFolder("\")
$comTask = $taskFolder.GetTask("Ruppert-PostTrade-Monitor")
$comTaskDef = $comTask.Definition

$comTrigger = $comTaskDef.Triggers.Item(1)
$comTrigger.Repetition.Interval = "PT30M"
$comTrigger.Repetition.Duration = "PT17H"
$comTrigger.Repetition.StopAtDurationEnd = $true

$taskFolder.RegisterTaskDefinition("Ruppert-PostTrade-Monitor", $comTaskDef, 4, $null, $null, 3)

Write-Host "Done - Ruppert-PostTrade-Monitor set to every 30min from 6am to 11pm" -ForegroundColor Green
