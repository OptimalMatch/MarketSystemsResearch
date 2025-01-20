from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional
from decimal import Decimal
import uuid
from datetime import datetime
import logging
import csv
from pathlib import Path

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
        self.orders: Dict[str, Order] = {}  # Track orders by ID (string)

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
            self.bids = [o for o in self.bids if o.id != order_id]
        else:
            self.asks = [o for o in self.asks if o.id != order_id]

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
        trades = []
        logging.debug(f"Matching order: {order}")

        while True:
            match = None
            if order.side == OrderSide.BUY:
                # Match against asks (sells)
                if self.asks and self.asks[0].price <= order.price:
                    match = self.asks[0]
            else:
                # Match against bids (buys)
                if self.bids and self.bids[0].price >= order.price:
                    match = self.bids[0]

            if not match:
                logging.debug(f"No match found for order: {order}")
                break

            # Calculate trade size
            remaining_size = order.size - order.filled
            match_remaining = match.size - match.filled
            trade_size = min(remaining_size, match_remaining)

            # Create and record the trade
            trade = Trade.create(
                security_id=self.security_id,
                buyer_id=order.owner_id if order.side == OrderSide.BUY else match.owner_id,
                seller_id=match.owner_id if order.side == OrderSide.BUY else order.owner_id,
                price=match.price,
                size=trade_size
            )
            trades.append(trade)
            self.trades.append(trade)
            logging.debug(f"Trade executed: {trade}")

            # Update order fills
            order.filled += trade_size
            match.filled += trade_size

            # Remove matched order if fully filled
            if match.filled == match.size:
                if order.side == OrderSide.BUY:
                    self.asks.pop(0)
                else:
                    self.bids.pop(0)

            # Break if original order is fully filled
            if order.filled == order.size:
                break

        return trades

    def _add_bid(self, order: Order):
        """Add bid order maintaining price-time priority (highest price first)"""
        insert_index = len(self.bids)
        for i, bid in enumerate(self.bids):
            if order.price > bid.price:
                insert_index = i
                break
        self.bids.insert(insert_index, order)

    def _add_ask(self, order: Order):
        """Add ask order maintaining price-time priority (lowest price first)"""
        insert_index = len(self.asks)
        for i, ask in enumerate(self.asks):
            if order.price < ask.price:
                insert_index = i
                break
        self.asks.insert(insert_index, order)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID"""
        # Convert order_id to string if it isn't already
        order_id = str(order_id)

        if order_id not in self.orders:
            return False

        order = self.orders[order_id]
        if order.side == OrderSide.BUY:
            self.bids = [o for o in self.bids if str(o.id) != order_id]
        else:
            self.asks = [o for o in self.asks if str(o.id) != order_id]

        order.status = 'cancelled'
        return True

# Market implementation
class Market:

    def __init__(self):
        # Dynamically generate the filename with the current timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.TRADE_LOG_FILE = Path(f"trades_log_{timestamp}.csv")

        self.orderbooks: Dict[str, OrderBook] = {}
        self.balances: Dict[str, Dict[str, Decimal]] = {}  # user_id -> {security_id -> amount}
        self.trade_count = 0  # Initialize trade counter
        self.logger = logging.getLogger(__name__)


    def create_orderbook(self, security_id: str) -> OrderBook:
        """Create a new orderbook for a security"""
        if security_id in self.orderbooks:
            raise ValueError(f"Orderbook for security {security_id} already exists")
        self.orderbooks[security_id] = OrderBook(security_id)
        return self.orderbooks[security_id]

    def place_order(self, owner_id: str, security_id: str, side: OrderSide,
                    price: Decimal, size: Decimal) -> str:
        """Place a new order and return the order ID"""
        logging.debug(f"Placing order - Owner: {owner_id}, Side: {side}, Price: {price}, Size: {size}")
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        if not self._validate_balance(owner_id, security_id, side, price, size):
            raise ValueError("Insufficient balance")

        # Create and place order
        order = Order.create(owner_id, side, price, size, security_id)
        trades = self.orderbooks[security_id].add_order(order)
        self._process_trades(trades)

        return order.id  # Return just the order ID

    def _validate_balance(self, owner_id: str, security_id: str,
                          side: OrderSide, price: Decimal, size: Decimal) -> bool:
        """Validate user has sufficient balance for order"""
        if owner_id not in self.balances:
            self.balances[owner_id] = {}

        user_balances = self.balances[owner_id]

        if side == OrderSide.SELL:
            # Check security balance for sells
            security_balance = user_balances.get(security_id, Decimal('0'))
            return security_balance >= size
        else:
            # Check cash balance for buys
            cash_balance = user_balances.get('cash', Decimal('0'))
            required_cash = price * size
            return cash_balance >= required_cash

    def _process_trades(self, trades: List[Trade]):
        """Process trades and update user balances"""

        # Ensure the trade log file exists with headers
        if not self.TRADE_LOG_FILE.exists():
            with self.TRADE_LOG_FILE.open('w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"])

        for trade in trades:
            # Update buyer balances
            if trade.buyer_id not in self.balances:
                self.balances[trade.buyer_id] = {}
            buyer_balances = self.balances[trade.buyer_id]

            # Deduct cash from buyer
            cash_deduction = trade.price * trade.size
            buyer_balances['cash'] = buyer_balances.get('cash', Decimal('0')) - cash_deduction

            # Add security to buyer
            buyer_balances[trade.security_id] = buyer_balances.get(trade.security_id, Decimal('0')) + trade.size

            # Update seller balances
            if trade.seller_id not in self.balances:
                self.balances[trade.seller_id] = {}
            seller_balances = self.balances[trade.seller_id]

            # Add cash to seller
            seller_balances['cash'] = seller_balances.get('cash', Decimal('0')) + cash_deduction

            # Deduct security from seller
            seller_balances[trade.security_id] = seller_balances.get(trade.security_id, Decimal('0')) - trade.size

            # Increment trade count
            self.trade_count += 1
            logging.debug(f"Trade executed. Total trades: {self.trade_count}")

            # Optionally log trade details
            logging.info(f"Trade: {trade}")

            #Log the trade to the file
            with self.TRADE_LOG_FILE.open('a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    trade.id,
                    trade.security_id,
                    trade.buyer_id,
                    trade.seller_id,
                    f"{trade.price:.2f}",
                    f"{trade.size:.2f}",
                    trade.timestamp.isoformat()
                ])

    def cancel_order(self, security_id: str, order_id: str) -> Optional[Order]:
        """Cancel an order in the market"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")
        return self.orderbooks[security_id].cancel_order(order_id)

    def get_market_depth(self, security_id: str, levels: int = 5) -> dict:
        """Get market depth for a security"""
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        orderbook = self.orderbooks[security_id]

        return {
            'bids': [{'price': o.price, 'size': o.size - o.filled}
                     for o in orderbook.bids[:levels]],
            'asks': [{'price': o.price, 'size': o.size - o.filled}
                     for o in orderbook.asks[:levels]],
            'last_price': orderbook.get_market_price()
        }

    def get_balance(self, user_id: str, security_id: Optional[str] = None) -> Dict[str, Decimal]:
        """Get user's balance for all securities or a specific security"""
        if user_id not in self.balances:
            return {}
        if security_id:
            return {security_id: self.balances[user_id].get(security_id, Decimal('0'))}
        return self.balances[user_id]

    def deposit(self, user_id: str, security_id: str, amount: Decimal):
        """Deposit funds or securities into the market"""
        if user_id not in self.balances:
            self.balances[user_id] = {}
        self.balances[user_id][security_id] = self.balances[user_id].get(security_id, Decimal('0')) + amount

    def withdraw(self, user_id: str, security_id: str, amount: Decimal):
        """Withdraw funds or securities from the market"""
        if user_id not in self.balances or security_id not in self.balances[user_id]:
            raise ValueError("Insufficient balance")

        current_balance = self.balances[user_id][security_id]
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