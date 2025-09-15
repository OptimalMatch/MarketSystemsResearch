"""
Integrated Order Management System
Bridges the ultra-fast matching engine with existing OMS functionality
"""

import asyncio
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import uuid
import sys
import os

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import with error handling for missing components
try:
    from matching_engine.ultra_fast_engine import UltraFastMatchingEngine, BatchOptimizedEngine
except ImportError:
    from ..matching_engine.ultra_fast_engine import UltraFastMatchingEngine, BatchOptimizedEngine

try:
    from matching_engine.engine import OrderStatus, OrderType
except ImportError:
    # Define minimal enums if main engine not available
    from enum import Enum
    class OrderStatus(Enum):
        NEW = "NEW"
        PARTIALLY_FILLED = "PARTIALLY_FILLED"
        FILLED = "FILLED"
        CANCELLED = "CANCELLED"
    class OrderType(Enum):
        MARKET = "MARKET"
        LIMIT = "LIMIT"

try:
    from order_management.oms import OrderManagementSystem, OrderValidator
except ImportError:
    # Create minimal validator
    class OrderValidator:
        def validate_order(self, order):
            return {'valid': True, 'errors': []}
    OrderManagementSystem = None

try:
    from risk_management.risk_engine import RiskEngine
except ImportError:
    # Create minimal risk engine
    class RiskEngine:
        async def check_order(self, order):
            return {'approved': True}

try:
    from ledger.decoin_ledger import DeCoinLedger, ExchangeSettlementBridge
except ImportError:
    from ..ledger.decoin_ledger import DeCoinLedger, ExchangeSettlementBridge

try:
    from data_feed.websocket_server import WebSocketDataFeed
except ImportError:
    WebSocketDataFeed = None

