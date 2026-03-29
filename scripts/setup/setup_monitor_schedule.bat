@echo off
REM Sets up Windows Task Scheduler for Ruppert Position Monitor
REM Run this once as Administrator

SET PYTHON=python
SET SCRIPT=C:\Users\David Wu\.openclaw\workspace\kalshi-bot\position_monitor.py

echo Setting up Ruppert Position Monitor schedule...

REM Evening check (10pm) — T-1 full ensemble re-check
schtasks /create /tn "RuppertMonitor_Evening" /tr "%PYTHON% \"%SCRIPT%\" summary" /sc daily /st 22:00 /f
echo   [OK] Evening check at 10:00 PM

REM Morning check (7am) — day-of morning conditions
schtasks /create /tn "RuppertMonitor_Morning" /tr "%PYTHON% \"%SCRIPT%\" summary" /sc daily /st 07:00 /f
echo   [OK] Morning check at 7:00 AM

REM Noon check (12pm) — final intraday check
schtasks /create /tn "RuppertMonitor_Noon" /tr "%PYTHON% \"%SCRIPT%\" check" /sc daily /st 12:00 /f
echo   [OK] Noon check at 12:00 PM

REM Afternoon check (3pm) — catching late-day moves
schtasks /create /tn "RuppertMonitor_Afternoon" /tr "%PYTHON% \"%SCRIPT%\" check" /sc daily /st 15:00 /f
echo   [OK] Afternoon check at 3:00 PM

echo.
echo Done! Tasks registered in Windows Task Scheduler.
echo To verify: schtasks /query /tn "RuppertMonitor*"
echo To remove: schtasks /delete /tn "RuppertMonitor*" /f
pause
