"""
Risk Management
Kelly criterion position sizing and daily exposure limits.
"""
import config
from logger import get_daily_exposure


def kelly_fraction(prob, bet_price_cents):
    """
    Kelly criterion: what fraction of bankroll to bet.
    prob: our estimated probability of WINNING the bet
    bet_price_cents: cost of the contract in cents (e.g. 82 cents for a NO contract)
    Returns fraction between 0 and 1.
    """
    if prob <= 0 or prob >= 1 or bet_price_cents <= 0:
        return 0
    q = 1 - prob
    # Actual payout odds: profit per dollar bet
    # If you pay X cents and win, you get 100 cents back = (100-X)/X profit per cent paid
    b = (100 - bet_price_cents) / bet_price_cents
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    # Use fractional Kelly (25%) to be conservative
    return max(0, kelly * 0.25)


def calculate_position_size(bankroll, edge_opportunity):
    """
    Calculate how much to bet on an opportunity.
    Returns amount in dollars, capped by risk limits.
    """
    win_prob = edge_opportunity.get('win_prob', edge_opportunity['noaa_prob'])
    bet_price = edge_opportunity.get('bet_price', edge_opportunity['yes_price'])
    fraction = kelly_fraction(win_prob, bet_price)

    # Ideal Kelly bet
    ideal_size = bankroll * fraction

    # Cap at max position size
    size = min(ideal_size, config.MAX_POSITION_SIZE)

    # Check daily exposure
    daily_used = get_daily_exposure()
    remaining_daily = config.MAX_DAILY_EXPOSURE - daily_used

    if remaining_daily <= 0:
        print(f"[Risk] Daily exposure limit reached (${config.MAX_DAILY_EXPOSURE}). No more trades today.")
        return 0

    size = min(size, remaining_daily)

    # Minimum meaningful bet
    if size < 1.0:
        return 0

    return round(size, 2)


def contracts_from_size(size_dollars, price_cents):
    """
    Convert dollar amount to number of contracts.
    Each contract costs price_cents/100 dollars.
    """
    if price_cents <= 0:
        return 0
    price_dollars = price_cents / 100
    contracts = int(size_dollars / price_dollars)
    return max(1, contracts)


def check_pre_trade(opportunity, bankroll):
    """
    Final pre-trade risk check.
    Returns (approved, reason, size, contracts)
    """
    size = calculate_position_size(bankroll, opportunity)

    if size <= 0:
        return False, "Daily exposure limit reached or Kelly says skip", 0, 0

    price_cents = opportunity.get('bet_price', opportunity['yes_price'] if opportunity['side'] == 'yes' else (100 - opportunity['yes_price']))
    contracts = contracts_from_size(size, price_cents)

    if contracts <= 0:
        return False, "Position too small to be meaningful", 0, 0

    return True, "Trade approved", size, contracts
