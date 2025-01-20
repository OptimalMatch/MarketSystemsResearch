import time
import random
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import statistics
from dataclasses import dataclass
from Exchange import Market, OrderSide


@dataclass
class PerformanceMetrics:
    total_orders: int
    successful_orders: int
    failed_orders: int
    execution_time: float
    orders_per_second: float
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    latency_percentile_95th_ms: float


class ExchangePerformanceTester:
    def __init__(self, market: Market):
        self.market = market
        self.securities = ['AAPL', 'GOOGL', 'MSFT', 'AMZN']  # Test securities
        self.users = [f'user{i}' for i in range(100)]  # Test users
        self.latencies = []
        self._setup_complete = False

    def setup_test_data(self):
        """Initialize the market with test data"""
        if self._setup_complete:
            return

        # Create orderbooks if they don't exist
        for security in self.securities:
            try:
                self.market.create_orderbook(security)
            except ValueError:
                # Orderbook already exists, skip creation
                continue

        # Setup initial balances
        for user in self.users:
            # Give each user some cash and securities
            self.market.deposit(user, 'cash', Decimal('1000000'))
            for security in self.securities:
                self.market.deposit(user, security, Decimal('10000'))

        self._setup_complete = True

    def generate_random_order(self) -> Dict:
        """Generate a random order for testing"""
        security = random.choice(self.securities)
        side = random.choice([OrderSide.BUY, OrderSide.SELL])
        base_price = Decimal('100')
        price_variation = Decimal(str(random.uniform(-10, 10)))
        price = base_price + price_variation
        size = Decimal(str(random.randint(1, 100)))
        user = random.choice(self.users)

        return {
            'owner_id': user,
            'security_id': security,
            'side': side,
            'price': price,
            'size': size
        }

    def execute_single_order(self, order_params: Dict) -> float:
        """Execute a single order and return the execution time"""
        start_time = time.perf_counter()
        try:
            self.market.place_order(
                owner_id=order_params['owner_id'],
                security_id=order_params['security_id'],
                side=order_params['side'],
                price=order_params['price'],
                size=order_params['size']
            )
            success = True
        except Exception as e:
            print(f"Order failed: {str(e)}")  # Debug information
            success = False

        end_time = time.perf_counter()
        execution_time = end_time - start_time

        return execution_time, success

    def clear_market_state(self):
        """Clear all orders and trades (optional cleanup between tests)"""
        for security in self.securities:
            if security in self.market.orderbooks:
                orderbook = self.market.orderbooks[security]
                orderbook.bids.clear()
                orderbook.asks.clear()
                orderbook.trades.clear()
        self.latencies.clear()

    def run_performance_test(self,
                             num_orders: int = 1000,
                             concurrent_orders: int = 10) -> PerformanceMetrics:
        """
        Run a performance test with the specified number of orders and concurrency level
        """
        self.setup_test_data()
        self.latencies = []
        successful_orders = 0
        failed_orders = 0

        # Generate all orders upfront
        orders = [self.generate_random_order() for _ in range(num_orders)]

        # Execute orders with ThreadPoolExecutor
        start_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=concurrent_orders) as executor:
            future_to_order = {
                executor.submit(self.execute_single_order, order): order
                for order in orders
            }

            for future in as_completed(future_to_order):
                try:
                    execution_time, success = future.result()
                    self.latencies.append(execution_time * 1000)  # Convert to milliseconds
                    if success:
                        successful_orders += 1
                    else:
                        failed_orders += 1
                except Exception as e:
                    print(f"Error processing order: {str(e)}")
                    failed_orders += 1

        end_time = time.perf_counter()
        total_time = end_time - start_time

        # Calculate metrics
        orders_per_second = num_orders / total_time
        if self.latencies:  # Only calculate if we have successful orders
            avg_latency = statistics.mean(self.latencies)
            min_latency = min(self.latencies)
            max_latency = max(self.latencies)
            percentile_95 = statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) >= 20 else max_latency
        else:
            avg_latency = min_latency = max_latency = percentile_95 = 0

        return PerformanceMetrics(
            total_orders=num_orders,
            successful_orders=successful_orders,
            failed_orders=failed_orders,
            execution_time=total_time,
            orders_per_second=orders_per_second,
            avg_latency_ms=avg_latency,
            min_latency_ms=min_latency,
            max_latency_ms=max_latency,
            latency_percentile_95th_ms=percentile_95
        )

    def run_load_test(self,
                      duration_seconds: int = 60,
                      concurrent_orders: int = 10) -> PerformanceMetrics:
        """Run a load test for a specified duration"""
        self.setup_test_data()
        self.latencies = []
        successful_orders = 0
        failed_orders = 0

        start_time = time.perf_counter()
        end_time = start_time + duration_seconds

        with ThreadPoolExecutor(max_workers=concurrent_orders) as executor:
            futures = set()

            while time.perf_counter() < end_time:
                # Keep submitting orders while maintaining concurrency level
                while len(futures) < concurrent_orders:
                    order = self.generate_random_order()
                    futures.add(
                        executor.submit(self.execute_single_order, order)
                    )

                # Process completed futures
                done_futures = []
                for future in list(futures):
                    if future.done():
                        done_futures.append(future)
                        futures.remove(future)

                for future in done_futures:
                    try:
                        execution_time, success = future.result()
                        self.latencies.append(execution_time * 1000)
                        if success:
                            successful_orders += 1
                        else:
                            failed_orders += 1
                    except Exception as e:
                        print(f"Error processing order: {str(e)}")
                        failed_orders += 1

                time.sleep(0.001)  # Small sleep to prevent CPU thrashing

        total_time = time.perf_counter() - start_time
        total_orders = successful_orders + failed_orders

        # Calculate metrics
        orders_per_second = total_orders / total_time
        if self.latencies:
            avg_latency = statistics.mean(self.latencies)
            min_latency = min(self.latencies)
            max_latency = max(self.latencies)
            percentile_95 = statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) >= 20 else max_latency
        else:
            avg_latency = min_latency = max_latency = percentile_95 = 0

        return PerformanceMetrics(
            total_orders=total_orders,
            successful_orders=successful_orders,
            failed_orders=failed_orders,
            execution_time=total_time,
            orders_per_second=orders_per_second,
            avg_latency_ms=avg_latency,
            min_latency_ms=min_latency,
            max_latency_ms=max_latency,
            latency_percentile_95th_ms=percentile_95
        )


