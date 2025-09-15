#!/usr/bin/env python3
"""
Test Exchange API Endpoints
"""

import requests
import json
import time
from decimal import Decimal

API_BASE = "http://localhost:13000"

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{API_BASE}/health")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Health check passed: {data}")
        return True
    else:
        print(f"❌ Health check failed: {response.status_code}")
        return False

def test_place_order(api_key="test-key"):
    """Test order placement"""
    print("\nTesting order placement...")

    # Place a buy order
    order = {
        "symbol": "DEC/USD",
        "side": "buy",
        "order_type": "limit",
        "quantity": "10.0",
        "price": "99.50",
        "time_in_force": "GTC"
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    response = requests.post(
        f"{API_BASE}/api/v1/orders",
        json=order,
        headers=headers
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Order placed: {data}")
        return data.get("order_id")
    else:
        print(f"❌ Order placement failed: {response.status_code}")
        print(f"   Response: {response.text}")
        return None

def test_order_book(symbol="DEC/USD"):
    """Test order book endpoint"""
    print(f"\nTesting order book for {symbol}...")

    response = requests.get(f"{API_BASE}/api/v1/market/orderbook/{symbol}")

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Order book retrieved:")
        print(f"   Bids: {len(data.get('bids', []))} levels")
        print(f"   Asks: {len(data.get('asks', []))} levels")
        if data.get('bids'):
            print(f"   Best bid: {data['bids'][0]}")
        if data.get('asks'):
            print(f"   Best ask: {data['asks'][0]}")
        return True
    else:
        print(f"❌ Order book request failed: {response.status_code}")
        return False

def test_recent_trades(symbol="DEC/USD"):
    """Test recent trades endpoint"""
    print(f"\nTesting recent trades for {symbol}...")

    response = requests.get(f"{API_BASE}/api/v1/market/trades/{symbol}")

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Recent trades retrieved: {len(data)} trades")
        if data:
            print(f"   Latest trade: {data[0]}")
        return True
    else:
        print(f"❌ Recent trades request failed: {response.status_code}")
        return False

def test_websocket():
    """Test WebSocket connection"""
    print("\nTesting WebSocket connection...")
    try:
        import websocket
        ws = websocket.WebSocket()
        ws.connect("ws://localhost:13765/ws")

        # Subscribe to DEC/USD
        subscribe_msg = json.dumps({
            "action": "subscribe",
            "symbols": ["DEC/USD"]
        })
        ws.send(subscribe_msg)

        # Receive response
        response = ws.recv()
        print(f"✅ WebSocket connected: {response}")
        ws.close()
        return True
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")
        return False

def simulate_trading():
    """Simulate trading activity"""
    print("\n" + "="*60)
    print("SIMULATING TRADING ACTIVITY")
    print("="*60)

    # Place multiple orders
    orders = [
        {"side": "buy", "price": "99.00", "quantity": "5.0"},
        {"side": "buy", "price": "99.50", "quantity": "10.0"},
        {"side": "buy", "price": "100.00", "quantity": "15.0"},
        {"side": "sell", "price": "100.50", "quantity": "10.0"},
        {"side": "sell", "price": "101.00", "quantity": "15.0"},
        {"side": "sell", "price": "101.50", "quantity": "20.0"},
    ]

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": "test-key"
    }

    placed_orders = []
    for order_params in orders:
        order = {
            "symbol": "DEC/USD",
            "order_type": "limit",
            "time_in_force": "GTC",
            **order_params
        }

        response = requests.post(
            f"{API_BASE}/api/v1/orders",
            json=order,
            headers=headers
        )

        if response.status_code == 200:
            order_id = response.json().get("order_id")
            placed_orders.append(order_id)
            print(f"  Placed {order['side']} order at ${order['price']}: {order_id}")
        else:
            print(f"  Failed to place order: {response.text}")

        time.sleep(0.1)  # Small delay between orders

    return placed_orders

def main():
    """Run all tests"""
    print("="*60)
    print("EXCHANGE API TEST SUITE")
    print("="*60)

    results = {}

    # Test health
    results['health'] = test_health()

    # Test order placement
    order_id = test_place_order()
    results['order_placement'] = order_id is not None

    # Test order book
    results['order_book'] = test_order_book()

    # Test recent trades
    results['recent_trades'] = test_recent_trades()

    # Test WebSocket
    results['websocket'] = test_websocket()

    # Simulate trading
    if results['health']:
        simulate_trading()

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.ljust(20)}: {status}")

    total_passed = sum(1 for v in results.values() if v)
    total_tests = len(results)

    print(f"\nTotal: {total_passed}/{total_tests} tests passed")

    if total_passed == total_tests:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print(f"\n⚠️  {total_tests - total_passed} tests failed")

if __name__ == "__main__":
    # Check if services are running
    try:
        response = requests.get(f"{API_BASE}/health", timeout=2)
        main()
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API. Is the exchange running?")
        print("   Run: ./start-exchange.sh")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")