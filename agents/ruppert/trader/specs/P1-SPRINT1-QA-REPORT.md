# P1 Sprint 1 — QA Report: Signal Integrity
**Sprint:** P1-1  
**Date:** 2026-04-03  
**QA Agent:** Subagent (Claude Sonnet)  
**Status:** ✅ APPROVED — All 8 issues pass. Ready to commit.

---

## Summary

All three batches reviewed against:
- `agents/ruppert/trader/specs/P1-SPRINT1-SPEC.md`
- `agents/ruppert/strategist/specs/P1-SPRINT1-STRATEGIST-SPEC.md`
- `agents/ruppert/dev/P1-SPRINT1-DEV-NOTES.md`

Files inspected:
- `agents/ruppert/trader/crypto_15m.py` — ISSUE-129, ISSUE-114, ISSUE-069, ISSUE-105
- `agents/ruppert/strategist/strategy.py` — ISSUE-104
- `agents/ruppert/data_analyst/polymarket_client.py` — ISSUE-116
- `agents/ruppert/data_analyst/ws_feed.py` — ISSUE-096
- `agents/ruppert/trader/crypto_client.py` — ISSUE-032

**Result: All 8 issues implemented correctly per spec. No blocking defects. Three minor observations noted below (non-blocking).**

---

## Batch 1: ISSUE-129 + ISSUE-104

### ISSUE-129 — Near-Zero OI Delta Guard (`crypto_15m.py`)

**Spec requirement:** Guard in `fetch_open_interest_delta()` changed from `prev_oi == 0` to `prev_oi < 1e-6`. Returns `{'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}` on near-zero.

**Actual code** (in `fetch_oi_conviction()` — function was renamed post-spec authoring, not a sprint concern):

```python
if prev_oi is _CACHE_MISS or prev_oi < 1e-6:  # ISSUE-129: guard near-zero prev_oi
    return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}
```

**Verdict: ✅ PASS**
- Guard uses `< 1e-6` (not `== 0`) — correct.
- Returns `oi_z: 0.0` on near-zero — correct.
- `_CACHE_MISS` sentinel check retained — correct.
- No change to `_z_score()` or rolling window logic — correct (spec said no change needed there).

---

### ISSUE-104 — `_module_cap_missing` Init (`strategy.py`)

**Spec requirement:** `_module_cap_missing = False` initialized **before** the `if module is not None:` block.

**Actual code** in `should_enter()`:

```python
# --- Per-module daily cap ---
_module_cap_missing = False  # ISSUE-104: init before if block (linter hygiene)
if module is not None:
    _module_key = module.upper() + '_DAILY_CAP_PCT'
    _module_cap = getattr(config, _module_key, None)
    _module_cap_missing = _module_cap is None
    if not _module_cap_missing:
        ...
```

**Verdict: ✅ PASS**
- Initialization `= False` placed exactly one line before `if module is not None:` — correct.
- Runtime behavior unchanged (Python short-circuit already prevented NameError) — correct.
- Linter-clean: `_module_cap_missing` is always defined before any read — correct.
- Later guard `if module is not None and _module_cap_missing:` remains unchanged — correct.

---

## Batch 2: ISSUE-114 + ISSUE-069 + ISSUE-116

### ISSUE-069 — WARNING on Missing Weight Keys (`crypto_15m.py`)

**Spec requirement:** WARNING logged at module load when any weight key is MISSING from config. Uses `hasattr()` (not value comparison). Missing key names included in warning message. Must appear BEFORE ISSUE-114 ValueError in file.

**Actual code:**