if __name__ == "__main__":
    # Example usage
    market = Market()
    tester = ExchangePerformanceTester(market)

    print("\nRunning throughput test...")
    metrics = tester.run_performance_test(num_orders=100000, concurrent_orders=1000)

    print(f"Throughput Test Results:")
    print(f"Total Orders: {metrics.total_orders}")
    print(f"Successful Orders: {metrics.successful_orders}")
    print(f"Failed Orders: {metrics.failed_orders}")
    print(f"Total Time: {metrics.execution_time:.4f} seconds")
    print(f"Orders per Second: {metrics.orders_per_second:.2f}")
    print(f"Average Latency: {metrics.avg_latency_ms:.4f} ms")
    print(f"Min Latency: {metrics.min_latency_ms:.4f} ms")
    print(f"Max Latency: {metrics.max_latency_ms:.4f} ms")
    print(f"95th Percentile Latency: {metrics.latency_percentile_95th_ms:.4f} ms")

    # Optional: Clear state before load test
    tester.clear_market_state()

    print("\nRunning load test...")
    metrics = tester.run_load_test(duration_seconds=30, concurrent_orders=10000)

    print(f"\nLoad Test Results:")
    print(f"Total Orders: {metrics.total_orders}")
    print(f"Successful Orders: {metrics.successful_orders}")
    print(f"Failed Orders: {metrics.failed_orders}")
    print(f"Total Time: {metrics.execution_time:.4f} seconds")
    print(f"Orders per Second: {metrics.orders_per_second:.2f}")
    print(f"Average Latency: {metrics.avg_latency_ms:.4f} ms")
    print(f"Min Latency: {metrics.min_latency_ms:.4f} ms")
    print(f"Max Latency: {metrics.max_latency_ms:.4f} ms")
    print(f"95th Percentile Latency: {metrics.latency_percentile_95th_ms:.4f} ms")