"""
Kalshi API Client Wrapper
Uses the official kalshi_python_sync SDK.
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional
from kalshi_python_sync import Configuration, KalshiClient as _KalshiClient

# Ensure project root is on sys.path when running standalone
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

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
# Note: Kalshi uses the same endpoint for both demo and production.
# Demo mode is distinguished by account credentials, not by URL.
PROD_HOST = 'https://api.elections.kalshi.com/trade-api/v2'
DEMO_HOST = PROD_HOST  # Same endpoint; demo uses demo account credentials, not a different URL


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
        """Get account balance in dollars. Retries up to 3 times on transient errors."""
        delay = 1.0
        for attempt in range(3):
            try:
                result = self.client.get_balance()
                return result.balance / 100  # Kalshi returns cents
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"  [Balance] Error fetching balance: {e} — retrying in {delay:.1f}s (attempt {attempt+1}/3)")
                time.sleep(delay)
                delay *= 2

    def search_markets(self, keyword):
        """
        Search for open weather markets using the public API.
        No auth needed for market data — uses requests directly.
        Orderbook prices are enriched per-market (real bid/ask from orderbook endpoint).
        """
        import requests
        # Single source of truth: derive series list from openmeteo_client.CITIES
        # This ensures search_markets() and the weather signal engine stay in sync.
        from agents.ruppert.data_analyst.openmeteo_client import CITIES as _CITIES
        weather_series = list(_CITIES.keys())
        all_markets = []

        for series in weather_series:
            try:
                url = 'https://api.elections.kalshi.com/trade-api/v2/markets'
                params = {'series_ticker': series, 'status': 'open', 'limit': 30}
                resp = _get_with_retry(url, params=params, timeout=10)
                if resp is not None and resp.status_code == 200:
                    data = resp.json()
                    markets = data.get('markets', [])

                    # Enrich each market with real orderbook prices.
                    # The REST /markets list endpoint returns null for yes_ask/yes_bid/
                    # no_ask/no_bid; the orderbook endpoint (orderbook_fp) has the live
                    # bid/ask via no_dollars and yes_dollars (float-dollar fractions, 0–1).
                    # volume/open_interest come from the market list response directly.
                    for market in markets:
                        ticker = market.get('ticker', '')
                        if not ticker:
                            continue
                        try:
                            ob_url = f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook'
                            ob_resp = _get_with_retry(ob_url, timeout=5)
                            if ob_resp is None:
                                print(f"  [Warning] Orderbook fetch exhausted retries for {ticker} — bid/ask will be null")
                            elif ob_resp.status_code == 200:
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
                            else:
                                print(f"  [Warning] Orderbook fetch failed for {ticker}: HTTP {ob_resp.status_code} — bid/ask will be null")
                        except Exception as e:
                            print(f"  [Warning] Orderbook error for {ticker}: {e} — bid/ask will be null")
                        time.sleep(0.1)  # 20 req/sec rate limit

                    all_markets.extend(markets)
            except Exception as e:
                print(f"  [Warning] Could not fetch {series}: {e}")
            time.sleep(0.1)  # inter-series courtesy delay — 10 req/sec for series-level calls

        return all_markets

    def get_markets_metadata(self, series_ticker, status='open'):
        """
        Paginate through ALL markets for a series and return raw dicts
        WITHOUT orderbook enrichment. Fast: one list call per page.
        Each dict has floor_strike, ticker, yes_ask_dollars, no_ask_dollars, etc.
        """
        host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
        url = f"{host}/markets"
        all_markets = []
        cursor = None
        while True:
            params = {'series_ticker': series_ticker, 'status': status, 'limit': 100}
            if cursor:
                params['cursor'] = cursor
            resp = _get_with_retry(url, params=params, timeout=10)
            if resp is None or resp.status_code != 200:
                break
            data = resp.json()
            batch = data.get('markets', [])
            all_markets.extend(batch)
            cursor = data.get('cursor')
            if not cursor or not batch:
                break
            time.sleep(0.1)  # rate limit courtesy
        return all_markets

    def enrich_orderbook(self, market):
        """Enrich a single market dict with live orderbook bid/ask prices. Modifies in place."""
        ticker = market.get('ticker', '')
        if not ticker:
            return market
        try:
            host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
            ob_url = f"{host}/markets/{ticker}/orderbook"
            ob_resp = _get_with_retry(ob_url, timeout=5)
            if ob_resp is not None and ob_resp.status_code == 200:
                ob = ob_resp.json().get('orderbook_fp', {})
                no_bids  = ob.get('no_dollars', [])
                yes_bids = ob.get('yes_dollars', [])
                if no_bids:
                    best_no_bid = max(float(p) for p, v in no_bids)
                    market['no_bid']  = int(round(best_no_bid * 100))
                    market['yes_ask'] = 100 - market['no_bid']
                if yes_bids:
                    best_yes_bid = max(float(p) for p, v in yes_bids)
                    market['yes_bid'] = int(round(best_yes_bid * 100))
                    market['no_ask']  = 100 - market['yes_bid']
            else:
                print(f"  [Warning] Orderbook fetch failed for {ticker}: HTTP {ob_resp.status_code if ob_resp else 'timeout'}")
        except Exception as e:
            print(f"  [Warning] Orderbook error for {ticker}: {e}")
        time.sleep(0.1)
        return market

    def get_markets(self, series_ticker, status='open', limit=30):
        """
        Fetch markets for a series ticker via raw HTTP — bypasses SDK Pydantic deserialization.
        Returns a list of plain dicts enriched with live orderbook bid/ask prices.
        """
        url = f"{DEMO_HOST if self.environment == 'demo' else PROD_HOST}/markets"
        params = {'series_ticker': series_ticker, 'status': status, 'limit': limit}
        resp = _get_with_retry(url, params=params, timeout=10)
        if resp is None or resp.status_code != 200:
            return []
        markets = resp.json().get('markets', [])

        for market in markets:
            ticker = market.get('ticker', '')
            if not ticker:
                continue
            try:
                ob_url = f"{DEMO_HOST if self.environment == 'demo' else PROD_HOST}/markets/{ticker}/orderbook"
                ob_resp = _get_with_retry(ob_url, timeout=5)
                if ob_resp is not None and ob_resp.status_code == 200:
                    ob = ob_resp.json().get('orderbook_fp', {})
                    no_bids  = ob.get('no_dollars', [])
                    yes_bids = ob.get('yes_dollars', [])
                    if no_bids:
                        best_no_bid = max(float(p) for p, v in no_bids)
                        market['no_bid']  = int(round(best_no_bid * 100))
                        market['yes_ask'] = 100 - market['no_bid']
                    if yes_bids:
                        best_yes_bid = max(float(p) for p, v in yes_bids)
                        market['yes_bid'] = int(round(best_yes_bid * 100))
                        market['no_ask']  = 100 - market['yes_bid']
                else:
                    print(f"  [Warning] Orderbook fetch failed for {ticker}: HTTP {ob_resp.status_code if ob_resp else 'timeout'}")
            except Exception as e:
                print(f"  [Warning] Orderbook error for {ticker}: {e}")
            time.sleep(0.1)

        return markets

    def get_market(self, ticker):
        """Get a specific market by ticker via raw HTTP — bypasses SDK Pydantic deserialization."""
        return self._get_market_raw(ticker)

    def _get_market_raw(self, ticker):
        """Raw HTTP fetch for a single market, with orderbook enrichment."""
        host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
        url = f"{host}/markets/{ticker}"
        resp = _get_with_retry(url, timeout=10)
        if resp is None or resp.status_code != 200:
            return {}
        market = resp.json().get('market', {}) or {}
        if not market:
            return {}
        try:
            ob_url = f"{host}/markets/{ticker}/orderbook"
            ob_resp = _get_with_retry(ob_url, timeout=5)
            if ob_resp is not None and ob_resp.status_code == 200:
                ob = ob_resp.json().get('orderbook_fp', {})
                no_bids  = ob.get('no_dollars', [])
                yes_bids = ob.get('yes_dollars', [])
                if no_bids:
                    best_no_bid = max(float(p) for p, v in no_bids)
                    market['no_bid']  = int(round(best_no_bid * 100))
                    market['yes_ask'] = 100 - market['no_bid']
                if yes_bids:
                    best_yes_bid = max(float(p) for p, v in yes_bids)
                    market['yes_bid'] = int(round(best_yes_bid * 100))
                    market['no_ask']  = 100 - market['yes_bid']
        except Exception as e:
            print(f"  [Warning] Orderbook error for {ticker}: {e}")
        return market

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
            client_order_id=f"ruppert_{int(time.time() * 1000)}",
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
        try:
            result = self.client.get_positions()
            return result.market_positions or []
        except Exception:
            # SDK Pydantic deserialization fails when API returns None for StrictInt fields.
            # Fall back to raw HTTP request and return SimpleNamespace objects.
            return self._get_positions_raw()

    def _build_rest_auth_headers(self, method: str, path: str) -> dict:
        """Build RSA/PSS auth headers for direct REST calls.
        Uses same signing pattern as ws_feed._build_auth_headers().
        """
        import base64
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from pathlib import Path as _Path

        timestamp = str(int(time.time() * 1000))
        key_data = _Path(self.private_key_path).read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        msg = f"{timestamp}{method}{path}".encode()
        signature = private_key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        sig_b64 = base64.b64encode(signature).decode()
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    def _get_positions_raw(self):
        """Raw HTTP fallback for get_positions when SDK Pydantic deserialization fails.
        Retries up to 3 times on transient errors (mirrors get_balance/get_orders pattern).
        """
        import requests
        from types import SimpleNamespace
        host = DEMO_HOST if self.environment == 'demo' else PROD_HOST
        url = f"{host}/portfolio/positions"
        path = '/trade-api/v2/portfolio/positions'
        delay = 1.0
        for attempt in range(3):
            headers = self._build_rest_auth_headers('GET', path)
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                raw = resp.json().get('market_positions') or []
                positions = []
                for p in raw:
                    positions.append(SimpleNamespace(
                        ticker=p.get('ticker') or '',
                        position=int(p.get('position') or 0),
                        total_traded=int(p.get('total_traded') or 0),
                        market_exposure=int(p.get('market_exposure') or 0),
                        realized_pnl=int(p.get('realized_pnl') or 0),
                        fees_paid=int(p.get('fees_paid') or 0),
                    ))
                return positions
            except Exception as e:
                if attempt == 2:
                    print(f"  [Warning] _get_positions_raw failed after 3 attempts: {e}")
                    return []
                print(f"  [Warning] _get_positions_raw HTTP error: {e} — retrying in {delay:.1f}s (attempt {attempt+1}/3)")
                time.sleep(delay)
                delay *= 2

    def get_orders(self):
        """Get recent orders. Retries up to 3 times on transient errors."""
        delay = 1.0
        for attempt in range(3):
            try:
                result = self.client.get_orders()
                return result.orders or []
            except Exception as e:
                if attempt == 2:
                    print(f"  [Orders] All retries exhausted: {e}")
                    return []
                print(f"  [Orders] Error fetching orders: {e} — retrying in {delay:.1f}s (attempt {attempt+1}/3)")
                time.sleep(delay)
                delay *= 2


if __name__ == '__main__':
    print("Testing Kalshi connection...")
    client = KalshiClient()
    balance = client.get_balance()
    print(f"Balance: ${balance:.2f}")
    markets = client.search_markets('temperature')
    print(f"Found {len(markets)} weather markets")
    for m in markets[:5]:
        print(f"  - {m.get('ticker')}: {m.get('title')}")

