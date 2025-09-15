#!/usr/bin/env python3
"""
Matching Engine Service
Runs the ultra-fast matching engine as a standalone service
"""

import asyncio
import os
import signal
import sys
from ultra_fast_engine import UltraFastMatchingEngine, BatchOptimizedEngine

class MatchingEngineService:
    def __init__(self):
        self.engines = {}
        self.running = True

        # Initialize engines for each symbol
        self.symbols = ["DEC/USD", "BTC/USD", "ETH/USD", "DEC/BTC"]
        for symbol in self.symbols:
            self.engines[symbol] = UltraFastMatchingEngine(symbol)

        print(f"Initialized matching engines for {len(self.symbols)} symbols")

    async def run(self):
        """Main service loop"""
        print("Matching Engine Service started")
        print(f"Symbols: {', '.join(self.symbols)}")

        # Report statistics periodically
        while self.running:
            await asyncio.sleep(30)  # Report every 30 seconds

            total_orders = sum(e.total_orders for e in self.engines.values())
            total_trades = sum(e.total_trades for e in self.engines.values())

            print(f"Stats - Orders: {total_orders:,}, Trades: {total_trades:,}")

    def shutdown(self, signum, frame):
        """Graceful shutdown"""
        print("\nShutting down Matching Engine Service...")
        self.running = False
        sys.exit(0)

if __name__ == "__main__":
    service = MatchingEngineService()

    # Set up signal handlers
    signal.signal(signal.SIGINT, service.shutdown)
    signal.signal(signal.SIGTERM, service.shutdown)

    # Run service
    asyncio.run(service.run())