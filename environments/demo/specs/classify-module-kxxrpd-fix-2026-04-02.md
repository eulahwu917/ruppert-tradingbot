# classify_module: Add KXXRPD / KXDOGED threshold-daily rules

**Status:** Ready for Dev
**Date:** 2026-04-02
**Found by:** DS audit — KXXRPD/KXDOGED tickers misrouted to `crypto_band_daily` instead of `crypto_threshold_daily`

---

## Problem

`classify_module()` in `agents/ruppert/data_scientist/logger.py` (line 461) has threshold-daily checks for BTC, ETH, and SOL but **not** XRP or DOGE:

```
Line 514:  if t.startswith('KXBTCD')  → crypto_threshold_daily_btc   ✓
Line 516:  if t.startswith('KXETHD')  → crypto_threshold_daily_eth   ✓
Line 518:  if t.startswith('KXSOLD')  → crypto_threshold_daily_sol   ✓
           (KXXRPD  — MISSING)
           (KXDOGED — MISSING)
Line 529:  if t.startswith('KXXRP')   → crypto_band_daily_xrp        ← catches KXXRPD too!
Line 531:  if t.startswith('KXDOGE')  → crypto_band_daily_doge       ← catches KXDOGED too!
```

Since `KXXRP` is a prefix of `KXXRPD`, tickers like `KXXRPD-26APR021200-50` match the band-daily rule instead of threshold-daily. Same for `KXDOGED`.

## Fix

### 1. Add two rules in `logger.py` classify_module(), lines 519–520

Insert **after** line 518 (`KXSOLD` check) and **before** line 521 (`crypto_1d` fallback):

```python
    if t.startswith('KXXRPD'):
        return 'crypto_threshold_daily_xrp'
    if t.startswith('KXDOGED'):
        return 'crypto_threshold_daily_doge'
```

The resulting block (lines 512–524) should read:

```python
    # ── Crypto threshold daily (above/below binary) ───────────────────────
    # NOTE: D-suffix series (KXBTCD) must be checked BEFORE base prefixes (KXBTC)
    if t.startswith('KXBTCD') or (src == 'crypto_1d' and t.startswith('KXBTC')):
        return 'crypto_threshold_daily_btc'
    if t.startswith('KXETHD') or (src == 'crypto_1d' and t.startswith('KXETH')):
        return 'crypto_threshold_daily_eth'
    if t.startswith('KXSOLD') or (src == 'crypto_1d' and t.startswith('KXSOL')):
        return 'crypto_threshold_daily_sol'
    if t.startswith('KXXRPD'):
        return 'crypto_threshold_daily_xrp'
    if t.startswith('KXDOGED'):
        return 'crypto_threshold_daily_doge'
    # Fallback for src='crypto_1d' with unrecognised asset
    if src == 'crypto_1d':
        return 'crypto_threshold_daily_btc'
```

### 2. Update the docstring taxonomy table (line 479)

Add these two entries between the SOL threshold-daily and the band-daily section:

```
      crypto_threshold_daily_xrp    KXXRPD*
      crypto_threshold_daily_doge   KXDOGED*
```

### 3. Check for historical mis-bucketed trades

Dev should run:

```bash
grep -r "KXXRPD\|KXDOGED" logs/trades/ | head -20
```

If any trades exist with these tickers and `module: crypto_band_daily_*`, they were mis-bucketed. The existing `scripts/pnl_correction_module_id.py` can be extended with two new rules to fix them:

```python
    (re.compile(r'^KXXRPD'),   'crypto_threshold_daily_xrp'),
    (re.compile(r'^KXDOGED'),  'crypto_threshold_daily_doge'),
```

## Verification

After the fix, Dev should confirm:
- `classify_module('bot', 'KXXRPD-26APR021200-50')` → `'crypto_threshold_daily_xrp'`
- `classify_module('bot', 'KXDOGED-26APR021200-50')` → `'crypto_threshold_daily_doge'`
- `classify_module('bot', 'KXXRP-26APR021200-50')` → `'crypto_band_daily_xrp'` (unchanged)
- `classify_module('bot', 'KXDOGE-26APR021200-50')` → `'crypto_band_daily_doge'` (unchanged)

## Scope

- **DO NOT** commit — hand back to QA for review after implementation.
- Only touch `logger.py` (classify_module + docstring).
- Do not modify api.py, config.py, or dashboard templates.
