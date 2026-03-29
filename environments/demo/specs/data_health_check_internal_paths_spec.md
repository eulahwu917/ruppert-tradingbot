# Dev Spec: Internal Data Path Contracts — `data_health_check.py`

**Spec ID:** DHC-002  
**Author:** Data Scientist (Ruppert)  
**Date:** 2026-03-28  
**Status:** Ready for Dev  
**Priority:** High — this is the class of bug that allowed the trades path issue to go undetected

---

## 1. Problem

`data_health_check.py` currently validates only **external APIs** (NWS, Kraken, FRED, CME, Open-Meteo, Capital). It never checks that the **internal file path contracts** between `logger.py` (writer) and `dashboard/api.py` (reader) are intact.

The trades path bug went undetected because no automated check confirmed that:
- The `trades/` directory existed at the path the dashboard actually reads
- The files in it were parseable JSON
- The supporting truth files existed and had expected structure

This spec defines exactly what to add to close that blind spot.

---

## 2. What to Add

Two new check functions, called sequentially in `main()` after the existing checks:

1. **`check_internal_paths(results)`** — validates on-disk file/directory contracts
2. **`check_dashboard_reachable(results)`** — validates the FastAPI dashboard is up and serving

---

## 3. Where in the File

### 3a. New functions — insert **before `main()`**

Place both new functions immediately before the `def main():` definition, after `check_capital()`. This maintains the existing top-to-bottom ordering: external checks → internal checks → dashboard check → main.

### 3b. New calls — inside `main()`, **after `check_capital(results)`**

```python
check_internal_paths(results)
check_dashboard_reachable(results)
```

---

## 4. Exact Logic — `check_internal_paths(results)`

```python
def check_internal_paths(results: dict):
    """Validate internal data path contracts (logger → dashboard)."""
    paths = _get_paths()
    trades_dir  = paths['trades']          # logs/trades/
    truth_dir   = paths['truth']           # logs/truth/
    logs_dir    = paths['logs']            # logs/

    # --- Check 1: logs/trades/ directory exists ---
    if not trades_dir.is_dir():
        _push_alert(f"Internal path missing: trades dir not found at {trades_dir}")
        results["internal_trades_dir"] = "fail"
    else:
        results["internal_trades_dir"] = "ok"

    # --- Check 2: At least one trades_*.jsonl file exists ---
    trade_files = sorted(trades_dir.glob("trades_*.jsonl")) if trades_dir.is_dir() else []
    if not trade_files:
        _push_alert(f"No trades_*.jsonl files found in {trades_dir}")
        results["internal_trades_files"] = "fail"
    else:
        results["internal_trades_files"] = "ok"

    # --- Check 3: Latest trades_*.jsonl has at least one parseable line ---
    if trade_files:
        latest = trade_files[-1]
        parsed_ok = False
        try:
            with open(latest, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                        parsed_ok = True
                        break
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            _push_alert(f"Could not read latest trades file {latest.name}: {e}")
            results["internal_trades_parseable"] = "fail"
        else:
            if not parsed_ok:
                _push_alert(f"Latest trades file {latest.name} has no parseable JSON lines")
                results["internal_trades_parseable"] = "warn"
            else:
                results["internal_trades_parseable"] = "ok"
    else:
        # Already failed above; skip parse check
        results["internal_trades_parseable"] = "fail"

    # --- Check 4: logs/truth/pnl_cache.json exists and has 'closed_pnl' key ---
    pnl_cache = truth_dir / "pnl_cache.json"
    if not pnl_cache.exists():
        _push_alert(f"Internal path missing: {pnl_cache}")
        results["internal_pnl_cache"] = "fail"
    else:
        try:
            data = json.loads(pnl_cache.read_text(encoding="utf-8"))
            if "closed_pnl" not in data:
                _push_alert(f"pnl_cache.json missing 'closed_pnl' key (found: {list(data.keys())})")
                results["internal_pnl_cache"] = "fail"
            else:
                results["internal_pnl_cache"] = "ok"
        except json.JSONDecodeError as e:
            _push_alert(f"pnl_cache.json is not valid JSON: {e}")
            results["internal_pnl_cache"] = "fail"

    # --- Check 5: logs/truth/crypto_smart_money.json exists (WARN only if missing) ---
    smart_money = truth_dir / "crypto_smart_money.json"
    if not smart_money.exists():
        logger.warning("crypto_smart_money.json not found — may be absent early in session (non-fatal)")
        results["internal_smart_money"] = "warn"
    else:
        try:
            json.loads(smart_money.read_text(encoding="utf-8"))
            results["internal_smart_money"] = "ok"
        except json.JSONDecodeError as e:
            _push_alert(f"crypto_smart_money.json is not valid JSON: {e}")
            results["internal_smart_money"] = "fail"

    # --- Check 6: logs/cycle_log.jsonl exists and last entry is parseable ---
    cycle_log = logs_dir / "cycle_log.jsonl"
    if not cycle_log.exists():
        _push_alert(f"Internal path missing: {cycle_log}")
        results["internal_cycle_log"] = "fail"
    else:
        try:
            lines = [l.strip() for l in cycle_log.read_text(encoding="utf-8").splitlines() if l.strip()]
            if not lines:
                _push_alert("cycle_log.jsonl exists but is empty")
                results["internal_cycle_log"] = "warn"
            else:
                json.loads(lines[-1])   # parse the last line only
                results["internal_cycle_log"] = "ok"
        except json.JSONDecodeError as e:
            _push_alert(f"cycle_log.jsonl last line is not valid JSON: {e}")
            results["internal_cycle_log"] = "fail"
        except Exception as e:
            _push_alert(f"cycle_log.jsonl read failed: {e}")
            results["internal_cycle_log"] = "fail"
```

