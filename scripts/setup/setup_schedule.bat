@echo off
set PYTHON=C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe
set BOTDIR=C:\Users\David Wu\.openclaw\workspace\kalshi-bot

schtasks /delete /tn "Ruppert_7am"        /f 2>nul
schtasks /delete /tn "Ruppert_7am_Report" /f 2>nul
schtasks /delete /tn "Ruppert_12pm"       /f 2>nul
schtasks /delete /tn "Ruppert_3pm"        /f 2>nul
schtasks /delete /tn "Ruppert_7pm_Report" /f 2>nul
schtasks /delete /tn "Ruppert_10pm"       /f 2>nul

schtasks /create /tn "Ruppert_7am"        /tr "\"%PYTHON%\" \"%BOTDIR%\ruppert_cycle.py\" full"  /sc DAILY /st 07:00 /f
schtasks /create /tn "Ruppert_7am_Report" /tr "\"%PYTHON%\" \"%BOTDIR%\daily_report.py\""        /sc DAILY /st 07:05 /f
schtasks /create /tn "Ruppert_12pm"       /tr "\"%PYTHON%\" \"%BOTDIR%\ruppert_cycle.py\" check" /sc DAILY /st 12:00 /f
schtasks /create /tn "Ruppert_3pm"        /tr "\"%PYTHON%\" \"%BOTDIR%\ruppert_cycle.py\" full"  /sc DAILY /st 15:00 /f
schtasks /create /tn "Ruppert_7pm_Report" /tr "\"%PYTHON%\" \"%BOTDIR%\daily_report.py\""        /sc DAILY /st 19:00 /f
schtasks /create /tn "Ruppert_10pm"       /tr "\"%PYTHON%\" \"%BOTDIR%\ruppert_cycle.py\" check" /sc DAILY /st 22:00 /f

echo.
echo Schedule registered with full Python path.
echo   07:00  Full scan
echo   07:05  Morning report to David
echo   12:00  Position check
echo   15:00  Full scan
echo   19:00  Evening report to David
echo   22:00  Night check
