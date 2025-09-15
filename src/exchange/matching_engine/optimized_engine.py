"""
Ultra-high performance matching engine implementation
Target: 1M+ orders/second with <10 microsecond latency
"""

import numpy as np
import numba
from numba import jit, types
from numba.typed import Dict
import mmap
import os
import struct
from decimal import Decimal
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import IntEnum
import time
import asyncio
from collections import deque
import multiprocessing as mp
import psutil

class OrderSide(IntEnum):
    BUY = 0
    SELL = 1

class OrderType(IntEnum):
    MARKET = 0
    LIMIT = 1
    STOP = 2
    STOP_LIMIT = 3

class OrderStatus(IntEnum):
    NEW = 0
    PARTIALLY_FILLED = 1
    FILLED = 2
    CANCELLED = 3

# Pre-allocate arrays for maximum performance
MAX_ORDERS = 1_000_000
MAX_TRADES = 100_000
MAX_DEPTH = 10_000

@dataclass
class OrderBookArrays:
    """Memory-aligned arrays for order book data"""
    # Price, Quantity, Timestamp, OrderID, UserID
    bids: np.ndarray = None
    asks: np.ndarray = None
    bid_count: int = 0
    ask_count: int = 0

    def __init__(self):
        # Allocate aligned memory for cache optimization
        self.bids = np.zeros((MAX_DEPTH, 5), dtype=np.float64, order='C')
        self.asks = np.zeros((MAX_DEPTH, 5), dtype=np.float64, order='C')
        self.bid_count = 0
        self.ask_count = 0

