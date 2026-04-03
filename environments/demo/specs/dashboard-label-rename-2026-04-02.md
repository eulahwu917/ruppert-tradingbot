# Spec: Dashboard Card Label Rename

**Date:** 2026-04-02
**Author:** DS (Data Scientist)
**Status:** Ready for Dev

## Problem

The dashboard cards still display legacy labels `1H Dir` and `1H Band` from the old taxonomy. These need to be renamed to `Threshold Daily` and `Band Daily` to match the Phase A taxonomy rename completed on 2026-04-01.

## Changes Required

**File:** `dashboard/templates/index.html`

| Line | Old Label | New Label |
|------|-----------|-----------|
| 509 (comment) | `<!-- ₿ 1H Dir -->` | `<!-- ₿ Threshold Daily -->` |
| 514 (display) | `1H Dir` | `Threshold Daily` |
| 553 (comment) | `<!-- ₿ 1H Band -->` | `<!-- ₿ Band Daily -->` |
| 558 (display) | `1H Band` | `Band Daily` |

## Scope

- Display labels only — no module IDs, API keys, or JS variable names change.
- The underlying module IDs (`crypto_threshold_daily`, `crypto_band_daily`) are already correct.

## Testing

- After change, reload dashboard at `http://localhost:8765/` and verify:
  - Card header reads "Threshold Daily" (not "1H Dir")
  - Card header reads "Band Daily" (not "1H Band")
  - All stats (P&L, win rate, trade counts) still populate correctly.

## Notes

- Dev must NOT commit. Hand to QA after implementation.
