# strategy_simulator.py — Ruppert Backtest Framework
# Mirrors bot/strategy.py sizing and filtering logic for simulation.
# No live API calls, no imports from the live/demo bot directories.

import math

# ---------------------------------------------------------------------------
# Default config — mirrors current live parameters from team_context.md
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "min_edge_weather":       0.15,   # minimum |model_prob - market_prob|
    "min_edge_crypto":        0.12,
    "min_confidence_weather": 0.55,
    "min_confidence_crypto":  0.50,
    "pct_capital_cap":        0.025,  # max 2.5% of capital per trade
    "max_position_cap":       50.0,   # hard dollar cap per ticker
    "daily_cap_pct":          0.70,   # max 70% of capital deployed in one day
    "same_day_skip_hour":     14,     # UTC hour: skip same-day markets after this
    "fractional_kelly":       0.25,   # fractional Kelly multiplier
    "min_trade_size":         5.0,    # minimum trade size in dollars
}


# ---------------------------------------------------------------------------
# Kelly sizing helpers
# ---------------------------------------------------------------------------

def _kelly_fraction(prob: float, odds: float) -> float:
    """
    Standard Kelly criterion fraction.
    prob:  probability of winning (0..1)
    odds:  net odds paid on a win (e.g. if YES pays $1 on a $0.60 bet, odds = 0.667)
    Returns fraction of bankroll to bet (can be negative → don't bet).
    """
    if odds <= 0:
        return 0.0
    q = 1.0 - prob
    kelly = (prob * odds - q) / odds
    return max(kelly, 0.0)


def _position_size(
    signal: dict,
    market: dict,
    capital: float,
    config: dict,
) -> float:
    """
    Compute Kelly-weighted position size, capped by config limits.
    Returns dollar size (float).
    """
    prob = signal.get("prob", 0.5)
    direction = signal.get("direction", "YES")

    # Entry price in cents (0-100 scale)
    # yes_ask and last_price from Kalshi API are in dollars (0.01-1.0), not cents
    yes_ask = market.get("yes_ask")
    last_price = market.get("last_price", 0.50)

    if yes_ask is None or yes_ask <= 0:
        yes_ask = 1.0 - last_price if last_price else 0.50

    if direction == "YES":
        entry_cents = float(yes_ask) * 100.0   # dollars → cents
    else:
        # Buying NO: price is (1 - yes_ask) in dollars → cents
        entry_cents = (1.0 - float(yes_ask)) * 100.0

    if entry_cents <= 0 or entry_cents >= 100:
        entry_cents = 50.0  # fallback

    # Convert cents to decimal probability / price
    entry_price = entry_cents / 100.0

    # Net odds: if I pay entry_price and win, I get $1 → net = (1 - entry_price)
    odds = (1.0 - entry_price) / entry_price if entry_price > 0 else 0.0

    kelly = _kelly_fraction(prob, odds)
    fractional = kelly * config.get("fractional_kelly", 0.25)

    # Dollar size from fractional Kelly
    raw_size = fractional * capital

    # Cap at pct_capital_cap
    cap1 = capital * config["pct_capital_cap"]
    # Cap at max_position_cap
    cap2 = config["max_position_cap"]

    size = min(raw_size, cap1, cap2)

    # Enforce minimum
    if size < config.get("min_trade_size", 5.0):
        return 0.0

    return round(size, 2)


# ---------------------------------------------------------------------------
# Main filter: should_trade
# ---------------------------------------------------------------------------

