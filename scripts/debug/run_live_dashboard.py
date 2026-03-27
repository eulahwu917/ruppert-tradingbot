"""
run_live_dashboard.py — Launch script for the LIVE Ruppert Dashboard.

Sets KALSHI_ENV=live, reads config/live_env.json, then starts the LIVE dashboard
API on port 8766 with logs from logs-live/.

DO NOT run this unless you have completed the pre-flight checklist (see PREFLIGHT.md).
"""
import os
import sys
import json
from pathlib import Path

# ── Set LIVE environment variable immediately ───────────────────────────────
os.environ['KALSHI_ENV'] = 'live'

# ── Resolve paths ────────────────────────────────────────────────────────────
BOT_DIR = Path(__file__).parent
CONFIG_PATH = BOT_DIR / 'config' / 'live_env.json'

# ── Read live_env.json ───────────────────────────────────────────────────────
if not CONFIG_PATH.exists():
    print(f"[LIVE] ERROR: {CONFIG_PATH} not found. Cannot start LIVE dashboard.")
    sys.exit(1)

with open(CONFIG_PATH, encoding='utf-8') as f:
    live_cfg = json.load(f)

if live_cfg.get('environment') != 'live':
    print("[LIVE] ERROR: config/live_env.json does not have environment=live. Aborting.")
    sys.exit(1)

PORT = live_cfg.get('dashboard_port', 8766)
LOGS_DIR = live_cfg.get('logs_dir', 'logs-live')

# ── Create logs-live/ if it doesn't exist ───────────────────────────────────
logs_path = BOT_DIR / LOGS_DIR
logs_path.mkdir(exist_ok=True)

print(f"[LIVE] Starting LIVE dashboard on port {PORT}")
print(f"[LIVE] Logs directory: {logs_path}")
print(f"[LIVE] Environment: {live_cfg['environment'].upper()}")
print("[LIVE] ⚠️  REAL ORDERS WILL BE PLACED IF BOT CYCLES ARE ENABLED.")
print()

# ── Launch LIVE dashboard via uvicorn ────────────────────────────────────────
import uvicorn

# Pass LOGS_DIR and PORT via environment so api_live.py can pick them up
os.environ['RUPPERT_LOGS_DIR'] = str(logs_path)
os.environ['RUPPERT_PORT'] = str(PORT)

uvicorn.run(
    "dashboard.api_live:app",
    host="0.0.0.0",
    port=PORT,
    reload=False,
    app_dir=str(BOT_DIR),
)
