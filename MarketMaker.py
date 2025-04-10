from decimal import Decimal
from typing import Dict, List, Optional
from time import sleep
import threading
from enum import Enum
import logging
import statistics
from Exchange import Market, OrderSide

#logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - MARKETMAKER - %(message)s')

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
            # Get market state
            depth = self.market.get_market_depth(security)

            # Update price history even if depth is empty
            current_price = None
            if depth and depth.get('asks') and depth['asks']:
                current_price = Decimal(str(depth['asks'][0]['price']))
            elif depth and depth.get('bids') and depth['bids']:
                current_price = Decimal(str(depth['bids'][0]['price']))
            else:
                current_price = self.market_stats[security]['last_price'] or Decimal('100')

            if current_price:
                self.price_history[security].append(current_price)
                if len(self.price_history[security]) > self.price_window:
                    self.price_history[security].pop(0)

            # Update market stats
            self._update_market_stats(security, current_price)

            # Calculate order parameters
            order_params = self._calculate_order_parameters(security, depth)
            if not order_params:
                self.logger.warning(f"Skipping order placement for {security} - no parameters calculated")
                return

            # Place new orders
            self._place_new_orders(security, order_params)

        except Exception as e:
            self.logger.error(f"Error updating security {security}: {str(e)}")

    def _calculate_order_parameters(self, security: str, depth: Dict) -> Optional[Dict]:
        """Calculate order parameters based on market conditions"""
        try:
            stats = self.market_stats[security]
            
            # Convert all numeric inputs to Decimal
            current_price = (
                Decimal(str(depth['asks'][0]['price'])) if depth.get('asks') 
                else Decimal(str(depth['bids'][0]['price'])) if depth.get('bids')
                else stats['last_price'] or Decimal('100')
            )
            
            # Calculate base spread
            volatility_spread = self.min_spread + (stats['volatility'] * Decimal('2'))
            trend_spread = volatility_spread * (Decimal('1') + abs(stats['trend']))
            spread = min(trend_spread, self.max_spread)
            
            # Adjust prices based on market condition
            if stats['condition'] == MarketCondition.BULL_RUN:
                bid_price = current_price * (Decimal('1') - spread * Decimal('0.8'))
                ask_price = current_price * (Decimal('1') + spread * Decimal('1.2'))
            elif stats['condition'] == MarketCondition.BEAR_DIP:
                bid_price = current_price * (Decimal('1') - spread * Decimal('1.2'))
                ask_price = current_price * (Decimal('1') + spread * Decimal('0.8'))
            else:
                bid_price = current_price * (Decimal('1') - spread)
                ask_price = current_price * (Decimal('1') + spread)
            
            # Calculate sizes based on position
            position = self.positions[security]
            max_position = self.max_position * self.position_limit_pct
            position_ratio = abs(position / max_position) if max_position != 0 else Decimal('0')
            
            base_size = self.base_order_size * stats['momentum']
            if position > 0:
                bid_size = base_size * (Decimal('1') - position_ratio)
                ask_size = base_size * (Decimal('1') + position_ratio)
            else:
                bid_size = base_size * (Decimal('1') + abs(position_ratio))
                ask_size = base_size * (Decimal('1') - abs(position_ratio))
            
            return {
                'bid_price': bid_price.quantize(Decimal('0.01')),
                'ask_price': ask_price.quantize(Decimal('0.01')),
                'bid_size': bid_size.quantize(Decimal('0.01')),
                'ask_size': ask_size.quantize(Decimal('0.01'))
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating order parameters: {str(e)}")
            return None

    def _update_market_stats(self, security: str, current_price: Decimal):
        """Update market statistics"""
        stats = self.market_stats[security]
        
        # Update last price
        stats['last_price'] = current_price
        
        # Calculate volatility
        if len(self.price_history[security]) >= 2:
            returns = [
                (Decimal(str(p2)) / Decimal(str(p1))) - Decimal('1')
                for p1, p2 in zip(self.price_history[security][:-1], self.price_history[security][1:])
            ]
            if returns:
                stats['volatility'] = Decimal(str(statistics.stdev([float(r) for r in returns])))
        
        # Calculate trend
        if len(self.price_history[security]) >= 2:
            first_price = Decimal(str(self.price_history[security][0]))
            last_price = Decimal(str(self.price_history[security][-1]))
            stats['trend'] = (last_price / first_price) - Decimal('1')
        
        # Update market condition
        if stats['trend'] > self.trend_threshold:
            stats['condition'] = MarketCondition.BULL_RUN
            stats['momentum'] = Decimal('1') + abs(stats['trend'])
        elif stats['trend'] < -self.trend_threshold:
            stats['condition'] = MarketCondition.BEAR_DIP
            stats['momentum'] = Decimal('1') + abs(stats['trend'])
        else:
            stats['condition'] = MarketCondition.BALANCED
            stats['momentum'] = Decimal('1')

    def _place_new_orders(self, security: str, params: dict):
        """Place new orders with proper error handling"""
        try:
            cash_balance = self._get_cash_balance()
            security_balance = self._get_security_balance(security)
            logging.info(f"{self.maker_id} Balances - Cash: {cash_balance}, Security: {security_balance}")

            if cash_balance <= 0 or security_balance <= 0:
                self.logger.warning(f"Insufficient balances. Cash: {cash_balance}, Security: {security_balance}")
                return

            position = self.positions[security]
            position_limit = self.max_position * self.position_limit_pct
            orders_placed = 0

            # Get current market depth
            depth = self.market.get_market_depth(security)
            current_price = self._get_current_price(depth, security)

            self.logger.info(f"\n{self.maker_id} Placing orders for {security}:")
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
            return Decimal(str(depth['asks'][0]['price']))
        if depth and depth.get('bids') and depth['bids']:
            return Decimal(str(depth['bids'][0]['price']))
        return self.market_stats[security].get('last_price', Decimal('100'))

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