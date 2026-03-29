# Dev Cleanup — 2026-03-26 (SA-3)

## Summary

Three surgical fixes applied to the Ruppert trading bot.

---

## Fix 1 — Optimizer thresholds moved to config.py

**Files:** `config.py`, `optimizer.py`

Added new `# Optimizer thresholds` section at the bottom of `config.py`:
- `OPTIMIZER_MIN_TRADES = 30`
- `OPTIMIZER_LOW_WIN_RATE = 0.60`
- `OPTIMIZER_BRIER_FLAG = 0.25`
- `OPTIMIZER_HOLD_TIME_FLAG_HRS = 12`
- `OPTIMIZER_CAP_UTIL_FLAG = 0.30`
- `OPTIMIZER_MAX_AVG_SIZE = 40.0`

In `optimizer.py`, replaced 6 hardcoded module-level constants with `getattr(_config, ...)` reads with fallback defaults. Thresholds are now tunable from config without touching optimizer logic.

---

## Fix 2 — Legacy commented-out constants removed from config.py

**File:** `config.py`

Removed the entire `# Legacy fixed-dollar caps (kept for reference...)` comment block (8 commented-out lines for MAX_POSITION_SIZE, MAX_DAILY_EXPOSURE, CRYPTO/GEO/ECON variants).

Cleaned up inline comments on 4 active lines:
- `ECON_MAX_POSITION` → `# kept for ruppert_cycle.py budget checks`
- `ECON_MAX_DAILY_EXPOSURE` → `# kept for ruppert_cycle.py budget checks`
- `GEO_MAX_POSITION_SIZE` → `# kept for ruppert_cycle.py budget checks`
- `GEO_MAX_DAILY_EXPOSURE` → `# kept for ruppert_cycle.py budget checks`

---

## Fix 3 — Crypto confidence: real multi-factor score replaces edge proxy

**File:** `ruppert_cycle.py`

Before: `'confidence': round(best_edge, 3)` — edge value used as a proxy.

After: composite score computed just before `new_crypto.append()`:
```python
_spread = ya - na
_spread_score = max(0.0, 1.0 - (_spread / 20.0))  # tighter spread = higher score
_edge_score = min(1.0, best_edge / 0.30)            # 30% edge = max score
_time_score = min(1.0, _hours_left / 48.0)           # 48h+ = max score
_crypto_confidence = round((_edge_score * 0.5 + _spread_score * 0.3 + _time_score * 0.2), 3)
```

Weights: edge 50%, spread 30%, time to settlement 20%.

---

## Syntax Checks

All three modified files passed `ast.parse()`:
- `config.py SYNTAX OK`
- `optimizer.py SYNTAX OK`
- `ruppert_cycle.py SYNTAX OK`
