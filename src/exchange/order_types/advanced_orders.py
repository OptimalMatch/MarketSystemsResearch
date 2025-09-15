"""
Advanced Order Types for Exchange
Implements stop-loss, trailing stops, and iceberg orders
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Extended order types"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    ICEBERG = "iceberg"
    TAKE_PROFIT = "take_profit"
    OCO = "one_cancels_other"  # One-Cancels-Other


@dataclass
class StopLossOrder:
    """Stop-loss order that triggers a market sell when price drops below stop price"""
    order_id: str
    user_id: str
    symbol: str
    side: str  # Usually 'sell' for stop-loss
    quantity: Decimal
    stop_price: Decimal
    limit_price: Optional[Decimal] = None  # If set, becomes stop-limit order
    triggered: bool = False
    trigger_time: Optional[datetime] = None
    time_in_force: str = "GTC"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def should_trigger(self, current_price: Decimal) -> bool:
        """Check if stop-loss should trigger based on current price"""
        if self.triggered:
            return False

        if self.side == "sell":
            # Trigger when price falls to or below stop price
            return current_price <= self.stop_price
        else:  # buy stop
            # Trigger when price rises to or above stop price
            return current_price >= self.stop_price


@dataclass
class TrailingStopOrder:
    """Trailing stop that follows price movements with a specified distance"""
    order_id: str
    user_id: str
    symbol: str
    side: str
    quantity: Decimal
    trail_amount: Optional[Decimal] = None  # Fixed amount trailing
    trail_percent: Optional[Decimal] = None  # Percentage trailing
    stop_price: Optional[Decimal] = None  # Current stop price
    high_water_mark: Optional[Decimal] = None  # Highest price seen (for sell)
    low_water_mark: Optional[Decimal] = None  # Lowest price seen (for buy)
    triggered: bool = False
    trigger_time: Optional[datetime] = None
    time_in_force: str = "GTC"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

        if self.trail_amount is None and self.trail_percent is None:
            raise ValueError("Either trail_amount or trail_percent must be specified")

    def update_trail(self, current_price: Decimal) -> bool:
        """Update trailing stop based on current price. Returns True if stop updated."""
        if self.triggered:
            return False

        updated = False

        if self.side == "sell":
            # For sell orders, track the highest price
            if self.high_water_mark is None or current_price > self.high_water_mark:
                self.high_water_mark = current_price

                # Calculate new stop price
                if self.trail_amount:
                    new_stop = self.high_water_mark - self.trail_amount
                else:  # trail_percent
                    new_stop = self.high_water_mark * (Decimal(1) - self.trail_percent / Decimal(100))

                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
                    updated = True
                    logger.debug(f"Trailing stop {self.order_id} updated: stop={self.stop_price}, high={self.high_water_mark}")

        else:  # buy
            # For buy orders, track the lowest price
            if self.low_water_mark is None or current_price < self.low_water_mark:
                self.low_water_mark = current_price

                # Calculate new stop price
                if self.trail_amount:
                    new_stop = self.low_water_mark + self.trail_amount
                else:  # trail_percent
                    new_stop = self.low_water_mark * (Decimal(1) + self.trail_percent / Decimal(100))

                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop
                    updated = True
                    logger.debug(f"Trailing stop {self.order_id} updated: stop={self.stop_price}, low={self.low_water_mark}")

        return updated

    def should_trigger(self, current_price: Decimal) -> bool:
        """Check if trailing stop should trigger"""
        if self.triggered or self.stop_price is None:
            return False

        if self.side == "sell":
            return current_price <= self.stop_price
        else:  # buy
            return current_price >= self.stop_price


@dataclass
class IcebergOrder:
    """Iceberg order that only shows a portion of the total quantity"""
    order_id: str
    user_id: str
    symbol: str
    side: str
    total_quantity: Decimal
    display_quantity: Decimal  # Visible quantity in order book
    price: Decimal
    executed_quantity: Decimal = Decimal(0)
    current_slice_id: Optional[str] = None  # ID of current visible slice
    slices_executed: int = 0
    time_in_force: str = "GTC"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

        if self.display_quantity > self.total_quantity:
            self.display_quantity = self.total_quantity

    def get_next_slice(self) -> Tuple[Decimal, bool]:
        """Get the next slice to display. Returns (quantity, is_final)"""
        remaining = self.total_quantity - self.executed_quantity

        if remaining <= 0:
            return Decimal(0), True

        if remaining <= self.display_quantity:
            # Final slice
            return remaining, True
        else:
            # Regular slice
            return self.display_quantity, False

    def record_execution(self, executed_qty: Decimal):
        """Record partial execution of current slice"""
        self.executed_quantity += executed_qty
        logger.debug(f"Iceberg {self.order_id}: executed {executed_qty}, total {self.executed_quantity}/{self.total_quantity}")

    @property
    def is_complete(self) -> bool:
        """Check if entire iceberg order is executed"""
        return self.executed_quantity >= self.total_quantity

    @property
    def completion_percentage(self) -> Decimal:
        """Get completion percentage"""
        if self.total_quantity == 0:
            return Decimal(100)
        return (self.executed_quantity / self.total_quantity) * Decimal(100)


@dataclass
class TakeProfitOrder:
    """Take-profit order that triggers when price reaches target"""
    order_id: str
    user_id: str
    symbol: str
    side: str  # Usually opposite of position
    quantity: Decimal
    target_price: Decimal
    limit_price: Optional[Decimal] = None  # If set, becomes take-profit-limit
    triggered: bool = False
    trigger_time: Optional[datetime] = None
    time_in_force: str = "GTC"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    def should_trigger(self, current_price: Decimal) -> bool:
        """Check if take-profit should trigger"""
        if self.triggered:
            return False

        if self.side == "sell":
            # Trigger when price rises to or above target
            return current_price >= self.target_price
        else:  # buy
            # Trigger when price falls to or below target
            return current_price <= self.target_price


@dataclass
class OCOOrder:
    """One-Cancels-Other: Two orders where execution of one cancels the other"""
    order_id: str
    user_id: str
    symbol: str
    # First leg (usually limit order)
    leg1_side: str
    leg1_quantity: Decimal
    leg1_price: Decimal
    # Second leg (usually stop-loss)
    leg2_side: str
    leg2_quantity: Decimal
    leg2_stop_price: Decimal
    # Optional fields with defaults
    leg1_type: str = "limit"
    leg1_order_id: Optional[str] = None
    leg2_limit_price: Optional[Decimal] = None
    leg2_type: str = "stop_loss"
    leg2_order_id: Optional[str] = None
    # Status
    active: bool = True
    triggered_leg: Optional[int] = None  # 1 or 2
    time_in_force: str = "GTC"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class AdvancedOrderManager:
    """Manages advanced order types and their triggers"""

    def __init__(self):
        self.stop_orders: Dict[str, StopLossOrder] = {}
        self.trailing_stops: Dict[str, TrailingStopOrder] = {}
        self.iceberg_orders: Dict[str, IcebergOrder] = {}
        self.take_profit_orders: Dict[str, TakeProfitOrder] = {}
        self.oco_orders: Dict[str, OCOOrder] = {}
        self.price_history: Dict[str, List[Decimal]] = {}  # symbol -> recent prices

    def add_stop_loss(self, order: StopLossOrder) -> str:
        """Add a stop-loss order"""
        self.stop_orders[order.order_id] = order
        logger.info(f"Added stop-loss order {order.order_id}: {order.quantity} @ stop {order.stop_price}")
        return order.order_id

    def add_trailing_stop(self, order: TrailingStopOrder) -> str:
        """Add a trailing stop order"""
        self.trailing_stops[order.order_id] = order
        logger.info(f"Added trailing stop {order.order_id}: trail={order.trail_amount or str(order.trail_percent)+'%'}")
        return order.order_id

    def add_iceberg(self, order: IcebergOrder) -> str:
        """Add an iceberg order"""
        self.iceberg_orders[order.order_id] = order
        logger.info(f"Added iceberg order {order.order_id}: {order.total_quantity} (display {order.display_quantity})")
        return order.order_id

    def add_take_profit(self, order: TakeProfitOrder) -> str:
        """Add a take-profit order"""
        self.take_profit_orders[order.order_id] = order
        logger.info(f"Added take-profit order {order.order_id}: {order.quantity} @ target {order.target_price}")
        return order.order_id

    def add_oco(self, order: OCOOrder) -> str:
        """Add an OCO order"""
        self.oco_orders[order.order_id] = order
        logger.info(f"Added OCO order {order.order_id}: limit @ {order.leg1_price}, stop @ {order.leg2_stop_price}")
        return order.order_id

    def update_price(self, symbol: str, price: Decimal) -> List[Dict]:
        """Update price and check for triggered orders. Returns list of triggered orders."""
        triggered = []

        # Update price history
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        self.price_history[symbol].append(price)
        if len(self.price_history[symbol]) > 100:  # Keep last 100 prices
            self.price_history[symbol].pop(0)

        # Check stop-loss orders
        for order_id, order in list(self.stop_orders.items()):
            if order.symbol == symbol and order.should_trigger(price):
                order.triggered = True
                order.trigger_time = datetime.utcnow()
                triggered.append({
                    "type": "stop_loss",
                    "order": order,
                    "trigger_price": price
                })
                logger.info(f"Stop-loss {order_id} triggered at {price}")

        # Check and update trailing stops
        for order_id, order in list(self.trailing_stops.items()):
            if order.symbol == symbol:
                order.update_trail(price)
                if order.should_trigger(price):
                    order.triggered = True
                    order.trigger_time = datetime.utcnow()
                    triggered.append({
                        "type": "trailing_stop",
                        "order": order,
                        "trigger_price": price
                    })
                    logger.info(f"Trailing stop {order_id} triggered at {price}")

        # Check take-profit orders
        for order_id, order in list(self.take_profit_orders.items()):
            if order.symbol == symbol and order.should_trigger(price):
                order.triggered = True
                order.trigger_time = datetime.utcnow()
                triggered.append({
                    "type": "take_profit",
                    "order": order,
                    "trigger_price": price
                })
                logger.info(f"Take-profit {order_id} triggered at {price}")

        return triggered

    def get_iceberg_slice(self, order_id: str) -> Optional[Dict]:
        """Get the current slice of an iceberg order"""
        if order_id not in self.iceberg_orders:
            return None

        order = self.iceberg_orders[order_id]
        if order.is_complete:
            return None

        quantity, is_final = order.get_next_slice()
        return {
            "order_id": f"{order_id}_slice_{order.slices_executed}",
            "parent_id": order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": quantity,
            "price": order.price,
            "is_final_slice": is_final
        }

    def handle_iceberg_execution(self, order_id: str, executed_qty: Decimal) -> Optional[Dict]:
        """Handle execution of an iceberg slice and return next slice if any"""
        if order_id not in self.iceberg_orders:
            return None

        order = self.iceberg_orders[order_id]
        order.record_execution(executed_qty)
        order.slices_executed += 1

        if not order.is_complete:
            return self.get_iceberg_slice(order_id)
        return None

    def handle_oco_trigger(self, order_id: str, triggered_leg: int) -> Optional[str]:
        """Handle OCO order trigger. Returns ID of order to cancel."""
        if order_id not in self.oco_orders:
            return None

        order = self.oco_orders[order_id]
        if not order.active:
            return None

        order.active = False
        order.triggered_leg = triggered_leg

        # Return the ID of the leg to cancel
        if triggered_leg == 1:
            return order.leg2_order_id
        else:
            return order.leg1_order_id

    def get_active_orders_by_user(self, user_id: str) -> Dict[str, List]:
        """Get all active advanced orders for a user"""
        result = {
            "stop_loss": [],
            "trailing_stop": [],
            "iceberg": [],
            "take_profit": [],
            "oco": []
        }

        for order in self.stop_orders.values():
            if order.user_id == user_id and not order.triggered:
                result["stop_loss"].append(order)

        for order in self.trailing_stops.values():
            if order.user_id == user_id and not order.triggered:
                result["trailing_stop"].append(order)

        for order in self.iceberg_orders.values():
            if order.user_id == user_id and not order.is_complete:
                result["iceberg"].append(order)

        for order in self.take_profit_orders.values():
            if order.user_id == user_id and not order.triggered:
                result["take_profit"].append(order)

        for order in self.oco_orders.values():
            if order.user_id == user_id and order.active:
                result["oco"].append(order)

        return result

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an advanced order"""
        if order_id in self.stop_orders:
            del self.stop_orders[order_id]
            return True
        if order_id in self.trailing_stops:
            del self.trailing_stops[order_id]
            return True
        if order_id in self.iceberg_orders:
            del self.iceberg_orders[order_id]
            return True
        if order_id in self.take_profit_orders:
            del self.take_profit_orders[order_id]
            return True
        if order_id in self.oco_orders:
            del self.oco_orders[order_id]
            return True
        return False