# Batch 5 — Data Scientist Specs
**Author:** Data Scientist  
**Date:** 2026-04-04  
**Status:** Draft → Adversarial Review  

These specs are written in plain English for adversarial review before Dev builds anything.

---

## Revision Log

| Rev | Date | Author | Changes |
|-----|------|--------|---------|
| 1.0 | 2026-04-04 | Data Scientist | Initial draft |
| 1.1 | 2026-04-04 | Data Scientist | Adversarial review revisions: added critical site B5-DS-3i (`load_traded_tickers()` in `utils.py` L17, dedup failure → duplicate trade); added explicit naive-tz fallback stub to B5-DS-1; added `exit_records` inline-scope clarification to B5-DS-2; added new-dependency note to B5-DS-4 |

---

## B5-DS-1: `settlement_checker.py` — Naive datetime in `hold_duration_hours` calculation

**File:** `environments/demo/settlement_checker.py`  
**Lines:** ~229–232  

### What the code does now

At line 229–232, the settlement checker computes how long a position was held:

```python
entry_dt = datetime.fromisoformat(
    pos.get('timestamp', '').replace('Z', '+00:00').split('+')[0]
)
hold_hours = round((datetime.now() - entry_dt).total_seconds() / 3600, 2)
```

The `split('+')[0]` strips the timezone offset from the stored timestamp, making `entry_dt` a naive datetime (no timezone info). `datetime.now()` is also naive (local wall clock). Subtraction works but uses local machine time, which may differ from UTC or PDT depending on server timezone. If the server runs in UTC, the result will be correct numerically but accidentally — it has no explicit timezone contract. If the server is ever run in a different timezone, hold durations will be wrong.

### The actual problem

The file already imports `timezone` (line 23: `from datetime import date, datetime, timezone`) and defines `_PDT = ZoneInfo('America/Los_Angeles')` (line 40). The rest of the file uses `datetime.now(_PDT)` consistently for timestamps. Only this one hold_duration calculation uses naive `datetime.now()`.

### What the fix should do

Replace the naive calculation with a timezone-aware one. Both sides of the subtraction must use the same timezone reference.

**Option A (preferred — UTC):** Strip the `split('+')[0]` manipulation entirely. Parse the timestamp properly with timezone awareness, and compare to `datetime.now(timezone.utc)`:

```python
entry_dt = datetime.fromisoformat(
    pos.get('timestamp', '').replace('Z', '+00:00')
)
# entry_dt is now tz-aware (UTC+00:00 or offset as stored)
hold_hours = round((datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600, 2)
```

**Why this works:** Trade log timestamps from `logger.py` are stored as ISO strings. If they include a UTC offset (`+00:00` or `Z`), `fromisoformat` after `.replace('Z', '+00:00')` produces a tz-aware datetime. Subtracting two tz-aware datetimes is always safe regardless of server timezone.

**Edge case to verify:** If any trade log timestamps are stored as naive (no timezone suffix at all), `fromisoformat` will return a naive datetime and the subtraction against `datetime.now(timezone.utc)` will raise `TypeError`. Dev must check a sample of actual `logs/trades/trades_*.jsonl` entries to confirm the `timestamp` field format. If naive timestamps exist, apply this explicit fallback stub immediately after the `fromisoformat` call:

```python
if entry_dt.tzinfo is None:
    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
```

This attaches UTC explicitly before the subtraction. Do not silently skip naive timestamps.

**Do not leave the `split('+')[0]` stripping in place** — that is the root cause of the naivety.

### Priority

**Critical for correctness.** Hold duration in settle records is used by the Optimizer and Strategist for exit timing analysis. Wrong hold durations corrupt that analysis.

---

## B5-DS-2: P&L computation divergence between `/api/state` and `/api/pnl`

**File:** `environments/demo/dashboard/api.py`  
**Relevant blocks:** `_build_state()` starting at line ~1401; `get_pnl_history()` starting at line ~986  

### What the code does now

There are two separate endpoints that both report P&L figures:

1. **`/api/state`** → calls `_build_state()` (line ~1401)
2. **`/api/pnl`** → calls `get_pnl_history()` (line ~986)

