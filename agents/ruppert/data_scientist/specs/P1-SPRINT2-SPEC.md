# P1 Sprint 2 Spec — Settlement + Capital Accuracy
_Authored: 2026-04-03 | Data Scientist agent_
_Sprint: P1-2 | Basis: P1-DS-REVIEW.md_
_Revised: 2026-04-03 | Adversarial review response — DS-P1-Sprint2-Revision_

---

## Revision Summary (2026-04-03)

Four issues required spec corrections after adversarial review:

| Issue | Problem Found | Fix |
|-------|--------------|-----|
| ISSUE-027 | Spec incorrectly stated post_trade_monitor.py was already correct — it has the same exit_price=99 win bug | Added post_trade_monitor.py as a second fix target for the win formula |
| ISSUE-110 | Spec comment said "1s, 2s, 4s" but actual code delays are 1s, 2s (no sleep after last attempt). Also missed bare `continue` in post_trade_monitor.py | Fixed delay description; added post_trade_monitor.py to retry scope |
| ISSUE-030 | Spec did not make ordering explicit: exit_pnl is computed AFTER exit_opp dict is built in post_trade_monitor.py. Risk of NameError if Dev adds pnl to dict literal before it's defined | Added explicit ordering requirement with correct code sequence |
| ISSUE-102 | Spec only fixed TICKER_MODULE_MAP — but _cap_map in data_agent.py also missing xrp/doge entries, leaving those modules uncapped after the fix | Added _cap_map fix as a required second step in ISSUE-102 |

---

## Sprint Overview

Four issues. Two in the same function. All affect P&L accuracy — some silently, some catastrophically.

| Issue | File | What breaks | Effort |
|-------|------|-------------|--------|
| ISSUE-026 + ISSUE-027 | settlement_checker.py, post_trade_monitor.py | Win P&L understated; loss P&L formula wrong | Small |
| ISSUE-110 | settlement_checker.py, post_trade_monitor.py | Transient API errors skip settlement for 24h | Small |
| ISSUE-030 | ruppert_cycle.py, post_trade_monitor.py | `pnl` field absent from cycle/monitor exits | Small-Medium |
| ISSUE-102 | data_agent.py (TICKER_MODULE_MAP + _cap_map) | Threshold daily XRP/DOGE trades misclassified AND uncapped | Small |

---

## ISSUE-026 + ISSUE-027 — Fix win/loss formulas in settlement_checker.py AND post_trade_monitor.py

### Files
- `environments/demo/settlement_checker.py` — `compute_pnl()` function (~line 72–114)
- `agents/ruppert/trader/post_trade_monitor.py` — `check_settlements()` function (~line 185–200)

**Both files have ISSUE-026 (exit_price=99 for wins). Fix both.**

### What the code does now

**settlement_checker.py — compute_pnl():**
```python
if side_won:
    exit_price = 99          # BUG-026: should be 100
    pnl = (99 - entry_price) * contracts / 100
else:
    exit_price = 1
    pnl = -size_dollars      # BUG-027: wrong formula — uses size_dollars, not entry math
```

**post_trade_monitor.py — check_settlements():**
```python
if side == 'yes':
    if result == 'yes':
        exit_price = 99          # BUG-026: SAME bug — should be 100
        pnl = (99 - entry_price) * contracts / 100
    else:
        exit_price = 1
        pnl = -(entry_price * contracts / 100)   # loss formula IS correct here ✓
else:  # side == 'no'
    if result == 'no':
        exit_price = 99          # BUG-026: SAME bug — should be 100
        pnl = (99 - entry_price) * contracts / 100
    else:
        exit_price = 1
        pnl = -(entry_price * contracts / 100)   # loss formula IS correct here ✓
```

**Note:** post_trade_monitor.py's loss formula is already correct — only the win branch needs fixing. Do not change the loss branch in post_trade_monitor.py.

### ISSUE-026: Wrong exit price for wins (both files)

Kalshi pays 100¢ per contract when a position wins. Both files set `exit_price = 99` in the win branch, which means every win is short-changed by 1¢ per contract. On a 1000-contract position, that's $10 of invisible P&L per trade. The P&L formula `(99 - entry_price)` inherits this error — a 50¢ entry that wins should net 50¢ per contract, but the formula gives 49¢.

