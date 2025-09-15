"""
High-performance matching engine for real exchange.
Optimized for low latency and high throughput.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
import heapq
import time
from collections import defaultdict
import uuid
from datetime import datetime


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    ICEBERG = "iceberg"
    POST_ONLY = "post_only"
    FILL_OR_KILL = "fill_or_kill"
    IMMEDIATE_OR_CANCEL = "immediate_or_cancel"


class OrderStatus(Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(Enum):
    GTC = "good_till_cancel"
    IOC = "immediate_or_cancel"
    FOK = "fill_or_kill"
    GTD = "good_till_date"
    DAY = "day"


@dataclass
class Order:
    """Order with all necessary fields for real exchange."""
    id: str
    user_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: OrderType
    price: Optional[Decimal]
    quantity: Decimal
    time_in_force: TimeInForce
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Decimal = Decimal('0')
    remaining_quantity: Decimal = field(init=False)
    average_fill_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    iceberg_quantity: Optional[Decimal] = None
    post_only: bool = False
    reduce_only: bool = False
    client_order_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expire_time: Optional[datetime] = None

    def __post_init__(self):
        self.remaining_quantity = self.quantity - self.filled_quantity

    def __lt__(self, other):
        """For heap operations - price-time priority."""
        if self.side == 'buy':
            # For buys, higher price is better (use negative for min heap)
            if self.price != other.price:
                return -self.price < -other.price
        else:
            # For sells, lower price is better
            if self.price != other.price:
                return self.price < other.price
        # Time priority (earlier is better)
        return self.created_at < other.created_at


@dataclass
class Trade:
    """Executed trade record."""
    id: str
    symbol: str
    buyer_order_id: str
    seller_order_id: str
    buyer_user_id: str
    seller_user_id: str
    price: Decimal
    quantity: Decimal
    maker_order_id: str
    taker_order_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    fee_currency: str = "USD"
    buyer_fee: Decimal = Decimal('0')
    seller_fee: Decimal = Decimal('0')


class OrderBook:
    """Optimized order book for a single trading pair."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: List[Order] = []  # Max heap (use negative prices)
        self.asks: List[Order] = []  # Min heap
        self.orders: Dict[str, Order] = {}
        self.stop_orders: Dict[str, Order] = {}
        self.order_index: Dict[str, Set[str]] = defaultdict(set)  # user_id -> order_ids
        self.last_trade_price: Optional[Decimal] = None
        self.last_trade_time: Optional[datetime] = None
        self.daily_volume: Decimal = Decimal('0')
        self.daily_trades: int = 0

    def add_order(self, order: Order) -> List[Trade]:
        """Add order and execute matches."""
        trades = []

        # Validate order
        if not self._validate_order(order):
            order.status = OrderStatus.REJECTED
            return trades

        # Store order
        self.orders[order.id] = order
        self.order_index[order.user_id].add(order.id)

        # Handle different order types
        if order.order_type == OrderType.MARKET:
            trades = self._match_market_order(order)
        elif order.order_type == OrderType.LIMIT:
            trades = self._match_limit_order(order)
        elif order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT]:
            self._add_stop_order(order)
        elif order.order_type == OrderType.POST_ONLY:
            trades = self._match_post_only_order(order)

        # Check stop orders after trades
        if trades:
            self._trigger_stop_orders(trades[-1].price)

        return trades

    def _validate_order(self, order: Order) -> bool:
        """Validate order parameters."""
        if order.quantity <= 0:
            return False

        if order.order_type == OrderType.LIMIT and order.price is None:
            return False

        if order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT] and order.stop_price is None:
            return False

        # Add more validation rules as needed
        return True

    def _match_market_order(self, order: Order) -> List[Trade]:
        """Match market order against book."""
        trades = []

        if order.side == 'buy':
            book = self.asks
        else:
            book = self.bids

        while book and order.remaining_quantity > 0:
            counter_order = heapq.heappop(book)

            # Skip self-trade
            if counter_order.user_id == order.user_id:
                heapq.heappush(book, counter_order)
                continue

            trade = self._execute_trade(order, counter_order)
            if trade:
                trades.append(trade)

            # Put back partially filled order
            if counter_order.remaining_quantity > 0:
                heapq.heappush(book, counter_order)

        # Update order status
        if order.remaining_quantity == 0:
            order.status = OrderStatus.FILLED
        elif order.filled_quantity > 0:
            order.status = OrderStatus.PARTIALLY_FILLED

        return trades

    def _match_limit_order(self, order: Order) -> List[Trade]:
        """Match limit order against book."""
        trades = []

        if order.side == 'buy':
            book = self.asks
            while book and order.remaining_quantity > 0:
                if book[0].price > order.price:
                    break
                counter_order = heapq.heappop(book)

                # Skip self-trade
                if counter_order.user_id == order.user_id:
                    heapq.heappush(book, counter_order)
                    continue

                trade = self._execute_trade(order, counter_order)
                if trade:
                    trades.append(trade)

                if counter_order.remaining_quantity > 0:
                    heapq.heappush(book, counter_order)
        else:
            book = self.bids
            while book and order.remaining_quantity > 0:
                # Note: bids use negative prices in heap
                if -book[0].price < order.price:
                    break
                counter_order = heapq.heappop(book)

                # Skip self-trade
                if counter_order.user_id == order.user_id:
                    heapq.heappush(book, counter_order)
                    continue

                trade = self._execute_trade(order, counter_order)
                if trade:
                    trades.append(trade)

                if counter_order.remaining_quantity > 0:
                    heapq.heappush(book, counter_order)

        # Add remaining order to book
        if order.remaining_quantity > 0:
            if order.side == 'buy':
                # Use negative price for buy orders (max heap)
                order.price = -order.price
                heapq.heappush(self.bids, order)
                order.price = -order.price  # Restore original
            else:
                heapq.heappush(self.asks, order)
        else:
            order.status = OrderStatus.FILLED

        return trades

    def _match_post_only_order(self, order: Order) -> List[Trade]:
        """Match post-only order (must be maker)."""
        # Check if order would cross the spread
        if order.side == 'buy':
            if self.asks and order.price >= self.asks[0].price:
                order.status = OrderStatus.REJECTED
                return []
        else:
            if self.bids and order.price <= -self.bids[0].price:
                order.status = OrderStatus.REJECTED
                return []

        # Add as limit order
        if order.side == 'buy':
            order.price = -order.price
            heapq.heappush(self.bids, order)
            order.price = -order.price
        else:
            heapq.heappush(self.asks, order)

        return []

    def _execute_trade(self, taker_order: Order, maker_order: Order) -> Optional[Trade]:
        """Execute trade between two orders."""
        trade_quantity = min(taker_order.remaining_quantity, maker_order.remaining_quantity)

        if trade_quantity <= 0:
            return None

        # Use maker price
        trade_price = abs(maker_order.price) if maker_order.price else self.last_trade_price

        # Create trade
        trade = Trade(
            id=str(uuid.uuid4()),
            symbol=self.symbol,
            buyer_order_id=taker_order.id if taker_order.side == 'buy' else maker_order.id,
            seller_order_id=maker_order.id if taker_order.side == 'buy' else taker_order.id,
            buyer_user_id=taker_order.user_id if taker_order.side == 'buy' else maker_order.user_id,
            seller_user_id=maker_order.user_id if taker_order.side == 'buy' else taker_order.user_id,
            price=trade_price,
            quantity=trade_quantity,
            maker_order_id=maker_order.id,
            taker_order_id=taker_order.id
        )

        # Update orders
        taker_order.filled_quantity += trade_quantity
        taker_order.remaining_quantity -= trade_quantity
        maker_order.filled_quantity += trade_quantity
        maker_order.remaining_quantity -= trade_quantity

        # Update order status
        if taker_order.remaining_quantity == 0:
            taker_order.status = OrderStatus.FILLED
        else:
            taker_order.status = OrderStatus.PARTIALLY_FILLED

        if maker_order.remaining_quantity == 0:
            maker_order.status = OrderStatus.FILLED
        else:
            maker_order.status = OrderStatus.PARTIALLY_FILLED

        # Update market data
        self.last_trade_price = trade_price
        self.last_trade_time = trade.timestamp
        self.daily_volume += trade_quantity * trade_price
        self.daily_trades += 1

        return trade

    def _add_stop_order(self, order: Order):
        """Add stop order to monitoring."""
        self.stop_orders[order.id] = order

    def _trigger_stop_orders(self, price: Decimal):
        """Check and trigger stop orders."""
        triggered = []

        for order_id, order in self.stop_orders.items():
            if order.side == 'buy' and price >= order.stop_price:
                triggered.append(order_id)
            elif order.side == 'sell' and price <= order.stop_price:
                triggered.append(order_id)

        for order_id in triggered:
            order = self.stop_orders.pop(order_id)
            if order.order_type == OrderType.STOP:
                order.order_type = OrderType.MARKET
            else:  # STOP_LIMIT
                order.order_type = OrderType.LIMIT
            self.add_order(order)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if order_id not in self.orders:
            return False

        order = self.orders[order_id]

        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
            return False

        # Remove from books
        if order.side == 'buy':
            self.bids = [o for o in self.bids if o.id != order_id]
            heapq.heapify(self.bids)
        else:
            self.asks = [o for o in self.asks if o.id != order_id]
            heapq.heapify(self.asks)

        # Remove from stop orders
        if order_id in self.stop_orders:
            del self.stop_orders[order_id]

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()

        return True

    def get_order_book_snapshot(self, depth: int = 20) -> Dict:
        """Get current order book snapshot."""
        return {
            "symbol": self.symbol,
            "bids": [
                {"price": abs(o.price), "quantity": o.remaining_quantity}
                for o in sorted(self.bids)[:depth]
            ],
            "asks": [
                {"price": o.price, "quantity": o.remaining_quantity}
                for o in sorted(self.asks)[:depth]
            ],
            "last_price": self.last_trade_price,
            "timestamp": datetime.utcnow().isoformat()
        }


class MatchingEngine:
    """Main matching engine managing multiple order books."""

    def __init__(self):
        self.order_books: Dict[str, OrderBook] = {}
        self.trades: List[Trade] = []
        self.trade_callbacks = []

    def add_symbol(self, symbol: str):
        """Add new trading pair."""
        if symbol not in self.order_books:
            self.order_books[symbol] = OrderBook(symbol)

    def place_order(self, order: Order) -> Tuple[bool, List[Trade]]:
        """Place an order."""
        if order.symbol not in self.order_books:
            return False, []

        trades = self.order_books[order.symbol].add_order(order)

        # Store trades and trigger callbacks
        self.trades.extend(trades)
        for callback in self.trade_callbacks:
            for trade in trades:
                callback(trade)

        return True, trades

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        if symbol not in self.order_books:
            return False

        return self.order_books[symbol].cancel_order(order_id)

    def get_order_book(self, symbol: str, depth: int = 20) -> Optional[Dict]:
        """Get order book for symbol."""
        if symbol not in self.order_books:
            return None

        return self.order_books[symbol].get_order_book_snapshot(depth)

    def register_trade_callback(self, callback):
        """Register callback for trade events."""
        self.trade_callbacks.append(callback)