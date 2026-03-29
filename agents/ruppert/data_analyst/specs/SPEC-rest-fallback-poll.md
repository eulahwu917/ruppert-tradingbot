# REST FALLBACK POLL SPEC

**Author:** Data Analyst  
**Date:** 2026-03-29  
**Status:** Ready for Dev (v2 — DS review incorporated)  
**Scope:** `ws_feed.py` only — no other files modified

**Revision history:**
- v2 (2026-03-29): Fix book_depth_usd from REST orderbook (top-3 vols each side); ISO normalization for dedup guard Z suffix; asyncio.get_running_loop() throughout

---

## Summary

The WebSocket feed can go silent for a 15m window if: (a) the connection drops mid-window, (b) Kalshi stops pushing ticker events for a series, or (c) the WS reconnects after the window opens but before any ticker event fires. In all cases, the current 15m window gets zero evaluation coverage.

This spec adds a **background asyncio task** (`_fallback_poll_task`) that wakes every 60 seconds, checks whether each CRYPTO_15M_SERIES has been evaluated for the current window, and fires a REST-based evaluation if the WS has been silent. The task is lifecycle-bound to each WS connection attempt — it is created on connect and cancelled on disconnect/reconnect.

---

## Trigger Mechanism (with task lifecycle — cancel/recreate per reconnect)

### When to fire
- Every 60 seconds while connected
- For each series in `CRYPTO_15M_SERIES`, check: has the current window been evaluated?
- "Current window" = the 15-minute block whose open timestamp ≤ now < close timestamp
- Only fire if: window has been open ≥ 90 seconds (enough for WS to have fired if it was going to) AND window still has ≥ 60 seconds remaining (not late enough to be LATE_WINDOW skipped)
- Do **not** fire in the last 2 minutes of a window (evaluate_crypto_15m_entry will SKIP anyway and this avoids noisy logs)

### Task lifecycle — CRITICAL

The fallback task must be **created and cancelled per reconnect cycle**, not once globally. The `run_ws_feed()` function has a `while True:` reconnect loop; any long-lived background task that survives a disconnect will hold stale state and may double-fire on reconnect.

**Pattern:**

```python
# Inside run_ws_feed(), inside the while True reconnect loop:

async with websockets.connect(...) as ws:
    # ... subscribe ...
    
    # START fallback task for this connection
    fallback_task = asyncio.create_task(_fallback_poll_loop())
    
    try:
        async for raw in ws:
            await handle_message(raw)
            # ... periodic purge/persist logic ...
    finally:
        # CANCEL on every exit (disconnect, exception, clean shutdown)
        fallback_task.cancel()
        try:
            await fallback_task
        except asyncio.CancelledError:
            pass
```

The `finally` block ensures cancellation even on clean exits. On reconnect the outer `while True` creates a fresh task.

### Fallback poll loop implementation

```python
async def _fallback_poll_loop() -> None:
    """Background task: REST-poll each 15m series if WS hasn't fired for current window.
    Created and cancelled per WS connection cycle — do not run globally.
    """
    while True:
        await asyncio.sleep(60)
        try:
            await _check_and_fire_fallback()
        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception as e:
            logger.warning('[WS Feed] Fallback poll error: %s', e)
```

---

## Dedup Guard (per-window, not just cache staleness)

Cache staleness alone is insufficient. Example failure: WS fires evaluation at T+3min for BTC window, then WS reconnects at T+5min and the fallback task wakes up — it would fire a second evaluation for the same window.

### Guard structure

Module-level dict in `ws_feed.py`:

```python
# Keyed by "SERIES::window_open_ts_iso" (e.g. "KXBTC15M::2026-03-29T16:15:00+00:00")
# Value: ISO timestamp when evaluation was first fired (WS or fallback)
_window_evaluated: dict[str, str] = {}
```

### Guard update — WS path

In `handle_message()`, after calling `evaluate_crypto_15m_entry(...)`, mark the window.
WS `open_time` may carry a `Z` suffix (e.g. `2026-03-29T16:15:00Z`) while the fallback
uses `+00:00` format. Normalize before writing the key so both paths produce matching keys:

```python
# Inside the crypto 15m branch of handle_message():
# Normalize Z suffix to match fallback's +00:00 format
_open_time_norm = open_time.replace('Z', '+00:00') if open_time and open_time.endswith('Z') else open_time
if _open_time_norm:
    _guard_key = f"{series_prefix}::{_open_time_norm}"
    _window_evaluated[_guard_key] = datetime.utcnow().isoformat()
```

Where `series_prefix` is determined by which CRYPTO_15M_SERIES the ticker starts with (e.g. `KXBTC15M`).

### Guard check — fallback path

Before firing REST evaluation in `_check_and_fire_fallback()`:

