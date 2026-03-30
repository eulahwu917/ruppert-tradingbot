# Spec: Crypto 15m — Cap Redesign (Strategist)
**Module:** `agents/ruppert/trader/crypto_15m.py`  
**Date:** 2026-03-30  
**Author:** Ruppert (Strategist)  
**Status:** APPROVED — Ready for Dev implementation  
**Companion spec (race condition detail):** `agents/ruppert/trader/specs/crypto-15m-cap-race-spec-2026-03-30.md`

---

## Executive Summary

The current `CRYPTO_15M_DAILY_CAP_PCT` design was ported from the weather module without adapting it to 15m contract mechanics. It measures cumulative open exposure, which is meaningless for contracts that settle every 15 minutes. By mid-afternoon the counter blocks legitimate trades from settled positions.

This spec replaces it with a two-tier risk system:

- **Tier 1 (primary):** Per-window cap — limits dollars wagered per 15-minute window across all tickers
- **Tier 2 (backstop):** Daily wager ceiling — set high (40%), exists only as an execution bug safety net
- **Circuit breaker (primary halt control):** Halt (advisory-only initially) after 3 consecutive complete-loss windows

The race condition (all 4 tickers passing the cap check simultaneously before any log write) is addressed via an in-memory per-window counter with `threading.Lock`. See Trader's companion spec for the detailed race condition BEFORE/AFTER.

---

## Decisions (Authoritative)