class IntegratedOMS:
    """
    Integrated Order Management System combining:
    - Ultra-fast matching engine (1M+ orders/sec)
    - Risk management checks
    - DeCoin instant settlement
    - WebSocket data distribution
    """

    def __init__(self):
        # Initialize components
        self.engines: Dict[str, UltraFastMatchingEngine] = {}
        self.batch_engines: Dict[str, BatchOptimizedEngine] = {}

        # Initialize for each trading pair
        self.symbols = ["DEC/USD", "BTC/USD", "DEC/BTC", "ETH/USD"]
        for symbol in self.symbols:
            self.engines[symbol] = UltraFastMatchingEngine(symbol)
            self.batch_engines[symbol] = BatchOptimizedEngine(symbol)

        # Risk management
        self.risk_engine = RiskEngine()
        self.validator = OrderValidator()

        # DeCoin ledger for instant settlement
        self.ledger = DeCoinLedger()
        self.settlement_bridge = ExchangeSettlementBridge(self.ledger)

        # WebSocket data feed
        self.data_feed = None  # Will be initialized separately

        # Order tracking
        self.orders: Dict[int, dict] = {}
        self.user_orders: Dict[str, List[int]] = {}

        # Statistics
        self.total_orders = 0
        self.total_trades = 0
        self.total_volume = Decimal('0')

    async def submit_order(self,
                          user_id: str,
                          symbol: str,
                          side: str,
                          order_type: str,
                          quantity: Decimal,
                          price: Optional[Decimal] = None,
                          time_in_force: str = "GTC") -> Tuple[bool, Any]:
        """
        Submit order with full validation and risk checks
        Returns: (success, order_id or error_message)
        """
        # Validate order parameters
        validation = self.validator.validate_order({
            'symbol': symbol,
            'side': side,
            'order_type': order_type,
            'quantity': float(quantity),
            'price': float(price) if price else None,
            'time_in_force': time_in_force
        })

        if not validation['valid']:
            return False, validation['errors']

        # Risk checks
        risk_check = await self.risk_engine.check_order({
            'user_id': user_id,
            'symbol': symbol,
            'side': side,
            'quantity': float(quantity),
            'price': float(price) if price else 0
        })

        if not risk_check['approved']:
            return False, f"Risk check failed: {risk_check.get('reason', 'Unknown')}"

        # For DEC pairs, check balance
        if symbol.startswith("DEC/"):
            if side == "sell":
                # Check DEC balance
                user_address = await self.settlement_bridge.get_user_address(user_id)
                balance = await self.ledger.get_balance(user_address)
                if balance < quantity:
                    return False, "Insufficient DEC balance"

        # Route to appropriate engine
        engine = self.engines.get(symbol)
        if not engine:
            return False, f"Unknown symbol: {symbol}"

        # Submit to matching engine
        try:
            order_id, trades = engine.place_order(
                side=side,
                price=float(price) if price else 0,
                quantity=float(quantity),
                user_id=hash(user_id) % 1000000  # Convert to numeric ID
            )

            # Track order
            order_info = {
                'id': order_id,
                'user_id': user_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': price,
                'filled_quantity': Decimal('0'),
                'status': 'NEW',
                'created_at': time.time(),
                'trades': []
            }

            # Process trades
            if trades:
                await self.process_trades(order_info, trades)

            # Store order
            self.orders[order_id] = order_info

            # Track user orders
            if user_id not in self.user_orders:
                self.user_orders[user_id] = []
            self.user_orders[user_id].append(order_id)

            # Update statistics
            self.total_orders += 1

            # Broadcast order book update if we have data feed
            if self.data_feed:
                snapshot = engine.get_order_book_snapshot()
                await self.data_feed.broadcast_orderbook_update(symbol, snapshot)

            return True, order_id

        except Exception as e:
            return False, str(e)

    async def process_trades(self, order_info: dict, trades: List[dict]):
        """Process executed trades"""
        for trade in trades:
            # Update order info
            order_info['filled_quantity'] += Decimal(str(trade['quantity']))
            order_info['trades'].append(trade)

            # Update statistics
            self.total_trades += 1
            self.total_volume += Decimal(str(trade['quantity']))

            # Settlement for DEC pairs
            if order_info['symbol'].startswith("DEC/"):
                await self.settle_dec_trade(order_info, trade)

            # Broadcast trade if we have data feed
            if self.data_feed:
                await self.data_feed.broadcast_trade(order_info['symbol'], trade)

        # Update order status
        if order_info['filled_quantity'] >= order_info['quantity']:
            order_info['status'] = 'FILLED'
        else:
            order_info['status'] = 'PARTIALLY_FILLED'

    async def settle_dec_trade(self, order_info: dict, trade: dict):
        """Settle DEC trade instantly using ledger"""
        symbol = order_info['symbol']

        if symbol == "DEC/USD":
            # For DEC/USD, we need to handle fiat settlement separately
            # For now, just log it
            print(f"DEC/USD trade: {trade['quantity']} DEC at ${trade['price']}")

        elif symbol.startswith("DEC/"):
            # DEC to DEC trading (instant settlement)
            buyer_id = str(trade['buyer_id'])
            seller_id = str(trade['seller_id'])
            amount = Decimal(str(trade['quantity']))

            success, result = await self.settlement_bridge.settle_trade(
                buyer_id=buyer_id,
                seller_id=seller_id,
                amount=amount
            )

            if success:
                print(f"Settled DEC trade: {amount} DEC from {seller_id} to {buyer_id}")
            else:
                print(f"Settlement failed: {result}")

    async def cancel_order(self, user_id: str, order_id: int) -> Tuple[bool, str]:
        """Cancel an order"""
        # Check order exists and belongs to user
        if order_id not in self.orders:
            return False, "Order not found"

        order = self.orders[order_id]
        if order['user_id'] != user_id:
            return False, "Unauthorized"

        # Check if order can be cancelled
        if order['status'] in ['FILLED', 'CANCELLED']:
            return False, f"Order already {order['status']}"

        # Cancel in matching engine
        engine = self.engines.get(order['symbol'])
        if engine:
            success = engine.cancel_order(order_id)
            if success:
                order['status'] = 'CANCELLED'
                return True, "Order cancelled"

        return False, "Failed to cancel order"

    async def get_user_orders(self, user_id: str) -> List[dict]:
        """Get all orders for a user"""
        order_ids = self.user_orders.get(user_id, [])
        return [self.orders[oid] for oid in order_ids if oid in self.orders]

    async def get_order_book(self, symbol: str, depth: int = 20) -> dict:
        """Get order book snapshot"""
        engine = self.engines.get(symbol)
        if engine:
            return engine.get_order_book_snapshot(depth)
        return {'bids': [], 'asks': []}

    async def get_user_balance(self, user_id: str) -> Dict[str, Decimal]:
        """Get user balances"""
        balances = {}

        # Get DEC balance from ledger
        user_address = await self.settlement_bridge.get_user_address(user_id)
        dec_balance = await self.ledger.get_balance(user_address)
        balances['DEC'] = dec_balance

        # Other balances would come from different sources
        # For now, return mock balances
        balances['USD'] = Decimal('10000.00')
        balances['BTC'] = Decimal('0.5')
        balances['ETH'] = Decimal('5.0')

        return balances

    def get_stats(self) -> dict:
        """Get OMS statistics"""
        engine_stats = {}
        for symbol, engine in self.engines.items():
            engine_stats[symbol] = engine.get_stats()

        return {
            'total_orders': self.total_orders,
            'total_trades': self.total_trades,
            'total_volume': float(self.total_volume),
            'active_orders': len([o for o in self.orders.values() if o['status'] == 'NEW']),
            'engines': engine_stats,
            'ledger': self.ledger.get_stats() if self.ledger else {}
        }

    async def start_data_feed(self, host: str = "0.0.0.0", port: int = 13765):
        """Start WebSocket data feed server"""
        self.data_feed = WebSocketDataFeed(host, port)

        # Replace engines in data feed with our engines
        self.data_feed.engines = self.engines

        # Start server
        await self.data_feed.start()


