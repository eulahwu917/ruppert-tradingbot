# MEMORY.md — Data Analyst Long-Term Memory
_Owned by: Data Analyst agent. Updated after data source changes, feed issues, or infrastructure discoveries._

---

## Data Sources

### Kalshi
- API base: `api.elections.kalshi.com` (NOT `demo-api.kalshi.co` — that was wrong, fixed 2026-03-28)
- WS URL: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- Credentials: read from `secrets/kalshi_config.json`

### Weather
- ECMWF 40% + GEFS 40% + ICON 20% ensemble
- NOAA GHCND: bias cache at `logs/ghcnd_bias_cache.json`
- OpenMeteo: hours_since_midnight uses LOCAL time (not UTC) — fixed 2026-03-28

### Smart Money
- Wallets loaded from `logs/smart_money_wallets.json` (written by wallet_updater.py at 7am daily)
- Staleness threshold: >25h triggers warning
- Coinbase-Binance basis filter critical for crypto — Kalshi settles on Coinbase

### NWS Grids
- Miami: `MFL/106,51` (fixed 2026-03-26, was wrong)

## WS Feed Architecture
- Single persistent WS, subscribes to ALL tickers, filters by `WS_ACTIVE_SERIES` (30 prefixes)
- Routes to: market_cache + position exits + crypto entry eval
- Stale threshold: 60s; purge: 86400s (24h); persistence: `logs/price_cache.json`
- REST used for: orders + startup + reconnect recovery only

## Known Issues / Fixed
- market_cache REST fallback: wrong field names fixed (yes_bid not yes_bid_dollars) — 2026-03-28
- openmeteo_client: UTC vs local time bug fixed — 2026-03-28
- Unicode crash on Windows in market_scanner — fixed 2026-03-28
- fetch_smart_money: hardcoded output path → fixed to env_config

## Lessons Learned
- Always validate WS URL against prod API docs — demo URL was silently wrong for weeks
- REST fallback field names must match actual API response schema, not assumed names
