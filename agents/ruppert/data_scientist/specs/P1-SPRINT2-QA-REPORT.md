# P1 Sprint 2 — QA Report: Settlement + Capital Accuracy
_QA Agent | 2026-04-03_
_Sprint: P1-2 | Reviewing: 3 batches, 4 issues, 5 files_

---

## Verdict: ✅ APPROVED — All 3 batches pass

All changes verified against spec. No defects found. Commit messages at bottom.

---

## Files Verified

| File | Issues Covered | Status |
|------|---------------|--------|
| `environments/demo/settlement_checker.py` | ISSUE-026, ISSUE-027, ISSUE-110 | ✅ PASS |
| `agents/ruppert/trader/post_trade_monitor.py` | ISSUE-026, ISSUE-110, ISSUE-030 | ✅ PASS |
| `environments/demo/ruppert_cycle.py` | ISSUE-030 | ✅ PASS |
| `agents/ruppert/data_scientist/data_agent.py` | ISSUE-102 | ✅ PASS |

---

## Batch 1 — ISSUE-026 + ISSUE-027: Win/Loss Formula Fix

### settlement_checker.py — `compute_pnl()`

**Win branch:**
```python
exit_price = 100                              # ✅ Was 99 (ISSUE-026 fixed)
pnl = (100 - entry_price) * contracts / 100  # ✅ Formula updated to match
```

**Loss branch:**
```python
exit_price = 1
pnl = -(entry_price * contracts / 100)       # ✅ Was -size_dollars (ISSUE-027 fixed)
```

Both formulas now use contract-based math on the same basis. Win and loss are symmetric.

### post_trade_monitor.py — `check_settlements()`

**side=='yes' win branch:**
```python
exit_price = 100                              # ✅ Was 99 (ISSUE-026 fixed)
pnl = (100 - entry_price) * contracts / 100  # ✅ Updated
```

**side=='no' win branch:**
```python
exit_price = 100                              # ✅ Was 99 (ISSUE-026 fixed)
pnl = (100 - entry_price) * contracts / 100  # ✅ Updated
```

**Loss branches (both sides):**
```python
exit_price = 1
pnl = -(entry_price * contracts / 100)       # ✅ UNCHANGED — already correct per spec
```

### Cross-file pnl consistency check

Both files now compute win P&L identically:
- `settlement_checker.py`: `(100 - entry_price) * contracts / 100`
- `post_trade_monitor.py`: `(100 - entry_price) * contracts / 100`

✅ Identical formulas — no more divergence between the two settlement paths.

---

## Batch 2 — ISSUE-110: Retry Loop on API Errors

### settlement_checker.py — `check_settlements()`

```python
MAX_RETRIES = 3
market = None
for attempt in range(MAX_RETRIES):
    try:
        market = client.get_market(ticker)
        break
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt  # attempt=0 → 1s, attempt=1 → 2s
            print(f"  [WARN] API error for {ticker} (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
            time.sleep(wait)
        else:
            print(f"  [ERROR] API error for {ticker} after {MAX_RETRIES} attempts: {e} — skipping")
            error_count += 1
if market is None:
    continue
```

✅ 3-attempt loop present  
✅ Delay sequence: attempt=0 → 1s, attempt=1 → 2s, attempt=2 → no sleep (condition `attempt < MAX_RETRIES - 1` is False)  
✅ `error_count` incremented only on final failure  
✅ `if market is None: continue` guard present  
✅ `import time` confirmed at top of file (line in imports block)

### post_trade_monitor.py — `check_settlements()`

```python
MAX_RETRIES = 3
market = None
for attempt in range(MAX_RETRIES):
    try:
        market = client.get_market(ticker)
        break
    except Exception as e:
        if attempt < MAX_RETRIES - 1:
            wait = 2 ** attempt  # attempt=0 → 1s, attempt=1 → 2s
            print(f"  [Settlement Checker] API error for {ticker} (attempt {attempt+1}/{MAX_RETRIES}): {e} — retrying in {wait}s")
            time.sleep(wait)
        else:
            print(f"  [Settlement Checker] API error for {ticker} after {MAX_RETRIES} attempts: {e} — skipping")
if market is None:
    continue
```

✅ Same 3-attempt loop with identical delay logic  
✅ No `error_count` (correct — post_trade_monitor.py does not track errors per spec)  
✅ `if market is None: continue` guard present  
✅ `import time` confirmed present (line 9 of file: `import time`)  
✅ No sleep after final attempt — delay sequence is 1s, 2s only (not 1s, 2s, 4s)

