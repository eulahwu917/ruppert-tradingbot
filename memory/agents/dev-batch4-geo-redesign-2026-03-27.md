# Dev Batch 4 — Geo Module Market-First Redesign (2026-03-27)

## What changed

### geopolitical_scanner.py — Full rewrite
**Old flow (news-first):** Pull broad GDELT news → try to match Kalshi markets → flag by news volume → human review only.

**New flow (market-first):**
1. `KalshiClient` + `search_geo_markets()` fetches up to 50 open geo/political markets with live orderbook prices
2. Filter to tradeable range: `yes_ask` between 5–92 cents
3. For each market:
   - `_extract_search_keywords(title)` — strips prediction-market framing, stop words, dates → targeted GDELT query
   - `get_gdelt_events(query, timespan='24h', max_records=10)` — from `geo_client.py` (existing, with retry/backoff)
   - Stage 1 Haiku (`stage1_classify`) — relevance + severity screen (severity >= 3 passes)
   - Stage 2 Sonnet (`stage2_estimate`) — probability estimate
   - Edge = `abs(estimated_prob - market_prob)` → must exceed `GEO_MIN_EDGE_THRESHOLD` (15%)
   - Confidence must exceed `MIN_CONFIDENCE['geo']` (50%)
4. Returns list of opportunity dicts: `ticker, yes_ask, edge, direction, confidence, reasoning, ...`
5. Logs to `logs/geopolitical_scanner.jsonl`

**Resilience:** GDELT circuit breaker (5 failures), 5-minute time budget, all try/except wrapped.

### kalshi_market_search.py — Added `search_geo_markets()`
- Takes a `KalshiClient` instance → uses `get_markets()` (real orderbook prices)
- Step 1: Fetch from known `GEOPOLITICAL_SERIES` (9 tickers)
- Step 2: Discover additional series via `find_series_by_keywords()` with expanded `GEO_TITLE_KEYWORDS` (18 keywords including war, election, president, congress, sanction, trade, nato, china, russia, iran, nuclear, etc.)
- Deduplicates by ticker, filters discovered markets by geo keyword in title
- Returns up to 50 markets

### Files NOT changed
- `geo_edge_detector.py` — Stage 1/Stage 2 LLM calls unchanged (used as-is)
- `geo_client.py` — GDELT fetching functions reused (`get_gdelt_events`, `_days_to_expiry`, `_GdeltRequestFailed`)
- `main.py` — `run_geo_scan_module()` calls `run_geo_scan()` + `format_geo_brief()` unchanged; wiring preserved
- `config.py` — `GEO_MIN_EDGE_THRESHOLD=0.15`, `GEO_AUTO_TRADE=True`, `MIN_CONFIDENCE['geo']=0.50` all used as-is

## Syntax check
Both `geopolitical_scanner.py` and `kalshi_market_search.py` pass `ast.parse()`.

## Integration notes
- `run_geo_scan()` now returns opportunity dicts with `module: 'geo'` field — ready for `should_enter()` wiring
- The `format_geo_brief()` function was updated to display edge/confidence/reasoning instead of raw news volume
- No changes to the main cycle wiring — geo results still flow through `run_geo_scan_module()` in `main.py`
