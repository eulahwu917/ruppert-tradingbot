@echo off
echo Starting Ruppert Dashboard on http://localhost:8765
cd /d "C:\Users\David Wu\.openclaw\workspace\environments\demo"
python -m uvicorn dashboard.api:app --port 8765 --host 0.0.0.0
pause
