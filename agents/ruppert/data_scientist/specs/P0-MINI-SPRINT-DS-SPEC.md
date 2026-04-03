# P0 Mini-Sprint — Data Scientist Fixes
**Date:** 2026-04-03  
**Authored by:** DS (Data Scientist sub-agent)  
**Revised:** 2026-04-03 (post adversarial review — see revision summary below)  
**Issues:** ISSUE-007, ISSUE-006, ISSUE-040  
**Reviewer:** David (please review before Dev starts)

---

## Revision Summary (v2)

Changes made after adversarial review (`memory/agents/p0-mini-sprint-adversarial-review.md`):

**ISSUE-007:**
- Added explicit enumeration of all callers of `compute_closed_pnl_from_logs()` and `get_capital()` with precise failure mode for each
- Identified that `capital.py::get_capital()` and `capital.py::get_pnl()` BOTH silently swallow RuntimeError — the logger.py fix alone does nothing unless both are also patched; added concrete fix specs for each
- Updated Option A code sample to include `_pnl_mtime_cache` invalidation on exception (was mentioned in prose only, absent from code)

**ISSUE-006:**
- Removed contradictory "analysis" walk-through that concluded "that's actually fine" mid-spec — replaced with a direct, consistent explanation
- Clarified precisely which fix is for win-rate correctness (outcome flip) vs. Brier semantic correctness (prob flip), and why both are needed
- Added explicit handling for `predicted_prob = None` on NO-side trades
- Added explicit note that `edge` field is NOT flipped (intentional — edge is signed correctly for NO-side already)

**ISSUE-040:**
- Added concrete `DOMAIN_THRESHOLD` recommendation (10) with rationale based on estimated current per-domain trade counts
- Specified that `enrich_trades()` must also be updated to use `classify_module()` instead of `detect_module()` so `analyze_win_rate_by_module()` uses fine-grained names
- Made ISSUE-006 an explicit hard prerequisite with language: "ISSUE-006 must be deployed and `scored_predictions.jsonl` deleted before ISSUE-040 takes effect"

---

## Overview

3 P0 issues that must be fixed before any P1 work begins. All three affect data integrity in the optimizer and scorer pipeline — bad inputs produce bad outputs silently.

- `agents/ruppert/data_scientist/logger.py` — ISSUE-007 (`compute_closed_pnl_from_logs()` silent $0 return)
- `environments/demo/prediction_scorer.py` — ISSUE-006 (NO-side Brier scores and win rate inverted)
- `environments/demo/prediction_scorer.py` + `agents/ruppert/strategist/optimizer.py` — ISSUE-040 (domain name mismatch kills optimizer)

---

## ISSUE-007 — `compute_closed_pnl_from_logs()` Silent $0 Return

**Files:** `agents/ruppert/data_scientist/logger.py`, `agents/ruppert/data_scientist/capital.py`

### What currently happens

`compute_closed_pnl_from_logs()` in `logger.py` is wrapped in a single top-level `try/except Exception`:

```python
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f'[Logger] compute_closed_pnl_from_logs() failed: {e}')
    return 0.0
```

If ANY exception is raised — including `KeyError` on `_get_paths()`, `PermissionError` reading a log file, or a malformed mtime check — the function silently returns `0.0`. All downstream consumers see $0 closed P&L and compute capital as if no trades have ever closed.

The mtime cache makes this worse: on failure, `_pnl_mtime_cache['mtime']` is NOT invalidated. The next call sees the old mtime in cache and may short-circuit, returning whatever stale/zero value is cached instead of retrying the computation.

### Caller Audit — CRITICAL READ

The fix to `logger.py` alone does NOTHING if callers swallow the raised exception. They must be fixed too.

#### Callers of `compute_closed_pnl_from_logs()`

**1. `capital.py::get_capital()`** (primary caller — highest blast radius)

Current behavior: wraps the ENTIRE function body in a broad `try/except Exception`. When `compute_closed_pnl_from_logs()` raises RuntimeError, `get_capital()` catches it, sends a Telegram alert (rate-limited to 1 per 4h), and returns `_DEFAULT_CAPITAL` ($10,000). **This completely negates the fix.** Every downstream consumer still gets a plausible-looking capital number and continues operating.

**Fix required:** Isolate the `compute_closed_pnl_from_logs()` call and re-raise RuntimeError explicitly, so the outer except does NOT swallow it:

