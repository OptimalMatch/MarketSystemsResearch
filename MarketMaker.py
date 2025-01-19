from decimal import Decimal
from random import random
from typing import Dict, List, Optional
import time
import threading
from enum import Enum
import logging
import statistics
from datetime import datetime, timedelta


class MarketCondition(Enum):
    BALANCED = "balanced"
    BULL_RUN = "bull_run"
    BEAR_DIP = "bear_dip"


class MarketMaker:
    def __init__(self, market, maker_id: str, securities: List[str]):
        self.market = market
        self.maker_id = maker_id
        self.securities = securities
        self.is_running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)

        # Configuration parameters
        self.spread_target = Decimal('0.02')  # 2% target spread
        self.max_position = Decimal('1000')  # Maximum position size
        self.min_order_size = Decimal('10')
        self.max_order_size = Decimal('100')
        self.price_levels = 3  # Number of price levels to maintain
        self.refresh_interval = 1.0  # Seconds between updates

        # Market making state
        self.positions: Dict[str, Decimal] = {sec: Decimal('0') for sec in securities}
        self.active_orders: Dict[str, List[str]] = {sec: [] for sec in securities}
        self.price_history: Dict[str, List[tuple]] = {sec: [] for sec in securities}

        # More aggressive price configuration
        self.min_price_increment = Decimal('2.0')  # Increased from 0.5
        self.max_price_increment = Decimal('5.0')  # Increased from 2.0
        self.order_size_min = 50  # Increased from 10
        self.order_size_max = 500  # Increased from 100
        self.aggressive_order_probability = 0.6  # Increased from 0.3

        # Track the last trade price
        self.last_trade_price = Decimal('100')
        self.initial_price = self.last_trade_price

        # Trading patterns for stronger momentum
        self.wave_patterns = [
            (100, 1.0),  # Warmup phase
            (200, 1.5),  # Building momentum
            (300, 2.0),  # Strong momentum
            (400, 2.5),  # Peak momentum
            (200, 2.0),  # Sustained pressure
            (100, 1.5),  # Cooling phase
        ]

        # Add momentum tracking
        self.momentum = 1.0
        self.momentum_increment = 0.1
        self.max_momentum = 3.0

    def start(self):
        """Start the market making algorithm"""
        if self.is_running:
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.start()
        self.logger.info(f"Market maker {self.maker_id} started")

    def stop(self):
        """Stop the market making algorithm"""
        self.is_running = False
        if self.thread:
            self.thread.join()
        self._cancel_all_orders()
        self.logger.info(f"Market maker {self.maker_id} stopped")

    def _run(self):
        """Main market making loop"""
        while self.is_running:
            try:
                for security in self.securities:
                    self._update_security(security)
            except Exception as e:
                self.logger.error(f"Error in market making loop: {str(e)}")

            time.sleep(self.refresh_interval)

    def _place_rush_order(self) -> bool:
        if not self.is_running:
            return False

        try:
            participant = random.choice(self.participants)

            # Get current market depth
            depth = self.market.get_market_depth(self.security_id)
            if depth['asks']:
                current_ask = depth['asks'][0]['price']
                self.last_trade_price = current_ask
            else:
                current_ask = self.last_trade_price

            # Increase momentum with successful trades
            self.momentum = min(self.momentum + self.momentum_increment, self.max_momentum)

            # Determine if this should be an aggressive order
            is_aggressive = random.random() < self.aggressive_order_probability

            # Calculate price increment based on wave pattern and momentum
            wave_orders, wave_multiplier = self.wave_patterns[self.current_wave]
            base_increment = random.uniform(
                float(self.min_price_increment),
                float(self.max_price_increment)
            )

            # Apply momentum to price increment
            if is_aggressive:
                price_increment = Decimal(str(base_increment * wave_multiplier * self.momentum * 2))
            else:
                price_increment = Decimal(str(base_increment * wave_multiplier * self.momentum))

            # Calculate buy price above current ask
            buy_price = current_ask + price_increment

            # Calculate size based on aggressiveness and momentum
            if is_aggressive:
                size = Decimal(str(random.randint(
                    self.order_size_max // 2,
                    int(self.order_size_max * self.momentum)
                )))
            else:
                size = Decimal(str(random.randint(
                    self.order_size_min,
                    self.order_size_max // 2
                )))

            # Place the order
            self.market.place_order(
                owner_id=participant,
                security_id=self.security_id,
                side=OrderSide.BUY,
                price=buy_price,
                size=size
            )

            # Update wave pattern with faster progression
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
                        self.stats['start_price'] * 100
                )

            return True

        except Exception as e:
            self.logger.error(f"Order placement failed: {str(e)}")
            return False

    def initialize_participants(self):
        """Initialize participants with much more funding"""
        self.participants = [f'rush_trader_{i}' for i in range(self.num_participants)]

        for participant in self.participants:
            try:
                # Increased funding for more aggressive trading
                self.market.deposit(participant, 'cash', Decimal('10000000'))
                self.market.deposit(participant, self.security_id, Decimal('100000'))
            except Exception as e:
                self.logger.error(f"Error funding participant {participant}: {str(e)}")

    def _update_security(self, security: str):
        """Update market making for a single security"""
        # Get current market state
        depth = self.market.get_market_depth(security)
        condition = self._analyze_market_condition(security, depth)

        # Update price history
        current_price = self._get_mid_price(depth)
        if current_price:
            self.price_history[security].append((datetime.now(), current_price))
            # Keep only last hour of price history
            cutoff = datetime.now() - timedelta(hours=1)
            self.price_history[security] = [
                (t, p) for t, p in self.price_history[security]
                if t > cutoff
            ]

        # Cancel existing orders
        self._cancel_security_orders(security)

        # Calculate new order parameters based on market condition
        params = self._calculate_order_params(security, depth, condition)
        if not params:
            return

        # Place new orders
        self._place_orders(security, params)

    def _analyze_market_condition(self, security: str, depth: dict) -> MarketCondition:
        """Analyze current market condition"""
        if not self.price_history[security]:
            return MarketCondition.BALANCED

        # Calculate price volatility
        recent_prices = [p for _, p in self.price_history[security][-10:]]
        if len(recent_prices) < 2:
            return MarketCondition.BALANCED

        price_changes = [
            (recent_prices[i] - recent_prices[i - 1]) / recent_prices[i - 1]
            for i in range(1, len(recent_prices))
        ]

        avg_change = statistics.mean(price_changes)

        # Detect market condition based on recent price movement
        if avg_change > Decimal('0.01'):  # 1% average increase
            return MarketCondition.BULL_RUN
        elif avg_change < Decimal('-0.01'):  # 1% average decrease
            return MarketCondition.BEAR_DIP
        else:
            return MarketCondition.BALANCED

    def _calculate_order_params(self, security: str, depth: dict,
                                condition: MarketCondition) -> Optional[Dict]:
        """Calculate order parameters based on market condition"""
        mid_price = self._get_mid_price(depth)
        if not mid_price:
            return None

        params = {
            'spread': self.spread_target,
            'sizes': [],
            'prices': []
        }

        # Adjust parameters based on market condition
        if condition == MarketCondition.BULL_RUN:
            # Provide more selling liquidity during bull runs
            params['spread'] = self.spread_target * Decimal('0.8')  # Tighter spread
            sell_sizes = [self.max_order_size] * self.price_levels
            buy_sizes = [self.min_order_size] * self.price_levels

            # Price levels above current price
            sell_prices = [
                mid_price * (1 + params['spread'] * (i + 1))
                for i in range(self.price_levels)
            ]
            # Price levels below current price
            buy_prices = [
                mid_price * (1 - params['spread'] * (i + 1) * Decimal('1.5'))
                for i in range(self.price_levels)
            ]

        elif condition == MarketCondition.BEAR_DIP:
            # Provide more buying liquidity during dips
            params['spread'] = self.spread_target * Decimal('0.8')
            sell_sizes = [self.min_order_size] * self.price_levels
            buy_sizes = [self.max_order_size] * self.price_levels

            sell_prices = [
                mid_price * (1 + params['spread'] * (i + 1) * Decimal('1.5'))
                for i in range(self.price_levels)
            ]
            buy_prices = [
                mid_price * (1 - params['spread'] * (i + 1))
                for i in range(self.price_levels)
            ]

        else:  # BALANCED
            params['spread'] = self.spread_target
            size = (self.min_order_size + self.max_order_size) / 2
            sell_sizes = [size] * self.price_levels
            buy_sizes = [size] * self.price_levels

            sell_prices = [
                mid_price * (1 + params['spread'] * (i + 1))
                for i in range(self.price_levels)
            ]
            buy_prices = [
                mid_price * (1 - params['spread'] * (i + 1))
                for i in range(self.price_levels)
            ]

        params['sizes'] = list(zip(buy_sizes, sell_sizes))
        params['prices'] = list(zip(buy_prices, sell_prices))

        return params

    def _place_orders(self, security: str, params: Dict):
        """Place new orders based on calculated parameters"""
        for (buy_size, sell_size), (buy_price, sell_price) in zip(
                params['sizes'], params['prices']):

            # Check position limits
            if abs(self.positions[security]) < self.max_position:
                try:
                    # Place buy order
                    order_id = self.market.place_order(
                        self.maker_id, security, OrderSide.BUY, buy_price, buy_size
                    )
                    self.active_orders[security].append(order_id)

                    # Place sell order
                    order_id = self.market.place_order(
                        self.maker_id, security, OrderSide.SELL, sell_price, sell_size
                    )
                    self.active_orders[security].append(order_id)
                except Exception as e:
                    self.logger.error(f"Error placing orders: {str(e)}")

    def _cancel_security_orders(self, security: str):
        """Cancel all active orders for a security"""
        for order_id in self.active_orders[security]:
            try:
                self.market.cancel_order(security, order_id)
            except Exception as e:
                self.logger.error(f"Error canceling order {order_id}: {str(e)}")
        self.active_orders[security].clear()

    def _cancel_all_orders(self):
        """Cancel all active orders across all securities"""
        for security in self.securities:
            self._cancel_security_orders(security)

    def _get_mid_price(self, depth: dict) -> Optional[Decimal]:
        """Calculate mid price from market depth"""
        if not depth['bids'] or not depth['asks']:
            return None

        best_bid = depth['bids'][0]['price']
        best_ask = depth['asks'][0]['price']
        return (best_bid + best_ask) / 2

    def update_position(self, security: str, quantity: Decimal):
        """Update position after trade execution"""
        self.positions[security] += quantity

    def get_position(self, security: str) -> Decimal:
        """Get current position for a security"""
        return self.positions[security]

    def get_market_stats(self, security: str) -> Dict:
        """Get current market making statistics"""
        return {
            'position': self.positions[security],
            'active_orders': len(self.active_orders[security]),
            'last_price': self._get_mid_price(
                self.market.get_market_depth(security)
            ),
            'condition': self._analyze_market_condition(
                security,
                self.market.get_market_depth(security)
            ).value
        }


# Example usage
if __name__ == "__main__":
    from Exchange import Market, OrderSide

    # Create market and initialize
    market = Market()
    market.create_orderbook('AAPL')

    # Create and start market maker
    maker_id = 'mm001'
    market.deposit(maker_id, 'cash', Decimal('1000000'))
    market.deposit(maker_id, 'AAPL', Decimal('10000'))

    mm = MarketMaker(market, maker_id, ['AAPL'])

    try:
        mm.start()

        # Monitor market maker activity
        while True:
            stats = mm.get_market_stats('AAPL')
            print(f"\nMarket Maker Stats:")
            print(f"Position: {stats['position']}")
            print(f"Active Orders: {stats['active_orders']}")
            print(f"Last Price: {stats['last_price']}")
            print(f"Market Condition: {stats['condition']}")
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping market maker...")
        mm.stop()