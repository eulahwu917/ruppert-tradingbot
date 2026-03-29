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
from agents.ruppert.data_scientist.logger import log_activity   # noqa: E402

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
    """Log a health check alert via the standard activity logger (ALERT_CANDIDATE)."""
    try:
        log_activity(f"[ALERT_CANDIDATE] [HealthCheck] {message}")
    except Exception as e:
        logger.error(f"Failed to push alert: {e}")


def check_nws(results: dict):
    """Check NWS API reachable and temp in seasonal range for Miami."""
    try:
        r = requests.get(
            "https://api.weather.gov/gridpoints/MFL/106,51/forecast",
            timeout=10, headers={"User-Agent": "ruppert-healthcheck"}
        )
        if r.status_code != 200:
            _push_alert(f"NWS API returned {r.status_code}")
            results["nws"] = "warn"
            return
        periods = r.json().get("properties", {}).get("periods", [])
        if not periods:
            _push_alert("NWS returned empty forecast periods")
            results["nws"] = "warn"
            return
        temp = periods[0].get("temperature", 0)
        month = datetime.now().month
        lo, hi = _TEMP_BOUNDS.get(month, (0, 130))
        if not (lo <= temp <= hi):
            _push_alert(f"NWS Miami temp {temp}F out of seasonal range ({lo}-{hi}F)")
            results["nws"] = "warn"
        else:
            results["nws"] = "ok"
    except Exception as e:
        _push_alert(f"NWS check failed: {e}")
        results["nws"] = "fail"


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


def check_fred(results: dict):
    """Check FRED DFEDTARU returns a sensible rate."""
    try:
        r = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU", timeout=10
        )
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        rate = float(lines[-1].split(",")[1])
        if not (0.0 <= rate <= 20.0):
            _push_alert(f"FRED rate anomaly: {rate}%")
            results["fred"] = "warn"
        else:
            results["fred"] = "ok"
    except Exception as e:
        _push_alert(f"FRED check failed: {e}")
        results["fred"] = "fail"


def check_cme(results: dict):
    """Check CME OAuth token is still valid."""
    try:
        from fed_client import _get_cme_oauth_token
        token = _get_cme_oauth_token()
        if not token:
            _push_alert("CME OAuth token unavailable")
            results["cme"] = "warn"
        else:
            results["cme"] = "ok"
    except Exception as e:
        _push_alert(f"CME check failed: {e}")
        results["cme"] = "fail"


def check_openmeteo(results: dict):
    """Check Open-Meteo ensemble returns members for Miami."""
    try:
        r = requests.get(
            "https://ensemble-api.open-meteo.com/v1/ensemble",
            params={
                "latitude": 25.7959, "longitude": -80.2870,
                "hourly": "temperature_2m",
                "models": "ecmwf_ifs025",
                "forecast_days": 2,
                "temperature_unit": "fahrenheit",
            },
            timeout=15,
        )
        r.raise_for_status()
        member_keys = [k for k in r.json().get("hourly", {}) if "member" in k]
        if len(member_keys) < 10:
            _push_alert(f"Open-Meteo returned only {len(member_keys)} ensemble members (expected 50+)")
            results["openmeteo"] = "warn"
        else:
            results["openmeteo"] = "ok"
    except Exception as e:
        _push_alert(f"Open-Meteo check failed: {e}")
        results["openmeteo"] = "fail"


def check_capital(results: dict):
    """Check capital.py returns a sensible value."""
    try:
        from agents.ruppert.data_scientist.capital import get_capital
        cap = get_capital()
        if cap < 100:
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

    check_nws(results)
    check_kraken(results)
    check_fred(results)
    check_cme(results)
    check_openmeteo(results)
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
