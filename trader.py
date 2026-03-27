"""
Trade Executor
Handles order placement with pre-trade checks.

Note: risk.py was a v1 legacy module — deleted during cleanup (2026-03-26).
contracts_from_size and check_pre_trade are inlined here so trader.py has
no external dependency on deleted code.
"""
from kalshi_client import KalshiClient
from logger import log_trade, log_activity, get_daily_exposure, send_telegram
import config


# ── Inlined from deleted risk.py (v1 legacy) ─────────────────────────────────

def contracts_from_size(size_dollars: float, price_cents: float) -> int:
    """Convert a dollar size into a contract count at the given price in cents."""
    if price_cents <= 0:
        return 0
    price_dollars = price_cents / 100
    contracts = int(size_dollars / price_dollars)
    return max(1, contracts)


def _legacy_kelly_fraction(prob: float, bet_price_cents: float) -> float:
    """Quarter-Kelly fraction (legacy, from risk.py). Used only by check_pre_trade fallback.

    Uses the same formula as bot/strategy.py: f = edge / (1 - win_prob),
    where edge = win_prob - (1 - win_prob) * (bet_price / (100 - bet_price)).
    """
    if prob <= 0 or prob >= 1 or bet_price_cents <= 0 or bet_price_cents >= 100:
        return 0
    edge = prob - (1 - prob) * (bet_price_cents / (100 - bet_price_cents))
    if edge <= 0:
        return 0
    f = edge / (1.0 - prob)
    return max(0, f * 0.25)


def _legacy_calculate_position_size(bankroll: float, opportunity: dict) -> float:
    """Legacy position sizing (from risk.py). Falls back to MAX_POSITION_SIZE cap."""
    win_prob = opportunity.get('win_prob', opportunity['noaa_prob'])
    bet_price = opportunity.get('bet_price', opportunity['yes_price'])
    fraction = _legacy_kelly_fraction(win_prob, bet_price)
    ideal_size = bankroll * fraction
    size = min(ideal_size, config.MAX_POSITION_SIZE)
    daily_used = get_daily_exposure()
    remaining_daily = config.MAX_DAILY_EXPOSURE - daily_used
    if remaining_daily <= 0:
        print(f'[Risk] Daily exposure limit reached (${config.MAX_DAILY_EXPOSURE}). No more trades today.')
        return 0
    size = min(size, remaining_daily)
    if size < 1.0:
        return 0
    return round(size, 2)


def check_pre_trade(opportunity: dict, bankroll: float):
    """
    Legacy pre-trade risk check (from risk.py). Used only when strategy_size is not provided.
    Returns: (approved: bool, reason: str, size: float, contracts: int)
    """
    size = _legacy_calculate_position_size(bankroll, opportunity)
    if size <= 0:
        return False, 'Daily exposure limit reached or Kelly says skip', 0, 0
    side = opportunity['side']
    price_cents = opportunity['yes_price'] if side == 'yes' else (100 - opportunity['yes_price'])
    contracts = contracts_from_size(size, price_cents)
    if contracts <= 0:
        return False, 'Position too small to be meaningful', 0, 0
    return True, 'Trade approved', size, contracts


# ─────────────────────────────────────────────────────────────────────────────


class Trader:
    def __init__(self, dry_run=True):
        self.client = KalshiClient()
        self.dry_run = dry_run  # If True, simulate trades without placing
        self.bankroll = self.client.get_balance()
        log_activity(f"Trader initialized. Balance: ${self.bankroll:.2f} | Dry run: {dry_run}")

    def refresh_balance(self):
        self.bankroll = self.client.get_balance()

    def execute_opportunity(self, opportunity):
        """
        Evaluate and execute a single trade opportunity.
        Returns True if trade was placed, False otherwise.
        """
        ticker = opportunity['ticker']
        side = opportunity['side']
        edge = opportunity['edge']

        log_activity(f"Evaluating: {ticker} | Edge: {edge:.1%} | Action: {opportunity['action']}")

        # ── Sizing: prefer strategy_size if provided; fall back to risk.py ───
        strategy_size = opportunity.get('strategy_size')
        if strategy_size:
            price_cents = opportunity['yes_price'] if side == 'yes' else (100 - opportunity['yes_price'])
            contracts = contracts_from_size(strategy_size, price_cents)
            if contracts <= 0:
                log_activity(f"  Skipped: strategy_size ${strategy_size:.2f} too small for {price_cents}¢ contract")
                return False
            size = strategy_size
            approved = True
            reason = f"strategy_size=${strategy_size:.2f}"
            log_activity(f"  Using strategy size ${size:.2f} (skipping risk.py re-sizing)")
        else:
            # Pre-trade risk check via risk.py (legacy fallback)
            log_activity(f'  [Trader] ⚠️ strategy_size missing for {ticker} — falling back to legacy sizing. Check scanner output.')
            send_telegram(f'⚠️ Legacy fallback triggered for {ticker}. strategy_size was not set by scanner — investigate.')
            approved, reason, size, contracts = check_pre_trade(opportunity, self.bankroll)
            if not approved:
                log_activity(f"  Skipped: {reason}")
                return False
            price_cents = opportunity['yes_price'] if side == 'yes' else (100 - opportunity['yes_price'])

        log_activity(f"  Placing {side.upper()} order: {contracts} contracts @ {price_cents}¢ (${size:.2f})")

        if self.dry_run:
            log_activity(f"  [DRY RUN] Would have placed order — skipping actual execution")
            log_trade(opportunity, size, contracts, {'dry_run': True, 'status': 'simulated'})
            return True

        try:
            result = self.client.place_order(
                ticker=ticker,
                side=side,
                price_cents=price_cents,
                count=contracts,
            )
            log_activity(f"  Order placed successfully: {result}")
            log_trade(opportunity, size, contracts, result)
            self.bankroll -= size  # Update local balance tracking
            return True

        except Exception as e:
            log_activity(f"  Order failed: {e}")
            return False

    def execute_all(self, opportunities):
        """Execute all opportunities in order of edge size."""
        if not opportunities:
            log_activity("No opportunities to execute.")
            return 0

        executed = 0
        for opp in opportunities:
            if self.execute_opportunity(opp):
                executed += 1

        log_activity(f"Executed {executed}/{len(opportunities)} opportunities.")
        return executed