| # | Question | Decision |
|---|----------|----------|
| Q1 | Window cap value | **2% of capital (~$166/window).** Covers 2 normal entries OR 1 scale-in + 1 normal. Scale-ins are NOT exempt. |
| Q2 | Daily ceiling | **Replace with circuit breaker as primary.** Keep 40% ceiling as backstop only (execution bug safety net — should never fire in normal operation). Remove the old 6% daily cap entirely. |
| Q2a | Circuit breaker threshold | **3 consecutive complete-loss windows** trigger halt. "Complete loss" = all entries in that window expire at zero. Any winning window resets counter to 0. Partial losses don't count. |
| Q2b | Advisory mode | **Implement as advisory-only** (log when it would fire, don't actually halt). Review and calibrate after 30 trades. |
| Q3 | Race condition fix | **In-memory per-window counter with `threading.Lock`.** See Trader's spec for implementation detail. |
| Q4 | Re-hydrate on restart | **Yes.** Circuit breaker state and daily wager counter re-read from trade/settlement log on startup. |
| Q5 | `get_daily_wager()` placement | **`logger.py`** alongside existing `get_daily_exposure()`. |

---

## 1. Config Changes

**File:** `agents/ruppert/config.py` (or wherever `CRYPTO_15M_DAILY_CAP_PCT` currently lives)

### BEFORE
```python
CRYPTO_15M_DAILY_CAP_PCT = 0.06   # 6% of capital cumulative cap
```

### AFTER
```python
# Remove:
# CRYPTO_15M_DAILY_CAP_PCT = 0.06   ← DELETE THIS LINE

# Add:
CRYPTO_15M_WINDOW_CAP_PCT           = 0.02   # 2% of capital per 15-min window (~$166 at $8,300 capital)
CRYPTO_15M_DAILY_WAGER_CAP_PCT      = 0.40   # 40% backstop only — execution bug safety net, not normal risk control
CRYPTO_15M_CIRCUIT_BREAKER_N        = 3      # consecutive complete-loss windows before halt
CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True   # True = log warning only, don't actually halt (data collection mode)
```

**Notes:**
- `CRYPTO_15M_WINDOW_CAP_PCT = 0.02` is the operative risk control. At ~$8,300 capital this is ~$166/window. Normal entries are ~$78 each, so 2 fit cleanly. A scale-in (~$156) plus a normal entry (~$78) overflows — the trim logic handles this (see Section 3).
- `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40` should never fire in normal operation. If it fires, something is wrong at the code/order level and the human should be paged.
- `CRYPTO_15M_CIRCUIT_BREAKER_N = 3` is the primary halt control. Calibrate after 30 trades.
- `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True` — flip to `False` after calibration review to enable actual halting.

---

## 2. `logger.py` Changes

**File:** `agents/ruppert/logger.py`

Add two new functions alongside the existing `get_daily_exposure()`.

### 2a. `get_daily_wager(module)`

Sums all buy `size_dollars` for the given module today, regardless of settlement status. This is the Tier 2 backstop counter.

**Difference from `get_daily_exposure()`:** `get_daily_exposure()` sums only *un-exited* buys (open positions). `get_daily_wager()` sums *all* buys today regardless of whether they've settled — it's a wager total, not an exposure total.

#### BEFORE
*(function does not exist)*

#### AFTER
```python
def get_daily_wager(module: str) -> float:
    """
    Returns the total dollars wagered (all buy entries) for the given module today,
    regardless of whether positions have settled or been exited.

    Used for the Tier 2 daily wager backstop in crypto_15m.

    Args:
        module: Module name string (e.g. 'crypto_15m')

    Returns:
        Total size_dollars of all buy actions logged today for this module.
    """
    today = date.today().isoformat()   # 'YYYY-MM-DD'
    total = 0.0
    trades = _read_trades_for_module(module)   # use existing internal helper or equivalent
    for trade in trades:
        if trade.get('date') == today and trade.get('action') == 'buy':
            total += float(trade.get('size_dollars', 0.0))
    return total
```

**Implementation notes for Dev:**
- Follow the same file-read pattern as the existing `get_daily_exposure()` — same log file, same parsing logic.
- Filter on `action == 'buy'` and today's date only.
- Do NOT filter on settlement status — include all buys regardless of whether a corresponding sell/expire exists.
- If the log file doesn't exist yet (first run of the day), return `0.0`.

---

### 2b. `get_window_exposure(module, window_open_ts)`

Sums buy `size_dollars` for the given module within a specific 15-minute window. Used by the in-memory counter on startup re-hydration and as a cross-check.

#### BEFORE
*(function does not exist)*

#### AFTER
```python
def get_window_exposure(module: str, window_open_ts: str) -> float:
    """
    Returns the total dollars placed (buy entries) for the given module
    within a specific 15-minute window, identified by its open timestamp.

    Used for Tier 1 window cap enforcement and startup re-hydration
    of the in-memory _window_exposure counter.

    Args:
        module:          Module name string (e.g. 'crypto_15m')
        window_open_ts:  ISO timestamp string of the window open
                         (e.g. '2026-03-30T13:15:00') — same key used
                         in _window_exposure dict in crypto_15m.py

    Returns:
        Total size_dollars of all buy actions logged for this module
        in the specified window.
    """
    total = 0.0
    trades = _read_trades_for_module(module)
    for trade in trades:
        if (trade.get('action') == 'buy'
                and trade.get('window_open_ts') == window_open_ts):
            total += float(trade.get('size_dollars', 0.0))
    return total
```

**Implementation notes for Dev:**
- `window_open_ts` must match the exact string format written to the trade log by `log_trade()`. Confirm the field name is `window_open_ts` in the log schema; adjust if it differs.
- This function is also used at startup to re-hydrate `_window_exposure` for any window that is currently open (i.e., started in the last 15 minutes) — see Section 3, Startup Re-hydration.
- No date filter needed — `window_open_ts` is already window-specific and unique per day.

---

## 3. `crypto_15m.py` Changes

**File:** `agents/ruppert/trader/crypto_15m.py`

This section describes the *what* at a level sufficient for Dev to implement. For the detailed race condition BEFORE/AFTER code, see the Trader's companion spec: `agents/ruppert/trader/specs/crypto-15m-cap-race-spec-2026-03-30.md`.

---

### 3a. Module-Level State (new)

Add at the top of `crypto_15m.py`, after imports:

```python
import threading
from datetime import date

# Per-window exposure counter (in-memory, race-safe)
_window_lock      = threading.Lock()
_window_exposure  = {}    # dict: window_open_ts (str) → float (dollars committed this window)
_daily_wager      = 0.0   # float: total dollars wagered today (all buys)
_daily_wager_date = ''    # str: ISO date string, used to detect midnight rollover
_cb_consecutive_losses = 0  # int: consecutive complete-loss windows (circuit breaker counter)
_cb_last_window_ts     = ''  # str: last window_open_ts seen; triggers CB state file re-read on change
```

---

### 3b. Startup Re-hydration

On module load (or first call to `evaluate_crypto_15m_entry()`), re-hydrate the in-memory counters from the trade/settlement log before any trades are evaluated.

**When to call:** Once per process startup. A simple `_initialized` flag guards against repeated calls.

#### Re-hydration logic (AFTER):

```python
def _rehydrate_state():
    """
    Re-read trade log and settlement log to restore in-memory counters
    after a restart. Call once at startup before first evaluation.
    """
    global _daily_wager, _daily_wager_date, _window_exposure, _cb_consecutive_losses

    today_str = date.today().isoformat()
    _daily_wager_date = today_str

    # 1. Daily wager: sum all buys today from trade log
    _daily_wager = get_daily_wager('crypto_15m')

    # 2. Window exposure: re-hydrate for any window currently open
    #    (i.e., window that started within the last 15 minutes)
    #    This is optional but prevents a brief over-allocation window post-restart.
    #    Use get_window_exposure(module, window_open_ts) for the current window key.
    current_window_ts = _get_current_window_open_ts()  # derive from now()
    if current_window_ts:
        _window_exposure[current_window_ts] = get_window_exposure('crypto_15m', current_window_ts)

    # 3. Circuit breaker: re-read consecutive complete-loss count from state FILE.
    #    The state file is written by settlement_checker.py after each window settles.
    #    It is NOT reconstructed from the settlements log — see note below.
    #    NOTE: If the state file is missing on startup, _read_circuit_breaker_state()
    #    returns 0 (safe, permissive — CB starts with no accumulated loss streak).
    _cb_consecutive_losses = _read_circuit_breaker_state()
    # See Section 4 for the state file format and settlement_checker.py integration.
```

**Notes for Dev:**
- `_get_current_window_open_ts()` should derive the current 15-minute window open timestamp from `datetime.now()` (floor to 15-minute boundary). Use whatever helper already exists for this in the module.
- `_read_circuit_breaker_state()` reads from the circuit breaker state file written by `settlement_checker.py` (see Section 4). Returns 0 if file doesn't exist.

---

### 3c. Entry Check Flow (AFTER)

Replace the existing cap check in `evaluate_crypto_15m_entry()` with the following three-tier check. The checks occur **after** position sizing is calculated and **before** order execution. They run inside a `threading.Lock` to eliminate the race condition.

**Order of checks matters — run in this order:**

```
1. Circuit breaker check  (primary halt control)
2. Tier 2: Daily wager backstop  (execution bug safety net)
3. Tier 1: Window cap  (operative risk control)
```

#### BEFORE (current):
```python
daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
current_exposure = get_daily_exposure('crypto_15m')

if current_exposure >= daily_cap:
    _log_decision(..., 'SKIP', 'DAILY_CAP', ...)
    return
```

#### AFTER (conceptual — Trader's spec has the full code):

```python
# --- Constants (read once, outside lock) ---
window_cap      = capital * config.CRYPTO_15M_WINDOW_CAP_PCT        # ~$166
daily_wager_cap = capital * config.CRYPTO_15M_DAILY_WAGER_CAP_PCT   # ~$3,320 (40%)
cb_n            = config.CRYPTO_15M_CIRCUIT_BREAKER_N               # 3
cb_advisory     = config.CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY        # True

_skip_reason = None

# Required global declarations — without these, Python raises UnboundLocalError
# on assignment to module-level variables inside this function.
global _cb_consecutive_losses, _cb_last_window_ts
global _daily_wager, _daily_wager_date, _window_exposure

with _window_lock:

    # --- Fix (Critical): Re-read CB state file on each window transition ---
    # settlement_checker.py updates the state FILE after each settled window, but
    # does NOT update the in-memory variable. Without this re-read, the circuit
    # breaker can only fire as a startup gate — it never trips mid-session.
    # Re-reading once per window (when window_open_ts changes) is low-cost: one
    # file read per 15-minute window.
    win_key = window_open_ts or 'unknown'
    if win_key != _cb_last_window_ts:
        _cb_consecutive_losses = _read_circuit_breaker_state()
        _cb_last_window_ts = win_key

    # --- Check 0: Circuit breaker ---
    if _cb_consecutive_losses >= cb_n:
        if cb_advisory:
            logger.warning(
                f'[crypto_15m] CIRCUIT BREAKER advisory: {_cb_consecutive_losses} consecutive '
                f'complete-loss windows (threshold={cb_n}). Would halt but ADVISORY mode is on.'
            )
            # Do NOT return — advisory mode continues trading
        else:
            _skip_reason = 'CIRCUIT_BREAKER'

    if not _skip_reason:
        # --- Check 1: Tier 2 daily wager backstop ---
        today_str = date.today().isoformat()
        if _daily_wager_date != today_str:
            _daily_wager = 0.0
            _daily_wager_date = today_str

        if _daily_wager + position_usd > daily_wager_cap:
            # Trim to backstop edge
            trimmed = daily_wager_cap - _daily_wager
            if trimmed < 5.0:
                _skip_reason = 'DAILY_WAGER_BACKSTOP'
            else:
                position_usd = trimmed

    if not _skip_reason:
        # --- Check 2: Tier 1 window cap ---
        # win_key already set above (during CB state re-read)
        win_exp = _window_exposure.get(win_key, 0.0)

        if win_exp + position_usd > window_cap:
            # Trim to window cap edge
            trimmed = window_cap - win_exp
            if trimmed < 5.0:
                _skip_reason = 'WINDOW_CAP'
            else:
                position_usd = trimmed

    if not _skip_reason:
        # Reserve capacity atomically (release on order failure)
        _window_exposure[win_key] = _window_exposure.get(win_key, 0.0) + position_usd
        _daily_wager += position_usd

# --- Outside lock ---
if _skip_reason:
    _log_decision(..., 'SKIP', _skip_reason, ...)
    return

# ... execute order ...

if order_failed:
    # Release reservation on failure
    with _window_lock:
        _window_exposure[win_key] = max(0.0, _window_exposure.get(win_key, 0.0) - position_usd)
        _daily_wager = max(0.0, _daily_wager - position_usd)
    return

log_trade(...)
```

**Key behavioral notes:**
- **Circuit breaker in advisory mode:** Logs a warning, does NOT skip the trade, counter still increments.
- **Circuit breaker in enforcement mode** (`ADVISORY = False`): Adds `CIRCUIT_BREAKER` to skip reason, blocks entry.
- **Tier 2 trim:** If daily wager is near the 40% backstop, trim position to fit rather than skip entirely — unless the trim is below $5 (not worth the order overhead).
- **Tier 1 trim:** If window exposure is near the 2% cap, trim to fit. Minimum viable position is $5.
- **Scale-ins are NOT exempt.** They consume window cap the same as normal entries.
- **Capacity reservation:** Done inside the lock before order execution. Released on order failure. This is the core race condition fix.

---

### 3d. Remove Old Cap Check

**Dev action:** Delete the following lines (or their equivalents) from `evaluate_crypto_15m_entry()`:

```python
# DELETE these lines:
daily_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
current_exposure = get_daily_exposure('crypto_15m')

if current_exposure >= daily_cap:
    _log_decision(..., 'SKIP', 'DAILY_CAP', ...)
    return
```

Also remove `CRYPTO_15M_DAILY_CAP_PCT` from `config.py`. Leave `get_daily_exposure()` in `logger.py` intact — it may be used by other modules.

---

## 4. Settlement Checker Integration

**File:** `agents/ruppert/settlement_checker.py` (or equivalent)

The circuit breaker needs to know when a 15-minute window closes as a **complete loss** (all entries in that window expired at zero). This requires the settlement checker to classify each window after its options expire.

### 4a. What is a "Complete Loss"?

A window is a **complete loss** if and only if:
- All `buy` entries for `module='crypto_15m'` with `window_open_ts = W` have a corresponding settlement with `payout = 0` (or `result = 'loss'` — match whatever field the settlement log uses).
- The window has fully closed (all positions settled, none pending).

A window is **NOT a complete loss** if:
- At least one entry in the window settled with any positive payout (even $0.01).
- Any entry in the window is still pending settlement.

### 4b. Circuit Breaker State File

**Path:** `agents/ruppert/state/crypto_15m_circuit_breaker.json`

**Format:**
```json
{
  "consecutive_losses": 2,
  "last_updated": "2026-03-30T14:30:00",
  "last_window_ts": "2026-03-30T14:15:00",
  "last_window_result": "loss",
  "advisory_would_have_fired_count": 0
}
```

**Fields:**
- `consecutive_losses`: Current streak of consecutive complete-loss windows. Reset to 0 on any winning window.
- `last_updated`: ISO timestamp of last state file write.
- `last_window_ts`: `window_open_ts` of the most recently settled window.
- `last_window_result`: `"loss"` | `"win"` | `"partial_loss"` — result of the last settled window.
- `advisory_would_have_fired_count`: Running count of times circuit breaker would have fired in advisory mode. Used for calibration after 30 trades.

### 4c. Settlement Checker Changes

#### BEFORE:
*(settlement_checker.py classifies individual positions but does not aggregate window-level results or update circuit breaker state)*

#### AFTER:

After processing all settlements for a 15-minute window batch, add:

```python
def _update_circuit_breaker_state(module: str, window_open_ts: str, settlements: list):
    """
    Classify the just-settled window as complete loss, win, or partial loss,
    then update the circuit breaker state file.

    Called by settlement_checker.py after each 15m window's positions are settled.

    Args:
        module:          Module name (e.g. 'crypto_15m')
        window_open_ts:  ISO timestamp of the window that just settled
        settlements:     List of settlement result dicts for this window
                         Each dict must have at minimum: {'payout': float, 'ticker': str}
    """
    if not settlements:
        return  # No settlements to classify — don't update state

    # Use absolute path via _get_paths() to avoid working-directory ambiguity.
    # settlement_checker.py may run from a different cwd than crypto_15m.py reads from;
    # a relative path would write to one location and be read from another.
    # _get_paths()['logs'] returns the absolute base log/state directory.
    # config is importable from settlement_checker.py (confirm import exists; add if not).
    state_path = os.path.join(_get_paths()['logs'], 'crypto_15m_circuit_breaker.json')

    # Classify the window
    payouts = [s.get('payout', 0.0) for s in settlements]
    if all(p == 0.0 for p in payouts):
        window_result = 'loss'        # complete loss
    elif any(p > 0.0 for p in payouts):
        window_result = 'win'         # at least one winner
    else:
        window_result = 'partial_loss'  # shouldn't reach here given above logic

    # Read current state (or initialize)
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {'consecutive_losses': 0, 'advisory_would_have_fired_count': 0}

    # Update consecutive loss counter
    if window_result == 'loss':
        state['consecutive_losses'] = state.get('consecutive_losses', 0) + 1
    else:
        # Any non-complete-loss resets the counter
        state['consecutive_losses'] = 0

    # Track advisory fire count
    cb_n = config.CRYPTO_15M_CIRCUIT_BREAKER_N
    if state['consecutive_losses'] >= cb_n:
        state['advisory_would_have_fired_count'] = state.get('advisory_would_have_fired_count', 0) + 1
        logger.warning(
            f'[circuit_breaker] Advisory: {state["consecutive_losses"]} consecutive complete-loss '
            f'windows for {module} (threshold={cb_n}). advisory_would_have_fired_count='
            f'{state["advisory_would_have_fired_count"]}'
        )

    state['last_updated']      = datetime.utcnow().isoformat()
    state['last_window_ts']    = window_open_ts
    state['last_window_result'] = window_result

    # Atomic write
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    tmp_path = state_path + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, state_path)

    logger.info(f'[circuit_breaker] Window {window_open_ts} result={window_result}, '
                f'consecutive_losses={state["consecutive_losses"]}')
```

**Integration point:** Call `_update_circuit_breaker_state('crypto_15m', window_open_ts, settlements)` after each complete 15-minute window batch is processed — i.e., after all options for that window have been settled or expired.

**Re-hydration on startup:** `crypto_15m.py`'s `_rehydrate_state()` reads this file at startup and populates `_cb_consecutive_losses`. This ensures the circuit breaker state survives restarts.

---

## 5. Summary of All Changes

| # | File | Change | Type |
|---|------|--------|------|
| 1 | `config.py` | Remove `CRYPTO_15M_DAILY_CAP_PCT` | Delete |
| 2 | `config.py` | Add `CRYPTO_15M_WINDOW_CAP_PCT = 0.02` | Add |
| 3 | `config.py` | Add `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40` | Add |
| 4 | `config.py` | Add `CRYPTO_15M_CIRCUIT_BREAKER_N = 3` | Add |
| 5 | `config.py` | Add `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True` | Add |
| 6 | `logger.py` | Add `get_daily_wager(module)` | New function |
| 7 | `logger.py` | Add `get_window_exposure(module, window_open_ts)` | New function |
| 8 | `crypto_15m.py` | Add module-level `_window_lock`, `_window_exposure`, `_daily_wager`, `_cb_consecutive_losses` | Add |
| 9 | `crypto_15m.py` | Add `_rehydrate_state()` with startup re-hydration | New function |
| 10 | `crypto_15m.py` | Remove old daily cap check | Delete |
| 11 | `crypto_15m.py` | Add circuit breaker + Tier 2 + Tier 1 check block (with lock) | Replace |
| 12 | `crypto_15m.py` | Add capacity release on order failure | Add |
| 13 | `settlement_checker.py` | Add `_update_circuit_breaker_state()` | New function |
| 14 | `settlement_checker.py` | Call `_update_circuit_breaker_state()` after each window settles | Add |
| 15 | `state/` | Create `agents/ruppert/state/` directory | New dir |

---

## 6. Calibration Plan

After **30 completed trades** (not windows — individual option positions):

1. Review `advisory_would_have_fired_count` from `crypto_15m_circuit_breaker.json`
2. Review how many times the counter reached 2 (one away from firing) vs 3
3. Review whether complete-loss windows cluster (same macro regime?) or are independent
4. David decides: flip `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = False` to enable enforcement, or adjust `N`
5. Dev implements the flip — no code change needed, just config

**Target calibration outcome:** Circuit breaker fires at most 1–2 times per month under normal conditions, and fires reliably during bad-signal days.

---

## 7. Notes for Dev

1. **Don't implement the race condition BEFORE/AFTER from scratch** — use the Trader's companion spec at `agents/ruppert/trader/specs/crypto-15m-cap-race-spec-2026-03-30.md` as the authoritative code template for the in-memory lock pattern.
2. **`get_daily_exposure()` in `logger.py`:** Do NOT remove — it may be used by other modules (weather module, etc.). Only add the two new functions.
3. **Scale-ins:** The window cap applies to scale-ins equally. No exemption logic needed — just let the existing position sizing flow through the same cap check.
4. **`state/` directory:** Create `agents/ruppert/state/` if it doesn't exist. The settlement checker should `os.makedirs(..., exist_ok=True)` on every write to be safe.
5. **Atomic file write:** Use the `.tmp` + `os.replace()` pattern for `crypto_15m_circuit_breaker.json` to prevent partial reads on restart.
6. **Thread safety of state file:** The state file is written by `settlement_checker.py` and read by `crypto_15m.py` at startup. These run in different contexts, so no lock is needed on the file itself — it's written once per window settlement and read once per startup.

---

*End of spec.*
