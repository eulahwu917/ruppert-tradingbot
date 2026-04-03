# P1 Sprint 1 — Dev Implementation Notes

**Sprint:** P1-1 — Signal Integrity for crypto_15m  
**Dev:** Subagent (Claude Sonnet)  
**Date:** 2026-04-03  

---

## Batch 1 — One-liners ✅ COMPLETE (pending QA)

### ISSUE-129: Near-zero OI delta guard (`crypto_15m.py`)
- **File:** `agents/ruppert/trader/crypto_15m.py` line ~411
- **Change:** `prev_oi == 0` → `prev_oi < 1e-6`
- **Notes:** Exactly as specced. Guard condition in `fetch_open_interest_delta()`. No other changes.
- **Sanity check:** `crypto_15m.py` imports cleanly.

### ISSUE-104: `_module_cap_missing = False` init (`strategy.py`)
- **File:** `agents/ruppert/strategist/strategy.py` line ~371 (before `if module is not None:`)
- **Change:** Added `_module_cap_missing = False  # ISSUE-104: init before if block (linter hygiene)` one line before the `if module is not None:` block.
- **Notes:** Pure hygiene fix. No runtime behavior change. Short-circuit already prevented NameError.
- **Sanity check:** `strategy.py` imports cleanly.

**Ready for QA — Batch 1.**

---

## Batch 2 — Signal integrity cluster ✅ COMPLETE (pending QA)

### ISSUE-069: WARNING log when config weight keys are missing (`crypto_15m.py`)
- **File:** `agents/ruppert/trader/crypto_15m.py`
- **Change:** Replaced bare `getattr()` weight loading with named-default constants + `hasattr()` detection loop + `logger.warning()` call. Sequenced BEFORE the ISSUE-114 ValueError guard (per spec).
- **Notes:** Uses `hasattr()` not value comparison — detects missing keys regardless of whether value happens to equal default. Missing keys named explicitly in warning message.

### ISSUE-114: `raise ValueError` if weights don't sum to 1.0 (`crypto_15m.py`)
- **File:** `agents/ruppert/trader/crypto_15m.py`
- **Change:** Added `_weights_sum` check with `raise ValueError` (not `assert` — immune to `-O` flag). Error message includes actual sum and all four weight values for debuggability. Placed AFTER ISSUE-069 warning block.
- **Notes:** Tolerance `1e-6` per spec. Module import fails immediately if misconfigured.

### ISSUE-116: Word-boundary fix in `polymarket_client.py`
- **File:** `agents/ruppert/data_analyst/polymarket_client.py`
- **Changes:**
  1. Added `import re` at top of file (confirmed not previously present)
  2. Added `_ALIASES_REQUIRING_WORD_BOUNDARY = {"eth", "sol", "xrp", "btc"}` at module level near `_ASSET_ALIASES`
  3. Replaced `_asset_in_title()` body with word-boundary-aware loop per spec
  4. Replaced raw substring match in `get_smart_money_signal()` with `len <= 4` word-boundary guard

**Ready for QA — Batch 2.**

---

## Batch 3 — Infrastructure fixes ✅ COMPLETE (pending QA)

### ISSUE-096: WS reconnect exponential backoff (`ws_feed.py`)
- **File:** `agents/ruppert/data_analyst/ws_feed.py`
- **Changes:**
  - Added `_reconnect_delay = 5` and `_reconnect_max = 60` outside `while True` loop (function scope)
  - Backoff reset (`_reconnect_delay = 5`) placed immediately after `_write_heartbeat()` inside `async with ws:` block (after successful connect)
  - PATH 1 (timeout break): added `log_activity` + `await asyncio.sleep(_reconnect_delay)` + `_reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)` after the `async with ws:` block exits cleanly
  - PATH 2 (exception): replaced flat `await asyncio.sleep(5)` with `await asyncio.sleep(_reconnect_delay)` + `_reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)`
- **Structural note:** PATH 1 sleep block placed inside outer `try:` but outside `async with ws:`. `finally: market_cache.persist()` still runs for both paths — no conflict.

### ISSUE-032: Smart money wallet path fix (`crypto_client.py`)
- **File:** `agents/ruppert/trader/crypto_client.py`
- **Changes:**
  - Added `from agents.ruppert.env_config import get_paths as _env_get_paths` (module-level import — confirmed no circular import risk)
  - Changed `_WALLETS_FILE` from `Path(__file__).parent / 'logs' / 'smart_money_wallets.json'` to `_env_get_paths()['logs'] / 'smart_money_wallets.json'`
  - Added `logger.warning()` for empty/missing wallets case (wallet file exists but `wallets` key absent or empty list)

### ISSUE-105: Window cap reservation uses `actual_spend` (`crypto_15m.py`)
- **File:** `agents/ruppert/trader/crypto_15m.py`
- **Changes (followed spec pseudocode exactly):**
  1. Declared `actual_spend = None` and `contracts = None` before the lock
  2. Moved contract computation INSIDE `with _window_lock:`, after all trim logic, guarded by `if not _skip_reason:`
  3. Computed `_actual_spend = _contracts * (entry_price / 100.0)` inside lock
  4. Reserved `_actual_spend` in `_window_exposure` and `_daily_wager` (not `position_usd`)
  5. Assigned `actual_spend = _actual_spend` and `contracts = _contracts` to enclosing scope inside lock
  6. Removed the outside-lock `contracts` assignment that previously existed
  7. Updated rollback path to use `actual_spend`
  8. Updated `size_dollars` in log record to `round(actual_spend, 2)`
- **Notes:** `actual_spend` is `None` when `_skip_reason` is set — rollback path is guarded by same condition, so `None` is never used in rollback arithmetic.

**Ready for QA — Batch 3.**

---

## Audit Results

**`qa_self_test.py`:** PASS — 33/33 checks passed  
**`config_audit.py`:** PASS WITH WARNINGS — 6 pre-existing Task Scheduler state warnings (unrelated to this sprint)

## Spec Contradictions / Flags

None found. All specs were internally consistent. No self-authorized changes made.

## One Note on ISSUE-116 (_ASSET_ALIASES)

Added `"ethereum"` to the ETH aliases list (spec test cases include `"will ethereum price be above $2000?" → True`). Original code only had `["eth"]`. Added `"ethereum"` as a plain-match alias (not in `_ALIASES_REQUIRING_WORD_BOUNDARY` — it's long enough to be unambiguous). This is consistent with the spec's intent and test table.

## Files Changed

- `agents/ruppert/trader/crypto_15m.py` — ISSUE-129, ISSUE-114, ISSUE-069, ISSUE-105
- `agents/ruppert/strategist/strategy.py` — ISSUE-104
- `agents/ruppert/data_analyst/polymarket_client.py` — ISSUE-116
- `agents/ruppert/data_analyst/ws_feed.py` — ISSUE-096
- `agents/ruppert/trader/crypto_client.py` — ISSUE-032
