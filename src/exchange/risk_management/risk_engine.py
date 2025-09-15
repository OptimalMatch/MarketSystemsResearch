"""
Risk Management Engine for real exchange.
Handles pre-trade checks, position limits, and risk monitoring.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class RiskCheckType(Enum):
    POSITION_LIMIT = "position_limit"
    EXPOSURE_LIMIT = "exposure_limit"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    ORDER_SIZE_LIMIT = "order_size_limit"
    RATE_LIMIT = "rate_limit"
    MARGIN_CHECK = "margin_check"
    CONCENTRATION_LIMIT = "concentration_limit"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class RiskProfile:
    """User risk profile and limits."""
    user_id: str
    tier: str  # 'retail', 'professional', 'institutional'
    max_position_size: Decimal
    max_daily_loss: Decimal
    max_order_size: Decimal
    max_open_orders: int
    max_daily_trades: int
    max_leverage: Decimal
    concentration_limit: Decimal  # Max % of portfolio in single asset
    required_margin: Decimal  # Required margin ratio
    enabled: bool = True
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


@dataclass
class Position:
    """User position in an asset."""
    user_id: str
    symbol: str
    quantity: Decimal
    average_price: Decimal
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    margin_used: Decimal = Decimal('0')
    last_updated: datetime = None

    def __post_init__(self):
        if not self.last_updated:
            self.last_updated = datetime.utcnow()

    @property
    def notional_value(self) -> Decimal:
        return self.quantity * self.average_price


class CircuitBreaker:
    """Circuit breaker for extreme market conditions."""

    def __init__(self):
        self.triggers: Dict[str, List[Dict]] = {}  # symbol -> triggers
        self.active_halts: Dict[str, Dict] = {}  # symbol -> halt info

    def add_trigger(self, symbol: str, threshold_pct: Decimal, duration_seconds: int, trigger_type: str = "price"):
        """Add circuit breaker trigger."""
        if symbol not in self.triggers:
            self.triggers[symbol] = []

        self.triggers[symbol].append({
            "threshold_pct": threshold_pct,
            "duration_seconds": duration_seconds,
            "type": trigger_type
        })

    def check_trigger(self, symbol: str, current_price: Decimal, reference_price: Decimal) -> Optional[Dict]:
        """Check if circuit breaker should trigger."""
        if symbol not in self.triggers:
            return None

        # Check if already halted
        if symbol in self.active_halts:
            halt = self.active_halts[symbol]
            if datetime.utcnow() < halt["end_time"]:
                return halt
            else:
                # Halt expired
                del self.active_halts[symbol]

        # Check for new triggers
        price_change_pct = abs((current_price - reference_price) / reference_price * 100)

        for trigger in self.triggers[symbol]:
            if price_change_pct >= trigger["threshold_pct"]:
                # Trigger circuit breaker
                halt = {
                    "symbol": symbol,
                    "start_time": datetime.utcnow(),
                    "end_time": datetime.utcnow() + timedelta(seconds=trigger["duration_seconds"]),
                    "reason": f"Price moved {price_change_pct:.2f}% (threshold: {trigger['threshold_pct']}%)",
                    "trigger_type": trigger["type"]
                }
                self.active_halts[symbol] = halt
                logger.warning(f"Circuit breaker triggered for {symbol}: {halt['reason']}")
                return halt

        return None

    def is_halted(self, symbol: str) -> bool:
        """Check if symbol is currently halted."""
        if symbol in self.active_halts:
            if datetime.utcnow() < self.active_halts[symbol]["end_time"]:
                return True
            else:
                del self.active_halts[symbol]
        return False


class RiskEngine:
    """Main risk management engine."""

    def __init__(self):
        self.risk_profiles: Dict[str, RiskProfile] = {}
        self.positions: Dict[str, Dict[str, Position]] = {}  # user_id -> symbol -> position
        self.daily_trades: Dict[str, int] = {}  # user_id -> count
        self.daily_losses: Dict[str, Decimal] = {}  # user_id -> loss
        self.order_rate_limiter: Dict[str, List[datetime]] = {}  # user_id -> timestamps
        self.circuit_breaker = CircuitBreaker()
        self.market_prices: Dict[str, Decimal] = {}  # symbol -> price

    def add_risk_profile(self, profile: RiskProfile):
        """Add or update user risk profile."""
        self.risk_profiles[profile.user_id] = profile

    def update_market_price(self, symbol: str, price: Decimal):
        """Update market price for risk calculations."""
        self.market_prices[symbol] = price

    def check_pre_trade_risk(self, order: Dict) -> Tuple[bool, Optional[str]]:
        """Perform pre-trade risk checks."""
        user_id = order["user_id"]
        symbol = order["symbol"]
        side = order["side"]
        quantity = Decimal(str(order["quantity"]))
        price = Decimal(str(order.get("price", 0)))

        # Get user risk profile
        if user_id not in self.risk_profiles:
            return False, "No risk profile found"

        profile = self.risk_profiles[user_id]

        if not profile.enabled:
            return False, "Trading disabled for user"

        # Check circuit breaker
        if self.circuit_breaker.is_halted(symbol):
            return False, f"Trading halted for {symbol}"

        # Check order size limit
        if quantity > profile.max_order_size:
            return False, f"Order size exceeds limit: {profile.max_order_size}"

        # Check position limit
        current_position = self._get_position(user_id, symbol)
        new_position = current_position + (quantity if side == "buy" else -quantity)

        if abs(new_position) > profile.max_position_size:
            return False, f"Position size would exceed limit: {profile.max_position_size}"

        # Check daily trade limit
        if self._get_daily_trade_count(user_id) >= profile.max_daily_trades:
            return False, f"Daily trade limit reached: {profile.max_daily_trades}"

        # Check rate limit (orders per second)
        if not self._check_rate_limit(user_id):
            return False, "Rate limit exceeded"

        # Check daily loss limit
        daily_loss = self.daily_losses.get(user_id, Decimal('0'))
        if daily_loss >= profile.max_daily_loss:
            return False, f"Daily loss limit reached: {profile.max_daily_loss}"

        # Check margin requirements
        if not self._check_margin(user_id, symbol, quantity, price):
            return False, "Insufficient margin"

        # Check concentration limit
        if not self._check_concentration(user_id, symbol, quantity, price):
            return False, f"Concentration limit exceeded: {profile.concentration_limit}%"

        return True, None

    def update_position(self, user_id: str, symbol: str, trade: Dict):
        """Update user position after trade."""
        quantity = Decimal(str(trade["quantity"]))
        price = Decimal(str(trade["price"]))
        is_buy = trade["buyer_user_id"] == user_id

        if user_id not in self.positions:
            self.positions[user_id] = {}

        if symbol not in self.positions[user_id]:
            self.positions[user_id][symbol] = Position(
                user_id=user_id,
                symbol=symbol,
                quantity=Decimal('0'),
                average_price=Decimal('0')
            )

        position = self.positions[user_id][symbol]

        if is_buy:
            # Update average price for buys
            total_cost = position.quantity * position.average_price + quantity * price
            position.quantity += quantity
            if position.quantity != 0:
                position.average_price = total_cost / position.quantity
        else:
            # Calculate realized P&L for sells
            if position.quantity > 0:
                realized_pnl = quantity * (price - position.average_price)
                position.realized_pnl += realized_pnl
                self._update_daily_pnl(user_id, realized_pnl)

            position.quantity -= quantity

        position.last_updated = datetime.utcnow()

        # Update unrealized P&L
        if symbol in self.market_prices:
            market_price = self.market_prices[symbol]
            position.unrealized_pnl = position.quantity * (market_price - position.average_price)

    def get_user_risk_summary(self, user_id: str) -> Dict:
        """Get user's current risk summary."""
        if user_id not in self.risk_profiles:
            return {}

        profile = self.risk_profiles[user_id]
        positions = self.positions.get(user_id, {})

        total_exposure = Decimal('0')
        total_unrealized_pnl = Decimal('0')
        total_realized_pnl = Decimal('0')
        total_margin_used = Decimal('0')

        position_details = []
        for symbol, position in positions.items():
            total_exposure += abs(position.notional_value)
            total_unrealized_pnl += position.unrealized_pnl
            total_realized_pnl += position.realized_pnl
            total_margin_used += position.margin_used

            position_details.append({
                "symbol": symbol,
                "quantity": str(position.quantity),
                "average_price": str(position.average_price),
                "notional_value": str(position.notional_value),
                "unrealized_pnl": str(position.unrealized_pnl),
                "realized_pnl": str(position.realized_pnl)
            })

        return {
            "user_id": user_id,
            "tier": profile.tier,
            "total_exposure": str(total_exposure),
            "total_unrealized_pnl": str(total_unrealized_pnl),
            "total_realized_pnl": str(total_realized_pnl),
            "total_margin_used": str(total_margin_used),
            "daily_trades": self._get_daily_trade_count(user_id),
            "daily_loss": str(self.daily_losses.get(user_id, Decimal('0'))),
            "positions": position_details,
            "limits": {
                "max_position_size": str(profile.max_position_size),
                "max_daily_loss": str(profile.max_daily_loss),
                "max_daily_trades": profile.max_daily_trades,
                "max_leverage": str(profile.max_leverage)
            }
        }

    def _get_position(self, user_id: str, symbol: str) -> Decimal:
        """Get current position quantity."""
        if user_id in self.positions and symbol in self.positions[user_id]:
            return self.positions[user_id][symbol].quantity
        return Decimal('0')

    def _get_daily_trade_count(self, user_id: str) -> int:
        """Get daily trade count for user."""
        return self.daily_trades.get(user_id, 0)

    def _check_rate_limit(self, user_id: str, max_per_second: int = 10) -> bool:
        """Check order rate limit."""
        now = datetime.utcnow()

        if user_id not in self.order_rate_limiter:
            self.order_rate_limiter[user_id] = []

        # Remove old timestamps
        cutoff = now - timedelta(seconds=1)
        self.order_rate_limiter[user_id] = [
            ts for ts in self.order_rate_limiter[user_id] if ts > cutoff
        ]

        # Check limit
        if len(self.order_rate_limiter[user_id]) >= max_per_second:
            return False

        # Add current timestamp
        self.order_rate_limiter[user_id].append(now)
        return True

    def _check_margin(self, user_id: str, symbol: str, quantity: Decimal, price: Decimal) -> bool:
        """Check margin requirements."""
        profile = self.risk_profiles[user_id]
        required_margin = quantity * price / profile.max_leverage

        # Would check actual account balance here
        # For now, assume sufficient margin
        return True

    def _check_concentration(self, user_id: str, symbol: str, quantity: Decimal, price: Decimal) -> bool:
        """Check concentration limits."""
        profile = self.risk_profiles[user_id]
        positions = self.positions.get(user_id, {})

        # Calculate total portfolio value
        total_value = Decimal('0')
        for sym, pos in positions.items():
            if sym in self.market_prices:
                total_value += abs(pos.quantity * self.market_prices[sym])

        # Add new position value
        new_position_value = quantity * price
        total_value += new_position_value

        # Check concentration
        if total_value > 0:
            concentration = new_position_value / total_value * 100
            if concentration > profile.concentration_limit:
                return False

        return True

    def _update_daily_pnl(self, user_id: str, pnl: Decimal):
        """Update daily P&L tracking."""
        if pnl < 0:
            if user_id not in self.daily_losses:
                self.daily_losses[user_id] = Decimal('0')
            self.daily_losses[user_id] += abs(pnl)

    def reset_daily_counters(self):
        """Reset daily counters (call at start of trading day)."""
        self.daily_trades.clear()
        self.daily_losses.clear()
        logger.info("Daily risk counters reset")