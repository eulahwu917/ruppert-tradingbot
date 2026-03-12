"""
Position Monitor — Risk Management
===================================
Runs every 5-10 minutes via Task Scheduler.
Applies exit rules in priority order:
1. 95c rule: no_bid >= 95 → sell all (capital efficiency)
2. 70% gain: captured >= 70% of max profit → sell all
3. Near settlement (<30 min): hold
4. Signal reversal: 10-20% trim 25%, 20-35% exit 50%, 35%+ exit 100%
"""

import json
import os
import re
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BOT_DIR  = Path(__file__).parent.parent          # kalshi-bot/
LOGS_DIR = BOT_DIR / "logs"
SECRETS  = BOT_DIR.parent / "secrets"
CONFIG_FILE = SECRETS / "kalshi_config.json"

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
MONITOR_LOG     = LOGS_DIR / "position_monitor.jsonl"


# ── Credentials (never hardcoded) ─────────────────────────────────────────────

def _load_kalshi_config() -> dict:
    """Read API credentials from secrets/kalshi_config.json."""
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)


# ── Position loading ──────────────────────────────────────────────────────────

def load_open_positions() -> list[dict]:
    """
    Read all trade log files in logs/ and return open (unsettled) positions.

    Each position dict includes:
        ticker, side, contracts, entry_price (cents 0-100),
        entry_edge, source, module
    """
    # Collect latest entry per ticker from all trade log files
    by_ticker: dict[str, dict] = {}
    for log_path in sorted(LOGS_DIR.glob("trades_*.jsonl")):
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker')
                    if not ticker:
                        continue
                    # Keep the most recent entry per ticker
                    by_ticker[ticker] = entry
                except Exception:
                    pass

    if not by_ticker:
        print("[MONITOR] No trades found in logs/")
        return []

    # Check market status via Kalshi public API — filter out settled/closed
    open_positions = []
    for ticker, trade in by_ticker.items():
        try:
            url = f"{KALSHI_API_BASE}/markets/{ticker}"
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                market = resp.json().get('market', {})
                status = market.get('status', 'unknown')
                if status != 'active':
                    print(f"[MONITOR] {ticker} status={status} — skipping")
                    continue
            elif resp.status_code == 404:
                print(f"[MONITOR] {ticker} not found — skipping")
                continue
            else:
                # API error: include position conservatively
                print(f"[MONITOR] {ticker} API error {resp.status_code} — including anyway")
        except Exception as e:
            print(f"[MONITOR] {ticker} status check failed: {e} — including anyway")

        side = trade.get('side', 'no').lower()
        market_prob = trade.get('market_prob', 0.0)

        # entry_price in cents: cost per contract paid
        # market_prob = yes probability; for NO trades we paid (1 - market_prob)*100
        if side == 'no':
            entry_price = round((1.0 - market_prob) * 100, 1)
        else:
            entry_price = round(market_prob * 100, 1)

        open_positions.append({
            'ticker':      ticker,
            'side':        side,
            'contracts':   trade.get('contracts', 0),
            'entry_price': entry_price,
            'entry_edge':  trade.get('edge', 0.0),
            'source':      trade.get('source', 'unknown'),
            'module':      trade.get('source', 'unknown'),  # source doubles as module
        })

    print(f"[MONITOR] {len(open_positions)} open position(s) loaded")
    return open_positions


# ── Market data ───────────────────────────────────────────────────────────────

def get_current_bid(ticker: str, side: str) -> float | None:
    """
    Query Kalshi API for the current bid price of the held side.

    Returns the bid in cents (0-100), or None on error.
    API key is read from secrets/kalshi_config.json — never hardcoded.
    """
    try:
        # The public markets endpoint returns bid/ask without auth
        url = f"{KALSHI_API_BASE}/markets/{ticker}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            print(f"[MONITOR] get_current_bid({ticker}): HTTP {resp.status_code}")
            return None
        market = resp.json().get('market', {})
        if side.lower() == 'no':
            bid = market.get('no_bid')
        else:
            bid = market.get('yes_bid')
        return float(bid) if bid is not None else None
    except Exception as e:
        print(f"[MONITOR] get_current_bid({ticker}) error: {e}")
        return None


