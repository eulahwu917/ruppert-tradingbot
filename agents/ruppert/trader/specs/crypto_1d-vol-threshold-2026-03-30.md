# Spec: crypto_1d — R1 Volatility Threshold Per-Asset

**File:** `agents/ruppert/trader/crypto_1d.py`
**Date:** 2026-03-30
**Author:** Ruppert (Trader)
**Status:** Ready for Dev

---

## Problem

The R1 (extreme volatility) filter hardcodes `0.04` as the ATR% threshold for all assets:

```python
# R1: extreme volatility
atr_pct = s3.get('ATR_pct', 0.0)
if atr_pct > 0.04:
    return _skip(asset, window, f'R1_extreme_vol (ATR_pct={atr_pct:.3f})', signals_dict)
```

Meanwhile, the file already defines a per-asset `HIGH_VOL_THRESHOLD` dict:

```python
HIGH_VOL_THRESHOLD = {
    'BTC': 0.03,
    'ETH': 0.04,
    'SOL': 0.05,
}
```

The R1 filter ignores this dict entirely. This means:
- **BTC** is under-filtered: its threshold should be 0.03, but 0.04 is used → trades enter on days that should be skipped.
- **SOL** is over-filtered: its threshold should be 0.05, but 0.04 is used → valid high-vol SOL days are incorrectly blocked.
- **ETH** is coincidentally correct (both are 0.04).

The `compute_s3_atr_band()` function (line 322) already uses `HIGH_VOL_THRESHOLD.get(asset, 0.04)` correctly for `high_vol_day` flagging. The R1 gate should use the same lookup.

---

## Location

Approximately line 911–914 of `crypto_1d.py`, inside `evaluate_1d_entry(asset, window, ...)`:

```python
# R1: extreme volatility
atr_pct = s3.get('ATR_pct', 0.0)
if atr_pct > 0.04:
    return _skip(asset, window, f'R1_extreme_vol (ATR_pct={atr_pct:.3f})', signals_dict)
```

---

## BEFORE

```python
# R1: extreme volatility
atr_pct = s3.get('ATR_pct', 0.0)
if atr_pct > 0.04:
    return _skip(asset, window, f'R1_extreme_vol (ATR_pct={atr_pct:.3f})', signals_dict)
```

---

## AFTER

```python
# R1: extreme volatility — per-asset threshold
atr_pct = s3.get('ATR_pct', 0.0)
if atr_pct > HIGH_VOL_THRESHOLD.get(asset, 0.04):
    return _skip(asset, window, f'R1_extreme_vol (ATR_pct={atr_pct:.3f})', signals_dict)
```

**No other changes.** `HIGH_VOL_THRESHOLD` is already defined at module level and is in scope.

---

## Acceptance Criteria

1. R1 filter uses `HIGH_VOL_THRESHOLD.get(asset, 0.04)` — not the literal `0.04`.
2. BTC R1 threshold = 0.03 (tighter filter).
3. ETH R1 threshold = 0.04 (unchanged behaviour).
4. SOL R1 threshold = 0.05 (looser filter, matches its higher vol profile).
5. Any unknown asset falls back to 0.04 (via `.get(asset, 0.04)`).
6. The skip reason string in the decision log is unchanged (`R1_extreme_vol (ATR_pct=X.XXX)`).
7. `compute_s3_atr_band()` is **not modified** — it already uses `HIGH_VOL_THRESHOLD` correctly.

---

## Out of Scope

- **Do not** wire `get_active_positions(asset=)` or `get_daily_exposure(asset=)` into this change. That simplification of fallback guards is a separate Dev task pending DS specs.

---

## Risk

**Low.** One-line change. Only affects BTC (tightens filter) and SOL (loosens filter). ETH behaviour unchanged. Change is directly consistent with the intent of `HIGH_VOL_THRESHOLD` as already documented in the file.
