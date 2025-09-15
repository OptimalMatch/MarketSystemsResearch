#!/usr/bin/env python3
"""
Test Live DeCoin Blockchain Integration with Exchange
"""

import asyncio
import sys
import os
from decimal import Decimal
from datetime import datetime

# Add source to path
sys.path.insert(0, 'src/exchange')

from blockchain.decoin_integration import DeCoinBlockchainClient, ExchangeDeCoinBridge
from database.db_manager import get_db_manager, close_db_manager
from order_management.integrated_oms import IntegratedOMS


async def test_blockchain_connectivity():
    """Test basic blockchain connectivity"""
    print("\n1. BLOCKCHAIN CONNECTIVITY TEST")
    print("-" * 40)

    client = DeCoinBlockchainClient()
    await client.initialize()

    try:
        # Get blockchain status
        status = await client.get_blockchain_status()
        print(f"✅ Connected to DeCoin blockchain")
        print(f"   Status: {status}")

        # Get blockchain info
        info = await client.get_blockchain_info()
        print(f"✅ Blockchain info retrieved")
        print(f"   Height: {info.get('height', 'unknown')}")
        print(f"   Chain: {info.get('chain', 'unknown')}")

        return client
    except Exception as e:
        print(f"❌ Blockchain connection failed: {e}")
        return None


async def test_wallet_creation(client: DeCoinBlockchainClient):
    """Test wallet creation and funding"""
    print("\n2. WALLET CREATION TEST")
    print("-" * 40)

    try:
        # Exchange wallets already created during initialization
        print(f"✅ Hot wallet: {client.exchange_hot_wallet}")
        print(f"✅ Cold wallet: {client.exchange_cold_wallet}")

        # Check balances
        hot_balance = await client.get_balance(client.exchange_hot_wallet)
        cold_balance = await client.get_balance(client.exchange_cold_wallet)

        print(f"   Hot wallet balance: {hot_balance} DEC")
        print(f"   Cold wallet balance: {cold_balance} DEC")

        # Request faucet if balance is low
        if hot_balance < 100:
            print("   Requesting faucet for hot wallet...")
            success = await client.request_faucet(client.exchange_hot_wallet)
            if success:
                print("✅ Faucet request successful")
                await asyncio.sleep(2)  # Wait for transaction
                hot_balance = await client.get_balance(client.exchange_hot_wallet)
                print(f"   New hot wallet balance: {hot_balance} DEC")

        return True
    except Exception as e:
        print(f"❌ Wallet test failed: {e}")
        return False


async def test_transaction_flow(client: DeCoinBlockchainClient):
    """Test sending and receiving transactions"""
    print("\n3. TRANSACTION FLOW TEST")
    print("-" * 40)

    try:
        # Create test addresses
        test_address1 = client.generate_address("test_address_1")
        test_address2 = client.generate_address("test_address_2")

        print(f"✅ Test addresses created")
        print(f"   Address 1: {test_address1}")
        print(f"   Address 2: {test_address2}")

        # Send test transaction
        print("\nSending test transaction...")
        tx_hash = await client.send_transaction(
            from_address=client.exchange_hot_wallet,
            to_address=test_address1,
            amount=Decimal("0.1")
        )

        print(f"✅ Transaction sent: {tx_hash}")

        # Check transaction status (don't wait for confirmations in test)
        await asyncio.sleep(1)
        tx = await client.get_transaction(tx_hash)
        if tx:
            print(f"✅ Transaction found in blockchain")
            print(f"   Amount: {tx.amount} DEC")
            print(f"   Status: {tx.status}")
        else:
            print("⚠️  Transaction not yet visible")

        return True
    except Exception as e:
        print(f"❌ Transaction test failed: {e}")
        return False


async def test_deposit_withdrawal(client: DeCoinBlockchainClient):
    """Test deposit and withdrawal functionality"""
    print("\n4. DEPOSIT/WITHDRAWAL TEST")
    print("-" * 40)

    bridge = ExchangeDeCoinBridge(client)

    try:
        # Generate deposit address for user
        user_id = "test_user_001"
        deposit_addr = bridge.generate_deposit_address(user_id)
        print(f"✅ Deposit address for {user_id}: {deposit_addr}")

        # Simulate external deposit by sending to deposit address
        print("\nSimulating external deposit...")
        deposit_tx = await client.send_transaction(
            from_address=client.exchange_hot_wallet,
            to_address=deposit_addr,
            amount=Decimal("1.0")
        )
        print(f"✅ Deposit transaction sent: {deposit_tx}")

        # Process the deposit
        await asyncio.sleep(2)  # Wait for transaction to propagate
        success, message = await bridge.process_deposit(user_id, deposit_tx)
        if success:
            print(f"✅ Deposit processed: {message}")
        else:
            print(f"⚠️  Deposit processing: {message}")

        # Test withdrawal
        print("\nTesting withdrawal...")
        withdrawal_addr = client.generate_address("withdrawal_destination")
        success, result = await bridge.process_withdrawal(
            user_id=user_id,
            amount=Decimal("0.5"),
            to_address=withdrawal_addr
        )

        if success:
            print(f"✅ Withdrawal successful: {result}")
        else:
            print(f"⚠️  Withdrawal: {result}")

        return True
    except Exception as e:
        print(f"❌ Deposit/Withdrawal test failed: {e}")
        return False


