#!/usr/bin/env python3
"""
Test Exchange Components Without Containers
Direct testing of matching engine, ledger, and WebSocket components
"""

import asyncio
import time
import sys
import os
from decimal import Decimal

# Add source to path
sys.path.insert(0, 'src/exchange')

# Test imports
print("Testing component imports...")
try:
    from matching_engine.ultra_fast_engine import UltraFastMatchingEngine
    print("✅ Matching engine imported")
except ImportError as e:
    print(f"❌ Matching engine import failed: {e}")
    sys.exit(1)

try:
    from ledger.decoin_ledger import DeCoinLedger, ExchangeSettlementBridge
    print("✅ DeCoin ledger imported")
except ImportError as e:
    print(f"❌ DeCoin ledger import failed: {e}")

try:
    from order_management.integrated_oms import IntegratedOMS
    print("✅ Integrated OMS imported")
except ImportError as e:
    print(f"❌ Integrated OMS import failed: {e}")

print("\n" + "="*60)
print("EXCHANGE COMPONENT TESTING")
print("="*60)

async def test_matching_engine():
    """Test the ultra-fast matching engine"""
    print("\n1. MATCHING ENGINE TEST")
    print("-" * 40)

    engine = UltraFastMatchingEngine("DEC/USD")

    # Place test orders
    print("Placing test orders...")

    # Place sell orders
    for i in range(5):
        price = 100.0 + i * 0.10
        order_id, trades = engine.place_order("sell", price, 10.0, user_id=1)

    # Place buy orders
    for i in range(5):
        price = 99.90 - i * 0.10
        order_id, trades = engine.place_order("buy", price, 10.0, user_id=2)

    # Get order book
    book = engine.get_order_book_snapshot(5)
    print(f"\nOrder Book Snapshot:")
    print(f"  Symbol: {book['symbol']}")
    if book['bids']:
        print(f"  Best Bid: ${book['bids'][0][0]:.2f} ({book['bids'][0][1]:.1f})")
    if book['asks']:
        print(f"  Best Ask: ${book['asks'][0][0]:.2f} ({book['asks'][0][1]:.1f})")
    if book['bids'] and book['asks']:
        spread = book['asks'][0][0] - book['bids'][0][0]
        print(f"  Spread: ${spread:.2f}")

    # Performance test
    print("\nPerformance test (10,000 orders)...")
    start = time.perf_counter()

    for i in range(10000):
        side = "buy" if i % 2 == 0 else "sell"
        price = 100.0 + (i % 20 - 10) * 0.01
        engine.place_order(side, price, 1.0, user_id=i % 100)

    elapsed = time.perf_counter() - start
    orders_per_second = 10000 / elapsed

    stats = engine.get_stats()
    print(f"\nResults:")
    print(f"  Orders processed: 10,000")
    print(f"  Time: {elapsed:.3f} seconds")
    print(f"  Throughput: {orders_per_second:,.0f} orders/second")
    print(f"  Trades executed: {stats['total_trades']}")

    if orders_per_second > 100000:
        print(f"  ✅ Performance target met (>100K orders/sec)")
    else:
        print(f"  ⚠️  Below target performance")

    return orders_per_second

async def test_decoin_ledger():
    """Test DeCoin ledger system"""
    print("\n2. DECOIN LEDGER TEST")
    print("-" * 40)

    # Initialize ledger (in-memory only)
    ledger = DeCoinLedger(redis_host="localhost", redis_port=6379)
    bridge = ExchangeSettlementBridge(ledger)

    print("Creating test addresses...")
    alice_addr = await bridge.get_user_address("alice")
    bob_addr = await bridge.get_user_address("bob")

    print(f"  Alice: {alice_addr}")
    print(f"  Bob:   {bob_addr}")

    # Fund accounts
    print("\nFunding accounts...")
    await bridge.deposit("alice", Decimal('1000'))
    await bridge.deposit("bob", Decimal('500'))

    print(f"  Alice balance: {await ledger.get_balance(alice_addr)} DEC")
    print(f"  Bob balance:   {await ledger.get_balance(bob_addr)} DEC")

    # Test transfers
    print("\nTesting transfers (100 transfers)...")
    start = time.perf_counter()

    for i in range(100):
        if i % 2 == 0:
            await bridge.settle_trade("bob", "alice", Decimal('1'))
        else:
            await bridge.settle_trade("alice", "bob", Decimal('1'))

    elapsed = time.perf_counter() - start
    avg_time = (elapsed / 100) * 1000  # Convert to ms

    print(f"\nResults:")
    print(f"  Transfers: 100")
    print(f"  Total time: {elapsed:.3f} seconds")
    print(f"  Average time: {avg_time:.2f}ms per transfer")

    if avg_time < 100:
        print(f"  ✅ Performance target met (<100ms)")
    else:
        print(f"  ⚠️  Above target latency")

    # Final balances
    print(f"\nFinal balances:")
    print(f"  Alice: {await ledger.get_balance(alice_addr)} DEC")
    print(f"  Bob:   {await ledger.get_balance(bob_addr)} DEC")

    stats = ledger.get_stats()
    print(f"\nLedger Statistics:")
    print(f"  Total transfers: {stats['total_transfers']}")
    print(f"  Total volume: {stats['total_volume']:.2f} DEC")

    return avg_time