```python
# DEMO mode path — inside the existing try/except structure
from agents.ruppert.data_scientist.logger import compute_closed_pnl_from_logs
try:
    closed_pnl = compute_closed_pnl_from_logs()
except RuntimeError:
    raise  # do NOT swallow — capital is unknown; let callers handle it
return round(total + closed_pnl, 2)
```

The outer `except Exception` in `get_capital()` should still exist to catch failures in deposits-file reading, Kalshi API calls, and config loading — but it must NOT catch RuntimeError from the P&L compute path. The cleanest fix is to call `compute_closed_pnl_from_logs()` inside its own try/except that re-raises RuntimeError and lets other exceptions fall through to the outer handler.

**2. `capital.py::get_pnl()`** (secondary caller)

Current behavior: wraps the call in `try/except Exception`, logs a warning, and returns `{'closed': 0.0, 'open': 0.0, 'total': 0.0}`. Silent swallow. Any caller of `get_pnl()` (e.g. dashboard API, audit scripts) silently gets $0 closed P&L on failure.

**Fix required:** Propagate RuntimeError:

```python
def get_pnl() -> dict:
    result = {'closed': 0.0, 'open': 0.0, 'total': 0.0}
    from agents.ruppert.data_scientist.logger import compute_closed_pnl_from_logs
    try:
        result['closed'] = compute_closed_pnl_from_logs()
        result['total'] = result['closed'] + result['open']
    except RuntimeError:
        logger.error('[Capital] get_pnl() — P&L compute failed, propagating')
        raise  # caller must handle — do not return zeroed dict silently
    return result
```

#### Callers of `get_capital()`

After the fix to `get_capital()`, it will raise RuntimeError when P&L is unknown. Dev must audit all callers:

**1. `capital.py::get_buying_power()`** — calls `get_capital()` with no try/except. After the fix, RuntimeError propagates to all callers of `get_buying_power()`. This is CORRECT behavior — do not add a try/except here. Callers of `get_buying_power()` (trader.py, ws_feed.py, etc.) must handle the error explicitly.

**2. `optimizer.py` (module load)** — calls `_get_capital()` at the top level as a module-level statement. If `get_capital()` raises, the entire optimizer module fails to import. This is acceptable — if capital is unknown, the optimizer should not run.

**3. All other callers (ws_feed.py, trader.py, heartbeat code, dashboard/api.py, etc.):** Dev must `grep -r "get_capital\|get_buying_power" --include="*.py"` across the workspace and audit every caller. The required contract for each caller: catch RuntimeError → log + send Telegram → skip the current cycle. Do NOT silently return a fallback value and continue operating.

### The Fix — logger.py

**Option A (preferred) — raise with mtime cache invalidation:**

```python
except Exception as e:
    # Invalidate mtime cache so the next call retries from scratch instead of
    # short-circuiting on the stale (possibly None or wrong) cached mtime.
    _pnl_mtime_cache['mtime'] = None
    _pnl_mtime_cache['value'] = None
    raise RuntimeError(
        f'[Logger] compute_closed_pnl_from_logs() failed — cannot compute capital: {e}'
    ) from e
```

**Option B (supplement only — for callers in tight loops that must not crash):** If a caller genuinely cannot propagate the exception (e.g. a dashboard refresh that must stay alive), it should cache the last known good value and use that, while alerting David:

```python
try:
    capital = get_capital()
    _last_known_capital = capital  # update cache on success
except RuntimeError as e:
    logger.error('[Caller] Capital compute failed: %s — using last known value', e)
    send_telegram(f'🚨 Capital compute failed — using stale ${_last_known_capital:.0f}')
    capital = _last_known_capital  # use last known, do NOT use DEFAULT_CAPITAL
```

**Recommended:** Option A (raise + cache invalidation) in `logger.py`. Fix `get_capital()` and `get_pnl()` in `capital.py` to re-raise. Any caller that must stay alive should implement Option B with an explicit last-known-good cache — not a hardcoded fallback.

### What Could Go Wrong

- **ws_feed.py and trader.py** must handle RuntimeError from `get_buying_power()`. If they don't catch it, the process crashes. This is CORRECT behavior — we don't want to keep trading with unknown capital. Dev must verify these callers gracefully log + skip the cycle rather than crashing the entire process.
- **mtime race condition (pre-existing, not worsened by fix):** If a log file is being written while `compute_closed_pnl_from_logs()` is reading it, `p.read_text()` may return a partial last line. The inner `except Exception: pass` silently skips it. The fix does not make this worse — it's noted here for awareness.

