# Developer Fixes — 2026-03-11
**SA-3 Developer** | All 10 must-fix issues + 4 impactful warnings resolved.
**Status:** All files staged with `git add`. Awaiting CEO review before commit/push.

---

## Must-Fix Issues (10/10 resolved)

### Issue 1 — ruppert_cycle.py: ImportError `scan_weather`
- **File:** `ruppert_cycle.py` line ~208
- **Fix:** Changed `from main import scan_weather` → `from main import run_weather_scan`; updated call to `run_weather_scan(dry_run=DRY_RUN)`.
- **Result:** Step 3 (weather scan) no longer crashes on every full-mode run.

### Issue 2 — ruppert_cycle.py: TypeError in weather position check
- **File:** `ruppert_cycle.py` lines ~76–147
- **Fix:**
  - Replaced `from edge_detector import detect_edge` with `from edge_detector import parse_date_from_ticker, parse_threshold_from_ticker`
  - Replaced `sig = get_full_weather_signal(city)` with correct 3-arg call:
    - `series_ticker = ticker.split('-')[0].upper()` (e.g. `KXHIGHMIA`)
    - `threshold_f = parse_threshold_from_ticker(ticker)` (e.g. `85.5`)
    - `target_date = parse_date_from_ticker(ticker)` (e.g. `date(2026,3,12)`)
    - `sig = get_full_weather_signal(series_ticker, threshold_f, target_date)`
  - Updated field access from incorrect `sig.get('tomorrow_high_f')` / `sig.get('ensemble_prob')` to correct `sig.get('conditions', {}).get('tomorrow_high_f')` / `sig.get('final_prob')`.
  - Removed dead city_map lookup (was entirely wrong approach).
- **Result:** Weather position checks now run without TypeError; exit alerts and auto-exits are functional.

### Issue 3 — dashboard/api.py: NameError `BASE_DIR` in HC endpoints
- **File:** `dashboard/api.py` — `approve_highconviction` and `pass_highconviction`
- **Fix:** Replaced `BASE_DIR / 'logs' / 'highconviction_approved.jsonl'` → `LOGS_DIR / 'highconviction_approved.jsonl'`; same for `highconviction_passed.jsonl`.
- **Result:** HC approve/pass endpoints no longer throw `NameError` on every call.

### Issue 4 — Wrong strptime format `"%Y%d%b%d"` in 2 files
- **Files:** `edge_detector.py` (line 114), `main.py` (line 150)
- **Fix:** Changed `"%Y%d%b%d"` → `"%Y%b%d"` in both locations.
- **Note:** QA report cited `ruppert_cycle.py` as a third location but `strptime` is not present there — confirmed by search. Only 2 files affected.
- **Result:** `parse_date_from_ticker()` now correctly parses `26MAR11` → `date(2026, 3, 11)`. `run_exit_scan()` near-settlement logic now fires correctly.

### Issue 5 — ruppert_cycle.py: No daily cap check on crypto trades
- **File:** `ruppert_cycle.py`
- **Fix:**
  - Added `from bot.strategy import check_daily_cap` to top-level imports.
  - Added `get_daily_exposure` to logger import.
  - Added cap check block before `for t in new_crypto[:3]:` loop — computes `_deployed_today`, calls `check_daily_cap()`, skips all crypto trades and prints a clear message if cap is reached.
- **Result:** Crypto trades now respect the 70% daily cap. Cannot over-deploy if weather scan already consumed most of the budget.

### Issue 6 — logger.py: Missing `encoding='utf-8'` on all 5 file opens
- **File:** `logger.py`
- **Fix:** Added `encoding='utf-8'` to:
  - `log_trade()` — `open(_today_log_path(), 'a', ...)`
  - `log_opportunity()` — `open(_activity_log_path(), 'a', ...)`
  - `log_activity()` — `open(_activity_log_path(), 'a', ...)`
  - `get_daily_exposure()` — `open(log_path, 'r', ...)`
  - `get_daily_summary()` — `open(log_path, 'r', ...)`
- **Result:** All logger file operations now safe on Windows (no cp1252 corruption risk).

### Issue 7 — config.py, kalshi_client.py: Missing `encoding='utf-8'`
- **Files:** `config.py`, `kalshi_client.py`
- **Fix:** Added `encoding='utf-8'` to:
  - `config.py` `load_config()` — `open(CONFIG_FILE, 'r', ...)`
  - `kalshi_client.py` `__init__` — `open(self.private_key_path, 'r', ...)`
- **Result:** Credential and private key files always read with correct encoding on Windows.

