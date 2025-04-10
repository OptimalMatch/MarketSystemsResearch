from decimal import Decimal
import threading
import random
import time
from typing import List, Dict
import logging
from concurrent.futures import ThreadPoolExecutor
import queue
from datetime import datetime
import signal
import sys
from Exchange import Market, OrderSide
from MarketMaker import MarketMaker
import psutil
import os

def get_memory_usage():
    """Return memory usage in MB."""
    process = psutil.Process()
    mem_info = process.memory_info()
    return mem_info.rss / 1024 / 1024  # Convert bytes to MB

class MarketRushSimulator:
    def __init__(self, market: Market, security_id: str, num_participants: int = 10000, enable_simulated_sellers: bool = True):
        self.market = market
        self.security_id = security_id
        self.num_participants = num_participants
        self.enable_simulated_sellers = enable_simulated_sellers
        self.is_running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)
        self.price_queue = queue.Queue()
        self.executor = None
        self.batch_size = 200  # Increased from 100
        self.worker_threads = 200  # Increased from 100
        self.batch_delay = 0.025  # Reduced from 0.05

        # More controlled price configuration
        self.min_price_increment = Decimal('0.05')  # 5 cents minimum
        self.max_price_increment = Decimal('0.25')  # 25 cents maximum
        self.order_size_min = 10  # Minimum order size
        self.order_size_max = 100  # Maximum order size
        self.aggressive_order_probability = 0.3  # 30% aggressive orders

        # Use a local cache for market depth
        self.cached_depth = {'asks': [], 'bids': []}
        self.last_depth_update = 0
        self.depth_cache_ttl = 0.1  # 100ms cache TTL

        # Pre-calculate pools for better performance
        self.participant_pool = []
        self.participant_pool_size = 1000
        self.current_participant_index = 0
        
        # Pre-calculate price increment pool
        self.price_increment_pool = []
        self.price_increment_pool_size = 1000
        self.current_price_increment_index = 0
        
        # Pre-calculate order size pool
        self.order_size_pool = []
        self.order_size_pool_size = 1000
        self.current_order_size_index = 0

        # Track the last trade price
        self.last_trade_price = Decimal('100')
        self.initial_price = self.last_trade_price

        # More controlled wave patterns
        self.wave_patterns = [
            (100, 1.0),  # Normal trading
            (200, 1.2),  # Building pressure
            (300, 1.5),  # Increased pressure
            (200, 1.2),  # Easing
            (100, 1.0)  # Back to normal
        ]

        # Momentum control
        self.momentum = Decimal('1.0')
        self.momentum_increment = Decimal('0.01')
        self.max_momentum = Decimal('1.5')
        self.min_momentum = Decimal('0.5')

        self.current_wave = 0
        self.orders_in_current_wave = 0

        self.stats = {
            'total_orders': 0,
            'successful_orders': 0,
            'failed_orders': 0,
            'current_price': self.last_trade_price,
            'price_movement_percent': Decimal('0'),
            'start_price': self.initial_price,
            'highest_price': self.initial_price,
            'volume': Decimal('0')
        }

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print("\nReceived shutdown signal. Stopping simulation...")
        self.stop_rush()

    def start_rush(self, duration_seconds: int = 300):
        """Start the market rush simulation"""
        if self.is_running:
            return

        self.is_running = True
        self.initialize_participants()

        # Initialize ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=self.worker_threads)

        # Start simulation thread
        self.thread = threading.Thread(target=self._run_simulation, args=(duration_seconds,))
        self.thread.daemon = True
        self.thread.start()

        self.logger.info(f"Market rush started with {self.num_participants} participants")

    def stop_rush(self):
        """Stop the market rush simulation"""
        self.is_running = False

        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None

        if self.thread:
            self.thread.join(timeout=2.0)

        self.logger.info("Market rush stopped")

    def _run_simulation(self, duration_seconds: int):
        """Main simulation loop"""
        if not self.executor:
            return

        start_time = time.time()
        end_time = start_time + duration_seconds
        orders_placed = 0
        trades_executed = 0
        last_log_time = start_time
        log_interval = 1.0  # Log every second

        try:
            while time.time() < end_time and self.is_running:
                # Update market depth cache if needed
                current_time = time.time()
                if current_time - self.last_depth_update > self.depth_cache_ttl:
                    try:
                        self.cached_depth = self.market.get_market_depth(self.security_id)
                        self.last_depth_update = current_time
                        if self.cached_depth['asks']:
                            self.last_trade_price = self.cached_depth['asks'][0]['price']
                            self.stats['current_price'] = self.last_trade_price
                    except Exception as e:
                        self.logger.error(f"Error getting market depth: {str(e)}")

                # Submit batch of orders
                futures = []
                for _ in range(self.batch_size):
                    if not self.is_running:
                        break
                    futures.append(
                        self.executor.submit(self._place_rush_order)
                    )

                # Process completed orders in parallel
                completed_futures = []
                for future in futures:
                    if not self.is_running:
                        break
                    try:
                        result = future.result(timeout=0.5)
                        completed_futures.append(result)
                        if result:
                            orders_placed += 1
                            trades_executed += 1
                    except Exception as e:
                        self.logger.error(f"Error processing order: {str(e)}")
                        self.stats['failed_orders'] += 1
                        self.stats['total_orders'] += 1

                # Bulk update stats
                successes = sum(1 for result in completed_futures if result)
                self.stats['successful_orders'] += successes
                self.stats['failed_orders'] += (len(completed_futures) - successes)
                self.stats['total_orders'] += len(completed_futures)

                # Log performance metrics periodically
                current_time = time.time()
                if current_time - last_log_time >= log_interval:
                    elapsed_time = current_time - start_time
                    orders_per_sec = orders_placed / elapsed_time
                    trades_per_sec = trades_executed / elapsed_time
                    memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024  # MB
                    
                    self.logger.info("Performance Metrics:")
                    self.logger.info(f"Memory Usage: {memory_usage:.2f} MB")
                    self.logger.info(f"Order Throughput: {orders_per_sec:.2f} orders/sec")
                    self.logger.info(f"Trade Throughput: {trades_per_sec:.2f} trades/sec")
                    
                    last_log_time = current_time
                
                time.sleep(self.batch_delay)

        except Exception as e:
            self.logger.error(f"Simulation error: {str(e)}")
        finally:
            self.is_running = False

    def _refill_pools(self):
        """Pre-calculate pools of random values"""
        # Refill participant pool
        self.participant_pool = [random.choice(self.participants) for _ in range(self.participant_pool_size)]
        self.current_participant_index = 0
        
        # Refill price increment pool
        self.price_increment_pool = [
            random.uniform(float(self.min_price_increment), float(self.max_price_increment))
            for _ in range(self.price_increment_pool_size)
        ]
        self.current_price_increment_index = 0
        
        # Refill order size pool
        self.order_size_pool = [
            random.randint(self.order_size_min, self.order_size_max)
            for _ in range(self.order_size_pool_size)
        ]
        self.current_order_size_index = 0

    def _get_next_from_pool(self, pool, size, current_index_attr):
        """Get next item from a pool, refill if needed"""
        current_index = getattr(self, current_index_attr)
        if current_index >= size:
            self._refill_pools()
            current_index = 0
        
        item = pool[current_index]
        setattr(self, current_index_attr, current_index + 1)
        return item

    def _get_next_participant(self):
        """Get next participant from pool"""
        return self._get_next_from_pool(
            self.participant_pool,
            self.participant_pool_size,
            'current_participant_index'
        )

    def _get_next_price_increment(self):
        """Get next price increment from pool"""
        return self._get_next_from_pool(
            self.price_increment_pool,
            self.price_increment_pool_size,
            'current_price_increment_index'
        )

    def _get_next_order_size(self):
        """Get next order size from pool"""
        return self._get_next_from_pool(
            self.order_size_pool,
            self.order_size_pool_size,
            'current_order_size_index'
        )

    def initialize_participants(self):
        """Initialize participants with more funding"""
        self.participants = []
        for i in range(self.num_participants):
            participant_id = f"participant_{i}"
            # Give each participant more initial funding
            self.market.deposit(participant_id, "cash", Decimal("1000000"))
            self.market.deposit(participant_id, self.security_id, Decimal("10000"))
            self.participants.append(participant_id)

        # Pre-fill all random pools
        self._refill_pools()

    def _place_rush_order(self) -> bool:
        if not self.is_running:
            return False

        try:
            # Use cached market depth instead of querying again
            current_price = self.last_trade_price
            if self.cached_depth['asks']:
                current_price = self.cached_depth['asks'][0]['price']
            elif self.cached_depth['bids']:
                current_price = self.cached_depth['bids'][0]['price']

            # Get pre-calculated values from pools
            participant = self._get_next_participant()
            base_increment = self._get_next_price_increment()
            order_size = self._get_next_order_size()
            
            # Use pre-calculated random values for better performance
            is_sell_order = random.random() < 0.5
            wave_orders, wave_multiplier = self.wave_patterns[self.current_wave]
            
            # Use faster float operations
            wave_multiplier = float(wave_multiplier)
            momentum = float(self.momentum)
            current_price_float = float(current_price)
            
            price_increment = base_increment * wave_multiplier * momentum
            if random.random() < 0.5:  # 50% chance for overlap
                price_increment *= -1

            # Calculate final price and size
            price = Decimal(str(current_price_float + price_increment))
            size = Decimal(str(order_size))

            # Place the order
            side = OrderSide.SELL if is_sell_order else OrderSide.BUY
            self.market.place_order(
                owner_id=participant,
                security_id=self.security_id,
                side=side,
                price=price,
                size=size
            )

            # Update wave pattern
            self.orders_in_current_wave += 1
            if self.orders_in_current_wave >= wave_orders:
                self.current_wave = (self.current_wave + 1) % len(self.wave_patterns)
                self.orders_in_current_wave = 0

            # Update stats
            self.stats['volume'] += size
            self.stats['current_price'] = price
            self.stats['highest_price'] = max(self.stats['highest_price'], price)
            if self.stats['start_price'] > 0:
                self.stats['price_movement_percent'] = (
                        (self.stats['current_price'] - self.stats['start_price']) /
                        self.stats['start_price'] * Decimal('100')
                )

            return True

        except Exception as e:
            self.logger.error(f"Order placement failed: {str(e)}")
            return False

    def get_stats(self) -> Dict:
        """Get current simulation statistics"""
        return self.stats.copy()