```python
_W_TFI_DEFAULT  = 0.42
_W_OBI_DEFAULT  = 0.25
_W_MACD_DEFAULT = 0.15
_W_OI_DEFAULT   = 0.18

W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  _W_TFI_DEFAULT)
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  _W_OBI_DEFAULT)
W_MACD = getattr(config, 'CRYPTO_15M_DIR_W_MACD', _W_MACD_DEFAULT)
W_OI   = getattr(config, 'CRYPTO_15M_DIR_W_OI',   _W_OI_DEFAULT)

_missing_weight_keys = [
    key for key, present in [
        ('CRYPTO_15M_DIR_W_TFI',  hasattr(config, 'CRYPTO_15M_DIR_W_TFI')),
        ('CRYPTO_15M_DIR_W_OBI',  hasattr(config, 'CRYPTO_15M_DIR_W_OBI')),
        ('CRYPTO_15M_DIR_W_MACD', hasattr(config, 'CRYPTO_15M_DIR_W_MACD')),
        ('CRYPTO_15M_DIR_W_OI',   hasattr(config, 'CRYPTO_15M_DIR_W_OI')),
    ] if not present
]
if _missing_weight_keys:
    logger.warning(
        'crypto_15m: signal weight config keys missing: %s. '
        'Using fallback defaults: TFI=%.2f OBI=%.2f MACD=%.2f OI=%.2f',
        ', '.join(_missing_weight_keys),
        W_TFI, W_OBI, W_MACD, W_OI,
    )
```

**Verdict: ✅ PASS**
- Uses `hasattr()` to detect absence, not value comparison — correct.
- Missing key names joined into warning message — correct.
- Fallback values (TFI, OBI, MACD, OI) logged alongside key names — correct.
- Block appears BEFORE the ISSUE-114 ValueError guard — correct sequencing.

---

### ISSUE-114 — Weight Sum `raise ValueError` (`crypto_15m.py`)

**Spec requirement:** `raise ValueError` (not `assert`) after weights defined. Error message includes actual sum. Tolerance `1e-6`. Appears AFTER ISSUE-069 warning block.

**Actual code:**

```python
# ISSUE-114: raise ValueError (not assert — immune to -O flag) if weights don't sum to 1.0
_weights_sum = W_TFI + W_OBI + W_MACD + W_OI
if abs(_weights_sum - 1.0) >= 1e-6:
    raise ValueError(
        f"CRYPTO_15M signal weights must sum to 1.0, got {_weights_sum:.6f} "
        f"(TFI={W_TFI}, OBI={W_OBI}, MACD={W_MACD}, OI={W_OI})"
    )
```

**Verdict: ✅ PASS**
- `raise ValueError` (not `assert`) — immune to `-O` flag — correct.
- Error message includes actual sum via `{_weights_sum:.6f}` — correct.
- All four weight values included in message for debuggability — correct.
- Tolerance `abs(...) >= 1e-6` — correct.
- Placed AFTER ISSUE-069 warning block — correct sequencing.

---

### ISSUE-116 — Polymarket ETH Alias Word-Boundary Fix (`polymarket_client.py`)

**Spec requirements:**
1. `import re` added.
2. `_ALIASES_REQUIRING_WORD_BOUNDARY` at module level (not inside function).
3. `_asset_in_title()` uses word-boundary regex for short tickers.
4. `get_smart_money_signal()` also fixed with `len(keyword_lower) <= 4` guard.
5. "will steth lose its peg?" → `False` for ETH.
6. "ethereum price prediction" → `True` for ETH.

**Actual code — `import re`:**
```python
import re  # (present at top of file)
```
✅ Present.

**Module-level constant:**
```python
_ALIASES_REQUIRING_WORD_BOUNDARY: set[str] = {"eth", "sol", "xrp", "btc", "doge"}
```
✅ At module level (not inside any function). Dev added "doge" beyond the spec's `{"eth", "sol", "xrp", "btc"}` — the spec explicitly noted Dev should consider adding it. Acceptable.

**`_asset_in_title()` fix:**
```python
def _asset_in_title(asset: str, title_lower: str) -> bool:
    aliases = _ASSET_ALIASES.get(asset.upper(), [asset.lower()])
    for alias in aliases:
        if alias in _ALIASES_REQUIRING_WORD_BOUNDARY:
            if re.search(r'\b' + re.escape(alias) + r'\b', title_lower):
                return True
        else:
            if alias in title_lower:
                return True
    return False
```
✅ Word-boundary for short tickers, plain match for longer aliases.

**`get_smart_money_signal()` fix:**
```python
if len(keyword_lower) <= 4:
    if not re.search(r'\b' + re.escape(keyword_lower) + r'\b', title_lower_pos):
        continue
else:
    if keyword_lower not in title_lower_pos:
        continue
```
✅ Correct `len <= 4` boundary guard.

**`_ASSET_ALIASES` — ETH aliases updated:**
```python
"ETH":  ["eth", "ethereum"],
```
Dev added "ethereum" to support the spec's test case `"will ethereum price be above $2000?" → True`. Correct.