**Fix (settlement_checker.py):** Change `exit_price = 99` to `exit_price = 100` in the win branch. Update the formula to `(100 - entry_price) * contracts / 100`.

**Fix (post_trade_monitor.py):** Same change in ALL win branches of `check_settlements()` — both the `side == 'yes'` and `side == 'no'` win cases use `exit_price = 99`. Change both to `exit_price = 100` and update the formula to `(100 - entry_price) * contracts / 100`.

### ISSUE-027: Loss formula is asymmetric (settlement_checker.py only)

The win formula uses `(exit_price - entry_price) * contracts / 100` — contract-based math. The loss formula in settlement_checker.py uses `-size_dollars` — a completely different basis. These produce inconsistent results:

- A 1000-contract position at 10¢ entry has `size_dollars = $100`. Loss formula gives `-$100`.
- Correct loss: `-(10 * 1000 / 100) = -$100`. In this case the same, but `size_dollars` may be rounded or stale.
- The asymmetry risk: `size_dollars` is a display/stored field that may not match `entry_price × contracts` exactly.

The correct loss formula is: `pnl = -(entry_price * contracts / 100)` — same entry math as the win side.

**Fix (settlement_checker.py only):** The loss branch. post_trade_monitor.py already uses the correct formula for losses — do not change it.

### What changes

**settlement_checker.py — compute_pnl() — win branch:**
```python
# Before
exit_price = 99
pnl = (99 - entry_price) * contracts / 100

# After
exit_price = 100
pnl = (100 - entry_price) * contracts / 100
```

**settlement_checker.py — compute_pnl() — loss branch:**
```python
# Before
exit_price = 1
pnl = -size_dollars

# After
exit_price = 1
pnl = -(entry_price * contracts / 100)
```

**post_trade_monitor.py — check_settlements() — win branches (both side=='yes' and side=='no' win cases):**
```python
# Before (in each win branch)
exit_price = 99
pnl = (99 - entry_price) * contracts / 100

# After (in each win branch)
exit_price = 100
pnl = (100 - entry_price) * contracts / 100
```

**post_trade_monitor.py — loss branches: NO CHANGE.** They already use `-(entry_price * contracts / 100)` correctly.

### What trading behavior changes

Every future settlement that goes through either file will now use the correct 100¢ payout for wins. Two settlement paths were previously diverging; after this fix they are consistent. Historical records are already logged — this fix only affects new settlements going forward.

### What could go wrong

- If `entry_price` is missing or zero (fell through to the 50¢ fallback), the settlement_checker.py loss P&L changes from `-size_dollars` to `-(50 * contracts / 100)`. For large contract counts at low prices, these can differ. The fallback is documented in the existing code and is acceptable.
- `compute_closed_pnl_from_logs()` in logger.py sums the `pnl` field directly — it does NOT recompute from `exit_price`. So changing exit_price from 99 to 100 in settle records is safe; the stored `exit_price` field will now correctly read `100c` for wins.
- `action_detail` strings referencing `exit_price` will now print `100c` — this is correct.

---

## ISSUE-110 — Add retry with backoff to API calls in settlement_checker.py AND post_trade_monitor.py

### Files
- `environments/demo/settlement_checker.py` — `check_settlements()` function (~line 150)
- `agents/ruppert/trader/post_trade_monitor.py` — `check_settlements()` function (~line 150)

**Both files have the same bare `continue` on API errors. Fix both.**

### What the code does now

**settlement_checker.py:**
```python
try:
    market = client.get_market(ticker)
except Exception as e:
    print(f"  [ERROR] API error for {ticker}: {e}")
    error_count += 1
    continue   # skip — no retry
```

**post_trade_monitor.py:**
```python
try:
    market = client.get_market(ticker)
except Exception as e:
    print(f"  [Settlement Checker] API error for {ticker}: {e}")
    continue   # same bare continue — no retry
```

A single API exception silently skips the position until the next scheduled run. settlement_checker.py runs daily — positions skip for ~24 hours. post_trade_monitor.py runs every 30 minutes — positions skip ~30 minutes per transient failure. In both cases, P&L records are not written and capital stays "deployed" for the duration.

### What changes

Replace the bare `continue` in both files with a retry loop. 3 attempts, exponential backoff.