**Scope:** `logger.py` (the function), `capital.py` (`get_capital()` and `get_pnl()`)  
**Risk:** Low-medium. The silent failure is the current risk. A loud failure is safer.

---

## ISSUE-006 — NO-Side Brier Scores and Win Rate Inverted

**File:** `environments/demo/prediction_scorer.py`

### What currently happens

In `score_new_settlements()`, `_outcome` is derived from `settlement_result`:

```python
if _sr_str in ('yes', '1', 'true'):
    _outcome = 1
elif _sr_str in ('no', '0', 'false'):
    _outcome = 0
```

This sets `_outcome = 1` when the market settles YES, regardless of which side the bot bought. For YES-side trades this is correct (YES settlement = win). For NO-side trades this is wrong: a YES settlement means the NO buyer LOST, so `_outcome` should be 0, not 1.

### The Bug — Precise Statement

The `outcome` field in `scored_predictions.jsonl` must represent whether the BETTOR WON (1 = win, 0 = loss). Currently it represents whether the market settled YES. These are equivalent for YES-side trades and inverted for NO-side trades.

**Effect 1 — Win-rate is wrong for NO-side trades (primary bug):**  
`analyze_win_rate_by_module()` in optimizer.py counts `outcome == 1` as a win. Currently, NO-side wins (settled NO) are counted as `outcome=0` (loss) and NO-side losses (settled YES) are counted as `outcome=1` (win). The win rate for every module with NO-side trades is inverted.

**Effect 2 — Brier score is semantically wrong for NO-side trades (secondary bug):**  
`predicted_prob` currently stores the model's YES probability for both sides. The Brier formula `(outcome - predicted_prob)²` requires both to be in the same frame. After flipping `outcome` to "did the bettor win?", `predicted_prob` must also represent the bettor's probability of winning — i.e., `1 - model_YES_prob` for NO-side trades. **The numerical Brier score is invariant to this flip** (the value is identical before and after). But the semantic frame becomes correct: Brier now measures calibration of the bettor's win probability rather than the YES probability of someone who bet NO. This enables meaningful cross-side calibration comparisons.

### Why Both Flips Are Needed

- `outcome` flip: **win-rate correctness** — the primary behavioral fix
- `predicted_prob` flip: **Brier semantic correctness** — the numerical value doesn't change, but the frame is now consistent across YES and NO-side trades

Omitting the `predicted_prob` flip leaves win-rate fixed but Brier semantically incorrect for NO-side trades. Both must be applied together.

### Handling `predicted_prob = None` on NO-side trades

If a NO-side trade has no model probability in the buy record (`predicted_prob = None`), the code must:
- Flip `_outcome` (the win-rate fix still applies and does not require a probability)
- Skip the `predicted_prob` flip (the `if predicted_prob is not None:` guard handles this)
- Write `predicted_prob = None` and `brier_score = None` to the scored record (correct — no Brier without a prob)
- Win-rate analysis will correctly count this trade; Brier analysis will exclude it

This is correct behavior and requires no special handling beyond the guard already in the proposed code.

### The Fix

Insert the NO-side flip BEFORE the Brier calculation, immediately after `_outcome` is set from `settlement_result`:

```python
        # For NO-side trades: flip outcome and predicted_prob into the bettor's frame.
        # outcome=1 must mean "bettor won" regardless of side.
        # predicted_prob must represent the bettor's win probability for Brier to be meaningful.
        # NOTE: If predicted_prob is None, only _outcome is flipped. Brier stays None (correct).
        # NOTE: edge is NOT flipped — it is already signed from the bettor's perspective.
        side = rec.get('side') or buy_rec.get('side', 'yes')
        if side == 'no' and _outcome is not None:
            _outcome = 1 - _outcome
            if predicted_prob is not None:
                predicted_prob = round(1.0 - float(predicted_prob), 4)

        # Compute Brier score
        _brier = None
        if _outcome is not None and predicted_prob is not None:
            _brier = round((_outcome - float(predicted_prob)) ** 2, 4)
```

### Verification Table

| Scenario | Before fix | After fix |
|---|---|---|
| NO buyer wins (settled NO), prob=0.03 | outcome=0, prob=0.03, brier=0.0009 | outcome=1, prob=0.97, brier=0.0009 |
| NO buyer loses (settled YES), prob=0.03 | outcome=1, prob=0.03, brier=0.9409 | outcome=0, prob=0.97, brier=0.9409 |
| NO buyer wins, prob=None | outcome=0, prob=None, brier=None | outcome=1, prob=None, brier=None |
| YES buyer wins (settled YES), prob=0.70 | outcome=1, prob=0.70, brier=0.09 ✓ | unchanged ✓ |

