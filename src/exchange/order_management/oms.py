"""
Order Management System (OMS) for real exchange.
Handles order lifecycle, validation, and routing.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid
from datetime import datetime
import asyncio
import logging

from ..matching_engine.engine import Order, OrderType, OrderStatus, TimeInForce, MatchingEngine


logger = logging.getLogger(__name__)


class OrderValidationError(Exception):
    """Order validation failed."""
    pass


class OrderRouter:
    """Routes orders to appropriate matching engines."""

    def __init__(self):
        self.engines: Dict[str, MatchingEngine] = {}
        self.symbol_routing: Dict[str, str] = {}  # symbol -> engine_id

    def register_engine(self, engine_id: str, engine: MatchingEngine, symbols: List[str]):
        """Register matching engine for symbols."""
        self.engines[engine_id] = engine
        for symbol in symbols:
            self.symbol_routing[symbol] = engine_id
            engine.add_symbol(symbol)

    def route_order(self, order: Order) -> Optional[str]:
        """Route order to appropriate engine."""
        if order.symbol not in self.symbol_routing:
            return None

        engine_id = self.symbol_routing[order.symbol]
        return engine_id


class OrderValidator:
    """Validates orders before execution."""

    def __init__(self):
        self.symbol_config: Dict[str, Dict] = {}
        self.user_limits: Dict[str, Dict] = {}

    def add_symbol_config(self, symbol: str, config: Dict):
        """Add symbol trading configuration."""
        self.symbol_config[symbol] = config

    def set_user_limits(self, user_id: str, limits: Dict):
        """Set user trading limits."""
        self.user_limits[user_id] = limits

    def validate_order(self, order: Order) -> Tuple[bool, Optional[str]]:
        """Validate order against rules."""
        try:
            # Check symbol exists
            if order.symbol not in self.symbol_config:
                return False, f"Invalid symbol: {order.symbol}"

            config = self.symbol_config[order.symbol]

            # Check quantity limits
            min_qty = config.get('min_quantity', Decimal('0.001'))
            max_qty = config.get('max_quantity', Decimal('1000000'))

            if order.quantity < min_qty:
                return False, f"Quantity below minimum: {min_qty}"

            if order.quantity > max_qty:
                return False, f"Quantity above maximum: {max_qty}"

            # Check price limits for limit orders
            if order.order_type == OrderType.LIMIT and order.price:
                min_price = config.get('min_price', Decimal('0.00001'))
                max_price = config.get('max_price', Decimal('1000000'))

                if order.price < min_price:
                    return False, f"Price below minimum: {min_price}"

                if order.price > max_price:
                    return False, f"Price above maximum: {max_price}"

                # Check tick size
                tick_size = config.get('tick_size', Decimal('0.01'))
                if order.price % tick_size != 0:
                    return False, f"Price not aligned with tick size: {tick_size}"

            # Check user limits
            if order.user_id in self.user_limits:
                limits = self.user_limits[order.user_id]

                # Daily order limit
                daily_limit = limits.get('daily_orders', 1000)
                # This would check against actual daily count from database
                # For now, we'll skip this check

                # Notional limit
                if order.price:
                    notional = order.quantity * order.price
                    max_notional = limits.get('max_notional', Decimal('1000000'))
                    if notional > max_notional:
                        return False, f"Notional value exceeds limit: {max_notional}"

            return True, None

        except Exception as e:
            logger.error(f"Order validation error: {e}")
            return False, str(e)


class OrderManagementSystem:
    """Main OMS coordinating order flow."""

    def __init__(self):
        self.validator = OrderValidator()
        self.router = OrderRouter()
        self.orders: Dict[str, Order] = {}
        self.user_orders: Dict[str, List[str]] = {}  # user_id -> order_ids
        self.order_history: List[Dict] = []

    async def submit_order(self, order_request: Dict) -> Dict:
        """Submit new order."""
        try:
            # Create order object
            order = self._create_order(order_request)

            # Validate order
            is_valid, error_msg = self.validator.validate_order(order)
            if not is_valid:
                return {
                    "success": False,
                    "error": error_msg,
                    "order_id": None
                }

            # Check risk (would integrate with risk management)
            risk_check = await self._check_risk(order)
            if not risk_check["passed"]:
                return {
                    "success": False,
                    "error": risk_check["reason"],
                    "order_id": None
                }

            # Route order to matching engine
            engine_id = self.router.route_order(order)
            if not engine_id:
                return {
                    "success": False,
                    "error": "No matching engine available",
                    "order_id": None
                }

            # Submit to matching engine
            engine = self.router.engines[engine_id]
            success, trades = engine.place_order(order)

            if success:
                # Store order
                self.orders[order.id] = order
                if order.user_id not in self.user_orders:
                    self.user_orders[order.user_id] = []
                self.user_orders[order.user_id].append(order.id)

                # Log to history
                self._log_order_event(order, "submitted")

                # Process trades
                if trades:
                    await self._process_trades(trades)

                return {
                    "success": True,
                    "order_id": order.id,
                    "status": order.status.value,
                    "trades": [self._trade_to_dict(t) for t in trades]
                }
            else:
                return {
                    "success": False,
                    "error": "Order submission failed",
                    "order_id": None
                }

        except Exception as e:
            logger.error(f"Order submission error: {e}")
            return {
                "success": False,
                "error": str(e),
                "order_id": None
            }

    async def cancel_order(self, user_id: str, order_id: str) -> Dict:
        """Cancel an order."""
        try:
            # Check order exists and belongs to user
            if order_id not in self.orders:
                return {
                    "success": False,
                    "error": "Order not found"
                }

            order = self.orders[order_id]

            if order.user_id != user_id:
                return {
                    "success": False,
                    "error": "Unauthorized"
                }

            # Route cancellation to engine
            engine_id = self.router.route_order(order)
            if engine_id:
                engine = self.router.engines[engine_id]
                success = engine.cancel_order(order.symbol, order_id)

                if success:
                    self._log_order_event(order, "cancelled")
                    return {
                        "success": True,
                        "order_id": order_id
                    }

            return {
                "success": False,
                "error": "Cancellation failed"
            }

        except Exception as e:
            logger.error(f"Order cancellation error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def modify_order(self, user_id: str, order_id: str, modifications: Dict) -> Dict:
        """Modify an existing order (cancel/replace)."""
        try:
            # Cancel existing order
            cancel_result = await self.cancel_order(user_id, order_id)
            if not cancel_result["success"]:
                return cancel_result

            # Get original order
            original_order = self.orders[order_id]

            # Create new order with modifications
            new_order_request = {
                "user_id": user_id,
                "symbol": original_order.symbol,
                "side": original_order.side,
                "order_type": original_order.order_type.value,
                "quantity": modifications.get("quantity", original_order.quantity),
                "price": modifications.get("price", original_order.price),
                "time_in_force": original_order.time_in_force.value,
                "client_order_id": modifications.get("client_order_id", original_order.client_order_id)
            }

            # Submit new order
            result = await self.submit_order(new_order_request)

            if result["success"]:
                result["original_order_id"] = order_id

            return result

        except Exception as e:
            logger.error(f"Order modification error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_order_status(self, user_id: str, order_id: str) -> Optional[Dict]:
        """Get order status."""
        if order_id not in self.orders:
            return None

        order = self.orders[order_id]

        if order.user_id != user_id:
            return None

        return self._order_to_dict(order)

    def get_user_orders(self, user_id: str, status: Optional[OrderStatus] = None) -> List[Dict]:
        """Get user's orders."""
        if user_id not in self.user_orders:
            return []

        orders = []
        for order_id in self.user_orders[user_id]:
            order = self.orders[order_id]
            if status is None or order.status == status:
                orders.append(self._order_to_dict(order))

        return orders

    def _create_order(self, request: Dict) -> Order:
        """Create order from request."""
        return Order(
            id=str(uuid.uuid4()),
            user_id=request["user_id"],
            symbol=request["symbol"],
            side=request["side"],
            order_type=OrderType(request["order_type"]),
            price=Decimal(str(request.get("price", 0))) if request.get("price") else None,
            quantity=Decimal(str(request["quantity"])),
            time_in_force=TimeInForce(request.get("time_in_force", "GTC")),
            stop_price=Decimal(str(request.get("stop_price", 0))) if request.get("stop_price") else None,
            client_order_id=request.get("client_order_id"),
            post_only=request.get("post_only", False),
            reduce_only=request.get("reduce_only", False)
        )

    async def _check_risk(self, order: Order) -> Dict:
        """Check risk for order."""
        # This would integrate with risk management system
        # For now, always pass
        return {"passed": True}

    async def _process_trades(self, trades: List):
        """Process executed trades."""
        # This would:
        # 1. Update positions
        # 2. Calculate fees
        # 3. Trigger settlement
        # 4. Send notifications
        pass

    def _log_order_event(self, order: Order, event: str):
        """Log order event to history."""
        self.order_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "order_id": order.id,
            "user_id": order.user_id,
            "event": event,
            "order": self._order_to_dict(order)
        })

    def _order_to_dict(self, order: Order) -> Dict:
        """Convert order to dictionary."""
        return {
            "id": order.id,
            "user_id": order.user_id,
            "symbol": order.symbol,
            "side": order.side,
            "order_type": order.order_type.value,
            "price": str(order.price) if order.price else None,
            "quantity": str(order.quantity),
            "filled_quantity": str(order.filled_quantity),
            "remaining_quantity": str(order.remaining_quantity),
            "status": order.status.value,
            "time_in_force": order.time_in_force.value,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat()
        }

    def _trade_to_dict(self, trade) -> Dict:
        """Convert trade to dictionary."""
        return {
            "id": trade.id,
            "symbol": trade.symbol,
            "price": str(trade.price),
            "quantity": str(trade.quantity),
            "buyer_order_id": trade.buyer_order_id,
            "seller_order_id": trade.seller_order_id,
            "timestamp": trade.timestamp.isoformat()
        }