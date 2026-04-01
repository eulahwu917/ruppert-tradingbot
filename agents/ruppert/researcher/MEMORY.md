# MEMORY.md — Researcher Long-Term Memory
_Owned by: Researcher agent. Updated after scans, discoveries, or pattern findings._

---

## Market Scan History
- Last light scan: 2026-03-29 (weekly Sunday scan)

## Known Market Constraints
- California-based operation: avoid sports and election prediction markets
- Geo markets: high edge variance, manual approval required

## Discovered Opportunities
- See `logs/truth/opportunities_backlog.json` for active queue

## Lessons Learned
- (populate after first real scan cycle)

---

## 2026-03-31 Session Update

### New Data Sources Available

**Polymarket Client** (`agents/ruppert/data_analyst/polymarket_client.py`):
- Functions: `get_crypto_consensus()`, `get_geo_signals()`, `get_wallet_positions()`, `get_smart_money_signal()`, `get_markets_by_keyword()`
- Shadow mode only — 7-day collection in progress before any wiring into signals

**Sports Odds** (collector now live):
- 11 NBA + 33 MLB games collected daily
- Vegas vs Kalshi gap visible on dashboard (`/api/sports`)
- Potential future module: arbitrage signals on large gap games

**TheNewsAPI**: Key at `secrets/thenewsapi_config.json` — use `found` field for volume/spike detection

### Analysis Toolkit
- `python scripts/data_toolkit.py` — use this for all data queries. Supports winrate, P&L, module breakdowns. <3s response.
- `bird` CLI for X/Twitter searches (not `xurl` — removed)

### Capital at EOD: ~$13,146
