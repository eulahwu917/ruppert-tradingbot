"""
ws/connection.py — Kalshi WebSocket Client
Persistent connection with automatic reconnection.
Subscribes to ticker (price updates) and fill (order fills) channels.
"""
import asyncio
import json
import time
import logging
import base64
from typing import Callable, Optional
from pathlib import Path

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    websockets = None
    ConnectionClosed = Exception

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)

# Kalshi WebSocket endpoints
WS_URL_DEMO = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WS_URL_PROD = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# Reconnection settings
RECONNECT_DELAY_INITIAL = 1.0   # seconds
RECONNECT_DELAY_MAX = 60.0      # max backoff
HEARTBEAT_INTERVAL = 30.0       # Kalshi requires ping every 30s


class KalshiWebSocket:
    """
    Async WebSocket client for Kalshi real-time data.
    
    Usage:
        ws = KalshiWebSocket(api_key, private_key, environment='demo')
        await ws.connect()
        await ws.subscribe_ticker(['KXBTC-26MAR28-B87500', ...])
        await ws.subscribe_fills()
        
        async for msg in ws.messages():
            handle(msg)
    """
    
    def __init__(
        self,
        api_key_id: str,
        private_key_path: str,
        environment: str = 'demo',
        on_ticker: Optional[Callable] = None,
        on_fill: Optional[Callable] = None,
        on_settlement: Optional[Callable] = None,
    ):
        if not WS_AVAILABLE:
            raise ImportError("websockets package not installed. Run: pip install websockets")
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography package not installed. Run: pip install cryptography")
        
        self.api_key_id = api_key_id
        self.private_key_path = private_key_path
        self.environment = environment
        self.url = WS_URL_DEMO if environment == 'demo' else WS_URL_PROD
        
        # Callbacks
        self.on_ticker = on_ticker
        self.on_fill = on_fill
        self.on_settlement = on_settlement
        
        # State
        self._ws = None
        self._connected = False
        self._subscriptions: set = set()
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._reconnect_delay = RECONNECT_DELAY_INITIAL
    
    def _generate_auth_headers(self) -> dict:
        """Generate authentication headers for Kalshi WS connection."""
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        path = "/trade-api/ws/v2"
        
        # Load private key
        key_data = Path(self.private_key_path).read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        
        # Sign: timestamp + method + path (RSA-PSS required by Kalshi API)
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
    
    async def connect(self) -> bool:
        """Establish WebSocket connection with authentication."""
        try:
            headers = self._generate_auth_headers()
            self._ws = await websockets.connect(
                self.url,
                additional_headers=headers,
                ping_interval=None,   # Kalshi sends server-side pings every 10s; client pings cause false 1011 disconnects
                ping_timeout=None,
            )
            self._connected = True
            self._reconnect_delay = RECONNECT_DELAY_INITIAL
            logger.info(f"WebSocket connected to {self.url}")
            
            # Re-subscribe after reconnect
            if self._subscriptions:
                await self._resubscribe()
            
            return True
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._connected = False
            return False
    
    async def _resubscribe(self):
        """Re-establish subscriptions after reconnect."""
        for sub in list(self._subscriptions):
            try:
                msg = json.loads(sub)
                await self._send(msg)
            except Exception as e:
                logger.warning(f"Failed to resubscribe: {e}")
    
    async def _send(self, message: dict):
        """Send JSON message to WebSocket."""
        if self._ws and self._connected:
            await self._ws.send(json.dumps(message))
    
    async def subscribe_ticker(self, tickers: list[str]):
        """Subscribe to price updates for a list of tickers."""
        if not tickers:
            return
        
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
                "market_tickers": tickers,
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info(f"Subscribed to ticker channel for {len(tickers)} markets")
    
    async def subscribe_fills(self):
        """Subscribe to order fill notifications."""
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["fill"],
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info("Subscribed to fill channel")
    
    async def subscribe_orderbook(self, tickers: list[str]):
        """Subscribe to orderbook updates (L2 depth)."""
        if not tickers:
            return
        
        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": tickers,
            }
        }
        self._subscriptions.add(json.dumps(msg))
        await self._send(msg)
        logger.info(f"Subscribed to orderbook channel for {len(tickers)} markets")
    
    async def messages(self):
        """Async generator yielding parsed WebSocket messages."""
        while True:
            try:
                if not self._connected:
                    await self._reconnect()
                
                msg = await self._ws.recv()
                data = json.loads(msg)
                
                # Route to callbacks
                msg_type = data.get("type")
                if msg_type == "ticker" and self.on_ticker:
                    await self.on_ticker(data)
                elif msg_type == "fill" and self.on_fill:
                    await self.on_fill(data)
                elif msg_type == "orderbook_delta":
                    pass  # Handle if needed
                
                yield data
                
            except ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
                self._connected = False
                await self._reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self._connected = False
                await asyncio.sleep(1)
    
    async def _reconnect(self):
        """Reconnect with exponential backoff."""
        while not self._connected:
            logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
            await asyncio.sleep(self._reconnect_delay)
            
            if await self.connect():
                break
            
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                RECONNECT_DELAY_MAX
            )
    
    async def close(self):
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._connected = False
            logger.info("WebSocket closed")
    
    @property
    def connected(self) -> bool:
        return self._connected


# ─────────────────────────────── Self-test ───────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import config
    
    async def test_connection():
        print("=== WebSocket Connection Test ===\n")
        
        ws = KalshiWebSocket(
            api_key_id=config.get_api_key_id(),
            private_key_path=config.get_private_key_path(),
            environment=config.get_environment(),
        )
        
        print(f"Connecting to {ws.url}...")
        connected = await ws.connect()
        
        if connected:
            print("✓ Connected successfully!")
            
            # Test subscription
            await ws.subscribe_ticker(['KXBTC-26MAR28-B87500'])
            print("✓ Subscribed to test ticker")
            
            # Read a few messages
            print("\nListening for messages (5 seconds)...")
            try:
                async for msg in asyncio.wait_for(ws.messages(), timeout=5.0):
                    print(f"  Received: {msg.get('type', 'unknown')}")
            except asyncio.TimeoutError:
                print("  (timeout - no messages received)")
            
            await ws.close()
            print("\n✓ Connection closed cleanly")
        else:
            print("✗ Connection failed")
    
    asyncio.run(test_connection())