**Test case verification — "will steth lose its peg?" for ETH:**
- ETH aliases: `["eth", "ethereum"]`.
- "eth": in `_ALIASES_REQUIRING_WORD_BOUNDARY` → `re.search(r'\beth\b', "will steth lose its peg?")`.
  - In "steth", "t" (word char) precedes "e", so `\b` before "e" does NOT fire. No standalone "eth" elsewhere.
  - Result: no match.
- "ethereum": plain substring match → "ethereum" not in title → no match.
- **Returns `False` ✅**

**Test case verification — "ethereum price prediction" for ETH:**
- "eth": `re.search(r'\beth\b', "ethereum price prediction")` → "eth" appears inside "ethereum" but "e" is preceded by nothing (start of word) — actually, "ethereum" starts with "eth": position 0-2 are e-t-h, position 3 is 'e'. So `\beth` matches at position 0 (word boundary at start of string), but then we need `\b` after "h" — position after "h" is "e" (word char), so `\b` after "h" does NOT fire. So regex does NOT match "eth" inside "ethereum".
- "ethereum": plain substring match → "ethereum" IS in "ethereum price prediction" → match!
- **Returns `True` ✅**

**Verdict: ✅ PASS** — Both critical test cases verified. Both call sites fixed.

---

## Batch 3: ISSUE-096 + ISSUE-032 + ISSUE-105

### ISSUE-096 — WS Reconnect Exponential Backoff (`ws_feed.py`)

**Spec requirements:**
- `_reconnect_delay` declared OUTSIDE `while True` (function scope).
- PATH 1 (timeout break): sleeps and advances backoff.
- PATH 2 (exception): sleeps and advances backoff.
- Backoff resets on successful connect, using `_write_heartbeat()` as the anchor.
- PATH 1 sleep block inside outer `try:` but outside `async with ws:`.
- `finally: market_cache.persist()` unaffected.

**Actual code (structural):**

```python
_reconnect_delay = 5    # ISSUE-096: exponential backoff — starts at 5s, OUTSIDE while True
_reconnect_max   = 60   # ISSUE-096: caps at 60s

while True:
    try:
        ...
        async with websockets.connect(...) as ws:
            # ISSUE-096: reset backoff HERE — connection is live
            _reconnect_delay = 5
            _write_heartbeat()  # heartbeat written on every successful reconnect
            ...
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        log_activity('[WS Feed] recv timeout (30s silence) — reconnecting')
                        break   # PATH 1 exit
                    ...
            finally:
                fallback_task.cancel()
                ...

        # PATH 1 lands here: inside outer try, outside async with ws:
        log_activity(f'[WS Feed] Timeout disconnect — reconnecting in {_reconnect_delay}s')
        await asyncio.sleep(_reconnect_delay)
        _reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)

    except Exception as e:
        # PATH 2: exception-based disconnect
        print(f'  [WS Feed] Disconnected: {e} — reconnecting in {_reconnect_delay}s')
        log_activity(f'[WS Feed] Disconnected: {e}')
        try:
            await position_tracker.recovery_poll_positions()
        except Exception as re:
            logger.warning('[WS Feed] Recovery poll failed: %s', re)
        await asyncio.sleep(_reconnect_delay)
        _reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)

    finally:
        market_cache.persist()
```

**Verdict: ✅ PASS**
- `_reconnect_delay = 5` and `_reconnect_max = 60` declared OUTSIDE `while True` — correct.
- Backoff reset `_reconnect_delay = 5` immediately after `async with websockets.connect()` succeeds, before `_write_heartbeat()` — consistent with spec anchor intent.
- PATH 1 (timeout): `asyncio.sleep(_reconnect_delay)` + `min(_reconnect_delay * 2, _reconnect_max)` — correct.
- PATH 2 (exception): `asyncio.sleep(_reconnect_delay)` + `min(_reconnect_delay * 2, _reconnect_max)` — correct.
- PATH 1 sleep block is inside outer `try:` but outside `async with ws:` — correct structural placement.
- `finally: market_cache.persist()` still runs for both paths — correct, unaffected.
- Recovery poll (`recovery_poll_positions()`) on PATH 2 wrapped in its own try/except — correct.

---

