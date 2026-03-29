"""
ws_feed_watchdog.py — Watchdog for ws_feed.py
Checks every 5 minutes. Restarts if:
  1. Process is not running
  2. Process is hung (no heartbeat in 10 min)

Run via Task Scheduler at system startup.
Environment: set RUPPERT_ENV=demo (or live) in Task Scheduler task.
"""

import subprocess
import sys
import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

# Config
CHECK_INTERVAL_SECONDS = 300   # 5 minutes
HEARTBEAT_STALE_SECONDS = 600  # 10 minutes — if no heartbeat, assume hung

# Environment
WORKSPACE_ROOT = Path(os.environ.get(
    'OPENCLAW_WORKSPACE',
    Path.home() / '.openclaw' / 'workspace'
))

PYTHON_EXE = r'C:\Users\David Wu\AppData\Local\Programs\Python\Python312\python.exe'


def get_env():
    return os.environ.get('RUPPERT_ENV', 'demo')


def get_env_root():
    return WORKSPACE_ROOT / 'environments' / get_env()


def get_heartbeat_file():
    return get_env_root() / 'logs' / 'ws_feed_heartbeat.json'


def get_ws_feed_script():
    # ws_feed.py is in the environment root (runs as -m agents.data_analyst.ws_feed)
    return get_env_root()


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[Watchdog {ts}] {msg}", flush=True)

    # Also write to log file
    log_file = get_env_root() / 'logs' / 'watchdog.log'
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def is_heartbeat_fresh() -> bool:
    """Check if ws_feed.py has written a recent heartbeat."""
    hb_file = get_heartbeat_file()
    if not hb_file.exists():
        return False

    try:
        data = json.loads(hb_file.read_text(encoding='utf-8'))
        last_ts = data.get('last_heartbeat')
        if not last_ts:
            return False

        last_dt = datetime.fromisoformat(last_ts)
        stale_threshold = datetime.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
        return last_dt > stale_threshold
    except Exception as e:
        log(f"Heartbeat check failed: {e}")
        return False


def start_ws_feed():
    """Start ws_feed.py in a new process via module invocation."""
    env_root = get_env_root()
    env = get_env()

    log(f"Starting ws_feed.py for env={env} from {env_root}")

    # Build environment for subprocess
    proc_env = os.environ.copy()
    proc_env['RUPPERT_ENV'] = env
    proc_env['PYTHONPATH'] = str(WORKSPACE_ROOT)  # P1-2 fix: ensure agents.ruppert.* importable

    # Start detached on Windows
    subprocess.Popen(
        [PYTHON_EXE, '-m', 'agents.ruppert.data_analyst.ws_feed'],  # P1-2 fix: correct module path
        cwd=str(WORKSPACE_ROOT),  # P1-2 fix: run from workspace root so agents.ruppert.* is importable
        env=proc_env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    log("ws_feed.py started")


def run_watchdog():
    """Main watchdog loop."""
    env = get_env()
    log(f"Watchdog starting for environment: {env}")
    log(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
    log(f"Heartbeat stale threshold: {HEARTBEAT_STALE_SECONDS}s")

    while True:
        try:
            if not is_heartbeat_fresh():
                log("Heartbeat stale or missing — ws_feed appears dead")
                time.sleep(2)  # Brief pause before restart
                start_ws_feed()
                log("Restarted ws_feed.py")
            else:
                pass  # ws_feed is alive
        except Exception as e:
            log(f"Watchdog error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == '__main__':
    run_watchdog()
