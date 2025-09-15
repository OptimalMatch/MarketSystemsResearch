"""
Ultra-fast WebSocket data feed server
Distributes market data from the matching engine with minimal latency
"""

import asyncio
import json
import time
import msgpack
import websockets
from websockets import WebSocketServerProtocol
from typing import Dict, Set, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
from collections import defaultdict, deque
import sys
import os

# Add matching engine to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from matching_engine.ultra_fast_engine import UltraFastMatchingEngine

class MessageType(Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    ORDERBOOK = "orderbook"
    TRADE = "trade"
    TICKER = "ticker"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

class Channel(Enum):
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    TICKER = "ticker"
    ALL = "all"

@dataclass
class Subscription:
    client_id: str
    channel: Channel
    symbol: str
    depth: int = 20

@dataclass
class MarketDataMessage:
    type: MessageType
    channel: Channel
    symbol: str
    data: Any
    timestamp: float = None
    sequence: int = 0

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

class WebSocketDataFeed:
    """
    High-performance WebSocket server for market data distribution
    Features:
    - Binary protocol support (MessagePack)
    - Differential order book updates
    - Subscription management
    - Automatic reconnection handling
    """

    def __init__(self,
                 host: str = "0.0.0.0",
                 port: int = 13765,
                 use_binary: bool = True):

        self.host = host
        self.port = port
        self.use_binary = use_binary

        # Client management
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        self.subscriptions: Dict[str, Set[Subscription]] = defaultdict(set)
        self.client_subscriptions: Dict[str, Set[str]] = defaultdict(set)

        # Market data cache
        self.orderbook_cache: Dict[str, dict] = {}
        self.last_trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.ticker_cache: Dict[str, dict] = {}

        # Sequence numbers for message ordering
        self.sequence_numbers: Dict[str, int] = defaultdict(int)

        # Statistics
        self.total_messages_sent = 0
        self.total_bytes_sent = 0
        self.connection_count = 0

        # Matching engines (one per symbol)
        self.engines: Dict[str, UltraFastMatchingEngine] = {}

        # Initialize default symbols
        self._initialize_symbols()

    def _initialize_symbols(self):
        """Initialize matching engines for default symbols"""
        symbols = ["DEC/USD", "BTC/USD", "ETH/USD", "DEC/BTC"]
        for symbol in symbols:
            self.engines[symbol] = UltraFastMatchingEngine(symbol)
            self.orderbook_cache[symbol] = {'bids': [], 'asks': []}

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """Handle new WebSocket connection"""
        client_id = str(uuid.uuid4())
        self.clients[client_id] = websocket
        self.connection_count += 1

        print(f"Client {client_id} connected from {websocket.remote_address}")

        try:
            # Send welcome message
            await self.send_welcome(websocket, client_id)

            # Handle messages
            async for message in websocket:
                await self.handle_message(client_id, message)

        except websockets.exceptions.ConnectionClosed:
            print(f"Client {client_id} disconnected")

        finally:
            # Clean up
            await self.handle_disconnection(client_id)

    async def send_welcome(self, websocket: WebSocketServerProtocol, client_id: str):
        """Send welcome message to new client"""
        welcome = {
            'type': 'welcome',
            'client_id': client_id,
            'timestamp': time.time(),
            'symbols': list(self.engines.keys()),
            'protocol': 'binary' if self.use_binary else 'json'
        }

        await self.send_to_client(websocket, welcome)

    async def handle_message(self, client_id: str, message: Any):
        """Process incoming message from client"""
        try:
            # Parse message
            if self.use_binary:
                data = msgpack.unpackb(message, raw=False)
            else:
                data = json.loads(message)

            msg_type = data.get('type')

            if msg_type == MessageType.SUBSCRIBE.value:
                await self.handle_subscription(client_id, data)

            elif msg_type == MessageType.UNSUBSCRIBE.value:
                await self.handle_unsubscription(client_id, data)

            elif msg_type == MessageType.HEARTBEAT.value:
                await self.handle_heartbeat(client_id)

            else:
                await self.send_error(client_id, f"Unknown message type: {msg_type}")

        except Exception as e:
            await self.send_error(client_id, str(e))

    async def handle_subscription(self, client_id: str, data: dict):
        """Handle subscription request"""
        channel = data.get('channel')
        symbol = data.get('symbol')
        depth = data.get('depth', 20)

        if not channel or not symbol:
            await self.send_error(client_id, "Missing channel or symbol")
            return

        # Validate symbol
        if symbol not in self.engines:
            await self.send_error(client_id, f"Unknown symbol: {symbol}")
            return

        # Create subscription
        sub = Subscription(
            client_id=client_id,
            channel=Channel(channel),
            symbol=symbol,
            depth=depth
        )

        # Add to subscriptions
        sub_key = f"{channel}:{symbol}"
        self.subscriptions[sub_key].add(client_id)
        self.client_subscriptions[client_id].add(sub_key)

        # Send initial snapshot
        await self.send_initial_snapshot(client_id, channel, symbol, depth)

        # Confirm subscription
        await self.send_to_client(self.clients[client_id], {
            'type': 'subscribed',
            'channel': channel,
            'symbol': symbol,
            'timestamp': time.time()
        })

    async def handle_unsubscription(self, client_id: str, data: dict):
        """Handle unsubscription request"""
        channel = data.get('channel')
        symbol = data.get('symbol')

        sub_key = f"{channel}:{symbol}"

        if sub_key in self.subscriptions:
            self.subscriptions[sub_key].discard(client_id)

        if client_id in self.client_subscriptions:
            self.client_subscriptions[client_id].discard(sub_key)

        # Confirm unsubscription
        await self.send_to_client(self.clients[client_id], {
            'type': 'unsubscribed',
            'channel': channel,
            'symbol': symbol,
            'timestamp': time.time()
        })

    async def handle_heartbeat(self, client_id: str):
        """Handle heartbeat message"""
        await self.send_to_client(self.clients[client_id], {
            'type': MessageType.HEARTBEAT.value,
            'timestamp': time.time()
        })

    async def handle_disconnection(self, client_id: str):
        """Clean up after client disconnection"""
        # Remove from clients
        if client_id in self.clients:
            del self.clients[client_id]

        # Remove all subscriptions
        for sub_key in list(self.client_subscriptions.get(client_id, [])):
            if sub_key in self.subscriptions:
                self.subscriptions[sub_key].discard(client_id)

        # Clean up client subscriptions
        if client_id in self.client_subscriptions:
            del self.client_subscriptions[client_id]

    async def send_initial_snapshot(self, client_id: str, channel: str,
                                   symbol: str, depth: int):
        """Send initial data snapshot to new subscriber"""
        if channel == Channel.ORDERBOOK.value:
            # Send order book snapshot
            engine = self.engines[symbol]
            snapshot = engine.get_order_book_snapshot(depth)

            await self.send_to_client(self.clients[client_id], {
                'type': MessageType.ORDERBOOK.value,
                'channel': channel,
                'symbol': symbol,
                'snapshot': True,
                'data': snapshot,
                'timestamp': time.time()
            })

        elif channel == Channel.TRADES.value:
            # Send recent trades
            trades = list(self.last_trades[symbol])

            await self.send_to_client(self.clients[client_id], {
                'type': MessageType.TRADE.value,
                'channel': channel,
                'symbol': symbol,
                'data': trades,
                'timestamp': time.time()
            })

        elif channel == Channel.TICKER.value:
            # Send ticker data
            ticker = self.ticker_cache.get(symbol, {})

            await self.send_to_client(self.clients[client_id], {
                'type': MessageType.TICKER.value,
                'channel': channel,
                'symbol': symbol,
                'data': ticker,
                'timestamp': time.time()
            })

    async def broadcast_orderbook_update(self, symbol: str, update: dict):
        """Broadcast order book update to subscribers"""
        sub_key = f"{Channel.ORDERBOOK.value}:{symbol}"
        subscribers = self.subscriptions.get(sub_key, set())

        if not subscribers:
            return

        # Increment sequence number
        self.sequence_numbers[symbol] += 1

        message = {
            'type': MessageType.ORDERBOOK.value,
            'channel': Channel.ORDERBOOK.value,
            'symbol': symbol,
            'sequence': self.sequence_numbers[symbol],
            'data': update,
            'timestamp': time.time()
        }

        # Broadcast to all subscribers
        await self.broadcast_to_subscribers(subscribers, message)

    async def broadcast_trade(self, symbol: str, trade: dict):
        """Broadcast trade to subscribers"""
        # Add to trade cache
        self.last_trades[symbol].append(trade)

        # Broadcast to trade channel subscribers
        sub_key = f"{Channel.TRADES.value}:{symbol}"
        subscribers = self.subscriptions.get(sub_key, set())

        if subscribers:
            message = {
                'type': MessageType.TRADE.value,
                'channel': Channel.TRADES.value,
                'symbol': symbol,
                'data': trade,
                'timestamp': time.time()
            }

            await self.broadcast_to_subscribers(subscribers, message)

        # Update ticker
        await self.update_ticker(symbol, trade)

    async def update_ticker(self, symbol: str, trade: dict):
        """Update and broadcast ticker data"""
        # Update ticker cache
        if symbol not in self.ticker_cache:
            self.ticker_cache[symbol] = {
                'last': 0,
                'volume_24h': 0,
                'high_24h': 0,
                'low_24h': float('inf'),
                'bid': 0,
                'ask': 0
            }

        ticker = self.ticker_cache[symbol]
        ticker['last'] = trade['price']

        # Get current best bid/ask
        engine = self.engines[symbol]
        snapshot = engine.get_order_book_snapshot(1)
        if snapshot['bids']:
            ticker['bid'] = snapshot['bids'][0][0]
        if snapshot['asks']:
            ticker['ask'] = snapshot['asks'][0][0]

        # Broadcast to ticker subscribers
        sub_key = f"{Channel.TICKER.value}:{symbol}"
        subscribers = self.subscriptions.get(sub_key, set())

        if subscribers:
            message = {
                'type': MessageType.TICKER.value,
                'channel': Channel.TICKER.value,
                'symbol': symbol,
                'data': ticker,
                'timestamp': time.time()
            }

            await self.broadcast_to_subscribers(subscribers, message)

    async def broadcast_to_subscribers(self, subscribers: Set[str], message: dict):
        """Broadcast message to a set of subscribers"""
        # Prepare message once
        if self.use_binary:
            data = msgpack.packb(message)
        else:
            data = json.dumps(message)

        # Send to all subscribers concurrently
        tasks = []
        for client_id in subscribers:
            if client_id in self.clients:
                websocket = self.clients[client_id]
                tasks.append(self.send_raw(websocket, data))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Update statistics
        self.total_messages_sent += len(subscribers)
        self.total_bytes_sent += len(data) * len(subscribers)

    async def send_to_client(self, websocket: WebSocketServerProtocol, message: dict):
        """Send message to specific client"""
        try:
            if self.use_binary:
                data = msgpack.packb(message)
                await websocket.send(data)
            else:
                data = json.dumps(message)
                await websocket.send(data)

            self.total_messages_sent += 1
            self.total_bytes_sent += len(data)

        except Exception as e:
            print(f"Error sending to client: {e}")

    async def send_raw(self, websocket: WebSocketServerProtocol, data: bytes):
        """Send raw data to websocket"""
        try:
            await websocket.send(data)
        except Exception:
            pass  # Client disconnected

    async def send_error(self, client_id: str, error_message: str):
        """Send error message to client"""
        if client_id in self.clients:
            await self.send_to_client(self.clients[client_id], {
                'type': MessageType.ERROR.value,
                'message': error_message,
                'timestamp': time.time()
            })

    async def simulate_market_activity(self):
        """Simulate market activity for testing"""
        print("Starting market simulation...")

        while True:
            # Generate random orders for each symbol
            for symbol, engine in self.engines.items():
                # Place some orders
                for _ in range(10):
                    import random

                    side = random.choice(['buy', 'sell'])
                    price = 100.0 + random.uniform(-5, 5)
                    quantity = random.uniform(0.1, 10.0)

                    order_id, trades = engine.place_order(side, price, quantity)

                    # Broadcast trades
                    for trade in trades:
                        await self.broadcast_trade(symbol, trade)

                # Broadcast order book update
                snapshot = engine.get_order_book_snapshot(20)
                await self.broadcast_orderbook_update(symbol, snapshot)

            await asyncio.sleep(0.1)  # 10 updates per second

    def get_stats(self) -> dict:
        """Get server statistics"""
        return {
            'active_connections': len(self.clients),
            'total_subscriptions': sum(len(subs) for subs in self.subscriptions.values()),
            'messages_sent': self.total_messages_sent,
            'bytes_sent': self.total_bytes_sent,
            'symbols': list(self.engines.keys())
        }

    async def start(self):
        """Start the WebSocket server"""
        print(f"Starting WebSocket server on {self.host}:{self.port}")
        print(f"Protocol: {'Binary (MessagePack)' if self.use_binary else 'JSON'}")

        # Start market simulation in background
        asyncio.create_task(self.simulate_market_activity())

        # Start WebSocket server
        async with websockets.serve(self.handle_connection, self.host, self.port):
            print(f"WebSocket server running on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever


# Test client for development
async def test_client():
    """Test WebSocket client"""
    uri = "ws://localhost:13765"

    async with websockets.connect(uri) as websocket:
        print("Connected to server")

        # Subscribe to DEC/USD orderbook
        await websocket.send(json.dumps({
            'type': 'subscribe',
            'channel': 'orderbook',
            'symbol': 'DEC/USD',
            'depth': 10
        }))

        # Subscribe to DEC/USD trades
        await websocket.send(json.dumps({
            'type': 'subscribe',
            'channel': 'trades',
            'symbol': 'DEC/USD'
        }))

        # Subscribe to DEC/USD ticker
        await websocket.send(json.dumps({
            'type': 'subscribe',
            'channel': 'ticker',
            'symbol': 'DEC/USD'
        }))

        # Listen for messages
        message_count = 0
        start_time = time.time()

        async for message in websocket:
            data = json.loads(message)
            message_count += 1

            # Print first few messages
            if message_count <= 5:
                print(f"Received: {data['type']} for {data.get('symbol', 'N/A')}")

            # Print statistics every 100 messages
            if message_count % 100 == 0:
                elapsed = time.time() - start_time
                rate = message_count / elapsed
                print(f"Received {message_count} messages, Rate: {rate:.1f} msg/sec")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "client":
        # Run test client
        asyncio.run(test_client())
    else:
        # Run server
        server = WebSocketDataFeed()
        asyncio.run(server.start())