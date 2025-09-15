"""
DeCoin Ledger System - Ultra-fast internal ledger with blockchain anchoring
Integrates with existing DeCoin blockchain at /home/unidatum/github/decoin/
"""

import asyncio
import time
import json
import hashlib
import redis

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # Make PostgreSQL optional
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import threading
from collections import defaultdict, deque
import uuid
import sys
import os

# Add DeCoin source to path for integration (optional)
try:
    sys.path.insert(0, '/home/unidatum/github/decoin/src')
    # Import DeCoin blockchain components
    from blockchain import Transaction as DecoinTransaction, TransactionType, Block
    from transactions import TransactionBuilder
    DECOIN_AVAILABLE = True
except ImportError:
    # DeCoin not available - will run in standalone mode
    DecoinTransaction = None
    TransactionType = None
    Block = None
    TransactionBuilder = None
    DECOIN_AVAILABLE = False

class TransferStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    ANCHORED = "anchored"

@dataclass
class InternalTransfer:
    """Ultra-fast internal transfer record"""
    id: str
    from_address: str
    to_address: str
    amount: Decimal
    timestamp: float
    status: TransferStatus
    tx_hash: Optional[str] = None
    block_height: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WalletBalance:
    """Wallet balance with available and pending amounts"""
    address: str
    available: Decimal
    pending: Decimal
    total: Decimal
    last_updated: float