Both endpoints independently:
- Call `read_all_trades()` to load all trade records
- Build a `close_records` index mapping `(ticker, side)` → settle/exit record
- Split positions into "settled" vs "open" buckets
- Loop through settled positions and accumulate `pnl_val`

### Where they diverge

The two functions implement this logic with **different deduplication strategies**:

- **`_build_state()`** (line ~1428): uses a **SUM accumulator** — when multiple settle records exist for the same `(ticker, side)`, it adds their `pnl` values together. This is the correct behavior for partial fills or scale-in trades that generate multiple settle records.

- **`get_pnl_history()`** (line ~1008): uses **last-write-wins** — the loop `close_records_pnl[(tk, sd)] = t` simply overwrites with the most recent record. Only the last settle record's P&L is counted. Earlier legs are silently dropped.

Additionally, `get_pnl_history()` builds a second index (`_close_records_by_id`, line ~1015) for win-rate counting by trade_id, but does **not** use this for the actual P&L dollar total. The dollar total still comes from the last-write-wins `close_records_pnl` dict.

The result: for any position with multiple settle records (scale-ins, split settlements), `/api/pnl` will under-count P&L compared to `/api/state`. The dashboard therefore shows inconsistent figures depending on which endpoint the frontend calls.

### What the fix should do

Extract the close-records-building logic into a single shared helper function and use it in both endpoints.

**Proposed shared function — `_build_close_records(all_trades: list) -> dict`:**

```
Input:  all_trades — the full list of trade records (from read_all_trades())
Output: dict mapping (ticker, side) -> merged record

Rules:
1. Iterate all_trades in order (chronological, as returned by read_all_trades()).
2. For each record where action is 'exit' or 'settle':
   a. key = (record['ticker'], record['side'])
   b. If key not seen before: store a copy of the record.
   c. If key already seen AND both records have a non-None 'pnl' field:
      add the new record's pnl to the existing entry's pnl (accumulate).
   d. If key already seen but either record is missing pnl: keep the existing
      record as-is (do not overwrite with a worse record).
3. Return the completed dict.
```

This matches the existing `_build_state()` SUM logic, which is the correct behavior.

**Both endpoints must:**
- Call `_build_close_records(all_trades)` instead of building the index inline
- Use the returned dict for all P&L dollar totals

**Placement:** Define `_build_close_records()` near the top of `api.py` with the other shared helpers (around line 80–90, after the existing `read_today_trades()` and `read_all_trades()` helpers).

**Do not change the `/api/pnl` win-rate counting path** (`_close_records_by_id` by trade_id) — that deduplication by trade_id is separate and correct. Only the P&L dollar total accumulation needs to be unified.

**Scope boundary:** The separate `exit_records` dict built inline in `_build_state()` (action='exit', keyed by ticker alone — not `(ticker, side)`) is **not** part of `_build_close_records()` and must remain inline. Do not fold it into the shared helper.

### Priority

**High.** `/api/pnl` and `/api/state` are the two panels David uses to monitor performance. If they show different totals, trust in both is undermined. This is a data integrity issue, not just display.

---

## B5-DS-3: Remaining `date.today()` sweep — `data_agent.py`, `dashboard/api.py`, `crypto_15m.py`

### Background

Batch 2 deferred all remaining `date.today()` calls in these files. The overnight audit found they number 10+ in `data_agent.py`, 6 in `api.py`, and 2 in `crypto_15m.py`. **Post-review addition:** `agents/ruppert/trader/utils.py` contains an additional critical `date.today()` site in `load_traded_tickers()` at line 17 (see subsection below). During UTC/PDT boundary windows (midnight UTC = 5pm PDT summer / 4pm PDT winter), `date.today()` returns the wrong date, which can silently disable circuit breakers, misroute trade logs, and corrupt audit records.

### The fix pattern

The fix is to replace `date.today()` with a PDT-aware equivalent. The standard pattern used elsewhere in this codebase is:

```python
from zoneinfo import ZoneInfo as _ZoneInfo
_LA = _ZoneInfo('America/Los_Angeles')
def _today_pdt():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone(_LA).date()
```