# ── Exit rules ────────────────────────────────────────────────────────────────

def check_95c_rule(current_bid: float) -> bool:
    """
    95c rule: if bid >= 95c, sell all to recycle capital.
    Near-guaranteed contracts lock up capital unnecessarily.
    """
    return current_bid >= 95


def check_70pct_gain(current_bid: float, entry_price: float) -> bool:
    """
    70% gain rule: sell when we've captured >= 70% of max possible profit.
    Max profit per contract = (100 - entry_price) cents.
    Gain = (current_bid - entry_price).
    """
    max_profit = 100.0 - entry_price
    if max_profit <= 0:
        return False
    gain_pct = (current_bid - entry_price) / max_profit
    return gain_pct >= 0.70


def check_near_settlement(ticker: str) -> bool:
    """
    Parse settlement date/time from ticker and return True if < 30 min away.

    Supported formats:
      - KXHIGHMIA-26MAR11-...    → settles end-of-day March 11, 2026
      - KXETH-26MAR1217-...      → settles March 12, 2026 at 17:00 ET
      - KXCPI-26JUN-...          → monthly (can't determine exact time, return False)
    """
    try:
        parts = ticker.split('-')
        if len(parts) < 2:
            return False
        date_part = parts[1]  # e.g. "26MAR11" or "26MAR1217" or "26JUN"

        # Pattern: YY + MON + DD + optional HH  (e.g. "26MAR11" or "26MAR1217")
        m = re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$', date_part)
        if not m:
            return False  # Monthly or unrecognised format — can't determine, hold

        yy, mon_str, dd, hh = m.group(1), m.group(2), m.group(3), m.group(4)
        year = int("20" + yy)
        day  = int(dd)
        hour = int(hh) if hh else 23   # weather markets settle end-of-day

        settle_dt = datetime.strptime(
            f"{year} {mon_str} {day} {hour}:59",
            "%Y %b %d %H:%M"
        )
        # Treat as US Eastern (UTC-4 in EDT, UTC-5 in EST)
        # Use a simple offset: ET is UTC-5 (conservative — if we're off by an
        # hour we might exit 30 min early, which is still fine)
        settle_utc = settle_dt.replace(tzinfo=timezone.utc) if settle_dt.tzinfo else \
                     settle_dt.replace(tzinfo=timezone.utc)
        # Shift: Eastern ≈ UTC-4 (EDT, Mar–Nov) → add 4 hours to convert ET→UTC
        from datetime import timedelta
        settle_utc_adjusted = settle_utc + timedelta(hours=4)

        now_utc = datetime.now(timezone.utc)
        delta   = settle_utc_adjusted - now_utc
        minutes_to_settle = delta.total_seconds() / 60

        return 0 <= minutes_to_settle < 30

    except Exception as e:
        print(f"[MONITOR] check_near_settlement({ticker}) error: {e}")
        return False


# ── Logging ───────────────────────────────────────────────────────────────────

def log_exit(ticker: str, side: str, contracts: int, fraction: float, reason: str):
    """
    Append exit decision to logs/position_monitor.jsonl.
    Prints a summary line to stdout.
    """
    LOGS_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event":     "exit",
        "ticker":    ticker,
        "side":      side,
        "contracts": contracts,
        "fraction":  fraction,
        "reason":    reason,
        "mode":      "demo",
    }
    with open(MONITOR_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + "\n")

    contracts_to_exit = max(1, round(contracts * fraction))
    print(f"[MONITOR] EXIT {ticker} {reason} {fraction:.0%} ({contracts_to_exit}/{contracts} contracts)")


