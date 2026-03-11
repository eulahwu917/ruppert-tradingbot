"""
Weather Backtest — Last 7 Days of Kalshi KXHIGH Settlements
"""
import sys, json, requests
from datetime import date, datetime, timedelta
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

BASE  = "https://api.elections.kalshi.com/trade-api/v2/markets"
ARCH  = "https://archive-api.open-meteo.com/v1/archive"

CITIES = {
    "KXHIGHNY":  {"name":"New York",    "lat":40.7128, "lon":-74.0060, "tz":"America/New_York"},
    "KXHIGHLA":  {"name":"Los Angeles", "lat":34.0522, "lon":-118.2437,"tz":"America/Los_Angeles"},
    "KXHIGHCHI": {"name":"Chicago",     "lat":41.8781, "lon":-87.6298, "tz":"America/Chicago"},
    "KXHIGHHOU": {"name":"Houston",     "lat":29.7604, "lon":-95.3698, "tz":"America/Chicago"},
    "KXHIGHMIA": {"name":"Miami",       "lat":25.7617, "lon":-80.1918, "tz":"America/New_York"},
    "KXHIGHPHX": {"name":"Phoenix",     "lat":33.4484, "lon":-112.0740,"tz":"America/Phoenix"},
}

def parse_date(s):
    try: return datetime.strptime(s, "%y%b%d").date()
    except: return None

def parse_threshold(s):
    try: return float(s[1:])
    except: return None

def fetch_series(series, days_back=7):
    cutoff = date.today() - timedelta(days=days_back)
    try:
        r = requests.get(BASE,
            params={"series_ticker": series, "status": "settled", "limit": 200},
            timeout=15)
        r.raise_for_status()
        out = []
        for m in r.json().get("markets", []):
            parts = m.get("ticker","").split("-")
            if len(parts) < 3: continue
            d = parse_date(parts[1])
            if d and d >= cutoff:
                out.append(m)
        return out
    except Exception as e:
        print(f"  ERR {series}: {e}")
        return []

def om_archive_high(series, target_date):
    c = CITIES[series]
    try:
        r = requests.get(ARCH, params={
            "latitude": c["lat"], "longitude": c["lon"],
            "start_date": str(target_date), "end_date": str(target_date),
            "daily": "temperature_2m_max", "temperature_unit": "fahrenheit",
            "timezone": c["tz"]
        }, timeout=10)
        r.raise_for_status()
        vals = r.json().get("daily",{}).get("temperature_2m_max",[])
        return round(vals[0],1) if vals else None
    except:
        return None

