# position_monitor.py — pykalshi Adoption Plan
**Version:** 2.0 (Post-CEO Review)  
**Date:** 2026-03-27  
**Author:** Ruppert Architect  
**Status:** Ready for Dev

---

## Executive Summary

Replace `post_trade_monitor.py` entirely with a new `position_monitor.py` that integrates
pykalshi WebSocket subscriptions for real-time settlement and fill events, while preserving
all existing logic verbatim. One process. No parallel runners. Seamless fallback to polling
if WebSocket is unavailable (e.g., DEMO environment).

---

## 1. New File: `position_monitor.py`

### 1.1 Location

```
ruppert-tradingbot-demo/position_monitor.py   ← new canonical file
```

### 1.2 High-Level Structure

```
position_monitor.py
├── Constants & config
├── _update_pnl_cache()            ← VERBATIM from post_trade_monitor.py
├── push_alert()                   ← VERBATIM from post_trade_monitor.py
├── load_open_positions()          ← VERBATIM from post_trade_monitor.py
├── get_market_data()              ← VERBATIM from post_trade_monitor.py
├── check_weather_position()       ← VERBATIM from post_trade_monitor.py
├── check_crypto_position()        ← VERBATIM from post_trade_monitor.py
├── check_alert_only_position()    ← VERBATIM from post_trade_monitor.py
├── check_settlements()            ← VERBATIM from post_trade_monitor.py (polling fallback)
├── --- NEW SECTION ---
├── _ws_try_connect()              ← NEW: attempts pykalshi Feed connection
├── _handle_lifecycle_msg()        ← NEW: handles MarketLifecycleMessage
├── _handle_fill_msg()             ← NEW: handles FillMessage
├── _handle_position_msg()         ← NEW: handles PositionMessage
├── run_ws_event_loop()            ← NEW: event-driven mode (when WS available)
├── run_polling_mode()             ← NEW: wrapper around existing run_monitor() logic
└── main()                         ← NEW: detects WS availability, routes to right mode
```

### 1.3 New Constants in `position_monitor.py`

```python
# WebSocket behavior
WS_CONNECT_TIMEOUT_SEC  = 10      # How long to wait for Feed connection before fallback
WS_EVENT_LOOP_DURATION  = 840     # 14 minutes — run event loop, then exit (Task Scheduler restarts)
WS_ENABLED              = True    # Master kill-switch: set False to force polling always
WS_RECONNECT_BACKOFF    = True    # Let pykalshi Feed handle auto-reconnect

# Polling mode (fallback)
POLLING_SETTLEMENT_CHECK = True   # Run check_settlements() in polling mode
```

These constants go at the top of `position_monitor.py` alongside existing constants
(`LOGS`, `ALERTS_FILE`, `DRY_RUN`).

### 1.4 pykalshi Integration Detail

#### Subscriptions

```python
from pykalshi import Feed, MarketLifecycleMessage, FillMessage, PositionMessage

def _ws_try_connect(open_tickers: list[str]) -> Feed | None:
    """
    Attempt to connect pykalshi Feed. Returns Feed on success, None on failure.
    Handles missing DEMO endpoint gracefully — any exception → returns None.
    """
    if not WS_ENABLED:
        return None
    try:
        feed = Feed(
            api_key=config.get_api_key_id(),
            private_key_path=config.get_private_key_path(),
            environment=config.get_environment(),  # 'demo' or 'live'
        )
        feed.connect(timeout=WS_CONNECT_TIMEOUT_SEC)
        # Subscribe to lifecycle events for all open tickers
        for ticker in open_tickers:
            feed.subscribe_market_lifecycle(ticker)
        feed.subscribe_fills()
        feed.subscribe_positions()
        return feed
    except Exception as e:
        print(f"  [WS] Connection failed ({e}) — falling back to polling")
        return None
```

#### Event Handlers

```python
def _handle_lifecycle_msg(msg: MarketLifecycleMessage, client, logs_dir: Path):
    """
    Real-time settlement: when a market resolves via WS, run settlement logic
    for that specific ticker instead of waiting for polling cycle.
    Uses existing check_settlements() logic filtered to one ticker.
    """
    ticker = msg.market_ticker
    result = msg.result  # 'yes' | 'no' | None
    print(f"  [WS] MarketLifecycle: {ticker} → {result}")
    if result in ('yes', 'no'):
        # Call targeted settlement logic (see §1.5)
        _settle_single_ticker(ticker, result, client, logs_dir)


def _handle_fill_msg(msg: FillMessage):
    """
    Real-time fill confirmation. Log to activity log only — no state change.
    We do NOT update positions from fills here; load_open_positions() is still
    the source of truth (reads from trade logs).
    """
    print(f"  [WS] Fill confirmed: {msg.ticker} {msg.side} @ {msg.price}c × {msg.count}")
    log_activity(f"[WS FILL] {msg.ticker} {msg.side} @ {msg.price}c × {msg.count}")


def _handle_position_msg(msg: PositionMessage):
    """
    Live position update. Log for diagnostic purposes only.
    Does not alter auto-exit logic — that still reads from trade logs.
    Future: could be used for reconciliation.
    """
    print(f"  [WS] Position update: {msg.ticker} {msg.side} {msg.position}")
```

