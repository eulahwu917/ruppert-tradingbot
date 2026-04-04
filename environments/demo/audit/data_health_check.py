"""
Daily Data Health Check — QA-owned pre-scan validation.

Runs at 6:45am daily via Task Scheduler, before the 7am trading cycle.
Validates all data sources are returning sensible values.
Flags anomalies to pending_alerts.json (heartbeat forwards to David).

QA agent owns this script — runs weekly manual check, reviews output.

Usage: python data_health_check.py
"""

import json
import logging
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path

# Resolve workspace root for env_config import
_AUDIT_DIR      = Path(__file__).parent
_DEMO_DIR       = _AUDIT_DIR.parent
_WORKSPACE_ROOT = _DEMO_DIR.parent.parent  # audit -> demo -> environments -> workspace
for _p in (_WORKSPACE_ROOT, _DEMO_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agents.ruppert.env_config import get_paths as _get_paths  # noqa: E402
import config  # noqa: E402  (_DEMO_DIR already on sys.path above)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_LOGS_DIR = _get_paths()['logs']

# Seasonal temp bounds per month (rough sanity — not precise)
_TEMP_BOUNDS = {
    1:  (0,  80),   # Jan
    2:  (0,  85),
    3:  (10, 95),
    4:  (20, 105),
    5:  (30, 110),
    6:  (40, 115),
    7:  (45, 120),
    8:  (45, 120),
    9:  (35, 110),
    10: (20, 105),
    11: (5,  95),
    12: (0,  85),   # Dec
}


def _push_alert(message: str):
    """Write health check alert directly to pending_alerts.json."""
    alert = {
        "level": "warning",
        "message": message,
        "source": "data_health_check",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    alerts_path = _LOGS_DIR / "truth" / "pending_alerts.json"
    try:
        import portalocker
        with open(alerts_path, 'r+', encoding='utf-8') as f:
            portalocker.lock(f, portalocker.LOCK_EX)
            try:
                try:
                    existing = json.loads(f.read())
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
                existing.append(alert)
                f.seek(0)
                f.truncate()
                f.write(json.dumps(existing, indent=2))
            finally:
                portalocker.unlock(f)
    except ImportError:
        # portalocker not installed — best-effort write without file lock
        try:
            existing = json.loads(alerts_path.read_text(encoding='utf-8')) if alerts_path.exists() else []
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        existing.append(alert)
        alerts_path.parent.mkdir(parents=True, exist_ok=True)
        alerts_path.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    except FileNotFoundError:
        # File doesn't exist yet — create it
        alerts_path.parent.mkdir(parents=True, exist_ok=True)
        alerts_path.write_text(json.dumps([alert], indent=2), encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to push alert to pending_alerts.json: {e}")



def check_kraken(results: dict):
    """Check Kraken API reachable and BTC price sensible."""
    try:
        r = requests.get(
            "https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=8
        )
        r.raise_for_status()
        btc = float(list(r.json()["result"].values())[0]["c"][0])
        if not (1000 < btc < 10_000_000):
            _push_alert(f"Kraken BTC price anomaly: ${btc:,.0f}")
            results["kraken"] = "warn"
        else:
            results["kraken"] = "ok"
    except Exception as e:
        _push_alert(f"Kraken check failed: {e}")
        results["kraken"] = "fail"



def check_capital(results: dict):
    """Check capital.py returns a sensible value."""
    try:
        from agents.ruppert.data_scientist.capital import get_capital
        cap = get_capital()
        if cap < config.MIN_CAPITAL_ALERT:
            _push_alert(f"Capital anomaly: ${cap:.2f} (too low)")
            results["capital"] = "warn"
        else:
            results["capital"] = "ok"
    except Exception as e:
        _push_alert(f"Capital check failed: {e}")
        results["capital"] = "fail"


def main():
    logger.info("=== Daily Data Health Check starting ===")
    results = {}

    check_kraken(results)
    check_capital(results)

    # Summary
    passed  = sum(1 for v in results.values() if v == "ok")
    warned  = sum(1 for v in results.values() if v == "warn")
    failed  = sum(1 for v in results.values() if v == "fail")
    total   = len(results)

    logger.info(f"Health check complete: {passed}/{total} OK, {warned} warnings, {failed} failures")
    for src, status in results.items():
        icon = "OK" if status == "ok" else "WARN" if status == "warn" else "FAIL"
        logger.info(f"  {src:15} {icon}")

    if warned + failed > 0:
        logger.warning(f"{warned + failed} issue(s) flagged to pending_alerts.json")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