```python
guard_key = f"{series}::{window_open_iso}"
if guard_key in _window_evaluated:
    continue  # already evaluated by WS or prior fallback — skip
```

### Guard cleanup

Prune entries older than 60 minutes in the existing 5-minute purge cycle to prevent unbounded growth:

```python
# Inside the `if now - last_purge > 300:` block:
_prune_window_guard()
```

```python
def _prune_window_guard():
    """Remove dedup entries older than 60 minutes."""
    cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    stale = [k for k, v in _window_evaluated.items() if v < cutoff]
    for k in stale:
        del _window_evaluated[k]
```

---

## Ticker Format (validated from actual log data)

### Observed examples from `decisions_15m.jsonl`

```
KXBTC15M-26MAR291230-30
KXETH15M-26MAR291230-30
KXXRP15M-26MAR291230-30
```

### Pattern breakdown

```
{SERIES}-{YY}{MON}{DD}{HHMM}-{STRIKE}
```

| Component | Example | Notes |
|-----------|---------|-------|
| `SERIES`  | `KXBTC15M` | Series prefix (KXBTC15M, KXETH15M, etc.) |
| `YY`      | `26` | 2-digit year |
| `MON`     | `MAR` | 3-letter month abbreviation |
| `DD`      | `29` | Day, no leading zero (WARNING: unverified for single-digit days) |
| `HHMM`    | `1230` | **Close time in US Eastern Time (ET), not UTC** — confirmed: window_close_ts=16:30 UTC = 12:30 EDT |
| `STRIKE`  | `30` | Floor strike — **varies per market, cannot be hardcoded** |

### Why ticker construction is unsafe

The `-STRIKE` suffix (e.g. `-30`) is the market's floor strike price level and varies. It cannot be derived from the series name or window time alone. Two markets for the same series/window could theoretically have different strikes.

### Resolution strategy — use REST lookup, not construction

Rather than building the ticker string, resolve via REST:

```python
async def _resolve_15m_ticker(series: str, window_open_dt: datetime) -> dict | None:
    """Find the active 15m market for this series and window via REST.
    Returns market dict with yes_ask, yes_bid, close_time, open_time, or None.
    """
    loop = asyncio.get_running_loop()
    markets = await loop.run_in_executor(
        None, 
        lambda: _get_kalshi_client().get_markets_metadata(series, status='open')
    )
    window_open_iso = window_open_dt.replace(tzinfo=timezone.utc).isoformat()
    for m in markets:
        if (m.get('open_time') or '').replace('Z', '+00:00') == window_open_iso:
            return m
    return None
```

`get_markets_metadata()` is already implemented in `kalshi_client.py` — it paginates the `/markets` endpoint filtered by `series_ticker` and `status=open`. It returns raw dicts with `open_time`, `close_time`, `ticker`, and price fields.

---

## REST Price Fetch

Once the market dict is resolved, enrich with live orderbook prices:

```python
async def _fetch_15m_market_price(series: str, window_open_dt: datetime) -> dict | None:
    """Resolve ticker and fetch live bid/ask for a 15m series/window via REST."""
    market = await _resolve_15m_ticker(series, window_open_dt)
    if not market:
        logger.warning('[Fallback] No open market found for %s window %s', series, window_open_dt)
        return None
    
    ticker = market.get('ticker', '')
    if not ticker:
        return None
    
    # Enrich with live orderbook prices and compute book_depth_usd
    # enrich_orderbook() fetches the orderbook endpoint — the raw response contains
    # orderbook_fp.yes_dollars and orderbook_fp.no_dollars as [[price_str, vol_str], ...]
    # We compute book_depth_usd as sum of top-3 volumes on each side (same window, no extra call).
    loop = asyncio.get_running_loop()
    
    def _enrich_and_compute_depth(m):
        client = _get_kalshi_client()
        t = m.get('ticker', '')
        # Fetch raw orderbook response directly to get volumes
        host = client.client.configuration.host  # reuse configured host
        ob_url = f"{host}/markets/{t}/orderbook"
        from agents.ruppert.data_analyst.kalshi_client import _get_with_retry
        ob_resp = _get_with_retry(ob_url, timeout=5)
        depth = 0.0
        if ob_resp is not None and ob_resp.status_code == 200:
            ob = ob_resp.json().get('orderbook_fp', {})
            yes_side = ob.get('yes_dollars', [])   # [[price_str, vol_str], ...]
            no_side  = ob.get('no_dollars', [])
            # Top-3 volumes on each side (vol is already in dollars)
            yes_vols = sorted([float(v) for p, v in yes_side], reverse=True)[:3]
            no_vols  = sorted([float(v) for p, v in no_side],  reverse=True)[:3]
            depth = sum(yes_vols) + sum(no_vols)
            # Also derive bid/ask from the same response
            if no_side:
                best_no_bid = max(float(p) for p, v in no_side)
                m['no_bid']  = int(round(best_no_bid * 100))
                m['yes_ask'] = 100 - m['no_bid']
            if yes_side:
                best_yes_bid = max(float(p) for p, v in yes_side)
                m['yes_bid'] = int(round(best_yes_bid * 100))
                m['no_ask']  = 100 - m['yes_bid']
        m['_book_depth_usd'] = depth
        return m

    enriched = await loop.run_in_executor(None, lambda: _enrich_and_compute_depth(market))
    
    yes_ask = enriched.get('yes_ask')
    yes_bid = enriched.get('yes_bid')
    book_depth_usd = enriched.get('_book_depth_usd', 0.0)
    if yes_ask is None or yes_bid is None:
        logger.warning('[Fallback] No bid/ask from REST for %s', ticker)
        return None
    
    return {
        'ticker': ticker,
        'yes_ask': yes_ask,           # cents (int)
        'yes_bid': yes_bid,           # cents (int)
        'book_depth_usd': book_depth_usd,  # sum of top-3 volumes each side (dollars)
        'open_time': market.get('open_time'),
        'close_time': market.get('close_time'),
    }
```

