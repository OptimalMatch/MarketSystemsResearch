"""
Simplified DeCoin Blockchain Bridge for Exchange
Handles deposits and withdrawals with the live DeCoin blockchain
"""

import aiohttp
import asyncio
import hashlib
from typing import Dict, Optional, List
from decimal import Decimal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class SimpleDeCoinBridge:
    """Simplified bridge for DeCoin blockchain integration"""

    def __init__(self, node_url: str = "http://localhost:11080"):
        self.node_url = node_url
        self.exchange_address = self.generate_address("exchange_master")
        self.pending_deposits: Dict[str, Dict] = {}
        self.pending_withdrawals: Dict[str, Dict] = {}
        logger.info(f"Exchange master address: {self.exchange_address}")

    def generate_address(self, seed: str) -> str:
        """Generate deterministic DeCoin address"""
        hash_bytes = hashlib.sha256(seed.encode()).digest()
        address_hash = hashlib.sha256(hash_bytes).hexdigest()[:32]
        return f"DEC{address_hash}"

    def get_user_deposit_address(self, user_id: str) -> str:
        """Get unique deposit address for user"""
        return self.generate_address(f"deposit_{user_id}")

    async def submit_transaction(self, sender: str, recipient: str, amount: float) -> Dict:
        """Submit transaction to DeCoin blockchain"""
        async with aiohttp.ClientSession() as session:
            tx_data = {
                "sender": sender,
                "recipient": recipient,
                "amount": amount
            }

            try:
                async with session.post(
                    f"{self.node_url}/transaction",
                    json=tx_data,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result
                    else:
                        error = await response.text()
                        logger.error(f"Transaction failed: {error}")
                        return {"success": False, "error": error}
            except Exception as e:
                logger.error(f"Transaction error: {e}")
                return {"success": False, "error": str(e)}

    async def get_blockchain_info(self) -> Dict:
        """Get blockchain information"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.node_url}/blockchain",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return {}
            except Exception as e:
                logger.error(f"Failed to get blockchain info: {e}")
                return {}

    async def get_balance(self, address: str) -> float:
        """Get balance for an address"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.node_url}/balance/{address}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("balance", 0.0)
                    return 0.0
            except Exception as e:
                logger.error(f"Failed to get balance: {e}")
                return 0.0

    async def process_deposit(self, user_id: str, amount: Decimal) -> Dict:
        """Process a deposit from blockchain to exchange"""
        deposit_address = self.get_user_deposit_address(user_id)

        # In production, this would verify actual blockchain transaction
        # For now, we simulate by creating a transaction record
        tx_result = await self.submit_transaction(
            sender=deposit_address,
            recipient=self.exchange_address,
            amount=float(amount)
        )

        if tx_result.get("success"):
            tx_id = tx_result.get("data", {}).get("transaction_id", "unknown")
            self.pending_deposits[tx_id] = {
                "user_id": user_id,
                "amount": amount,
                "timestamp": datetime.utcnow(),
                "status": "confirmed"
            }
            logger.info(f"Deposit processed: {amount} DEC for user {user_id}")
            return {"success": True, "tx_id": tx_id, "amount": amount}
        else:
            return {"success": False, "error": tx_result.get("error", "Unknown error")}

    async def process_withdrawal(self, user_id: str, amount: Decimal, to_address: str) -> Dict:
        """Process a withdrawal from exchange to blockchain"""
        # Submit transaction from exchange to user's external address
        tx_result = await self.submit_transaction(
            sender=self.exchange_address,
            recipient=to_address,
            amount=float(amount)
        )

        if tx_result.get("success"):
            tx_id = tx_result.get("data", {}).get("transaction_id", "unknown")
            self.pending_withdrawals[tx_id] = {
                "user_id": user_id,
                "amount": amount,
                "to_address": to_address,
                "timestamp": datetime.utcnow(),
                "status": "confirmed"
            }
            logger.info(f"Withdrawal processed: {amount} DEC to {to_address}")
            return {"success": True, "tx_id": tx_id, "amount": amount}
        else:
            return {"success": False, "error": tx_result.get("error", "Unknown error")}

    async def get_transaction_status(self, tx_id: str) -> Dict:
        """Get status of a transaction"""
        # Check deposits
        if tx_id in self.pending_deposits:
            return self.pending_deposits[tx_id]

        # Check withdrawals
        if tx_id in self.pending_withdrawals:
            return self.pending_withdrawals[tx_id]

        # Query blockchain
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.node_url}/transaction/{tx_id}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return {"status": "not_found"}
            except Exception as e:
                logger.error(f"Failed to get transaction status: {e}")
                return {"status": "error", "error": str(e)}


async def test_bridge():
    """Test the simplified DeCoin bridge"""
    print("Testing Simplified DeCoin Bridge")
    print("=" * 50)

    bridge = SimpleDeCoinBridge()

    # Get blockchain info
    info = await bridge.get_blockchain_info()
    print(f"Blockchain height: {info.get('height', 'unknown')}")
    print(f"Exchange address: {bridge.exchange_address}")

    # Test deposit address generation
    user_id = "test_user_001"
    deposit_addr = bridge.get_user_deposit_address(user_id)
    print(f"Deposit address for {user_id}: {deposit_addr}")

    # Test deposit
    print("\nTesting deposit...")
    deposit_result = await bridge.process_deposit(user_id, Decimal("10.0"))
    if deposit_result.get("success"):
        print(f"✅ Deposit successful: {deposit_result}")
    else:
        print(f"❌ Deposit failed: {deposit_result}")

    # Test withdrawal
    print("\nTesting withdrawal...")
    withdrawal_addr = bridge.generate_address("external_wallet")
    withdrawal_result = await bridge.process_withdrawal(
        user_id,
        Decimal("5.0"),
        withdrawal_addr
    )
    if withdrawal_result.get("success"):
        print(f"✅ Withdrawal successful: {withdrawal_result}")
    else:
        print(f"❌ Withdrawal failed: {withdrawal_result}")

    # Check balances
    print("\nChecking balances...")
    exchange_balance = await bridge.get_balance(bridge.exchange_address)
    print(f"Exchange balance: {exchange_balance} DEC")

    print("\nBridge test completed!")


if __name__ == "__main__":
    asyncio.run(test_bridge())