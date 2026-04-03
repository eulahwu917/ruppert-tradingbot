# Migration: Add KXXRPD / KXDOGED rules to pnl_correction_module_id.py

**Status:** Ready for Dev
**Date:** 2026-04-02
**Author:** DS audit
**Prerequisite:** classify_module fix in logger.py (see `specs/classify-module-kxxrpd-fix-2026-04-02.md`)

---

## Problem

`scripts/pnl_correction_module_id.py` has 8 ticker-to-module patterns in `_TICKER_MODULE_PATTERNS` but is missing rules for **KXXRPD** (XRP threshold daily) and **KXDOGED** (DOGE threshold daily). Trades with these tickers logged with `module="crypto"` will not be corrected.

### Affected records

3 KXXRPD records found in `logs/trades/trades_2026-04-02.jsonl`:

| Line | Ticker | Action | Module (current) | Module (correct) |
|------|--------|--------|------------------|------------------|
| 167 | `KXXRPD-26APR0210-T1.2999` | buy | `crypto` | `crypto_threshold_daily_xrp` |
| 208 | `KXXRPD-26APR0210-T1.2999` | settle | `crypto` | `crypto_threshold_daily_xrp` |
| 225 | `KXXRPD-26APR0210-T1.2999` | settle | `crypto` | `crypto_threshold_daily_xrp` |

**KXDOGED:** 0 records found in any `.jsonl` or `.csv` trade log. Rule added for future-proofing.

> Note: The original estimate was 7 KXXRPD records. 3 additional KXXRPD records exist in `logs/all_trades_export.csv` (from the deleted `trades_2026-03-31.jsonl`) with `module=crypto_1h_band`, but those are no longer in active JSONL trade logs. 1 open position reference exists in `logs/state.json`.

---

## Fix

### Add two entries to `_TICKER_MODULE_PATTERNS` (line 23-32)

Insert after line 31 (`KXSOLD` rule), before the closing `]`:

```python
    (re.compile(r'^KXXRPD'),    'crypto_threshold_daily_xrp'),
    (re.compile(r'^KXDOGED'),   'crypto_threshold_daily_doge'),
```

The resulting `_TICKER_MODULE_PATTERNS` should be:

```python
_TICKER_MODULE_PATTERNS = [
    (re.compile(r'^KXBTC-.*-B'),   'crypto_band_daily_btc'),
    (re.compile(r'^KXETH-.*-B'),   'crypto_band_daily_eth'),
    (re.compile(r'^KXXRP-.*-B'),   'crypto_band_daily_xrp'),
    (re.compile(r'^KXDOGE-.*-B'),  'crypto_band_daily_doge'),
    (re.compile(r'^KXSOL-.*-B'),   'crypto_band_daily_sol'),
    (re.compile(r'^KXBTCD-.*-T'),  'crypto_threshold_daily_btc'),
    (re.compile(r'^KXETHD-.*-T'),  'crypto_threshold_daily_eth'),
    (re.compile(r'^KXSOLD-.*-T'),  'crypto_threshold_daily_sol'),
    (re.compile(r'^KXXRPD'),       'crypto_threshold_daily_xrp'),
    (re.compile(r'^KXDOGED'),      'crypto_threshold_daily_doge'),
]
```

Note: KXXRPD/KXDOGED patterns omit the `-.*-T` suffix used by BTC/ETH/SOL. This is safe because `KXXRPD` is an unambiguous prefix (the band-daily XRP ticker is `KXXRP-`, never `KXXRPD`). The simpler pattern also matches existing records that use `module="crypto"` regardless of ticker suffix format.

### No other changes needed

- The `process_file()` function already handles the `module == 'crypto'` check and atomic file writes.
- `TARGET_FILES` already includes `trades_2026-04-02.jsonl` where the 3 affected records live.

---

## Verification

After adding the rules, dry-run should show:

```
DRY-RUN: line 167 | KXXRPD-26APR0210-T1.2999 | module='crypto' -> 'crypto_threshold_daily_xrp'
DRY-RUN: line 208 | KXXRPD-26APR0210-T1.2999 | module='crypto' -> 'crypto_threshold_daily_xrp'
DRY-RUN: line 225 | KXXRPD-26APR0210-T1.2999 | module='crypto' -> 'crypto_threshold_daily_xrp'
Total records to correct: 3
```

Then `--apply` to write.

---

## Scope

- **Only** modify `_TICKER_MODULE_PATTERNS` in `scripts/pnl_correction_module_id.py`
- **DO NOT** commit — hand to QA after implementation
