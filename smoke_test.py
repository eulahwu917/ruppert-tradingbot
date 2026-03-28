"""
Smoke test — validates all recent implementations without hitting live APIs.
Run: python smoke_test.py
"""
import sys
import os
import json
import traceback
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASS = []
FAIL = []
WARN = []

def ok(label, note=""):
    PASS.append(f"  PASS  {label}" + (f" -- {note}" if note else ""))

def fail(label, note=""):
    FAIL.append(f"  FAIL  {label}" + (f" -- {note}" if note else ""))

def warn(label, note=""):
    WARN.append(f"  WARN  {label}" + (f" -- {note}" if note else ""))

def try_import(module, label=None):
    label = label or module
    try:
        __import__(module)
        ok(f"import {label}")
        return True
    except Exception as e:
        fail(f"import {label}", str(e))
        return False

# ─── 1. Core deps ─────────────────────────────────────────────────────────────
print("\n[1] Core dependencies")
try:
    import websockets
    ok("websockets", f"v{websockets.__version__}")
except ImportError:
    fail("websockets", "pip install websockets>=12.0")

try:
    import cryptography
    ok("cryptography")
except ImportError:
    fail("cryptography")

# ─── 2. Config ────────────────────────────────────────────────────────────────
print("[2] Config")
try:
    import config
    ok("config import")
    dry = getattr(config, 'DRY_RUN', None)
    ok("DRY_RUN", f"={dry}")
    env = getattr(config, 'get_environment', lambda: 'unknown')()
    ok("environment", env)
except Exception as e:
    fail("config", str(e))

# ─── 3. WebSocket layer ───────────────────────────────────────────────────────
print("[3] WebSocket layer (ws/)")
try:
    from ws.connection import KalshiWebSocket
    ok("ws.connection import")

    # Instantiation check (no network call)
    try:
        ws = KalshiWebSocket(
            api_key_id="test-key",
            private_key_path="secrets/kalshi_config.json",  # won't read until connect()
            environment="demo",
        )
        ok("KalshiWebSocket instantiation")
        ok("WS URL", ws.url)
    except Exception as e:
        fail("KalshiWebSocket instantiation", str(e))
except Exception as e:
    fail("ws.connection import", str(e))

try:
    import ws as ws_pkg
    ok("ws package __init__")
except Exception as e:
    fail("ws package __init__", str(e))