**Delay sequence (corrected):**
- Attempt 0 fails → wait 1s → attempt 1
- Attempt 1 fails → wait 2s → attempt 2
- Attempt 2 fails → skip (no sleep after final attempt)

Total max wait per failing ticker: **3 seconds** (1s + 2s). The formula `wait = 2 ** attempt` with `if attempt < MAX_RETRIES - 1` produces delays of 1s and 2s only — there is no 4s delay because the last attempt does not sleep before the loop exits.

**Pattern to apply in both files:**

```python
import time  # already present in settlement_checker.py; verify in post_trade_monitor.py

MAX_RETRIES = 3
market = None
for attempt in range(MAX_RETRIES):
    try:
        market = client.get_market(ticker)
        break
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt   # attempt=0 → 1s, attempt=1 → 2s (no sleep after last attempt)
            print(f"  [WARN] API error for {ticker} (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
            time.sleep(wait)
        else:
            print(f"  [ERROR] API error for {ticker} after {MAX_RETRIES} attempts: {e} — skipping")
            error_count += 1  # only in settlement_checker.py — adjust for post_trade_monitor.py if it tracks errors differently

if market is None:
    continue
```

**Applying to post_trade_monitor.py:** Use the same loop. If post_trade_monitor.py does not have an `error_count` tracker, omit that line — just log the error and let `market = None` trigger the `continue`. Verify `time` is imported; add `import time` at the top if not present.

### What trading behavior changes

Transient Kalshi API errors will no longer silently skip settlements. Positions that settled will get their records written on the same run. Persistent API failures (all 3 attempts fail) behave the same as before — skip + log.

### What could go wrong

- `time` is confirmed imported in settlement_checker.py (used at the bottom of the loop). Verify import in post_trade_monitor.py before applying.
- Rate limiting: at < 20 open positions, worst case is 20 × 3s = 60s extra per run. Acceptable for both files.
- The retry does NOT apply to the `_append_jsonl` write path — write failures should remain immediate errors. Don't retry writes.
- 429 responses: `except Exception` catches these but the 1s/2s backoff may be too short for a `Retry-After: 60` header. This is a known limitation — acceptable for this sprint scope.

---

## ISSUE-030 — Add pnl field to exit records written by ruppert_cycle.py and post_trade_monitor.py

### Files
- `environments/demo/ruppert_cycle.py` — `run_position_check()` function
- `agents/ruppert/trader/post_trade_monitor.py` — `run_monitor()` function, auto-exit block

### Why this matters (cross-domain note)

`compute_closed_pnl_from_logs()` in `logger.py` is the capital backbone. It sums the `pnl` field from settle and exit records. If exit records are missing `pnl`, those trades contribute $0 to the capital calculation. Weather auto-exits and monitor exits are the two exit paths that write records without a `pnl` field — meaning real closed P&L from those paths is silently zeroed.

### What the code does now

**ruppert_cycle.py — run_position_check() (auto-exit path, ~line 385 and ~line 416):**

The function uses TWO separate loops. `pnl` is computed in the first loop and appended to `actions_taken`. The `opp` dict is built in the second loop (the execution loop) where `pnl` is available as a loop variable from the tuple unpack:

```python
# First loop (~line 385): pnl computed, appended to actions_taken
pnl = round((cur_p - entry_p) * contracts / 100, 2)
...
actions_taken.append(('exit', ticker, side, cur_p, contracts, pnl))

# Second loop (~line 416): iterates actions_taken — pnl IS available here
for action, ticker, side, price, contracts, pnl in actions_taken:
    opp = {'ticker': ticker, 'title': ticker, 'side': side, 'action': 'exit',
           'yes_price': price if side=='yes' else 100-price,
           'market_prob': price/100, 'noaa_prob': None, 'edge': None,
           'size_dollars': round(contracts*price/100, 2), 'contracts': contracts,
           'source': 'weather', 'timestamp': ts(), 'date': str(date.today())}
    # pnl is the 6th tuple element, available as loop var, but NOT added to opp
    if state.dry_run:
        log_trade(opp, ...)
    else:
        result = client.sell_position(...)
        log_trade(opp, ...)
```

**post_trade_monitor.py — run_monitor(), auto-exit block (~line 476–490):**

