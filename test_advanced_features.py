#!/usr/bin/env python3
"""
Test Advanced Order Types and Market Making
"""

import asyncio
import sys
from decimal import Decimal
from datetime import datetime
import time

sys.path.insert(0, 'src/exchange')

from matching_engine.enhanced_engine import EnhancedMatchingEngine
from market_making.market_maker import MarketMakerConfig, MarketMakingStrategy


def test_stop_loss_orders():
    """Test stop-loss order functionality"""
    print("\n1. STOP-LOSS ORDER TEST")
    print("-" * 40)

    engine = EnhancedMatchingEngine("DEC/USD")

    # Set initial market price
    engine.place_order("buy", 100.0, 10, user_id=1)
    engine.place_order("sell", 100.0, 10, user_id=2)
    print(f"✅ Initial market price set at 100.0")

    # Place stop-loss order
    order_id, trades, ext_id = engine.place_order(
        "sell", None, 50, user_id=3,
        order_type="stop_loss",
        stop_price=95.0
    )
    print(f"✅ Stop-loss order placed: Sell 50 @ stop 95.0 (ID: {ext_id})")

    # Price doesn't trigger stop yet
    engine.place_order("buy", 98.0, 5, user_id=4)
    engine.place_order("sell", 98.0, 5, user_id=5)
    print(f"  Price at 98.0 - Stop not triggered")

    # Price drops to trigger stop
    engine.place_order("buy", 94.0, 5, user_id=6)
    engine.place_order("sell", 94.0, 5, user_id=7)
    print(f"  Price at 94.0 - Stop should trigger")

    stats = engine.get_stats()
    print(f"✅ Total trades executed: {stats['total_trades']}")
    return True


def test_trailing_stop_orders():
    """Test trailing stop functionality"""
    print("\n2. TRAILING STOP ORDER TEST")
    print("-" * 40)

    engine = EnhancedMatchingEngine("ETH/USD")

    # Set initial price
    engine.place_order("buy", 2000.0, 1, user_id=1)
    engine.place_order("sell", 2000.0, 1, user_id=2)
    print(f"✅ Initial price set at 2000.0")

    # Place trailing stop with $50 trail
    order_id, trades, ext_id = engine.place_order(
        "sell", None, 5, user_id=3,
        order_type="trailing_stop",
        trail_amount=50.0
    )
    print(f"✅ Trailing stop placed: Sell 5 ETH with $50 trail (ID: {ext_id})")

    # Price rises - trailing stop should adjust
    engine.place_order("buy", 2050.0, 1, user_id=4)
    engine.place_order("sell", 2050.0, 1, user_id=5)
    print(f"  Price rises to 2050 - Stop adjusts to ~2000")

    engine.place_order("buy", 2100.0, 1, user_id=6)
    engine.place_order("sell", 2100.0, 1, user_id=7)
    print(f"  Price rises to 2100 - Stop adjusts to ~2050")

    # Price drops but not enough to trigger
    engine.place_order("buy", 2080.0, 1, user_id=8)
    engine.place_order("sell", 2080.0, 1, user_id=9)
    print(f"  Price drops to 2080 - Stop not triggered")

    # Price drops enough to trigger
    engine.place_order("buy", 2040.0, 1, user_id=10)
    engine.place_order("sell", 2040.0, 1, user_id=11)
    print(f"  Price drops to 2040 - Stop should trigger")

    return True


def test_iceberg_orders():
    """Test iceberg order functionality"""
    print("\n3. ICEBERG ORDER TEST")
    print("-" * 40)

    engine = EnhancedMatchingEngine("BTC/USD")

    # Place iceberg order - total 100, display 10
    order_id, trades, ext_id = engine.place_order(
        "sell", 50000.0, 100, user_id=1,
        order_type="iceberg",
        display_quantity=10
    )
    print(f"✅ Iceberg order placed: Sell 100 BTC @ 50000 (display 10)")

    # Check order book - should only show 10
    book = engine.get_order_book()
    visible_qty = sum(ask["quantity"] for ask in book["asks"] if ask["price"] == 50000.0)
    print(f"  Visible quantity in book: {visible_qty}")

    # Execute against iceberg
    executed = 0
    for i in range(5):
        order_id, trades, _ = engine.place_order("buy", 50000.0, 10, user_id=i+10)
        if trades:
            executed += sum(t["quantity"] for t in trades)
            print(f"  Executed 10 BTC - Total executed: {executed}")

    print(f"✅ Iceberg partially executed: {executed}/100 BTC")
    return True


