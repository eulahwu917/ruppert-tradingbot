# Ruppert Trading Bot: Architecture Review & Adoption Plan
**Architect Review (Opus) | 2026-03-27**

## Plan A: `position_monitor.py` — Native WebSocket Implementation

### File Structure

```
position_monitor.py          # Main entry point (replaces post_trade_monitor.py)
ws/
├── __init__.py
├── connection.py            # KalshiWebSocket class — connection lifecycle
├── auth.py                  # RSA-PSS signing for WS handshake
├── channels.py              # Channel handlers (lifecycle, ticker, fill)
└── fallback.py              # Poll-based fallback (current logic extracted)
```

### WS Endpoints
- PROD: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- DEMO: `wss://demo-api.kalshi.co/trade-api/ws/v2` (may not exist — handle gracefully)

### Auth
Same RSA-PSS signing as REST. Headers:
- `KALSHI-ACCESS-KEY`: api_key_id
- `KALSHI-ACCESS-TIMESTAMP`: timestamp_ms
- `KALSHI-ACCESS-SIGNATURE`: base64(RSA-PSS(timestamp_ms + "GET" + "/trade-api/ws/v2"))

**Dev must verify:** Exact signature algorithm matches `kalshi_auth.create_auth_headers()`.

### Channels
- `market_lifecycle_v2` — settlement/finalization events (result: "yes"/"no")
- `ticker` — price updates (yes_bid, yes_ask, volume) for real-time crypto entry
- `fill` — order fills (private)
- `orderbook_delta` — orderbook changes

### Reconnect
- Exponential backoff: 0.5s → 30s, max 5 retries
- Silent fallback to polling if DEMO endpoint unavailable or max retries hit
- 14-minute event loop per Task Scheduler cycle

### Key Classes
- `KalshiWebSocket` (ws/connection.py) — connect, subscribe, listen, reconnect
- `ChannelDispatcher` (ws/channels.py) — routes messages to handlers
- `handle_market_lifecycle` — settlement → on_settlement callback
- `handle_ticker` — price tick → on_price_update for crypto entry
- `handle_fill` — fill confirmation → log only

### Short-Duration Crypto Markets (15-min/1-hour)
Subscribe to `ticker` channel for active crypto markets. On each price tick:
- Run `band_prob()` edge calculation
- If edge > MIN_EDGE_THRESHOLD AND position not already held → enter
- This is the key unlock for 15-min markets

### Migration
1. Archive `post_trade_monitor.py` → `archive/post_trade_monitor_pre_ws.py`
2. Create `ws/` subdirectory with 4 files
3. Create `position_monitor.py` (verbatim existing logic + WS layer)
4. Update Task Scheduler path
5. `pip install websockets` (minimal dependency)

---

## Plans B, C, D — INCOMPLETE (output truncated)
Opus was mid-output when truncated. Need to re-run for Plans B (volume-tier), C (crypto cadence), D (infrastructure gaps).