async def test_integrated_oms():
    """Test integrated OMS"""
    print("\n3. INTEGRATED OMS TEST")
    print("-" * 40)

    oms = IntegratedOMS()

    # Initialize test accounts
    print("Setting up test accounts...")
    await oms.settlement_bridge.deposit("trader1", Decimal('10000'))
    await oms.settlement_bridge.deposit("trader2", Decimal('10000'))

    # Place orders
    print("\nPlacing orders...")

    # Trader1 sells DEC
    success, result = await oms.submit_order(
        user_id="trader1",
        symbol="DEC/USD",
        side="sell",
        order_type="limit",
        quantity=Decimal('100'),
        price=Decimal('100.00')
    )
    print(f"  Trader1 sell order: {'✅' if success else '❌'} ({result})")

    # Trader2 buys DEC
    success, result = await oms.submit_order(
        user_id="trader2",
        symbol="DEC/USD",
        side="buy",
        order_type="limit",
        quantity=Decimal('100'),
        price=Decimal('100.00')
    )
    print(f"  Trader2 buy order: {'✅' if success else '❌'} ({result})")

    # Check order book
    book = await oms.get_order_book("DEC/USD", 5)
    print(f"\nOrder book after trades:")
    print(f"  Bids: {len(book['bids'])} levels")
    print(f"  Asks: {len(book['asks'])} levels")

    # Get stats
    stats = oms.get_stats()
    print(f"\nOMS Statistics:")
    print(f"  Total orders: {stats['total_orders']}")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Active orders: {stats['active_orders']}")

    return stats['total_trades'] > 0

async def test_decoin_api():
    """Test connection to live DeCoin API"""
    print("\n4. DECOIN BLOCKCHAIN CONNECTION TEST")
    print("-" * 40)

    import aiohttp

    nodes = [
        ("Node 1", "http://localhost:11080"),
        ("Node 2", "http://localhost:11081"),
        ("Validator", "http://localhost:11083")
    ]

    async with aiohttp.ClientSession() as session:
        for node_name, url in nodes:
            try:
                async with session.get(f"{url}/blockchain", timeout=2) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        height = data.get('height', 'Unknown')
                        print(f"  {node_name}: ✅ Connected (Height: {height})")
                    else:
                        print(f"  {node_name}: ❌ Error {resp.status}")
            except Exception as e:
                print(f"  {node_name}: ❌ Connection failed")

async def main():
    """Run all tests"""
    print(f"Starting tests at {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # Test matching engine
    try:
        results['matching_engine'] = await test_matching_engine()
    except Exception as e:
        print(f"❌ Matching engine test failed: {e}")
        results['matching_engine'] = None

    # Test DeCoin ledger
    try:
        results['ledger'] = await test_decoin_ledger()
    except Exception as e:
        print(f"❌ DeCoin ledger test failed: {e}")
        results['ledger'] = None

    # Test integrated OMS
    try:
        results['oms'] = await test_integrated_oms()
    except Exception as e:
        print(f"❌ Integrated OMS test failed: {e}")
        results['oms'] = None

    # Test DeCoin API
    try:
        await test_decoin_api()
    except Exception as e:
        print(f"❌ DeCoin API test failed: {e}")

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    if results.get('matching_engine') and results['matching_engine'] > 100000:
        print("✅ Matching Engine: PASS ({:,.0f} orders/sec)".format(results['matching_engine']))
    else:
        print("❌ Matching Engine: FAIL")

    if results.get('ledger') and results['ledger'] < 100:
        print(f"✅ DeCoin Ledger: PASS ({results['ledger']:.2f}ms avg)")
    else:
        print("❌ DeCoin Ledger: FAIL")

    if results.get('oms'):
        print("✅ Integrated OMS: PASS")
    else:
        print("❌ Integrated OMS: FAIL")

    print("\n" + "="*60)
    print("TESTING COMPLETE")
    print("="*60)

if __name__ == "__main__":
    # Check if Redis is available
    import subprocess
    try:
        result = subprocess.run(["redis-cli", "ping"], capture_output=True, text=True)
        if result.stdout.strip() != "PONG":
            print("⚠️  Warning: Redis not responding. Some tests may fail.")
            print("   Start Redis with: redis-server")
    except:
        print("⚠️  Warning: Redis CLI not found. Some tests may fail.")

    # Run tests
    asyncio.run(main())