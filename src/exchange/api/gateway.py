"""
API Gateway for real exchange.
Provides REST and WebSocket endpoints for trading.
"""

from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime
import asyncio
import json
import logging

from ..matching_engine.engine import OrderType, TimeInForce, OrderStatus
from ..matching_engine.ultra_fast_engine import UltraFastMatchingEngine
from ..order_management.oms import OrderManagementSystem
from ..risk_management.risk_engine import RiskEngine, RiskProfile
from .auth import get_current_user, get_current_user_full, check_rate_limit, init_db_pool

logger = logging.getLogger(__name__)

app = FastAPI(title="Exchange API", version="1.0.0")
security = HTTPBearer()

# Initialize systems (would be dependency injected in production)
oms = OrderManagementSystem()
risk_engine = RiskEngine()

# Initialize matching engines for market data
engines = {
    "DEC/USD": UltraFastMatchingEngine("DEC/USD"),
    "BTC/USD": UltraFastMatchingEngine("BTC/USD"),
    "ETH/USD": UltraFastMatchingEngine("ETH/USD"),
    "DEC/BTC": UltraFastMatchingEngine("DEC/BTC")
}


# Pydantic models for API
class OrderRequest(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field(..., pattern="^(market|limit|stop|stop_limit)$")
    quantity: str
    price: Optional[str] = None
    time_in_force: str = Field(default="GTC", pattern="^(GTC|IOC|FOK|DAY)$")
    stop_price: Optional[str] = None
    client_order_id: Optional[str] = None
    post_only: bool = False
    reduce_only: bool = False


class CancelOrderRequest(BaseModel):
    order_id: str


class ModifyOrderRequest(BaseModel):
    order_id: str
    quantity: Optional[str] = None
    price: Optional[str] = None


# Authentication mock (replace with real auth)
# Authentication is now handled by auth.py module


# REST API Endpoints
@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "Exchange API",
        "version": "1.0.0",
        "endpoints": {
            "trading": "/api/v1/orders",
            "market_data": "/api/v1/market",
            "account": "/api/v1/account",
            "websocket": "/ws"
        }
    }


@app.post("/api/v1/orders")
async def place_order(
    request: OrderRequest,
    user_id: str = Depends(get_current_user)
):
    """Place a new order."""
    try:
        order_dict = {
            "user_id": user_id,
            "symbol": request.symbol,
            "side": request.side,
            "order_type": request.order_type,
            "quantity": request.quantity,
            "price": request.price,
            "time_in_force": request.time_in_force,
            "stop_price": request.stop_price,
            "client_order_id": request.client_order_id,
            "post_only": request.post_only,
            "reduce_only": request.reduce_only
        }

        # Check risk
        risk_check = risk_engine.check_pre_trade_risk(order_dict)
        if not risk_check[0]:
            raise HTTPException(status_code=400, detail=risk_check[1])

        # Submit order
        result = await oms.submit_order(order_dict)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except Exception as e:
        logger.error(f"Order placement error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/orders/{order_id}")
async def cancel_order(
    order_id: str,
    user_id: str = Depends(get_current_user)
):
    """Cancel an order."""
    try:
        result = await oms.cancel_order(user_id, order_id)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except Exception as e:
        logger.error(f"Order cancellation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/orders/{order_id}")
async def modify_order(
    order_id: str,
    request: ModifyOrderRequest,
    user_id: str = Depends(get_current_user)
):
    """Modify an existing order."""
    try:
        modifications = {}
        if request.quantity:
            modifications["quantity"] = request.quantity
        if request.price:
            modifications["price"] = request.price

        result = await oms.modify_order(user_id, order_id, modifications)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except Exception as e:
        logger.error(f"Order modification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/orders")
async def get_orders(
    status: Optional[str] = None,
    user_id: str = Depends(get_current_user)
):
    """Get user's orders."""
    try:
        order_status = OrderStatus(status) if status else None
        orders = oms.get_user_orders(user_id, order_status)
        return {"orders": orders}

    except Exception as e:
        logger.error(f"Get orders error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/orders/{order_id}")