Brier values are identical before and after — only the semantic frame changes. Win-rate counts change for all NO-side trades.

### `edge` Field — Intentionally NOT Flipped

The `edge` field in the scored dict (`buy_rec.get('edge', 0)`) represents `model_prob - market_prob` (YES side). For NO-side trades, a negative edge means the NO side has a positive edge. This signed convention is already correct and should NOT be flipped. Dev must not flip it.

### What Could Go Wrong

- **Historical records** in `scored_predictions.jsonl` have inverted outcome/prob for all NO-side trades. Delete the file and re-score cleanly after deploying the fix. The scorer is idempotent and will re-process all settled trades.
- **Reporting discontinuity:** If the file is NOT deleted, historical and post-fix records will have opposite outcome conventions. Optimizer win-rate trends will be inconsistent across the boundary. Delete the file. This is the only clean path.
- The scorer uses `(ticker, date)` as the dedup key. After deletion, all settled trades are re-scored. This is safe and correct.

**Scope:** `environments/demo/prediction_scorer.py` only  
**Trading behavior change:** None — scorer is read-only  
**Risk:** Low. Delete `scored_predictions.jsonl` and re-score cleanly.

---

## ISSUE-040 — Domain Name Mismatch Kills Optimizer

**Files:** `environments/demo/prediction_scorer.py`, `agents/ruppert/strategist/optimizer.py`

### ⚠️ Hard Prerequisite

**ISSUE-006 must be deployed first and `scored_predictions.jsonl` must be deleted before ISSUE-040 takes effect.**

This is not a suggestion — it is a hard dependency. After ISSUE-006 is deployed and the file is deleted, the scorer will produce fresh records with correctly-framed outcomes AND correct `domain` field values (from `module` on the trade record). ISSUE-040's fix relies on these fresh records. If ISSUE-040 is deployed without ISSUE-006, the optimizer will read records with inverted NO-side outcomes AND the domain population will be mixed (old records with coarse `detect_module()` domains, new records with fine-grained `classify_module()` domains). The result: incorrect domain counts and contaminated win-rate tables.

**Deploy order is mandatory: ISSUE-006 → delete `scored_predictions.jsonl` → ISSUE-040.**

### What currently happens

**Scorer writes** `domain` = full module name (e.g. `"crypto_dir_15m_btc"`) from `rec.get('module') or buy_rec.get('module', '')` — the `classify_module()` taxonomy name.

**Optimizer ignores the `domain` field entirely.** In `get_domain_trade_counts()`, it calls `detect_module(ticker)` which returns coarse buckets:

```python
def detect_module(ticker: str) -> str:
    t = ticker.upper()
    if t.startswith("KXHIGH"):
        return "weather"
    for kw in ("BTC", "ETH", "SOL"):
        if kw in t:
            return "crypto"        # ← "crypto", not "crypto_dir_15m_btc"
    ...
```

Result: all BTC/ETH/SOL trades collapse into `"crypto"` (45+ trades total), while the scorer wrote them as `crypto_dir_15m_btc`, `crypto_dir_15m_eth`, etc. The optimizer reports "crypto: 45 trades [ELIGIBLE]" — misleading David into thinking there are 45 trades of a single type, when they are actually spread across 5+ subcategories.

Additionally, `enrich_trades()` also calls `detect_module(ticker)` when a trade record has no `module` field — so `analyze_win_rate_by_module()` will still bucket by coarse names ("crypto", "weather", etc.) even after the `get_domain_trade_counts()` fix.

### The Fix — Two Parts

#### Part 1: Fix `get_domain_trade_counts()` in optimizer.py

Replace `detect_module(ticker)` with the `domain` field from the scored record:

```python
def get_domain_trade_counts() -> dict[str, int]:
    counts = defaultdict(int)
    scored_path = LOGS_DIR / "scored_predictions.jsonl"
    if not scored_path.exists():
        return dict(counts)
    with open(scored_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ticker = rec.get("ticker", "")
                # Use stored domain (fine-grained classify_module name) if present;
                # fall back to detect_module for legacy records without domain field.
                domain = rec.get("domain") or detect_module(ticker)
                if domain:
                    counts[domain] += 1
            except json.JSONDecodeError:
                pass
    return dict(counts)
```