#### `_settle_single_ticker()` — New Helper

This is extracted from `check_settlements()`. Instead of iterating all open positions,
it processes one specific ticker with a known result. This avoids re-fetching the market
when the WS already gave us the result.

```python
def _settle_single_ticker(ticker: str, result: str, client, logs_dir: Path):
    """
    Run settlement logic for a single ticker with a known result (from WS event).
    Mirrors check_settlements() logic for one position — no API re-fetch for result.
    """
    # Load the open position record for this ticker
    positions = load_open_positions()
    matched = [p for p in positions if p.get('ticker') == ticker]
    if not matched:
        print(f"  [WS Settle] {ticker}: no open position found — skipping")
        return
    pos = matched[0]
    side = pos.get('side', '')
    # ... (rest of settlement P&L calculation, log write, pnl_cache update)
    # Identical to check_settlements() inner loop but for one position, result known
```

### 1.5 Event Loop Mode vs Polling Mode

#### `run_ws_event_loop(feed, client)`

```python
def run_ws_event_loop(feed: Feed, client):
    """
    Event-driven mode. Runs for WS_EVENT_LOOP_DURATION seconds then exits cleanly.
    Task Scheduler restarts every 15 minutes, so duration < 15 min avoids overlap.
    
    Flow:
      1. Initial polling scan (identical to run_polling_mode) — immediate
      2. Enter event loop — handle incoming WS messages for duration
      3. Periodically re-run auto-exit scan (every 5 min) inside loop
      4. Exit cleanly — Task Scheduler restarts
    """
    import time
    start = time.monotonic()
    last_scan = 0

    # Run initial full scan immediately (settlement + auto-exit + weather alerts)
    run_polling_mode(client, run_settlement_check=False)  # WS handles settlements

    while (time.monotonic() - start) < WS_EVENT_LOOP_DURATION:
        msg = feed.next_message(timeout=30)
        if msg is None:
            pass  # timeout, loop again
        elif isinstance(msg, MarketLifecycleMessage):
            _handle_lifecycle_msg(msg, client, LOGS_DIR)
        elif isinstance(msg, FillMessage):
            _handle_fill_msg(msg)
        elif isinstance(msg, PositionMessage):
            _handle_position_msg(msg)

        # Periodic auto-exit re-scan (every 5 min) regardless of WS events
        if (time.monotonic() - last_scan) > 300:
            run_polling_mode(client, run_settlement_check=False)
            last_scan = time.monotonic()

    feed.close()
    print(f"  [WS] Event loop exited after {WS_EVENT_LOOP_DURATION}s — Task Scheduler will restart")
```

#### `run_polling_mode(client, run_settlement_check=True)`

Thin wrapper around the existing `run_monitor()` logic. Accepts `run_settlement_check`
flag so that when WS is active, we skip the polling-based `check_settlements()` (WS
handles it via `_handle_lifecycle_msg`).

#### `main()`

```python
def main():
    print_header()
    client = KalshiClient()
    open_positions = load_open_positions()
    open_tickers = [p['ticker'] for p in open_positions if p.get('ticker')]

    # Attempt WS connection
    feed = _ws_try_connect(open_tickers)

    if feed is not None:
        print(f"  [WS] Connected — running event-driven mode")
        run_ws_event_loop(feed, client)
    else:
        print(f"  [WS] Unavailable — running polling mode")
        run_polling_mode(client, run_settlement_check=True)

if __name__ == '__main__':
    main()
```

---

## 2. Process Execution Model

### Decision: Task Scheduler (15-min restarts) with event loop inside

**Keep Task Scheduler as the restart mechanism.** Position monitor runs every 15 min,
6am–11pm, same as current `post_trade_monitor.py`.

**When WS connects:** process runs a 14-minute event loop (`WS_EVENT_LOOP_DURATION = 840`),
handles events in real time, then exits. Task Scheduler relaunches 1 minute later.