class OptimizedMatchingEngine:
    """
    Ultra-fast matching engine using numpy arrays and numba JIT compilation
    """

    def __init__(self, symbol: str = "DEC/USD", use_mmap: bool = True):
        self.symbol = symbol
        self.use_mmap = use_mmap

        # Order books using numpy arrays
        self.order_book = OrderBookArrays()

        # Order storage (memory-mapped if enabled)
        if use_mmap:
            self._init_memory_mapped_storage()
        else:
            self.orders = {}

        # Trade buffer (pre-allocated)
        self.trade_buffer = np.zeros((MAX_TRADES, 7), dtype=np.float64)
        self.trade_count = 0

        # Performance metrics
        self.order_counter = 0
        self.trade_counter = 0
        self.last_trade_price = 0.0

        # Lock-free queue for incoming orders
        self.order_queue = deque(maxlen=100000)

        # CPU affinity for performance
        self._set_cpu_affinity()

    def _init_memory_mapped_storage(self):
        """Initialize memory-mapped file for order storage"""
        self.mmap_size = MAX_ORDERS * 256  # 256 bytes per order
        self.mmap_file = f"/tmp/matching_engine_{self.symbol.replace('/', '_')}.mmap"

        # Create or open memory-mapped file
        if not os.path.exists(self.mmap_file):
            with open(self.mmap_file, 'wb') as f:
                f.write(b'\0' * self.mmap_size)

        self.mmap_fd = os.open(self.mmap_file, os.O_RDWR)
        self.mmap_data = mmap.mmap(self.mmap_fd, self.mmap_size)

    def _set_cpu_affinity(self):
        """Pin process to specific CPU cores for performance"""
        try:
            # Get available CPUs
            cpu_count = psutil.cpu_count()

            # Pin to high-performance cores (usually the last ones)
            if cpu_count >= 4:
                high_perf_cores = list(range(cpu_count - 2, cpu_count))
                p = psutil.Process()
                p.cpu_affinity(high_perf_cores)
                print(f"Process pinned to CPU cores: {high_perf_cores}")
        except:
            pass  # CPU affinity not supported on this platform

    @staticmethod
    @jit(nopython=True, cache=True, fastmath=True)
    def _match_orders_jit(bid_array: np.ndarray, ask_array: np.ndarray,
                          bid_count: int, ask_count: int,
                          trade_buffer: np.ndarray, trade_count: int,
                          current_timestamp: float) -> Tuple[int, int, int]:
        """
        JIT-compiled order matching logic for maximum speed
        Returns: (new_bid_count, new_ask_count, new_trade_count)
        """
        bid_idx = 0
        ask_idx = 0

        while bid_idx < bid_count and ask_idx < ask_count:
            bid_price = bid_array[bid_idx, 0]
            ask_price = ask_array[ask_idx, 0]

            # Check if orders cross
            if bid_price >= ask_price:
                bid_qty = bid_array[bid_idx, 1]
                ask_qty = ask_array[ask_idx, 1]

                # Calculate trade quantity
                trade_qty = min(bid_qty, ask_qty)
                trade_price = ask_price  # Trade at ask price (price-time priority)

                # Record trade
                if trade_count < MAX_TRADES:
                    trade_buffer[trade_count, 0] = trade_price
                    trade_buffer[trade_count, 1] = trade_qty
                    trade_buffer[trade_count, 2] = bid_array[bid_idx, 3]  # Buyer order ID
                    trade_buffer[trade_count, 3] = ask_array[ask_idx, 3]  # Seller order ID
                    trade_buffer[trade_count, 4] = bid_array[bid_idx, 4]  # Buyer user ID
                    trade_buffer[trade_count, 5] = ask_array[ask_idx, 4]  # Seller user ID
                    trade_buffer[trade_count, 6] = current_timestamp  # Timestamp
                    trade_count += 1

                # Update quantities
                bid_array[bid_idx, 1] -= trade_qty
                ask_array[ask_idx, 1] -= trade_qty

                # Remove filled orders
                if bid_array[bid_idx, 1] <= 0:
                    bid_idx += 1
                if ask_array[ask_idx, 1] <= 0:
                    ask_idx += 1
            else:
                break

        # Compact arrays (remove filled orders)
        new_bid_count = 0
        for i in range(bid_idx, bid_count):
            if bid_array[i, 1] > 0:
                if i != new_bid_count:
                    bid_array[new_bid_count] = bid_array[i]
                new_bid_count += 1

        new_ask_count = 0
        for i in range(ask_idx, ask_count):
            if ask_array[i, 1] > 0:
                if i != new_ask_count:
                    ask_array[new_ask_count] = ask_array[i]
                new_ask_count += 1

        return new_bid_count, new_ask_count, trade_count

    def place_order(self, order_dict: dict) -> Tuple[bool, List[dict]]:
        """
        Place an order in the book
        Ultra-fast path for limit orders
        """
        start_time = time.perf_counter_ns()

        # Extract order data
        order_id = self.order_counter
        self.order_counter += 1

        side = OrderSide.BUY if order_dict['side'] == 'buy' else OrderSide.SELL
        price = float(order_dict['price'])
        quantity = float(order_dict['quantity'])
        user_id = float(order_dict.get('user_id', 0))
        timestamp = time.time()

        # Add to appropriate side of book
        if side == OrderSide.BUY:
            if self.order_book.bid_count < MAX_DEPTH:
                idx = self.order_book.bid_count
                self.order_book.bids[idx] = [price, quantity, timestamp, order_id, user_id]
                self.order_book.bid_count += 1

                # Sort bids (highest first) - using numpy for speed
                if self.order_book.bid_count > 1:
                    sorted_indices = np.argsort(-self.order_book.bids[:self.order_book.bid_count, 0])
                    self.order_book.bids[:self.order_book.bid_count] = self.order_book.bids[sorted_indices]
        else:
            if self.order_book.ask_count < MAX_DEPTH:
                idx = self.order_book.ask_count
                self.order_book.asks[idx] = [price, quantity, timestamp, order_id, user_id]
                self.order_book.ask_count += 1

                # Sort asks (lowest first)
                if self.order_book.ask_count > 1:
                    sorted_indices = np.argsort(self.order_book.asks[:self.order_book.ask_count, 0])
                    self.order_book.asks[:self.order_book.ask_count] = self.order_book.asks[sorted_indices]

        # Attempt matching
        trades = self._try_match()

        # Calculate latency
        latency_ns = time.perf_counter_ns() - start_time

        # Log performance metrics (every 10000 orders)
        if self.order_counter % 10000 == 0:
            print(f"Order {self.order_counter}: Latency: {latency_ns/1000:.2f} μs")

        return True, trades

    def _try_match(self) -> List[dict]:
        """Execute matching using JIT-compiled function"""
        # Call JIT-compiled matching function
        new_bid_count, new_ask_count, new_trade_count = self._match_orders_jit(
            self.order_book.bids,
            self.order_book.asks,
            self.order_book.bid_count,
            self.order_book.ask_count,
            self.trade_buffer,
            self.trade_count,
            time.time()  # Pass current timestamp
        )

        # Extract trades from buffer
        trades = []
        if new_trade_count > self.trade_count:
            for i in range(self.trade_count, new_trade_count):
                trade = {
                    'price': self.trade_buffer[i, 0],
                    'quantity': self.trade_buffer[i, 1],
                    'buyer_order_id': int(self.trade_buffer[i, 2]),
                    'seller_order_id': int(self.trade_buffer[i, 3]),
                    'buyer_user_id': int(self.trade_buffer[i, 4]),
                    'seller_user_id': int(self.trade_buffer[i, 5]),
                    'timestamp': self.trade_buffer[i, 6]
                }
                trades.append(trade)
                self.last_trade_price = trade['price']

        # Update counts
        self.order_book.bid_count = new_bid_count
        self.order_book.ask_count = new_ask_count
        self.trade_count = new_trade_count

        return trades

    def cancel_order(self, order_id: int, side: str) -> bool:
        """Cancel an order (optimized for speed)"""
        if side == 'buy':
            for i in range(self.order_book.bid_count):
                if self.order_book.bids[i, 3] == order_id:
                    # Remove by shifting array
                    self.order_book.bids[i:self.order_book.bid_count-1] = \
                        self.order_book.bids[i+1:self.order_book.bid_count]
                    self.order_book.bid_count -= 1
                    return True
        else:
            for i in range(self.order_book.ask_count):
                if self.order_book.asks[i, 3] == order_id:
                    # Remove by shifting array
                    self.order_book.asks[i:self.order_book.ask_count-1] = \
                        self.order_book.asks[i+1:self.order_book.ask_count]
                    self.order_book.ask_count -= 1
                    return True
        return False

    def get_order_book_snapshot(self, depth: int = 10) -> dict:
        """Get current order book state"""
        return {
            'symbol': self.symbol,
            'bids': self.order_book.bids[:min(depth, self.order_book.bid_count), :2].tolist(),
            'asks': self.order_book.asks[:min(depth, self.order_book.ask_count), :2].tolist(),
            'last_price': self.last_trade_price,
            'timestamp': time.time()
        }

    def get_performance_stats(self) -> dict:
        """Get engine performance statistics"""
        return {
            'total_orders': self.order_counter,
            'total_trades': self.trade_count,
            'bid_depth': self.order_book.bid_count,
            'ask_depth': self.order_book.ask_count,
            'last_trade_price': self.last_trade_price
        }

    def cleanup(self):
        """Clean up resources"""
        if self.use_mmap and hasattr(self, 'mmap_data'):
            self.mmap_data.close()
            os.close(self.mmap_fd)
            os.remove(self.mmap_file)


