# P0 Mini-Sprint — Dev Implementation Notes
**Date:** 2026-04-03  
**Developer:** Dev sub-agent  
**Session:** Dev-P0-MiniSprint

---

## Pre-Implementation Code Review

Read both spec files and all target source files before making any changes. Notes:

### Files examined
- `agents/ruppert/trader/position_monitor.py` — confirmed `WS_ENABLED = True` at line ~62
- `agents/ruppert/strategist/strategy.py` — confirmed `if vol_ratio > 0: kelly_size *= (1.0 / vol_ratio)` block
- `agents/ruppert/data_scientist/logger.py` — confirmed `except Exception as e: ... return 0.0` in `compute_closed_pnl_from_logs()`; `_pnl_mtime_cache` defined at module level
- `agents/ruppert/data_scientist/capital.py` — confirmed both `get_capital()` and `get_pnl()` swallow RuntimeError silently
- `environments/demo/prediction_scorer.py` — confirmed `_outcome` derived from `settlement_result` only, no side-flip
- `agents/ruppert/strategist/optimizer.py` — confirmed `get_domain_trade_counts()` uses `detect_module(ticker)` ignoring `domain` field; `enrich_trades()` uses `detect_module`; `DOMAIN_THRESHOLD = 30` hardcoded

### No spec contradictions found
All code matched spec descriptions exactly.

---

## Batch 1 — ISSUE-034 + ISSUE-117

**Status:** IMPLEMENTING

### ISSUE-034: position_monitor.py WS_ENABLED = True → False
- File: `agents/ruppert/trader/position_monitor.py`
- Change: Line with `WS_ENABLED = True` → `WS_ENABLED = False`
- Also: comment updated to reflect retired status
- Secondary effect: `_settle_single_ticker()` source stamp will now always write `"poll_settlement"` — correct

### ISSUE-117: strategy.py vol_ratio=0 guard
- File: `agents/ruppert/strategist/strategy.py`  
- Change: Replace `if vol_ratio > 0: kelly_size *= (1.0 / vol_ratio)` with guard + unconditional multiply
- Exact replacement per spec:
  ```python
  if vol_ratio <= 0:
      return 0.0  # missing vol data — do not trade
  kelly_size *= (1.0 / vol_ratio)
  ```
- Verified: `calculate_position_size(vol_ratio=0)` → 0.0 ✅
- Verified: `calculate_position_size(vol_ratio=1.0)` → >0.0 ✅

**BATCH 1 READY FOR QA**

---

## Batch 2 — ISSUE-007

**Status:** PENDING BATCH 1 QA

### logger.py: compute_closed_pnl_from_logs()
- Replace `except Exception as e: ... return 0.0` with cache invalidation + RuntimeError raise
- Verified: RuntimeError raised + mtime/value both set to None on failure ✅

### capital.py: get_capital() and get_pnl()
- `get_capital()`: isolate `compute_closed_pnl_from_logs()` in inner try/except re-raise; outer except also re-raises RuntimeError explicitly via `isinstance(e, RuntimeError)` check
- `get_pnl()`: replace silent swallow with re-raise
- Verified: `get_capital()` raises RuntimeError when compute fails ✅
- Verified: `get_capital()` works normally when no error ✅
- Verified: `get_pnl()` raises RuntimeError when compute fails ✅
- Verified: non-RuntimeError exceptions (deposits file failures) still fall back to default ✅

**BATCH 2 READY FOR QA**

---

## Batch 3 — ISSUE-006

**Status:** PENDING BATCH 2 QA

### prediction_scorer.py
- Insert NO-side flip block after `_outcome` is set, before Brier calculation
- Flip both `_outcome` and `predicted_prob` for NO-side trades
- Do NOT flip `edge`
- All 4 spec verification cases pass ✅:
  - NO buyer wins (settled NO), prob=0.03 → outcome=1, prob=0.97, brier=0.0009 ✅
  - NO buyer loses (settled YES), prob=0.03 → outcome=0, prob=0.97, brier=0.9409 ✅
  - NO buyer wins, prob=None → outcome=1, prob=None, brier=None ✅
  - YES buyer wins (settled YES), prob=0.70 → outcome=1, prob=0.70, brier=0.09 ✅

**BATCH 3 READY FOR QA**

---

## Batch 4 — ISSUE-040

**Status:** PENDING BATCH 3 QA (hard prerequisite: ISSUE-006)

### optimizer.py
- `get_domain_trade_counts()`: use `rec.get("domain") or detect_module(ticker)` — fine-grained domain from stored field, fallback for legacy records
- `enrich_trades()`: replace `detect_module()` with `classify_module()` from logger.py — imports at function top
- `DOMAIN_THRESHOLD`: lowered from 30 to 10 with explanatory comment
- Console output label updated: `threshold=30` → `f"threshold={DOMAIN_THRESHOLD}"`
- Verified: `DOMAIN_THRESHOLD = 10` ✅
- Verified: `get_domain_trade_counts()` reads fine-grained `domain` field, falls back to `detect_module` for legacy ✅
- Verified: `enrich_trades()` produces `crypto_dir_15m_btc` instead of coarse `crypto` ✅

**BATCH 4 READY FOR QA**

---

## Summary of All Changes

| Batch | Issue | File | Change | Status |
|---|---|---|---|---|
| 1 | ISSUE-034 | `agents/ruppert/trader/position_monitor.py` | `WS_ENABLED = True` → `False` | READY FOR QA |
| 1 | ISSUE-117 | `agents/ruppert/strategist/strategy.py` | Add `vol_ratio <= 0: return 0.0` guard | READY FOR QA |
| 2 | ISSUE-007 | `agents/ruppert/data_scientist/logger.py` | `compute_closed_pnl_from_logs()` raises RuntimeError + invalidates cache | READY FOR QA |
| 2 | ISSUE-007 | `agents/ruppert/data_scientist/capital.py` | `get_capital()` + `get_pnl()` re-raise RuntimeError | READY FOR QA |
| 3 | ISSUE-006 | `environments/demo/prediction_scorer.py` | NO-side flip for outcome + predicted_prob | READY FOR QA |
| 4 | ISSUE-040 | `agents/ruppert/strategist/optimizer.py` | domain field read, classify_module, DOMAIN_THRESHOLD=10 | READY FOR QA |

---
