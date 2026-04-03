# Spec: Fix tracked_positions.json module field

**Date:** 2026-04-02
**Priority:** P0
**Author:** DS (Ruppert)
**Status:** Ready for Dev

## Problem

7 of 12 entries in `logs/tracked_positions.json` have `module: "crypto"` instead of the specific module ID assigned by `classify_module()` in `agents/ruppert/data_scientist/logger.py:461`. This breaks per-module P&L bucketing, cap enforcement, and dashboard rollups.

## Root cause

These positions were opened before the module taxonomy migration (2026-04-01 Phase A rename). The entry code at that time wrote the raw source string `"crypto"` rather than routing through `classify_module()`.

## Fix: field-level changes

All 7 positions are band-type daily crypto (ticker contains `-B`). No `src` parameter needed — ticker prefix alone is unambiguous.

| Position Key | Current `module` | Correct `module` |
|---|---|---|
| `KXBTC-26APR0217-B66375::yes` | `crypto` | `crypto_band_daily_btc` |
| `KXETH-26APR0317-B2060::yes` | `crypto` | `crypto_band_daily_eth` |
| `KXBTC-26APR0217-B66625::yes` | `crypto` | `crypto_band_daily_btc` |
| `KXBTC-26APR0217-B66125::yes` | `crypto` | `crypto_band_daily_btc` |
| `KXDOGE-26APR0317-B0.092::yes` | `crypto` | `crypto_band_daily_doge` |
| `KXBTC-26APR0217-B66875::yes` | `crypto` | `crypto_band_daily_btc` |
| `KXXRP-26APR0317-B1.3299500::yes` | `crypto` | `crypto_band_daily_xrp` |

## Positions already correct (no change)

| Position Key | Module (correct) |
|---|---|
| `KXBTC-26APR0212-B66950::yes` | `crypto_band_daily_btc` |
| `KXDOGE15M-26APR021145-45::no` | `crypto_dir_15m_doge` |
| `KXXRP15M-26APR021145-45::yes` | `crypto_dir_15m_xrp` |
| `KXBTC15M-26APR021145-45::yes` | `crypto_dir_15m_btc` |
| `KXETH15M-26APR021145-45::yes` | `crypto_dir_15m_eth` |

## Implementation instructions (Dev)

1. Load `logs/tracked_positions.json`
2. For each of the 7 keys listed above, set `positions[key]["module"]` to the correct value
3. Atomic write: write to `tracked_positions.json.tmp`, then rename over the original
4. Do NOT commit — hand to QA for verification

## Verification (QA)

- `jq '[.[]] | map(select(.module == "crypto")) | length' logs/tracked_positions.json` should return `0`
- All 12 entries should have a module matching `classify_module()` output for their ticker
