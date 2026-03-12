"""
Kalshi API Client Wrapper
Uses the official kalshi_python_sync SDK.
"""
import os
import time
from kalshi_python_sync import Configuration, KalshiClient as _KalshiClient

import config as cfg

# API URLs
PROD_HOST = 'https://api.elections.kalshi.com/trade-api/v2'
DEMO_HOST = 'https://api.elections.kalshi.com/trade-api/v2'  # Same URL, demo uses demo account credentials


class KalshiClient:
    def __init__(self):
        self.api_key_id = cfg.get_api_key_id()
        self.private_key_path = cfg.get_private_key_path()
        self.environment = cfg.get_environment()

        # Read private key
        with open(self.private_key_path, 'r') as f:
            private_key_pem = f.read()

        # Configure SDK
        host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
        configuration = Configuration(host=host)
        configuration.api_key_id = self.api_key_id
        configuration.private_key_pem = private_key_pem

        self.client = _KalshiClient(configuration)
        print(f"[Kalshi] Initialized in {self.environment.upper()} mode")

    def get_balance(self):
        """Get account balance in dollars."""
        result = self.client.get_balance()
        return result.balance / 100  # Kalshi returns cents

    def search_markets(self, keyword):
        """
        Search for open weather markets using the public API.
        No auth needed for market data — uses requests directly.
        """
        import requests
        weather_series = ['KXHIGHNY', 'KXHIGHLA', 'KXHIGHCHI', 'KXHIGHHOU', 'KXHIGHMIA', 'KXHIGHPHX']
        all_markets = []

        for series in weather_series:
            try:
                url = f'https://api.elections.kalshi.com/trade-api/v2/markets'
                params = {'series_ticker': series, 'status': 'open', 'limit': 20}
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    markets = data.get('markets', [])
                    all_markets.extend(markets)
            except Exception as e:
                print(f"  [Warning] Could not fetch {series}: {e}")

        return all_markets

    def get_market(self, ticker):
        """Get a specific market by ticker."""
        result = self.client.get_market(ticker)
        return result.market

    def place_order(self, ticker, side, price_cents, count):
        """
        Place a limit order.
        side: 'yes' or 'no'
        price_cents: price in cents (e.g. 30 = 30c)
        count: number of contracts
        """
        return self.client.create_order(
            ticker=ticker,
            client_order_id=f"ruppert_{int(time.time())}",
            type='limit',
            action='buy',
            side=side,
            count=count,
            yes_price=price_cents if side == 'yes' else (100 - price_cents),
        )

    def sell_position(self, ticker, side, price_cents, count):
        """
        Sell (exit) an existing position.
        side: 'yes' or 'no' — the side you HOLD (you're selling it)
        price_cents: limit price to sell at
        count: number of contracts to sell
        """
        return self.client.create_order(
            ticker=ticker,
            client_order_id=f"ruppert_exit_{int(time.time() * 1000)}",
            type='limit',
            action='sell',
            side=side,
            count=count,
            yes_price=price_cents if side == 'yes' else (100 - price_cents),
        )

    def get_positions(self):
        """Get current open positions."""
        result = self.client.get_positions()
        return result.market_positions or []

    def get_orders(self):
        """Get recent orders."""
        result = self.client.get_orders()
        return result.orders or []


if __name__ == '__main__':
    print("Testing Kalshi connection...")
    client = KalshiClient()
    balance = client.get_balance()
    print(f"Balance: ${balance:.2f}")
    markets = client.search_markets('temperature')
    print(f"Found {len(markets)} weather markets")
    for m in markets[:5]:
        print(f"  - {m.ticker}: {m.title}")
