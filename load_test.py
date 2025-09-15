#!/usr/bin/env python3
"""
Load Testing for Exchange System
Tests performance with concurrent users and high volume
"""

import asyncio
import aiohttp
import time
import random
import json
from datetime import datetime
from typing import List, Dict
import statistics

API_BASE = "http://localhost:13000"
WS_BASE = "ws://localhost:13765"


class LoadTester:
    def __init__(self, num_users: int = 10, orders_per_user: int = 100):
        self.num_users = num_users
        self.orders_per_user = orders_per_user
        self.results = {
            'orders_placed': 0,
            'orders_failed': 0,
            'trades_executed': 0,
            'response_times': [],
            'websocket_latencies': [],
            'errors': []
        }

    async def place_order(self, session: aiohttp.ClientSession, user_id: int) -> float:
        """Place a single order and return response time"""
        # Random order parameters
        side = random.choice(['buy', 'sell'])
        price = 100 + random.uniform(-5, 5)
        quantity = random.uniform(0.1, 10)

        order = {
            "symbol": "DEC/USD",
            "side": side,
            "order_type": "limit",
            "quantity": str(quantity),
            "price": str(price),
            "time_in_force": "GTC"
        }

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": f"test-user-{user_id}"
        }

        start_time = time.perf_counter()

        try:
            async with session.post(
                f"{API_BASE}/api/v1/orders",
                json=order,
                headers=headers,
                timeout=5
            ) as response:
                response_time = time.perf_counter() - start_time

                if response.status == 200:
                    self.results['orders_placed'] += 1
                else:
                    self.results['orders_failed'] += 1
                    error_text = await response.text()
                    self.results['errors'].append(f"Order failed: {error_text[:100]}")

                return response_time

        except asyncio.TimeoutError:
            self.results['orders_failed'] += 1
            self.results['errors'].append("Order timeout")
            return 5.0  # Timeout value

        except Exception as e:
            self.results['orders_failed'] += 1
            self.results['errors'].append(f"Order error: {str(e)[:100]}")
            return 0.0

    async def user_session(self, user_id: int):
        """Simulate a single user placing multiple orders"""
        async with aiohttp.ClientSession() as session:
            user_times = []

            for _ in range(self.orders_per_user):
                response_time = await self.place_order(session, user_id)
                if response_time > 0:
                    user_times.append(response_time)
                    self.results['response_times'].append(response_time)

                # Small random delay between orders
                await asyncio.sleep(random.uniform(0.01, 0.1))

            if user_times:
                avg_time = statistics.mean(user_times)
                print(f"User {user_id}: {len(user_times)} orders, avg {avg_time:.3f}s")

    async def test_market_data(self):
        """Test market data endpoint performance"""
        print("\nTesting market data endpoints...")

        async with aiohttp.ClientSession() as session:
            endpoints = [
                "/api/v1/market/orderbook/DEC-USD",
                "/api/v1/market/trades/DEC-USD",
                "/api/v1/market/ticker/DEC-USD"
            ]

            for endpoint in endpoints:
                start_time = time.perf_counter()

                try:
                    async with session.get(f"{API_BASE}{endpoint}", timeout=5) as response:
                        response_time = time.perf_counter() - start_time

                        if response.status == 200:
                            data = await response.json()
                            print(f"  {endpoint}: {response_time:.3f}s")
                        else:
                            print(f"  {endpoint}: Failed ({response.status})")

                except Exception as e:
                    print(f"  {endpoint}: Error - {e}")

    async def test_websocket(self):
        """Test WebSocket feed performance"""
        print("\nTesting WebSocket feed...")

        try:
            import websockets

            async with websockets.connect(f"{WS_BASE}/ws") as websocket:
                # Subscribe to all symbols
                subscribe_msg = json.dumps({
                    "action": "subscribe",
                    "symbols": ["DEC/USD", "BTC/USD", "ETH/USD"]
                })

                start_time = time.perf_counter()
                await websocket.send(subscribe_msg)

                # Receive some messages
                for _ in range(10):
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        latency = time.perf_counter() - start_time
                        self.results['websocket_latencies'].append(latency)
                        start_time = time.perf_counter()
                    except asyncio.TimeoutError:
                        break

                if self.results['websocket_latencies']:
                    avg_latency = statistics.mean(self.results['websocket_latencies'])
                    print(f"  WebSocket latency: {avg_latency*1000:.2f}ms")

        except Exception as e:
            print(f"  WebSocket error: {e}")

    async def run(self):
        """Run the complete load test"""
        print("=" * 60)
        print(f"LOAD TEST: {self.num_users} users, {self.orders_per_user} orders each")
        print("=" * 60)

        # Test market data first
        await self.test_market_data()

        # Test WebSocket
        await self.test_websocket()

        # Start load test
        print(f"\nStarting load test with {self.num_users} concurrent users...")
        start_time = time.perf_counter()

        # Create tasks for all users
        tasks = [self.user_session(i) for i in range(self.num_users)]

        # Run all users concurrently
        await asyncio.gather(*tasks)

        total_time = time.perf_counter() - start_time

        # Calculate statistics
        self.print_results(total_time)

    def print_results(self, total_time: float):
        """Print test results and statistics"""
        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)

        total_orders = self.results['orders_placed'] + self.results['orders_failed']
        success_rate = (self.results['orders_placed'] / total_orders * 100) if total_orders > 0 else 0

        print(f"\nOrders:")
        print(f"  Total attempted: {total_orders}")
        print(f"  Successful: {self.results['orders_placed']}")
        print(f"  Failed: {self.results['orders_failed']}")
        print(f"  Success rate: {success_rate:.1f}%")

        if self.results['response_times']:
            times = self.results['response_times']
            print(f"\nResponse Times:")
            print(f"  Min: {min(times):.3f}s")
            print(f"  Max: {max(times):.3f}s")
            print(f"  Mean: {statistics.mean(times):.3f}s")
            print(f"  Median: {statistics.median(times):.3f}s")

            if len(times) > 1:
                print(f"  Std Dev: {statistics.stdev(times):.3f}s")

            # Calculate percentiles
            sorted_times = sorted(times)
            p50 = sorted_times[len(sorted_times) // 2]
            p95 = sorted_times[int(len(sorted_times) * 0.95)]
            p99 = sorted_times[int(len(sorted_times) * 0.99)]

            print(f"  P50: {p50:.3f}s")
            print(f"  P95: {p95:.3f}s")
            print(f"  P99: {p99:.3f}s")

        print(f"\nThroughput:")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Orders/second: {total_orders / total_time:.1f}")

        if self.results['errors']:
            print(f"\nErrors (first 5):")
            for error in self.results['errors'][:5]:
                print(f"  - {error}")

        # Performance assessment
        print("\n" + "=" * 60)
        print("PERFORMANCE ASSESSMENT")
        print("=" * 60)

        if success_rate > 95 and statistics.mean(times) < 0.1:
            print("✅ EXCELLENT: High success rate with low latency")
        elif success_rate > 90 and statistics.mean(times) < 0.5:
            print("✅ GOOD: Acceptable performance under load")
        elif success_rate > 80:
            print("⚠️  FAIR: Some performance degradation under load")
        else:
            print("❌ POOR: Significant issues under load")


async def stress_test():
    """Run increasingly aggressive load tests"""
    print("STRESS TEST - Finding Breaking Point")
    print("=" * 60)

    test_configs = [
        (10, 10),    # Warm up: 10 users, 10 orders each
        (50, 20),    # Medium: 50 users, 20 orders each
        (100, 50),   # High: 100 users, 50 orders each
        (200, 100),  # Extreme: 200 users, 100 orders each
    ]

    for num_users, orders_per_user in test_configs:
        print(f"\n\nTest Level: {num_users} users × {orders_per_user} orders")
        print("-" * 40)

        tester = LoadTester(num_users, orders_per_user)
        await tester.run()

        # Check if we should continue
        if tester.results['orders_failed'] > tester.results['orders_placed']:
            print("\n⚠️  System showing signs of stress. Stopping test.")
            break

        # Pause between tests
        print("\nPausing for 5 seconds before next test...")
        await asyncio.sleep(5)


async def main():
    """Main test runner"""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        await stress_test()
    else:
        # Default load test
        tester = LoadTester(num_users=50, orders_per_user=20)
        await tester.run()


if __name__ == "__main__":
    print("EXCHANGE LOAD TESTING")
    print("=" * 60)
    print("Usage:")
    print("  python load_test.py         # Standard load test")
    print("  python load_test.py stress  # Stress test (increasing load)")
    print("=" * 60)
    print()

    # Check if API is running
    import requests
    try:
        response = requests.get(f"{API_BASE}/health", timeout=2)
        if response.status_code == 200:
            print("✅ API is running")
            asyncio.run(main())
        else:
            print("❌ API returned error")
    except:
        print("❌ Cannot connect to API. Please start the exchange first.")
        print("   Run: ./start-exchange.sh")