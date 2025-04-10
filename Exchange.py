from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional, Union, Tuple
from decimal import Decimal
import uuid
from datetime import datetime
import logging
import csv
from pathlib import Path
from collections import defaultdict
import time

#logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - EXCHANGE - %(message)s')

# Basic structures
class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    id: str
    owner_id: str
    side: OrderSide
    price: Decimal
    size: Decimal
    filled: Decimal
    created_at: datetime
    security_id: str
    status: str = 'open'  # Add status field

    @classmethod
    def create(cls, owner_id: str, side: OrderSide, price: Decimal,
               size: Decimal, security_id: str) -> 'Order':
        return cls(
            id=str(uuid.uuid4()),  # Ensure ID is a string
            owner_id=owner_id,
            side=side,
            price=price,
            size=size,
            filled=Decimal('0'),
            created_at=datetime.now(),
            security_id=security_id,
            status='open'
        )

    def __hash__(self):
        return hash(str(self.id))  # Make Order hashable based on its ID


@dataclass
class Trade:
    id: str
    security_id: str
    buyer_id: str
    seller_id: str
    price: Decimal
    size: Decimal
    timestamp: datetime

    @classmethod
    def create(cls, security_id: str, buyer_id: str, seller_id: str,
               price: Decimal, size: Decimal) -> 'Trade':
        return cls(
            id=str(uuid.uuid4()),
            security_id=security_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            price=price,
            size=size,
            timestamp=datetime.now()
        )