**Key decisions:**
- `crypto_smart_money.json` uses `"warn"` (not `"fail"`) on absence — it may legitimately not exist early in a session.
- Parse checks read only the **minimum necessary** (first valid line for trades, last line for cycle_log) — avoids loading large files.
- All path variables derive from `_get_paths()` (already in scope at module level as `_LOGS_DIR`). The function calls `_get_paths()` internally to access `trades`, `truth`, and `logs` sub-paths which are not separately aliased at module level.

---

## 5. Exact Logic — `check_dashboard_reachable(results)`

```python
def check_dashboard_reachable(results: dict):
    """Check that the FastAPI dashboard is up and serving expected endpoints."""
    base = "http://localhost:8765"

    # --- Check 7: /api/trades returns 200 with non-empty body ---
    try:
        r = requests.get(f"{base}/api/trades", timeout=5)
        if r.status_code != 200:
            _push_alert(f"Dashboard /api/trades returned HTTP {r.status_code}")
            results["dashboard_trades"] = "fail"
        elif not r.text.strip():
            _push_alert("Dashboard /api/trades returned 200 but empty body")
            results["dashboard_trades"] = "warn"
        else:
            results["dashboard_trades"] = "ok"
    except requests.exceptions.ConnectionError:
        _push_alert("Dashboard not reachable at localhost:8765 (connection refused)")
        results["dashboard_trades"] = "fail"
    except Exception as e:
        _push_alert(f"Dashboard /api/trades check failed: {e}")
        results["dashboard_trades"] = "fail"

    # --- Check 8: /docs returns 200 ---
    try:
        r = requests.get(f"{base}/docs", timeout=5)
        if r.status_code != 200:
            _push_alert(f"Dashboard /docs returned HTTP {r.status_code}")
            results["dashboard_docs"] = "fail"
        else:
            results["dashboard_docs"] = "ok"
    except requests.exceptions.ConnectionError:
        # Already alerted above if /api/trades also failed; avoid duplicate
        results["dashboard_docs"] = "fail"
    except Exception as e:
        _push_alert(f"Dashboard /docs check failed: {e}")
        results["dashboard_docs"] = "fail"
```

**Key decisions:**
- `timeout=5` (shorter than external API timeouts — localhost should respond immediately).
- Connection refused → `"fail"`, not `"warn"`. Dashboard down is a hard failure.
- Non-empty body check on `/api/trades` because an empty `[]` body in JSON still parses — `r.text.strip()` being empty would indicate a broken response, not an empty trade list. Note: an empty JSON array `"[]"` is non-empty text and is acceptable.

---

## 6. Updated `main()` call block

The existing `main()` call block currently reads:

```python
check_nws(results)
check_kraken(results)
check_fred(results)
check_cme(results)
check_openmeteo(results)
check_capital(results)
```

Change to:

```python
check_nws(results)
check_kraken(results)
check_fred(results)
check_cme(results)
check_openmeteo(results)
check_capital(results)

# --- Internal path contract validation ---
check_internal_paths(results)
check_dashboard_reachable(results)
```

No other changes to `main()` needed — the summary loop already iterates `results.items()` dynamically, so the new keys are automatically included in the pass/warn/fail totals and the per-source log table.

