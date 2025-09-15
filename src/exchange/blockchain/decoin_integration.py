"""
DeCoin Blockchain Integration for Exchange
Handles real deposits, withdrawals, and settlement with live DeCoin blockchain
"""

import asyncio
import aiohttp
import hashlib
import json
from typing import Dict, Optional, List, Tuple
from decimal import Decimal
from datetime import datetime
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeCoinTransaction:
    """Represents a DeCoin blockchain transaction"""
    tx_hash: str
    from_address: str
    to_address: str
    amount: Decimal
    timestamp: datetime
    confirmations: int
    status: str


class DeCoinBlockchainClient:
    """Client for interacting with live DeCoin blockchain"""

    def __init__(self, node_url: str = "http://localhost:11080"):
        self.node_url = node_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.exchange_hot_wallet: Optional[str] = None
        self.exchange_cold_wallet: Optional[str] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def initialize(self):
        """Initialize connection and create exchange wallets"""
        if not self.session:
            self.session = aiohttp.ClientSession()

        # Check blockchain status
        status = await self.get_blockchain_status()
        logger.info(f"Connected to DeCoin blockchain: {status}")

        # Generate exchange wallets
        self.exchange_hot_wallet = self.generate_address("exchange_hot_wallet")
        self.exchange_cold_wallet = self.generate_address("exchange_cold_wallet")

        logger.info(f"Exchange hot wallet: {self.exchange_hot_wallet}")
        logger.info(f"Exchange cold wallet: {self.exchange_cold_wallet}")

        # Request initial funds from faucet for testing
        await self.request_faucet(self.exchange_hot_wallet)

        return True

    def generate_address(self, seed: str) -> str:
        """Generate deterministic DeCoin address from seed"""
        # DeCoin addresses start with "DEC" followed by hash
        hash_obj = hashlib.sha256(seed.encode())
        address_hash = hashlib.sha256(hash_obj.digest()).hexdigest()[:32]
        return f"DEC{address_hash}"

    async def get_blockchain_status(self) -> Dict:
        """Get current blockchain status"""
        async with self.session.get(f"{self.node_url}/status") as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"Failed to get blockchain status: {response.status}")

    async def get_blockchain_info(self) -> Dict:
        """Get blockchain information"""
        async with self.session.get(f"{self.node_url}/blockchain") as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"Failed to get blockchain info: {response.status}")

    async def get_balance(self, address: str) -> Decimal:
        """Get balance for a DeCoin address"""
        async with self.session.get(f"{self.node_url}/balance/{address}") as response:
            if response.status == 200:
                data = await response.json()
                return Decimal(str(data.get("balance", 0)))
            else:
                return Decimal("0")

    async def get_transactions(self, address: str) -> List[Dict]:
        """Get transactions for an address"""
        async with self.session.get(f"{self.node_url}/transactions/{address}") as response:
            if response.status == 200:
                return await response.json()
            else:
                return []

    async def send_transaction(self, from_address: str, to_address: str,
                              amount: Decimal, private_key: Optional[str] = None) -> str:
        """Send a DeCoin transaction"""
        tx_data = {
            "sender": from_address,
            "recipient": to_address,
            "amount": float(amount),  # DeCoin API expects float
            "timestamp": datetime.utcnow().isoformat()
        }

        # Sign transaction if private key provided
        if private_key:
            signature = self.sign_transaction(tx_data, private_key)
            tx_data["signature"] = signature

        async with self.session.post(
            f"{self.node_url}/transaction",
            json=tx_data,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 200:
                result = await response.json()
                # DeCoin returns transaction_id in data field
                if "data" in result:
                    tx_hash = result["data"].get("transaction_id")
                else:
                    tx_hash = result.get("tx_hash", result.get("hash", result.get("transaction_id")))
                logger.info(f"Transaction sent: {tx_hash}")
                return tx_hash
            else:
                error = await response.text()
                raise Exception(f"Transaction failed: {error}")

    def sign_transaction(self, tx_data: Dict, private_key: str) -> str:
        """Sign a transaction with private key"""
        # Simplified signing for testing
        message = json.dumps(tx_data, sort_keys=True)
        signature = hashlib.sha256(f"{message}{private_key}".encode()).hexdigest()
        return signature

    async def get_transaction(self, tx_hash: str) -> Optional[DeCoinTransaction]:
        """Get transaction details by hash"""
        async with self.session.get(f"{self.node_url}/transaction/{tx_hash}") as response:
            if response.status == 200:
                data = await response.json()
                return DeCoinTransaction(
                    tx_hash=data.get("hash", tx_hash),
                    from_address=data.get("from"),
                    to_address=data.get("to"),
                    amount=Decimal(str(data.get("amount", 0))),
                    timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
                    confirmations=data.get("confirmations", 0),
                    status=data.get("status", "pending")
                )
            else:
                return None

    async def wait_for_confirmations(self, tx_hash: str, required_confirmations: int = 1,
                                    timeout: int = 60) -> bool:
        """Wait for transaction to be confirmed"""
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            tx = await self.get_transaction(tx_hash)
            if tx and tx.confirmations >= required_confirmations:
                logger.info(f"Transaction {tx_hash} confirmed with {tx.confirmations} confirmations")
                return True

            await asyncio.sleep(2)  # Check every 2 seconds

        logger.warning(f"Timeout waiting for confirmations on {tx_hash}")
        return False

    async def request_faucet(self, address: str) -> bool:
        """Request test tokens from faucet"""
        async with self.session.post(f"{self.node_url}/faucet/{address}") as response:
            if response.status == 200:
                result = await response.json()
                logger.info(f"Faucet request successful: {result}")
                return True
            else:
                logger.warning(f"Faucet request failed for {address}")
                return False

    async def get_mempool(self) -> List[Dict]:
        """Get pending transactions in mempool"""
        async with self.session.get(f"{self.node_url}/mempool") as response:
            if response.status == 200:
                return await response.json()
            else:
                return []


class ExchangeDeCoinBridge:
    """Bridge between exchange and DeCoin blockchain for deposits/withdrawals"""

    def __init__(self, blockchain_client: DeCoinBlockchainClient):
        self.blockchain = blockchain_client
        self.deposit_addresses: Dict[str, str] = {}  # user_id -> deposit_address
        self.pending_deposits: Dict[str, Dict] = {}  # tx_hash -> deposit_info
        self.pending_withdrawals: Dict[str, Dict] = {}  # tx_hash -> withdrawal_info

    def generate_deposit_address(self, user_id: str) -> str:
        """Generate unique deposit address for user"""
        if user_id not in self.deposit_addresses:
            # Generate deterministic address based on user_id
            address = self.blockchain.generate_address(f"user_deposit_{user_id}")
            self.deposit_addresses[user_id] = address
            logger.info(f"Generated deposit address for user {user_id}: {address}")

        return self.deposit_addresses[user_id]

    async def process_deposit(self, user_id: str, tx_hash: str) -> Tuple[bool, str]:
        """Process a deposit transaction from blockchain"""
        try:
            # Get transaction details
            tx = await self.blockchain.get_transaction(tx_hash)
            if not tx:
                return False, "Transaction not found"

            # Verify destination is user's deposit address
            expected_address = self.deposit_addresses.get(user_id)
            if tx.to_address != expected_address:
                return False, "Invalid deposit address"

            # Wait for confirmations
            confirmed = await self.blockchain.wait_for_confirmations(
                tx_hash,
                required_confirmations=1,  # Low for testing, use 6+ in production
                timeout=120
            )

            if not confirmed:
                return False, "Transaction not confirmed"

            # Credit user's exchange balance
            # This would integrate with the exchange's balance system
            logger.info(f"Deposit confirmed: {tx.amount} DEC for user {user_id}")

            return True, f"Deposited {tx.amount} DEC"

        except Exception as e:
            logger.error(f"Deposit processing error: {e}")
            return False, str(e)

    async def process_withdrawal(self, user_id: str, amount: Decimal,
                                to_address: str) -> Tuple[bool, str]:
        """Process a withdrawal from exchange to blockchain"""
        try:
            # Verify user has sufficient balance
            # This would check the exchange's balance system

            # Send transaction from hot wallet
            tx_hash = await self.blockchain.send_transaction(
                from_address=self.blockchain.exchange_hot_wallet,
                to_address=to_address,
                amount=amount
            )

            # Track pending withdrawal
            self.pending_withdrawals[tx_hash] = {
                "user_id": user_id,
                "amount": amount,
                "to_address": to_address,
                "timestamp": datetime.utcnow(),
                "status": "pending"
            }

            # Wait for confirmation
            confirmed = await self.blockchain.wait_for_confirmations(tx_hash, 1, 120)

            if confirmed:
                self.pending_withdrawals[tx_hash]["status"] = "confirmed"
                logger.info(f"Withdrawal confirmed: {amount} DEC to {to_address}")
                return True, tx_hash
            else:
                self.pending_withdrawals[tx_hash]["status"] = "failed"
                return False, "Transaction not confirmed"

        except Exception as e:
            logger.error(f"Withdrawal processing error: {e}")
            return False, str(e)

    async def scan_deposits(self):
        """Scan blockchain for new deposits to user addresses"""
        for user_id, address in self.deposit_addresses.items():
            transactions = await self.blockchain.get_transactions(address)

            for tx in transactions:
                tx_hash = tx.get("hash")
                if tx_hash not in self.pending_deposits:
                    # New deposit detected
                    self.pending_deposits[tx_hash] = {
                        "user_id": user_id,
                        "amount": Decimal(str(tx.get("amount", 0))),
                        "timestamp": datetime.utcnow(),
                        "status": "detected"
                    }

                    logger.info(f"New deposit detected: {tx_hash} for user {user_id}")

                    # Process the deposit
                    success, message = await self.process_deposit(user_id, tx_hash)
                    self.pending_deposits[tx_hash]["status"] = "completed" if success else "failed"

    async def get_hot_wallet_balance(self) -> Decimal:
        """Get hot wallet balance"""
        return await self.blockchain.get_balance(self.blockchain.exchange_hot_wallet)

    async def get_cold_wallet_balance(self) -> Decimal:
        """Get cold wallet balance"""
        return await self.blockchain.get_balance(self.blockchain.exchange_cold_wallet)

    async def move_to_cold_storage(self, amount: Decimal) -> str:
        """Move funds from hot to cold wallet"""
        return await self.blockchain.send_transaction(
            from_address=self.blockchain.exchange_hot_wallet,
            to_address=self.blockchain.exchange_cold_wallet,
            amount=amount
        )


async def test_blockchain_integration():
    """Test DeCoin blockchain integration"""
    print("Testing DeCoin Blockchain Integration")
    print("=" * 50)

    async with DeCoinBlockchainClient() as client:
        await client.initialize()

        # Get blockchain info
        info = await client.get_blockchain_info()
        print(f"Blockchain height: {info.get('height', 'unknown')}")

        # Check hot wallet balance
        balance = await client.get_balance(client.exchange_hot_wallet)
        print(f"Hot wallet balance: {balance} DEC")

        # Create bridge
        bridge = ExchangeDeCoinBridge(client)

        # Generate deposit address for test user
        deposit_addr = bridge.generate_deposit_address("test_user_001")
        print(f"Deposit address for test_user_001: {deposit_addr}")

        # Test withdrawal (small amount)
        success, result = await bridge.process_withdrawal(
            "test_user_001",
            Decimal("1.0"),
            deposit_addr  # Send to same address for testing
        )
        print(f"Withdrawal test: {'Success' if success else 'Failed'} - {result}")

        # Scan for deposits
        await bridge.scan_deposits()

        print("\nIntegration test completed!")


if __name__ == "__main__":
    asyncio.run(test_blockchain_integration())