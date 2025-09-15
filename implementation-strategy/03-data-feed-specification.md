# Data Feed Service Specification

## Overview
Real-time market data distribution system providing order book updates, trade feeds, and aggregated market statistics with sub-millisecond latency.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Data Sources                           │
│  (Matching Engine, OMS, External Feeds)                   │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│                  Data Aggregator                          │
│  (Normalization, Validation, Enrichment)                  │
└──────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   WebSocket  │  │     REST     │  │     FIX      │
│    Server    │  │     API      │  │   Gateway    │
└──────────────┘  └──────────────┘  └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   [Clients]           [Clients]           [Clients]
```

## Core Components

### 1. Data Aggregator

```python
class DataAggregator:
    def __init__(self):
        self.order_books = {}
        self.trade_cache = deque(maxlen=10000)
        self.ticker_cache = {}
        self.candle_builder = CandleBuilder()

    def process_order_event(self, event):
        """Process order book changes"""
        # Update internal order book
        # Generate L2/L3 updates
        # Trigger subscriber notifications

    def process_trade_event(self, trade):
        """Process executed trades"""
        # Update trade cache
        # Update ticker data
        # Update volume statistics
        # Build candlesticks
```

### 2. Market Data Types

#### Level 1 Data (Ticker)
```json
{
  "type": "ticker",
  "symbol": "BTC/USD",
  "timestamp": "2025-01-14T12:00:00.123456Z",
  "data": {
    "bid": "45000.00",
    "bid_size": "2.5",
    "ask": "45001.00",
    "ask_size": "3.0",
    "last": "45000.50",
    "volume_24h": "1234.56",
    "high_24h": "46000.00",
    "low_24h": "44000.00",
    "change_24h": "2.5%"
  }
}
```

#### Level 2 Data (Order Book)
```json
{
  "type": "l2_snapshot",
  "symbol": "BTC/USD",
  "timestamp": "2025-01-14T12:00:00.123456Z",
  "data": {
    "bids": [
      ["45000.00", "2.5"],
      ["44999.00", "5.0"],
      ["44998.00", "10.0"]
    ],
    "asks": [
      ["45001.00", "3.0"],
      ["45002.00", "4.5"],
      ["45003.00", "8.0"]
    ]
  }
}
```

#### Level 3 Data (Full Order Book)
```json
{
  "type": "l3_update",
  "symbol": "BTC/USD",
  "timestamp": "2025-01-14T12:00:00.123456Z",
  "data": {
    "action": "add",
    "order_id": "123456",
    "side": "buy",
    "price": "45000.00",
    "size": "1.5"
  }
}
```

#### Trade Feed
```json
{
  "type": "trade",
  "symbol": "BTC/USD",
  "timestamp": "2025-01-14T12:00:00.123456Z",
  "data": {
    "trade_id": "789012",
    "price": "45000.50",
    "size": "0.5",
    "side": "buy",
    "liquidation": false
  }
}
```

### 3. WebSocket Implementation

```python
class MarketDataWebSocket:
    def __init__(self):
        self.connections = {}
        self.subscriptions = defaultdict(set)

    async def handle_connection(self, websocket):
        """Handle new WebSocket connection"""
        client_id = str(uuid.uuid4())
        self.connections[client_id] = websocket

    async def handle_subscription(self, client_id, message):
        """Process subscription requests"""
        channel = message['channel']
        symbol = message.get('symbol')

        # Validate subscription
        if not self.validate_subscription(client_id, channel):
            return {"error": "Invalid subscription"}

        # Add to subscription list
        self.subscriptions[f"{channel}:{symbol}"].add(client_id)

        # Send initial snapshot
        await self.send_snapshot(client_id, channel, symbol)

    async def broadcast_update(self, channel, symbol, data):
        """Broadcast updates to subscribers"""
        subscribers = self.subscriptions[f"{channel}:{symbol}"]

        message = json.dumps({
            "channel": channel,
            "symbol": symbol,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Send to all subscribers in parallel
        await asyncio.gather(*[
            self.connections[client_id].send(message)
            for client_id in subscribers
            if client_id in self.connections
        ])
```

### 4. REST API Endpoints

```yaml
/api/v1/market/symbols:
  GET:
    description: List all trading symbols
    response:
      - symbol: BTC/USD
        base_currency: BTC
        quote_currency: USD
        min_order_size: 0.001
        tick_size: 0.01
        status: active

/api/v1/market/{symbol}/ticker:
  GET:
    description: Get current ticker data
    parameters:
      - symbol: Trading pair

/api/v1/market/{symbol}/orderbook:
  GET:
    description: Get order book snapshot
    parameters:
      - symbol: Trading pair
      - depth: Number of levels (default: 20)

/api/v1/market/{symbol}/trades:
  GET:
    description: Get recent trades
    parameters:
      - symbol: Trading pair
      - limit: Number of trades (default: 100)

/api/v1/market/{symbol}/candles:
  GET:
    description: Get candlestick data
    parameters:
      - symbol: Trading pair
      - interval: 1m, 5m, 15m, 1h, 4h, 1d
      - start: Start timestamp
      - end: End timestamp
```

### 5. Data Storage

```python
class MarketDataStorage:
    def __init__(self):
        # TimescaleDB for time-series data
        self.timeseries_db = TimescaleDB()

        # Redis for real-time cache
        self.redis_cache = Redis()

        # S3 for historical data archive
        self.s3_archive = S3Client()

    async def store_trade(self, trade):
        """Store trade in multiple systems"""
        # Write to TimescaleDB
        await self.timeseries_db.insert_trade(trade)

        # Update Redis cache
        await self.redis_cache.lpush(f"trades:{trade.symbol}", trade)

        # Archive if needed
        if self.should_archive(trade):
            await self.s3_archive.upload(trade)

    async def get_historical_data(self, symbol, start, end):
        """Retrieve historical data"""
        # Check Redis cache first
        cached = await self.redis_cache.get(f"hist:{symbol}:{start}:{end}")
        if cached:
            return cached

        # Query TimescaleDB
        data = await self.timeseries_db.query_range(symbol, start, end)

        # Cache result
        await self.redis_cache.setex(
            f"hist:{symbol}:{start}:{end}",
            3600,
            data
        )

        return data
```

## Performance Requirements

### Latency Targets
- **Order Book Updates**: <1ms to subscribers
- **Trade Feed**: <1ms to subscribers
- **REST API**: <10ms response time
- **WebSocket Connection**: <100ms establishment

### Throughput Targets
- **Updates per Second**: 1M+ across all symbols
- **Concurrent WebSockets**: 100,000+
- **REST Requests**: 50,000/second
- **Data Points Stored**: 10M+/second

### Reliability
- **Uptime**: 99.99% availability
- **Data Loss**: Zero tolerance
- **Failover**: <1 second
- **Recovery**: Full replay capability

## Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Set up TimescaleDB for time-series storage
- [ ] Implement Redis caching layer
- [ ] Create data aggregator service
- [ ] Build WebSocket server

### Phase 2: Data Types
- [ ] Implement Level 1 (ticker) data
- [ ] Implement Level 2 (order book) data
- [ ] Implement trade feed
- [ ] Build candlestick aggregation

### Phase 3: Distribution
- [ ] WebSocket subscription management
- [ ] REST API endpoints
- [ ] FIX protocol gateway
- [ ] Binary protocol (optional)

### Phase 4: Advanced Features
- [ ] Historical data API
- [ ] Data compression
- [ ] Differential updates
- [ ] Market statistics calculation

### Phase 5: Optimization
- [ ] Implement data batching
- [ ] Add connection pooling
- [ ] Optimize serialization
- [ ] Implement rate limiting

## Monitoring & Alerting

### Key Metrics
- **Latency**: p50, p95, p99 percentiles
- **Throughput**: Messages/second by type
- **Connections**: Active WebSocket connections
- **Errors**: Failed deliveries, timeouts

### Alerts
- Latency exceeds 10ms (p99)
- Message queue depth >10,000
- Connection failures >1%
- Storage capacity <20%

## Security Considerations

### Access Control
- API key authentication for REST
- JWT tokens for WebSocket
- Rate limiting per user/IP
- Subscription limits per tier

### Data Protection
- TLS 1.3 for all connections
- Message signing for integrity
- Audit logging for compliance
- Data anonymization options

## Testing Strategy

### Unit Tests
- Data aggregation logic
- Message serialization
- Subscription management
- Cache operations

### Integration Tests
- End-to-end data flow
- WebSocket reconnection
- Failover scenarios
- Data consistency

### Load Tests
- 1M updates/second
- 100K concurrent connections
- Sustained load for 24 hours
- Burst traffic handling

### Chaos Testing
- Network partitions
- Database failures
- Cache invalidation
- Service crashes