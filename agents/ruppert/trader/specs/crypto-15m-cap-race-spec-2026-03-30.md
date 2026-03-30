# Spec: Crypto 15m — Cap Design & Race Condition
**Module:** `agents/ruppert/trader/crypto_15m.py`
**Date:** 2026-03-30
**Author:** Ruppert (Trader)
**Status:** DRAFT — for CEO/David review. Do NOT send to Dev yet.

---

## Overview

Two distinct but related issues threaten the integrity of the `crypto_15m` risk controls:

1. **Issue 1 (Design):** The current daily cumulative cap is conceptually mismatched for a module where capital recycles every 15 minutes. The cap design was ported from the all-day weather module without adapting it to 15m contract mechanics.

2. **Issue 2 (Implementation):** A race condition allows all 4 tickers in a window to simultaneously pass the cap check before any of them records a trade, causing cap overrun by 2–5x. Today's example: 13 trades placed, $1,019 deployed vs $499 cap.

These issues interact: fixing Issue 1 changes what the cap counter should measure, which changes how Issue 2's fix should be designed.

---

## Issue 1: Daily Cap — Wrong Risk Model for 15m Contracts

### Background

The current cap:
```python
CRYPTO_15M_DAILY_CAP_PCT = 0.06   # 6% of capital ≈ $499 at ~$8,300 capital
daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
current_exposure = get_daily_exposure('crypto_15m')

if current_exposure >= daily_cap:
    return  # SKIP: DAILY_CAP
```

`get_daily_exposure('crypto_15m')` reads all un-exited buys since launch date (2026-03-26). For the 15m module, a trade entered at 13:15 has settled by 13:30. The exposure counter therefore accumulates all day, even though each position's actual risk window is only 15 minutes.

### What Risk Was the Daily Cap Designed to Protect Against?

For the **weather module**, positions are open all day. The daily cap protects against:
- **Concentration risk:** Too much capital tied up in correlated positions simultaneously
- **Drawdown acceleration:** Losing on many concurrent positions in a single bad day
- **Capital lock-up:** Not having buying power for better opportunities

All three risks arise because weather trades are **live and at risk** for 8–12 hours. The cap correctly limits simultaneous exposure.

### Does That Risk Apply the Same Way to 15m Contracts?

**No. Critically different mechanics:**

| Factor | Weather (all-day) | Crypto 15m |
|--------|-------------------|------------|
| Positions concurrent | Many open at once | Each expires in 15 min |
| Capital at risk simultaneously | All open positions | Only current window's positions |
| Capital recycling | Slow (once/day) | Fast (56 windows/day) |
| "Exposure" accumulation | Meaningful | Misleading |

With 15m contracts, `get_daily_exposure()` counts every buy since 13:00 even though the 13:00–13:15 position already settled. By mid-afternoon the counter exceeds the cap from settled trades, blocking new entries that have no relation to current risk.

**The daily cumulative cap actively breaks the module's intended behavior by noon.**

### What Risk Does the 15m Module Actually Need to Control?

Two real risks to protect against:

