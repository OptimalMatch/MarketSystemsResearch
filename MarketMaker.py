from decimal import Decimal
from typing import Dict, List, Optional
#import time
from time import sleep
import threading
from enum import Enum
import logging
import statistics
from Exchange import Market, OrderSide

#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - MARKETMAKER - %(message)s')

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

        # More aggressive configuration
        self.refresh_interval = 0.05  # Faster updates
        self.volatility_threshold = Decimal('0.002')  # More sensitive (0.2%)
        self.max_position = Decimal('100000')  # Much larger position limit
        self.min_spread = Decimal('0.0005')  # Tighter spreads (0.05%)
        self.max_spread = Decimal('0.02')  # Smaller maximum spread (2%)
        self.base_order_size = Decimal('1000')  # Larger base size
        self.position_limit_pct = Decimal('0.95')  # Higher position limit

        # Market monitoring
        self.price_window = 5  # Look at last 5 prices for faster response
        self.trend_threshold = Decimal('0.001')  # More sensitive trend detection
        self.momentum_factor = Decimal('1.5')  # Stronger momentum response

        # Initialize state
        self.positions = {sec: Decimal('0') for sec in securities}
        self.active_orders = {sec: [] for sec in securities}
        self.price_history = {sec: [] for sec in securities}
        self.market_stats = {sec: {
            'volatility': Decimal('0'),
            'trend': Decimal('0'),
            'last_price': None,
            'condition': MarketCondition.BALANCED,
            'momentum': Decimal('1.0'),
            'trades_count': 0,
            'last_trade_time': None,
            'total_volume': Decimal('0')
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
            sleep(self.refresh_interval)

    def _update_security(self, security: str):
        """Update market making for a single security"""
        try:
            # Log active orders before update
            active_orders = self.active_orders.get(security, [])
            logging.debug(f"Active orders for {security}: {active_orders}")

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

            # Log active orders after placing new ones
            active_orders_after = self.active_orders.get(security, [])
            logging.debug(f"Active orders for {security} after update: {active_orders_after}")
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
            logging.debug(f"Market Depth for {security}: {depth}")

            # Get or estimate current price
            current_price = self._get_mid_price(depth)
            logging.debug(f"Calculated current price for {security}: {current_price}")
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

            params = {
                'buy_prices': buy_prices,
                'sell_prices': sell_prices,
                'buy_sizes': buy_sizes,
                'sell_sizes': sell_sizes
            }
            logging.debug(f"Order parameters for {security}: {params}")
            return params

        except Exception as e:
            self.logger.error(f"Error calculating order parameters: {str(e)}")
            return None

    def _get_mid_price(self, depth: dict) -> Optional[Decimal]:
        """Calculate mid price from market depth"""
        try:
            logging.debug(f"Market Depth for {depth}: {depth}")
            if not depth['bids'] or not depth['asks']:
                return None
            best_bid = depth['bids'][0]['price']
            best_ask = depth['asks'][0]['price']
            return (best_bid + best_ask) / Decimal('2')
        except (KeyError, IndexError) as e:
            logging.error(f"Error accessing market depth: {e}")
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
        """Place new orders with proper error handling"""
        try:
            cash_balance = self._get_cash_balance()
            security_balance = self._get_security_balance(security)
            logging.debug(f"Balances - Cash: {cash_balance}, Security: {security_balance}")

            if cash_balance <= 0 or security_balance <= 0:
                self.logger.warning(f"Insufficient balances. Cash: {cash_balance}, Security: {security_balance}")
                return

            position = self.positions[security]
            position_limit = self.max_position * self.position_limit_pct
            orders_placed = 0

            # Get current market depth
            depth = self.market.get_market_depth(security)
            current_price = self._get_current_price(depth, security)

            self.logger.info(f"\nPlacing orders for {security}:")
            self.logger.info(f"Current price: {current_price}")
            self.logger.info(f"Current position: {position}")

            # Check balances
            cash_balance = self._get_cash_balance()
            security_balance = self._get_security_balance(security)

            if cash_balance <= 0 or security_balance <= 0:
                self.logger.warning("Insufficient balance for order placement")
                return

            # Calculate safe order sizes
            max_order_size = min(
                Decimal('100'),  # Base size
                cash_balance / current_price / Decimal('10'),  # 10% of cash
                security_balance / Decimal('10')  # 10% of security balance
            )

            # Generate order levels
            spread = Decimal('0.001')  # 0.1% spread
            levels = 3

            for i in range(levels):
                level_factor = Decimal(str(i + 1))
                size_factor = Decimal('1') / level_factor

                # Calculate buy parameters
                buy_size = max_order_size * size_factor
                buy_price = current_price * (Decimal('1') - spread * level_factor)

                # Calculate sell parameters
                sell_size = max_order_size * size_factor
                sell_price = current_price * (Decimal('1') + spread * level_factor)

                # Place buy order if we have room
                if position < position_limit:
                    try:
                        adjusted_buy_size = min(buy_size, (position_limit - position))
                        if adjusted_buy_size > 0:
                            self.logger.info(f"Placing buy order: {adjusted_buy_size} @ {buy_price}")
                            order_id = self.market.place_order(
                                self.maker_id,
                                security,
                                OrderSide.BUY,
                                buy_price,
                                adjusted_buy_size
                            )
                            if order_id:
                                self.active_orders[security].append(order_id)
                                position += adjusted_buy_size
                                orders_placed += 1
                    except Exception as e:
                        self.logger.error(f"Error placing buy order: {str(e)}")

                # Place sell order if we have room
                if position > -position_limit:
                    try:
                        adjusted_sell_size = min(sell_size, (position_limit + position))
                        if adjusted_sell_size > 0:
                            self.logger.info(f"Placing sell order: {adjusted_sell_size} @ {sell_price}")
                            order_id = self.market.place_order(
                                self.maker_id,
                                security,
                                OrderSide.SELL,
                                sell_price,
                                adjusted_sell_size
                            )
                            if order_id:
                                self.active_orders[security].append(order_id)
                                position -= adjusted_sell_size
                                orders_placed += 1
                    except Exception as e:
                        self.logger.error(f"Error placing sell order: {str(e)}")

            self.logger.info(f"Successfully placed {orders_placed} orders")
            self.positions[security] = position

        except Exception as e:
            self.logger.error(f"Error in place_new_orders: {str(e)}")

    def _get_cash_balance(self) -> Decimal:
        """Get available cash balance"""
        try:
            balance = self.market.balances.get(self.maker_id, {}).get('cash', Decimal('0'))
            return balance
        except Exception as e:
            self.logger.error(f"Error getting cash balance: {str(e)}")
            return Decimal('0')

    def _get_security_balance(self, security: str) -> Decimal:
        """Get available security balance"""
        try:
            balance = self.market.balances.get(self.maker_id, {}).get(security, Decimal('0'))
            return balance
        except Exception as e:
            self.logger.error(f"Error getting security balance: {str(e)}")
            return Decimal('0')

    def _get_current_price(self, depth: dict, security: str) -> Decimal:
        """Get current price with fallbacks"""
        if depth and depth.get('asks') and depth['asks']:
            return depth['asks'][0]['price']
        if depth and depth.get('bids') and depth['bids']:
            return depth['bids'][0]['price']
        return self.market_stats[security].get('last_price', Decimal('100'))

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