---

## Batch 3 — ISSUE-030: pnl Field in Exit Records

### ruppert_cycle.py — `run_position_check()` execution loop

```python
for action, ticker, side, price, contracts, pnl in actions_taken:
    ...
    opp = {'ticker': ticker, 'title': ticker, 'side': side, 'action': 'exit',
           'yes_price': price if side=='yes' else 100-price,
           'market_prob': price/100, 'noaa_prob': None, 'edge': None,
           'size_dollars': round(contracts*price/100, 2), 'contracts': contracts,
           'source': 'weather', 'timestamp': ts(), 'date': str(date.today()),
           'pnl': pnl}                                        # ✅ Added (line 434)
```

✅ `'pnl': pnl` present in the dict literal  
✅ `pnl` is the 6th element unpacked from the tuple — defined before the dict is built (no NameError risk)  
✅ Shared by both dry_run and live branches (same `opp` dict used in both paths)

### post_trade_monitor.py — `run_monitor()` auto-exit block

```python
exit_opp = {
    'ticker': ticker, 'title': pos.get('title', ticker),
    'side': side, 'action': 'exit',
    ...
    # pnl NOT in dict literal (correct — exit_pnl not defined yet)
}

# exit_pnl computed AFTER dict is built
ep = normalize_entry_price(pos)
exit_pnl = round((cur_price - ep) * pos_contracts / 100, 2)
exit_opp['pnl'] = exit_pnl  # ✅ Option B: separate line after computation (NameError-safe)
```

✅ `exit_opp['pnl'] = exit_pnl` as a **separate line**, after `exit_pnl` is computed  
✅ Not inside the dict literal — no NameError possible  
✅ Applied before both `log_trade()` calls (dry_run and live branches)  
✅ Comment in code confirms intent: `# ISSUE-030: add pnl field after computation (NameError-safe)`

---

## Batch 3 — ISSUE-102: data_agent.py TICKER_MODULE_MAP + _cap_map

### TICKER_MODULE_MAP additions (lines 79–80)

```python
# ── Crypto threshold daily (above/below daily) ────────────────────────────
# Must appear BEFORE base prefixes (KXBTC, KXETH, etc.)
'KXBTCD':    'crypto_threshold_daily_btc',
'KXETHD':    'crypto_threshold_daily_eth',
'KXSOLD':    'crypto_threshold_daily_sol',
'KXXRPD':    'crypto_threshold_daily_xrp',    # ✅ Added (line 79)
'KXDOGED':   'crypto_threshold_daily_doge',   # ✅ Added (line 80)

# ── Crypto band daily (range prediction) ─────────────────────────────────
'KXBTC':     'crypto_band_daily_btc',
'KXXRP':     'crypto_band_daily_xrp',         # ✅ Base prefix still intact
'KXDOGE':    'crypto_band_daily_doge',         # ✅ Base prefix still intact
```

✅ `KXXRPD` → `crypto_threshold_daily_xrp` present  
✅ `KXDOGED` → `crypto_threshold_daily_doge` present  
✅ Positioned in threshold daily section, BEFORE base prefixes (`KXXRP`, `KXDOGE`)  
✅ `KXXRP` (no D) still maps to `crypto_band_daily_xrp` — no regression  
✅ `KXDOGE` (no D) still maps to `crypto_band_daily_doge` — no regression  
✅ Longest-prefix sort will match `KXXRPD` (6 chars) before `KXXRP` (5 chars) — ordering correct

### _cap_map additions (lines 339–340)

```python
_cap_map = {
    ...
    'crypto_threshold_daily_btc':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_eth':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_sol':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',
    'crypto_threshold_daily_xrp':  'CRYPTO_1H_DIR_DAILY_CAP_PCT',   # ✅ Added (line 339)
    'crypto_threshold_daily_doge': 'CRYPTO_1H_DIR_DAILY_CAP_PCT',   # ✅ Added (line 340)
    ...
}
```

✅ `crypto_threshold_daily_xrp` present with `CRYPTO_1H_DIR_DAILY_CAP_PCT` key  
✅ `crypto_threshold_daily_doge` present with `CRYPTO_1H_DIR_DAILY_CAP_PCT` key  
✅ Same cap config key as btc/eth/sol entries — consistent with same asset class  
✅ Module string exactly matches what was added to TICKER_MODULE_MAP (no typos)

---