Use a module-level lazy client getter to avoid re-instantiating on every poll:

```python
_kalshi_client_instance: 'KalshiClient | None' = None

def _get_kalshi_client():
    global _kalshi_client_instance
    if _kalshi_client_instance is None:
        from agents.ruppert.data_analyst.kalshi_client import KalshiClient
        _kalshi_client_instance = KalshiClient()
    return _kalshi_client_instance
```

---

## Evaluation Call

```python
async def _check_and_fire_fallback() -> None:
    """Check each 15m series; fire REST-based evaluation if WS missed the window."""
    from datetime import timezone, timedelta
    
    now_utc = datetime.now(tz=timezone.utc)
    
    # Compute current 15m window boundaries
    window_minutes = (now_utc.minute // 15) * 15
    window_open_dt = now_utc.replace(minute=window_minutes, second=0, microsecond=0)
    window_close_dt = window_open_dt + timedelta(minutes=15)
    window_open_iso = window_open_dt.isoformat()
    
    elapsed_secs = (now_utc - window_open_dt).total_seconds()
    remaining_secs = (window_close_dt - now_utc).total_seconds()
    
    # Only fire in the useful window: 90s after open, 120s before close
    if elapsed_secs < 90 or remaining_secs < 120:
        return
    
    for series in CRYPTO_15M_SERIES:
        guard_key = f"{series}::{window_open_iso}"
        
        # Skip if WS already evaluated this window
        if guard_key in _window_evaluated:
            continue
        
        try:
            market = await _fetch_15m_market_price(series, window_open_dt)
            if not market:
                continue
            
            ticker = market['ticker']
            yes_ask = market['yes_ask']
            yes_bid = market['yes_bid']
            close_time = market['close_time']
            open_time = market['open_time']
            
            # Update market cache with REST price
            market_cache.update(ticker, yes_bid / 100, yes_ask / 100, source='rest_fallback')
            
            logger.info('[Fallback] Firing REST eval for %s (WS missed window)', ticker)
            
            book_depth_usd = market.get('book_depth_usd', 0.0)
            
            from agents.ruppert.trader.crypto_15m import evaluate_crypto_15m_entry
            evaluate_crypto_15m_entry(
                ticker, yes_ask, yes_bid, close_time, open_time,
                book_depth_usd=book_depth_usd,  # computed from top-3 volumes each side
                dollar_oi=0.0,                  # REST OI not fetched here — strategy must tolerate 0
            )
            
            # Mark window as evaluated by fallback
            _window_evaluated[guard_key] = now_utc.isoformat()
            
        except Exception as e:
            logger.warning('[Fallback] eval error for %s: %s', series, e)
```

---

## File Changes (ws_feed.py only)

### New module-level additions (near top of file, after imports)

```python
from datetime import timezone, timedelta  # add to existing datetime import

# Per-window evaluation dedup guard
# Key: "{series}::{window_open_iso}"  Value: ISO timestamp when evaluated
_window_evaluated: dict[str, str] = {}

# Lazy KalshiClient instance for REST fallback (avoids re-init per poll cycle)
_kalshi_client_instance = None
```

### New functions to add

1. `_get_kalshi_client()` — lazy singleton getter
2. `_prune_window_guard()` — cleanup old entries
3. `_resolve_15m_ticker(series, window_open_dt)` — async REST market lookup
4. `_fetch_15m_market_price(series, window_open_dt)` — async REST price fetch
5. `_check_and_fire_fallback()` — async main fallback logic
6. `_fallback_poll_loop()` — async 60s polling loop

