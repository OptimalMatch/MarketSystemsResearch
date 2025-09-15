"""
Ultra-fast matching engine using heaps and minimal Python overhead
Target: 100K+ orders/second
"""

import heapq
import time
from decimal import Decimal
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import array
import mmap
import os
from collections import deque
import struct

@dataclass(slots=True)
class Order:
    """Lightweight order structure using slots for memory efficiency"""
    id: int
    user_id: int
    price: float
    quantity: float
    timestamp: float
    side: int  # 0=buy, 1=sell

    def __lt__(self, other):
        # For buy orders: higher price = higher priority (negate for min heap)
        # For sell orders: lower price = higher priority
        if self.side == 0:  # Buy
            return -self.price < -other.price
        else:  # Sell
            return self.price < other.price


class UltraFastMatchingEngine:
    """
    Heap-based matching engine for maximum performance
    """

    def __init__(self, symbol: str = "DEC/USD"):
        self.symbol = symbol

        # Use heaps for O(log n) insertion and O(1) best price access
        self.buy_orders = []  # Max heap (using negative prices)
        self.sell_orders = []  # Min heap

        # Order lookup for cancellation
        self.order_map: Dict[int, Order] = {}

        # Performance counters
        self.order_id_counter = 0
        self.trade_id_counter = 0
        self.last_trade_price = 0.0

        # Pre-allocated trade buffer
        self.trade_buffer = deque(maxlen=10000)

        # Statistics
        self.total_orders = 0
        self.total_trades = 0
        self.total_volume = 0.0

    def place_order(self, side: str, price: float, quantity: float, user_id: int = 0) -> Tuple[int, List[dict]]:
        """
        Place an order and attempt matching
        Returns: (order_id, list of trades)
        """
        # Generate order ID
        order_id = self.order_id_counter
        self.order_id_counter += 1
        self.total_orders += 1

        # Create order
        order = Order(
            id=order_id,
            user_id=user_id,
            price=price,
            quantity=quantity,
            timestamp=time.perf_counter(),
            side=0 if side == 'buy' else 1
        )

        # Store in map
        self.order_map[order_id] = order

        # Try to match immediately
        trades = self._try_match_order(order)

        # If order has remaining quantity, add to book
        if order.quantity > 0:
            if order.side == 0:  # Buy
                heapq.heappush(self.buy_orders, (-order.price, order.timestamp, order))
            else:  # Sell
                heapq.heappush(self.sell_orders, (order.price, order.timestamp, order))

        return order_id, trades

    def _try_match_order(self, incoming_order: Order) -> List[dict]:
        """
        Attempt to match an incoming order against the book
        """
        trades = []

        if incoming_order.side == 0:  # Buy order
            # Match against sell orders
            while incoming_order.quantity > 0 and self.sell_orders:
                # Peek at best sell order
                best_price, _, best_order = self.sell_orders[0]

                # Check if prices cross
                if incoming_order.price >= best_order.price:
                    # Execute trade
                    trade_qty = min(incoming_order.quantity, best_order.quantity)

                    # Record trade
                    trade = {
                        'id': self.trade_id_counter,
                        'price': best_order.price,  # Trade at passive order price
                        'quantity': trade_qty,
                        'buyer_id': incoming_order.user_id,
                        'seller_id': best_order.user_id,
                        'timestamp': time.perf_counter()
                    }
                    trades.append(trade)

                    self.trade_id_counter += 1
                    self.total_trades += 1
                    self.total_volume += trade_qty
                    self.last_trade_price = best_order.price

                    # Update quantities
                    incoming_order.quantity -= trade_qty
                    best_order.quantity -= trade_qty

                    # Remove filled order from book
                    if best_order.quantity <= 0:
                        heapq.heappop(self.sell_orders)
                        del self.order_map[best_order.id]
                else:
                    # No more matches possible
                    break

        else:  # Sell order
            # Match against buy orders
            while incoming_order.quantity > 0 and self.buy_orders:
                # Peek at best buy order
                neg_price, _, best_order = self.buy_orders[0]
                best_price = -neg_price

                # Check if prices cross
                if incoming_order.price <= best_order.price:
                    # Execute trade
                    trade_qty = min(incoming_order.quantity, best_order.quantity)

                    # Record trade
                    trade = {
                        'id': self.trade_id_counter,
                        'price': best_order.price,  # Trade at passive order price
                        'quantity': trade_qty,
                        'buyer_id': best_order.user_id,
                        'seller_id': incoming_order.user_id,
                        'timestamp': time.perf_counter()
                    }
                    trades.append(trade)

                    self.trade_id_counter += 1
                    self.total_trades += 1
                    self.total_volume += trade_qty
                    self.last_trade_price = best_order.price

                    # Update quantities
                    incoming_order.quantity -= trade_qty
                    best_order.quantity -= trade_qty

                    # Remove filled order from book
                    if best_order.quantity <= 0:
                        heapq.heappop(self.buy_orders)
                        del self.order_map[best_order.id]
                else:
                    # No more matches possible
                    break

        return trades

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order
        Note: This is O(n) - could be optimized with additional data structures
        """
        if order_id not in self.order_map:
            return False

        order = self.order_map[order_id]
        order.quantity = 0  # Mark as cancelled
        del self.order_map[order_id]

        # Order will be lazily removed from heap when encountered
        return True

    def get_order_book_snapshot(self, depth: int = 10) -> dict:
        """Get current order book state"""
        # Extract top orders from heaps (without modifying them)
        bids = []
        bid_prices = {}

        # Aggregate buy orders by price
        for neg_price, _, order in self.buy_orders:
            if order.quantity > 0:  # Skip cancelled orders
                price = -neg_price
                if price not in bid_prices:
                    bid_prices[price] = 0
                bid_prices[price] += order.quantity

        # Convert to list and sort
        for price in sorted(bid_prices.keys(), reverse=True)[:depth]:
            bids.append([price, bid_prices[price]])

        # Aggregate sell orders by price
        asks = []
        ask_prices = {}

        for price, _, order in self.sell_orders:
            if order.quantity > 0:  # Skip cancelled orders
                if price not in ask_prices:
                    ask_prices[price] = 0
                ask_prices[price] += order.quantity

        # Convert to list and sort
        for price in sorted(ask_prices.keys())[:depth]:
            asks.append([price, ask_prices[price]])

        return {
            'symbol': self.symbol,
            'bids': bids,
            'asks': asks,
            'last_price': self.last_trade_price,
            'spread': asks[0][0] - bids[0][0] if bids and asks else 0
        }

    def get_stats(self) -> dict:
        """Get performance statistics"""
        return {
            'total_orders': self.total_orders,
            'total_trades': self.total_trades,
            'total_volume': self.total_volume,
            'active_orders': len(self.order_map),
            'bid_depth': sum(1 for _, _, o in self.buy_orders if o.quantity > 0),
            'ask_depth': sum(1 for _, _, o in self.sell_orders if o.quantity > 0),
            'last_price': self.last_trade_price
        }


class BatchOptimizedEngine(UltraFastMatchingEngine):
    """
    Batch processing version for even higher throughput
    """

    def __init__(self, symbol: str = "DEC/USD", batch_size: int = 1000):
        super().__init__(symbol)
        self.batch_size = batch_size
        self.order_queue = deque()
        self.batch_trades = []

    def queue_order(self, side: str, price: float, quantity: float, user_id: int = 0):
        """Queue an order for batch processing"""
        self.order_queue.append((side, price, quantity, user_id))

    def process_batch(self) -> List[dict]:
        """Process all queued orders in a batch"""
        batch_trades = []

        # Process up to batch_size orders
        processed = 0
        while self.order_queue and processed < self.batch_size:
            side, price, quantity, user_id = self.order_queue.popleft()
            _, trades = self.place_order(side, price, quantity, user_id)
            batch_trades.extend(trades)
            processed += 1

        return batch_trades


def benchmark_ultra_fast():
    """Benchmark the ultra-fast matching engine"""
    print("Benchmarking Ultra-Fast Matching Engine...")
    print("-" * 50)

    engine = UltraFastMatchingEngine("DEC/USD")

    # Warm up
    for i in range(1000):
        engine.place_order(
            side='buy' if i % 2 == 0 else 'sell',
            price=100.0 + (i % 20 - 10) * 0.1,
            quantity=1.0,
            user_id=i
        )

    # Reset for benchmark
    engine = UltraFastMatchingEngine("DEC/USD")

    # Benchmark
    num_orders = 100000
    start = time.perf_counter()

    for i in range(num_orders):
        # Create order distribution that generates trades
        side = 'buy' if i % 2 == 0 else 'sell'

        if side == 'buy':
            price = 100.0 - (i % 5) * 0.01  # Bids from 99.96 to 100.00
        else:
            price = 100.0 + (i % 5) * 0.01  # Asks from 100.00 to 100.04

        engine.place_order(
            side=side,
            price=price,
            quantity=1.0 + (i % 10) * 0.1,
            user_id=i % 1000
        )

    elapsed = time.perf_counter() - start

    # Calculate metrics
    orders_per_second = num_orders / elapsed
    latency_us = (elapsed / num_orders) * 1_000_000

    print(f"\nResults:")
    print(f"  Orders processed: {num_orders:,}")
    print(f"  Time elapsed: {elapsed:.3f} seconds")
    print(f"  Throughput: {orders_per_second:,.0f} orders/second")
    print(f"  Average latency: {latency_us:.2f} microseconds")

    stats = engine.get_stats()
    print(f"\nEngine Statistics:")
    print(f"  Total trades: {stats['total_trades']:,}")
    print(f"  Total volume: {stats['total_volume']:,.2f}")
    print(f"  Active orders: {stats['active_orders']}")
    print(f"  Last price: {stats['last_price']:.2f}")

    return orders_per_second


def benchmark_batch_processing():
    """Benchmark batch processing mode"""
    print("\nBenchmarking Batch Processing Mode...")
    print("-" * 50)

    engine = BatchOptimizedEngine("DEC/USD", batch_size=1000)

    # Queue orders
    num_orders = 100000
    start_queue = time.perf_counter()

    for i in range(num_orders):
        side = 'buy' if i % 2 == 0 else 'sell'
        price = 100.0 + (i % 20 - 10) * 0.01
        engine.queue_order(side, price, 1.0, i % 1000)

    queue_time = time.perf_counter() - start_queue

    # Process in batches
    start_process = time.perf_counter()
    total_trades = []

    while engine.order_queue:
        trades = engine.process_batch()
        total_trades.extend(trades)

    process_time = time.perf_counter() - start_process
    total_time = queue_time + process_time

    # Calculate metrics
    orders_per_second = num_orders / total_time
    latency_us = (total_time / num_orders) * 1_000_000

    print(f"\nResults:")
    print(f"  Orders processed: {num_orders:,}")
    print(f"  Queue time: {queue_time:.3f} seconds")
    print(f"  Process time: {process_time:.3f} seconds")
    print(f"  Total time: {total_time:.3f} seconds")
    print(f"  Throughput: {orders_per_second:,.0f} orders/second")
    print(f"  Average latency: {latency_us:.2f} microseconds")
    print(f"  Trades executed: {len(total_trades):,}")

    return orders_per_second


if __name__ == "__main__":
    # Run benchmarks
    print("=" * 60)
    print("ULTRA-FAST MATCHING ENGINE BENCHMARK")
    print("=" * 60)

    throughput1 = benchmark_ultra_fast()

    throughput2 = benchmark_batch_processing()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if throughput1 > 100000:
        print(f"✅ Standard Mode: {throughput1:,.0f} orders/sec - TARGET ACHIEVED!")
    else:
        print(f"⚠️  Standard Mode: {throughput1:,.0f} orders/sec - Below target")

    if throughput2 > 100000:
        print(f"✅ Batch Mode: {throughput2:,.0f} orders/sec - TARGET ACHIEVED!")
    else:
        print(f"⚠️  Batch Mode: {throughput2:,.0f} orders/sec - Below target")

    print("\nRecommendation:")
    if max(throughput1, throughput2) > 100000:
        print("  Performance target achieved! Ready for production testing.")
    else:
        print("  Consider C++ implementation or hardware optimization for target performance.")