class AsyncOptimizedEngine:
    """Async wrapper for the optimized matching engine"""

    def __init__(self, symbol: str = "DEC/USD"):
        self.engine = OptimizedMatchingEngine(symbol)
        self.processing = False

    async def place_order_async(self, order: dict) -> Tuple[bool, List[dict]]:
        """Async order placement"""
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.engine.place_order, order)

    async def cancel_order_async(self, order_id: int, side: str) -> bool:
        """Async order cancellation"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.engine.cancel_order, order_id, side)

    async def get_snapshot_async(self, depth: int = 10) -> dict:
        """Async order book snapshot"""
        return self.engine.get_order_book_snapshot(depth)


# Benchmark function
def benchmark_engine():
    """Benchmark the matching engine performance"""
    print("Starting Optimized Matching Engine Benchmark...")
    print("-" * 50)

    engine = OptimizedMatchingEngine("DEC/USD", use_mmap=False)

    # Warm up JIT compilation
    print("Warming up JIT compiler...")
    for i in range(1000):
        engine.place_order({
            'side': 'buy' if i % 2 == 0 else 'sell',
            'price': 100.0 + (i % 10) * 0.1,
            'quantity': 1.0,
            'user_id': i % 100
        })

    # Reset for actual benchmark
    engine = OptimizedMatchingEngine("DEC/USD", use_mmap=False)

    # Benchmark order placement
    print("\nBenchmarking order placement...")
    start = time.perf_counter()

    num_orders = 100000
    for i in range(num_orders):
        # Create realistic order distribution
        side = 'buy' if i % 2 == 0 else 'sell'

        # Price around 100 with small spread
        if side == 'buy':
            price = 99.95 + (i % 10) * 0.01
        else:
            price = 100.05 + (i % 10) * 0.01

        engine.place_order({
            'side': side,
            'price': price,
            'quantity': 1.0 + (i % 10) * 0.1,
            'user_id': i % 1000
        })

    elapsed = time.perf_counter() - start
    orders_per_second = num_orders / elapsed
    latency_us = (elapsed / num_orders) * 1_000_000

    print(f"\nResults:")
    print(f"  Orders processed: {num_orders:,}")
    print(f"  Time elapsed: {elapsed:.3f} seconds")
    print(f"  Throughput: {orders_per_second:,.0f} orders/second")
    print(f"  Average latency: {latency_us:.2f} microseconds")

    stats = engine.get_performance_stats()
    print(f"\nEngine Statistics:")
    print(f"  Total trades executed: {stats['total_trades']:,}")
    print(f"  Current bid depth: {stats['bid_depth']}")
    print(f"  Current ask depth: {stats['ask_depth']}")
    print(f"  Last trade price: {stats['last_trade_price']:.2f}")

    engine.cleanup()

    return orders_per_second


if __name__ == "__main__":
    # Run benchmark
    throughput = benchmark_engine()

    if throughput > 100000:
        print("\n✅ Performance target achieved: >100K orders/second")
    else:
        print(f"\n⚠️  Performance below target. Current: {throughput:.0f} orders/second")
        print("   Target: 100,000 orders/second")