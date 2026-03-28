# QA API Health Check — 2026-03-13
**Agent:** SA-4 QA  
**Run time:** 2026-03-13 ~14:40 PDT  
**Scope:** Live HTTP runtime check — all 8 data sources  

---

## Summary Table

| API | Status | Notes |
|-----|--------|-------|
| 1. Kalshi Market Data (public) | ✅ PASS | 5 markets returned, orderbook live with 33 rows |
| 2. Kalshi Auth (Balance) | ✅ PASS | $172.37 demo balance |
| 3. NOAA/NWS (19 cities) | ⚠️ PARTIAL | 18/19 PASS — Miami grid point is a marine zone (404) |
| 4. Kraken (5 crypto pairs) | ✅ PASS | All 5 live; XDGEUSD→DOGEUSD fallback working |
| 5. Polymarket FOMC | ✅ PASS | Event live, 4 markets, prices loaded |
| 6. FRED DFEDTARU | ✅ PASS | Rate = 3.75% as of 2026-03-13 |
| 7. Open-Meteo (openmeteo_client) | ✅ PASS | Miami & Austin both returning valid signals |
| 8. Kalshi search_markets() + orderbook | ✅ PASS | 192/192 markets priced (100% coverage) |

---

## API 1: Kalshi Market Data (Public)

**Status: ✅ PASS**

- Endpoint: `GET /trade-api/v2/markets?series_ticker=KXHIGHMIA&status=open&limit=5`
- HTTP 200, returned 5 open markets
- Sample ticker: `KXHIGHMIA-26MAR14-T86`
- Orderbook for sample ticker: HTTP 200, `no_dollars` rows=33, `yes_dollars` rows=2
- Orderbook enrichment working correctly

---

## API 2: Kalshi Authenticated (Balance)

**Status: ✅ PASS**

- Environment: DEMO mode
- Balance: **$172.37**
- SDK auth via RSA private key: working

---

## API 3: NOAA/NWS — All 19 Cities

**Status: ⚠️ PARTIAL (18/19 PASS)**

| City | Series | NWS Office | Status | Sample Temp |
|------|--------|-----------|--------|------------|
| New York | KXHIGHNY | OKX 33,37 | ✅ PASS | 48°F |
| Chicago | KXHIGHCHI | LOT 75,73 | ✅ PASS | 43°F |
| **Miami** | **KXHIGHMIA** | **MFL 110,37** | **❌ FAIL** | **404 Marine Zone** |
| Phoenix | KXHIGHPHX | PSR 157,57 | ✅ PASS | 93°F |
| Houston | KXHIGHHOU | HGX 66,99 | ✅ PASS | 77°F |
| Austin | KXHIGHAUS | EWX 156,91 | ✅ PASS | 80°F |
| Denver | KXHIGHDEN | BOU 63,62 | ✅ PASS | 72°F |
| Los Angeles (LAX) | KXHIGHLAX | LOX 148,41 | ✅ PASS | 82°F |
| Philadelphia | KXHIGHPHIL | PHI 50,76 | ✅ PASS | 50°F |
| Minneapolis | KXHIGHTMIN | MPX 108,72 | ✅ PASS | 36°F |
| Dallas | KXHIGHTDAL | FWD 89,104 | ✅ PASS | 78°F |
| Washington DC | KXHIGHTDC | LWX 96,72 | ✅ PASS | 55°F |
| Las Vegas | KXHIGHTLV | VEF 123,98 | ✅ PASS | 87°F |
| New Orleans | KXHIGHTNOU | LIX 68,88 | ✅ PASS | 73°F |
| Oklahoma City | KXHIGHTOKC | OUN 97,94 | ✅ PASS | 74°F |
| San Francisco | KXHIGHTSFO | MTR 85,98 | ✅ PASS | 66°F |
| Seattle | KXHIGHTSEA | SEW 124,61 | ✅ PASS | 41°F |
| San Antonio | KXHIGHTSATX | EWX 126,54 | ✅ PASS | 81°F |
| Atlanta | KXHIGHTATL | FFC 51,87 | ✅ PASS | 66°F |

**Miami FAIL detail:**
```
404 {"title": "Marine Forecast Not Supported", 
     "type": "https://api.weather.gov/problems/MarineForecastNotSupported",
     "detail": "Forecasts for marine areas are not yet supported by this API."}
```
Grid point MFL/110,37 falls in a marine zone offshore.  
**Impact:** Code gracefully falls back to Open-Meteo + bias. Miami signals still work end-to-end.  
**Recommendation:** Find the correct inland NWS grid point for Miami (e.g., Miami downtown ~MFL/104,38).

---

## API 4: Kraken — 5 Crypto Pairs

