#!/usr/bin/env python3
"""
DeCoin Ledger Service
Manages DeCoin balances and settlements
"""

import asyncio
import os
import signal
import sys
from .decoin_ledger import DeCoinLedger, ExchangeSettlementBridge

class DeCoinLedgerService:
    def __init__(self):
        # Get configuration from environment
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))

        # PostgreSQL configuration
        postgres_config = None
        if os.getenv('POSTGRES_HOST'):
            postgres_config = {
                'host': os.getenv('POSTGRES_HOST'),
                'database': os.getenv('POSTGRES_DB', 'exchange_db'),
                'user': os.getenv('POSTGRES_USER', 'exchange_user'),
                'password': os.getenv('POSTGRES_PASSWORD', 'exchange_pass'),
                'port': int(os.getenv('POSTGRES_PORT', 5432))
            }

        # Initialize ledger
        self.ledger = DeCoinLedger(
            redis_host=redis_host,
            redis_port=redis_port,
            postgres_config=postgres_config,
            anchor_interval=3600  # Anchor every hour
        )

        self.settlement_bridge = ExchangeSettlementBridge(self.ledger)
        self.running = True

        print("DeCoin Ledger Service initialized")
        print(f"Redis: {redis_host}:{redis_port}")
        print(f"PostgreSQL: {postgres_config['host'] if postgres_config else 'Not configured'}")

    async def run(self):
        """Main service loop"""
        print("DeCoin Ledger Service started")

        # Initialize some test addresses
        await self.initialize_test_accounts()

        # Report statistics periodically
        while self.running:
            await asyncio.sleep(30)  # Report every 30 seconds

            stats = self.ledger.get_stats()
            print(f"Ledger Stats - Transfers: {stats['total_transfers']:,}, "
                  f"Volume: {stats['total_volume']:.2f} DEC, "
                  f"Avg time: {stats['average_transfer_time_ms']:.2f}ms")

    async def initialize_test_accounts(self):
        """Initialize test accounts for development"""
        if os.getenv('ENVIRONMENT') == 'development':
            print("Creating test accounts...")

            # Create test addresses
            test_users = ['alice', 'bob', 'charlie', 'market_maker']
            for user in test_users:
                address = await self.settlement_bridge.get_user_address(user)
                print(f"  {user}: {address}")

                # Fund market maker
                if user == 'market_maker':
                    await self.settlement_bridge.deposit(user, 1000000)
                    print(f"    Funded with 1,000,000 DEC")

    def shutdown(self, signum, frame):
        """Graceful shutdown"""
        print("\nShutting down DeCoin Ledger Service...")
        self.running = False
        sys.exit(0)

if __name__ == "__main__":
    service = DeCoinLedgerService()

    # Set up signal handlers
    signal.signal(signal.SIGINT, service.shutdown)
    signal.signal(signal.SIGTERM, service.shutdown)

    # Run service
    asyncio.run(service.run())