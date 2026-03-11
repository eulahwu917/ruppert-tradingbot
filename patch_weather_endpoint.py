"""
Fix /api/kalshi/weather — replace slow blocking NOAA/Open-Meteo call with:
1. Serve from cache file (logs/weather_scan.jsonl) written by background scanner
2. If cache missing/stale, fetch raw Kalshi markets only (no edge calc) — fast
"""
from pathlib import Path

api_path = Path('dashboard/api.py')
code = api_path.read_text(encoding='utf-8')

# Find the weather endpoint
start = code.find('.get("/api/kalshi/weather")')
start = code.rfind('@app', 0, start)
end   = code.find('\n@app.', start + 10)
if end == -1:
    end = len(code)

OLD_BLOCK = code[start:end]

NEW_BLOCK = '''@app.get("/api/kalshi/weather")
def get_weather_markets():
    """
    Weather markets — served from scanner cache for speed.
    Background scanner (ruppert_cycle.py) writes logs/weather_scan.jsonl.
    Fallback: raw Kalshi markets with no edge calc (fast, no NOAA calls).
    """
    import requests as req

    # 1. Try cache first (written by background scanner)
    cache = LOGS_DIR / "weather_scan.jsonl"
    if cache.exists():
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime)
        if age < 14400:  # < 4 hours old
            markets = []
            for line in cache.read_text(encoding='utf-8').splitlines():
                try: markets.append(json.loads(line))
                except: pass
            if markets:
                return markets

    # 2. Fast fallback: raw Kalshi markets, no blocking NOAA/ensemble calls
    try:
        series = ['KXHIGHNY', 'KXHIGHLA', 'KXHIGHCHI', 'KXHIGHHOU', 'KXHIGHMIA', 'KXHIGHPHX']
        markets = []
        for s in series:
            try:
                resp = req.get(
                    'https://api.elections.kalshi.com/trade-api/v2/markets',
                    params={'series_ticker': s, 'status': 'open', 'limit': 8},
                    timeout=5
                )
                if resp.status_code == 200:
                    for m in resp.json().get('markets', []):
                        m['_has_edge']  = False
                        m['_edge']      = None
                        m['_noaa_prob'] = None
                        m['kalshi_url'] = f"https://kalshi.com/markets/{m.get('ticker','')}"
                        markets.append(m)
            except Exception:
                pass
        return markets[:30]
    except Exception as e:
        return {"error": str(e)}

'''

code = code[:start] + NEW_BLOCK + code[end:]
api_path.write_text(code, encoding='utf-8')
print(f"Patched /api/kalshi/weather — now cache-first, no blocking NOAA calls")
print(f"File size: {len(code.splitlines())} lines")