### ISSUE-032 — Wallet Path Fix (`crypto_client.py`)

**Spec requirements:**
- `_WALLETS_FILE` uses `env_config.get_paths()['logs']`.
- `env_config` imported at module level (no circular import risk — confirmed by spec).
- WARNING logged if wallet file exists but has no usable wallet data (empty list or missing key).
- Falls back to hardcoded stub.

**Actual code:**

```python
from agents.ruppert.env_config import get_paths as _env_get_paths  # ISSUE-032: wallet path fix
...
_WALLETS_FILE = _env_get_paths()['logs'] / 'smart_money_wallets.json'
```

```python
raw = data.get('wallets', [])
if raw and isinstance(raw, list):
    ...  # success path
else:
    # ISSUE-032: warn if wallet file exists but has no usable wallet data
    logger.warning(
        '_load_wallets: wallet file exists but contains no wallets '
        '(key missing or empty list) — using hardcoded fallback'
    )
# fallthrough to stub
```

**Verdict: ✅ PASS**
- `env_config` imported at module level — correct (no circular import risk confirmed).
- `_WALLETS_FILE` resolves to `env_config.get_paths()['logs'] / 'smart_money_wallets.json'` — same directory `wallet_updater.py` writes to — correct.
- Empty file case: `json.loads('')` raises `json.JSONDecodeError`, caught by outer `except Exception as e:` which logs a warning and falls through to stub — correct (existing handler, no change needed per spec).
- Missing `wallets` key / empty list: caught by the new `else:` branch with `logger.warning(...)` — correct.
- Hardcoded fallback stub (`TOP_TRADER_WALLETS`) retained — correct.
- `wallet_source` in `get_polymarket_smart_money()` will correctly report `'dynamic'` when live file present — correct (uses `_WALLETS_FILE.exists()` check).

---

### ISSUE-105 — Post-Trim `actual_spend` Reservation (`crypto_15m.py`)

**Spec requirements:**
- `contracts` computed INSIDE lock, AFTER all trim logic, using final post-trim `position_usd`.
- `actual_spend = _contracts * (entry_price / 100.0)` — inside lock.
- Reservation (`_window_exposure`, `_daily_wager`) uses `actual_spend`.
- `actual_spend` and `contracts` assigned to enclosing scope inside lock.
- Outside-lock `contracts` assignment removed.
- Rollback uses `actual_spend`.
- `size_dollars` in log record uses `actual_spend`.

**Actual code:**

```python
# ISSUE-105: Step 1 — declare before lock; will be set inside lock if trade proceeds
actual_spend = None
contracts    = None

with _window_lock:
    # ... circuit breaker check ...
    # ... daily backstop check / trim ...
    # ... window cap check / trim ...

    if not _skip_reason:
        # Step 2: Compute contracts from FINAL post-trim position_usd
        _contracts = max(1, int(position_usd / (entry_price / 100.0)))
        # Step 3: Compute actual_spend = contracts × entry_price/100
        _actual_spend = _contracts * (entry_price / 100.0)
        # Step 4: Reserve actual_spend (not position_usd)
        _window_exposure[win_key] = _window_exposure.get(win_key, 0.0) + _actual_spend
        _daily_wager += _actual_spend
        # Step 5: Expose to enclosing scope for rollback and log record
        actual_spend = _actual_spend
        contracts = _contracts

# Outside lock — execute:
# ISSUE-105: contracts and actual_spend set inside lock above; do NOT recompute here
...

# Rollback on order failure:
with _window_lock:
    _window_exposure[win_key] = max(0.0, _window_exposure.get(win_key, 0.0) - actual_spend)
    _daily_wager = max(0.0, _daily_wager - actual_spend)

# Log record:
'size_dollars': round(actual_spend, 2),  # ISSUE-105: use actual_spend

# log_trade call:
log_trade(opp, actual_spend, contracts, order_result)
```

**Verdict: ✅ PASS**
- Contracts computed INSIDE lock after all trim logic — correct.
- `actual_spend = _contracts * (entry_price / 100.0)` — correct formula.
- Reservation uses `actual_spend` (not `position_usd`) — correct.
- `actual_spend` and `contracts` assigned to enclosing function scope inside lock — correct.
- Comment explicitly marks that outside-lock recomputation is removed — correct.
- Rollback uses `actual_spend` — correct.
- `size_dollars` in log record: `round(actual_spend, 2)` — correct.
- `log_trade(opp, actual_spend, contracts, order_result)` — correct.
- `actual_spend` is `None` only when `_skip_reason` is set; function returns early before rollback in that case — safe, no `None`-arithmetic risk.