# Example usage and testing
async def test_integrated_oms():
    """Test the integrated OMS"""
    print("Testing Integrated Order Management System...")
    print("-" * 50)

    oms = IntegratedOMS()

    # Initialize some user balances
    await oms.settlement_bridge.deposit("alice", Decimal('10000'))
    await oms.settlement_bridge.deposit("bob", Decimal('5000'))

    print("Initial balances:")
    alice_balance = await oms.get_user_balance("alice")
    bob_balance = await oms.get_user_balance("bob")
    print(f"Alice: {alice_balance}")
    print(f"Bob: {bob_balance}")

    # Submit orders
    print("\nSubmitting orders...")

    # Alice buys DEC
    success, order_id = await oms.submit_order(
        user_id="alice",
        symbol="DEC/USD",
        side="buy",
        order_type="limit",
        quantity=Decimal('100'),
        price=Decimal('100.00')
    )
    print(f"Alice buy order: {success}, Order ID: {order_id}")

    # Bob sells DEC
    success, order_id = await oms.submit_order(
        user_id="bob",
        symbol="DEC/USD",
        side="sell",
        order_type="limit",
        quantity=Decimal('100'),
        price=Decimal('100.00')
    )
    print(f"Bob sell order: {success}, Order ID: {order_id}")

    # Check order book
    book = await oms.get_order_book("DEC/USD", 5)
    print(f"\nOrder Book:")
    print(f"Bids: {book['bids'][:3]}")
    print(f"Asks: {book['asks'][:3]}")

    # Performance test
    print("\nPerformance test...")
    start = time.perf_counter()
    num_orders = 10000

    for i in range(num_orders):
        user = "alice" if i % 2 == 0 else "bob"
        side = "buy" if i % 2 == 0 else "sell"
        price = Decimal('100') + Decimal(i % 10) * Decimal('0.01')

        await oms.submit_order(
            user_id=user,
            symbol="DEC/USD",
            side=side,
            order_type="limit",
            quantity=Decimal('1'),
            price=price
        )

    elapsed = time.perf_counter() - start
    orders_per_second = num_orders / elapsed

    print(f"\nProcessed {num_orders} orders in {elapsed:.3f} seconds")
    print(f"Throughput: {orders_per_second:.0f} orders/second")

    # Get statistics
    stats = oms.get_stats()
    print(f"\nOMS Statistics:")
    print(f"  Total orders: {stats['total_orders']}")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Total volume: {stats['total_volume']:.2f}")
    print(f"  Active orders: {stats['active_orders']}")


if __name__ == "__main__":
    asyncio.run(test_integrated_oms())