# ── Main monitor loop ─────────────────────────────────────────────────────────

def run_monitor():
    """
    Main loop: load all open positions, apply exit rules in priority order,
    log actions, and print a summary.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[MONITOR] === Position Monitor run at {now_str} ===")

    positions = load_open_positions()
    if not positions:
        print("[MONITOR] No open positions — nothing to do.")
        _log_summary(0, 0)
        return

    exits_triggered = 0

    for pos in positions:
        ticker      = pos['ticker']
        side        = pos['side']
        contracts   = pos['contracts']
        entry_price = pos['entry_price']
        entry_edge  = pos['entry_edge']

        print(f"\n[MONITOR] Checking {ticker} | side={side} | {contracts} contracts @ {entry_price:.0f}c entry")

        current_bid = get_current_bid(ticker, side)
        if current_bid is None:
            print(f"[MONITOR]   Could not fetch bid — skipping exit rules for {ticker}")
            continue

        print(f"[MONITOR]   Current {side}_bid = {current_bid:.0f}c  (entry {entry_price:.0f}c)")

        # ── Rule 1: 95c rule ─────────────────────────────────────────────────
        if check_95c_rule(current_bid):
            log_exit(ticker, side, contracts, 1.0, "95c_rule")
            # TODO: live mode - call trader.sell(ticker, side, contracts, price=current_bid)
            exits_triggered += 1
            continue

        # ── Rule 2: 70% gain ─────────────────────────────────────────────────
        if check_70pct_gain(current_bid, entry_price):
            gain_pct = (current_bid - entry_price) / max(1, 100 - entry_price)
            log_exit(ticker, side, contracts, 1.0, f"70pct_gain({gain_pct:.0%})")
            # TODO: live mode - call trader.sell(ticker, side, contracts, price=current_bid)
            exits_triggered += 1
            continue

        # ── Rule 3: Near settlement (<30 min) ────────────────────────────────
        if check_near_settlement(ticker):
            print(f"[MONITOR]   {ticker} near settlement (<30 min) — holding to expiry")
            continue

        # ── Rule 4: Signal reversal (bid has moved AGAINST our position) ──────
        # Reversal = current_bid has fallen below entry (we're losing).
        # Measure loss as fraction of entry price eroded.
        if current_bid < entry_price:
            loss_pct = (entry_price - current_bid) / entry_price
            if loss_pct >= 0.35:
                log_exit(ticker, side, contracts, 1.0, f"signal_reversal({loss_pct:.0%})_full")
                # TODO: live mode - call trader.sell(ticker, side, contracts, price=current_bid)
                exits_triggered += 1
            elif loss_pct >= 0.20:
                log_exit(ticker, side, contracts, 0.50, f"signal_reversal({loss_pct:.0%})_half")
                # TODO: live mode - call trader.sell(ticker, side, round(contracts*0.5), price=current_bid)
                exits_triggered += 1
            elif loss_pct >= 0.10:
                log_exit(ticker, side, contracts, 0.25, f"signal_reversal({loss_pct:.0%})_trim")
                # TODO: live mode - call trader.sell(ticker, side, round(contracts*0.25), price=current_bid)
                exits_triggered += 1
            else:
                print(f"[MONITOR]   {ticker} small loss ({loss_pct:.0%}) — within tolerance, holding")
        else:
            gain_pct = (current_bid - entry_price) / entry_price
            print(f"[MONITOR]   {ticker} holding | unrealised gain {gain_pct:+.0%}")

    print(f"\n[MONITOR] === Summary: {exits_triggered} exit(s) triggered out of {len(positions)} position(s) ===")
    _log_summary(len(positions), exits_triggered)


def _log_summary(positions: int, exits: int):
    """Append a run summary line to position_monitor.jsonl."""
    LOGS_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event":     "run_summary",
        "positions": positions,
        "exits":     exits,
        "mode":      "demo",
    }
    with open(MONITOR_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run_monitor()