**Status: ✅ PASS**

| Pair | Symbol | Price |
|------|--------|-------|
| Bitcoin | XBTUSD | $71,203.50 |
| Ethereum | ETHUSD | $2,106.78 |
| Ripple | XRPUSD | $1.40 |
| Solana | SOLUSD | $88.59 |
| Dogecoin | XDGEUSD→DOGEUSD | $0.0963 |

**Note:** `XDGEUSD` returns Kraken error as expected; `DOGEUSD` fallback is in place and working.

---

## API 5: Polymarket — FOMC Slug

**Status: ✅ PASS**

- URL: `https://gamma-api.polymarket.com/events?slug=fed-decision-in-march-885`
- HTTP 200
- Event title: "Fed decision in March?"
- Markets: 4
- Sample market: "Will the Fed decrease interest rates by 50+ bps after the March 2026 meeting?"
- Sample prices: `["0.0015", "0.9985"]` — market pricing 0.15% chance of 50bps cut (very dovish odds)

---

## API 6: FRED — DFEDTARU

**Status: ✅ PASS**

- URL: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU`
- HTTP 200, CSV format
- Header: `observation_date,DFEDTARU`
- Latest value: **3.75%** (as of 2026-03-13)
- Total rows: 6,297 (historical data intact)

---

## API 7: Open-Meteo (openmeteo_client)

**Status: ✅ PASS**

> ⚠️ **Test spec note:** The task spec called `get_full_weather_signal('KXHIGHMIA', 84.5, '2026-03-14')` with a string date. The function signature expects `datetime.date`. The string caused a runtime error (`unsupported operand type(s) for -: 'str' and 'datetime.date'`). This is a **test spec bug**, not an API bug. Tests were re-run with correct `date(2026,3,14)` object.

### Miami (KXHIGHMIA) — existing city
- `get_full_weather_signal('KXHIGHMIA', 84.5, date(2026,3,14))`
- `final_prob`: **0.6246** (62.5% chance high exceeds 84.5°F)
- `final_confidence`: **0.8892**
- Ensemble: ECMWF=10%, GFS=100%, ICON=92.3% → weighted 62.5%
- NWS official: 404 (marine zone, falls back gracefully)
- Open-Meteo current temp: 80.4°F, today high: 81.6°F

### Austin (KXHIGHAUS) — new city
- `get_full_weather_signal('KXHIGHAUS', 82.0, date(2026,3,14))`
- `final_prob`: **0.801** (80.1% chance high exceeds 82°F)
- `final_confidence`: **0.602**
- Ensemble: ECMWF=70%, GFS=86.7%, ICON=87.2% → weighted 80.1%
- NWS official: **85°F** ✅ (NWS data working for Austin)
- Open-Meteo current temp: 83.0°F, today high: 82.9°F

---

## API 8: Kalshi search_markets() + Orderbook Enrichment

**Status: ✅ PASS**

- Called `client.search_markets('temperature')` across all 19 weather series
- **Total markets returned: 192**
- **Markets with orderbook prices: 192 (100% coverage)**
- Sample: `KXHIGHNY-26MAR14-T56` → `yes_bid=3`, `yes_ask=4`
- Rate-limit compliance: 0.05s sleep between orderbook calls working

---

## Issues to Fix

### 🔴 Priority 1: Miami NWS Grid Point
- **Issue:** `MFL/110,37` resolves to a marine forecast zone
- **Effect:** Miami always falls back to Open-Meteo for NWS official data; no degradation in signal quality (Open-Meteo handles it), but no NWS cross-check
- **Fix:** Update `NWS_GRID_POINTS["KXHIGHMIA"]` to a valid inland grid cell, e.g., try `MFL/104,38` or look up via `https://api.weather.gov/points/25.7617,-80.1918`

### 🟡 Priority 2: XDGEUSD Symbol
- **Issue:** Kraken's canonical symbol for DOGE is `DOGEUSD`, not `XDGEUSD`  
- **Effect:** No runtime impact — fallback is already coded and working  
- **Fix:** Update the primary symbol in the pair list to `DOGEUSD` to avoid the failed first request

### 🟡 Priority 3: open-meteo_client date type
- **Issue:** `get_full_weather_signal()` signature expects `datetime.date`, but calling with a string fails silently with a type error
- **Effect:** No impact at runtime (main.py/ruppert_cycle.py use date objects), but makes CLI/test usage fragile
- **Fix:** Add `if isinstance(target_date, str): target_date = date.fromisoformat(target_date)` coercion at function entry

---

## Overall Health

**7/8 APIs fully green. 1 partial (Miami NWS marine zone — gracefully handled).**  
The bot's data layer is healthy and ready for live trading session.
