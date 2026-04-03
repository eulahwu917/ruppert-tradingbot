# Spec: Onboard KXSOL15M — Add SOL to 15-Minute Crypto Direction Scanner

**Date:** 2026-03-30
**Author:** Trader (Ruppert)
**Priority:** High — Live instrument not being scanned or traded
**Type:** New instrument onboarding (no architectural change)

---

## Problem

`KXSOL15M` is live on Kalshi with CF Benchmarks RTI settlement — identical architecture to the existing BTC/ETH/XRP/DOGE 15-minute direction series. It is not currently being scanned, cached, or evaluated because it is absent from two configuration locations.

---

## Files to Change

1. `environments/demo/config.py` — `WS_ACTIVE_SERIES` list
2. `agents/ruppert/trader/crypto_15m.py` — `CRYPTO_15M_SERIES` list and `ASSET_SYMBOLS` dict (and `_parse_asset_from_ticker`)

---

## Change 1 of 3 — `environments/demo/config.py`: Add `'KXSOL15M'` to `WS_ACTIVE_SERIES`

### BEFORE

```python
# Crypto 15m direction
'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M',
```

### AFTER

```python
# Crypto 15m direction
'KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M',
```

**Location:** `environments/demo/config.py`, `WS_ACTIVE_SERIES` list, line ~180
**Effect:** WebSocket cache layer will now ingest and retain KXSOL15M tickers.

---

## Change 2 of 3 — `agents/ruppert/trader/crypto_15m.py`: Add `'KXSOL15M'` to `CRYPTO_15M_SERIES` and `'SOL'` to `ASSET_SYMBOLS`

### BEFORE

```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M']

ASSET_SYMBOLS = {
    'BTC':  'BTC-USDT-SWAP',
    'ETH':  'ETH-USDT-SWAP',
    'XRP':  'XRP-USDT-SWAP',
    'DOGE': 'DOGE-USDT-SWAP',
}
```

### AFTER

```python
CRYPTO_15M_SERIES = ['KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M']

ASSET_SYMBOLS = {
    'BTC':  'BTC-USDT-SWAP',
    'ETH':  'ETH-USDT-SWAP',
    'XRP':  'XRP-USDT-SWAP',
    'DOGE': 'DOGE-USDT-SWAP',
    'SOL':  'SOL-USDT-SWAP',
}
```

**Location:** `agents/ruppert/trader/crypto_15m.py`, lines ~52–59
**Effect:** Scanner recognizes KXSOL15M tickers; OKX price feed mapped to `SOL-USDT-SWAP`.

---

## Change 3 of 3 — `agents/ruppert/trader/crypto_15m.py`: Add `'KXSOL15M'` to `_parse_asset_from_ticker()`

### BEFORE

```python
def _parse_asset_from_ticker(ticker: str) -> str | None:
    """Extract asset name from 15-min ticker (KXBTC15M-... → BTC)."""
    series = ticker.split('-')[0].upper()
    for prefix in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M'):
        if series == prefix:
            asset = prefix.replace('KX', '').replace('15M', '')
            return asset
    return None
```

### AFTER

```python
def _parse_asset_from_ticker(ticker: str) -> str | None:
    """Extract asset name from 15-min ticker (KXBTC15M-... → BTC)."""
    series = ticker.split('-')[0].upper()
    for prefix in ('KXBTC15M', 'KXETH15M', 'KXXRP15M', 'KXDOGE15M', 'KXSOL15M'):
        if series == prefix:
            asset = prefix.replace('KX', '').replace('15M', '')
            return asset
    return None
```

**Location:** `agents/ruppert/trader/crypto_15m.py`, lines ~799–808
**Effect:** Asset extraction returns `'SOL'` for KXSOL15M tickers, enabling correct price lookup via `ASSET_SYMBOLS`.

---

## Scope Summary

| File | Lines Changed | Change Type |
|------|--------------|-------------|
| `environments/demo/config.py` | 1 | Add `'KXSOL15M'` to list |
| `agents/ruppert/trader/crypto_15m.py` | 2 | Add to `CRYPTO_15M_SERIES`, `ASSET_SYMBOLS` |
| `agents/ruppert/trader/crypto_15m.py` | 1 | Add to `_parse_asset_from_ticker` prefix tuple |

**Total:** 4 lines changed across 2 files. No logic changes. No new functions. Pure list/dict extension following established patterns.

---

## Verification

After changes:
1. Confirm `'KXSOL15M' in WS_ACTIVE_SERIES` → `True`
2. Confirm `'KXSOL15M' in CRYPTO_15M_SERIES` → `True`
3. Confirm `_parse_asset_from_ticker('KXSOL15M-26MAR281315-15')` → `'SOL'`
4. Confirm `ASSET_SYMBOLS['SOL']` → `'SOL-USDT-SWAP'`
5. Run one 15m scan cycle — confirm SOL markets are fetched, evaluated, and eligible for trade

---

## Notes

- Settlement method is CF Benchmarks RTI — identical to existing BTC/ETH/XRP/DOGE 15m contracts. No model changes needed.
- `KXSOL` (hourly bands) is already present in `WS_ACTIVE_SERIES`; this onboarding is specifically for the 15-minute direction series `KXSOL15M`.
- The comment on line ~151 of `config.py` (`# 15-Min Crypto Direction (KXBTC15M / KXETH15M / KXXRP15M / KXDOGE15M)`) should also be updated to include `KXSOL15M` for accuracy.