def run_simulation(enable_market_maker: bool = True):
    # Create and initialize market
    market = Market()
    security_id = 'AAPL'
    market.create_orderbook(security_id)

    if enable_market_maker:
        # Create and start market maker
        maker_id = 'mm001'
        market.deposit(maker_id, 'cash', Decimal('100000000000'))
        market.deposit(maker_id, security_id, Decimal('1000000000'))
        mm = MarketMaker(market, maker_id, [security_id])

    # Create rush simulator with sell orders enabled
    rush = MarketRushSimulator(market, security_id, num_participants=10000, enable_simulated_sellers=True)

    start_time = time.time()  # Start timer

    try:
        # Start both systems
        print("Starting market maker and rush simulation...")
        if enable_market_maker:
            mm.start()
        rush.start_rush(duration_seconds=300)

        # Monitor the simulation
        while rush.is_running:
            elapsed_time = time.time() - start_time

            # Gather stats
            stats = rush.get_stats()
            orders_processed = stats['total_orders']
            trades_executed = market.get_trade_count()

            # Calculate throughput
            order_throughput = orders_processed / elapsed_time if elapsed_time > 0 else 0
            trade_throughput = trades_executed / elapsed_time if elapsed_time > 0 else 0

            # Get memory usage
            memory_usage = get_memory_usage()

            # Display stats
            print("\nRush Statistics:")
            print(f"Total Orders: {stats['total_orders']}")
            print(f"Successful Orders: {stats['successful_orders']}")
            print(f"Failed Orders: {stats['failed_orders']}")
            print(f"Current Price: {stats['current_price']}")
            print(f"Price Movement: {stats['price_movement_percent']:.2f}%")
            print(f"Volume: {stats['volume']}")
            print(f"Total Trades: {trades_executed}")

            # Display performance metrics
            print("\nPerformance Metrics:")
            print(f"Memory Usage: {memory_usage:.2f} MB")
            print(f"Order Throughput: {order_throughput:.2f} orders/sec")
            print(f"Trade Throughput: {trade_throughput:.2f} trades/sec")

            mm_stats = mm.get_market_stats(security_id)
            print("\nMarket Maker Stats:")
            print(f"Position: {mm_stats['position']}")
            print(f"Market Condition: {mm_stats['condition']}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping simulation...")
    finally:
        rush.stop_rush()
        if enable_market_maker:
            mm.stop()
        market.finalize_trades()  # Flush remaining trades
        print("Simulation ended")


if __name__ == "__main__":
    run_simulation()