#!/usr/bin/env python3
"""Test script for cryptocurrency trading functionality."""

from decimal import Decimal
from src.core.Exchange import Market, OrderSide
from src.core.SecuritiesPlatform import Security, SecurityType
from src.utils.config import Config
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def initialize_securities(market):
    """Initialize all securities from config."""
    for ticker, info in Config.SECURITIES.items():
        market.create_orderbook(ticker)
        logging.info(f"Created orderbook for {ticker} ({info['name']})")

def test_crypto_trading():
    """Test cryptocurrency trading functionality."""
    # Create market instance
    market = Market()

    # Initialize all securities
    initialize_securities(market)

    # Create test users and deposit funds
    users = ['alice', 'bob', 'charlie']

    # Deposit cash for all users
    for user in users:
        market.deposit(user, 'cash', Decimal('1000000'))
        logging.info(f"Deposited $1,000,000 cash for {user}")

    # Deposit some cryptocurrencies
    market.deposit('alice', 'BTC', Decimal('10'))
    market.deposit('alice', 'DEC', Decimal('1000'))
    market.deposit('bob', 'BTC', Decimal('5'))
    market.deposit('bob', 'DEC', Decimal('500'))

    logging.info("\n=== Initial Balances ===")
    for user in users:
        balance = market.get_balance(user)
        logging.info(f"{user}: {balance}")

    # Test Bitcoin trading
    logging.info("\n=== Bitcoin Trading ===")

    # Alice sells 1 BTC at $45,000
    order1 = market.place_order('alice', 'BTC', OrderSide.SELL,
                                Decimal('45000'), Decimal('1'))
    logging.info(f"Alice placed sell order for 1 BTC at $45,000 (Order: {order1})")

    # Charlie buys 0.5 BTC at $45,000
    order2 = market.place_order('charlie', 'BTC', OrderSide.BUY,
                                Decimal('45000'), Decimal('0.5'))
    logging.info(f"Charlie placed buy order for 0.5 BTC at $45,000 (Order: {order2})")

    # Bob buys 0.5 BTC at $45,000
    order3 = market.place_order('bob', 'BTC', OrderSide.BUY,
                                Decimal('45000'), Decimal('0.5'))
    logging.info(f"Bob placed buy order for 0.5 BTC at $45,000 (Order: {order3})")

    # Test DeCoin trading
    logging.info("\n=== DeCoin Trading ===")

    # Alice sells 100 DEC at $100
    order4 = market.place_order('alice', 'DEC', OrderSide.SELL,
                                Decimal('100'), Decimal('100'))
    logging.info(f"Alice placed sell order for 100 DEC at $100 (Order: {order4})")

    # Charlie buys 50 DEC at $100
    order5 = market.place_order('charlie', 'DEC', OrderSide.BUY,
                                Decimal('100'), Decimal('50'))
    logging.info(f"Charlie placed buy order for 50 DEC at $100 (Order: {order5})")

    # Test fractional cryptocurrency orders
    logging.info("\n=== Fractional Trading ===")

    # Bob sells 0.1 BTC at $46,000
    order6 = market.place_order('bob', 'BTC', OrderSide.SELL,
                                Decimal('46000'), Decimal('0.1'))
    logging.info(f"Bob placed sell order for 0.1 BTC at $46,000 (Order: {order6})")

    # Charlie buys 0.05 BTC at $46,000
    order7 = market.place_order('charlie', 'BTC', OrderSide.BUY,
                                Decimal('46000'), Decimal('0.05'))
    logging.info(f"Charlie placed buy order for 0.05 BTC at $46,000 (Order: {order7})")

    # Check market depth for all securities
    logging.info("\n=== Market Depth ===")
    for ticker in Config.SECURITIES.keys():
        depth = market.get_market_depth(ticker)
        logging.info(f"{ticker} Depth:")
        logging.info(f"  Bids: {depth['bids']}")
        logging.info(f"  Asks: {depth['asks']}")

    # Final balances
    logging.info("\n=== Final Balances ===")
    for user in users:
        balance = market.get_balance(user)
        logging.info(f"{user}: {balance}")

    # Trade statistics
    logging.info(f"\n=== Trade Statistics ===")
    logging.info(f"Total trades executed: {market.get_trade_count()}")

    # Test traditional stock trading alongside crypto
    logging.info("\n=== Mixed Asset Trading (Stock + Crypto) ===")

    # Deposit AAPL shares
    market.deposit('alice', 'AAPL', Decimal('100'))

    # Alice sells 10 AAPL at $150
    order8 = market.place_order('alice', 'AAPL', OrderSide.SELL,
                                Decimal('150'), Decimal('10'))
    logging.info(f"Alice placed sell order for 10 AAPL at $150 (Order: {order8})")

    # Charlie buys 5 AAPL at $150
    order9 = market.place_order('charlie', 'AAPL', OrderSide.BUY,
                                Decimal('150'), Decimal('5'))
    logging.info(f"Charlie placed buy order for 5 AAPL at $150 (Order: {order9})")

    # Finalize trades (flush any remaining trade buffer)
    market.finalize_trades()

    logging.info("\n=== Test Complete ===")
    return market

if __name__ == "__main__":
    try:
        market = test_crypto_trading()
        logging.info("Cryptocurrency trading test completed successfully!")
    except Exception as e:
        logging.error(f"Test failed: {e}")
        raise