from decimal import Decimal
from typing import Dict, List, Optional
import time
import threading
from enum import Enum
import logging
import statistics
from Exchange import Market, OrderSide

class MarketCondition(Enum):
    BALANCED = "balanced"
    BULL_RUN = "bull_run"
    BEAR_DIP = "bear_dip"

class MarketMaker:
    def __init__(self, market: Market, maker_id: str, securities: List[str]):
        self.market = market
        self.maker_id = maker_id
        self.securities = securities
        self.is_running = False
        self.thread = None
        self.logger = logging.getLogger(__name__)

        # More sensitive configuration parameters
        self.refresh_interval = 0.05  # Faster updates
        self.volatility_threshold = Decimal('0.005')  # More sensitive (0.5% instead of 1%)
        self.max_position = Decimal('50000')  # Larger position limit
        self.min_spread = Decimal('0.001')  # Tighter spreads
        self.max_spread = Decimal('0.03')  # Smaller maximum spread
        self.base_order_size = Decimal('500')  # Larger base size
        self.position_limit_pct = Decimal('0.9')  # Higher position limit

        # Market monitoring parameters
        self.price_window = 10  # Look at last 10 prices for faster response
        self.trend_threshold = Decimal('0.003')  # 0.3% trend detection
        self.momentum_factor = Decimal('1.5')  # Amplify response to trends

        # State tracking
        self.positions = {sec: Decimal('0') for sec in securities}
        self.active_orders = {sec: [] for sec in securities}
        self.price_history = {sec: [] for sec in securities}
        self.market_stats = {sec: {
            'volatility': Decimal('0'),
            'trend': Decimal('0'),
            'last_price': None,
            'condition': MarketCondition.BALANCED,
            'momentum': Decimal('1.0')
        } for sec in securities}

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()
        self.logger.info(f"Market maker {self.maker_id} started")

    def stop(self):
        self.is_running = False
        if self.thread:
            self.thread.join()
        self._cancel_all_orders()
        self.logger.info(f"Market maker {self.maker_id} stopped")

    def _run(self):
        while self.is_running:
            try:
                for security in self.securities:
                    self._update_security(security)
            except Exception as e:
                self.logger.error(f"Error in market maker loop: {str(e)}")
            time.sleep(self.refresh_interval)

    def _update_security(self, security: str):
        """Update market making for a single security"""
        try:
            # Get market state
            depth = self.market.get_market_depth(security)

            # Update price history even if depth is empty
            current_price = None
            if depth and depth.get('asks') and depth['asks']:
                current_price = depth['asks'][0]['price']
            elif depth and depth.get('bids') and depth['bids']:
                current_price = depth['bids'][0]['price']
            else:
                current_price = self.market_stats[security]['last_price'] or Decimal('100')

            if current_price:
                self.price_history[security].append(current_price)
                self.market_stats[security]['last_price'] = current_price

                # Keep only recent price history
                if len(self.price_history[security]) > 50:
                    self.price_history[security].pop(0)

            # Analyze market condition
            condition = self._analyze_market_condition(security)
            old_condition = self.market_stats[security]['condition']
            if condition != old_condition:
                self.logger.info(f"Market condition changed for {security}: {old_condition.value} -> {condition.value}")

            self.market_stats[security]['condition'] = condition

            # Calculate new orders
            params = self._calculate_order_parameters(security, condition)
            if params:
                # Cancel existing orders
                old_orders = len(self.active_orders[security])
                if old_orders > 0:
                    self._cancel_security_orders(security)
                    self.logger.info(f"Cancelled {old_orders} orders for {security}")

                # Place new orders
                self._place_new_orders(security, params)
            else:
                self.logger.warning(f"Skipping order placement for {security} - no parameters calculated")

        except Exception as e:
            self.logger.error(f"Error updating security {security}: {str(e)}")

    def _analyze_market_condition(self, security: str) -> MarketCondition:
        """Enhanced market condition analysis"""
        if not self.price_history[security] or len(self.price_history[security]) < 2:
            return MarketCondition.BALANCED

        try:
            # Use recent price history for faster response
            prices = self.price_history[security][-self.price_window:]
            price_changes = [
                (prices[i] - prices[i - 1]) / prices[i - 1]
                for i in range(1, len(prices))
            ]

            if not price_changes:
                return MarketCondition.BALANCED

            # Calculate trend metrics
            avg_change = sum(price_changes) / len(price_changes)
            recent_volatility = statistics.stdev(price_changes) if len(price_changes) > 1 else Decimal('0')

            # Calculate short-term momentum
            short_term_return = (prices[-1] - prices[0]) / prices[0]

            # Update market stats
            self.market_stats[security]['volatility'] = Decimal(str(recent_volatility))
            self.market_stats[security]['trend'] = Decimal(str(avg_change))

            # Momentum adjustment
            if abs(short_term_return) > self.trend_threshold:
                self.market_stats[security]['momentum'] *= self.momentum_factor
            else:
                self.market_stats[security]['momentum'] = Decimal('1.0')

            # More sensitive market condition detection
            if avg_change > self.volatility_threshold:
                return MarketCondition.BULL_RUN
            elif avg_change < -self.volatility_threshold:
                return MarketCondition.BEAR_DIP

        except Exception as e:
            self.logger.error(f"Error in market condition analysis: {str(e)}")

        return MarketCondition.BALANCED

    def _calculate_order_parameters(self, security: str, condition: MarketCondition):
        """Enhanced order parameter calculation"""
        try:
            depth = self.market.get_market_depth(security)

            # Get or estimate current price
            current_price = self._get_mid_price(depth)
            if not current_price:
                current_price = self.market_stats[security]['last_price'] or Decimal('100')
                self.logger.info(f"Using fallback price: {current_price}")

            stats = self.market_stats[security]
            volatility = stats['volatility']
            trend = stats['trend']

            # Base sizing parameters
            base_size = self.base_order_size
            if condition == MarketCondition.BULL_RUN:
                buy_size = base_size * Decimal('0.5')  # Reduce buying in bull market
                sell_size = base_size * Decimal('2.0')  # Increase selling in bull market
                spread_multiplier = Decimal('1.2')
            elif condition == MarketCondition.BEAR_DIP:
                buy_size = base_size * Decimal('2.0')  # Increase buying in bear market
                sell_size = base_size * Decimal('0.5')  # Reduce selling in bear market
                spread_multiplier = Decimal('1.2')
            else:
                buy_size = sell_size = base_size
                spread_multiplier = Decimal('1.0')

            # Calculate spread based on volatility
            spread = max(
                min(
                    self.min_spread * (1 + volatility * Decimal('10')),
                    self.max_spread
                ),
                self.min_spread
            ) * spread_multiplier

            # Generate price levels
            levels = 3
            buy_prices = []
            sell_prices = []
            buy_sizes = []
            sell_sizes = []

            for i in range(levels):
                level_multiplier = Decimal(str(i + 1))

                # Calculate prices with progressive spreads
                buy_price = current_price * (1 - spread * level_multiplier)
                sell_price = current_price * (1 + spread * level_multiplier)

                # Calculate sizes with decay for further levels
                level_size_multiplier = Decimal('1') / (level_multiplier * Decimal('1.2'))
                buy_level_size = buy_size * level_size_multiplier
                sell_level_size = sell_size * level_size_multiplier

                buy_prices.append(buy_price)
                sell_prices.append(sell_price)
                buy_sizes.append(buy_level_size)
                sell_sizes.append(sell_level_size)

            self.logger.info(f"Calculated order parameters for {security}:")
            self.logger.info(f"Current price: {current_price}")
            self.logger.info(f"Spread: {spread}")
            self.logger.info(f"Buy prices: {buy_prices}")
            self.logger.info(f"Sell prices: {sell_prices}")

            return {
                'buy_prices': buy_prices,
                'sell_prices': sell_prices,
                'buy_sizes': buy_sizes,
                'sell_sizes': sell_sizes
            }

        except Exception as e:
            self.logger.error(f"Error calculating order parameters: {str(e)}")
            return None

    def _get_mid_price(self, depth: dict) -> Optional[Decimal]:
        """Calculate mid price from market depth"""
        try:
            if not depth['bids'] or not depth['asks']:
                return None

            best_bid = depth['bids'][0]['price']
            best_ask = depth['asks'][0]['price']
            return (best_bid + best_ask) / Decimal('2')

        except (KeyError, IndexError):
            return None

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

    def update_position(self, security: str, quantity: Decimal):
        """Update position after trade execution"""
        self.positions[security] += quantity

    def get_position(self, security: str) -> Decimal:
        """Get current position for a security"""
        return self.positions[security]

    def get_market_stats(self, security_id: str) -> Dict:
        """Get current market making statistics"""
        return {
            'position': self.positions[security_id],
            'condition': self.market_stats[security_id]['condition'].value,
            'last_price': self.market_stats[security_id]['last_price']
        }

    def process_trade(self, security: str, trade_info: dict):
        """Process a completed trade and update positions"""
        try:
            # Log trade details
            self.logger.info(f"Processing trade for {security}: {trade_info}")

            # Update position based on trade
            if trade_info['buyer_id'] == self.maker_id:
                self.positions[security] += trade_info['size']
                self.logger.info(f"Position increased by {trade_info['size']}")
            elif trade_info['seller_id'] == self.maker_id:
                self.positions[security] -= trade_info['size']
                self.logger.info(f"Position decreased by {trade_info['size']}")

            # Log new position
            self.logger.info(f"New position for {security}: {self.positions[security]}")

            # Update market stats
            self.market_stats[security]['last_price'] = trade_info['price']

            # Calculate P&L if needed
            # ... (add P&L tracking if desired)

        except Exception as e:
            self.logger.error(f"Error processing trade: {str(e)}")

    def get_detailed_stats(self, security_id: str) -> Dict:
        """Get detailed market making statistics"""
        stats = {
            'position': self.positions[security_id],
            'condition': self.market_stats[security_id]['condition'].value,
            'last_price': self.market_stats[security_id]['last_price'],
            'active_orders': len(self.active_orders[security_id]),
            'price_history_length': len(self.price_history[security_id]),
            'volatility': float(self.market_stats[security_id]['volatility']),
            'trend': float(self.market_stats[security_id]['trend'])
        }

        if security_id in self.price_history and self.price_history[security_id]:
            stats['price_change'] = float(
                (self.price_history[security_id][-1] - self.price_history[security_id][0]) /
                self.price_history[security_id][0] * 100
            )
        else:
            stats['price_change'] = 0.0

        return stats

    def _place_new_orders(self, security: str, params: dict):
        """Place new orders based on calculated parameters"""
        try:
            position = self.positions[security]
            position_limit = self.max_position * self.position_limit_pct
            orders_placed = 0

            # Place buy orders if we have room
            if position < position_limit:
                for price, size in zip(params['buy_prices'], params['buy_sizes']):
                    adjusted_size = min(size, (position_limit - position))
                    if adjusted_size > 0:
                        try:
                            self.logger.info(f"Placing buy order: price={price}, size={adjusted_size}")
                            order_id = self.market.place_order(
                                self.maker_id,
                                security,
                                OrderSide.BUY,
                                price,
                                adjusted_size
                            )
                            if order_id:
                                self.active_orders[security].append(order_id)
                                orders_placed += 1
                                self.logger.info(f"Buy order placed successfully: {order_id}")
                        except Exception as e:
                            self.logger.error(f"Error placing buy order: {str(e)}")

            # Place sell orders if we have room
            if position > -position_limit:
                for price, size in zip(params['sell_prices'], params['sell_sizes']):
                    adjusted_size = min(size, (position_limit + position))
                    if adjusted_size > 0:
                        try:
                            self.logger.info(f"Placing sell order: price={price}, size={adjusted_size}")
                            order_id = self.market.place_order(
                                self.maker_id,
                                security,
                                OrderSide.SELL,
                                price,
                                adjusted_size
                            )
                            if order_id:
                                self.active_orders[security].append(order_id)
                                orders_placed += 1
                                self.logger.info(f"Sell order placed successfully: {order_id}")
                        except Exception as e:
                            self.logger.error(f"Error placing sell order: {str(e)}")

            self.logger.info(f"Placed {orders_placed} new orders for {security}")

        except Exception as e:
            self.logger.error(f"Error in place_new_orders: {str(e)}")

if __name__ == "__main__":
    # Example usage
    market = Market()
    market.create_orderbook('AAPL')

    maker_id = 'mm001'
    market.deposit(maker_id, 'cash', Decimal('1000000'))
    market.deposit(maker_id, 'AAPL', Decimal('10000'))

    mm = MarketMaker(market, maker_id, ['AAPL'])

    try:
        mm.start()
        while True:
            stats = mm.get_market_stats('AAPL')
            print(f"\nMarket Maker Stats:")
            print(f"Position: {stats['position']}")
            print(f"Market Condition: {stats['condition']}")
            print(f"Last Price: {stats['last_price']}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nStopping market maker...")
        mm.stop()