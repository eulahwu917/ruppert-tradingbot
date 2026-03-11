@echo off
echo Setting up Ruppert autonomous trading + report schedule...

set PYTHON=python
set BOTDIR=C:\Users\David Wu\.openclaw\workspace\kalshi-bot

:: Clean up old tasks
schtasks /delete /tn "RuppertMonitor_Morning"      /f 2>nul
schtasks /delete /tn "RuppertMonitor_Noon"         /f 2>nul
schtasks /delete /tn "RuppertMonitor_Afternoon"    /f 2>nul
schtasks /delete /tn "RuppertMonitor_Evening"      /f 2>nul
schtasks /delete /tn "Ruppert_FullCycle_Morning"   /f 2>nul
schtasks /delete /tn "Ruppert_Check_Noon"          /f 2>nul
schtasks /delete /tn "Ruppert_FullCycle_Afternoon" /f 2>nul
schtasks /delete /tn "Ruppert_Check_Evening"       /f 2>nul
schtasks /delete /tn "Ruppert_Report_Evening"      /f 2>nul

:: 07:00 — Full cycle + morning report (Account Value + P&L)
schtasks /create /tn "Ruppert_7am" /tr "%PYTHON% \"%BOTDIR%\ruppert_cycle.py\" full" /sc DAILY /st 07:00 /f
schtasks /create /tn "Ruppert_7am_Report" /tr "%PYTHON% \"%BOTDIR%\daily_report.py\"" /sc DAILY /st 07:05 /f
echo Registered: 07:00 full scan + 07:05 morning report

:: 12:00 — Position check only
schtasks /create /tn "Ruppert_12pm" /tr "%PYTHON% \"%BOTDIR%\ruppert_cycle.py\" check" /sc DAILY /st 12:00 /f
echo Registered: 12:00 position check

:: 15:00 — Afternoon full cycle
schtasks /create /tn "Ruppert_3pm" /tr "%PYTHON% \"%BOTDIR%\ruppert_cycle.py\" full" /sc DAILY /st 15:00 /f
echo Registered: 15:00 full scan

:: 19:00 — Evening report (Account Value + P&L)
schtasks /create /tn "Ruppert_7pm_Report" /tr "%PYTHON% \"%BOTDIR%\daily_report.py\"" /sc DAILY /st 19:00 /f
echo Registered: 19:00 evening report

:: 22:00 — Night position check
schtasks /create /tn "Ruppert_10pm" /tr "%PYTHON% \"%BOTDIR%\ruppert_cycle.py\" check" /sc DAILY /st 22:00 /f
echo Registered: 22:00 night position check

echo.
echo Full schedule:
echo   07:00  Full scan (weather + crypto + smart money + execute)
echo   07:05  Morning report to David (Account Value + P&L)
echo   12:00  Position check + auto-exit if needed
echo   15:00  Full scan (afternoon)
echo   19:00  Evening report to David (Account Value + P&L)
echo   22:00  Night position check
echo.
echo Done.
