# DATA ANALYST SPECS — Batch DA
_Authored by: Data Analyst agent | Date: 2026-03-29_

---

## DA1: Heartbeat Written Every 5min — Should Be Every 60s (MEDIUM)

**Files to modify:**
- `agents/ruppert/data_analyst/ws_feed.py`

**Change:**

Add a `_write_heartbeat()` call inside the 60-second persist block, immediately after `market_cache.persist()`.

**Current code** (find this exact block inside the `async for raw in ws:` loop):

```python
                    # Periodic persist every 60s
                    if now - last_persist >= 60:
                        market_cache.persist()
                        last_persist = now
```

**Replace with:**

```python
                    # Periodic persist every 60s
                    if now - last_persist >= 60:
                        market_cache.persist()
                        _write_heartbeat()
                        last_persist = now
```

No other changes. The existing `_write_heartbeat()` calls on WS connect and in the 300s purge block remain as-is.

**Context for Dev:** `_write_heartbeat()` is defined at module level (bottom of file). The 300s purge block already calls it. The 60s block currently does not, meaning the watchdog heartbeat file is only refreshed every 5 minutes. Any watchdog tolerance < 5 minutes will false-alarm.

**Test (QA):**
1. Run `ws_feed.py` and tail the `logs/ws_feed_heartbeat.json` file.
2. Confirm `last_heartbeat` timestamp updates approximately every 60 seconds (not every 300s).
3. Let run for 10 minutes — `last_heartbeat` should never be more than ~65s stale at any check point.

---

## DA2: openmeteo_client.py Bare Imports of ghcnd_client — Fragile Import Path (HIGH)

**Files to modify:**
- `agents/ruppert/data_analyst/openmeteo_client.py`

**Change — Part 1: Add workspace path bootstrap at top of file**

`openmeteo_client.py` currently has NO `sys.path` bootstrap. Every other file in `data_analyst/` uses the following standard pattern (reference: `ghcnd_client.py` lines 1–8 of the path setup block, also identical in `kalshi_client.py` and `ws_feed.py`):

```python
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))
```

Add this block to `openmeteo_client.py` immediately after the module docstring, before the `import requests` line. The file currently starts with:

```python
"""
Open-Meteo Client — Multi-source weather data for Kalshi weather trading.
...
"""

import requests
import logging
```

**Replace with:**

```python
"""
Open-Meteo Client — Multi-source weather data for Kalshi weather trading.
...
"""

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

import requests
import logging
```

**Change — Part 2: Replace all three bare `ghcnd_client` imports**

There are exactly three import sites. Replace all three:

**Site 1** — inside `_get_bias()` function (~line 175):

_Current:_
```python
        from ghcnd_client import get_bias as _ghcnd_bias
        return _ghcnd_bias(series_ticker)
```

_Replace with:_
```python
        from agents.ruppert.data_analyst.ghcnd_client import get_bias as _ghcnd_bias
        return _ghcnd_bias(series_ticker)
```

**Site 2** — inside `get_current_conditions()`, in the bias correction block (~line 340):

_Current:_
```python
        try:
            from ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
            bias        = _ghcnd_bias(series_ticker)
            bias_source = get_bias_source(series_ticker)
        except Exception:
            bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
            bias_source = "hardcoded_import_error"
```

_Replace with:_
```python
        try:
            from agents.ruppert.data_analyst.ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
            bias        = _ghcnd_bias(series_ticker)
            bias_source = get_bias_source(series_ticker)
        except Exception:
            bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
            bias_source = "hardcoded_import_error"
```

**Site 3** — inside `get_full_weather_signal()`, in the bias block near the top (~line 480):

_Current:_
```python
    try:
        from ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
        bias        = _ghcnd_bias(series_ticker)
        bias_source = get_bias_source(series_ticker)
    except Exception:
        bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
        bias_source = "hardcoded_import_error"
```

_Replace with:_
```python
    try:
        from agents.ruppert.data_analyst.ghcnd_client import get_bias as _ghcnd_bias, get_bias_source
        bias        = _ghcnd_bias(series_ticker)
        bias_source = get_bias_source(series_ticker)
    except Exception:
        bias        = CITY_BIAS_F.get(series_ticker, DEFAULT_BIAS_F)
        bias_source = "hardcoded_import_error"
```

