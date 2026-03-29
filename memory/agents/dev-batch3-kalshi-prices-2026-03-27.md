# Dev Batch 3: Kalshi Price Fetching Fix — 2026-03-27

## Problem
Crypto (`main.py:run_crypto_scan`) and Econ (`economics_scanner.py:fetch_open_markets`) both used raw `requests.get()` to fetch Kalshi markets. The list endpoint returns `null` for `yes_ask`/`no_ask`/`yes_bid`/`no_bid` — only the per-market orderbook endpoint has real prices. Weather already worked correctly because it routed through `KalshiClient`.

## Changes Made

### Fix 1: Crypto — `main.py:run_crypto_scan`
- **Removed**: `r = requests.get(BASE, params={...})` + `r.json().get('markets', [])`
- **Replaced with**: `client.get_markets(series, status='open', limit=50)`
- **Removed**: Unused `BASE` variable (line 435)
- **Added**: Comment explaining the ~250 orderbook API calls are intentional
- `KalshiClient` was already instantiated at line 436; no new import needed

### Fix 2: Econ — `economics_scanner.py:fetch_open_markets`
- **Removed**: Raw `requests.get(f'{BASE}/markets', ...)` block
- **Replaced with**: `KalshiClient()` instantiation + `client.get_markets(series_ticker, status='open', limit=limit)`
- Added `from kalshi_client import KalshiClient` import inside the function

### No downstream changes needed
- All existing `m.get('yes_ask')`, `m.get('no_ask')`, etc. reads work as-is because `KalshiClient.get_markets()` enriches each market dict with orderbook prices (integer cents).

## Verification
- Syntax check passed (`ast.parse`) for both `main.py` and `economics_scanner.py`

## Status: COMPLETE — ready for QA
