# setup_scheduler_v2.ps1
# Ruppert Trading Bot - Task Scheduler v2
# Run as Administrator

$PythonExe = "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe"
$ScriptDir = "C:\Users\David Wu\.openclaw\workspace\ruppert-tradingbot-demo"

Write-Host "=== Ruppert Scheduler v2 Setup ===" -ForegroundColor Cyan

# DELETE redundant tasks
Write-Host "[1] Removing redundant tasks..." -ForegroundColor Yellow
try {
    Unregister-ScheduledTask -TaskName "Ruppert-Demo-12PM" -Confirm:$false -ErrorAction Stop
    Write-Host "  Deleted: Ruppert-Demo-12PM"
} catch {
    Write-Host "  Ruppert-Demo-12PM not found (skipping)"
}

# UPDATE existing tasks
Write-Host "[2] Updating existing tasks..." -ForegroundColor Yellow

$action7am = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py full" -WorkingDirectory $ScriptDir
$trigger7am = New-ScheduledTaskTrigger -Daily -At 7:00AM
try {
    Set-ScheduledTask -TaskName "Ruppert-Demo-7AM" -Action $action7am -Trigger $trigger7am -ErrorAction Stop
    Write-Host "  Updated: Ruppert-Demo-7AM"
} catch {
    Register-ScheduledTask -TaskName "Ruppert-Demo-7AM" -Action $action7am -Trigger $trigger7am -Description "Ruppert full cycle 7am" -RunLevel Highest
    Write-Host "  Created: Ruppert-Demo-7AM"
}

$action3pm = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py full" -WorkingDirectory $ScriptDir
$trigger3pm = New-ScheduledTaskTrigger -Daily -At 3:00PM
try {
    Set-ScheduledTask -TaskName "Ruppert-Demo-3PM" -Action $action3pm -Trigger $trigger3pm -ErrorAction Stop
    Write-Host "  Updated: Ruppert-Demo-3PM"
} catch {
    Register-ScheduledTask -TaskName "Ruppert-Demo-3PM" -Action $action3pm -Trigger $trigger3pm -Description "Ruppert full cycle 3pm" -RunLevel Highest
    Write-Host "  Created: Ruppert-Demo-3PM"
}

Write-Host "  Kept: Ruppert-Demo-10PM (no changes)"

# ADD new tasks
Write-Host "[3] Adding new tasks..." -ForegroundColor Yellow

$actionWeather = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py weather_only" -WorkingDirectory $ScriptDir
$triggerWeather = New-ScheduledTaskTrigger -Daily -At 7:00PM
try { Unregister-ScheduledTask -TaskName "Ruppert-Weather-7PM" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName "Ruppert-Weather-7PM" -Action $actionWeather -Trigger $triggerWeather -Description "Ruppert weather_only 7pm" -RunLevel Highest
Write-Host "  Added: Ruppert-Weather-7PM"

$actionCrypto10 = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $ScriptDir
$triggerCrypto10 = New-ScheduledTaskTrigger -Daily -At 10:00AM
try { Unregister-ScheduledTask -TaskName "Ruppert-Crypto-10AM" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName "Ruppert-Crypto-10AM" -Action $actionCrypto10 -Trigger $triggerCrypto10 -Description "Ruppert crypto_only 10am" -RunLevel Highest
Write-Host "  Added: Ruppert-Crypto-10AM"

$actionCrypto6 = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py crypto_only" -WorkingDirectory $ScriptDir
$triggerCrypto6 = New-ScheduledTaskTrigger -Daily -At 6:00PM
try { Unregister-ScheduledTask -TaskName "Ruppert-Crypto-6PM" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName "Ruppert-Crypto-6PM" -Action $actionCrypto6 -Trigger $triggerCrypto6 -Description "Ruppert crypto_only 6pm" -RunLevel Highest
Write-Host "  Added: Ruppert-Crypto-6PM"

$actionEcon = New-ScheduledTaskAction -Execute $PythonExe -Argument "ruppert_cycle.py econ_prescan" -WorkingDirectory $ScriptDir
$triggerEcon = New-ScheduledTaskTrigger -Daily -At 5:00AM
try { Unregister-ScheduledTask -TaskName "Ruppert-Econ-Prescan" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName "Ruppert-Econ-Prescan" -Action $actionEcon -Trigger $triggerEcon -Description "Ruppert econ_prescan 5am" -RunLevel Highest
Write-Host "  Added: Ruppert-Econ-Prescan"

# ADD post-trade monitor (every 30 min, 6am-11pm)
Write-Host "[4] Adding post-trade monitor..." -ForegroundColor Yellow

$actionMonitor = New-ScheduledTaskAction -Execute $PythonExe -Argument "post_trade_monitor.py" -WorkingDirectory $ScriptDir
$triggerMonitor = New-ScheduledTaskTrigger -Daily -At 6:00AM
$triggerMonitor.Repetition.Interval = [System.TimeSpan]::FromMinutes(30)
$triggerMonitor.Repetition.Duration = [System.TimeSpan]::FromHours(17)
try { Unregister-ScheduledTask -TaskName "Ruppert-PostTrade-Monitor" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
Register-ScheduledTask -TaskName "Ruppert-PostTrade-Monitor" -Action $actionMonitor -Trigger $triggerMonitor -Description "Ruppert post-trade monitor every 30min 6am-11pm" -RunLevel Highest
Write-Host "  Added: Ruppert-PostTrade-Monitor (every 30min)"

Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "  5:00am  Ruppert-Econ-Prescan"
Write-Host "  6:00am  Ruppert-PostTrade-Monitor (every 30min until 11pm)"
Write-Host "  7:00am  Ruppert-Demo-7AM (full)"
Write-Host " 10:00am  Ruppert-Crypto-10AM (crypto_only)"
Write-Host "  3:00pm  Ruppert-Demo-3PM (full)"
Write-Host "  6:00pm  Ruppert-Crypto-6PM (crypto_only)"
Write-Host "  7:00pm  Ruppert-Weather-7PM (weather_only)"
Write-Host " 10:00pm  Ruppert-Demo-10PM (check)"