---

## Non-Blocking Observations

These are informational only — none block approval.

**OBS-1: `fetch_oi_conviction()` vs `fetch_open_interest_delta()`**  
The spec references the function as `fetch_open_interest_delta()`, but the actual function in code is `fetch_oi_conviction()`. This is a pre-existing rename, unrelated to this sprint. The ISSUE-129 fix is correctly applied to the function that actually computes the OI delta. No action needed.

**OBS-2: "doge" added to `_ALIASES_REQUIRING_WORD_BOUNDARY`**  
The spec's `_ALIASES_REQUIRING_WORD_BOUNDARY` set was `{"eth", "sol", "xrp", "btc"}`. Dev added `"doge"`. The spec notes: "Dev should consider adding it for consistency. It's low risk either way (no known tokens starting with 'doge'), but consistent is better." Dev made the right call proactively.

**OBS-3: `position_tracker.add_position()` still uses `position_usd` for `size_dollars`**  
The ISSUE-105 spec says to update `size_dollars` in the log record. Dev correctly updated the trade log record (`opp['size_dollars'] = round(actual_spend, 2)`). The `position_tracker.add_position()` call uses a separate `size_dollars` parameter for exit-tracking purposes, and the spec does not require updating it. This is in-scope behavior. Minor inconsistency: position tracker's `size_dollars` may differ from the trade log's `size_dollars` by a few cents of integer rounding. Not a defect per spec.

---

## Commit Messages (Per Batch)

**Batch 1:**
```
fix: near-zero OI delta guard (ISSUE-129) + init _module_cap_missing before if block (ISSUE-104)

ISSUE-129: crypto_15m.py — prev_oi == 0 guard extended to prev_oi < 1e-6 in fetch_oi_conviction()
to prevent near-zero division corrupting the rolling OI window.

ISSUE-104: strategy.py — _module_cap_missing = False initialized before if module is not None:
block. Hygiene fix; no runtime behavior change.
```

**Batch 2:**
```
fix: weight integrity guards (ISSUE-069, ISSUE-114) + ETH alias word-boundary (ISSUE-116)

ISSUE-069: crypto_15m.py — WARNING logged at module load when weight config keys are missing
from config. Uses hasattr() to detect absence; missing key names included in message.

ISSUE-114: crypto_15m.py — raise ValueError (not assert) if signal weights don't sum to 1.0
within 1e-6. Error message includes actual sum. Fires at import; blocks trading on bad weights.
ISSUE-069 warning sequenced before ISSUE-114 ValueError per spec.

ISSUE-116: polymarket_client.py — word-boundary regex in _asset_in_title() prevents
"eth" matching "steth", "etherfi", "ethena". get_smart_money_signal() also fixed.
_ALIASES_REQUIRING_WORD_BOUNDARY constant added at module level.
"ethereum" added to ETH aliases to support long-form title matching.
```

**Batch 3:**
```
fix: WS exponential backoff (ISSUE-096) + wallet path (ISSUE-032) + actual_spend reservation (ISSUE-105)

ISSUE-096: ws_feed.py — exponential backoff (5→10→20→60s) for both reconnect paths.
_reconnect_delay declared outside while True. PATH 1 (timeout) and PATH 2 (exception)
both sleep and advance backoff. Reset to 5s on successful connect via _write_heartbeat().

ISSUE-032: crypto_client.py — _WALLETS_FILE now uses env_config.get_paths()['logs']
(was Path(__file__).parent / 'logs'). No circular import risk (env_config is stdlib-only).
WARNING logged on empty/missing wallets case with fallback to hardcoded stub.

ISSUE-105: crypto_15m.py — contracts and actual_spend computed inside _window_lock after
all trim logic. Reservation, rollback, and size_dollars log field all use actual_spend
(not pre-floor position_usd). Eliminates systematic overcounting of window exposure.
```

---

_QA sign-off: All 8 issues verified against source. No blocking defects. Sprint P1-1 approved for commit._