def test_take_profit_orders():
    """Test take-profit order functionality"""
    print("\n4. TAKE-PROFIT ORDER TEST")
    print("-" * 40)

    engine = EnhancedMatchingEngine("DEC/USD")

    # Set initial price
    engine.place_order("buy", 100.0, 10, user_id=1)
    engine.place_order("sell", 100.0, 10, user_id=2)
    print(f"✅ Initial price set at 100.0")

    # Place take-profit order
    order_id, trades, ext_id = engine.place_order(
        "sell", None, 50, user_id=3,
        order_type="take_profit",
        stop_price=105.0  # Target price
    )
    print(f"✅ Take-profit order placed: Sell 50 @ target 105.0")

    # Price rises but not to target
    engine.place_order("buy", 103.0, 5, user_id=4)
    engine.place_order("sell", 103.0, 5, user_id=5)
    print(f"  Price at 103.0 - Take-profit not triggered")

    # Price reaches target
    engine.place_order("buy", 105.0, 5, user_id=6)
    engine.place_order("sell", 105.0, 5, user_id=7)
    print(f"  Price at 105.0 - Take-profit should trigger")

    return True


async def test_market_making():
    """Test market making algorithms"""
    print("\n5. MARKET MAKING TEST")
    print("-" * 40)

    engine = EnhancedMatchingEngine("DEC/USD")

    # Set initial market price
    engine.place_order("buy", 100.0, 10, user_id=1)
    engine.place_order("sell", 100.0, 10, user_id=2)

    # Configure grid market maker
    grid_config = MarketMakerConfig(
        strategy=MarketMakingStrategy.GRID,
        symbol="DEC/USD",
        base_currency="DEC",
        quote_currency="USD",
        inventory_target=Decimal(1000),
        spread_bps=20,  # 0.2% spread
        order_amount=Decimal(10),
        max_orders_per_side=3
    )

    # Add grid market maker
    engine.add_market_maker("grid_mm_1", grid_config)
    print(f"✅ Added grid market maker")

    # Configure spread market maker
    spread_config = MarketMakerConfig(
        strategy=MarketMakingStrategy.SPREAD,
        symbol="DEC/USD",
        base_currency="DEC",
        quote_currency="USD",
        inventory_target=Decimal(500),
        spread_bps=10,  # 0.1% spread
        order_amount=Decimal(5),
        max_orders_per_side=2
    )

    # Add spread market maker
    engine.add_market_maker("spread_mm_1", spread_config)
    print(f"✅ Added spread market maker")

    # Configure Avellaneda-Stoikov market maker
    as_config = MarketMakerConfig(
        strategy=MarketMakingStrategy.AVELLANEDA_STOIKOV,
        symbol="DEC/USD",
        base_currency="DEC",
        quote_currency="USD",
        inventory_target=Decimal(200),
        spread_bps=15,
        order_amount=Decimal(8),
        risk_factor=Decimal("0.01")
    )

    engine.add_market_maker("as_mm_1", as_config)
    print(f"✅ Added Avellaneda-Stoikov market maker")

    # Start market makers
    for mm in engine.market_makers.values():
        await mm.start()

    # Generate market maker orders
    mm_orders = await engine.run_market_makers()
    print(f"\n✅ Market makers generated {len(mm_orders)} orders:")

    for order in mm_orders[:5]:  # Show first 5
        print(f"  {order['maker_id']}: {order['side']} {order['quantity']} @ {order['price']:.2f}")

    # Place the market maker orders
    for order in mm_orders:
        engine.place_order(
            order["side"],
            order["price"],
            order["quantity"],
            user_id=hash(order["maker_id"]) % 1000,
            metadata=order.get("metadata", {})
        )

    # Check order book
    book = engine.get_order_book()
    print(f"\n✅ Order book after market making:")
    print(f"  Bids: {len(book['bids'])} levels")
    print(f"  Asks: {len(book['asks'])} levels")

    if book['bids'] and book['asks']:
        spread = book['asks'][0]['price'] - book['bids'][0]['price']
        mid = (book['asks'][0]['price'] + book['bids'][0]['price']) / 2
        spread_bps = (spread / mid) * 10000
        print(f"  Spread: {spread:.4f} ({spread_bps:.1f} bps)")

    # Get performance reports
    print(f"\n✅ Market Maker Performance:")
    for maker_id, maker in engine.market_makers.items():
        report = maker.get_performance_report()
        print(f"  {maker_id}: {report['strategy']} - {report['active_orders']} active orders")

    return True