Then replace `date.today()` with `_today_pdt()`.

Each file below should define this helper once at module scope (or import it from a shared location — see B5-DS-4 note below about constants consolidation; a shared `_today_pdt` could live in `agents/ruppert/trader/utils.py` for trader files).

---

### `agents/ruppert/trader/utils.py`

One site — added by adversarial review:

**Site — Line 17** (`load_traded_tickers`):
```python
today = date.today().isoformat()
trade_log = TRADES_DIR / f"trades_{today}.jsonl"
```
`load_traded_tickers()` is the deduplication guard called by all trader modules before placing any trade. During the midnight UTC/PDT boundary window, `date.today()` returns tomorrow's date. That log file does not yet exist. `load_traded_tickers()` returns an empty set. The caller sees no previously traded tickers → dedup check passes → **a duplicate trade executes**.

This is at least as critical as the `crypto_15m.py` line 553 site. The distinction: line 553 affects P&L cap logic within one module; this site affects the dedup guard for **all** trader modules that call `load_traded_tickers()`.

**Priority: CRITICAL (trading correctness — duplicate trade prevention)**  
Fix: replace `date.today()` with `_today_pdt()`. Define the `_today_pdt()` helper once in `utils.py` at module scope (after the existing imports, before `TRADES_DIR`) and use it here.

**Diff consolidation (mandatory):** B5-DS-4 is already adding a patch to `utils.py` (adding `CRYPTO_15M_SERIES`). The `_today_pdt()` helper definition and its use in `load_traded_tickers()` **must be bundled into that same B5-DS-4 diff** — do not open a separate utils.py change. Dev: one clean utils.py patch covers both.

---

### `agents/ruppert/trader/crypto_15m.py`

Two sites, both deferred from Batch 2:

**Site 1 — Line 553** (`_get_session_pnl_15m`):
```python
today = date.today().isoformat()
log_path = _get_paths()['trades'] / f'trades_{today}.jsonl'
```
This determines which trade log file to read for same-session P&L. If the date is wrong, the session P&L returns $0.00, the window cap check silently passes, and trades exceed the intended cap.  
**Priority: CRITICAL (trading correctness — risk control)**  
Fix: replace `date.today()` with `_today_pdt()`.

**Site 2 — Line 1333** (buy record construction):
```python
'date': str(date.today()),
```
This is the `date` field written into every buy record in the trade log. If this is wrong, the Data Scientist's synthesizer and Optimizer will bucket the trade into the wrong day. This is also the field referenced in the **Batch 2 B2-STR-2 cross-spec note** — incorrect buy record dates break any cross-spec logic that relies on date-matching buy and settle records.  
**Priority: CRITICAL (data integrity — buy record correctness, cross-spec dependency)**  
Fix: replace `date.today()` with `_today_pdt()`.

Both sites: `crypto_15m.py` already imports `zoneinfo` indirectly through other modules. Add `_today_pdt()` as a module-level helper (near the top of the file, after the existing constants block around line 55) and use it at both sites.

---

### `agents/ruppert/data_scientist/data_agent.py`

`data_agent.py` already imports `zoneinfo` at line 20 and uses it for timezone-aware checks elsewhere (e.g., the `check_15m_entry_drought` function at line 705). Add a `_today_pdt()` helper once near the top of the file (e.g., after the imports around line 30) and replace all `date.today()` calls.

**Site-by-site breakdown:**