**Risk A — Per-window concentration:** Putting too much into a single 15-minute window across 4 correlated crypto assets. If all 4 tickers move together (they do — they're all in the same macro regime), losing all 4 at once in one window is a real event.

**Risk B — Daily aggregate drawdown:** Losing a bit every window, 40+ times a day, adds up. A daily ceiling on *total dollars wagered* (not concurrent exposure) prevents runaway losses from a bad-signal day.

### Proposed Cap Design

**Replace the single daily cap with a two-tier control:**

#### Tier 1: Per-Window Position Limit (new)
Cap the total dollars placed *within a single 15-minute window* across all tickers.

```
CRYPTO_15M_WINDOW_CAP_PCT = 0.01  # 1% of capital per window ≈ $83
```

This replaces the "concurrent exposure" logic from the weather module. For a 15m contract, this is the right unit of risk containment.

#### Tier 2: Daily Wager Ceiling (redesigned)
Track *total dollars wagered today* (all buys, regardless of settlement), not open exposure. Cap at a higher ceiling since capital recycles.

```
CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.15  # 15% of capital ≈ $1,245
```

This is a daily loss-limiter: if signals are bad all day and every window is losing, this stops the module before it bleeds 15% in a day. 15% (vs current 6%) is appropriate because capital recycles — you're not risking 15% simultaneously.

#### Tier 1 check replaces the current cap check at entry time.
#### Tier 2 check is a new daily aggregate check (uses a new counter).

### BEFORE / AFTER: Issue 1

**BEFORE (current):**
```python
# In config.py
CRYPTO_15M_DAILY_CAP_PCT = 0.06   # 6% of capital, cumulative open exposure

# In crypto_15m.py
daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
current_exposure = get_daily_exposure('crypto_15m')  # sums all un-exited buys

if current_exposure >= daily_cap:
    _log_decision(..., 'SKIP', 'DAILY_CAP', ...)
    return
```

**AFTER (proposed):**
```python
# In config.py
CRYPTO_15M_WINDOW_CAP_PCT      = 0.01   # 1% per 15-min window ≈ $83
CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.15   # 15% daily wager ceiling ≈ $1,245

# In crypto_15m.py  (conceptual — not implementation)

# Tier 2: Daily wager ceiling (total dollars placed today, settled or not)
daily_wager = get_daily_wager('crypto_15m')           # NEW: sums all buys today, ignores exits
daily_wager_cap = capital * CRYPTO_15M_DAILY_WAGER_CAP_PCT
if daily_wager >= daily_wager_cap:
    _log_decision(..., 'SKIP', 'DAILY_WAGER_CAP', ...)
    return

# Tier 1: Per-window cap (this window only, all tickers combined)
window_cap = capital * CRYPTO_15M_WINDOW_CAP_PCT
window_exposure = get_window_exposure(window_open_ts)  # NEW: sums buys in this 15m window
if window_exposure + position_usd > window_cap:
    position_usd = window_cap - window_exposure        # partial-fill to cap edge, or skip
    if position_usd < 5.0:
        _log_decision(..., 'SKIP', 'WINDOW_CAP', ...)
        return
```

**New helper needed:** `get_daily_wager(module)` — sums `size_dollars` for all `action='buy'` entries today for the module, regardless of exit/settle status. This is the correct counter for Tier 2.

**New helper needed:** `get_window_exposure(window_open_ts)` — sums `size_dollars` for buys in today's trade log where `window_open_ts` matches the current window. This is the correct counter for Tier 1 (and directly solves the race condition if writes are synchronous — see Issue 2).

---

## Issue 2: Race Condition — Parallel Ticker Evaluation

### Code Confirmation

In `evaluate_crypto_15m_entry()`, the cap check reads exposure from the log file:

```python
current_exposure = get_daily_exposure('crypto_15m')

if current_exposure >= daily_cap:
    ...return
```

`get_daily_exposure()` reads the **trades log file on disk** (see `logger.py:203`). The write happens much later — only after signals are computed, risk filters pass, edge is confirmed, and `log_trade()` is finally called at the bottom of the function.

When the WS feed fires near-simultaneously for BTC, ETH, XRP, and DOGE at the start of a new 15-minute window, all 4 calls to `evaluate_crypto_15m_entry()` execute in rapid succession (or concurrently if the WS handler uses threads/async). Each reads `get_daily_exposure()` before any of them has written to the log.

**Race sequence (confirmed):**
```
T=0ms   BTC eval starts → reads exposure = $0 → passes cap check
T=5ms   ETH eval starts → reads exposure = $0 → passes cap check
T=10ms  XRP eval starts → reads exposure = $0 → passes cap check
T=15ms  DOGE eval starts → reads exposure = $0 → passes cap check
T=200ms BTC eval finishes → log_trade() writes $78 → exposure = $78
T=210ms ETH eval finishes → log_trade() writes $78 → exposure = $156
T=220ms XRP eval finishes → log_trade() writes $78 → exposure = $234
T=230ms DOGE eval finishes → log_trade() writes $78 → exposure = $312
```

All 4 placed. Cap of $499 not enforced per-ticker because the file lag makes each read stale. Over a full day with 13 windows × 4 tickers, this compounds to the $1,019 overrun observed today.

### Does Issue 1's Fix Affect How Issue 2 Should Be Fixed?

**Yes, significantly.** If we move from a daily cap to a per-window cap:

- The window cap is naturally window-scoped: only tickers in the same 15-minute window contend for the same slot
- The race is tightest exactly where the new cap matters most — within a window
- We need the in-memory counter to be window-keyed, not just a global running total

The per-window cap design effectively narrows the race window from "all day" to "15 minutes", but it also concentrates all 4 tickers into the exact same contention window. So Issue 2's fix must be implemented at the window level.

### Proposed Fix: In-Memory Per-Window Counter with Mutex

**Option A: Sequential evaluation (simple but slow)**
Serialize WS ticker evaluations so only one runs at a time. Pros: no race. Cons: signal staleness — BTC's signal at T=0 is different from DOGE's signal at T=800ms. For 15m contracts, 800ms lag is acceptable but not ideal.

**Option B: In-memory counter with a threading lock (recommended)**
Maintain a module-level in-memory dict keyed by `window_open_ts`. Protected by a `threading.Lock`. Read + increment + release atomically before the log write. The log write then serves as the durable record; the in-memory counter serves as the real-time gatekeeper.

This approach:
- Eliminates the race without serializing signal fetches
- Tickers still evaluate their signals in parallel
- Only the cap check + increment is serialized (microsecond critical section)
- Works correctly with the per-window cap design from Issue 1

### BEFORE / AFTER: Issue 2

**BEFORE (current):**
```python
# crypto_15m.py — cap check reads from disk log (stale during same window)

current_exposure = get_daily_exposure('crypto_15m')   # disk read, not updated yet

if current_exposure >= daily_cap:
    _log_decision(..., 'SKIP', 'DAILY_CAP', ...)
    return

# ... (100+ lines of signal/edge logic) ...

log_trade(opp, position_usd, contracts, order_result)  # disk write happens here (too late)
```

**AFTER (proposed — conceptual, not implementation):**
```python
# Module-level state (added at top of crypto_15m.py)
import threading
_window_lock = threading.Lock()
_window_exposure: dict[str, float] = {}   # window_open_ts → total $ committed this window
_daily_wager: float = 0.0                 # running total for today (reset at midnight)
_daily_wager_date: str = ''               # date string for daily reset

# In evaluate_crypto_15m_entry(), AFTER position_usd is calculated and BEFORE order execution:

with _window_lock:
    # Reset daily wager counter at day boundary
    today_str = date.today().isoformat()
    global _daily_wager, _daily_wager_date
    if _daily_wager_date != today_str:
        _daily_wager = 0.0
        _daily_wager_date = today_str

    # Tier 2: daily wager ceiling
    if _daily_wager + position_usd > daily_wager_cap:
        position_usd = daily_wager_cap - _daily_wager
        if position_usd < 5.0:
            # log DAILY_WAGER_CAP and return (outside lock)
            _skip = True

    if not _skip:
        # Tier 1: per-window cap
        win_key = window_open_ts or 'unknown'
        win_exp = _window_exposure.get(win_key, 0.0)
        if win_exp + position_usd > window_cap:
            position_usd = window_cap - win_exp
            if position_usd < 5.0:
                _skip = True  # log WINDOW_CAP and return (outside lock)

        if not _skip:
            # Tentatively reserve capacity (release if order fails)
            _window_exposure[win_key] = win_exp + position_usd
            _daily_wager += position_usd
            _reserved = True

if _skip:
    _log_decision(..., 'SKIP', 'WINDOW_CAP' or 'DAILY_WAGER_CAP', ...)
    return

# ... execute order ...

if order_failed:
    # Release reservation on failure
    with _window_lock:
        _window_exposure[win_key] = max(0.0, _window_exposure[win_key] - position_usd)
        _daily_wager = max(0.0, _daily_wager - position_usd)
    return

log_trade(...)   # disk write: durable record
```

**Key properties of this fix:**
- The lock covers only the cap check + increment, not signal fetches (which are slow I/O)
- Capacity is reserved immediately when a trade is approved, before the order executes
- Capacity is released if the order fails, so a failed order doesn't eat window budget
- The in-memory counter is authoritative for cap enforcement; the disk log is the audit trail
- At startup/restart, the in-memory counter starts at 0. For the daily wager counter, this is safe — the bot would only restart within a day during incident response, at which point trading being temporarily under-aggressive is acceptable. A more robust fix (re-hydrate from log on startup) is optional.

### Window Key Note

`window_open_ts` is derived from the ticker name in the current code. It must be consistent across all 4 tickers in the same window. Current parsing (from `KXBTC15M-26MAR281315-15`) produces an ISO timestamp; same logic applies to ETH/XRP/DOGE tickers for the same time slot. This is safe.

---

## Summary of Changes Required

| # | Change | Type | New Config Key |
|---|--------|------|----------------|
| 1 | Remove `CRYPTO_15M_DAILY_CAP_PCT` usage | Config + Code | — |
| 2 | Add `CRYPTO_15M_WINDOW_CAP_PCT = 0.01` | Config | New |
| 3 | Add `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.15` | Config | New |
| 4 | Add `get_daily_wager(module)` to `logger.py` | Code | — |
| 5 | Add `_window_lock`, `_window_exposure`, `_daily_wager` module-level state | Code | — |
| 6 | Replace cap check section in `evaluate_crypto_15m_entry()` | Code | — |
| 7 | Add reservation release on order failure | Code | — |

---

## Open Questions for David/CEO Review

1. **Window cap value:** Is $83/window (1% of $8,300 capital) the right number? At 4 tickers × ~$20 each, that's ~$80/window naturally. A 1% cap means we'd rarely hit it under normal conditions but it hard-stops a runaway window.

2. **Daily wager ceiling:** 15% (~$1,245) is a conservative full-day loss limiter. Is that the right magnitude? At $80/window × 56 windows = $4,480 maximum theoretical daily wager, 15% is a ~3.5-hour hard stop.

3. **Startup re-hydration:** Should the daily wager counter re-hydrate from the log file on startup? Current proposal: start at 0 (safe, slightly permissive on restart). Low priority.

4. **`get_daily_wager()` placement:** Should it live in `logger.py` alongside `get_daily_exposure()`, or in a new `crypto_15m_state.py`? Recommend `logger.py` for consistency.