def run(days_back=7):
    print(f"\n{'='*72}")
    print(f"  KALSHI WEATHER BACKTEST  |  Last {days_back} Days  |  {date.today()}")
    print(f"{'='*72}\n")

    # ── 1. Collect settled markets ────────────────────────────────────────────
    all_markets = []
    for series in CITIES:
        name = CITIES[series]["name"]
        mkts = fetch_series(series, days_back)
        print(f"  {name:<14} → {len(mkts)} settled markets")
        for m in mkts:
            parts = m["ticker"].split("-")
            if len(parts) < 3: continue
            d = parse_date(parts[1])
            if not d: continue
            all_markets.append({
                "series":    series,
                "city":      name,
                "ticker":    m["ticker"],
                "kind":      parts[2][0],          # B or T
                "value":     parse_threshold(parts[2]),
                "date":      d,
                "actual_f":  float(m["expiration_value"]) if m.get("expiration_value") is not None else None,
                "result":    m.get("result"),
                "volume":    m.get("volume", 0) or 0,
                "last_price":m.get("last_price"),
            })

    if not all_markets:
        print("\n  No data found.")
        return

    # ── 2. Unique city/date combos with actual high ───────────────────────────
    actuals = {}  # (series, date) → actual_f
    for m in all_markets:
        key = (m["series"], m["date"])
        if key not in actuals and m["actual_f"] is not None:
            actuals[key] = m["actual_f"]

    print(f"\n{'─'*72}")
    print(f"  ACTUAL DAILY HIGHS  (Kalshi official settlement temp)")
    print(f"{'─'*72}")
    print(f"  {'City':<14} {'Date':<12} {'Actual':>7}  {'YES band':>20}  OM Archive  Delta")
    print(f"  {'─'*65}")

    calibration = []
    for (series, d), actual in sorted(actuals.items(), key=lambda x: (x[0][1], x[0][0])):
        name = CITIES[series]["name"]
        # Find which B band settled YES
        yes_band = "--"
        for m in all_markets:
            if m["series"]==series and m["date"]==d and m["kind"]=="B" and m["result"]=="yes":
                yes_band = f"B{m['value']} ({m['value']}–{m['value']+2}°F)"
                break
        # Open-Meteo archive
        om = om_archive_high(series, d) if d < date.today() else None
        delta_str = f"{om-actual:+.1f}°F" if om else "N/A"
        om_str    = f"{om}°F" if om else "N/A"
        match_sym = "✓" if om and abs(om-actual)<=2 else ("⚠" if om and abs(om-actual)<=4 else "❌" if om else "")
        print(f"  {name:<14} {str(d):<12} {str(actual)+'°F':>7}  {yes_band:>20}  {om_str:>8}  {delta_str:>7}  {match_sym}")
        if om:
            calibration.append(abs(om - actual))

    if calibration:
        avg_err   = sum(calibration) / len(calibration)
        within_2  = sum(1 for x in calibration if x <= 2) / len(calibration) * 100
        within_4  = sum(1 for x in calibration if x <= 4) / len(calibration) * 100
        print(f"\n  Open-Meteo accuracy:  avg error={avg_err:.1f}°F  "
              f"within 2°F={within_2:.0f}%  within 4°F={within_4:.0f}%")

    # ── 3. Top markets by volume ──────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print(f"  TOP MARKETS BY VOLUME  (where real price discovery happens)")
    print(f"{'─'*72}")
    print(f"  {'Ticker':<34} {'Vol':>8}  {'Result':<5}  {'Last Price'}")
    print(f"  {'─'*60}")
    for m in sorted(all_markets, key=lambda x: x["volume"], reverse=True)[:25]:
        print(f"  {m['ticker']:<34} {m['volume']:>8}  {m['result']:<5}  {m['last_price']}¢")

    # ── 4. Market type breakdown ──────────────────────────────────────────────
    b_mkts   = [m for m in all_markets if m["kind"] == "B"]
    b_yes    = [m for m in b_mkts if m["result"] == "yes"]
    t_mkts   = [m for m in all_markets if m["kind"] == "T"]
    t_yes    = [m for m in t_mkts if m["result"] == "yes"]
    total    = len(all_markets)

    print(f"\n{'─'*72}")
    print(f"  MARKET STATS")
    print(f"{'─'*72}")
    print(f"  Total settled markets: {total}")
    print(f"  Band (B) markets:  {len(b_yes):>3}/{len(b_mkts)}  YES = {len(b_yes)/len(b_mkts)*100:.0f}%"
          f"  (expect ~17% since exactly 1 of ~6 bands wins each day)")
    print(f"  Threshold (T) mkts:{len(t_yes):>3}/{len(t_mkts)}  YES = {len(t_yes)/len(t_mkts)*100:.0f}%"
          f"  (upper tail OR lower tail markets)")

    # ── 5. Edge simulation: bet NO on high B bands, YES on low B bands ────────
    print(f"\n{'─'*72}")
    print(f"  EDGE SIMULATION  — B-band markets")
    print(f"  Strategy: bet on whether actual high is ABOVE or BELOW a band")
    print(f"{'─'*72}")

    # For each B band, compute: was actual_f above or below it?
    above_band, below_band = 0, 0
    for m in b_mkts:
        actual = actuals.get((m["series"], m["date"]))
        if actual is None: continue
        if actual >= m["value"] + 2:  above_band += 1  # actual ABOVE this band
        elif actual < m["value"]:     below_band += 1  # actual BELOW this band

    print(f"  Of all B markets: {above_band} actual was ABOVE band, {below_band} BELOW band, "
          f"{len(b_yes)} IN band")
    print(f"  → NO bets on bands ABOVE actual win {above_band} times (buy NO on high bands)")
    print(f"  → NO bets on bands BELOW actual win {below_band} times (buy NO on low bands)")
    print(f"\n  Win rate if we bet NO on any B band NOT in the 'likely range':")
    no_wins  = above_band + below_band
    no_total = above_band + below_band + len(b_yes)
    print(f"  {no_wins}/{no_total} = {no_wins/no_total*100:.1f}%  (we win whenever the high ISN'T in our chosen band)")

    # ── 6. Key insight ────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print(f"  KEY INSIGHT FOR ALGORITHM")
    print(f"{'─'*72}")

    # What's the typical spread between bands?
    # Check if highest-volume B band matches actual
    correct_high_vol = 0
    total_days = len(actuals)
    for (series, d), actual in actuals.items():
        # Find highest volume B band for this day
        day_b = sorted(
            [m for m in b_mkts if m["series"]==series and m["date"]==d],
            key=lambda x: x["volume"], reverse=True
        )
        if day_b:
            top_band = day_b[0]
            if top_band["result"] == "yes":
                correct_high_vol += 1

    if total_days > 0:
        print(f"  Highest-volume B band = actual outcome: {correct_high_vol}/{total_days} days "
              f"({correct_high_vol/total_days*100:.0f}%)")
        print(f"  → Market volume concentrates around the correct temperature band!")
        print(f"  → Trading with market volume (not against it) is key signal.\n")

    # Save
    import os; os.makedirs("logs", exist_ok=True)
    with open(f"logs/backtest_{date.today()}.json","w",encoding="utf-8") as f:
        json.dump({
            "run_date": str(date.today()),
            "total_markets": total,
            "om_avg_error_f": round(avg_err,2) if calibration else None,
            "om_within_2f_pct": round(within_2,1) if calibration else None,
            "correct_high_vol_rate": round(correct_high_vol/total_days*100,1) if total_days else None,
        }, f, indent=2)
    print(f"  Saved → logs/backtest_{date.today()}.json")
    print(f"\n{'='*72}\n")

if __name__ == "__main__":
    run(days_back=7)
