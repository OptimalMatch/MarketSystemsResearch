#!/bin/bash
# Start Exchange System

echo "=========================================="
echo "Starting Exchange System"
echo "=========================================="

# Check if DeCoin is running
echo -n "Checking DeCoin nodes... "
if curl -s http://localhost:11080/blockchain > /dev/null 2>&1; then
    echo "✅ DeCoin is running"
else
    echo "⚠️  DeCoin not detected on port 11080"
fi

# Start PostgreSQL and Redis first
echo ""
echo "Starting database services..."
docker compose -f docker-compose.exchange.yml up -d postgres redis

# Wait for databases to be ready
echo "Waiting for databases..."
sleep 5

# Start core services
echo ""
echo "Starting core exchange services..."
docker compose -f docker-compose.exchange.yml up -d matching-engine decoin-ledger

# Wait for core services
sleep 3

# Start remaining services
echo ""
echo "Starting API and WebSocket services..."
docker compose -f docker-compose.exchange.yml up -d websocket-feed api-gateway

echo ""
echo "=========================================="
echo "Exchange System Started!"
echo "=========================================="
echo ""
echo "Services:"
echo "  API Gateway:    http://localhost:13000"
echo "  WebSocket Feed: ws://localhost:13765"
echo "  PostgreSQL:     localhost:5432"
echo "  Redis:          localhost:6379"
echo ""
echo "Check status with:"
echo "  docker compose -f docker-compose.exchange.yml ps"
echo ""
echo "View logs with:"
echo "  docker compose -f docker-compose.exchange.yml logs -f"
echo ""