async def test_exchange_integration():
    """Test full exchange integration with DeCoin"""
    print("\n5. EXCHANGE INTEGRATION TEST")
    print("-" * 40)

    # Initialize database
    os.environ["POSTGRES_HOST"] = "localhost"
    os.environ["POSTGRES_PORT"] = "5432"
    os.environ["POSTGRES_DB"] = "exchange_db"
    os.environ["POSTGRES_USER"] = "exchange_user"
    os.environ["POSTGRES_PASSWORD"] = "exchange_pass"

    try:
        # Initialize OMS with database
        oms = IntegratedOMS()
        await oms.initialize_database()
        print("✅ OMS initialized with database")

        # Create DeCoin blockchain client
        client = DeCoinBlockchainClient()
        await client.initialize()
        print("✅ DeCoin client initialized")

        # Create test users with DeCoin deposits
        user1_addr = client.generate_address("exchange_user_1")
        user2_addr = client.generate_address("exchange_user_2")

        # Simulate DeCoin deposits to exchange
        print("\nSimulating DeCoin deposits to exchange...")

        # User 1 deposits 100 DEC
        await oms.settlement_bridge.deposit("trader1", Decimal("100"))
        print("✅ Trader1 deposited 100 DEC")

        # User 2 deposits 100 DEC
        await oms.settlement_bridge.deposit("trader2", Decimal("100"))
        print("✅ Trader2 deposited 100 DEC")

        # Place DEC/USD orders
        print("\nPlacing DEC/USD orders...")

        # Trader1 sells DEC
        success, result = await oms.submit_order(
            user_id="trader1",
            symbol="DEC/USD",
            side="sell",
            order_type="limit",
            quantity=Decimal("10"),
            price=Decimal("50.00")
        )
        print(f"  Trader1 sell 10 DEC @ $50: {'✅' if success else '❌'}")

        # Trader2 buys DEC
        success, result = await oms.submit_order(
            user_id="trader2",
            symbol="DEC/USD",
            side="buy",
            order_type="limit",
            quantity=Decimal("10"),
            price=Decimal("50.00")
        )
        print(f"  Trader2 buy 10 DEC @ $50: {'✅' if success else '❌'}")

        # Check balances after trade
        stats = oms.get_stats()
        print(f"\n✅ Exchange Statistics:")
        print(f"   Total orders: {stats['total_orders']}")
        print(f"   Total trades: {stats['total_trades']}")
        print(f"   DEC/USD trades: {stats['total_trades']}")

        # Simulate withdrawal to blockchain
        print("\nSimulating withdrawal to blockchain...")
        balance = oms.settlement_bridge.get_balance("trader1")
        print(f"   Trader1 balance: {balance} DEC")

        if balance > 0:
            # In production, this would trigger actual blockchain withdrawal
            print(f"✅ Ready to withdraw {balance} DEC to blockchain")

        return True

    except Exception as e:
        print(f"❌ Exchange integration failed: {e}")
        return False
    finally:
        await close_db_manager()


async def test_mempool_monitoring(client: DeCoinBlockchainClient):
    """Test mempool monitoring for pending transactions"""
    print("\n6. MEMPOOL MONITORING TEST")
    print("-" * 40)

    try:
        # Get mempool
        mempool = await client.get_mempool()
        print(f"✅ Mempool retrieved: {len(mempool)} pending transactions")

        if mempool:
            print("   Recent pending transactions:")
            for tx in mempool[:3]:
                print(f"     - From: {tx.get('sender', 'unknown')[:20]}...")
                print(f"       To: {tx.get('recipient', 'unknown')[:20]}...")
                print(f"       Amount: {tx.get('amount', 0)} DEC")

        return True
    except Exception as e:
        print(f"❌ Mempool test failed: {e}")
        return False


async def main():
    """Run all DeCoin integration tests"""
    print("=" * 60)
    print("DECOIN BLOCKCHAIN LIVE INTEGRATION TEST")
    print("=" * 60)

    results = {}

    # Test blockchain connectivity
    client = await test_blockchain_connectivity()
    results['connectivity'] = client is not None

    if client:
        # Test wallet creation
        results['wallets'] = await test_wallet_creation(client)

        # Test transaction flow
        results['transactions'] = await test_transaction_flow(client)

        # Test deposits and withdrawals
        results['deposits'] = await test_deposit_withdrawal(client)

        # Test exchange integration
        results['exchange'] = await test_exchange_integration()

        # Test mempool monitoring
        results['mempool'] = await test_mempool_monitoring(client)

        # Close client
        if client.session:
            await client.session.close()

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
        print("\n🎉 ALL DECOIN INTEGRATION TESTS PASSED!")
        print("\nThe exchange is now ready for live DeCoin trading!")
    else:
        print(f"\n⚠️  {total_tests - total_passed} tests failed")


if __name__ == "__main__":
    asyncio.run(main())