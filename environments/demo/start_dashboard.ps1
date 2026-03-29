$env:PYTHONPATH = "C:\Users\David Wu\.openclaw\workspace"
$env:RUPPERT_ENV = "demo"
Set-Location "C:\Users\David Wu\.openclaw\workspace\environments\demo"
& "C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn dashboard.api:app --port 8765 --host 0.0.0.0
