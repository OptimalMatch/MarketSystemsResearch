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

class MarketRushSimulator:
    def __init__(self, market: Market, security_id: str, num_participants: int = 10000):
        self.market = market
        self.security_id = security_id
        self.num_participants = num_participants
        self.is_running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)
        self.price_queue = queue.Queue()
        self.executor = None

        # More controlled price configuration
        self.min_price_increment = Decimal('0.05')  # 5 cents minimum
        self.max_price_increment = Decimal('0.25')  # 25 cents maximum
        self.order_size_min = 10  # Minimum order size
        self.order_size_max = 100  # Maximum order size
        self.aggressive_order_probability = 0.3  # 30% aggressive orders

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
        self.executor = ThreadPoolExecutor(max_workers=50)

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

        try:
            while time.time() < end_time and self.is_running:
                # Get current market price
                try:
                    depth = self.market.get_market_depth(self.security_id)
                    if depth['asks']:
                        self.last_trade_price = depth['asks'][0]['price']
                        self.stats['current_price'] = self.last_trade_price
                except Exception as e:
                    self.logger.error(f"Error getting market depth: {str(e)}")

                # Submit batch of orders
                futures = []
                for _ in range(50):  # Submit 50 orders at a time
                    if not self.is_running:
                        break
                    futures.append(
                        self.executor.submit(self._place_rush_order)
                    )

                # Process completed orders
                for future in futures:
                    if not self.is_running:
                        break
                    try:
                        success = future.result(timeout=1.0)
                        if success:
                            self.stats['successful_orders'] += 1
                        else:
                            self.stats['failed_orders'] += 1
                        self.stats['total_orders'] += 1
                    except Exception as e:
                        self.logger.error(f"Error processing order: {str(e)}")
                        self.stats['failed_orders'] += 1
                        self.stats['total_orders'] += 1

                time.sleep(0.1)  # Small delay between batches

        except Exception as e:
            self.logger.error(f"Simulation error: {str(e)}")
        finally:
            self.is_running = False

    def _place_rush_order(self) -> bool:
        if not self.is_running:
            return False

        try:
            participant = random.choice(self.participants)

            # Get current market depth
            depth = self.market.get_market_depth(self.security_id)
            if depth['asks']:
                current_price = depth['asks'][0]['price']
            else:
                current_price = self.last_trade_price

            # Apply controlled momentum - convert to Decimal
            self.momentum += self.momentum_increment
            self.momentum = min(max(self.momentum, self.min_momentum), self.max_momentum)

            # Determine if this should be an aggressive order
            is_aggressive = random.random() < float(self.aggressive_order_probability)

            # Calculate price increment using Decimal throughout
            wave_orders, wave_multiplier = self.wave_patterns[self.current_wave]
            base_increment = Decimal(str(random.uniform(
                float(self.min_price_increment),
                float(self.max_price_increment)
            )))

            wave_multiplier = Decimal(str(wave_multiplier))  # Convert to Decimal

            # Calculate controlled price increment
            if is_aggressive:
                price_increment = base_increment * wave_multiplier * self.momentum
            else:
                price_increment = base_increment * wave_multiplier

            # Ensure reasonable price movement
            max_increment = current_price * Decimal('0.01')  # Max 1% move per order
            price_increment = min(price_increment, max_increment)

            # Calculate buy price
            buy_price = current_price + price_increment

            # Calculate reasonable size - convert to Decimal
            if is_aggressive:
                size = Decimal(str(random.randint(
                    int(float(self.order_size_max)) // 2,
                    int(float(self.order_size_max))
                )))
            else:
                size = Decimal(str(random.randint(
                    int(float(self.order_size_min)),
                    int(float(self.order_size_max)) // 2
                )))

            # Place the order
            self.market.place_order(
                owner_id=participant,
                security_id=self.security_id,
                side=OrderSide.BUY,
                price=buy_price,
                size=size
            )

            # Update wave pattern
            self.orders_in_current_wave += 1
            if self.orders_in_current_wave >= wave_orders:
                self.current_wave = (self.current_wave + 1) % len(self.wave_patterns)
                self.orders_in_current_wave = 0

            # Update stats
            self.stats['current_price'] = buy_price
            self.stats['highest_price'] = max(self.stats['highest_price'], buy_price)
            self.stats['volume'] += size

            if self.stats['start_price'] > 0:
                self.stats['price_movement_percent'] = (
                        (buy_price - self.stats['start_price']) /
                        self.stats['start_price'] * Decimal('100')
                )

            return True

        except Exception as e:
            self.logger.error(f"Order placement failed: {str(e)}")
            return False

    def initialize_participants(self):
        """Initialize participants with more funding"""
        self.participants = [f'rush_trader_{i}' for i in range(self.num_participants)]
        logging.debug(f"Initializing {len(self.participants)} participants")

        for participant in self.participants:
            try:
                self.market.deposit(participant, 'cash', Decimal('100000000'))
                self.market.deposit(participant, self.security_id, Decimal('1000000'))
            except Exception as e:
                self.logger.error(f"Error funding participant {participant}: {str(e)}")

    def get_stats(self) -> Dict:
        """Get current simulation statistics"""
        return self.stats.copy()


def run_simulation():
    # Create and initialize market
    market = Market()
    security_id = 'AAPL'
    market.create_orderbook(security_id)

    # Create and start market maker
    maker_id = 'mm001'
    market.deposit(maker_id, 'cash', Decimal('100000000000'))
    market.deposit(maker_id, security_id, Decimal('1000000000'))
    mm = MarketMaker(market, maker_id, [security_id])

    # Create rush simulator
    rush = MarketRushSimulator(market, security_id, num_participants=10000)

    try:
        # Start both systems
        print("Starting market maker and rush simulation...")
        mm.start()
        rush.start_rush(duration_seconds=300)

        # Monitor the simulation
        while rush.is_running:
            stats = rush.get_stats()
            print("\nRush Statistics:")
            print(f"Total Orders: {stats['total_orders']}")
            print(f"Successful Orders: {stats['successful_orders']}")
            print(f"Failed Orders: {stats['failed_orders']}")
            print(f"Current Price: {stats['current_price']}")
            print(f"Price Movement: {stats['price_movement_percent']:.2f}%")
            print(f"Volume: {stats['volume']}")

            mm_stats = mm.get_market_stats(security_id)
            print("\nMarket Maker Stats:")
            print(f"Position: {mm_stats['position']}")
            print(f"Market Condition: {mm_stats['condition']}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping simulation...")
    finally:
        rush.stop_rush()
        mm.stop()
        print("Simulation ended")


if __name__ == "__main__":
    run_simulation()