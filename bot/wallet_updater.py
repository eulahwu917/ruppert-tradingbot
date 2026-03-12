"""
Wallet Updater — Auto-refreshes top Polymarket crypto trader wallets.

Fetches from the Polymarket leaderboard API (no auth required) and writes
results to logs/smart_money_wallets.json for use by crypto_client.py.

Used by ruppert_cycle.py: called once in the 7am full cycle before crypto scan.

Author: Ruppert (AI Trading Analyst)
Updated: 2026-03-12
"""

import json
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LEADERBOARD_URL = "https://data-api.polymarket.com/v1/leaderboard"
LOGS_DIR = Path(__file__).parent.parent / "logs"
WALLETS_FILE = LOGS_DIR / "smart_money_wallets.json"

# Minimum filters to exclude noise traders
MIN_PNL    = 0.0     # PnL must be > 0
MIN_VOLUME = 1000.0  # Volume must be > $1,000


def fetch_top_crypto_wallets(limit: int = 30) -> list:
    """
    Fetch top CRYPTO traders from Polymarket monthly leaderboard, ordered by PnL.

    Filters:
        - PnL > 0 (profitable traders only)
        - volume > $1,000 (exclude dust/noise)

    Args:
        limit: max number of wallet addresses to return (default 30)

    Returns:
        List of proxyWallet address strings, or [] on any error.
    """
    try:
        params = {
            "category":   "CRYPTO",
            "timePeriod": "MONTH",
            "orderBy":    "PNL",
            "limit":      50,   # always fetch 50, then filter down to `limit`
        }
        r = requests.get(LEADERBOARD_URL, params=params, timeout=15)
        r.raise_for_status()
        traders = r.json()

        if not isinstance(traders, list):
            logger.warning(
                "wallet_updater: unexpected leaderboard response type=%s", type(traders)
            )
            return []

        wallets = []
        for trader in traders:
            proxy_wallet = (trader.get("proxyWallet") or "").strip()
            pnl          = float(trader.get("pnl")    or 0)
            volume       = float(trader.get("volume") or 0)

            if not proxy_wallet:
                continue
            if pnl <= MIN_PNL:
                continue
            if volume <= MIN_VOLUME:
                continue

            wallets.append(proxy_wallet)
            if len(wallets) >= limit:
                break

        logger.info(
            "wallet_updater: fetched %d qualifying wallets from leaderboard", len(wallets)
        )
        return wallets

    except requests.RequestException as e:
        logger.warning("wallet_updater: HTTP error fetching leaderboard: %s", e)
        return []
    except Exception as e:
        logger.warning("wallet_updater: unexpected error fetching leaderboard: %s", e)
        return []


def update_wallet_list() -> bool:
    """
    Fetch top wallets and write them to logs/smart_money_wallets.json.

    If the API fails (network error, empty result, malformed response),
    the existing file is left UNCHANGED so the last-good wallet list persists.

    Returns:
        True  — wallet list successfully updated
        False — API failed; existing list preserved (or no prior list)
    """
    wallets = fetch_top_crypto_wallets(limit=30)

    if not wallets:
        logger.warning(
            "wallet_updater: no wallets returned — keeping existing list unchanged"
        )
        print("  [wallet_updater] API returned no wallets — existing list preserved")
        return False

    LOGS_DIR.mkdir(exist_ok=True)

    data = {
        "wallets":    wallets,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source":     "polymarket_leaderboard",
    }

    WALLETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  [wallet_updater] Updated: {len(wallets)} top CRYPTO traders written to {WALLETS_FILE.name}")
    logger.info("wallet_updater: wrote %d wallets to %s", len(wallets), WALLETS_FILE)
    return True


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=== Wallet Updater Self-Test ===\n")
    success = update_wallet_list()

    if success:
        data = json.loads(WALLETS_FILE.read_text(encoding="utf-8"))
        wallets = data["wallets"]
        print(f"\n  Total wallets stored: {len(wallets)}")
        print(f"  Updated at:          {data['updated_at']}")
        print(f"  Source:              {data['source']}")
        print(f"\n  First 5 wallets:")
        for w in wallets[:5]:
            print(f"    {w}")
        if len(wallets) > 5:
            print(f"    ... and {len(wallets) - 5} more")
    else:
        print("\n  Update failed — API unavailable or returned no qualifying wallets")
        if WALLETS_FILE.exists():
            data = json.loads(WALLETS_FILE.read_text(encoding="utf-8"))
            print(f"  Existing file preserved ({len(data['wallets'])} wallets from {data['updated_at']})")