async def get_order(
    order_id: str,
    user_id: str = Depends(get_current_user)
):
    """Get specific order details."""
    try:
        order = oms.get_order_status(user_id, order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        return order

    except Exception as e:
        logger.error(f"Get order error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/market/{symbol}/orderbook")
async def get_orderbook(symbol: str, depth: int = 20):
    """Get order book for symbol."""
    try:
        # Get from matching engine
        for engine in oms.router.engines.values():
            orderbook = engine.get_order_book(symbol, depth)
            if orderbook:
                return orderbook

        raise HTTPException(status_code=404, detail="Symbol not found")

    except Exception as e:
        logger.error(f"Get orderbook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/account/balance")
async def get_balance(user_id: str = Depends(get_current_user)):
    """Get account balance."""
    try:
        # This would connect to custody/settlement system
        return {
            "user_id": user_id,
            "balances": {
                "USD": "10000.00",
                "BTC": "0.5",
                "ETH": "10.0"
            }
        }

    except Exception as e:
        logger.error(f"Get balance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/account/positions")
async def get_positions(user_id: str = Depends(get_current_user)):
    """Get account positions."""
    try:
        risk_summary = risk_engine.get_user_risk_summary(user_id)
        return {
            "user_id": user_id,
            "positions": risk_summary.get("positions", [])
        }

    except Exception as e:
        logger.error(f"Get positions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/account/risk")
async def get_risk_summary(user_id: str = Depends(get_current_user)):
    """Get risk summary."""
    try:
        return risk_engine.get_user_risk_summary(user_id)

    except Exception as e:
        logger.error(f"Get risk summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket for real-time data
class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.subscriptions: Dict[WebSocket, List[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept new connection."""
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        self.active_connections[client_id].append(websocket)
        self.subscriptions[websocket] = []

    def disconnect(self, websocket: WebSocket, client_id: str):
        """Remove connection."""
        if client_id in self.active_connections:
            self.active_connections[client_id].remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    async def send_personal_message(self, message: str, client_id: str):
        """Send message to specific client."""
        if client_id in self.active_connections:
            for connection in self.active_connections[client_id]:
                await connection.send_text(message)

    async def broadcast(self, channel: str, message: str):
        """Broadcast to all subscribed connections."""
        for websocket, channels in self.subscriptions.items():
            if channel in channels:
                await websocket.send_text(message)

    def subscribe(self, websocket: WebSocket, channel: str):
        """Subscribe to channel."""
        if websocket in self.subscriptions:
            if channel not in self.subscriptions[websocket]:
                self.subscriptions[websocket].append(channel)

    def unsubscribe(self, websocket: WebSocket, channel: str):
        """Unsubscribe from channel."""
        if websocket in self.subscriptions:
            if channel in self.subscriptions[websocket]:
                self.subscriptions[websocket].remove(channel)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data."""
    client_id = "anonymous"  # Would authenticate properly
    await manager.connect(websocket, client_id)

    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle different message types
            if message["type"] == "subscribe":
                channel = message["channel"]
                manager.subscribe(websocket, channel)
                await websocket.send_text(json.dumps({
                    "type": "subscribed",
                    "channel": channel
                }))

            elif message["type"] == "unsubscribe":
                channel = message["channel"]
                manager.unsubscribe(websocket, channel)
                await websocket.send_text(json.dumps({
                    "type": "unsubscribed",
                    "channel": channel
                }))

            elif message["type"] == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                }))

    except WebSocketDisconnect:
        manager.disconnect(websocket, client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket, client_id)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "oms": "operational",
            "risk_engine": "operational",
            "matching_engine": "operational"
        }
    }


# Market Data Endpoints
@app.get("/api/v1/market/orderbook/{symbol}")
async def get_orderbook(
    symbol: str,
    depth: int = 20
):
    """Get order book for a symbol."""
    # Normalize symbol format
    symbol = symbol.replace("-", "/")

    if symbol not in engines:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    engine = engines[symbol]
    orderbook = engine.get_order_book_snapshot(depth)

    return {
        "symbol": symbol,
        "bids": orderbook.get("bids", []),
        "asks": orderbook.get("asks", []),
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/market/trades/{symbol}")
async def get_recent_trades(
    symbol: str,
    limit: int = 100
):
    """Get recent trades for a symbol."""
    # Normalize symbol format
    symbol = symbol.replace("-", "/")

    if symbol not in engines:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    # For now, return mock trades (in production, query from database)
    trades = []
    engine = engines[symbol]
    stats = engine.get_stats()

    # Generate some mock trades based on current orderbook
    orderbook = engine.get_order_book_snapshot(5)
    if orderbook.get("bids") and orderbook.get("asks"):
        mid_price = (orderbook["bids"][0][0] + orderbook["asks"][0][0]) / 2

        import random
        for i in range(min(limit, 10)):
            trades.append({
                "id": f"trade_{i}",
                "price": mid_price + random.uniform(-0.5, 0.5),
                "quantity": random.uniform(0.1, 10.0),
                "side": "buy" if random.random() > 0.5 else "sell",
                "timestamp": (datetime.utcnow() - timedelta(seconds=i*10)).isoformat()
            })

    return trades


@app.get("/api/v1/market/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Get 24hr ticker statistics for a symbol."""
    # Normalize symbol format
    symbol = symbol.replace("-", "/")

    if symbol not in engines:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    engine = engines[symbol]
    orderbook = engine.get_order_book_snapshot(1)
    stats = engine.get_stats()

    # Calculate ticker data
    bid = orderbook["bids"][0][0] if orderbook.get("bids") else 0
    ask = orderbook["asks"][0][0] if orderbook.get("asks") else 0
    last = (bid + ask) / 2 if bid and ask else 100.0

    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "last": last,
        "volume_24h": stats.get("total_volume", 0),
        "trades_24h": stats.get("total_trades", 0),
        "high_24h": last * 1.05,  # Mock data
        "low_24h": last * 0.95,   # Mock data
        "change_24h": 2.5,         # Mock data
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/market/symbols")
async def get_symbols():
    """Get list of all trading symbols."""
    return {
        "symbols": list(engines.keys()),
        "count": len(engines)
    }


# Account Endpoints
@app.get("/api/v1/account/balance")
async def get_balance(
    user_id: str = Depends(get_current_user),
    _: str = Depends(check_rate_limit)
):
    """Get user account balances."""
    # In production, query from database
    # For now, return mock data
    return {
        "balances": {
            "DEC": {
                "available": "10000.00000000",
                "locked": "500.00000000",
                "total": "10500.00000000"
            },
            "USD": {
                "available": "50000.00",
                "locked": "1000.00",
                "total": "51000.00"
            },
            "BTC": {
                "available": "0.50000000",
                "locked": "0.00000000",
                "total": "0.50000000"
            },
            "ETH": {
                "available": "5.00000000",
                "locked": "0.00000000",
                "total": "5.00000000"
            }
        },
        "total_value_usd": "75000.00",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/api/v1/account/info")
async def get_account_info(
    user_data: dict = Depends(get_current_user_full)
):
    """Get user account information."""
    return {
        "user_id": user_data["user_id"],
        "username": user_data.get("username", "unknown"),
        "email": user_data.get("email", ""),
        "kyc_status": user_data.get("kyc_status", "pending"),
        "permissions": user_data.get("permissions", []),
        "created_at": datetime.utcnow().isoformat()
    }


# Import for timedelta
from datetime import timedelta


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=13000)