`exit_opp` dict is built FIRST. Then `exit_pnl` is computed. Then `log_trade()` is called. This ordering is critical:

```python
# exit_opp dict built FIRST (line ~476)
exit_opp = {
    'ticker': ticker,
    ...other fields...
    # pnl NOT here — exit_pnl does not exist yet at this point
}

# exit_pnl computed AFTER dict is built (line ~490)
ep = normalize_entry_price(pos)
exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)

# log_trade called after (line ~492+)
if _dry_run:
    log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, {'dry_run': True})
else:
    ...
    result = client.sell_position(ticker, side, cur_price, pos_contracts)
    log_trade(exit_opp, exit_opp['size_dollars'], pos_contracts, result)
```

### What changes

**ruppert_cycle.py:** Add `'pnl': pnl` to the `opp` dict in the second (execution) loop. `pnl` is already the 6th tuple element unpacked from `actions_taken` — it's available as a local variable. Both dry_run and live branches share the same `opp` dict, so one addition covers both paths:

```python
for action, ticker, side, price, contracts, pnl in actions_taken:
    opp = {
        'ticker': ticker,
        ...existing fields...,
        'pnl': pnl,   # ADD THIS — pnl is the 6th element unpacked from actions_taken tuple
    }
```

**post_trade_monitor.py:** The ordering constraint is strict — `'pnl': exit_pnl` CANNOT be added inside the `exit_opp` dict literal because `exit_pnl` is defined after the dict. Dev must choose one of two correct approaches:

**Option A (preferred): Move exit_pnl computation before the dict**
```python
# Compute exit_pnl FIRST
ep = normalize_entry_price(pos)
exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)

# Then build the dict with pnl included
exit_opp = {
    'ticker': ticker,
    ...other fields...,
    'pnl': exit_pnl,   # safe — exit_pnl already defined above
}

if _dry_run:
    log_trade(exit_opp, ...)
else:
    ...
    log_trade(exit_opp, ...)
```

**Option B: Add pnl as a separate dict update after computation**
```python
# Dict built first (existing order preserved)
exit_opp = {
    'ticker': ticker,
    ...other fields...
    # DO NOT add 'pnl': exit_pnl here — exit_pnl not defined yet
}

# exit_pnl computed (existing)
ep = normalize_entry_price(pos)
exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)

# ADD THIS LINE — update dict after computation, before log_trade calls
exit_opp['pnl'] = exit_pnl

if _dry_run:
    log_trade(exit_opp, ...)
else:
    ...
    log_trade(exit_opp, ...)
```

**⚠️ Do NOT add `'pnl': exit_pnl` inside the original dict literal** — this causes a `NameError` because `exit_pnl` is not defined at the point the dict is constructed.

### Exit paths to verify

Dev should audit every exit write path in both files:

**ruppert_cycle.py:**
- `run_position_check()` auto-exit (second loop over actions_taken): `log_trade(opp, ...)` — add `pnl` to `opp` ✓
- `run_econ_prescan_mode()` does not write exit records — skip
- No other exit writes in this file

**post_trade_monitor.py:**
- `run_monitor()` auto-exit block: `log_trade(exit_opp, ...)` — add `pnl` per Option A or B above ✓
- `check_settlements()` inside post_trade_monitor.py: settle records already include `pnl` in the record dict (`"pnl": round(pnl, 2)`). This path is correct — no change needed.

### What trading behavior changes

After the fix, every exit from these paths will have a `pnl` field. `compute_closed_pnl_from_logs()` will include these exits in the capital calculation instead of treating them as $0. The capital figure will increase by the sum of all previously-dropped exit P&L.

### What could go wrong

- If `normalize_entry_price(pos)` returns a bad value (None, 0), `exit_pnl` could be wrong. Pre-existing risk — the compute was already happening. The fix surfaces it in the P&L record.
- After this fix, DS should run `compute_closed_pnl_from_logs()` and compare the before/after capital figure to quantify how much was silently dropped. This is a verification step, not a code change.
- Historical exit records without `pnl` (prior to this fix) will still contribute $0. Backfill is out of scope for this sprint.
- The `ws_feed.py` exit path is not affected — WS exits already write `pnl` correctly.

### Cross-domain coordination note