class Exchange:
    def __init__(self):
        self.orderbooks = {}
        self.balances = {}
        self.order_id_counter = 0

        self.logger = logging.getLogger(__name__)


    def next_order_id(self) -> str:
        """Generate next order ID"""
        self.order_id_counter += 1
        return f"order_{self.order_id_counter}"

    def place_order(self, owner_id: str, security_id: str, side: OrderSide,
                    price: Decimal, size: Decimal) -> str:
        """Place a new order and return the order ID"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        if not self._validate_balance(owner_id, security_id, side, price, size):
            raise ValueError("Insufficient balance")

        # Create a new order using the create classmethod
        order = Order.create(owner_id, side, price, size, security_id)

        # Generate and assign a new order ID
        order_id = self.next_order_id()
        order.id = order_id  # Override the UUID with our sequential ID

        # Process the order
        trades = self.orderbooks[security_id].add_order(order)
        self._process_trades(trades)

        # Log order placement
        self.logger.info(f"Placed order {order_id}: {side.value} {size} @ {price}")

        return order_id

    def cancel_order(self, security_id: str, order_id: str) -> bool:
        """Cancel an existing order"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        return self.orderbooks[security_id].cancel_order(order_id)

    def get_order_status(self, security_id: str, order_id: str) -> Dict:
        """Get the status of an order"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        return self.orderbooks[security_id].get_order_status(order_id)



class OrderBook:
    def __init__(self, security_id: str):
        self.security_id = security_id
        self.bids: List[Order] = []
        self.asks: List[Order] = []
        self.trades: List[Trade] = []
        self.orders: Dict[str, Order] = {}
        
        # Pre-allocate trade list with capacity
        self.trade_buffer_size = 1000
        self.trade_buffer = []
        
        # Use sorted lists for price levels
        self.bid_prices = []  # Sorted descending
        self.ask_prices = []  # Sorted ascending
        
        # Add order count tracking
        self.order_count = 0
        self.trade_count = 0

    def add_order(self, order: Order) -> List[Trade]:
        """Add an order and return any resulting trades"""
        # Make sure order.id is a string
        if not isinstance(order.id, str):
            raise ValueError("Order ID must be a string")

        # Store order in lookup dictionary
        self.orders[str(order.id)] = order

        # Match order
        trades = self._match_order(order)

        # If not fully filled, add to book
        remaining_size = order.size - order.filled
        if remaining_size > 0:
            if order.side == OrderSide.BUY:
                self._add_bid(order)
            else:
                self._add_ask(order)

        return trades

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID"""
        if order_id not in self.orders:
            return False

        order = self.orders[order_id]
        if order.side == OrderSide.BUY:
            self._remove_bid(order)
        else:
            self._remove_ask(order)

        order.status = 'cancelled'
        return True

    def get_order_status(self, order_id: str) -> Dict:
        """Get order status"""
        # Convert order_id to string if it isn't already
        order_id = str(order_id)

        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        order = self.orders[order_id]
        return {
            'id': str(order.id),  # Ensure ID is a string
            'status': order.status,
            'filled': order.filled,
            'remaining': order.size - order.filled
        }

    def get_market_price(self) -> Optional[Decimal]:
        """Get current market price based on last trade or best bid/ask"""
        if self.trades:
            return self.trades[-1].price
        elif self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return None

    def _match_order(self, order: Order) -> List[Trade]:
        """Match order using pre-allocated trade buffer"""
        self.trade_buffer.clear()
        order_price = float(order.price)
        
        while True:
            match = None
            if order.side == OrderSide.BUY and self.asks:
                match = self.asks[0]
                if float(match.price) > order_price:
                    break
            elif order.side == OrderSide.SELL and self.bids:
                match = self.bids[0]
                if float(match.price) < order_price:
                    break
            
            if not match:
                break

            # Calculate trade size
            trade_size = min(order.size - order.filled, match.size - match.filled)

            # Create trade and add to buffer
            trade = Trade.create(
                security_id=self.security_id,
                buyer_id=order.owner_id if order.side == OrderSide.BUY else match.owner_id,
                seller_id=match.owner_id if order.side == OrderSide.BUY else order.owner_id,
                price=match.price,
                size=trade_size
            )
            self.trade_buffer.append(trade)
            self.trades.append(trade)
            self.trade_count += 1

            # Update fills
            order.filled += trade_size
            match.filled += trade_size

            # Remove filled orders
            if match.filled >= match.size:
                if order.side == OrderSide.BUY:
                    self.asks.pop(0)
                    if not self.asks or float(self.asks[0].price) != float(match.price):
                        self.ask_prices.pop(0)
                else:
                    self.bids.pop(0)
                    if not self.bids or float(self.bids[0].price) != float(match.price):
                        self.bid_prices.pop(0)
                match.status = 'filled'

            if order.filled >= order.size:
                order.status = 'filled'
                break

        return self.trade_buffer

    def _add_bid(self, order: Order):
        """Add bid order maintaining price-time priority (highest price first)"""
        # Binary search for insertion point
        price = float(order.price)  # Convert to float for faster comparisons
        pos = self._binary_search_bids(price)
        self.bids.insert(pos, order)
        
        # Update price levels if needed
        if not self.bid_prices or price != self.bid_prices[-1]:
            pos = self._binary_search_prices(self.bid_prices, price, reverse=True)
            self.bid_prices.insert(pos, price)

    def _add_ask(self, order: Order):
        """Add ask order maintaining price-time priority (lowest price first)"""
        # Binary search for insertion point
        price = float(order.price)  # Convert to float for faster comparisons
        pos = self._binary_search_asks(price)
        self.asks.insert(pos, order)
        
        # Update price levels if needed
        if not self.ask_prices or price != self.ask_prices[-1]:
            pos = self._binary_search_prices(self.ask_prices, price)
            self.ask_prices.insert(pos, price)

    def _binary_search_bids(self, price: float) -> int:
        """Binary search for bid insertion point (descending order)"""
        left, right = 0, len(self.bids)
        while left < right:
            mid = (left + right) // 2
            if float(self.bids[mid].price) < price:
                right = mid
            else:
                left = mid + 1
        return left

    def _binary_search_asks(self, price: float) -> int:
        """Binary search for ask insertion point (ascending order)"""
        left, right = 0, len(self.asks)
        while left < right:
            mid = (left + right) // 2
            if float(self.asks[mid].price) > price:
                right = mid
            else:
                left = mid + 1
        return left

    def _binary_search_prices(self, prices: List[float], price: float, reverse: bool = False) -> int:
        """Binary search for price level insertion point"""
        left, right = 0, len(prices)
        while left < right:
            mid = (left + right) // 2
            if (prices[mid] < price) != reverse:
                right = mid
            else:
                left = mid + 1
        return left

    def _remove_bid(self, order: Order):
        """Remove a bid order efficiently using index tracking"""
        if order.id in self.orders:
            price = float(order.price)
            
            # Binary search to find and remove order
            pos = self._binary_search_bids(price)
            while pos < len(self.bids) and float(self.bids[pos].price) == price:
                if self.bids[pos].id == order.id:
                    self.bids.pop(pos)
                    # Update price levels if needed
                    if not any(float(o.price) == price for o in self.bids):
                        pos = self._binary_search_prices(self.bid_prices, price, reverse=True)
                        self.bid_prices.pop(pos)
                    break
                pos += 1

    def _remove_ask(self, order: Order):
        """Remove an ask order efficiently using index tracking"""
        if order.id in self.orders:
            price = float(order.price)
            
            # Binary search to find and remove order
            pos = self._binary_search_asks(price)
            while pos < len(self.asks) and float(self.asks[pos].price) == price:
                if self.asks[pos].id == order.id:
                    self.asks.pop(pos)
                    # Update price levels if needed
                    if not any(float(o.price) == price for o in self.asks):
                        pos = self._binary_search_prices(self.ask_prices, price)
                        self.ask_prices.pop(pos)
                    break
                pos += 1