**When WS fails:** process runs one polling scan (identical to current behavior), exits
in ~30 seconds. Task Scheduler relaunches on next tick.

This avoids needing a separate long-lived service manager (no `nssm`, no `systemd` equivalent
on Windows). The 14-minute window is short enough to avoid Task Scheduler overlap (15-min tick).

### Task Scheduler Changes

| Setting | Old | New |
|---|---|---|
| Script | `post_trade_monitor.py` | `position_monitor.py` |
| Trigger | Every 15 min, 6am–11pm | Same |
| Run As | Same user | Same |
| Working Dir | Same | Same |

**One change only:** update the script path in the Task Scheduler XML or GUI.

---

## 3. Fallback Behavior When WebSocket Unavailable

### Trigger conditions (all caught by `_ws_try_connect`)
- `Feed` raises `ConnectionError` (DEMO endpoint doesn't exist)
- `Feed` raises `TimeoutError` (endpoint exists but hangs)
- `Feed` raises any other exception (auth failure, wrong URL, etc.)
- `WS_ENABLED = False` (manual override)

### Fallback behavior
- `_ws_try_connect()` catches all exceptions, prints reason, returns `None`
- `main()` sees `feed is None`, calls `run_polling_mode()` with `run_settlement_check=True`
- Polling mode is **identical to current `post_trade_monitor.py`** — no behavior change
- No manual intervention required
- No config file to edit
- No environment variable to set

### Testing the fallback
Dev can set `WS_ENABLED = False` at the top of `position_monitor.py` to force polling
mode during initial testing, verifying all existing logic works before touching WS code.

---

## 4. Migration Path

### Step 1: Archive `post_trade_monitor.py`
```
post_trade_monitor.py  →  archive/post_trade_monitor_pre_ws.py
```
**Do not delete.** Move to `archive/` with the date in the name. Git commit separately
so it's in history regardless.

### Step 2: Create `position_monitor.py` in demo project
Dev writes `position_monitor.py` starting from `post_trade_monitor.py` verbatim,
then adds the WS layer on top. The existing functions are not modified — only new
functions are added.

### Step 3: Update Task Scheduler
Change Task Scheduler trigger from `post_trade_monitor.py` → `position_monitor.py`.
Do NOT remove the old task immediately — rename it to `Ruppert_PostMonitor_ARCHIVED`
and disable it. Delete after 2 weeks of confirmed clean runs.

### Step 4: Smoke test in polling mode
Set `WS_ENABLED = False`, run one manual cycle, verify output matches old behavior exactly.
Re-enable `WS_ENABLED = True`.

### Step 5: Smoke test in WS mode (LIVE only — if DEMO endpoint exists)
If DEMO WS endpoint is confirmed available: run manually with `WS_ENABLED = True`,
verify WS connects, verify settlement events are handled, verify polling fallback still works
when WS is force-disconnected mid-run.

### Step 6: Deploy to live project
Same file, same process. `ruppert-tradingbot-live/` already has a `position_monitor.py`
stub — Dev should review what's in it before overwriting.

---

## 5. Changes in Other Files

### `config.py` — No changes required
`get_environment()` already returns `'demo'` or `'live'` based on `mode.json`. pykalshi
`Feed` will use this to select the correct WS endpoint. No new constants needed in config.py
(WS constants live in `position_monitor.py` itself for now).

### `logger.py` — No changes required
`log_activity()`, `log_trade()`, `acquire_exit_lock()`, `release_exit_lock()`,
`normalize_entry_price()` — all called identically. No signature changes.

### `pnl_cache.json` — No changes
`_update_pnl_cache()` is copied verbatim. File format and write behavior unchanged.

### `ruppert_cycle.py` — No changes required
`ruppert_cycle.py` does not import or call `post_trade_monitor.py`. The two scripts run
independently. No coupling to update.

### `pending_alerts.json` — No changes
`push_alert()` is copied verbatim. Alert format unchanged.

### Task Scheduler — One change
Update the `post_trade_monitor` task to point to `position_monitor.py`. See §2.

### `requirements.txt` / `pyproject.toml` — Add `pykalshi`
```
pykalshi>=0.1.0   # or whatever current release is on PyPI
```
Dev should pin the exact version used during initial testing.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DEMO WS endpoint doesn't exist | High | Low | `_ws_try_connect()` catches all exceptions, falls back to polling silently |
| pykalshi API changes between versions | Medium | Medium | Pin exact version in requirements.txt; don't auto-upgrade |
| WS event loop holds process > 15 min | Low | Low | `WS_EVENT_LOOP_DURATION = 840s` (14 min) ensures exit before next Task Scheduler tick |
| Duplicate settlement (WS + polling both run) | Low | Medium | When WS active, `run_polling_mode()` is called with `run_settlement_check=False` |
| Double-exit if WS fill + auto-exit scan both trigger | Low | High | `acquire_exit_lock()` already prevents duplicate exits — unchanged behavior |
| WS connect succeeds but drops mid-loop | Low | Low | pykalshi `Feed` auto-reconnects with exponential backoff; polling scan runs every 5 min inside loop as backstop |
| pykalshi not installed in Task Scheduler Python env | Medium | High | Add to requirements.txt; Dev must verify `pip install pykalshi` in the correct venv before Task Scheduler cutover |
| `_settle_single_ticker()` diverges from `check_settlements()` | Medium | Medium | Keep `_settle_single_ticker()` as a thin call into a shared helper, not a separate reimplementation |
| live project `position_monitor.py` stub conflicts | Medium | High | Dev reviews live stub before overwriting (see §4 Step 6) |

---

## 7. Estimated Effort

| Task | Effort |
|---|---|
| Copy `post_trade_monitor.py` → `position_monitor.py` skeleton | 15 min |
| Write `_ws_try_connect()` | 30 min |
| Write `_handle_lifecycle_msg()`, `_handle_fill_msg()`, `_handle_position_msg()` | 45 min |
| Extract `_settle_single_ticker()` from `check_settlements()` | 30 min |
| Write `run_ws_event_loop()` | 45 min |
| Refactor `run_monitor()` → `run_polling_mode()` (thin wrapper, no logic change) | 20 min |
| Write `main()` dispatch | 15 min |
| Add `pykalshi` to requirements.txt | 5 min |
| Archive old file, update Task Scheduler | 15 min |
| Smoke test (polling mode) | 20 min |
| Smoke test (WS mode, if DEMO endpoint available) | 30 min |
| **Total** | **~4 hours** |

Dev can ship the polling-mode-only version in ~2 hours (skip WS smoke test until LIVE
endpoint is confirmed available in DEMO env).

---

## 8. Open Questions for CEO Decision

### Q1: WS_EVENT_LOOP_DURATION — 14 min or shorter?
**Current proposal:** 840 seconds (14 min), exiting before 15-min Task Scheduler tick.  
**Alternative:** 300 seconds (5 min) — more frequent restarts, fresher subscription list.  
**Tradeoff:** Shorter = more restarts + more reconnect overhead. Longer = WS stays connected longer, fewer reconnects.  
**CEO decides:** Keep 14 min or shorten to 5 min?

### Q2: Should `PositionMessage` data update `load_open_positions()` source of truth?
**Current plan:** `PositionMessage` is logged only; `load_open_positions()` still reads JSONL trade logs.  
**Alternative:** WS position data could replace/supplement API calls in auto-exit logic, reducing latency.  
**Tradeoff:** More complex; breaks current single-source-of-truth model.  
**CEO decides:** Log-only (safe) or use WS position data in auto-exit logic?

### Q3: Should pykalshi WS replace `get_market_data()` API calls during event loop?
**Current plan:** Even in WS mode, auto-exit logic still calls `get_market_data(ticker)` for current price.  
**Alternative:** Use `PositionMessage` or a `MarketOrderbookMessage` subscription to get live prices without REST calls.  
**Tradeoff:** Requires additional subscription type; reduces API rate usage.  
**CEO decides:** Keep REST price fetching or explore WS-based price feeds?

### Q4: Weather alert timing in WS mode
**Current plan:** Weather alert check runs as part of `run_polling_mode()` every 5 min inside the event loop.  
**No WS equivalent** for weather alerts — they rely on `openmeteo_client` data, not Kalshi WS events.  
**No decision needed here** — this is fine as-is. Just confirming CEO awareness.

### Q5: What's in `ruppert-tradingbot-live/position_monitor.py`?
There is already a `position_monitor.py` in the live project. Dev must audit it before this plan is implemented.  
**CEO action needed:** Ask Dev to report what's in the live `position_monitor.py` before starting.

---

## Appendix: File Reference

| File | Action |
|---|---|
| `post_trade_monitor.py` | → Archive as `archive/post_trade_monitor_pre_ws.py` |
| `position_monitor.py` | → Create (new canonical file) |
| `config.py` | No change |
| `logger.py` | No change |
| `ruppert_cycle.py` | No change |
| `requirements.txt` | Add `pykalshi>=X.Y.Z` |
| Task Scheduler task | Update script path only |
| `ruppert-tradingbot-live/position_monitor.py` | Audit before overwriting |
