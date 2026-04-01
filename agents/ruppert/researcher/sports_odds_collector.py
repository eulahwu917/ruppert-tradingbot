"""
sports_odds_collector.py
Ruppert Research — Sports Signal Data Collector

Runs hourly 8am–8pm PDT via Task Scheduler.
For each NBA/MLB game 12–24h from tip-off:
  - Fetches Kalshi yes_ask price
  - Fetches OddsAPI devigged moneyline
  - Computes delta (devigged Vegas prob - Kalshi yes_ask)
  - Searches X (Twitter) for injury news for teams playing that day
  - Logs all data to JSONL

Usage:
  python sports_odds_collector.py

Config (env vars or edit CONFIG below):
  ODDS_API_KEY  - The Odds API key (get at the-odds-api.com)
"""

import os
import sys
import json
import subprocess
import requests

# Ensure UTF-8 output on Windows (Task Scheduler uses cp1252 by default)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

CONFIG = {
    # OddsAPI
    "odds_api_key": json.loads((Path(__file__).resolve().parents[3] / 'secrets' / 'odds_api_config.json').read_text()).get('api_key') if (Path(__file__).resolve().parents[3] / 'secrets' / 'odds_api_config.json').exists() else os.getenv("ODDS_API_KEY", "YOUR_ODDS_API_KEY_HERE"),
    "odds_api_base": "https://api.the-odds-api.com/v4",

    # Kalshi (unauthenticated public API)
    "kalshi_base": "https://api.elections.kalshi.com/trade-api/v2",
    "kalshi_nba_series": "KXNBAGAME",
    "kalshi_mlb_series": "KXMLBGAME",

    # Entry window: games tipping off 12–24 hours from now
    "entry_window_min_hours": 12,
    "entry_window_max_hours": 24,

    # Output log path (relative to workspace root)
    "log_path": "environments/demo/logs/sports_odds_log.jsonl",

    # X (Twitter) search settings
    "x_search_results": 20,   # tweets per query
    "x_search_window_hours": 4,  # look for tweets in last N hours

    # X accounts to monitor for injury news (used in from: filters)
    "x_injury_accounts": [
        "ShamsCharania",     # The Athletic — NBA breaking news
        "wojespn",           # ESPN Woj — NBA
        "adrianwojnarowski", # Woj (alt handle)
        "ESPNBreaking",      # ESPN Breaking News
        "Stadium",           # Stadium sports
        "NBAonTNT",          # Official NBA on TNT
        "NBAonESPN",         # Official NBA on ESPN
        "TheAthleticNBA",    # The Athletic NBA
        "KevinOConnorNBA",   # The Ringer/Athletic NBA
        "JakeLFischer",      # Bleacher Report NBA
        "JonHeyman",         # MLB insider (MLB Heyman)
        "KenRosenthal",      # MLB The Athletic
        "JeffPassan",        # ESPN MLB
        "BNightengale",      # USA Today MLB
        "Feinsand",          # MLB.com insider
        "MLBNetwork",        # Official MLB Network
    ],

    # X injury search queries (keyword-based)
    "x_injury_queries": [
        '"OUT tonight" NBA',
        '"OUT tonight" MLB',
        '"questionable" NBA game',
        '"day-to-day" NBA',
        '"day-to-day" MLB',
        '"ruled out" NBA',
        '"ruled out" MLB',
        '"will not play" NBA',
        '"will not play" MLB',
        '"scratched" MLB lineup',
        '"injury update" NBA',
        '"injury update" MLB',
        '"does not practice" NBA',
        '"late scratch" NBA OR MLB',
    ],
}

# ─── WORKSPACE PATHS ─────────────────────────────────────────────────────────

WORKSPACE_ROOT = Path(r"C:\Users\David Wu\.openclaw\workspace")
LOG_PATH = WORKSPACE_ROOT / CONFIG["log_path"]
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc)

