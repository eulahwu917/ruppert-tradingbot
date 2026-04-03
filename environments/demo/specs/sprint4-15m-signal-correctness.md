# Sprint 4 Spec — 15m Signal Correctness
_CEO authored. Strategist reviews ISSUE-087. Trader reviews ISSUE-001, 035, 073._
_Date: 2026-04-03_

---

## Overview

4 issues in 2 files. Corrects anti-causal OBI signal, adds KXSOL15M to the feed, hardens Coinbase fail-open, and surfaces silent exceptions.

**Domain assignments:**
- **Strategist reviews:** ISSUE-087 (OBI EWM direction — algorithm correctness)
- **Trader reviews:** ISSUE-001, ISSUE-035, ISSUE-073

**Pipeline:** Strategist + Trader review spec → David approves → Dev implements → QA → CEO approves → commit.

---

## Fix 1 — ISSUE-001: KXSOL15M missing from `CRYPTO_15M_SERIES` in `ws_feed.py`

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**The problem:** `CRYPTO_15M_SERIES` in `ws_feed.py` is:
```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']
```
SOL 15m tickers (`KXSOL15M-*`) are not in this list. WS price ticks for SOL 15m markets match `CRYPTO_HOURLY_PREFIXES` (`KXSOL`) and get routed to `_safe_eval_hourly()` — the hourly band evaluator — instead of `_safe_eval_15m()`. SOL never trades on the 15m directional model.

**Note:** `crypto_15m.py` already has `KXSOL15M` in its own `CRYPTO_15M_SERIES` constant (line 56). The gap is specifically in `ws_feed.py`.

**The fix:** Add `'KXSOL15M'` to `CRYPTO_15M_SERIES` in `ws_feed.py`:
```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']
```

**IMPORTANT — must happen before or simultaneously with Sprint 5 (ISSUE-047):** ISSUE-047 adds CB coverage for SOL, XRP, DOGE. Sprint 5 must be completed before trading is re-enabled, so SOL 15m markets are protected by the circuit breaker when the feed goes live. This fix alone is safe to commit — SOL won't trade until WS feed is restarted, which is gated on David's go-ahead.

**Behavior change:** SOL 15m tickers route to `_safe_eval_15m()`. SOL will be evaluated by the 15m directional model when trading resumes.

---

## Fix 2 — ISSUE-087: OBI EWM is backwards — overweights old data

**File:** `agents/ruppert/trader/crypto_15m.py`
**Function:** `fetch_orderbook_imbalance()`

**The problem:** The EWM loop iterates in the wrong direction:
```python
alpha = 2.0 / 61.0
ewm = obi_instant          # start with the LATEST snapshot
for val in reversed(list(_obi_snapshots[symbol])[:-1]):  # iterate OLDEST → NEWEST
    ewm = alpha * val + (1 - alpha) * ewm
```

The standard EWM formula applies higher weight to RECENT data. The correct iteration is:
- Start with the OLDEST value as the seed
- Apply `ewm = alpha * current + (1 - alpha) * ewm` moving from old → new

The current code seeds with the latest snapshot and applies old values as the "current" value — giving historical data MORE weight than recent data. The OBI signal is directionally correct (it captures bid/ask imbalance) but its EWM smoothing is anti-causal: it gives the most weight to snapshots from ~2 minutes ago, not the most recent ones.

**The fix:** Correct the iteration order and seeding:
```python
alpha = 2.0 / 61.0
snapshots = list(_obi_snapshots[symbol])  # chronological: oldest first
if not snapshots:
    ewm = 0.0
else:
    ewm = snapshots[0]  # seed with OLDEST value
    for val in snapshots[1:]:  # iterate OLDEST → NEWEST (forward)
        ewm = alpha * val + (1 - alpha) * ewm
# ewm now reflects the most recent snapshot with highest weight
```

**Strategist note:** Historical win rates should be revalidated after this fix since signal direction was effectively wrong. After deploying, monitor for 24h comparing YES vs NO win rates.

**Transition warning:** `_rolling_obi` has been accumulating inverted EWM values. After the fix, corrected EWM output will shift but the z-score window still contains ~4h of pre-fix values. The first ~4h of `obi_z` post-deploy are transitional/noisy — expected, not a bug. Dev should add a one-time startup log noting the correction so the transition is visible in logs.

**Behavior change:** OBI signal correctly weights recent orderbook state most heavily. The 25% OBI component of the composite signal now behaves as designed. Expect some change in entry direction decisions.

---

## Fix 3 — ISSUE-035: Coinbase fail-open — basis filter skipped when Coinbase is unavailable

**File:** `agents/ruppert/trader/crypto_15m.py`
**Function:** `_check_strategy_gates()` (around line 735)

**The problem:** The Coinbase-OKX basis filter (R10):
```python
coinbase_price = fetch_coinbase_price(asset)
okx_price = fetch_okx_price(symbol)
if coinbase_price and okx_price and okx_price > 0:
    basis = abs(coinbase_price - okx_price) / okx_price
    _max_basis = getattr(config, 'CRYPTO_15M_MAX_BASIS_PCT', 0.0015)
    if basis > _max_basis:
        return {'block': 'BASIS_RISK', 'okx_volume_pct': okx_volume_pct}
```

When `coinbase_price` is `None` (API unavailable), the `if coinbase_price and okx_price` condition is False and the filter is silently skipped. The trade proceeds without basis validation. This matters because Kalshi settles on Coinbase price — the basis filter is most critical exactly when Coinbase is down.

