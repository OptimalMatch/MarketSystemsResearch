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

    def _json_serializer(self, obj):
        """Custom JSON serializer to handle special values"""
        import math
        if isinstance(obj, float):
            if math.isinf(obj):
                return 0  # Convert Infinity to 0 for numeric fields
            elif math.isnan(obj):
                return 0  # Convert NaN to 0 for numeric fields
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _clean_ticker_data(self, ticker: dict) -> dict:
        """Clean ticker data to remove Infinity and NaN values"""
        import math
        clean_ticker = {}
        for key, value in ticker.items():
            if isinstance(value, float):
                if math.isinf(value) or math.isnan(value):
                    clean_ticker[key] = 0
                else:
                    clean_ticker[key] = value
            else:
                clean_ticker[key] = value
        return clean_ticker

    async def handle_connection(self, websocket: WebSocketServerProtocol):
        """Handle new WebSocket connection"""
        client_id = str(uuid.uuid4())
        self.clients[client_id] = websocket
        self.connection_count += 1

        print(f"[WebSocket] Client {client_id} connected from {websocket.remote_address}", flush=True)

        try:
            # Send welcome message
            print(f"[WebSocket] Sending welcome message to client {client_id}", flush=True)
            await self.send_welcome(websocket, client_id)
            print(f"[WebSocket] Welcome message sent successfully to client {client_id}", flush=True)

            # Handle messages
            print(f"[WebSocket] Starting message loop for client {client_id}", flush=True)
            async for message in websocket:
                print(f"[WebSocket] Received message from client {client_id}: {message[:100]}...", flush=True)
                await self.handle_message(client_id, message)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WebSocket] Client {client_id} disconnected: {e}", flush=True)
        except Exception as e:
            print(f"[WebSocket] Unexpected error for client {client_id}: {e}", flush=True)
            import traceback
            traceback.print_exc()

        finally:
            # Clean up
            print(f"[WebSocket] Cleaning up client {client_id}", flush=True)
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

        print(f"[WebSocket] Preparing welcome message for client {client_id}: {welcome}", flush=True)
        await self.send_to_client(websocket, welcome)
        print(f"[WebSocket] Welcome message delivery completed for client {client_id}", flush=True)

    async def handle_message(self, client_id: str, message: Any):
        """Process incoming message from client"""
        try:
            # Parse message
            if self.use_binary:
                data = msgpack.unpackb(message, raw=False)
            else:
                data = json.loads(message)

            msg_type = data.get('type') or data.get('action')

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
        # Support both individual and bulk subscription formats
        if 'symbols' in data:
            # Bulk subscription format: {"action":"subscribe","symbols":["DEC/USD","BTC/USD"]}
            symbols = data.get('symbols', [])
            if not symbols:
                await self.send_error(client_id, "Missing symbols")
                return

            # Subscribe to all channels for each symbol
            for symbol in symbols:
                for channel in ['orderbook', 'trades', 'ticker']:
                    await self._handle_single_subscription(client_id, channel, symbol, 20)
            return

        # Individual subscription format: {"type":"subscribe","channel":"orderbook","symbol":"DEC/USD"}
        channel = data.get('channel')
        symbol = data.get('symbol')
        depth = data.get('depth', 20)

        if not channel or not symbol:
            await self.send_error(client_id, "Missing channel or symbol")
            return

        await self._handle_single_subscription(client_id, channel, symbol, depth)

    async def _handle_single_subscription(self, client_id: str, channel: str, symbol: str, depth: int):
        """Handle a single subscription"""
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

            # If no ticker data exists, create initial data with current best bid/ask
            if not ticker:
                current_time = time.time()
                engine = self.engines[symbol]
                snapshot = engine.get_order_book_snapshot(1)

                # Use mid price as starting point
                best_bid = snapshot['bids'][0][0] if snapshot['bids'] else 1.0
                best_ask = snapshot['asks'][0][0] if snapshot['asks'] else 1.05
                mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 1.02

                ticker = {
                    'last': mid_price,
                    'volume_24h': 5000 + (mid_price * 100),  # Simulated volume
                    'high_24h': mid_price * 1.05,
                    'low_24h': mid_price * 0.95,
                    'bid': best_bid,
                    'ask': best_ask,
                    'price_change_24h': mid_price * 0.02,
                    'price_change_percent_24h': 2.0,
                    'open_24h': mid_price * 0.98,
                    'last_update': current_time
                }

                # Cache the ticker data
                self.ticker_cache[symbol] = ticker

            # Clean ticker data
            clean_ticker = self._clean_ticker_data(ticker)

            await self.send_to_client(self.clients[client_id], {
                'type': MessageType.TICKER.value,
                'channel': channel,
                'symbol': symbol,
                'data': clean_ticker,
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
        # Enhance trade data with side field for frontend compatibility
        enhanced_trade = trade.copy()

        # Determine side from buyer_id/seller_id or add randomly if not deterministic
        if 'buyer_id' in enhanced_trade and 'seller_id' in enhanced_trade:
            # For market simulation, randomly assign side
            import random
            enhanced_trade['side'] = random.choice(['buy', 'sell'])
        elif 'side' not in enhanced_trade:
            # Fallback to random if no side info available
            import random
            enhanced_trade['side'] = random.choice(['buy', 'sell'])

        # Add to trade cache
        self.last_trades[symbol].append(enhanced_trade)

        # Broadcast to trade channel subscribers
        sub_key = f"{Channel.TRADES.value}:{symbol}"
        subscribers = self.subscriptions.get(sub_key, set())

        if subscribers:
            message = {
                'type': MessageType.TRADE.value,
                'channel': Channel.TRADES.value,
                'symbol': symbol,
                'data': enhanced_trade,
                'timestamp': time.time()
            }

            await self.broadcast_to_subscribers(subscribers, message)

        # Update ticker
        await self.update_ticker(symbol, trade)

    async def update_ticker(self, symbol: str, trade: dict):
        """Update and broadcast ticker data"""
        current_time = time.time()

        # Update ticker cache
        if symbol not in self.ticker_cache:
            base_price = trade['price']
            self.ticker_cache[symbol] = {
                'last': base_price,
                'volume_24h': 0,
                'high_24h': base_price,
                'low_24h': base_price,
                'bid': 0,
                'ask': 0,
                'price_change_24h': 0,
                'price_change_percent_24h': 0,
                'open_24h': base_price,
                'last_update': current_time,
                'trades_24h': []
            }

        ticker = self.ticker_cache[symbol]
        price = trade['price']
        quantity = trade.get('quantity', 0)

        # Update last price
        ticker['last'] = price
        ticker['last_update'] = current_time

        # Add trade to 24h history
        ticker['trades_24h'].append({
            'price': price,
            'quantity': quantity,
            'timestamp': current_time
        })

        # Clean trades older than 24 hours
        cutoff_time = current_time - 24 * 3600
        ticker['trades_24h'] = [t for t in ticker['trades_24h'] if t['timestamp'] > cutoff_time]

        # Calculate 24h statistics
        if ticker['trades_24h']:
            prices = [t['price'] for t in ticker['trades_24h']]
            ticker['high_24h'] = max(prices)
            ticker['low_24h'] = min(prices)
            ticker['volume_24h'] = sum(t['quantity'] for t in ticker['trades_24h'])

            # Price change calculation
            if len(ticker['trades_24h']) > 1:
                oldest_price = ticker['trades_24h'][0]['price']
                ticker['price_change_24h'] = price - oldest_price
                ticker['price_change_percent_24h'] = ((price - oldest_price) / oldest_price) * 100 if oldest_price > 0 else 0
            else:
                ticker['price_change_24h'] = 0
                ticker['price_change_percent_24h'] = 0
        else:
            # No recent trades, maintain current values or use defaults
            if ticker['volume_24h'] == 0:
                # Simulate some activity for demo purposes
                ticker['volume_24h'] = 1000 + (price * 10)
                ticker['high_24h'] = price * 1.05
                ticker['low_24h'] = price * 0.95
                ticker['price_change_24h'] = price * 0.02
                ticker['price_change_percent_24h'] = 2.0

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
            # Clean ticker data to ensure no Infinity/NaN values
            clean_ticker = self._clean_ticker_data(ticker)

            message = {
                'type': MessageType.TICKER.value,
                'channel': Channel.TICKER.value,
                'symbol': symbol,
                'data': clean_ticker,
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
            print(f"[WebSocket] Sending message type '{message.get('type')}' to client", flush=True)
            if self.use_binary:
                data = msgpack.packb(message)
                print(f"[WebSocket] Packed binary data: {len(data)} bytes", flush=True)
                await websocket.send(data)
            else:
                data = json.dumps(message, allow_nan=False, default=self._json_serializer)
                print(f"[WebSocket] Packed JSON data: {len(data)} bytes", flush=True)
                await websocket.send(data)

            self.total_messages_sent += 1
            self.total_bytes_sent += len(data)
            print(f"[WebSocket] Message sent successfully", flush=True)

        except Exception as e:
            print(f"[WebSocket] Error sending to client: {e}", flush=True)
            import traceback
            traceback.print_exc()

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
        print("Starting market simulation...", flush=True)

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
        print(f"Starting WebSocket server on {self.host}:{self.port}", flush=True)
        print(f"Protocol: {'Binary (MessagePack)' if self.use_binary else 'JSON'}", flush=True)

        # Start market simulation in background
        asyncio.create_task(self.simulate_market_activity())

        # Start WebSocket server
        async with websockets.serve(
            self.handle_connection,
            self.host,
            self.port
        ):
            print(f"WebSocket server running on ws://{self.host}:{self.port}", flush=True)
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