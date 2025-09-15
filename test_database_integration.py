#!/usr/bin/env python3
"""
Test Database Integration
Verifies orders and trades are persisted to PostgreSQL
"""

import asyncio
import sys
import os
from decimal import Decimal
from uuid import uuid4
import time

# Add source to path
sys.path.insert(0, 'src/exchange')

# Import database and OMS
from database.db_manager import DatabaseManager, get_db_manager, close_db_manager
from order_management.integrated_oms import IntegratedOMS


async def test_database_connection():
    """Test database connectivity"""
    print("\n1. DATABASE CONNECTION TEST")
    print("-" * 40)

    try:
        db = await get_db_manager()
        print("✅ Database connected successfully")

        # Test a simple query
        async with db.pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            print(f"✅ Test query result: {result}")

        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


async def test_user_creation():
    """Test user creation and retrieval"""
    print("\n2. USER MANAGEMENT TEST")
    print("-" * 40)

    db = await get_db_manager()

    # Create test user
    test_username = f"test_user_{uuid4().hex[:8]}"
    test_email = f"{test_username}@test.com"
    test_api_key = f"test_key_{uuid4().hex[:16]}"

    try:
        user_id = await db.create_user(
            username=test_username,
            email=test_email,
            api_key=test_api_key,
            api_secret_hash="hashed_secret",
            decoin_address=f"DEC_{test_username}"
        )
        print(f"✅ Created user: {test_username} (ID: {user_id})")

        # Retrieve user
        user = await db.get_user_by_api_key(test_api_key)
        if user:
            print(f"✅ Retrieved user: {user['username']}")
        else:
            print("❌ Failed to retrieve user")

        return str(user_id) if user else None
    except Exception as e:
        print(f"❌ User creation failed: {e}")
        return None


async def test_balance_operations(user_id: str):
    """Test balance tracking"""
    print("\n3. BALANCE TRACKING TEST")
    print("-" * 40)

    db = await get_db_manager()

    try:
        # Create initial balances
        await db.create_balance(user_id, "DEC", Decimal("1000"), Decimal("0"))
        await db.create_balance(user_id, "USD", Decimal("10000"), Decimal("0"))
        print("✅ Created initial balances")

        # Get balances
        dec_balance = await db.get_user_balance(user_id, "DEC")
        usd_balance = await db.get_user_balance(user_id, "USD")
        print(f"  DEC: {dec_balance['available']} available, {dec_balance['locked']} locked")
        print(f"  USD: {usd_balance['available']} available, {usd_balance['locked']} locked")

        # Lock balance for order
        success = await db.lock_balance_for_order(user_id, "DEC", Decimal("100"))
        if success:
            print("✅ Locked 100 DEC for order")

        # Check updated balance
        dec_balance = await db.get_user_balance(user_id, "DEC")
        print(f"  DEC after lock: {dec_balance['available']} available, {dec_balance['locked']} locked")

        # Unlock balance
        success = await db.unlock_balance(user_id, "DEC", Decimal("100"))
        if success:
            print("✅ Unlocked 100 DEC")

        return True
    except Exception as e:
        print(f"❌ Balance operations failed: {e}")
        return False


async def test_order_persistence():
    """Test order creation and persistence"""
    print("\n4. ORDER PERSISTENCE TEST")
    print("-" * 40)

    db = await get_db_manager()

    # Create a test user first
    user_id = str(uuid4())

    try:
        # Insert order
        order_data = {
            "user_id": user_id,
            "symbol": "DEC/USD",
            "side": "buy",
            "order_type": "limit",
            "quantity": Decimal("10"),
            "price": Decimal("100.50"),
            "time_in_force": "GTC"
        }

        order_id = await db.insert_order(order_data)
        print(f"✅ Created order: {order_id}")

        # Retrieve order
        order = await db.get_order(order_id)
        if order:
            print(f"✅ Retrieved order: {order['symbol']} {order['side']} {order['quantity']} @ {order['price']}")

        # Update order status
        await db.update_order_status(
            order_id,
            "partially_filled",
            Decimal("5"),
            Decimal("100.50")
        )
        print("✅ Updated order status to partially_filled")

        # Get user orders
        user_orders = await db.get_user_orders(user_id)
        print(f"✅ Found {len(user_orders)} orders for user")

        return order_id
    except Exception as e:
        print(f"❌ Order persistence failed: {e}")
        return None


async def test_trade_persistence(order_id: str):
    """Test trade recording"""
    print("\n5. TRADE PERSISTENCE TEST")
    print("-" * 40)

    db = await get_db_manager()

    try:
        # Insert trade
        trade_data = {
            "symbol": "DEC/USD",
            "buyer_order_id": order_id,
            "seller_order_id": None,
            "buyer_user_id": str(uuid4()),
            "seller_user_id": str(uuid4()),
            "price": Decimal("100.50"),
            "quantity": Decimal("5"),
            "maker_side": "buy"
        }

        trade_id = await db.insert_trade(trade_data)
        print(f"✅ Created trade: {trade_id}")

        # Get recent trades
        trades = await db.get_recent_trades("DEC/USD", 10)
        print(f"✅ Retrieved {len(trades)} recent trades")

        if trades:
            latest = trades[0]
            print(f"  Latest: {latest['quantity']} @ {latest['price']}")

        return True
    except Exception as e:
        print(f"❌ Trade persistence failed: {e}")
        return False


