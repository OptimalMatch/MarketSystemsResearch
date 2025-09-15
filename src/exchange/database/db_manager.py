"""
Database Manager for Exchange
Handles all PostgreSQL operations for orders, trades, and balances
"""

import os
import asyncpg
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages all database operations for the exchange"""

    def __init__(self, pool: Optional[asyncpg.Pool] = None):
        self.pool = pool
        self.connected = False

    async def connect(self):
        """Create database connection pool"""
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(
                    host=os.getenv("POSTGRES_HOST", "postgres"),
                    port=int(os.getenv("POSTGRES_PORT", 5432)),
                    database=os.getenv("POSTGRES_DB", "exchange_db"),
                    user=os.getenv("POSTGRES_USER", "exchange_user"),
                    password=os.getenv("POSTGRES_PASSWORD", "exchange_pass"),
                    min_size=10,
                    max_size=30,
                    command_timeout=60
                )
                self.connected = True
                logger.info("Database connection pool created")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise

    async def disconnect(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            self.connected = False
            logger.info("Database connection pool closed")

    # ==================== User Management ====================

    async def get_user_by_api_key(self, api_key: str) -> Optional[Dict]:
        """Get user by API key"""
        query = """
            SELECT id, username, email, api_secret_hash, decoin_address,
                   kyc_status, is_active, daily_volume_limit
            FROM exchange.users
            WHERE api_key = $1 AND is_active = true
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, api_key)
            if row:
                return dict(row)
        return None

    async def create_user(self, username: str, email: str,
                          api_key: str, api_secret_hash: str,
                          decoin_address: Optional[str] = None) -> UUID:
        """Create new user account"""
        query = """
            INSERT INTO exchange.users
            (username, email, api_key, api_secret_hash, decoin_address)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval(
                query, username, email, api_key, api_secret_hash, decoin_address
            )
            logger.info(f"Created user {username} with ID {user_id}")
            return user_id

    # ==================== Order Management ====================

    async def insert_order(self, order_data: Dict) -> str:
        """Insert new order into database"""
        order_id = f"ORD_{uuid4().hex[:16]}"

        query = """
            INSERT INTO exchange.orders
            (order_id, user_id, symbol, side, order_type, status,
             quantity, price, stop_price, time_in_force)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            db_id = await conn.fetchval(
                query,
                order_id,
                UUID(order_data.get("user_id")) if order_data.get("user_id") else None,
                order_data["symbol"],
                order_data["side"],
                order_data.get("order_type", "limit"),
                "new",
                Decimal(str(order_data["quantity"])),
                Decimal(str(order_data["price"])) if order_data.get("price") else None,
                Decimal(str(order_data["stop_price"])) if order_data.get("stop_price") else None,
                order_data.get("time_in_force", "GTC")
            )

            logger.info(f"Inserted order {order_id} with DB ID {db_id}")
            return order_id

    async def update_order_status(self, order_id: str, status: str,
                                  filled_quantity: Optional[Decimal] = None,
                                  average_price: Optional[Decimal] = None):
        """Update order status and fill information"""
        query = """
            UPDATE exchange.orders
            SET status = $2,
                filled_quantity = COALESCE($3, filled_quantity),
                average_price = COALESCE($4, average_price),
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, order_id, status, filled_quantity, average_price)
            logger.debug(f"Updated order {order_id} status to {status}")

    async def get_order(self, order_id: str) -> Optional[Dict]:
        """Get order by ID"""
        query = """
            SELECT * FROM exchange.orders
            WHERE order_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, order_id)
            if row:
                return dict(row)
        return None

    async def get_user_orders(self, user_id: str,
                              status: Optional[str] = None,
                              symbol: Optional[str] = None,
                              limit: int = 100) -> List[Dict]:
        """Get orders for a user"""
        query = """
            SELECT * FROM exchange.orders
            WHERE user_id = $1
        """
        params = [UUID(user_id)]

        if status:
            query += f" AND status = ${len(params) + 1}"
            params.append(status)

        if symbol:
            query += f" AND symbol = ${len(params) + 1}"
            params.append(symbol)

        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_active_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all active orders"""
        query = """
            SELECT * FROM exchange.orders
            WHERE status IN ('new', 'partially_filled')
        """
        params = []

        if symbol:
            query += " AND symbol = $1"
            params.append(symbol)

        query += " ORDER BY created_at DESC"

        async with self.pool.acquire() as conn:
            if params:
                rows = await conn.fetch(query, *params)
            else:
                rows = await conn.fetch(query)
            return [dict(row) for row in rows]

    # ==================== Trade Management ====================

    async def insert_trade(self, trade_data: Dict) -> str:
        """Insert executed trade into database"""
        trade_id = f"TRD_{uuid4().hex[:16]}"

        query = """
            INSERT INTO exchange.trades
            (trade_id, symbol, buyer_order_id, seller_order_id,
             buyer_user_id, seller_user_id, price, quantity,
             maker_side, taker_fee, maker_fee)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            db_id = await conn.fetchval(
                query,
                trade_id,
                trade_data["symbol"],
                trade_data.get("buyer_order_id"),
                trade_data.get("seller_order_id"),
                UUID(trade_data.get("buyer_user_id")) if trade_data.get("buyer_user_id") else None,
                UUID(trade_data.get("seller_user_id")) if trade_data.get("seller_user_id") else None,
                Decimal(str(trade_data["price"])),
                Decimal(str(trade_data["quantity"])),
                trade_data.get("maker_side", "buy"),
                Decimal(str(trade_data.get("taker_fee", 0))),
                Decimal(str(trade_data.get("maker_fee", 0)))
            )

            logger.info(f"Inserted trade {trade_id} with DB ID {db_id}")
            return trade_id

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """Get recent trades for a symbol"""
        query = """
            SELECT trade_id, price, quantity, maker_side, created_at
            FROM exchange.trades
            WHERE symbol = $1
            ORDER BY created_at DESC
            LIMIT $2
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, limit)
            return [dict(row) for row in rows]

    async def get_user_trades(self, user_id: str,
                              symbol: Optional[str] = None,
                              limit: int = 100) -> List[Dict]:
        """Get trades for a user"""
        query = """
            SELECT * FROM exchange.trades
            WHERE buyer_user_id = $1 OR seller_user_id = $1
        """
        params = [UUID(user_id)]

        if symbol:
            query += f" AND symbol = ${len(params) + 1}"
            params.append(symbol)

        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    # ==================== Balance Management ====================

    async def get_user_balance(self, user_id: str, currency: str) -> Dict:
        """Get user balance for a specific currency"""
        query = """
            SELECT available, locked, total
            FROM exchange.balances
            WHERE user_id = $1 AND currency = $2
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, UUID(user_id), currency)
            if row:
                return dict(row)

            # Create zero balance if not exists
            await self.create_balance(user_id, currency)
            return {"available": Decimal(0), "locked": Decimal(0), "total": Decimal(0)}

    async def get_all_user_balances(self, user_id: str) -> List[Dict]:
        """Get all balances for a user"""
        query = """
            SELECT currency, available, locked, total
            FROM exchange.balances
            WHERE user_id = $1
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, UUID(user_id))
            return [dict(row) for row in rows]

    async def create_balance(self, user_id: str, currency: str,
                           available: Decimal = Decimal(0),
                           locked: Decimal = Decimal(0)) -> bool:
        """Create or update user balance"""
        query = """
            INSERT INTO exchange.balances (user_id, currency, available, locked)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, currency)
            DO UPDATE SET
                available = $3,
                locked = $4,
                updated_at = CURRENT_TIMESTAMP
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, UUID(user_id), currency, available, locked)
            logger.info(f"Created/updated balance for user {user_id}, currency {currency}")
            return True

    async def update_balance(self, user_id: str, currency: str,
                            available_delta: Decimal = Decimal(0),
                            locked_delta: Decimal = Decimal(0)) -> bool:
        """Update user balance with deltas"""
        query = """
            UPDATE exchange.balances
            SET available = available + $3,
                locked = locked + $4,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = $1 AND currency = $2
            RETURNING available, locked
        """

        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                query, UUID(user_id), currency, available_delta, locked_delta
            )

            if result:
                if result['available'] < 0 or result['locked'] < 0:
                    # Rollback if balance would go negative
                    await conn.execute(
                        """
                        UPDATE exchange.balances
                        SET available = available - $3,
                            locked = locked - $4
                        WHERE user_id = $1 AND currency = $2
                        """,
                        UUID(user_id), currency, available_delta, locked_delta
                    )
                    return False
                return True
            return False

    async def lock_balance_for_order(self, user_id: str, currency: str,
                                    amount: Decimal) -> bool:
        """Lock balance for an order (move from available to locked)"""
        return await self.update_balance(
            user_id, currency,
            available_delta=-amount,
            locked_delta=amount
        )

    async def unlock_balance(self, user_id: str, currency: str,
                           amount: Decimal) -> bool:
        """Unlock balance (move from locked to available)"""
        return await self.update_balance(
            user_id, currency,
            available_delta=amount,
            locked_delta=-amount
        )

    async def execute_trade_settlement(self, trade_data: Dict) -> bool:
        """Execute balance updates for a trade"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Update buyer balance (receive base currency)
                buyer_id = trade_data.get("buyer_user_id")
                seller_id = trade_data.get("seller_user_id")

                if not buyer_id or not seller_id:
                    return False

                base_currency, quote_currency = trade_data["symbol"].split("/")
                quantity = Decimal(str(trade_data["quantity"]))
                price = Decimal(str(trade_data["price"]))
                total = quantity * price

                # Buyer receives base currency
                await self.update_balance(buyer_id, base_currency, available_delta=quantity)

                # Seller receives quote currency
                await self.update_balance(seller_id, quote_currency, available_delta=total)

                # Unlock any remaining locked balances
                # This would need order information to be precise

                logger.info(f"Settled trade: {quantity} {base_currency} for {total} {quote_currency}")
                return True

    # ==================== Market Data ====================

    async def get_24h_stats(self, symbol: str) -> Dict:
        """Get 24-hour statistics for a symbol"""
        query = """
            SELECT
                COUNT(*) as trade_count,
                SUM(quantity) as volume,
                MAX(price) as high,
                MIN(price) as low,
                AVG(price) as avg_price
            FROM exchange.trades
            WHERE symbol = $1
            AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, symbol)
            if row:
                return dict(row)
            return {
                "trade_count": 0,
                "volume": Decimal(0),
                "high": Decimal(0),
                "low": Decimal(0),
                "avg_price": Decimal(0)
            }

    async def save_candle(self, symbol: str, interval: str, candle_data: Dict):
        """Save OHLCV candle data"""
        query = """
            INSERT INTO exchange.candles
            (symbol, interval, open_time, close_time,
             open, high, low, close, volume, trades_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (symbol, interval, open_time)
            DO UPDATE SET
                high = GREATEST(candles.high, $6),
                low = LEAST(candles.low, $7),
                close = $8,
                volume = candles.volume + $9,
                trades_count = candles.trades_count + $10
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                symbol,
                interval,
                candle_data["open_time"],
                candle_data["close_time"],
                Decimal(str(candle_data["open"])),
                Decimal(str(candle_data["high"])),
                Decimal(str(candle_data["low"])),
                Decimal(str(candle_data["close"])),
                Decimal(str(candle_data["volume"])),
                candle_data.get("trades_count", 0)
            )

    # ==================== Audit & Logging ====================

    async def log_audit_event(self, user_id: Optional[str], action: str,
                             resource_type: Optional[str] = None,
                             resource_id: Optional[str] = None,
                             metadata: Optional[Dict] = None,
                             ip_address: Optional[str] = None):
        """Log an audit event"""
        query = """
            INSERT INTO exchange.audit_log
            (user_id, action, resource_type, resource_id, metadata, ip_address)
            VALUES ($1, $2, $3, $4, $5, $6)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                UUID(user_id) if user_id else None,
                action,
                resource_type,
                resource_id,
                json.dumps(metadata) if metadata else None,
                ip_address
            )


# Singleton instance
_db_manager: Optional[DatabaseManager] = None


async def get_db_manager() -> DatabaseManager:
    """Get or create database manager instance"""
    global _db_manager
    if not _db_manager:
        _db_manager = DatabaseManager()
        await _db_manager.connect()
    return _db_manager


async def close_db_manager():
    """Close database manager"""
    global _db_manager
    if _db_manager:
        await _db_manager.disconnect()
        _db_manager = None