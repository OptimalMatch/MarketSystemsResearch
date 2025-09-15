"""
Market Making Algorithms for Automated Liquidity Provision
Implements various market making strategies
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set
from decimal import Decimal
from enum import Enum
from datetime import datetime, timedelta
import asyncio
import logging
import random
import math

logger = logging.getLogger(__name__)


class MarketMakingStrategy(Enum):
    """Available market making strategies"""
    GRID = "grid"
    SPREAD = "spread"
    AVELLANEDA_STOIKOV = "avellaneda_stoikov"
    TWAP = "twap"  # Time-Weighted Average Price
    VWAP = "vwap"  # Volume-Weighted Average Price
    LIQUIDITY_MINING = "liquidity_mining"


@dataclass
class MarketMakerConfig:
    """Configuration for market maker"""
    strategy: MarketMakingStrategy
    symbol: str
    base_currency: str
    quote_currency: str
    inventory_target: Decimal  # Target inventory in base currency
    spread_bps: int  # Spread in basis points (1 bps = 0.01%)
    order_amount: Decimal  # Size of each order
    max_orders_per_side: int = 5
    refresh_interval: int = 10  # Seconds between order refreshes
    max_position: Decimal = Decimal(10000)  # Maximum position size
    min_spread: Decimal = Decimal("0.001")  # Minimum spread
    max_spread: Decimal = Decimal("0.05")  # Maximum spread
    risk_factor: Decimal = Decimal("0.01")  # Risk aversion parameter
    order_lifetime: int = 60  # Order lifetime in seconds
    enable_inventory_risk: bool = True
    enable_price_protection: bool = True


@dataclass
class MarketState:
    """Current market state for decision making"""
    mid_price: Decimal
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    spread: Decimal
    volume_24h: Decimal
    volatility: Decimal
    order_book_imbalance: Decimal  # -1 to 1, negative = more sells
    recent_trades: List[Dict]
    timestamp: datetime


class GridMarketMaker:
    """Grid trading strategy - places orders at regular price intervals"""

    def __init__(self, config: MarketMakerConfig):
        self.config = config
        self.grid_levels: List[Decimal] = []
        self.active_orders: Dict[str, Dict] = {}
        self.filled_orders: List[Dict] = []
        self.current_position: Decimal = Decimal(0)

    def calculate_grid_levels(self, center_price: Decimal, grid_spacing: Decimal,
                            num_levels: int) -> List[Decimal]:
        """Calculate grid price levels around center price"""
        levels = []

        # Create levels above and below center
        for i in range(1, num_levels + 1):
            # Buy levels below center
            buy_level = center_price - (grid_spacing * i)
            levels.append(("buy", buy_level))

            # Sell levels above center
            sell_level = center_price + (grid_spacing * i)
            levels.append(("sell", sell_level))

        return levels

    def generate_orders(self, market_state: MarketState) -> List[Dict]:
        """Generate grid orders based on current market state"""
        orders = []

        # Calculate grid spacing based on volatility
        grid_spacing = market_state.mid_price * self.config.spread_bps / Decimal(10000)

        # Adjust spacing based on volatility
        if market_state.volatility > Decimal("0.02"):  # High volatility
            grid_spacing *= Decimal("1.5")

        # Calculate grid levels
        levels = self.calculate_grid_levels(
            market_state.mid_price,
            grid_spacing,
            self.config.max_orders_per_side
        )

        # Generate orders for each level
        for side, price in levels:
            # Skip if position limit reached
            if self.current_position > self.config.max_position and side == "buy":
                continue
            if self.current_position < -self.config.max_position and side == "sell":
                continue

            order = {
                "symbol": self.config.symbol,
                "side": side,
                "price": price,
                "quantity": self.config.order_amount,
                "order_type": "limit",
                "time_in_force": "GTC",
                "metadata": {
                    "strategy": "grid",
                    "level": price,
                    "created_at": market_state.timestamp
                }
            }
            orders.append(order)

        return orders

    def adjust_for_inventory(self, orders: List[Dict]) -> List[Dict]:
        """Adjust orders based on current inventory"""
        if not self.config.enable_inventory_risk:
            return orders

        inventory_ratio = self.current_position / self.config.inventory_target if self.config.inventory_target > 0 else 0

        adjusted_orders = []
        for order in orders:
            adjusted_order = order.copy()

            if order["side"] == "buy":
                # Reduce buy size if over-inventory
                if inventory_ratio > 1:
                    adjusted_order["quantity"] *= Decimal(2 - min(inventory_ratio, 2))
            else:  # sell
                # Reduce sell size if under-inventory
                if inventory_ratio < 0:
                    adjusted_order["quantity"] *= Decimal(2 + max(inventory_ratio, -2))

            adjusted_orders.append(adjusted_order)

        return adjusted_orders


class SpreadMarketMaker:
    """Simple spread-based market making around mid price"""

    def __init__(self, config: MarketMakerConfig):
        self.config = config
        self.active_orders: Dict[str, Dict] = {}
        self.position: Decimal = Decimal(0)
        self.pnl: Decimal = Decimal(0)

    def calculate_optimal_spread(self, market_state: MarketState) -> Tuple[Decimal, Decimal]:
        """Calculate optimal bid-ask spread based on market conditions"""
        base_spread = self.config.spread_bps / Decimal(10000)

        # Adjust spread based on volatility
        volatility_adjustment = Decimal(1) + (market_state.volatility * Decimal(10))

        # Adjust spread based on inventory
        inventory_ratio = abs(self.position) / self.config.max_position
        inventory_adjustment = Decimal(1) + (inventory_ratio * Decimal(2))

        # Calculate final spread
        spread = base_spread * volatility_adjustment * inventory_adjustment
        spread = max(self.config.min_spread, min(spread, self.config.max_spread))

        # Calculate bid and ask offsets
        half_spread = spread / Decimal(2)

        # Skew based on inventory
        if self.position > 0:  # Long inventory, want to sell more
            bid_offset = half_spread * Decimal("1.2")
            ask_offset = half_spread * Decimal("0.8")
        elif self.position < 0:  # Short inventory, want to buy more
            bid_offset = half_spread * Decimal("0.8")
            ask_offset = half_spread * Decimal("1.2")
        else:
            bid_offset = ask_offset = half_spread

        return bid_offset, ask_offset

    def generate_orders(self, market_state: MarketState) -> List[Dict]:
        """Generate bid and ask orders"""
        orders = []

        # Calculate optimal spreads
        bid_offset, ask_offset = self.calculate_optimal_spread(market_state)

        # Generate bid orders
        bid_price = market_state.mid_price - bid_offset
        ask_price = market_state.mid_price + ask_offset

        # Adjust order sizes based on position
        buy_size = self.config.order_amount
        sell_size = self.config.order_amount

        if self.position > self.config.inventory_target:
            # Over inventory, reduce buys, increase sells
            buy_size *= Decimal("0.5")
            sell_size *= Decimal("1.5")
        elif self.position < -self.config.inventory_target:
            # Under inventory, increase buys, reduce sells
            buy_size *= Decimal("1.5")
            sell_size *= Decimal("0.5")

        # Create multiple orders at different levels
        for i in range(self.config.max_orders_per_side):
            level_adjustment = Decimal(i) * bid_offset * Decimal("0.2")

            # Buy order
            orders.append({
                "symbol": self.config.symbol,
                "side": "buy",
                "price": bid_price - level_adjustment,
                "quantity": buy_size * Decimal(1 - i * 0.1),  # Decrease size at further levels
                "order_type": "limit",
                "time_in_force": "GTC",
                "metadata": {
                    "strategy": "spread",
                    "level": i,
                    "spread": float(bid_offset + ask_offset)
                }
            })

            # Sell order
            orders.append({
                "symbol": self.config.symbol,
                "side": "sell",
                "price": ask_price + level_adjustment,
                "quantity": sell_size * Decimal(1 - i * 0.1),
                "order_type": "limit",
                "time_in_force": "GTC",
                "metadata": {
                    "strategy": "spread",
                    "level": i,
                    "spread": float(bid_offset + ask_offset)
                }
            })

        return orders


class AvellanedaStoikovMaker:
    """Advanced market making using Avellaneda-Stoikov model"""

    def __init__(self, config: MarketMakerConfig):
        self.config = config
        self.position: Decimal = Decimal(0)
        self.cash: Decimal = Decimal(100000)  # Starting cash
        self.trades: List[Dict] = []

    def calculate_reservation_price(self, market_state: MarketState,
                                   time_remaining: float) -> Decimal:
        """Calculate reservation price based on inventory and risk"""
        mid_price = market_state.mid_price

        # Inventory risk adjustment
        gamma = self.config.risk_factor  # Risk aversion parameter
        sigma = market_state.volatility

        # Calculate reservation price
        inventory_adjustment = float(self.position) * float(gamma) * float(sigma) * float(sigma) * time_remaining
        reservation_price = mid_price - Decimal(str(inventory_adjustment))

        return reservation_price

    def calculate_optimal_quotes(self, market_state: MarketState) -> Tuple[Decimal, Decimal]:
        """Calculate optimal bid and ask quotes using A-S model"""
        # Time remaining in trading day (simplified)
        time_remaining = 1.0  # Normalized time

        # Get reservation price
        reservation_price = self.calculate_reservation_price(market_state, time_remaining)

        # Calculate spread based on volatility and order arrival rate
        sigma = market_state.volatility
        gamma = self.config.risk_factor

        # Optimal spread from A-S model (simplified)
        spread_factor = 1 + float(gamma) * float(sigma) * float(sigma) * time_remaining / 2
        optimal_spread = Decimal(2) / gamma * Decimal(str(math.log(max(spread_factor, 1.001))))

        # Ensure spread is within configured bounds
        optimal_spread = max(self.config.min_spread, min(optimal_spread, self.config.max_spread))

        # Calculate bid and ask
        half_spread = optimal_spread / Decimal(2)
        bid_price = reservation_price - half_spread
        ask_price = reservation_price + half_spread

        return bid_price, ask_price

    def generate_orders(self, market_state: MarketState) -> List[Dict]:
        """Generate orders using Avellaneda-Stoikov model"""
        orders = []

        # Calculate optimal quotes
        bid_price, ask_price = self.calculate_optimal_quotes(market_state)

        # Adjust order sizes based on position and risk
        position_ratio = abs(self.position) / self.config.max_position
        size_multiplier = Decimal(1) - position_ratio * Decimal("0.5")

        order_size = self.config.order_amount * size_multiplier

        # Generate orders
        if self.position < self.config.max_position:
            orders.append({
                "symbol": self.config.symbol,
                "side": "buy",
                "price": bid_price,
                "quantity": order_size,
                "order_type": "limit",
                "time_in_force": "GTC",
                "metadata": {
                    "strategy": "avellaneda_stoikov",
                    "reservation_price": float(self.calculate_reservation_price(market_state, 1.0)),
                    "optimal_spread": float(ask_price - bid_price)
                }
            })

        if self.position > -self.config.max_position:
            orders.append({
                "symbol": self.config.symbol,
                "side": "sell",
                "price": ask_price,
                "quantity": order_size,
                "order_type": "limit",
                "time_in_force": "GTC",
                "metadata": {
                    "strategy": "avellaneda_stoikov",
                    "reservation_price": float(self.calculate_reservation_price(market_state, 1.0)),
                    "optimal_spread": float(ask_price - bid_price)
                }
            })

        return orders


class MarketMaker:
    """Main market maker orchestrator"""

    def __init__(self, config: MarketMakerConfig):
        self.config = config
        self.active = False
        self.strategy = self._create_strategy(config)
        self.active_orders: Set[str] = set()
        self.performance_metrics = {
            "total_volume": Decimal(0),
            "total_trades": 0,
            "pnl": Decimal(0),
            "sharpe_ratio": 0.0,
            "win_rate": 0.0
        }

    def _create_strategy(self, config: MarketMakerConfig):
        """Create the appropriate strategy instance"""
        if config.strategy == MarketMakingStrategy.GRID:
            return GridMarketMaker(config)
        elif config.strategy == MarketMakingStrategy.SPREAD:
            return SpreadMarketMaker(config)
        elif config.strategy == MarketMakingStrategy.AVELLANEDA_STOIKOV:
            return AvellanedaStoikovMaker(config)
        else:
            raise ValueError(f"Unknown strategy: {config.strategy}")

    async def start(self):
        """Start market making"""
        self.active = True
        logger.info(f"Starting market maker for {self.config.symbol} using {self.config.strategy.value} strategy")

    async def stop(self):
        """Stop market making and cancel all orders"""
        self.active = False
        logger.info(f"Stopping market maker for {self.config.symbol}")
        # In production, would cancel all active orders here

    async def update_market_state(self, market_data: Dict) -> MarketState:
        """Update market state from market data"""
        # Calculate metrics from market data
        mid_price = Decimal(str(market_data.get("mid_price", 0)))
        best_bid = Decimal(str(market_data.get("best_bid", 0))) if market_data.get("best_bid") else None
        best_ask = Decimal(str(market_data.get("best_ask", 0))) if market_data.get("best_ask") else None

        spread = best_ask - best_bid if best_ask and best_bid else Decimal(0)

        # Calculate volatility (simplified)
        recent_prices = market_data.get("recent_prices", [])
        if len(recent_prices) > 1:
            returns = [(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                      for i in range(1, len(recent_prices))]
            volatility = Decimal(str(math.sqrt(sum(r*r for r in returns) / len(returns)))) if returns else Decimal(0)
        else:
            volatility = Decimal("0.01")  # Default volatility

        # Calculate order book imbalance
        bid_volume = Decimal(str(market_data.get("bid_volume", 0)))
        ask_volume = Decimal(str(market_data.get("ask_volume", 0)))
        total_volume = bid_volume + ask_volume
        imbalance = (bid_volume - ask_volume) / total_volume if total_volume > 0 else Decimal(0)

        return MarketState(
            mid_price=mid_price,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            volume_24h=Decimal(str(market_data.get("volume_24h", 0))),
            volatility=volatility,
            order_book_imbalance=imbalance,
            recent_trades=market_data.get("recent_trades", []),
            timestamp=datetime.utcnow()
        )

    async def generate_orders(self, market_data: Dict) -> List[Dict]:
        """Generate new orders based on market conditions"""
        if not self.active:
            return []

        # Update market state
        market_state = await self.update_market_state(market_data)

        # Generate orders using the selected strategy
        orders = self.strategy.generate_orders(market_state)

        # Apply risk management
        orders = self._apply_risk_management(orders, market_state)

        return orders

    def _apply_risk_management(self, orders: List[Dict], market_state: MarketState) -> List[Dict]:
        """Apply risk management rules to orders"""
        filtered_orders = []

        for order in orders:
            # Check price protection
            if self.config.enable_price_protection:
                if order["side"] == "buy":
                    # Don't buy too far above mid price
                    if order["price"] > market_state.mid_price * Decimal("1.01"):
                        continue
                else:  # sell
                    # Don't sell too far below mid price
                    if order["price"] < market_state.mid_price * Decimal("0.99"):
                        continue

            # Check position limits
            if hasattr(self.strategy, 'position'):
                if abs(self.strategy.position) > self.config.max_position * Decimal("0.9"):
                    # Near position limit, only allow reducing orders
                    if (self.strategy.position > 0 and order["side"] == "buy") or \
                       (self.strategy.position < 0 and order["side"] == "sell"):
                        continue

            filtered_orders.append(order)

        return filtered_orders

    def handle_fill(self, order: Dict, fill_price: Decimal, fill_quantity: Decimal):
        """Handle order fill and update position"""
        # Update strategy position
        if hasattr(self.strategy, 'position'):
            if order["side"] == "buy":
                self.strategy.position += fill_quantity
            else:
                self.strategy.position -= fill_quantity

        # Update metrics
        self.performance_metrics["total_volume"] += fill_quantity * fill_price
        self.performance_metrics["total_trades"] += 1

        logger.info(f"Order filled: {order['side']} {fill_quantity} @ {fill_price}")

    def get_performance_report(self) -> Dict:
        """Get performance metrics"""
        return {
            "strategy": self.config.strategy.value,
            "symbol": self.config.symbol,
            "total_volume": float(self.performance_metrics["total_volume"]),
            "total_trades": self.performance_metrics["total_trades"],
            "current_position": float(getattr(self.strategy, 'position', 0)),
            "pnl": float(self.performance_metrics["pnl"]),
            "active_orders": len(self.active_orders)
        }