After Dev ships and QA passes, DS needs to:
1. Run `compute_closed_pnl_from_logs()` before and after a fresh set of exits to verify the new records are picked up
2. Check that the capital figure makes sense relative to known trade history
3. Document the expected capital delta before deploying to avoid a false alarm from the sudden jump

---

## ISSUE-102 — Add missing D-suffix prefixes to TICKER_MODULE_MAP AND _cap_map in data_agent.py

### File
`agents/ruppert/data_scientist/data_agent.py`
- `TICKER_MODULE_MAP` dict (~line 55–100) — **classification fix**
- `_cap_map` dict (~line 334–336) — **cap enforcement fix** ← NEW, required

**Both maps must be updated. Fixing only TICKER_MODULE_MAP leaves XRP/DOGE threshold daily modules with correct classification but uncapped exposure.**

### What the code does now

**TICKER_MODULE_MAP (~line 76–78):**
```python
# ── Crypto threshold daily (above/below daily) ────────────────────────────
'KXBTCD':    'crypto_threshold_daily_btc',
'KXETHD':    'crypto_threshold_daily_eth',
'KXSOLD':    'crypto_threshold_daily_sol',
# MISSING: KXXRPD and KXDOGED
```

`KXXRPD-...` tickers fall through to `KXXRP` → classified as `crypto_band_daily_xrp` (wrong module).
`KXDOGED-...` tickers fall through to `KXDOGE` → classified as `crypto_band_daily_doge` (wrong module).

**_cap_map (~line 334–336):**
```python
_cap_map = {
    ...
    'crypto_threshold_daily_btc': 'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_eth': 'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_sol': 'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    # MISSING: crypto_threshold_daily_xrp and crypto_threshold_daily_doge
}
```

`_cap_map` is used by `get_daily_cap_utilization()` for daily cap enforcement. Missing entries mean `crypto_threshold_daily_xrp` and `crypto_threshold_daily_doge` modules have no enforced cap — uncapped exposure for those modules even after the TICKER_MODULE_MAP fix correctly classifies them.

### Fix Part 1: TICKER_MODULE_MAP

Add two missing entries to the threshold daily section:

```python
# ── Crypto threshold daily (above/below daily) ────────────────────────────
# Must appear BEFORE base prefixes (KXBTC, KXETH, etc.)
'KXBTCD':    'crypto_threshold_daily_btc',
'KXETHD':    'crypto_threshold_daily_eth',
'KXSOLD':    'crypto_threshold_daily_sol',
'KXXRPD':    'crypto_threshold_daily_xrp',    # ADD
'KXDOGED':   'crypto_threshold_daily_doge',   # ADD
```

No other changes. The longest-prefix-first sort (`sorted(..., key=len, reverse=True)`) handles ordering automatically — `KXXRPD` (6 chars) will match before `KXXRP` (5 chars).

### Fix Part 2: _cap_map

Add the two missing module entries to `_cap_map` alongside the existing crypto threshold daily entries:

```python
_cap_map = {
    ...
    'crypto_threshold_daily_btc':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_eth':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_sol':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_xrp':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',   # ADD
    'crypto_threshold_daily_doge': 'CRYPTO_1H_DIR_DAILY_CAP_PCT',   # ADD
    ...
}
```

Use the same cap config key (`CRYPTO_1H_DIR_DAILY_CAP_PCT`) as the other threshold daily crypto modules. These are the same asset class and should share the same cap parameter.

### What trading behavior changes

- **TICKER_MODULE_MAP fix:** `check_module_mismatch()` stops flagging KXXRPD and KXDOGED trades as "module unknown." Module-level analytics correctly attribute XRP and DOGE threshold daily trades.
- **_cap_map fix:** `get_daily_cap_utilization()` will enforce the daily cap for `crypto_threshold_daily_xrp` and `crypto_threshold_daily_doge`. Previously these modules were effectively uncapped — any exposure in these modules was invisible to the cap enforcement logic.

Note: Live trade classification uses `classify_module()` in `logger.py` (already correct for these prefixes). Neither fix changes runtime trade execution, only audit accuracy and cap enforcement.

### What could go wrong

