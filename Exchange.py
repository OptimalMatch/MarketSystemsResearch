from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional
from decimal import Decimal
import uuid
from datetime import datetime
import logging


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

    @classmethod
    def create(cls, owner_id: str, side: OrderSide, price: Decimal,
               size: Decimal, security_id: str) -> 'Order':
        return cls(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            side=side,
            price=price,
            size=size,
            filled=Decimal('0'),
            created_at=datetime.now(),
            security_id=security_id
        )


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


# Orderbook implementation
class OrderBook:
    def __init__(self, security_id: str):
        self.security_id = security_id
        self.bids: List[Order] = []  # Buy orders, sorted by price desc
        self.asks: List[Order] = []  # Sell orders, sorted by price asc
        self.trades: List[Trade] = []

    def add_order(self, order: Order) -> List[Trade]:
        """Add order to the book and return any trades that were executed"""
        trades = self._match_order(order)

        # If order wasn't fully filled, add to book
        remaining_size = order.size - order.filled
        if remaining_size > 0:
            if order.side == OrderSide.BUY:
                self._add_bid(order)
            else:
                self._add_ask(order)

        return trades

    def _match_order(self, order: Order) -> List[Trade]:
        trades = []

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

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancel and remove an order from the book"""
        for orders in [self.bids, self.asks]:
            for i, order in enumerate(orders):
                if order.id == order_id:
                    return orders.pop(i)
        return None

    def get_market_price(self) -> Optional[Decimal]:
        """Get current market price based on last trade or best bid/ask"""
        if self.trades:
            return self.trades[-1].price
        elif self.bids and self.asks:
            return (self.bids[0].price + self.asks[0].price) / 2
        return None


# Market implementation
class Market:
    def __init__(self):
        self.orderbooks: Dict[str, OrderBook] = {}
        self.balances: Dict[str, Dict[str, Decimal]] = {}  # user_id -> {security_id -> amount}
        self.logger = logging.getLogger(__name__)

    def create_orderbook(self, security_id: str) -> OrderBook:
        """Create a new orderbook for a security"""
        if security_id in self.orderbooks:
            raise ValueError(f"Orderbook for security {security_id} already exists")
        self.orderbooks[security_id] = OrderBook(security_id)
        return self.orderbooks[security_id]

    def place_order(self, owner_id: str, security_id: str, side: OrderSide,
                    price: Decimal, size: Decimal) -> List[Trade]:
        """Place a new order in the market"""
        # Validate security exists
        if security_id not in self.orderbooks:
            raise ValueError(f"No orderbook for security {security_id}")

        # Validate user has sufficient balance
        if not self._validate_balance(owner_id, security_id, side, price, size):
            raise ValueError("Insufficient balance")

        # Create and place order
        order = Order.create(owner_id, side, price, size, security_id)
        trades = self.orderbooks[security_id].add_order(order)

        # Process trades and update balances
        self._process_trades(trades)

        return trades

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