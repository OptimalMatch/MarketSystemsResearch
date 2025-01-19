from Exchange import Market, OrderSide
from decimal import Decimal

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
print(depth)

# Check balances
print(market.get_balance('user1'))
print(market.get_balance('user2'))