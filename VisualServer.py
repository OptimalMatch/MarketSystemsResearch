from gevent import monkey
monkey.patch_all()  # Apply gevent monkey patching globally

import time
from decimal import Decimal
from Exchange import Market
from MarketMaker import MarketMaker
from MarketRushSimulator import MarketRushSimulator, get_memory_usage
from Visualization import Visualization  # The visualization class from earlier

def run_simulation_with_visualization():
    # Initialize the market
    market = Market()
    security_id = 'AAPL'
    market.create_orderbook(security_id)

    # Create and start the market maker
    maker_id = 'mm001'
    market.deposit(maker_id, 'cash', Decimal('100000000000'))
    market.deposit(maker_id, security_id, Decimal('1000000000'))
    mm = MarketMaker(market, maker_id, [security_id])

    # Create the rush simulator
    rush = MarketRushSimulator(market, security_id, num_participants=10000, enable_simulated_sellers=True)

    # Initialize visualization
    visualization = Visualization(market)

    try:
        # Start the visualization server
        visualization.start_server(port=5000)

        # Start both the market maker and the rush simulator
        print("Starting market maker, rush simulator, and visualization...")
        mm.start()
        rush.start_rush(duration_seconds=300)

        start_time = time.time()

        # Main monitoring loop
        while rush.is_running:
            elapsed_time = time.time() - start_time

            # Get simulator stats
            stats = rush.get_stats()
            orders_processed = stats['total_orders']
            trades_executed = market.get_trade_count()

            # Calculate throughput
            order_throughput = orders_processed / elapsed_time if elapsed_time > 0 else 0
            trade_throughput = trades_executed / elapsed_time if elapsed_time > 0 else 0

            # Get memory usage
            memory_usage = get_memory_usage()

            # Print stats
            print("\nRush Statistics:")
            print(f"Total Orders: {stats['total_orders']}")
            print(f"Successful Orders: {stats['successful_orders']}")
            print(f"Failed Orders: {stats['failed_orders']}")
            print(f"Current Price: {stats['current_price']}")
            print(f"Price Movement: {stats['price_movement_percent']:.2f}%")
            print(f"Volume: {stats['volume']}")
            print(f"Total Trades: {trades_executed}")

            print("\nPerformance Metrics:")
            print(f"Memory Usage: {memory_usage:.2f} MB")
            print(f"Order Throughput: {order_throughput:.2f} orders/sec")
            print(f"Trade Throughput: {trade_throughput:.2f} trades/sec")

            # Update visualization
            visualization.update_orderbook()
            visualization.update_candlestick()

            time.sleep(1)  # Update every second

    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")
    finally:
        # Stop everything
        rush.stop_rush()
        mm.stop()
        visualization.socketio.stop()  # Stop the Flask server
        market.finalize_trades()  # Flush any remaining trades
        print("Simulation ended.")

if __name__ == "__main__":
    run_simulation_with_visualization()