class DeCoinLedger:
    """
    High-performance internal ledger for DeCoin
    - Instant internal transfers (<100ms)
    - Redis for balance caching
    - PostgreSQL for transaction history
    - Periodic blockchain anchoring for external verification
    """

    def __init__(self,
                 redis_host: str = "localhost",
                 redis_port: int = 6379,
                 postgres_config: Optional[Dict] = None,
                 anchor_interval: int = 3600):  # Anchor every hour

        # Initialize Redis for ultra-fast balance queries
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
                connection_pool=redis.ConnectionPool(max_connections=100)
            )
            # Test connection
            self.redis_client.ping()
        except:
            # Fallback to in-memory only if Redis not available
            self.redis_client = None
            print("Warning: Redis not available, using in-memory cache only")

        # PostgreSQL for persistent transaction log
        if postgres_config and psycopg2:
            self.postgres_conn = psycopg2.connect(**postgres_config)
            self.init_database()
        else:
            self.postgres_conn = None

        # In-memory balance cache (backup for Redis)
        self.balance_cache: Dict[str, Decimal] = {}
        self.balance_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)

        # Transaction queues
        self.pending_transfers = deque(maxlen=100000)
        self.completed_transfers = deque(maxlen=100000)

        # Statistics
        self.total_transfers = 0
        self.total_volume = Decimal('0')
        self.transfer_times = deque(maxlen=1000)  # Last 1000 transfer times

        # Blockchain anchoring
        self.anchor_interval = anchor_interval
        self.last_anchor_time = time.time()
        self.anchor_queue = []

        # Address generation
        self.address_prefix = "DEC"
        self.address_counter = 0

        # Start background tasks
        self._start_background_tasks()

    def init_database(self):
        """Initialize PostgreSQL tables"""
        if not self.postgres_conn:
            return

        cursor = self.postgres_conn.cursor()

        # Create transfers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decoin_transfers (
                id VARCHAR(64) PRIMARY KEY,
                from_address VARCHAR(64) NOT NULL,
                to_address VARCHAR(64) NOT NULL,
                amount DECIMAL(20, 8) NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                status VARCHAR(20) NOT NULL,
                tx_hash VARCHAR(64),
                block_height INTEGER,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create balances table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decoin_balances (
                address VARCHAR(64) PRIMARY KEY,
                balance DECIMAL(20, 8) NOT NULL DEFAULT 0,
                pending DECIMAL(20, 8) NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transfers_from
            ON decoin_transfers(from_address, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transfers_to
            ON decoin_transfers(to_address, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_transfers_status
            ON decoin_transfers(status)
        """)

        self.postgres_conn.commit()
        cursor.close()

    async def create_address(self, user_id: str) -> str:
        """Generate a new DeCoin address for a user"""
        # Create deterministic address from user_id
        seed = f"{user_id}:{uuid.uuid4()}:{self.address_counter}"
        self.address_counter += 1

        # Generate address hash
        address_hash = hashlib.sha256(seed.encode()).hexdigest()

        # Format as DeCoin address (DEC + 20 chars)
        address = f"{self.address_prefix}{address_hash[:20].upper()}"

        # Initialize balance
        await self.set_balance(address, Decimal('0'))

        return address

    async def transfer(self,
                       from_address: str,
                       to_address: str,
                       amount: Decimal,
                       metadata: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        Execute instant internal transfer
        Returns: (success, transfer_id or error_message)
        """
        start_time = time.perf_counter()

        # Generate transfer ID
        transfer_id = str(uuid.uuid4())

        # Validate amount
        if amount <= 0:
            return False, "Invalid amount"

        # Get locks for both addresses (prevent double-spending)
        from_lock = self.balance_locks[from_address]
        to_lock = self.balance_locks[to_address]

        # Acquire locks in consistent order to prevent deadlock
        locks = sorted([(from_address, from_lock), (to_address, to_lock)])

        try:
            for _, lock in locks:
                lock.acquire()

            # Check balance
            from_balance = await self.get_balance(from_address)
            if from_balance < amount:
                return False, "Insufficient balance"

            # Update balances atomically
            new_from_balance = from_balance - amount
            to_balance = await self.get_balance(to_address)
            new_to_balance = to_balance + amount

            # Update Redis cache
            await self.set_balance(from_address, new_from_balance)
            await self.set_balance(to_address, new_to_balance)

            # Create transfer record
            transfer = InternalTransfer(
                id=transfer_id,
                from_address=from_address,
                to_address=to_address,
                amount=amount,
                timestamp=time.time(),
                status=TransferStatus.COMPLETED,
                metadata=metadata or {}
            )

            # Add to completed queue
            self.completed_transfers.append(transfer)

            # Update statistics
            self.total_transfers += 1
            self.total_volume += amount

            # Record transfer time
            transfer_time = time.perf_counter() - start_time
            self.transfer_times.append(transfer_time)

            # Log to database (async)
            if self.postgres_conn:
                asyncio.create_task(self._log_transfer_to_db(transfer))

            return True, transfer_id

        finally:
            # Release locks
            for _, lock in locks:
                lock.release()

    async def get_balance(self, address: str) -> Decimal:
        """Get balance from cache with fallback to database"""
        # Try Redis first
        if self.redis_client:
            balance_str = self.redis_client.get(f"balance:{address}")
            if balance_str:
                return Decimal(str(balance_str))

        # Fallback to memory cache
        if address in self.balance_cache:
            return self.balance_cache[address]

        # Fallback to database
        if self.postgres_conn:
            cursor = self.postgres_conn.cursor()
            cursor.execute(
                "SELECT balance FROM decoin_balances WHERE address = %s",
                (address,)
            )
            result = cursor.fetchone()
            cursor.close()

            if result:
                balance = Decimal(str(result[0]))
                # Update caches
                await self.set_balance(address, balance)
                return balance

        # Default to zero
        return Decimal('0')

    async def set_balance(self, address: str, balance: Decimal):
        """Update balance in all caches"""
        # Update Redis if available
        if self.redis_client:
            self.redis_client.set(f"balance:{address}", str(balance), ex=3600)  # 1 hour TTL

        # Update memory cache
        self.balance_cache[address] = balance

        # Update database (async)
        if self.postgres_conn:
            asyncio.create_task(self._update_balance_db(address, balance))

    async def _log_transfer_to_db(self, transfer: InternalTransfer):
        """Log transfer to PostgreSQL"""
        if not self.postgres_conn:
            return

        try:
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                INSERT INTO decoin_transfers
                (id, from_address, to_address, amount, timestamp, status, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                transfer.id,
                transfer.from_address,
                transfer.to_address,
                str(transfer.amount),
                transfer.timestamp,
                transfer.status.value,
                json.dumps(transfer.metadata)
            ))
            self.postgres_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Error logging transfer to database: {e}")

    async def _update_balance_db(self, address: str, balance: Decimal):
        """Update balance in PostgreSQL"""
        if not self.postgres_conn:
            return

        try:
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                INSERT INTO decoin_balances (address, balance, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (address)
                DO UPDATE SET balance = %s, updated_at = CURRENT_TIMESTAMP
            """, (address, str(balance), str(balance)))
            self.postgres_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Error updating balance in database: {e}")

    def _start_background_tasks(self):
        """Start background processing threads"""
        # Blockchain anchoring thread
        anchor_thread = threading.Thread(target=self._anchor_worker, daemon=True)
        anchor_thread.start()

        # Statistics reporting thread
        stats_thread = threading.Thread(target=self._stats_worker, daemon=True)
        stats_thread.start()

    def _anchor_worker(self):
        """Periodically anchor internal state to blockchain"""
        while True:
            time.sleep(60)  # Check every minute

            if time.time() - self.last_anchor_time >= self.anchor_interval:
                self._create_anchor_checkpoint()
                self.last_anchor_time = time.time()

    def _create_anchor_checkpoint(self):
        """Create blockchain checkpoint of current state"""
        try:
            # Calculate merkle root of all balances
            balances = []
            for address, balance in self.balance_cache.items():
                balances.append(f"{address}:{balance}")

            # Sort for consistency
            balances.sort()

            # Calculate merkle root
            merkle_root = self._calculate_merkle_root(balances)

            # Create anchor transaction (would be sent to DeCoin blockchain)
            anchor_tx = {
                'type': 'anchor',
                'merkle_root': merkle_root,
                'timestamp': time.time(),
                'total_transfers': self.total_transfers,
                'total_volume': str(self.total_volume)
            }

            print(f"Created anchor checkpoint: {merkle_root[:16]}...")

            # In production, this would submit to DeCoin blockchain
            # For now, just log it
            self.anchor_queue.append(anchor_tx)

        except Exception as e:
            print(f"Error creating anchor checkpoint: {e}")

    def _calculate_merkle_root(self, items: List[str]) -> str:
        """Calculate merkle root of items"""
        if not items:
            return hashlib.sha256(b'').hexdigest()

        hashes = [hashlib.sha256(item.encode()).hexdigest() for item in items]

        while len(hashes) > 1:
            if len(hashes) % 2 != 0:
                hashes.append(hashes[-1])

            new_hashes = []
            for i in range(0, len(hashes), 2):
                combined = hashes[i] + hashes[i + 1]
                new_hash = hashlib.sha256(combined.encode()).hexdigest()
                new_hashes.append(new_hash)
            hashes = new_hashes

        return hashes[0]

    def _stats_worker(self):
        """Report statistics periodically"""
        while True:
            time.sleep(30)  # Report every 30 seconds

            if self.transfer_times:
                avg_time = sum(self.transfer_times) / len(self.transfer_times)
                print(f"DeCoin Ledger Stats: {self.total_transfers} transfers, "
                      f"Volume: {self.total_volume:.2f} DEC, "
                      f"Avg time: {avg_time*1000:.2f}ms")

    def get_stats(self) -> Dict[str, Any]:
        """Get current ledger statistics"""
        avg_time = 0
        if self.transfer_times:
            avg_time = sum(self.transfer_times) / len(self.transfer_times)

        return {
            'total_transfers': self.total_transfers,
            'total_volume': float(self.total_volume),
            'average_transfer_time_ms': avg_time * 1000,
            'cached_addresses': len(self.balance_cache),
            'pending_transfers': len(self.pending_transfers),
            'completed_transfers': len(self.completed_transfers),
            'last_anchor_time': self.last_anchor_time
        }

    async def mint(self, address: str, amount: Decimal) -> bool:
        """Mint new DeCoin (admin function)"""
        current_balance = await self.get_balance(address)
        new_balance = current_balance + amount
        await self.set_balance(address, new_balance)

        # Log minting event
        transfer = InternalTransfer(
            id=str(uuid.uuid4()),
            from_address="MINT",
            to_address=address,
            amount=amount,
            timestamp=time.time(),
            status=TransferStatus.COMPLETED,
            metadata={'type': 'mint'}
        )

        self.completed_transfers.append(transfer)

        if self.postgres_conn:
            await self._log_transfer_to_db(transfer)

        return True

    async def burn(self, address: str, amount: Decimal) -> Tuple[bool, str]:
        """Burn DeCoin (remove from circulation)"""
        current_balance = await self.get_balance(address)

        if current_balance < amount:
            return False, "Insufficient balance"

        new_balance = current_balance - amount
        await self.set_balance(address, new_balance)

        # Log burning event
        transfer = InternalTransfer(
            id=str(uuid.uuid4()),
            from_address=address,
            to_address="BURN",
            amount=amount,
            timestamp=time.time(),
            status=TransferStatus.COMPLETED,
            metadata={'type': 'burn'}
        )

        self.completed_transfers.append(transfer)

        if self.postgres_conn:
            await self._log_transfer_to_db(transfer)

        return True, transfer.id


# Integration with exchange settlement
class ExchangeSettlementBridge:
    """Bridge between exchange trading and DeCoin ledger"""

    def __init__(self, ledger: DeCoinLedger):
        self.ledger = ledger
        self.user_addresses: Dict[str, str] = {}  # user_id -> DEC address

    async def get_user_address(self, user_id: str) -> str:
        """Get or create DeCoin address for user"""
        if user_id not in self.user_addresses:
            address = await self.ledger.create_address(user_id)
            self.user_addresses[user_id] = address
        return self.user_addresses[user_id]

    async def settle_trade(self,
                          buyer_id: str,
                          seller_id: str,
                          amount: Decimal) -> Tuple[bool, str]:
        """Settle a DEC trade instantly"""
        buyer_address = await self.get_user_address(buyer_id)
        seller_address = await self.get_user_address(seller_id)

        # Execute instant transfer
        success, result = await self.ledger.transfer(
            from_address=seller_address,
            to_address=buyer_address,
            amount=amount,
            metadata={
                'type': 'trade_settlement',
                'buyer_id': buyer_id,
                'seller_id': seller_id
            }
        )

        return success, result

    async def deposit(self, user_id: str, amount: Decimal) -> bool:
        """Process DEC deposit for user"""
        address = await self.get_user_address(user_id)
        return await self.ledger.mint(address, amount)

    async def withdraw(self, user_id: str, amount: Decimal,
                       external_address: str) -> Tuple[bool, str]:
        """Process DEC withdrawal to external address"""
        user_address = await self.get_user_address(user_id)

        # First, burn from internal ledger
        success, result = await self.ledger.burn(user_address, amount)

        if success:
            # In production, this would trigger blockchain transaction
            # For now, just log it
            print(f"Withdrawal queued: {amount} DEC to {external_address}")

        return success, result


# Example usage and testing
async def test_ledger():
    """Test the DeCoin ledger system"""
    print("Testing DeCoin Ledger System...")
    print("-" * 50)

    # Initialize ledger (without PostgreSQL for testing)
    ledger = DeCoinLedger()

    # Create settlement bridge
    bridge = ExchangeSettlementBridge(ledger)

    # Create test users
    alice_addr = await bridge.get_user_address("alice")
    bob_addr = await bridge.get_user_address("bob")

    print(f"Alice address: {alice_addr}")
    print(f"Bob address: {bob_addr}")

    # Deposit funds
    await bridge.deposit("alice", Decimal('1000'))
    await bridge.deposit("bob", Decimal('500'))

    print(f"\nInitial balances:")
    print(f"Alice: {await ledger.get_balance(alice_addr)} DEC")
    print(f"Bob: {await ledger.get_balance(bob_addr)} DEC")

    # Execute trades
    print("\nExecuting trades...")

    # Benchmark transfer speed
    start = time.perf_counter()
    num_transfers = 1000

    for i in range(num_transfers):
        # Alternate between Alice->Bob and Bob->Alice
        if i % 2 == 0:
            await bridge.settle_trade("bob", "alice", Decimal('1'))
        else:
            await bridge.settle_trade("alice", "bob", Decimal('1'))

    elapsed = time.perf_counter() - start

    print(f"\nCompleted {num_transfers} transfers in {elapsed:.3f} seconds")
    print(f"Average time per transfer: {(elapsed/num_transfers)*1000:.2f}ms")
    print(f"Throughput: {num_transfers/elapsed:.0f} transfers/second")

    # Final balances
    print(f"\nFinal balances:")
    print(f"Alice: {await ledger.get_balance(alice_addr)} DEC")
    print(f"Bob: {await ledger.get_balance(bob_addr)} DEC")

    # Get statistics
    stats = ledger.get_stats()
    print(f"\nLedger Statistics:")
    print(f"  Total transfers: {stats['total_transfers']}")
    print(f"  Total volume: {stats['total_volume']:.2f} DEC")
    print(f"  Average transfer time: {stats['average_transfer_time_ms']:.2f}ms")


if __name__ == "__main__":
    asyncio.run(test_ledger())