### Changes to `handle_message()`

After `evaluate_crypto_15m_entry(...)` call, add dedup mark:

```python
# Determine series prefix for this ticker
_series = next((s for s in CRYPTO_15M_SERIES if ticker_upper.startswith(s)), None)
# Normalize Z suffix to match fallback's +00:00 format
_open_time_norm = open_time.replace('Z', '+00:00') if open_time and open_time.endswith('Z') else open_time
if _series and _open_time_norm:
    _window_evaluated[f"{_series}::{_open_time_norm}"] = datetime.utcnow().isoformat()
```

### Changes to `run_ws_feed()` — inside the `while True` loop

```python
async with websockets.connect(...) as ws:
    # ... existing subscribe ...
    
    fallback_task = asyncio.create_task(_fallback_poll_loop())  # ADD
    
    try:                                                          # ADD (wrap existing for loop)
        async for raw in ws:
            await handle_message(raw)
            # ... existing periodic logic ...
    finally:                                                      # ADD
        fallback_task.cancel()                                    # ADD
        try:                                                      # ADD
            await fallback_task                                   # ADD
        except asyncio.CancelledError:                            # ADD
            pass                                                  # ADD
```

### Changes to purge block (every 5 minutes)

```python
if now - last_purge > 300:
    market_cache.purge_stale()
    await _rest_refresh_stale()
    _prune_window_guard()          # ADD
    # ... existing heartbeat print ...
```

---

## Failure Handling

| Failure | Behavior |
|---------|----------|
| REST lookup returns no market | Log warning, skip series, try again next 60s cycle |
| REST returns market but no bid/ask | Log warning, skip — do not fire eval with null prices |
| `evaluate_crypto_15m_entry` raises | Log warning, but **still mark `_window_evaluated`** to prevent retry storm |
| WS reconnects while fallback polling | `finally` block cancels task; new task created on next connect |
| KalshiClient raises 429 | `_get_with_retry` in kalshi_client handles with backoff; fallback will miss this cycle and retry next 60s |
| REST orderbook returns empty yes/no sides | `book_depth_usd` defaults to 0.0; evaluator R3 guard (LOW_KALSHI_LIQUIDITY) will SKIP — correct behavior for illiquid markets |

---

## QA Test Criteria

### TC-1: Task lifecycle
- Manually kill the WS connection (network drop or exception injection)
- Verify in logs: `fallback_task.cancel()` fires on disconnect
- Verify in logs: new fallback task created on reconnect
- No duplicate fallback tasks running simultaneously

### TC-2: WS fires first → fallback skips
- Let WS deliver a ticker event for KXBTC15M in a new window (T+2min)
- Confirm `_window_evaluated["KXBTC15M::..."]` is set
- At T+3min, fallback poll wakes
- Confirm fallback logs SKIP for KXBTC15M, no duplicate `evaluate_crypto_15m_entry` call
- Check decisions_15m.jsonl: only one entry per window per series

### TC-3: WS silent → fallback fires
- Pause WS ticker delivery for KXBTC15M (mock or filter in handle_message)
- At T+90s+, fallback poll wakes
- Confirm REST fetch fires for KXBTC15M
- Confirm `evaluate_crypto_15m_entry` called exactly once
- Confirm `_window_evaluated` marked

### TC-4: Fallback fires → WS fires late → no double eval
- Fallback fires at T+4min, marks `_window_evaluated`
- WS delivers a late ticker at T+6min
- Confirm handle_message sees guard_key already set and does NOT call evaluate again

### TC-5: Dedup guard pruning
- Populate `_window_evaluated` with entries from 2+ hours ago
- Trigger `_prune_window_guard()`
- Confirm old entries removed, recent entries retained

### TC-6: Ticker resolution via REST
- Query `get_markets_metadata("KXBTC15M")` for an active window
- Confirm returned market dict has `open_time` matching the current window boundary
- Confirm `enrich_orderbook` populates `yes_ask` and `yes_bid` as integers
- Cross-check ticker format: should match `KXBTC15M-{YY}{MON}{DD}{HHMM}-{STRIKE}` pattern

### TC-7: book_depth_usd computed from REST orderbook
- Confirm `_fetch_15m_market_price()` fetches orderbook and populates `book_depth_usd` in returned dict
- Verify: sum of top-3 volumes on yes_dollars side + top-3 on no_dollars side equals `book_depth_usd`
- For a market with known orderbook, cross-check value against manual orderbook response inspection
- Confirm that when book is empty (no yes/no sides), `book_depth_usd` falls back to 0.0 and R3 guard logs SKIP (not crash)