| Line | Context | Priority |
|------|---------|----------|
| 192 | `_current_log_path()` — determines which trade log file to open for audit | **CRITICAL** — wrong file = audit runs on stale data, misses today's trades |
| 443 | `today = date.today()` in open-positions audit — filters positions by today's market expiry | **CRITICAL** — wrong date = live positions treated as stale, false audit errors |
| 564 | `yesterday = date.today() - timedelta(days=1)` — yesterday lookback for trade scan | Critical-adjacent — off-by-one during boundary windows produces duplicate audit coverage |
| 570 | `today_str = date.today().isoformat()` — same audit block as line 564 | Same as above |
| 616 | `activity_{date.today().isoformat()}.log` — activity log filename | Lower — display/logging only, no trading impact |
| 820 | 7-day cutoff for stale position detection | Lower — display/audit only; slightly wrong cutoff window |
| 981 | `trades_{date.today().isoformat()}.jsonl` — trade log read inside an audit function | **CRITICAL** — same as line 192, wrong file |
| 1273 | `_issue_hash('daily_cap', ...)` — deduplication hash for daily cap alerts | Medium — wrong date causes duplicate or missed circuit-breaker alerts |
| 1326 | `data_audit_{date.today().isoformat()}.json` — output audit file naming | Lower — audit file goes to wrong-date filename; cosmetic |
| 1355 | `_issue_hash('batch', ...)` — batch-level alert dedup hash | Medium — same as line 1273 |
| 1419 | `last_full[:10] == date.today().isoformat()` — guards against double-running full audit | Medium — during boundary window, full audit runs twice or not at all |
| 1512 | `data_audit_{date.today().isoformat()}.json` — second audit output filename | Lower — same as line 1326 |
| 1526 | `_issue_hash('historical_audit', ...)` — historical audit dedup hash | Lower — display only |
| 1530 | Period string in audit summary text | Lower — cosmetic |

**Summary:** Lines 192, 443, 981 are critical (wrong trade log file). Lines 1273, 1355, 1419 are medium (alert dedup / audit guard logic). Lines 564, 570 are critical-adjacent. Remaining lines are lower priority.

Fix: add one `_today_pdt()` helper at module scope (after the imports block, around line 30). Replace all `date.today()` calls with `_today_pdt()`. No behavioral change for any call during normal hours; fixes boundary-window bugs.

---

### `environments/demo/dashboard/api.py`

`api.py` has no existing PDT-aware date helper. `date.today()` calls are inline. The file imports `from datetime import date, datetime` at line 17. There is no `_pdt_today`, `_today_pdt`, or timezone import at module scope.

**Add a `_today_pdt()` helper at module scope** (around line 20, near existing imports). Since `api.py` already imports `zoneinfo`-adjacent modules, this pattern works:

```python
from zoneinfo import ZoneInfo as _ZoneInfo
_LA_TZ = _ZoneInfo('America/Los_Angeles')
def _today_pdt():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone(_LA_TZ).date()
```

**Site-by-site breakdown:**

| Line | Context | Priority |
|------|---------|----------|
| 90 | `read_today_trades()` — trade log filename for today's trades | **CRITICAL** — this is the primary per-day trade log reader; wrong file = wrong dashboard data all day |
| 121 | `_get_crypto15m_summary()` — filters decisions_15m.jsonl by today's date prefix | Medium — wrong filter = today's 15m summary shows yesterday's data |
| 344 | `_get_module_pnl_week()` — `_today` used for week-start calculation | Lower — display/reporting; period P&L bucketing slightly off |
| 584 | `POST /api/deposit` — sets `date` field in deposit entry | Medium — deposit record goes to wrong date; affects capital reconciliation |
| 1074 | `_build_state()` — `_today` used for period P&L bucketing (day/month/year) | Lower — display only; period totals slightly wrong during boundary window |
| 1569 | `_build_state()` closed P&L period bucketing | Lower — display only |

**Priority summary:** Line 90 is critical (wrong trade log). Line 584 is medium (deposit records). Lines 121, 344, 1074, 1569 are lower priority (display/reporting).

Fix: add one `_today_pdt()` helper at module scope. Replace all 6 sites. The locally-scoped `from datetime import date as _date` imports inside `_build_state()` and `_get_module_pnl_week()` (lines 343, 1073, 1405) should be replaced by calls to the module-level `_today_pdt()` — no need for inline imports once the helper exists.

---

## B5-DS-4: `CRYPTO_15M_SERIES` duplicate definitions — consolidate to single source

**Files:**  
- `agents/ruppert/trader/crypto_15m.py` line 58  
- `agents/ruppert/trader/position_monitor.py` line 69  

### What the code does now

Both files define the same constant:
```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']
```