### Issue 8 — dashboard/api.py: Missing `encoding='utf-8'` in 3 file opens
- **File:** `dashboard/api.py`
- **Fix:** Added `encoding='utf-8'` to:
  - `read_today_trades()` — `open(log_path, ...)`
  - `get_deposits()` — `open(deposits_path, ...)`
  - `add_deposit()` — `open(deposits_path, 'a', ...)`
- **Result:** Dashboard file reads safe on Windows.

### Issue 9 — index.html: `api()` helper ignores fetch options; mode toggle broken
- **File:** `dashboard/templates/index.html` line 453
- **Fix:** Changed:
  - `async function api(url) {` → `async function api(url, opts={}) {`
  - `fetch(url)` → `fetch(url, opts)`
- **Result:** `switchMode()` POST request now reaches the server correctly. Mode toggle functional.

### Issue 10 — index.html: `openGeoSidebar()` references undefined `b.ticker`
- **File:** `dashboard/templates/index.html` lines 987–990 (inside `openGeoSidebar(m)`)
- **Fix:** Replaced all 4 `b.ticker` references with `m.ticker` in the action button onclick handlers. Also removed the erroneous trailing `>` after the Pass button.
- **Result:** YES/NO/Watch/Pass buttons in the Geo sidebar no longer throw `ReferenceError` when clicked.

---

## Warnings Fixed (4/4)

### W5 — crypto_scanner.py / dashboard/api.py: Cache file name mismatch
- **File:** `dashboard/api.py` `get_crypto_scan()`
- **Fix:** Changed `scan_cache = LOGS_DIR / "crypto_scan.jsonl"` → `LOGS_DIR / "crypto_scan_latest.json"`. Updated read logic from JSONL line-by-line to `json.load()` + `data.get('opportunities', [])` to match the JSON format that `crypto_scanner.py` actually writes.
- **Result:** Dashboard crypto scan panel now finds and displays cached edge analysis results from the scanner.

### W8 — dashboard/api.py get_summary(): Hardcoded "DRY RUN"
- **File:** `dashboard/api.py` `get_summary()`
- **Fix:** Changed `"mode": "DRY RUN"` → `"mode": get_mode().upper()` (returns `"DEMO"` or `"LIVE"` from mode.json).
- **Result:** Summary endpoint reflects actual operating mode. Will show `"LIVE"` when live mode is active.

### W11 — position_monitor.py: DST offset wrong (-5 → -4)
- **File:** `bot/position_monitor.py` `check_near_settlement()`
- **Fix:** Changed `timedelta(hours=5)` → `timedelta(hours=4)`. Updated comment to reflect EDT (UTC-4, March–November).
- **Result:** Near-settlement detection now accurate during EDT season. 30-minute hold window fires correctly.

### W14 — main.py: `deployed_today` not refreshed between trades
- **File:** `main.py` `run_weather_scan()`
- **Fix:** Added `deployed_today += decision['size']` immediately after each approved opportunity in the loop, so subsequent iterations see the running total.
- **Result:** If 3 weather trades fire in one scan, the 2nd and 3rd trades see the reduced remaining cap from the trades before them, preventing potential over-deployment.

---

## Files Changed (9 total)

| File | Issues Fixed |
|------|-------------|
| `ruppert_cycle.py` | Issues 1, 2, 5 |
| `edge_detector.py` | Issue 4 |
| `main.py` | Issue 4, W14 |
| `logger.py` | Issue 6 |
| `config.py` | Issue 7 |
| `kalshi_client.py` | Issue 7 |
| `dashboard/api.py` | Issues 3, 8, W5, W8 |
| `dashboard/templates/index.html` | Issues 9, 10 |
| `bot/position_monitor.py` | W11 |

---

## Notes for CEO Review

- **Issue 4 clarification:** QA report listed `ruppert_cycle.py` as a third location for the `%Y%d%b%d` format bug, but confirmed by search it doesn't exist there. Fixed in the 2 confirmed locations only.
- **Issue 2 field mapping:** `get_full_weather_signal()` returns `conditions.tomorrow_high_f` (not a top-level `tomorrow_high_f` key) and `final_prob` (not `ensemble_prob`). Updated Step 1 position check to use correct field paths. Logic is preserved — same alert/exit thresholds, just correct data access.
- **W5 format change:** The crypto scanner writes JSON (single object with `scan_time` + `opportunities` array), not JSONL. The dashboard code was looking for JSONL by both filename and parse strategy. Fixed both — no format changes made to the scanner output itself.
- **No trading thresholds changed.** All strategy parameters intact.
- **No live trading enabled.** `DRY_RUN = True` and `is_live = False` untouched.
