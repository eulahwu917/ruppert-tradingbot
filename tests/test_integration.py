# Run with: python -m pytest tests/test_integration.py -v
"""
Phase 3: Integration tests — hit the real Kalshi DEMO API (read-only).
These require network access and valid API credentials.
Do NOT include in pre-deploy gate.
"""
import pytest
from agents.data_analyst.kalshi_client import KalshiClient

pytestmark = pytest.mark.integration


def test_kalshi_client_initializes():
    client = KalshiClient()
    assert hasattr(client, 'get_markets')
    assert hasattr(client, 'get_market')


def test_kalshi_weather_markets_have_prices():
    client = KalshiClient()
    markets = client.get_markets('KXHIGHNY', status='open', limit=5)
    if not markets:
        pytest.skip('KXHIGHNY has no open markets — series may be inactive')
    for m in markets:
        assert m.get('yes_ask') is not None, f"yes_ask missing on {m.get('ticker')}"
        assert isinstance(m['yes_ask'], int), f"yes_ask not int on {m.get('ticker')}"
        assert m['yes_ask'] > 0, f"yes_ask <= 0 on {m.get('ticker')}"


def test_kalshi_get_market_returns_prices():
    client = KalshiClient()
    markets = client.get_markets('KXHIGHNY', status='open', limit=1)
    if not markets:
        pytest.skip('KXHIGHNY has no open markets — series may be inactive')
    ticker = markets[0]['ticker']
    market = client.get_market(ticker)
    assert market.get('yes_ask') is not None, 'yes_ask missing from get_market'
    assert market.get('status') is not None, 'status missing from get_market'


def test_kalshi_balance_readable():
    client = KalshiClient()
    balance = client.get_balance()
    assert isinstance(balance, (int, float))
    assert balance >= 0


def test_crypto_markets_have_prices_when_liquid():
    client = KalshiClient()
    markets = client.get_markets('KXBTC', status='open', limit=20)
    assert isinstance(markets, list)
    liquid = [m for m in markets if m.get('yes_ask') and m['yes_ask'] > 0]
    # Liquidity may be zero at rollover — just verify structure for liquid ones
    for m in liquid[:3]:
        assert isinstance(m.get('yes_ask'), int)
        # no_ask may be None if only one side of the orderbook has liquidity
        if m.get('no_ask') is not None:
            assert isinstance(m['no_ask'], int)