def log_entry(entry: dict):
    """Append a JSON line to the log file."""
    entry["logged_at"] = now_utc().isoformat()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[LOG] {entry.get('event_type', 'entry')} — {entry.get('matchup', entry.get('query', ''))}")

def devig_two_way(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig from two-way market. Returns devigged probs."""
    total = prob_a + prob_b
    return prob_a / total, prob_b / total

def american_to_prob(american_odds: int) -> float:
    """Convert American odds to implied probability."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)

# ─── KALSHI DATA ─────────────────────────────────────────────────────────────

def _parse_matchup_title(title: str) -> tuple[str, str]:
    """Parse 'Away at Home Winner?' title format. Returns (away, home) or ('','')."""
    import re
    m = re.match(r'^(.+?)\s+at\s+(.+?)\s+Winner\??$', title, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""

def _parse_game_date_from_ticker(event_ticker: str) -> datetime | None:
    """Extract game date from event_ticker like KXNBAGAME-26APR02MINDET -> 2026-04-02 UTC."""
    import re
    m = re.search(r'-(\d{2})([A-Z]{3})(\d{2})', event_ticker)
    if not m:
        return None
    year = 2000 + int(m.group(1))
    month_str = m.group(2)
    day = int(m.group(3))
    months = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
              "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
    month = months.get(month_str)
    if not month:
        return None
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None

def fetch_kalshi_games(series_ticker: str, sport: str) -> list[dict]:
    """
    Fetch open Kalshi markets for a series, filter to games 12–24h from now.
    Returns list of game dicts with yes_ask, yes_bid, commence_time, ticker.
    """
    url = f"{CONFIG['kalshi_base']}/markets"
    params = {
        "series_ticker": series_ticker,
        "status": "open",
        "limit": 200,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        markets = resp.json().get("markets", [])
    except Exception as e:
        print(f"[KALSHI ERROR] {sport} fetch failed: {e}")
        return []

    now = now_utc()
    window_min = CONFIG["entry_window_min_hours"]
    window_max = CONFIG["entry_window_max_hours"]

    # Group markets by event_ticker (2 markets per game, one per team)
    event_groups = defaultdict(list)
    # Track which event_tickers are in window (check once per event, not per market)
    event_in_window = {}

    for m in markets:
        event_ticker = m.get("event_ticker", "")

        # Check time window using game date parsed from event_ticker
        # We only know the date, not the exact game time, so include any game
        # whose date falls within 0–48h. Precise 12–24h filtering is applied
        # when matching against OddsAPI commence_time.
        if event_ticker not in event_in_window:
            game_date = _parse_game_date_from_ticker(event_ticker)
            if game_date is None:
                event_in_window[event_ticker] = (False, 0)
            else:
                hours_to_start_of_day = (game_date - now).total_seconds() / 3600
                hours_to_end_of_day = hours_to_start_of_day + 24
                in_range = hours_to_end_of_day >= 0 and hours_to_start_of_day <= 48
                event_in_window[event_ticker] = (in_range, max(hours_to_start_of_day, 0))

        in_window, hours_until = event_in_window[event_ticker]
        if not in_window:
            continue

        close_time_str = m.get("close_time") or m.get("expiration_time") or ""

        yes_ask = m.get("yes_ask_dollars")
        if yes_ask is None:
            continue

        event_ticker = m.get("event_ticker", "")
        # Extract team name from ticker suffix (e.g. KXNBAGAME-26APR02MINDET-MIN -> MIN)
        ticker_str = m.get("ticker", "")
        team_abbr = ticker_str.rsplit("-", 1)[-1] if ticker_str else ""
        event_groups[event_ticker].append({
            "ticker": ticker_str,
            "event_ticker": event_ticker,
            "title": m.get("title", ""),
            "subtitle": m.get("yes_sub_title", ""),
            "team_abbr": team_abbr,
            "close_time": close_time_str,
            "hours_until_close": round(hours_until, 2),
            "yes_ask": float(yes_ask),
            "yes_bid": float(m.get("yes_bid_dollars") or 0),
            "volume": m.get("volume_fp"),
            "open_interest": m.get("open_interest_fp"),
        })

    # Build paired matchup results
    results = []
    for event_ticker, pair in event_groups.items():
        # Extract team names from title (format: "Away at Home Winner?")
        title = pair[0]["title"]
        away_name, home_name = _parse_matchup_title(title)

        if len(pair) < 2:
            mk = pair[0]
            team_name = mk["subtitle"] or away_name or mk["team_abbr"]
            results.append({
                "sport": sport,
                "event_ticker": event_ticker,
                "team_a": team_name,
                "team_b": "",
                "kalshi_a_yes_ask": mk["yes_ask"],
                "kalshi_b_yes_ask": None,
                "ticker_a": mk["ticker"],
                "ticker_b": "",
                "close_time": mk["close_time"],
                "hours_until_close": mk["hours_until_close"],
                "kalshi_volume_a": mk["volume"],
                "kalshi_volume_b": None,
                "kalshi_oi_a": mk["open_interest"],
                "kalshi_oi_b": None,
            })
            continue

        # Two markets per game — pair them, use subtitle/abbr to identify each side
        a, b = pair[0], pair[1]
        team_a = a["subtitle"] or a["team_abbr"]
        team_b = b["subtitle"] or b["team_abbr"]

        # If we parsed title, use full names and map by abbreviation
        if away_name and home_name:
            team_a = away_name if away_name.upper().startswith(a["team_abbr"][:3].upper()) else home_name
            team_b = home_name if team_a == away_name else away_name

        results.append({
            "sport": sport,
            "event_ticker": event_ticker,
            "team_a": team_a,
            "team_b": team_b,
            "kalshi_a_yes_ask": a["yes_ask"],
            "kalshi_b_yes_ask": b["yes_ask"],
            "ticker_a": a["ticker"],
            "ticker_b": b["ticker"],
            "close_time": a["close_time"],
            "hours_until_close": a["hours_until_close"],
            "kalshi_volume_a": a["volume"],
            "kalshi_volume_b": b["volume"],
            "kalshi_oi_a": a["open_interest"],
            "kalshi_oi_b": b["open_interest"],
        })

    return results

# ─── ODDS API DATA ────────────────────────────────────────────────────────────

SPORT_KEYS = {
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
}

def fetch_odds_api(sport: str) -> list[dict]:
    """
    Fetch moneyline odds from OddsAPI for NBA or MLB.
    Returns list of game dicts with devigged home/away probs and commence_time.
    Cost: 1 credit per call (1 market, 1 region).
    """
    sport_key = SPORT_KEYS.get(sport)
    if not sport_key:
        return []

    url = f"{CONFIG['odds_api_base']}/sports/{sport_key}/odds"
    params = {
        "apiKey": CONFIG["odds_api_key"],
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"[ODDS API] {sport} — credits remaining: {remaining}")
        resp.raise_for_status()
        games = resp.json()
    except Exception as e:
        print(f"[ODDS API ERROR] {sport} fetch failed: {e}")
        return []

    now = now_utc()
    window_min = CONFIG["entry_window_min_hours"]
    window_max = CONFIG["entry_window_max_hours"]
    results = []

    for g in games:
        commence_str = g.get("commence_time", "")
        try:
            commence = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
        except Exception:
            continue

        hours_until = (commence - now).total_seconds() / 3600
        if not (window_min <= hours_until <= window_max):
            continue

        home_team = g.get("home_team", "")
        away_team = g.get("away_team", "")
        bookmakers = g.get("bookmakers", [])

        # Aggregate best consensus line (average of books, or use DraftKings as primary)
        home_probs = []
        away_probs = []

        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    odds = outcome.get("price", 0)
                    name = outcome.get("name", "")
                    prob = american_to_prob(int(odds))
                    if name == home_team:
                        home_probs.append(prob)
                    elif name == away_team:
                        away_probs.append(prob)

        if not home_probs or not away_probs:
            continue

        avg_home_raw = sum(home_probs) / len(home_probs)
        avg_away_raw = sum(away_probs) / len(away_probs)
        home_devig, away_devig = devig_two_way(avg_home_raw, avg_away_raw)

        results.append({
            "sport": sport,
            "game_id": g.get("id", ""),
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": commence_str,
            "hours_until_game": round(hours_until, 2),
            "books_count": len(bookmakers),
            "vegas_home_devig": round(home_devig, 4),
            "vegas_away_devig": round(away_devig, 4),
            "vegas_home_raw_avg": round(avg_home_raw, 4),
            "vegas_away_raw_avg": round(avg_away_raw, 4),
        })

    return results

# ─── X (TWITTER) INJURY SEARCH ───────────────────────────────────────────────

def search_x_injuries(teams: list[str]) -> list[dict]:
    """
    Search X for injury news for teams playing today.
    Uses bird CLI (--json). Returns list of tweet result dicts.
    """
    hits = []

    # Build team-specific queries
    team_queries = []
    for team in teams:
        team_queries.append(f'"{team}" (OUT OR questionable OR "day-to-day" OR "ruled out" OR scratch)')

    # Also run generic injury queries
    generic_queries = CONFIG["x_injury_queries"]

    all_queries = team_queries + generic_queries

    bird_cli = r'C:\Users\David Wu\AppData\Roaming\npm\node_modules\@steipete\bird\dist\cli.js'

    for query in all_queries:
        try:
            result = subprocess.run(
                ['node', bird_cli, 'search', query, '-n', str(CONFIG["x_search_results"]), '--json'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=15
            )
            if result.returncode != 0:
                print(f"[BIRD ERROR] query='{query}': {result.stderr.strip()}")
                tweets = []
            else:
                tweets = json.loads(result.stdout) if result.stdout.strip() else []
        except FileNotFoundError:
            print(f"[BIRD ERROR] bird CLI not found - skipping X search")
            tweets = []
        except json.JSONDecodeError as e:
            print(f"[BIRD PARSE ERROR] query='{query}': {e}")
            tweets = []
        except Exception as e:
            print(f"[BIRD ERROR] query='{query}': {e}")
            tweets = []

        if not tweets:
            continue

        for tweet in tweets:
            hits.append({
                "event_type": "x_injury_signal",
                "query": query,
                "tweet_id": tweet.get("id"),
                "text": tweet.get("text", ""),
                "author_id": tweet.get("username", tweet.get("author_id", "")),
                "created_at": tweet.get("createdAt", tweet.get("created_at", "")),
            })
            print(f"[X HIT] {tweet.get('text', '')[:80]}")

    return hits

# ─── MAIN COLLECTOR ──────────────────────────────────────────────────────────

def run_collection():
    print(f"\n{'='*60}")
    print(f"[Ruppert] Sports Odds Collector — {now_utc().isoformat()}")
    print(f"{'='*60}")

    all_teams_today = set()

    # ── 1. Fetch Kalshi markets ──
    kalshi_games = []
    for sport, series in [("NBA", CONFIG["kalshi_nba_series"]), ("MLB", CONFIG["kalshi_mlb_series"])]:
        games = fetch_kalshi_games(series, sport)
        kalshi_games.extend(games)
        print(f"[KALSHI] {sport}: {len(games)} games in window")

    # ── 2. Fetch OddsAPI lines ──
    odds_games = {}
    for sport in ["NBA", "MLB"]:
        games = fetch_odds_api(sport)
        print(f"[ODDS API] {sport}: {len(games)} games in window")
        for g in games:
            key = f"{g['away_team']} @ {g['home_team']}"
            odds_games[key] = g
            all_teams_today.add(g["home_team"])
            all_teams_today.add(g["away_team"])

    # ── 3. Compute deltas and log ──
    for kg in kalshi_games:
        team_a = kg["team_a"]
        team_b = kg["team_b"]
        matchup_key = f"{team_a} vs {team_b}" if team_a and team_b else kg["event_ticker"]

        # Collect team names for X search
        if team_a:
            all_teams_today.add(team_a)
        if team_b:
            all_teams_today.add(team_b)

        # Try to match against OddsAPI game by team name
        vegas_game = None
        matched_team_a_is_home = None
        for key, og in odds_games.items():
            home = og["home_team"].lower()
            away = og["away_team"].lower()
            ta_last = team_a.split()[-1].lower() if team_a else ""
            tb_last = team_b.split()[-1].lower() if team_b else ""
            if ta_last and (ta_last in home or ta_last in away):
                vegas_game = og
                matched_team_a_is_home = ta_last in home
                break
            if tb_last and (tb_last in home or tb_last in away):
                vegas_game = og
                matched_team_a_is_home = not (tb_last in home)
                break

        if vegas_game:
            # Map Kalshi team_a to the correct Vegas side
            if matched_team_a_is_home:
                vegas_a_prob = vegas_game["vegas_home_devig"]
                vegas_b_prob = vegas_game["vegas_away_devig"]
            else:
                vegas_a_prob = vegas_game["vegas_away_devig"]
                vegas_b_prob = vegas_game["vegas_home_devig"]

            delta_a = round(vegas_a_prob - kg["kalshi_a_yes_ask"], 4)
            delta_b = round(vegas_b_prob - kg["kalshi_b_yes_ask"], 4) if kg["kalshi_b_yes_ask"] is not None else None

            entry = {
                "event_type": "odds_snapshot",
                "sport": kg["sport"],
                "matchup": matchup_key,
                "event_ticker": kg["event_ticker"],
                "kalshi_ticker_a": kg["ticker_a"],
                "kalshi_ticker_b": kg["ticker_b"],
                "hours_until_game": kg["hours_until_close"],
                "kalshi_a_yes_ask": kg["kalshi_a_yes_ask"],
                "kalshi_b_yes_ask": kg["kalshi_b_yes_ask"],
                "vegas_a_devig": vegas_a_prob,
                "vegas_b_devig": vegas_b_prob,
                "delta_a_vegas_minus_kalshi": delta_a,
                "delta_b_vegas_minus_kalshi": delta_b,
                "books_count": vegas_game["books_count"],
                "kalshi_volume_a": kg["kalshi_volume_a"],
                "kalshi_volume_b": kg["kalshi_volume_b"],
                "kalshi_oi_a": kg["kalshi_oi_a"],
                "kalshi_oi_b": kg["kalshi_oi_b"],
                "tradeable": abs(delta_a) >= 0.03,  # flag if >= 3pp gap
                "vegas_home_team": vegas_game["home_team"],
                "vegas_away_team": vegas_game["away_team"],
            }
        else:
            entry = {
                "event_type": "kalshi_only_snapshot",
                "sport": kg["sport"],
                "matchup": matchup_key,
                "event_ticker": kg["event_ticker"],
                "kalshi_ticker_a": kg["ticker_a"],
                "hours_until_game": kg["hours_until_close"],
                "kalshi_a_yes_ask": kg["kalshi_a_yes_ask"],
                "kalshi_b_yes_ask": kg["kalshi_b_yes_ask"],
                "delta_vegas_minus_kalshi": None,
                "tradeable": False,
                "note": "Vegas line not yet posted",
            }

        log_entry(entry)

    # ── 4. X injury signal search ──
    if all_teams_today:
        print(f"\n[X SEARCH] Searching injury news for {len(all_teams_today)} teams...")
        hits = search_x_injuries(list(all_teams_today))
        for hit in hits:
            log_entry(hit)
        print(f"[X SEARCH] {len(hits)} injury signals logged")
    else:
        # No OddsAPI games found — still run generic queries
        print("[X SEARCH] No teams from OddsAPI, running generic injury queries...")
        hits = search_x_injuries([])
        for hit in hits:
            log_entry(hit)

    print(f"\n[Ruppert] Collection complete. Log: {LOG_PATH}")

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_collection()