## Spec Compliance Summary

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| settlement_checker.py win exit_price | 100 | 100 | ✅ |
| settlement_checker.py win formula | `(100-ep)*c/100` | `(100 - entry_price) * contracts / 100` | ✅ |
| settlement_checker.py loss formula | `-(ep*c/100)` | `-(entry_price * contracts / 100)` | ✅ |
| post_trade_monitor.py win exit_price (yes win) | 100 | 100 | ✅ |
| post_trade_monitor.py win exit_price (no win) | 100 | 100 | ✅ |
| post_trade_monitor.py win formula (both sides) | `(100-ep)*c/100` | `(100 - entry_price) * contracts / 100` | ✅ |
| post_trade_monitor.py loss branches | UNCHANGED | Not touched | ✅ |
| Both files pnl identical for same win | Yes | Same formula | ✅ |
| settlement_checker.py retry attempts | 3 | 3 | ✅ |
| Delay after attempt 0 | 1s | `2**0 = 1s` | ✅ |
| Delay after attempt 1 | 2s | `2**1 = 2s` | ✅ |
| Sleep after final attempt | None | No sleep (condition False) | ✅ |
| post_trade_monitor.py retry attempts | 3 | 3 | ✅ |
| post_trade_monitor.py delays | 1s, 2s | `2**0=1s`, `2**1=2s` | ✅ |
| post_trade_monitor.py no sleep after final | Yes | Confirmed | ✅ |
| post_trade_monitor.py `import time` | Present | Line 9 | ✅ |
| post_trade_monitor.py no error_count | Correct | Omitted | ✅ |
| ruppert_cycle.py `pnl` in opp dict | Yes | Line 434 | ✅ |
| post_trade_monitor.py `exit_opp['pnl']` separate line | Yes (Option B) | After exit_pnl computed | ✅ |
| post_trade_monitor.py no NameError risk | Confirmed | exit_pnl defined before assignment | ✅ |
| data_agent.py KXXRPD added | Yes | Line 79 | ✅ |
| data_agent.py KXDOGED added | Yes | Line 80 | ✅ |
| data_agent.py _cap_map xrp added | Yes | Line 339 | ✅ |
| data_agent.py _cap_map doge added | Yes | Line 340 | ✅ |
| _cap_map key matches TICKER_MODULE_MAP string | Must match | Exact match | ✅ |

---

## Post-Deploy Actions (DS, not blocking commit)

1. **ISSUE-030:** After deploy, run `compute_closed_pnl_from_logs()` before and after a fresh set of exits. Document the capital delta — the increase is real (previously dropped exit P&L now counted).
2. **ISSUE-102:** Check current XRP/DOGE threshold daily exposure before deploy. The `_cap_map` fix activates cap enforcement for those modules — a first-run breach flag is possible if exposure is already above cap.

---

## Commit Messages

### Batch 1
```
fix: correct win/loss settlement P&L formulas (ISSUE-026, ISSUE-027)

settlement_checker.py: win exit_price 99→100, win formula (100-ep)*c/100,
loss formula -size_dollars→-(ep*c/100). post_trade_monitor.py: win exit_price
99→100 in both yes/no win branches, win formula updated. Loss branches
unchanged (already correct). Both settlement paths now produce identical P&L
for the same win scenario.
```

### Batch 2
```
fix: add 3-attempt retry with 1s/2s backoff on API errors (ISSUE-110)

settlement_checker.py + post_trade_monitor.py: replace bare continue on
client.get_market() exceptions with retry loop (MAX_RETRIES=3). Delays:
1s after attempt 0, 2s after attempt 1, no sleep after final attempt.
Adds import time to post_trade_monitor.py. Prevents transient API errors
from silently skipping settlement for 24h/30min respectively.
```

### Batch 3
```
fix: add pnl to exit records; add KXXRPD/KXDOGED to classification maps (ISSUE-030, ISSUE-102)

ruppert_cycle.py: add pnl field to exit opp dict in execution loop — pnl
unpacked from actions_taken tuple. post_trade_monitor.py: add exit_opp['pnl']
= exit_pnl as separate line after exit_pnl is computed (NameError-safe, Option B).
data_agent.py: add KXXRPD→crypto_threshold_daily_xrp and KXDOGED→
crypto_threshold_daily_doge to TICKER_MODULE_MAP and _cap_map
(CRYPTO_1H_DIR_DAILY_CAP_PCT). Fixes silent $0 P&L from auto-exits and
uncapped XRP/DOGE threshold daily exposure.
```

---

_QA complete. No defects. All 3 batches approved for commit._