# Market implementation
class Market:

    def __init__(self):
        # Initialize trade buffer for aggregation
        self.trade_aggregation_buffer = defaultdict(
            lambda: {"total_volume": Decimal('0'), "total_price": Decimal('0'), "count": 0})
        self.last_aggregation_time = time.time()

        # Dynamically generate the filename with the current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.TRADE_LOG_FILE = Path(f"trades_log_{timestamp}.csv")

        # Pre-allocate buffers
        self.trade_buffer_size = 1000
        self.trade_buffer = []
        self.balance_update_buffer = []
        
        self.orderbooks: Dict[str, OrderBook] = {}
        self.balances: Dict[str, Dict[str, Decimal]] = {}  # Using Decimal for precision
        self.trade_count = 0  # Initialize trade counter
        self.logger = logging.getLogger(__name__)
        self.visualization = None  # Add reference to Visualization
        
        # Optimize market depth caching
        self.market_depth_cache = {}
        self.last_depth_update = {}
        self.depth_cache_ttl = 0.1
        
        # Add balance cache
        self.balance_cache = {}
        self.balance_cache_ttl = 0.1
        self.last_balance_update = {}

    def set_visualization(self, visualization):
        """Set the visualization instance."""
        self.visualization = visualization

    def create_orderbook(self, security_id: str) -> OrderBook:
        """Create a new orderbook for a security"""
        if security_id in self.orderbooks:
            raise ValueError(f"Orderbook for security {security_id} already exists")
        self.orderbooks[security_id] = OrderBook(security_id)
        return self.orderbooks[security_id]

    def place_order(self, owner_id: str, security_id: str, side: OrderSide, price: Decimal, size: Decimal) -> str:
        """Place a new order and return the order ID"""
        logging.debug(f"Placing order - Owner: {owner_id}, Side: {side}, Price: {price}, Size: {size}")
        # Convert to float for validation
        price_f = float(price)
        size_f = float(size)
        
        if not self._validate_balance(owner_id, security_id, side, price, size):
            raise ValueError("Insufficient balance")
            
        if security_id not in self.orderbooks:
            self.create_orderbook(security_id)
            
        order = Order.create(owner_id, side, price, size, security_id)
        trades = self.orderbooks[security_id].add_order(order)
        
        if trades:
            self._process_trades(trades)
            
        return order.id

    def _validate_balance(self, owner_id: str, security_id: str, side: OrderSide, price: Decimal, size: Decimal) -> bool:
        """Validate balance"""
        if side == OrderSide.BUY:
            required = price * size
            available = self.get_balance(owner_id, "cash")
            return available >= required
        else:
            available = self.get_balance(owner_id, security_id)
            return available >= size

    def _process_trades(self, trades: List[Trade]) -> None:
        """Process trades with batched balance updates"""
        self.balance_update_buffer.clear()
        
        for trade in trades:
            # Keep Decimal for calculations
            price = trade.price
            size = trade.size
            cost = price * size
            
            # Collect balance updates
            self.balance_update_buffer.extend([
                (trade.buyer_id, trade.security_id, size),
                (trade.buyer_id, "cash", -cost),
                (trade.seller_id, trade.security_id, -size),
                (trade.seller_id, "cash", cost)
            ])
            
            # Update trade stats
            self.trade_count += 1
            self.trade_buffer.append(trade)
            
            # Update trade aggregation
            agg = self.trade_aggregation_buffer[trade.security_id]
            agg["total_volume"] += size
            agg["total_price"] += price
            agg["count"] += 1
        
        # Batch process all balance updates
        self._batch_update_balances(self.balance_update_buffer)
        
        # Clear balance cache
        self.balance_cache.clear()
        
        # Notify visualization if needed
        if self.visualization and trades:
            self._flush_aggregated_trades()

    def _flush_aggregated_trades(self):
        """Emit aggregated trades to the visualization."""
        current_time = time.time()
        
        for security_id, data in list(self.trade_aggregation_buffer.items()):
            if data["count"] > 0:
                average_price = float(data["total_price"] / data["total_volume"])
                aggregated_trade = {
                    "time": int(current_time),
                    "security_id": security_id,
                    "average_price": average_price,
                    "total_volume": float(data["total_volume"]),
                    "count": data["count"]
                }
                if self.visualization:
                    self.visualization.emit_aggregated_trade(aggregated_trade)
                
                # Reset the buffer
                data["total_volume"] = Decimal('0')
                data["total_price"] = Decimal('0')
                data["count"] = 0

    def _batch_update_balances(self, updates: List[Tuple[str, str, Decimal]]) -> None:
        """Update balances in batch"""
        for user_id, security_id, amount in updates:
            if user_id not in self.balances:
                self.balances[user_id] = defaultdict(lambda: Decimal('0'))
            self.balances[user_id][security_id] += amount

    def get_balance(self, user_id: str, security_id: Optional[str] = None) -> Union[Decimal, Dict[str, Decimal]]:
        """Get balance with caching"""
        now = time.time()
        cache_key = (user_id, security_id)
        
        # Check cache
        if cache_key in self.balance_cache:
            if now - self.last_balance_update.get(cache_key, 0) < self.balance_cache_ttl:
                return self.balance_cache[cache_key]
        
        # Calculate balance
        if security_id:
            balance = self.balances.get(user_id, {}).get(security_id, Decimal('0'))
        else:
            balance = dict(self.balances.get(user_id, defaultdict(lambda: Decimal('0'))))
        
        # Update cache
        self.balance_cache[cache_key] = balance
        self.last_balance_update[cache_key] = now
        
        return balance

    def cancel_order(self, security_id: str, order_id: str) -> Optional[Order]:
        """Cancel an order in the market"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")
        return self.orderbooks[security_id].cancel_order(order_id)

    def get_market_depth(self, security_id: str, levels: int = 5) -> Dict:
        """Get market depth with optimized caching"""
        now = time.time()
        cache_key = (security_id, levels)
        
        if cache_key in self.market_depth_cache:
            if now - self.last_depth_update.get(cache_key, 0) < self.depth_cache_ttl:
                return self.market_depth_cache[cache_key]
        
        if security_id not in self.orderbooks:
            return {"bids": [], "asks": []}
            
        book = self.orderbooks[security_id]
        
        # Convert to float and return as dicts for compatibility
        depth = {
            "bids": [{"price": float(book.bids[i].price), "size": float(book.bids[i].size - book.bids[i].filled)}
                    for i in range(min(levels, len(book.bids)))],
            "asks": [{"price": float(book.asks[i].price), "size": float(book.asks[i].size - book.asks[i].filled)}
                    for i in range(min(levels, len(book.asks)))]
        }
        
        self.market_depth_cache[cache_key] = depth
        self.last_depth_update[cache_key] = now
        
        return depth

    def deposit(self, user_id: str, security_id: str, amount: Decimal):
        """Deposit funds or securities"""
        if user_id not in self.balances:
            self.balances[user_id] = defaultdict(lambda: Decimal('0'))
        self.balances[user_id][security_id] += amount

    def withdraw(self, user_id: str, security_id: str, amount: Decimal):
        """Withdraw funds or securities"""
        if user_id not in self.balances:
            raise ValueError("Insufficient balance")

        current_balance = self.balances[user_id].get(security_id, Decimal('0'))
        if current_balance < amount:
            raise ValueError("Insufficient balance")

        self.balances[user_id][security_id] = current_balance - amount

    def get_order_status(self, security_id: str, order_id: str) -> Dict:
        """Get the status of an order"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        return self.orderbooks[security_id].get_order_status(order_id)

    def get_trade_count(self) -> int:
        """Get the total number of executed trades."""
        return self.trade_count

    def _flush_trade_buffer(self):
        """Flush the trade buffer to the CSV file."""
        with self.TRADE_LOG_FILE.open('a', newline='') as file:
            writer = csv.writer(file)
            if file.tell() == 0:  # Write headers if file is empty
                writer.writerow(["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"])
            writer.writerows(self.trade_buffer)
        self.trade_buffer.clear()

    def finalize_trades(self):
        """Flush remaining trades in the buffer."""
        if self.trade_buffer:
            self._flush_trade_buffer()

# Example usage
if __name__ == "__main__":
    # Create a market
    market = Market()

    # Create an orderbook for a security
    market.create_orderbook('AAPL')

    # Deposit some funds and securities
    market.deposit('user1', 'cash', Decimal('10000'))
    market.deposit('user1', 'AAPL', Decimal('100'))
    market.deposit('user2', 'cash', Decimal('10000'))

    # Place some orders
    trades = market.place_order('user1', 'AAPL', OrderSide.SELL, Decimal('150'), Decimal('10'))
    trades = market.place_order('user2', 'AAPL', OrderSide.BUY, Decimal('150'), Decimal('5'))

    # Check market depth
    depth = market.get_market_depth('AAPL')
    print("Market Depth:", depth)

    # Check balances
    print("User1 Balance:", market.get_balance('user1'))
    print("User2 Balance:", market.get_balance('user2'))