**The fix:** Return a `COINBASE_UNAVAILABLE` block when the Coinbase price cannot be fetched:

```python
coinbase_price = fetch_coinbase_price(asset)
okx_price = fetch_okx_price(symbol)

if coinbase_price is None:
    # Kalshi settles on Coinbase price — can't validate basis without it.
    # Block entry rather than proceed blind.
    logger.warning('[crypto_15m] Coinbase price unavailable for %s — blocking entry (COINBASE_UNAVAILABLE)', asset)
    return {'block': 'COINBASE_UNAVAILABLE', 'okx_volume_pct': okx_volume_pct}

if okx_price and okx_price > 0:
    basis = abs(coinbase_price - okx_price) / okx_price
    _max_basis = getattr(config, 'CRYPTO_15M_MAX_BASIS_PCT', 0.0015)
    if basis > _max_basis:
        return {'block': 'BASIS_RISK', 'okx_volume_pct': okx_volume_pct}
```

**Behavior change:** When Coinbase API is unavailable, entries are blocked with `COINBASE_UNAVAILABLE` reason logged. No trades fire blind. The decision log will show `COINBASE_UNAVAILABLE` skip reasons for post-hoc analysis.

---

## Fix 4 — ISSUE-073: Exception swallows in scan loops — silent failures

**File:** `agents/ruppert/trader/crypto_15m.py`
**Function:** `evaluate_crypto_15m_entry()`

**The problem:** `evaluate_crypto_15m_entry()` has no top-level try/except internally. The outer catch that wraps it is in `ws_feed.py:_safe_eval_15m()` (around line 678):
```python
except Exception as e:
    logger.warning('[WS Feed] 15m eval error: %s', e)
```
This logs at WARNING with no traceback and no Telegram alert. When a crash occurs (OKX API timeout, import error, unexpected data), it looks like a normal low-priority warning and David has no idea the 15m evaluator is broken.

**The fix is in `ws_feed.py:_safe_eval_15m()`**, not in `crypto_15m.py`. Update the exception handler:

```python
# BEFORE (in _safe_eval_15m() in ws_feed.py):
except Exception as e:
    logger.warning('[WS Feed] 15m eval error: %s', e)

# AFTER:
except Exception as _eval_err:
    logger.error('[WS Feed] 15m eval CRASHED for %s: %s', ticker, _eval_err, exc_info=True)
    try:
        from agents.ruppert.trader.utils import push_alert
        push_alert('error', f'15m eval crashed for {ticker}: {_eval_err}', ticker=ticker)
    except Exception:
        pass  # alert failure must not prevent cleanup
```

**File to edit: `agents/ruppert/data_analyst/ws_feed.py`** (not crypto_15m.py).

**Also in `crypto_15m.py`:** `fetch_price_delta()` and `fetch_okx_price()` have silent `except Exception: pass` swallows — add `logger.warning()` to each so stale signals are visible in logs.

**Behavior change:** Any crash in 15m evaluation fires a Telegram alert and logs at ERROR level. Stale signals log at WARNING. Silent failures are eliminated.

---

## Batch split

All 4 fixes touch 2 files: `ws_feed.py` (Fixes 1 + 4) and `crypto_15m.py` (Fixes 2 + 3 + silent swallow cleanup). Single batch — Dev implements all 4 together.

---

## QA Checklist

**Trader verifies:**
1. ISSUE-001: `CRYPTO_15M_SERIES` in `ws_feed.py` includes `'KXSOL15M'` (5 entries total).
2. ISSUE-087: OBI EWM loop seeds with `snapshots[0]` (oldest) and iterates `snapshots[1:]` forward. `reversed()` is gone.
3. ISSUE-035: When `coinbase_price is None`, function returns `{'block': 'COINBASE_UNAVAILABLE', ...}`. The `if coinbase_price and okx_price` pattern is gone.
4. ISSUE-073: In `ws_feed.py:_safe_eval_15m()`, the exception handler logs at ERROR (not WARNING) with `exc_info=True` and calls `push_alert()`. In `crypto_15m.py`, `fetch_price_delta()` and `fetch_okx_price()` no longer have silent bare `pass` swallows — they log at WARNING.

**Strategist verifies:**
5. ISSUE-087: The corrected EWM is mathematically sound. The seed value and iteration direction match the standard EWM formula (most recent snapshot has highest weight).

**After all QA passes:** Monitor 15m signal quality for 24h after trading resumes. Strategist reviews YES vs NO win rates to confirm OBI fix direction.

---

## Change Log Entry (after commit)

Add to `memory/agents/fix-changelog.md`:

```
## Sprint 4 — 2026-04-03

| Issue ID | Title | Fix Summary | Commit |
|----------|-------|-------------|--------|
| ISSUE-001 | KXSOL15M added to WS series | ws_feed.py: 'KXSOL15M' added to CRYPTO_15M_SERIES | TBD |
| ISSUE-087 | OBI EWM direction corrected | crypto_15m.py: EWM seeds oldest, iterates forward; reversed() removed | TBD |
| ISSUE-035 | Coinbase fail-open blocked | crypto_15m.py: None coinbase_price → COINBASE_UNAVAILABLE block | TBD |
| ISSUE-073 | Exception swallows fixed | crypto_15m.py: outermost handler logs ERROR + push_alert; no bare pass | TBD |
```