- Typo risk in prefix strings: confirm `KXXRPD` and `KXDOGED` match the prefix used in `logger.py`'s `classify_module()` (confirmed at logger.py line 623: `t.startswith('KXXRPD')` and `t.startswith('KXDOGED')`).
- After the `_cap_map` fix, if XRP/DOGE threshold daily modules have accumulated exposure above the cap, the first cap check after deploy will flag a breach. DS should check current exposure in those modules before deploy and document expected state.

---

## Implementation Order

1. **ISSUE-026 + ISSUE-027** first — settlement_checker.py compute_pnl() win branch (exit_price + formula) and loss branch (formula). Then post_trade_monitor.py check_settlements() win branches (exit_price + formula only — loss already correct). Fix in one pass per file.
2. **ISSUE-110** next — retry pattern in settlement_checker.py check_settlements() and post_trade_monitor.py check_settlements(). Can be same PR or sequential.
3. **ISSUE-030** — ruppert_cycle.py and post_trade_monitor.py auto-exit blocks. Keep in same PR. After merge, DS verifies capital figure delta.
4. **ISSUE-102** — TICKER_MODULE_MAP and _cap_map additions together in one pass. Verify _cap_map key name matches the module string added to TICKER_MODULE_MAP exactly.

---

## QA Checklist

**ISSUE-026 + ISSUE-027:**
- [ ] Run settlement_checker.py in dry-run against a resolved market. Confirm win settle record shows `exit_price = 100`, `pnl = (100 - entry_price) * contracts / 100`
- [ ] Confirm loss settle record shows `pnl = -(entry_price * contracts / 100)`, not `-size_dollars`
- [ ] Confirm pnl values are symmetric: same position, opposite result should give approximately equal and opposite P&L when entry ≈ 50¢
- [ ] Run post_trade_monitor.py check_settlements() against a resolved market. Confirm win branches use `exit_price = 100` and `pnl = (100 - entry_price) * contracts / 100`
- [ ] Confirm post_trade_monitor.py loss branches are unchanged: still use `-(entry_price * contracts / 100)`
- [ ] Confirm both files now produce identical pnl for the same win scenario (no more divergence between settlement paths)

**ISSUE-110:**
- [ ] Mock API failure in settlement_checker.py (raise Exception on first call). Confirm retry fires, 1s delay observed, second call succeeds
- [ ] Mock 3 consecutive failures in settlement_checker.py. Confirm error_count incremented, position skipped, no crash
- [ ] Same mock tests in post_trade_monitor.py: retry fires, delays 1s then 2s (no 4s sleep), position skipped after 3 failures
- [ ] Confirm delay sequence is 1s, 2s only (not 1s, 2s, 4s — the last attempt does not sleep)
- [ ] Confirm `time` import is not duplicated in either file

**ISSUE-030:**
- [ ] Trigger an auto-exit in dry-run via ruppert_cycle.py. Read the logged record. Confirm `pnl` field is present and non-zero
- [ ] Trigger an auto-exit in dry-run via post_trade_monitor.py. Read the logged record. Confirm `pnl` field is present
- [ ] Verify no NameError — confirm `exit_pnl` is defined before it is referenced in post_trade_monitor.py (either Option A ordering or Option B dict update)
- [ ] Call `compute_closed_pnl_from_logs()` after the test exits. Confirm the P&L figure includes the new exits (not $0)
- [ ] Confirm ws_feed.py exit records are unaffected (still write pnl correctly)

**ISSUE-102:**
- [ ] Run `check_module_mismatch()` with a KXXRPD ticker. Confirm it classifies to `crypto_threshold_daily_xrp`, no mismatch warning
- [ ] Same for KXDOGED → `crypto_threshold_daily_doge`
- [ ] Confirm KXBTCD, KXETHD, KXSOLD still classify correctly (regression check)
- [ ] Confirm KXXRP (without D) still classifies to `crypto_band_daily_xrp` (base prefix still works)
- [ ] Run `get_daily_cap_utilization()` with a `crypto_threshold_daily_xrp` module. Confirm it returns a cap value (not None/missing) after _cap_map fix
- [ ] Same for `crypto_threshold_daily_doge`
- [ ] Check current XRP/DOGE threshold daily exposure before deploy — document expected state so a cap breach on first run isn't treated as a false alarm

---

_Spec revised. Data Scientist. 2026-04-03._
