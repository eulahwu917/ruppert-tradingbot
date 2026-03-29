# Developer Fix Log — 2026-03-13

**SA-2 Developer** | Task: Two targeted strategy.py fixes

---

## Status: ✅ COMPLETE — Both files updated

Files modified:
- `ruppert-tradingbot-demo/bot/strategy.py`
- `ruppert-tradingbot-live/bot/strategy.py`

---

## Fix 1: MAX_POSITION_CAP — Line 32

**Changed:**
```python
# Before
MAX_POSITION_CAP = 25.0          # hard dollar cap per single position entry

# After
MAX_POSITION_CAP = 50.0          # hard dollar cap per single position entry
```

---

## Fix 2: MIN_VIABLE_TRADE guard — Lines 191–194 (inserted after line 189)

**Added after `kelly_size_zero` check:**
```python
    # --- Minimum viable trade ---
    min_viable = round(max(5.0, capital * 0.01), 2)
    if size < min_viable:
        return {'enter': False, 'size': 0.0, 'reason': f'below_min_viable (${size:.2f} < ${min_viable:.2f})'}
```

This guard fires when computed size is positive but below the floor of `max($5.00, 1% of capital)`, preventing tiny uneconomical trades from being placed.

---

## Verification

Both files confirmed identical at:
- Line 32: `MAX_POSITION_CAP = 50.0`
- Lines 189–194: `kelly_size_zero` guard followed immediately by `min_viable` guard

No git operations performed — pending CEO/David push approval.