These are currently identical. QA flagged that they will diverge if a new series (e.g., KXSUI15M) is added — one file will be updated and the other won't, causing position_monitor to miss new series or crypto_15m to fail to match position entries.

### Where it should live

The right home is **`agents/ruppert/trader/utils.py`**.

Rationale:
- `utils.py` already exists and is imported by both files. `position_monitor.py` imports `push_alert` and `load_traded_tickers` from it (lines 78, 128). `crypto_15m.py` imports from `env_config` which is a peer of `utils.py`.
- `utils.py` is described as "Shared utility functions for the Ruppert trader modules" — constants that multiple trader modules share belong here.
- `utils.py` already imports `from datetime import date, datetime, timezone, timedelta` — it is a shared module, not a trading-logic module. A series list is a constants entry.

### What the fix should do

1. In `agents/ruppert/trader/utils.py`: add the constant near the top of the file, after the existing imports and `TRADES_DIR` line:
   ```python
   CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']
   ```

2. In `agents/ruppert/trader/crypto_15m.py` (line 58): remove the local definition. Add an import:
   ```python
   from agents.ruppert.trader.utils import CRYPTO_15M_SERIES
   ```
   (This can be added alongside the existing `from agents.ruppert.env_config import get_paths` import at line 109, or near the top of the constants block.)

3. In `agents/ruppert/trader/position_monitor.py` (line 69): remove the local definition. Add the same import:
   ```python
   from agents.ruppert.trader.utils import CRYPTO_15M_SERIES
   ```
   (Can be added alongside the existing `from agents.ruppert.trader.utils import push_alert` import at line 78.)

### Circular import check

Verify there is no circular import before building. `crypto_15m.py` imports from `utils.py`; `utils.py` must not import from `crypto_15m.py`. Check `utils.py` imports — currently it only imports from stdlib and `env_config`/`event_logger`. Safe.

`position_monitor.py` also imports from `utils.py` — same check applies. Currently clean.

Dev should confirm no circular dependency after making the change by doing a dry-run import in a fresh Python session.

### New dependency note

`crypto_15m.py` does **not** currently import `utils.py` at all — adding `from agents.ruppert.trader.utils import CRYPTO_15M_SERIES` introduces `utils.py` as a new import dependency for that module. This is intentional and safe (circular import check above confirms it), but Dev must note this explicitly in the implementation commit message so the new dependency is traceable in git history.

### Priority

**Medium (cleanup).** Currently identical so no production risk, but the divergence risk grows with every new series added. Fix in Batch 5 alongside the other cleanup items.

---

## Summary Table

| ID | File | Issue | Priority |
|----|------|--------|----------|
| B5-DS-1 | `settlement_checker.py` L229-232 | Naive datetime in hold_duration | Critical |
| B5-DS-2 | `dashboard/api.py` L986+, L1407+ | P&L computation diverges between endpoints | High |
| B5-DS-3a | `crypto_15m.py` L553 | `date.today()` in session P&L / log filename | Critical |
| B5-DS-3b | `crypto_15m.py` L1333 | `date.today()` in buy record (cross-spec B2-STR-2) | Critical |
| B5-DS-3i | `utils.py` `load_traded_tickers()` L17 | `date.today()` in dedup guard → empty set → duplicate trade | **Critical** |
| B5-DS-3c | `data_agent.py` L192, 443, 981 | `date.today()` in trade log file paths / audit | Critical |
| B5-DS-3d | `data_agent.py` L564, 570, 1273, 1355, 1419 | `date.today()` in alert dedup / audit guards | Medium |
| B5-DS-3e | `data_agent.py` L616, 820, 1326, 1512, 1526, 1530 | `date.today()` in log filenames / display | Lower |
| B5-DS-3f | `api.py` L90 | `date.today()` in `read_today_trades()` | Critical |
| B5-DS-3g | `api.py` L584 | `date.today()` in deposit record date field | Medium |
| B5-DS-3h | `api.py` L121, 344, 1074, 1569 | `date.today()` in display/period bucketing | Lower |
| B5-DS-4 | `crypto_15m.py` L58, `position_monitor.py` L69 | Duplicate `CRYPTO_15M_SERIES` definition | Medium |