def should_trade(
    signal: dict,
    market: dict,
    capital: float,
    config: dict,
    module: str = "weather",
) -> dict:
    """
    Decide whether to place a simulated trade.

    Args:
        signal:  output from simulate_weather_signal or simulate_crypto_signal
        market:  a single Kalshi settled market dict
        capital: current available capital in dollars
        config:  strategy config dict (DEFAULT_CONFIG or sweep variant)
        module:  'weather' or 'crypto'

    Returns:
        {'trade': bool, 'size': float, 'reason': str}
    """
    no_trade = {"trade": False, "size": 0.0, "reason": ""}

    # ---- Guard: signal valid ----
    if signal.get("skip", False):
        return {**no_trade, "reason": f"signal skip: {signal.get('reason', '')}"}

    direction = signal.get("direction", "NEUTRAL")
    if direction == "NEUTRAL" or direction == "UNKNOWN":
        return {**no_trade, "reason": "neutral/unknown direction"}

    # ---- Guard: market settled and valid ----
    last_price = market.get("last_price")
    if last_price is None:
        return {**no_trade, "reason": "no last_price (unsettled)"}

    # ---- Compute edge (model prob vs market implied prob) ----
    # yes_ask and last_price from Kalshi API are in dollars (0.01-1.0), not cents
    yes_ask = market.get("yes_ask")
    if yes_ask is None or yes_ask <= 0:
        yes_ask = 1.0 - last_price if last_price else 0.50

    if direction == "YES":
        market_prob = float(yes_ask)          # already 0-1 (dollars)
    else:
        market_prob = 1.0 - float(yes_ask)    # NO implied prob

    model_prob = signal.get("prob", 0.5)
    edge = abs(model_prob - market_prob)

    # Write edge back into signal for downstream reporting
    signal["edge"] = round(edge, 4)
    signal["market_prob"] = round(market_prob, 4)

    # ---- Apply thresholds ----
    if module == "weather":
        min_edge = config["min_edge_weather"]
        min_conf = config["min_confidence_weather"]
    else:
        min_edge = config["min_edge_crypto"]
        min_conf = config["min_confidence_crypto"]

    if edge < min_edge:
        return {**no_trade, "reason": f"edge {edge:.3f} < min {min_edge}"}

    confidence = signal.get("confidence", 0.0)
    if confidence < min_conf:
        return {**no_trade, "reason": f"confidence {confidence:.3f} < min {min_conf}"}

    # ---- Capital check ----
    if capital <= 0:
        return {**no_trade, "reason": "no capital"}

    # ---- Compute size ----
    size = _position_size(signal, market, capital, config)
    if size <= 0:
        return {**no_trade, "reason": "position size too small"}

    return {
        "trade":  True,
        "size":   size,
        "reason": f"edge={edge:.3f} conf={confidence:.3f} dir={direction}",
    }


# ---------------------------------------------------------------------------
# P&L computation
# ---------------------------------------------------------------------------

def compute_pnl(trade: dict, market: dict) -> float:
    """
    Compute realized P&L for a simulated trade after settlement.

    Args:
        trade: {
            ticker:            str,
            side:              'YES' or 'NO',
            entry_price_cents: float,   # e.g. 62.0 = 62¢
            contracts:         int,     # number of contracts ($0.01 each at settlement)
            size_dollars:      float,   # total dollars risked
        }
        market: {
            last_price: float,  # settlement price; ~99 = YES won, ~1 = NO won
        }

    Returns float: P&L in dollars (positive = profit, negative = loss)

    Kalshi contract mechanics:
      - Each contract costs entry_price_cents / 100 dollars
      - A winning contract pays $1.00
      - A losing contract pays $0.00
      - P&L = contracts * (payout - entry_price_cents/100)
            = contracts * (win_payout - cost_per_contract)
    """
    side = trade.get("side", "YES")
    entry_cents = float(trade.get("entry_price_cents", 50.0))
    size_dollars = float(trade.get("size_dollars", 0.0))
    # last_price from Kalshi API is in dollars (0.01-0.99), not cents
    last_price = float(market.get("last_price", 0.50))

    if size_dollars <= 0 or entry_cents <= 0:
        return 0.0

    # Number of contracts bought (each contract costs entry_cents/100 dollars)
    cost_per_contract = entry_cents / 100.0
    if cost_per_contract <= 0:
        return 0.0
    contracts = size_dollars / cost_per_contract

    # Determine outcome: YES won if last_price >= 0.50 (dollars, not cents)
    yes_won = last_price >= 0.50

    if side == "YES":
        won = yes_won
    else:
        won = not yes_won

    if won:
        # Each contract pays $1.00; we paid cost_per_contract
        pnl = contracts * (1.0 - cost_per_contract)
    else:
        # Lose the cost of each contract
        pnl = -size_dollars

    return round(pnl, 4)