#### Part 2: Fix `enrich_trades()` in optimizer.py

Replace the `detect_module()` fallback with `classify_module()` from logger.py so that `analyze_win_rate_by_module()` uses fine-grained names:

```python
def enrich_trades(trades: list, outcomes: dict) -> list:
    from agents.ruppert.data_scientist.logger import classify_module as _classify_module
    enriched = []
    for t in trades:
        rec = dict(t)
        # Module: use stored module if present; derive via classify_module (not detect_module)
        # so win-rate-by-module reports use fine-grained names (crypto_dir_15m_btc, not crypto)
        if "module" not in rec or not rec["module"]:
            rec["module"] = _classify_module(rec.get("source", ""), rec.get("ticker", ""))
        # ... rest of enrichment unchanged
```

This ensures `analyze_win_rate_by_module()` buckets by fine-grained names consistently with `get_domain_trade_counts()`.

### `DOMAIN_THRESHOLD` After the Fix — Concrete Recommendation

**Current value:** `DOMAIN_THRESHOLD = 30` (hardcoded in optimizer.py)

**Problem after fix:** Fine-grained domains will have far fewer trades than the coarse buckets. Estimated current trade counts (based on bot running since 2026-03-26, ~8 days):
- Coarse `"crypto"`: ~45 total trades (BTC + ETH + SOL combined)
- Fine-grained per-asset breakdown (estimated): `crypto_dir_15m_btc` ~15-20, `crypto_dir_15m_eth` ~10-15, others ~5-8
- `"weather"` coarse: varies — may split into `weather_band` and `weather_threshold`, each with fewer records
- `"geo"`: small volume, likely 5-15 total

At `DOMAIN_THRESHOLD=30`, virtually no fine-grained domain will be eligible. The optimizer will print "No domains eligible" and appear broken.

**Recommended fix:** Lower `DOMAIN_THRESHOLD` to `10` for the fine-grained regime.

```python
DOMAIN_THRESHOLD = 10  # Fine-grained domains (e.g. crypto_dir_15m_btc) — lowered from 30
```

Rationale: 10 trades per fine-grained domain is the minimum for any meaningful pattern detection. At the current trading rate (~1-3 trades/day per asset), most active subcategories will reach 10 within 5-10 days. As the dataset grows (target: 30+ per fine-grained domain), David can raise this back toward 30 via config. The change is low-risk because `run_domain_experiments()` is still a placeholder — eligible domain counts affect reporting only, not trading decisions.

**Note:** Also update the console output label from `"threshold=30"` to `f"threshold={DOMAIN_THRESHOLD}"` so the printed value stays in sync.

### What Could Go Wrong

- **Mixed domain population if ISSUE-006 is skipped:** Old records (pre-fix) will have `domain` values from before `classify_module()` was used consistently, or may have `domain=null`/`domain=""`. The `or detect_module(ticker)` fallback handles the null/empty case, but coarse-named records from before the fix will contaminate counts. This is why deleting the file as part of ISSUE-006 is a hard prerequisite — not optional.
- **`run_domain_experiments()` receives fine-grained domain names:** When this function is eventually implemented, domain strings passed to it will be fine-grained (e.g. `"crypto_dir_15m_btc"`). Implementation must use these directly — do not map back to coarse names.
- **`analyze_win_rate_by_module()` module names must match:** After Part 2 (enrich_trades fix), win-rate tables will show fine-grained names. This is correct. If any downstream reporting or David's manual review uses coarse names for grouping, `get_parent_module()` from `logger.py` can be used for display rollup.

**Scope:** `optimizer.py` (`get_domain_trade_counts()` and `enrich_trades()`) — ~20 lines total  
**Trading behavior change:** None — optimizer is analysis-only  
**Risk:** Very low (requires ISSUE-006 prerequisite to be completed first)

---

## Fix Order (Mandatory)

1. **ISSUE-006 first** — deploy the NO-side flip to `prediction_scorer.py`, then delete `scored_predictions.jsonl` and let the scorer re-process all settled trades. This is the hard prerequisite for ISSUE-040.
2. **ISSUE-040 second** — after fresh scored data exists with correct outcomes and fine-grained domain names.
3. **ISSUE-007** — capital safety fix; independent of the above, but should be in the same sprint. Dev must patch both `logger.py` AND `capital.py` (`get_capital()` and `get_pnl()`) together — shipping only the logger fix without fixing capital.py is ineffective.

---

_David reviews before Dev starts._