# ─── 4. position_monitor.py ───────────────────────────────────────────────────
print("[4] position_monitor.py")
try:
    # Import without running __main__
    import importlib.util
    spec = importlib.util.spec_from_file_location("position_monitor", ROOT / "position_monitor.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    ok("position_monitor import")

    ok("WS_ENABLED flag", str(getattr(pm, 'WS_ENABLED', 'MISSING')))
    ok("WS_EVENT_LOOP_DURATION", str(getattr(pm, 'WS_EVENT_LOOP_DURATION', 'MISSING')))
    ok("POLL_BACKSTOP_INTERVAL", str(getattr(pm, 'POLL_BACKSTOP_INTERVAL', 'MISSING')))
    ok("DRY_RUN from config", str(pm.DRY_RUN))

    # Check delegation imports work
    try:
        from post_trade_monitor import run_monitor, check_settlements, check_weather_position, check_crypto_position
        ok("post_trade_monitor delegation imports")
    except Exception as e:
        fail("post_trade_monitor delegation imports", str(e))

except Exception as e:
    fail("position_monitor import", str(e))
    traceback.print_exc()

# ─── 5. post_trade_monitor.py (95c/70% exit logic) ───────────────────────────
print("[5] post_trade_monitor.py — exit thresholds")
try:
    src = (ROOT / "post_trade_monitor.py").read_text(encoding="utf-8")
    if "95" in src and "0.70" in src:
        ok("95c + 70% thresholds present")
    else:
        fail("exit thresholds", "95c or 70% not found")

    # Check settle consistency
    import re
    # Look for spots that only check 'exit' without 'settle'
    bare_exit = re.findall(r"action\s*==\s*['\"]exit['\"]", src)
    settle_aware = re.findall(r"action\s*in\s*\(['\"]exit['\"].*settle|settle.*exit", src)
    if bare_exit and not settle_aware:
        fail("settle consistency in post_trade_monitor", f"{len(bare_exit)} bare 'exit' checks found")
    else:
        ok("settle consistency in post_trade_monitor")

except Exception as e:
    fail("post_trade_monitor checks", str(e))

# ─── 6. logger.py — settle consistency + tmp cleanup ─────────────────────────
print("[6] logger.py")
try:
    src = (ROOT / "logger.py").read_text(encoding="utf-8")
    if "settle" in src and "exit" in src:
        ok("settle+exit both referenced in logger.py")
    else:
        warn("settle not found in logger.py")

    # tmp cleanup lives in the monitor files, not logger.py — check there
    monitor_files = ["post_trade_monitor.py", "position_monitor.py"]
    found_unlink = any(
        ("unlink" in (ROOT / f).read_text(encoding="utf-8") or "missing_ok" in (ROOT / f).read_text(encoding="utf-8"))
        for f in monitor_files if (ROOT / f).exists()
    )
    if found_unlink:
        ok("tmp cleanup (unlink) present in monitor files")
    else:
        fail("tmp cleanup (unlink) not found in post_trade_monitor or position_monitor")
except Exception as e:
    fail("logger.py checks", str(e))

# ─── 7. edge_detector.py — dead code removed ─────────────────────────────────
print("[7] edge_detector.py — dead code")
try:
    src = (ROOT / "edge_detector.py").read_text(encoding="utf-8")
    if "model_prob_for_edge" in src:
        fail("model_prob_for_edge still present in edge_detector.py", "dead code not removed")
    else:
        ok("model_prob_for_edge removed")
except Exception as e:
    fail("edge_detector.py read", str(e))

# ─── 8. daily_progress_report.py — settle consistency ────────────────────────
print("[8] daily_progress_report.py")
try:
    src = (ROOT / "daily_progress_report.py").read_text(encoding="utf-8")
    bare = len(re.findall(r"action\s*==\s*['\"]exit['\"]", src))
    if bare:
        fail("settle consistency in daily_progress_report", f"{bare} bare 'exit' checks")
    else:
        ok("settle consistency in daily_progress_report")
except Exception as e:
    fail("daily_progress_report.py checks", str(e))

# ─── 9. ruppert_cycle.py — settle consistency ────────────────────────────────
print("[9] ruppert_cycle.py")
try:
    src = (ROOT / "ruppert_cycle.py").read_text(encoding="utf-8")
    bare = len(re.findall(r"action\s*==\s*['\"]exit['\"]", src))
    if bare:
        fail("settle consistency in ruppert_cycle", f"{bare} bare 'exit' checks")
    else:
        ok("settle consistency in ruppert_cycle")
except Exception as e:
    fail("ruppert_cycle.py checks", str(e))

# ─── 10. kalshi_client basic import ──────────────────────────────────────────
print("[10] kalshi_client")
try:
    from kalshi_client import KalshiClient
    ok("KalshiClient import")
except Exception as e:
    fail("KalshiClient import", str(e))

# ─── Summary ─────────────────────────────────────────────────────────────────
print()
print("=" * 60)
total = len(PASS) + len(FAIL)
if FAIL:
    print(f"SMOKE TEST FAIL -- {len(FAIL)} failure(s), {len(PASS)}/{total} passed")
else:
    print(f"SMOKE TEST PASS -- {len(PASS)}/{total} checks passed")
print("=" * 60)
for line in PASS:
    print(line)
for line in FAIL:
    print(line)
for line in WARN:
    print(line)
print()
sys.exit(1 if FAIL else 0)
