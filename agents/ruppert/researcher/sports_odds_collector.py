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
import json
import subprocess
import requests
from datetime import datetime, timezone, timedelta
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

def fetch_kalshi_games(series_ticker: str, sport: str) -> list[dict]:
    """
    Fetch open Kalshi markets for a series, filter to games 12–24h from now.
    Returns list of game dicts with yes_ask, yes_bid, commence_time, ticker.
    """
    url = f"{CONFIG['kalshi_base']}/markets"
    params = {
        "series_ticker": series_ticker,
        "status": "open",
        "limit": 100,
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
    results = []

    for m in markets:
        # Parse commence time (expiration_time or close_time as proxy)
        # Kalshi market titles typically include team names
        close_time_str = m.get("close_time") or m.get("expiration_time")
        if not close_time_str:
            continue
        try:
            close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        except Exception:
            continue

        hours_until = (close_time - now).total_seconds() / 3600
        if not (window_min <= hours_until <= window_max):
            continue

        yes_ask = m.get("yes_ask")  # in cents (0–100)
        yes_bid = m.get("yes_bid")
        no_ask = m.get("no_ask")
        ticker = m.get("ticker", "")
        title = m.get("title", "")
        event_ticker = m.get("event_ticker", "")

        if yes_ask is None:
            continue

        results.append({
            "sport": sport,
            "ticker": ticker,
            "event_ticker": event_ticker,
            "title": title,
            "close_time": close_time_str,
            "hours_until_close": round(hours_until, 2),
            "kalshi_yes_ask_cents": yes_ask,
            "kalshi_yes_ask": yes_ask / 100,
            "kalshi_yes_bid": (yes_bid or 0) / 100,
            "kalshi_no_ask": (no_ask or 0) / 100,
            "kalshi_open_interest": m.get("open_interest"),
            "kalshi_volume": m.get("volume"),
        })

    return results


def get_kalshi_teams_from_title(title: str) -> tuple[str, str]:
    """
    Attempt to extract team names from Kalshi market title.
    Example title: "Will the Boston Celtics beat the Miami Heat?"
    Returns (team_a, team_b) or ("", "")
    """
    # Simple heuristic: look for ' beat ' pattern
    if " beat " in title.lower():
        parts = title.split(" beat ")
        if len(parts) == 2:
            team_a = parts[0].replace("Will the ", "").replace("Will ", "").strip()
            team_b = parts[1].replace("?", "").replace("the ", "").strip()
            return team_a, team_b
    return "", ""

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

    for query in all_queries:
        try:
            result = subprocess.run(
                ['bird', 'search', query, '-n', str(CONFIG["x_search_results"]), '--json'],
                capture_output=True,
                text=True,
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
        team_a, team_b = get_kalshi_teams_from_title(kg["title"])
        matchup_key = f"{team_a} @ {team_b}" if team_a and team_b else kg["title"]

        # Try to match against OddsAPI game
        vegas_game = None
        for key, og in odds_games.items():
            # Fuzzy match: check if either team name appears
            if (team_a and (team_a in key or any(t in key for t in team_a.split()[-1:]))
                    or team_b and (team_b in key or any(t in key for t in team_b.split()[-1:]))):
                vegas_game = og
                break

        if vegas_game:
            # Kalshi yes_ask is for team_a (home team in Kalshi framing — usually favorite)
            # Vegas home_devig maps to home team
            kalshi_fav_prob = kg["kalshi_yes_ask"]

            # Use Vegas home team prob as reference
            vegas_fav_prob = vegas_game["vegas_home_devig"]

            delta = round(vegas_fav_prob - kalshi_fav_prob, 4)

            entry = {
                "event_type": "odds_snapshot",
                "sport": kg["sport"],
                "matchup": matchup_key,
                "kalshi_ticker": kg["ticker"],
                "hours_until_game": kg["hours_until_close"],
                "kalshi_yes_ask": kalshi_fav_prob,
                "kalshi_yes_bid": kg["kalshi_yes_bid"],
                "vegas_devig_home": vegas_fav_prob,
                "vegas_devig_away": vegas_game["vegas_away_devig"],
                "delta_vegas_minus_kalshi": delta,
                "books_count": vegas_game["books_count"],
                "kalshi_volume": kg["kalshi_volume"],
                "kalshi_open_interest": kg["kalshi_open_interest"],
                "tradeable": abs(delta) >= 0.03,  # flag if >= 3pp gap
                "vegas_home_team": vegas_game["home_team"],
                "vegas_away_team": vegas_game["away_team"],
            }
        else:
            # Log Kalshi-only (Vegas not yet posted)
            entry = {
                "event_type": "kalshi_only_snapshot",
                "sport": kg["sport"],
                "matchup": matchup_key,
                "kalshi_ticker": kg["ticker"],
                "hours_until_game": kg["hours_until_close"],
                "kalshi_yes_ask": kg["kalshi_yes_ask"],
                "kalshi_yes_bid": kg["kalshi_yes_bid"],
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
