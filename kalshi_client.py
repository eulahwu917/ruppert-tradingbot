"""
Kalshi API Client Wrapper
Uses the official kalshi_python_sync SDK.
"""
import os
import time
from kalshi_python_sync import Configuration, KalshiClient as _KalshiClient

import config as cfg

# ---------------------------------------------------------------------------
# HTTP retry helper (handles 429 + transient 5xx)
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, params=None, headers=None, timeout=10, max_retries=3):
    """
    GET request with exponential backoff on 429 (rate limit) and 5xx errors.
    Returns the Response object on success, or None if all retries exhausted.
    """
    import requests
    delay = 1.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get('Retry-After', delay))
                print(f"  [RateLimit] 429 on {url} — waiting {retry_after:.1f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(retry_after)
                delay *= 2
                continue
            if resp.status_code >= 500:
                print(f"  [ServerError] HTTP {resp.status_code} on {url} — retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(delay)
                delay *= 2
                continue
            return resp
        except Exception as e:
            print(f"  [RequestError] {e} on {url} — retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})")
            time.sleep(delay)
            delay *= 2
    print(f"  [RequestError] All {max_retries} retries exhausted for {url}")
    return None


# API URLs
PROD_HOST = 'https://api.elections.kalshi.com/trade-api/v2'
DEMO_HOST = 'https://api.elections.kalshi.com/trade-api/v2'  # Same URL, demo uses demo account credentials


class KalshiClient:
    def __init__(self):
        self.api_key_id = cfg.get_api_key_id()
        self.private_key_path = cfg.get_private_key_path()
        self.environment = cfg.get_environment()

        # Read private key
        with open(self.private_key_path, 'r', encoding='utf-8') as f:
            private_key_pem = f.read()

        # Configure SDK
        host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
        configuration = Configuration(host=host)
        configuration.api_key_id = self.api_key_id
        configuration.private_key_pem = private_key_pem

        self.client = _KalshiClient(configuration)
        self.is_live = (self.environment == 'live')
        print(f"[Kalshi] Initialized in {self.environment.upper()} mode")
        if not self.is_live:
            print("[Kalshi] DEMO mode — all order methods are BLOCKED. Read-only API calls are active.")

    def get_balance(self):
        """Get account balance in dollars."""
        result = self.client.get_balance()
        return result.balance / 100  # Kalshi returns cents

    def search_markets(self, keyword):
        """
        Search for open weather markets using the public API.
        No auth needed for market data — uses requests directly.
        Orderbook prices are enriched per-market (real bid/ask from orderbook endpoint).
        """
        import requests
        weather_series = [
            # HIGH temp — original cities
            'KXHIGHNY', 'KXHIGHCHI', 'KXHIGHMIA', 'KXHIGHHOU', 'KXHIGHPHX',
            # HIGH temp — new cities (expanded 2026-03-13)
            'KXHIGHAUS',    # Austin
            'KXHIGHDEN',    # Denver
            'KXHIGHLAX',    # Los Angeles (LAX coords)
            'KXHIGHPHIL',   # Philadelphia
            'KXHIGHTMIN',   # Minneapolis
            'KXHIGHTDAL',   # Dallas
            'KXHIGHTDC',    # Washington DC
            'KXHIGHTLV',    # Las Vegas
            'KXHIGHTNOU',   # New Orleans (try KXHIGHTNOLA if this 404s)
            'KXHIGHTOKC',   # Oklahoma City
            'KXHIGHTSFO',   # San Francisco
            'KXHIGHTSEA',   # Seattle
            'KXHIGHTSATX',  # San Antonio
            'KXHIGHTATL',   # Atlanta
        ]
        all_markets = []

        for series in weather_series:
            try:
                url = 'https://api.elections.kalshi.com/trade-api/v2/markets'
                params = {'series_ticker': series, 'status': 'open', 'limit': 30}
                resp = _get_with_retry(url, params=params, timeout=10)
                if resp is not None and resp.status_code == 200:
                    data = resp.json()
                    markets = data.get('markets', [])

                    # Enrich each market with real orderbook prices
                    # (REST /markets endpoint returns null for bid/ask fields)
                    for market in markets:
                        ticker = market.get('ticker', '')
                        if not ticker:
                            continue
                        try:
                            ob_url = f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook'
                            ob_resp = _get_with_retry(ob_url, timeout=5)
                            if ob_resp is not None and ob_resp.status_code == 200:
                                ob = ob_resp.json().get('orderbook_fp', {})
                                no_bids  = ob.get('no_dollars', [])   # [[price_str, vol_str], ...]
                                yes_bids = ob.get('yes_dollars', [])
                                # Best NO bid = highest price someone will pay for NO
                                if no_bids:
                                    best_no_bid = max(float(p) for p, v in no_bids)
                                    market['no_bid']  = int(round(best_no_bid * 100))
                                    market['yes_ask'] = 100 - market['no_bid']  # implied
                                # Best YES bid = highest price someone will pay for YES
                                if yes_bids:
                                    best_yes_bid = max(float(p) for p, v in yes_bids)
                                    market['yes_bid'] = int(round(best_yes_bid * 100))
                                    market['no_ask']  = 100 - market['yes_bid']  # implied
                                if not no_bids and not yes_bids:
                                    print(f"  [Warning] Empty orderbook for {ticker} — bid/ask will be null")
                            elif ob_resp is not None:
                                print(f"  [Warning] Orderbook fetch failed for {ticker}: HTTP {ob_resp.status_code} — bid/ask will be null")
                        except Exception as e:
                            print(f"  [Warning] Orderbook error for {ticker}: {e} — bid/ask will be null")
                        time.sleep(0.05)  # 20 req/sec rate limit

                    all_markets.extend(markets)
            except Exception as e:
                print(f"  [Warning] Could not fetch {series}: {e}")

        return all_markets

    def get_market(self, ticker):
        """Get a specific market by ticker."""
        result = self.client.get_market(ticker)
        return result.market

    def _demo_block(self, method_name):
        """Called by order-placing methods in demo mode. Logs and returns a safe stub."""
        print(f"[Kalshi] ORDER BLOCKED — demo mode. No API call made. (method: {method_name})")
        return {"dry_run": True, "simulated": True, "environment": "demo"}

    def place_order(self, ticker, side, price_cents, count):
        """
        Place a limit order.
        side: 'yes' or 'no'
        price_cents: price in cents (e.g. 30 = 30c)
        count: number of contracts
        """
        if not self.is_live:
            return self._demo_block("place_order")
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
        if not self.is_live:
            return self._demo_block("sell_position")
        return self.client.create_order(
            ticker=ticker,
            client_order_id=f"ruppert_exit_{int(time.time() * 1000)}",
            type='limit',
            action='sell',
            side=side,
            count=count,
            yes_price=price_cents if side == 'yes' else (100 - price_cents),
        )

    def cancel_order(self, order_id):
        """Cancel an open order."""
        if not self.is_live:
            return self._demo_block("cancel_order")
        return self.client.cancel_order(order_id=order_id)

    def amend_order(self, order_id, **kwargs):
        """Amend an open order (price or count)."""
        if not self.is_live:
            return self._demo_block("amend_order")
        return self.client.amend_order(order_id=order_id, **kwargs)

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
