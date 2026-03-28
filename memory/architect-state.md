# Architect State — Ruppert Trading Bot
*Last updated: 2026-03-28 09:32 PDT*
*Read this first every time you're spun up as Architect.*

---

## Current Architecture State

### LIVE (running in DEMO)
- **WS-first data layer** — ws_feed.py (persistent WebSocket) + market_cache.py (thread-safe cache) + position_tracker.py (instant exits)
- **All core modules**: edge_detector.py (weather), crypto_scanner.py (hourly bands), crypto_15m.py (15M direction), economics_scanner.py, geo_edge_detector.py, fed_client.py
- **Execution stack**: trader.py → Kalshi API, capital.py, logger.py
- **Orchestration**: ruppert_cycle.py (Task Scheduler), post_trade_monitor.py (runs separately from WS now)
- **Dashboard**: dashboard/api.py on port 8765

### BUILDING (active development)
- **crypto_long_horizon.py** — Monthly/annual crypto markets. Model: Fear&Greed regime + log-normal touch probability. Status: code exists, needs QA validation pass.
- **data_agent.py** — Post-scan auditor. Spec written, not yet built. Reports to Optimizer.
- **Decision logging** — decisions_15m.jsonl and decisions_long_horizon.jsonl for outcome tracking.

### PLANNED (not started)
- **Twitter signal pipeline** — Agent Reach / bird CLI. For Fed (confidence mod), Econ (monitor), Geo (breaking), Crypto LH (regime).
- **Autoresearcher v2** — Optimizer-driven, uses decision logs for signal weight tuning.
- **Cycle refactor** — ruppert_cycle.py from top-level script to testable function-based module (spec exists: agents/architect-cycle-refactor-plan-2026-03-27.md).

---

## Open Architectural Questions

1. **Data Agent scope**: Should it run as subprocess or integrated in cycle? Subprocess = isolation, integrated = simpler deployment. Leaning: subprocess for now (can change later).

2. **WS feed recovery**: Current reconnect logic is basic. Need exponential backoff + dead-letter queue for missed tickers? Low priority — current approach works.

3. **Decision log schema**: Finalize schema before autoresearcher v2. Current schema in crypto_15m.py is good template. Need: consistent outcome field filled after settlement.

4. **Long-horizon exit strategy**: Currently skips 70% gain threshold. Should it use time-based or regime-shift exits? TBD — needs data first.

---

## Decisions Already Made (don't re-litigate)

| Decision | Rationale | Date |
|----------|-----------|------|
| WS-first, REST fallback | Eliminates 30-min polling lag. REST for orders + startup. | 2026-03-28 |
| Thread-safe market_cache | Multiple modules read prices; locks prevent race conditions. | 2026-03-28 |
| position_tracker instant exits | WS tick → immediate exit if threshold hit. No more 30-min delay. | 2026-03-28 |
| Config-driven WS_ACTIVE_SERIES | Add new series without code change. | 2026-03-28 |
| 60s stale / 300s purge thresholds | Balances freshness vs REST overhead. | 2026-03-28 |
| Kelly 6 tiers (0.05–0.16) | Approved by Optimizer. Calibrated for current capital. | 2026-03-26 |
| Module daily caps (4-7%) | Limits concentration risk per module. | 2026-03-26 |
| Long-horizon 0.5% per-trade cap | Higher-risk module, smaller sizing. | 2026-03-28 |
| Decision logs (jsonl per module) | Enables autoresearcher outcome tracking. | 2026-03-28 |
| Data Agent reports to Optimizer | Data quality → algorithm insights. CEO only gets escalations. | 2026-03-28 |

---

## Known Technical Constraints

- **Windows asyncio**: Must set `WindowsSelectorEventLoopPolicy()` for WS to work.
- **Kalshi WS auth**: Uses PSS padding on PKCS#8 key. Path from config.get_private_key_path().
- **Market hours**: 6am–11pm local. WS feed auto-exits outside hours.
- **Thread safety**: All market_cache access goes through `_lock`. Don't bypass.
- **Log files are source of truth**: trades_*.jsonl, deposits.json. Never auto-fix these — escalate.

### Known Failure Modes

| Mode | Symptom | Recovery |
|------|---------|----------|
| WS disconnect | Cache ages, staleness flags | Auto-reconnect in ws_feed.py. REST fallback kicks in. |
| Cache corruption | Prices frozen or missing | Delete price_cache.json, restart. WS repopulates. |
| Position tracker drift | Tracked != Kalshi API | Data Agent escalates. Manual reconciliation. |
| Order execution fail | 429 or 500 from Kalshi | trader.py retries. If persistent, alert. |

---

## Build Queue & Priorities

| Priority | Task | Owner | Status |
|----------|------|-------|--------|
| **P0** | Long-horizon QA pass | QA | In progress |
| **P1** | Data Agent build | Dev | Spec written, not started |
| **P2** | Decision log outcome backfill | Researcher | After 1 week of 15M data |
| **P3** | Cycle refactor | Dev | Spec exists, low priority |
| **P4** | Twitter pipeline | Dev | Blocked on Agent Reach access |

---

## Key Config Values

| Config | Value | Rationale |
|--------|-------|-----------|
| `DRY_RUN` | `True` (mode.json) | DEMO mode. David flips to LIVE. |
| `WS_CACHE_STALE_SECONDS` | 60 | REST fallback trigger |
| `WS_CACHE_PURGE_SECONDS` | 300 | Clears dead entries |
| `CRYPTO_15M_MIN_EDGE` | 0.08 | 8c minimum for 15M |
| `LONG_HORIZON_MIN_EDGE` | 0.08 | 8c minimum for LH |
| `LONG_HORIZON_MAX_POSITION_PCT` | 0.005 | 0.5% per trade |
| `EXIT_95C_THRESHOLD` | 95 | Auto-exit at 95c |
| `EXIT_GAIN_PCT` | 0.70 | Auto-exit at 70% of max profit |
| `MARKET_HOUR_START` | 6 | WS active start |
| `MARKET_HOUR_END` | 23 | WS active end |

---

## Files to Check

When spun up, spot-check these for drift:
- `config.py` — risk caps, thresholds
- `ws_feed.py` — WS logic
- `market_cache.py` — cache logic
- `position_tracker.py` — exit rules
- `crypto_15m.py` — signal weights
- `crypto_long_horizon.py` — touch probability model
- `memory/MEMORY.md` — project-level memory

---

## Notes for Future Me

- If David asks about adding a new market series: update `config.WS_ACTIVE_SERIES` list. No code change needed.
- If WS flakes: check Windows asyncio policy first.
- If autoresearcher needs signal weight tuning: decision logs are in `logs/decisions_*.jsonl`.
- Data Agent spec is in the task brief from 2026-03-28. Build it per spec.
- Never let CEO or anyone bypass the Dev→QA pipeline. Time pressure is not an exception.
