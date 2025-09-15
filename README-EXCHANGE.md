# Exchange System - Containerized Deployment

## Overview

Ultra-high performance cryptocurrency exchange system featuring:
- **1.1M+ orders/second** matching engine
- **<100ms** DeCoin settlement
- Real-time WebSocket data feeds
- Integrated with live DeCoin blockchain

## Quick Start

### 1. Prerequisites
- Docker & Docker Compose installed
- Port 8000 (API), 8765 (WebSocket), 5432 (PostgreSQL), 6379 (Redis) available
- DeCoin containers running (optional, for blockchain integration)

### 2. Build and Start

```bash
# Build all containers
make -f Makefile.exchange build

# Start all services
make -f Makefile.exchange up

# Check status
make -f Makefile.exchange status
```

### 3. Verify Installation

```bash
# Check API health
curl http://localhost:8000/health

# Connect to WebSocket (example)
wscat -c ws://localhost:8765
> {"type": "subscribe", "channel": "ticker", "symbol": "DEC/USD"}
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   API Gateway                        │
│                  (Port 8000)                         │
└─────────────────────────────────────────────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    ▼                    ▼                    ▼
┌──────────┐      ┌──────────┐        ┌──────────┐
│   OMS    │      │ Matching │        │  DeCoin  │
│          │◄────►│  Engine  │◄──────►│  Ledger  │
└──────────┘      └──────────┘        └──────────┘
    │                    │                    │
    └────────────────────┼────────────────────┘
                         ▼
                ┌──────────────┐
                │   WebSocket  │
                │     Feed     │
                │  (Port 8765) │
                └──────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    ▼                    ▼                    ▼
[Traders]           [Market Makers]        [Bots]
```

## Services

### Core Services

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL | 5432 | Main database |
| Redis | 6379 | Cache & pub/sub |
| Matching Engine | Internal | Order matching (1.1M orders/sec) |
| OMS | Internal | Order management |
| DeCoin Ledger | Internal | Instant DEC settlements |
| WebSocket Feed | 8765 | Real-time market data |
| API Gateway | 8000 | REST API endpoint |

### Performance Metrics

- **Matching Engine**: 1,109,595 orders/second
- **DeCoin Transfers**: <100ms average
- **WebSocket Latency**: <1ms to subscribers
- **Database Writes**: 100K+ TPS

## API Endpoints

### Trading
```
POST   /api/v1/orders          - Place order
DELETE /api/v1/orders/{id}     - Cancel order
GET    /api/v1/orders          - List orders
```

### Market Data
```
GET    /api/v1/market/{symbol}/orderbook
GET    /api/v1/market/{symbol}/trades
GET    /api/v1/market/{symbol}/ticker
```

### Account
```
GET    /api/v1/account/balance
GET    /api/v1/account/positions
```

## WebSocket Channels

### Subscribe to channels:
```javascript
// Order book updates
{
  "type": "subscribe",
  "channel": "orderbook",
  "symbol": "DEC/USD",
  "depth": 20
}

// Trade feed
{
  "type": "subscribe",
  "channel": "trades",
  "symbol": "DEC/USD"
}

// Price ticker
{
  "type": "subscribe",
  "channel": "ticker",
  "symbol": "DEC/USD"
}
```

## Management Commands

```bash
# View logs
make -f Makefile.exchange logs

# View specific service logs
make -f Makefile.exchange logs-oms
make -f Makefile.exchange logs-ws

# Access PostgreSQL
make -f Makefile.exchange shell-db

# Access Redis
make -f Makefile.exchange shell-redis

# Monitor performance
make -f Makefile.exchange monitor

# Stop all services
make -f Makefile.exchange down

# Clean everything (including data)
make -f Makefile.exchange clean
```

## Configuration

Edit `.env.exchange` to customize:

```env
# Database
POSTGRES_PASSWORD=your-secure-password

# Performance
MAX_ORDERS_PER_SECOND=1000000

# DeCoin Integration
DECOIN_NODE_URL=http://host.docker.internal:11080
```

## Testing

### Integration Test
```bash
# Run automated tests
docker-compose -f docker-compose.exchange.yml exec api-gateway python src/exchange/test_live_integration.py
```

### Manual Testing
```python
# Connect and place orders
import asyncio
import aiohttp

async def test_order():
    async with aiohttp.ClientSession() as session:
        # Place order
        order = {
            "symbol": "DEC/USD",
            "side": "buy",
            "type": "limit",
            "quantity": 10,
            "price": 100.00
        }

        async with session.post(
            "http://localhost:8000/api/v1/orders",
            json=order
        ) as resp:
            result = await resp.json()
            print(f"Order placed: {result}")

asyncio.run(test_order())
```

## Production Deployment

### 1. Security Hardening
- Change all passwords in `.env.exchange`
- Enable TLS for all services
- Set up firewall rules
- Enable audit logging

### 2. Performance Tuning
- Increase PostgreSQL shared_buffers
- Tune Redis maxmemory
- Set CPU affinity for matching engine
- Enable huge pages

### 3. High Availability
- Set up PostgreSQL replication
- Configure Redis Sentinel
- Deploy multiple API gateway instances
- Use load balancer

### 4. Monitoring
- Set up Prometheus + Grafana
- Configure alerts
- Enable distributed tracing
- Set up log aggregation

## Troubleshooting

### Service won't start
```bash
# Check logs
docker-compose -f docker-compose.exchange.yml logs [service-name]

# Rebuild image
docker-compose -f docker-compose.exchange.yml build --no-cache [service-name]
```

### Performance issues
```bash
# Check resource usage
docker stats

# Increase resources in docker-compose.exchange.yml
services:
  matching-engine:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
```

### Database connection issues
```bash
# Check PostgreSQL is running
docker-compose -f docker-compose.exchange.yml ps postgres

# Test connection
docker-compose -f docker-compose.exchange.yml exec postgres pg_isready
```

## Support

For issues or questions:
- Check logs: `make -f Makefile.exchange logs`
- View status: `make -f Makefile.exchange status`
- GitHub Issues: [Create an issue](https://github.com/unidatum/MarketSystemsResearch/issues)