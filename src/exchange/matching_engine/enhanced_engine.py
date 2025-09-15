"""
Enhanced Matching Engine with Advanced Order Types Support
Integrates stop-loss, trailing stops, iceberg orders, and market making
"""

import heapq
from typing import Dict, List, Tuple, Optional
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from order_types.advanced_orders import (
    AdvancedOrderManager, StopLossOrder, TrailingStopOrder,
    IcebergOrder, TakeProfitOrder, OCOOrder
)
from market_making.market_maker import MarketMaker, MarketMakerConfig, MarketMakingStrategy

logger = logging.getLogger(__name__)


@dataclass(order=True)
class EnhancedOrder:
    """Enhanced order with priority queue ordering and advanced features"""
    price: float = field(compare=True)
    timestamp: int = field(compare=True)
    order_id: int = field(compare=False)
    side: str = field(compare=False)
    quantity: float = field(compare=False)
    user_id: int = field(compare=False)
    order_type: str = field(compare=False, default="limit")
    parent_order_id: Optional[str] = field(compare=False, default=None)  # For iceberg slices
    metadata: Dict = field(compare=False, default_factory=dict)


class EnhancedMatchingEngine:
    """Ultra-fast matching engine with advanced order types support"""

    def __init__(self, symbol: str = "DEC/USD"):
        self.symbol = symbol
        self.buy_orders = []  # Max heap (negative prices)
        self.sell_orders = []  # Min heap
        self.order_id_counter = 1
        self.timestamp_counter = 1
        self.trades = []
        self.last_price = None
        self.current_price = None

        # Advanced order managers
        self.advanced_orders = AdvancedOrderManager()
        self.market_makers: Dict[str, MarketMaker] = {}

        # Order tracking
        self.active_orders: Dict[int, EnhancedOrder] = {}
        self.order_map: Dict[str, int] = {}  # External ID -> Internal ID

        # Market data
        self.price_history = []
        self.volume_24h = Decimal(0)
        self.high_24h = None
        self.low_24h = None

    def place_order(self, side: str, price: float, quantity: float,
                   user_id: int = 0, order_type: str = "limit",
                   stop_price: Optional[float] = None,
                   trail_amount: Optional[float] = None,
                   trail_percent: Optional[float] = None,
                   display_quantity: Optional[float] = None,
                   external_id: Optional[str] = None,
                   metadata: Optional[Dict] = None) -> Tuple[int, List[dict], Optional[str]]:
        """
        Place an order with support for advanced order types.
        Returns (order_id, trades, external_order_id)
        """

        # Generate IDs
        order_id = self.order_id_counter
        self.order_id_counter += 1
        timestamp = self.timestamp_counter
        self.timestamp_counter += 1

        external_order_id = external_id or f"ORD_{order_id}"

        # Handle different order types
        if order_type == "stop_loss" and stop_price is not None:
            stop_order = StopLossOrder(
                order_id=external_order_id,
                user_id=str(user_id),
                symbol=self.symbol,
                side=side,
                quantity=Decimal(quantity),
                stop_price=Decimal(stop_price),
                limit_price=Decimal(price) if price else None
            )
            self.advanced_orders.add_stop_loss(stop_order)
            logger.info(f"Stop-loss order placed: {external_order_id}")
            return order_id, [], external_order_id

        elif order_type == "trailing_stop":
            trailing_order = TrailingStopOrder(
                order_id=external_order_id,
                user_id=str(user_id),
                symbol=self.symbol,
                side=side,
                quantity=Decimal(quantity),
                trail_amount=Decimal(trail_amount) if trail_amount else None,
                trail_percent=Decimal(trail_percent) if trail_percent else None
            )
            self.advanced_orders.add_trailing_stop(trailing_order)
            logger.info(f"Trailing stop order placed: {external_order_id}")
            return order_id, [], external_order_id

        elif order_type == "iceberg" and display_quantity:
            iceberg_order = IcebergOrder(
                order_id=external_order_id,
                user_id=str(user_id),
                symbol=self.symbol,
                side=side,
                total_quantity=Decimal(quantity),
                display_quantity=Decimal(display_quantity),
                price=Decimal(price)
            )
            self.advanced_orders.add_iceberg(iceberg_order)

            # Place the first visible slice
            slice_info = self.advanced_orders.get_iceberg_slice(external_order_id)
            if slice_info:
                result = self._place_limit_order(
                    side, price, float(slice_info["quantity"]),
                    user_id, order_id, timestamp,
                    parent_order_id=external_order_id,
                    metadata={"iceberg": True, "parent": external_order_id}
                )
                return result + (external_order_id,)
            return order_id, [], external_order_id

        elif order_type == "take_profit" and stop_price:
            tp_order = TakeProfitOrder(
                order_id=external_order_id,
                user_id=str(user_id),
                symbol=self.symbol,
                side=side,
                quantity=Decimal(quantity),
                target_price=Decimal(stop_price),
                limit_price=Decimal(price) if price else None
            )
            self.advanced_orders.add_take_profit(tp_order)
            logger.info(f"Take-profit order placed: {external_order_id}")
            return order_id, [], external_order_id

        else:
            # Regular limit or market order
            return self._place_limit_order(
                side, price, quantity, user_id,
                order_id, timestamp, metadata=metadata
            ) + (external_order_id,)

    def _place_limit_order(self, side: str, price: float, quantity: float,
                          user_id: int, order_id: int, timestamp: int,
                          parent_order_id: Optional[str] = None,
                          metadata: Optional[Dict] = None) -> Tuple[int, List[dict]]:
        """Place a regular limit order and perform matching"""
        order = EnhancedOrder(
            price=price,
            timestamp=timestamp,
            order_id=order_id,
            side=side,
            quantity=quantity,
            user_id=user_id,
            order_type="limit",
            parent_order_id=parent_order_id,
            metadata=metadata or {}
        )

        trades = []

        if side == "buy":
            # Try to match with sell orders
            while self.sell_orders and quantity > 0:
                best_sell = self.sell_orders[0]

                if price >= best_sell.price:
                    # Match found
                    trade_quantity = min(quantity, best_sell.quantity)
                    trade_price = best_sell.price

                    trades.append({
                        "buyer_id": user_id,
                        "seller_id": best_sell.user_id,
                        "price": trade_price,
                        "quantity": trade_quantity,
                        "timestamp": timestamp,
                        "buyer_order": order_id,
                        "seller_order": best_sell.order_id
                    })

                    quantity -= trade_quantity
                    best_sell.quantity -= trade_quantity
                    self.last_price = trade_price
                    self.current_price = trade_price

                    # Handle iceberg order refill
                    if best_sell.parent_order_id:
                        self._handle_iceberg_execution(best_sell.parent_order_id, trade_quantity)

                    if best_sell.quantity == 0:
                        heapq.heappop(self.sell_orders)
                        del self.active_orders[best_sell.order_id]
                else:
                    break

            # Add remaining quantity to buy orders
            if quantity > 0:
                order.quantity = quantity
                heapq.heappush(self.buy_orders, EnhancedOrder(
                    price=-price,  # Negative for max heap
                    timestamp=timestamp,
                    order_id=order_id,
                    side=side,
                    quantity=quantity,
                    user_id=user_id,
                    parent_order_id=parent_order_id,
                    metadata=metadata or {}
                ))
                self.active_orders[order_id] = order

        else:  # sell
            # Try to match with buy orders
            while self.buy_orders and quantity > 0:
                best_buy = self.buy_orders[0]
                best_buy_price = -best_buy.price  # Convert back from negative

                if price <= best_buy_price:
                    # Match found
                    trade_quantity = min(quantity, best_buy.quantity)
                    trade_price = best_buy_price

                    trades.append({
                        "buyer_id": best_buy.user_id,
                        "seller_id": user_id,
                        "price": trade_price,
                        "quantity": trade_quantity,
                        "timestamp": timestamp,
                        "buyer_order": best_buy.order_id,
                        "seller_order": order_id
                    })

                    quantity -= trade_quantity
                    best_buy.quantity -= trade_quantity
                    self.last_price = trade_price
                    self.current_price = trade_price

                    # Handle iceberg order refill
                    if best_buy.parent_order_id:
                        self._handle_iceberg_execution(best_buy.parent_order_id, trade_quantity)

                    if best_buy.quantity == 0:
                        heapq.heappop(self.buy_orders)
                        del self.active_orders[best_buy.order_id]
                else:
                    break

            # Add remaining quantity to sell orders
            if quantity > 0:
                order.quantity = quantity
                heapq.heappush(self.sell_orders, order)
                self.active_orders[order_id] = order

        # Store trades
        self.trades.extend(trades)

        # Update market data
        self._update_market_data(trades)

        # Check for triggered advanced orders
        if self.current_price:
            self._check_triggered_orders(self.current_price)

        return order_id, trades

    def _handle_iceberg_execution(self, parent_order_id: str, executed_qty: float):
        """Handle iceberg order execution and place next slice"""
        next_slice = self.advanced_orders.handle_iceberg_execution(
            parent_order_id,
            Decimal(executed_qty)
        )

        if next_slice:
            # Place the next slice
            self.place_order(
                side=next_slice["symbol"],
                price=float(next_slice["price"]),
                quantity=float(next_slice["quantity"]),
                user_id=0,  # Would need to track this properly
                order_type="limit",
                external_id=next_slice["order_id"],
                metadata={"iceberg": True, "parent": parent_order_id}
            )

    def _check_triggered_orders(self, current_price: float):
        """Check and execute triggered advanced orders"""
        triggered = self.advanced_orders.update_price(self.symbol, Decimal(current_price))

        for trigger_info in triggered:
            order = trigger_info["order"]
            trigger_type = trigger_info["type"]

            logger.info(f"Triggered {trigger_type} order: {order.order_id} at price {current_price}")

            # Place the triggered order as a market order
            if trigger_type in ["stop_loss", "trailing_stop", "take_profit"]:
                # Convert to market order
                self.place_order(
                    side=order.side,
                    price=float(order.limit_price) if hasattr(order, 'limit_price') and order.limit_price else current_price * 1.1,
                    quantity=float(order.quantity),
                    user_id=int(order.user_id) if order.user_id.isdigit() else 0,
                    order_type="limit",
                    external_id=f"{order.order_id}_triggered",
                    metadata={"triggered_from": order.order_id, "trigger_type": trigger_type}
                )

    def _update_market_data(self, trades: List[Dict]):
        """Update market data from trades"""
        for trade in trades:
            price = trade["price"]
            volume = trade["quantity"]

            # Update price history
            self.price_history.append(price)
            if len(self.price_history) > 1000:
                self.price_history.pop(0)

            # Update 24h stats
            self.volume_24h += Decimal(volume)

            if self.high_24h is None or price > self.high_24h:
                self.high_24h = price
            if self.low_24h is None or price < self.low_24h:
                self.low_24h = price

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an order"""
        # Check regular orders
        if order_id in self.active_orders:
            order = self.active_orders[order_id]

            # Remove from appropriate book
            if order.side == "buy":
                self.buy_orders = [o for o in self.buy_orders if o.order_id != order_id]
                heapq.heapify(self.buy_orders)
            else:
                self.sell_orders = [o for o in self.sell_orders if o.order_id != order_id]
                heapq.heapify(self.sell_orders)

            del self.active_orders[order_id]
            return True

        # Check advanced orders
        for external_id, internal_id in self.order_map.items():
            if internal_id == order_id:
                return self.advanced_orders.cancel_order(external_id)

        return False

    def add_market_maker(self, maker_id: str, config: MarketMakerConfig) -> bool:
        """Add a market maker to the engine"""
        if maker_id not in self.market_makers:
            self.market_makers[maker_id] = MarketMaker(config)
            logger.info(f"Added market maker {maker_id} for {config.symbol}")
            return True
        return False

    async def run_market_makers(self) -> List[Dict]:
        """Run all active market makers and collect their orders"""
        all_orders = []

        # Prepare market data
        market_data = self.get_market_data()

        for maker_id, maker in self.market_makers.items():
            if maker.active:
                orders = await maker.generate_orders(market_data)
                for order in orders:
                    order["maker_id"] = maker_id
                all_orders.extend(orders)

        return all_orders

    def get_market_data(self) -> Dict:
        """Get current market data for market makers"""
        best_bid = -self.buy_orders[0].price if self.buy_orders else None
        best_ask = self.sell_orders[0].price if self.sell_orders else None

        mid_price = None
        if best_bid and best_ask:
            mid_price = (best_bid + best_ask) / 2
        elif self.last_price:
            mid_price = self.last_price

        # Calculate order book volumes
        bid_volume = sum(o.quantity for o in self.buy_orders)
        ask_volume = sum(o.quantity for o in self.sell_orders)

        return {
            "symbol": self.symbol,
            "mid_price": mid_price,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "last_price": self.last_price,
            "volume_24h": float(self.volume_24h),
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "recent_prices": self.price_history[-100:] if self.price_history else [],
            "recent_trades": self.trades[-100:] if self.trades else []
        }

    def get_order_book(self, depth: int = 10) -> Dict:
        """Get order book with specified depth"""
        bids = []
        asks = []

        # Aggregate buy orders
        buy_levels = {}
        for order in sorted(self.buy_orders, key=lambda x: -x.price)[:depth*2]:
            price = -order.price
            if price not in buy_levels:
                buy_levels[price] = 0
            buy_levels[price] += order.quantity

        # Aggregate sell orders
        sell_levels = {}
        for order in sorted(self.sell_orders, key=lambda x: x.price)[:depth*2]:
            if order.price not in sell_levels:
                sell_levels[order.price] = 0
            sell_levels[order.price] += order.quantity

        # Format for output
        for price in sorted(buy_levels.keys(), reverse=True)[:depth]:
            bids.append({"price": price, "quantity": buy_levels[price]})

        for price in sorted(sell_levels.keys())[:depth]:
            asks.append({"price": price, "quantity": sell_levels[price]})

        return {
            "symbol": self.symbol,
            "bids": bids,
            "asks": asks,
            "timestamp": datetime.utcnow().isoformat()
        }

    def get_stats(self) -> Dict:
        """Get engine statistics"""
        return {
            "symbol": self.symbol,
            "total_orders": self.order_id_counter - 1,
            "active_orders": len(self.active_orders),
            "buy_orders": len(self.buy_orders),
            "sell_orders": len(self.sell_orders),
            "total_trades": len(self.trades),
            "last_price": self.last_price,
            "volume_24h": float(self.volume_24h),
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "advanced_orders": {
                "stop_loss": len(self.advanced_orders.stop_orders),
                "trailing_stop": len(self.advanced_orders.trailing_stops),
                "iceberg": len(self.advanced_orders.iceberg_orders),
                "take_profit": len(self.advanced_orders.take_profit_orders)
            },
            "market_makers": len(self.market_makers)
        }