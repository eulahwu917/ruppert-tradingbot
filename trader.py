"""
Trade Executor
Handles order placement with pre-trade checks.
"""
from kalshi_client import KalshiClient
from risk import check_pre_trade, contracts_from_size
from logger import log_trade, log_activity
import config


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
