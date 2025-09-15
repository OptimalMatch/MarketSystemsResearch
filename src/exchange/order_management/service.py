#!/usr/bin/env python3
"""
Order Management Service
Manages order lifecycle, validation, and routing
"""

import asyncio
import os
import signal
import sys
from typing import Optional
import logging
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from exchange.order_management.integrated_oms import IntegratedOMS
from exchange.matching_engine.ultra_fast_engine import UltraFastMatchingEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OMSService:
    """Order Management Service wrapper"""

    def __init__(self):
        self.oms: Optional[IntegratedOMS] = None
        self.running = False

    async def start(self):
        """Start the OMS service"""
        logger.info("Starting Order Management Service...")

        try:
            # Initialize OMS
            self.oms = IntegratedOMS()

            # Initialize test accounts if in development
            if os.getenv('ENVIRONMENT', 'development') == 'development':
                await self.setup_test_accounts()

            self.running = True
            logger.info("OMS Service started successfully")

            # Keep service running
            while self.running:
                await asyncio.sleep(1)
                # Could add periodic tasks here (health checks, cleanup, etc.)

        except Exception as e:
            logger.error(f"Failed to start OMS: {e}")
            raise

    async def setup_test_accounts(self):
        """Setup test accounts for development"""
        logger.info("Setting up test accounts...")

        test_accounts = [
            ("alice", Decimal("100000")),
            ("bob", Decimal("50000")),
            ("charlie", Decimal("25000")),
            ("market_maker", Decimal("1000000"))
        ]

        for user_id, amount in test_accounts:
            try:
                await self.oms.settlement_bridge.deposit(user_id, amount)
                logger.info(f"Funded {user_id} with {amount} DEC")
            except Exception as e:
                logger.warning(f"Could not fund {user_id}: {e}")

    async def stop(self):
        """Stop the OMS service"""
        logger.info("Stopping OMS Service...")
        self.running = False

        # Cleanup tasks
        if self.oms:
            stats = self.oms.get_stats()
            logger.info(f"Final stats: {stats}")

    def handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        asyncio.create_task(self.stop())


async def main():
    """Main entry point"""
    service = OMSService()

    # Setup signal handlers
    signal.signal(signal.SIGINT, service.handle_signal)
    signal.signal(signal.SIGTERM, service.handle_signal)

    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        await service.stop()


if __name__ == "__main__":
    logger.info("Order Management Service starting...")
    asyncio.run(main())