async def test_integrated_oms_with_db():
    """Test OMS with database integration"""
    print("\n6. INTEGRATED OMS WITH DATABASE TEST")
    print("-" * 40)

    # Initialize OMS
    oms = IntegratedOMS()
    await oms.initialize_database()
    print("✅ OMS initialized with database")

    # Create test users
    await oms.settlement_bridge.deposit("trader1", Decimal("10000"))
    await oms.settlement_bridge.deposit("trader2", Decimal("10000"))
    print("✅ Test accounts funded")

    # Submit orders
    print("\nSubmitting test orders...")

    # Trader1 sells
    success, result = await oms.submit_order(
        user_id="trader1",
        symbol="DEC/USD",
        side="sell",
        order_type="limit",
        quantity=Decimal("100"),
        price=Decimal("100.00")
    )
    print(f"  Trader1 sell: {'✅' if success else '❌'} ({result})")

    # Trader2 buys (should match)
    success, result = await oms.submit_order(
        user_id="trader2",
        symbol="DEC/USD",
        side="buy",
        order_type="limit",
        quantity=Decimal("50"),
        price=Decimal("100.00")
    )
    print(f"  Trader2 buy: {'✅' if success else '❌'} ({result})")

    # Check database for persisted data
    if oms.db_manager:
        # Check orders in database
        orders = await oms.db_manager.get_active_orders("DEC/USD")
        print(f"\n✅ Active orders in database: {len(orders)}")

        # Check trades in database
        trades = await oms.db_manager.get_recent_trades("DEC/USD", 10)
        print(f"✅ Recent trades in database: {len(trades)}")

    # Get statistics
    stats = oms.get_stats()
    print(f"\nOMS Statistics:")
    print(f"  Total orders: {stats['total_orders']}")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Active orders: {stats['active_orders']}")

    return True


async def test_market_data():
    """Test market data aggregation"""
    print("\n7. MARKET DATA TEST")
    print("-" * 40)

    db = await get_db_manager()

    try:
        # Get 24h stats
        stats = await db.get_24h_stats("DEC/USD")
        print(f"✅ 24h Statistics for DEC/USD:")
        print(f"  Trade count: {stats['trade_count']}")
        print(f"  Volume: {stats['volume']}")
        print(f"  High: {stats['high']}")
        print(f"  Low: {stats['low']}")
        print(f"  Avg price: {stats['avg_price']}")

        # Save candle data
        candle_data = {
            "open_time": "2025-01-14 22:00:00",
            "close_time": "2025-01-14 22:01:00",
            "open": Decimal("100.00"),
            "high": Decimal("100.50"),
            "low": Decimal("99.50"),
            "close": Decimal("100.25"),
            "volume": Decimal("1000"),
            "trades_count": 25
        }

        await db.save_candle("DEC/USD", "1m", candle_data)
        print("✅ Saved candle data")

        return True
    except Exception as e:
        print(f"❌ Market data test failed: {e}")
        return False


async def main():
    """Run all database integration tests"""
    print("=" * 60)
    print("DATABASE INTEGRATION TEST SUITE")
    print("=" * 60)

    results = {}

    # Test database connection
    results['connection'] = await test_database_connection()

    if results['connection']:
        # Test user management
        user_id = await test_user_creation()
        results['user'] = user_id is not None

        # Test balance tracking
        if user_id:
            results['balance'] = await test_balance_operations(user_id)

        # Test order persistence
        order_id = await test_order_persistence()
        results['order'] = order_id is not None

        # Test trade persistence
        if order_id:
            results['trade'] = await test_trade_persistence(order_id)

        # Test integrated OMS
        results['oms'] = await test_integrated_oms_with_db()

        # Test market data
        results['market_data'] = await test_market_data()

    # Clean up
    await close_db_manager()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.ljust(20)}: {status}")

    total_passed = sum(1 for v in results.values() if v)
    total_tests = len(results)

    print(f"\nTotal: {total_passed}/{total_tests} tests passed")

    if total_passed == total_tests:
        print("\n🎉 ALL DATABASE TESTS PASSED!")
    else:
        print(f"\n⚠️  {total_tests - total_passed} tests failed")


if __name__ == "__main__":
    # Set environment variables for database
    os.environ["POSTGRES_HOST"] = "localhost"
    os.environ["POSTGRES_PORT"] = "5432"
    os.environ["POSTGRES_DB"] = "exchange_db"
    os.environ["POSTGRES_USER"] = "exchange_user"
    os.environ["POSTGRES_PASSWORD"] = "exchange_pass"

    asyncio.run(main())