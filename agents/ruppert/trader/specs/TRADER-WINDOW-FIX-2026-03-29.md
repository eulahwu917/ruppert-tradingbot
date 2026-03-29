# TRADER-WINDOW-FIX-2026-03-29

**Spec:** Fix 30-Day Log Scan Window for Long-Horizon Positions  
**Filed:** 2026-03-29  
**Author:** Trader (Subagent)  
**Priority:** High — silent data loss on monthly/annual positions  
**Status:** Pending Dev

---

## Problem

`load_open_positions()` in both `post_trade_monitor.py` and `position_monitor.py`, and `check_settlements()` in `post_trade_monitor.py`, all scan a rolling 30-day window of trade log files to reconstruct open positions.

If a position was entered more than 30 days ago (e.g. a monthly or annual Kalshi market), the original buy record falls outside the scan window. The position is **silently dropped** — no settlement check, no exit monitoring, no alerts. The position becomes an orphan.

### Affected files and functions

| File | Function | Window |
|---|---|---|
| `post_trade_monitor.py` | `load_open_positions()` | 30 days |
| `post_trade_monitor.py` | `check_settlements()` | 30 days (inline copy) |
| `position_monitor.py` | `load_open_positions()` | 30 days |

---

## Fix Assessment

Two options were evaluated:

### Option A — Extend window to 365 days

Change `range(30)` → `range(365)` in all three scan loops.

**Pros:** Trivial change, zero risk of breaking data flow.  
**Cons:** Reads up to 365 files per cycle, most of which don't exist. Slight I/O cost (negligible on SSD, ~seconds on slow disk). Does not use the existing authoritative position source.

### Option B — Read from `tracked_positions.json` as primary source

Use `position_tracker._tracked` (or read `tracked_positions.json` directly) as the authoritative list of open positions, then look up metadata from logs only when needed.

**Pros:** Architecturally correct — tracker already persists positions with no date limit.  
**Cons:** Complex integration risk. `tracked_positions.json` stores a subset of fields (quantity, side, entry_price, module, title, exit_thresholds) — it **does not** store all fields that `load_open_positions()` consumers depend on (e.g. `target_date`, `ticker` for settlement, `scan_price`, `market_prob`, `confidence`, `noaa_prob`). A hybrid approach would be required: tracker as index, logs as metadata store. This adds complexity and a new failure mode (tracker present, log record missing).

### Decision: **Option A — Extend window to 365 days**

The tracker is not a drop-in replacement for the log-based position records in these functions. The log records carry richer metadata (target_date, confidence, noaa_prob, etc.) that settlement and exit checks depend on. Rebuilding all consumers to use the tracker as primary source is a multi-function refactor with meaningful risk.

Extending to 365 days is safe, simple, and correct. Monthly/annual markets expire within 365 days. The I/O cost is negligible — most files won't exist and are skipped in one `exists()` check per loop iteration.

---

## Implementation

### Change 1 — `post_trade_monitor.py` → `load_open_positions()`

**BEFORE:**
```python
def load_open_positions():
    """Load open positions from trade logs, filtering out exits.

    Reads today's log AND yesterday's log so multi-day positions entered
    yesterday are not missed. Today's entries/exits take precedence.
    """
    today = date.today()

    # Scan rolling 30-day window to include long-horizon positions (monthly/annual).
    logs_to_check = []
    for days_back in range(30):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

**AFTER:**
```python
def load_open_positions():
    """Load open positions from trade logs, filtering out exits.

    Scans a 365-day rolling window to capture long-horizon positions
    (monthly, quarterly, annual markets). Most files will not exist and
    are skipped cheaply via exists() check.
    """
    today = date.today()

    # Scan rolling 365-day window to capture long-horizon positions (monthly/annual).
    # Extended from 30 days — a 30-day window silently dropped positions entered
    # more than 30 days ago (e.g. annual markets). Most files don't exist; the
    # exists() check is cheap.
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

---

### Change 2 — `post_trade_monitor.py` → `check_settlements()`

**BEFORE:**
```python
    # Scan a rolling 30-day window to catch long-horizon positions (monthly/annual).
    # We read all available log files from the last 30 days; most will be empty/missing.
    logs_to_check = []
    for days_back in range(30):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

**AFTER:**
```python
    # Scan a rolling 365-day window to catch long-horizon positions (monthly/annual).
    # Extended from 30 days — positions entered more than 30 days ago were silently
    # skipped by the settlement checker. Most files don't exist; skipped via exists().
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

---

### Change 3 — `position_monitor.py` → `load_open_positions()`

**BEFORE:**
```python
def load_open_positions():
    """Load open positions from trade logs, filtering out exits/settlements."""
    today = date.today()

    # Scan rolling 30-day window to include long-horizon positions (monthly/annual).
    logs_to_check = []
    for days_back in range(30):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

**AFTER:**
```python
def load_open_positions():
    """Load open positions from trade logs, filtering out exits/settlements.

    Scans a 365-day rolling window to capture long-horizon positions
    (monthly, quarterly, annual markets). Most files will not exist and
    are skipped cheaply via exists() check.
    """
    today = date.today()

    # Scan rolling 365-day window to capture long-horizon positions (monthly/annual).
    # Extended from 30 days — a 30-day window silently dropped positions entered
    # more than 30 days ago (e.g. annual markets). Most files don't exist; the
    # exists() check is cheap.
    logs_to_check = []
    for days_back in range(365):
        log_date = today - timedelta(days=days_back)
        logs_to_check.append(TRADES_DIR / f"trades_{log_date.isoformat()}.jsonl")
```

---

## Summary of Changes

| File | Function | Line change |
|---|---|---|
| `post_trade_monitor.py` | `load_open_positions()` | `range(30)` → `range(365)` |
| `post_trade_monitor.py` | `check_settlements()` | `range(30)` → `range(365)` |
| `position_monitor.py` | `load_open_positions()` | `range(30)` → `range(365)` |

3 one-line changes total. Comments updated at each site to document the reason for the 365-day window.

---

## Testing Notes

- Confirm `TRADES_DIR` exists and has files older than 30 days (simulate with a test `.jsonl` at `trades_YYYY-MM-DD.jsonl` dated 45 days back containing an open buy).
- Run `python post_trade_monitor.py` and verify the old position appears in the "open positions" output.
- Confirm no performance regression — scan should complete in under 1 second even with 365-entry path list (most files missing).
- No schema changes. No new dependencies.

---

## Future Consideration (Not In Scope)

Long-term, `load_open_positions()` should be refactored to use `tracked_positions.json` as the **index** of open positions and the log files as a **metadata lookup**. This would make the window truly unbounded and independent of file age. That refactor should be a separate spec with full integration testing across settlement, exit monitoring, and alert routing.