---

## 7. Result Key Summary

| `results` key                  | Source check                                       | Fail = block scan? |
|-------------------------------|----------------------------------------------------|--------------------|
| `internal_trades_dir`         | `logs/trades/` directory exists                    | Yes                |
| `internal_trades_files`       | At least one `trades_*.jsonl` present              | Yes                |
| `internal_trades_parseable`   | Latest `trades_*.jsonl` has ≥1 valid JSON line     | Yes                |
| `internal_pnl_cache`          | `pnl_cache.json` exists + has `closed_pnl`         | Yes                |
| `internal_smart_money`        | `crypto_smart_money.json` exists (warn if absent)  | No (warn only)     |
| `internal_cycle_log`          | `cycle_log.jsonl` exists + last line parseable     | Yes                |
| `dashboard_trades`            | `GET /api/trades` → 200, non-empty body            | Yes                |
| `dashboard_docs`              | `GET /docs` → 200                                  | Yes                |

---

## 8. QA Criteria — What a Passing Run Looks Like

A clean passing run should log the following (timestamps will vary):

```
2026-03-28 06:45:01 INFO === Daily Data Health Check starting ===
2026-03-28 06:45:02 INFO   nws             OK
2026-03-28 06:45:02 INFO   kraken          OK
2026-03-28 06:45:03 INFO   fred            OK
2026-03-28 06:45:03 INFO   cme             OK
2026-03-28 06:45:04 INFO   openmeteo       OK
2026-03-28 06:45:04 INFO   capital         OK
2026-03-28 06:45:04 INFO   internal_trades_dir        OK
2026-03-28 06:45:04 INFO   internal_trades_files      OK
2026-03-28 06:45:04 INFO   internal_trades_parseable  OK
2026-03-28 06:45:04 INFO   internal_pnl_cache         OK
2026-03-28 06:45:04 INFO   internal_smart_money       OK   ← or WARN if file absent (acceptable)
2026-03-28 06:45:04 INFO   internal_cycle_log         OK
2026-03-28 06:45:05 INFO   dashboard_trades           OK
2026-03-28 06:45:05 INFO   dashboard_docs             OK
2026-03-28 06:45:05 INFO Health check complete: 14/14 OK, 0 warnings, 0 failures
```

Or with acceptable warn (smart_money absent):
```
2026-03-28 06:45:05 INFO Health check complete: 13/14 OK, 1 warnings, 0 failures
```

**Exit code:** `0` on zero failures (warns are allowed). `1` if any check returns `"fail"`.

---

## 9. Failure Scenarios (QA Regression Table)

| Scenario to simulate                        | Expected result key              | Expected status |
|--------------------------------------------|----------------------------------|-----------------|
| Delete `logs/trades/` directory             | `internal_trades_dir`            | `fail`          |
| Empty `logs/trades/` directory              | `internal_trades_files`          | `fail`          |
| Corrupt last trades file (write `???`)     | `internal_trades_parseable`      | `fail`          |
| Delete `pnl_cache.json`                     | `internal_pnl_cache`             | `fail`          |
| Remove `closed_pnl` key from pnl_cache.json | `internal_pnl_cache`            | `fail`          |
| Delete `crypto_smart_money.json`            | `internal_smart_money`           | `warn`          |
| Delete `cycle_log.jsonl`                    | `internal_cycle_log`             | `fail`          |
| Write non-JSON last line to cycle_log       | `internal_cycle_log`             | `fail`          |
| Kill the dashboard process                  | `dashboard_trades`               | `fail`          |
| Dashboard up but `/api/trades` broken       | `dashboard_trades`               | `fail`          |

---

## 10. No New Dependencies

All logic uses only modules already imported at the top of `data_health_check.py`:
- `json` (stdlib)
- `pathlib.Path` (stdlib)
- `requests` (already imported)
- `_get_paths` (already imported as `from agents.ruppert.env_config import get_paths as _get_paths`)
- `_push_alert`, `logger` (already in scope)

No new imports required.

---

## 11. Out of Scope (Do Not Do)

- Do NOT modify `logger.py`, `dashboard/api.py`, or any other agent file
- Do NOT add a database or structured output format — `pending_alerts.json` via `_push_alert` is sufficient
- Do NOT add retry logic — health check is a point-in-time snapshot; one attempt per check is correct
- Do NOT add the new checks to cron separately — they run as part of the existing 6:45am Task Scheduler job