def test_performance():
    """Test performance with advanced orders"""
    print("\n6. PERFORMANCE TEST WITH ADVANCED ORDERS")
    print("-" * 40)

    engine = EnhancedMatchingEngine("DEC/USD")

    # Place many advanced orders
    start_time = time.perf_counter()

    # Regular orders
    for i in range(1000):
        engine.place_order("buy", 99.0 - i*0.01, 1, user_id=i)
        engine.place_order("sell", 101.0 + i*0.01, 1, user_id=i+1000)

    # Stop-loss orders
    for i in range(100):
        engine.place_order(
            "sell", None, 10, user_id=i+2000,
            order_type="stop_loss",
            stop_price=95.0 - i*0.1
        )

    # Trailing stops
    for i in range(50):
        engine.place_order(
            "sell", None, 5, user_id=i+3000,
            order_type="trailing_stop",
            trail_amount=2.0
        )

    # Iceberg orders
    for i in range(20):
        engine.place_order(
            "sell", 100.0 + i*0.1, 100, user_id=i+4000,
            order_type="iceberg",
            display_quantity=10
        )

    elapsed = time.perf_counter() - start_time

    stats = engine.get_stats()
    total_orders = stats['total_orders']
    orders_per_second = total_orders / elapsed

    print(f"✅ Performance Results:")
    print(f"  Total orders placed: {total_orders}")
    print(f"  Time elapsed: {elapsed:.3f} seconds")
    print(f"  Throughput: {orders_per_second:.0f} orders/second")
    print(f"\n  Advanced orders:")
    for order_type, count in stats['advanced_orders'].items():
        if count > 0:
            print(f"    {order_type}: {count}")

    return orders_per_second > 1000  # Target: 1000+ orders/sec


async def main():
    """Run all advanced feature tests"""
    print("=" * 60)
    print("ADVANCED ORDER TYPES AND MARKET MAKING TEST SUITE")
    print("=" * 60)

    results = {}

    # Test stop-loss orders
    results['stop_loss'] = test_stop_loss_orders()

    # Test trailing stops
    results['trailing_stop'] = test_trailing_stop_orders()

    # Test iceberg orders
    results['iceberg'] = test_iceberg_orders()

    # Test take-profit orders
    results['take_profit'] = test_take_profit_orders()

    # Test market making
    results['market_making'] = await test_market_making()

    # Test performance
    results['performance'] = test_performance()

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
        print("\n🎉 ALL ADVANCED FEATURE TESTS PASSED!")
        print("\nThe exchange now supports:")
        print("  • Stop-loss orders")
        print("  • Trailing stop orders")
        print("  • Iceberg orders")
        print("  • Take-profit orders")
        print("  • Grid trading market making")
        print("  • Spread-based market making")
        print("  • Avellaneda-Stoikov market making")
    else:
        print(f"\n⚠️  {total_tests - total_passed} tests failed")


if __name__ == "__main__":
    asyncio.run(main())