**Test (QA):**
1. From the workspace root (`C:\Users\David Wu\.openclaw\workspace`), run:
   `python -m agents.ruppert.data_analyst.openmeteo_client`
   Confirm it completes without `ModuleNotFoundError` for `ghcnd_client`.
2. From a working directory OTHER than the `data_analyst/` folder (e.g., workspace root), run:
   `python agents/ruppert/data_analyst/openmeteo_client.py`
   Confirm same — no import error, bias source logged as `ghcnd` or `hardcoded_fallback` (not `hardcoded_import_error`).
3. Confirm `bias_source` in `get_current_conditions()` logs never shows `hardcoded_import_error` in a normal run.

---

## DA3: Kalshi Rate Limit 50ms — Spec Requires 100ms (MEDIUM)

**Files to modify:**
- `agents/ruppert/data_analyst/kalshi_client.py`

**Change:**

Replace every `time.sleep(0.05)` with `time.sleep(0.1)` in the four specified functions. There are exactly **4** occurrences. All are inter-request courtesy sleeps, not retry waits. Find each by the comment or context below:

**Occurrence 1** — `search_markets()`, inside the per-market orderbook enrichment loop:

_Current:_
```python
                        time.sleep(0.05)  # 20 req/sec rate limit
```
_Replace with:_
```python
                        time.sleep(0.1)  # 10 req/sec rate limit (spec: 100ms minimum)
```

**Occurrence 2** — `get_markets_metadata()`, at the bottom of the pagination loop:

_Current:_
```python
            time.sleep(0.05)  # rate limit courtesy
```
_Replace with:_
```python
            time.sleep(0.1)  # rate limit courtesy (spec: 100ms minimum)
```

**Occurrence 3** — `enrich_orderbook()`, at the end of the function before `return market`:

_Current:_
```python
        time.sleep(0.05)
        return market
```
_Replace with:_
```python
        time.sleep(0.1)
        return market
```

**Occurrence 4** — `get_markets()`, inside the per-market orderbook enrichment loop:

_Current:_
```python
            time.sleep(0.05)
```
_Replace with:_
```python
            time.sleep(0.1)
```

**Note for Dev:** Do NOT change the `time.sleep(delay)` calls inside `_get_with_retry()` — those are exponential backoff delays (starting at 1.0s) and are separate from the inter-request rate limit sleeps being corrected here.

**Test (QA):**
1. `grep -n "sleep(0.05)" agents/ruppert/data_analyst/kalshi_client.py` → must return 0 results.
2. `grep -n "sleep(0.1)" agents/ruppert/data_analyst/kalshi_client.py` → must return exactly 4 results (in `search_markets`, `get_markets_metadata`, `enrich_orderbook`, `get_markets`).
3. Run `python agents/ruppert/data_analyst/kalshi_client.py` and confirm it completes without 429 errors. Optionally instrument with timing to confirm ≥100ms between successive orderbook fetches.

---

## DA4: MEMORY.md Stale Purge Value (LOW)

**Files to modify:**
- `agents/ruppert/data_analyst/MEMORY.md`

**Change:**

In the `## WS Feed Architecture` section, find this line:

_Current:_
```
- Stale threshold: 60s; purge: 300s; persistence: `logs/price_cache.json`
```

_Replace with:_
```
- Stale threshold: 60s; purge: 86400s (24h); persistence: `logs/price_cache.json`
```

**Context:** `WS_CACHE_PURGE_SECONDS` in the codebase is currently `86400`. The MEMORY.md value of `300s` reflects an old default and will mislead future debugging sessions.

**Test (QA):**
1. Open `MEMORY.md` and confirm the WS Feed Architecture line reads `purge: 86400s (24h)`.
2. Cross-check: `grep WS_CACHE_PURGE_SECONDS` in `market_cache.py` (or wherever it's defined) should show `86400`. If values differ, flag to Data Analyst for reconciliation before closing.

---

_End of Batch DA Specs_
