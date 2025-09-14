import eventlet
eventlet.monkey_patch()

import logging
from datetime import datetime
import time
import psutil
import os
import signal
import sys
from decimal import Decimal

from src.core.Exchange import Market
from src.market.MarketMaker import MarketMaker
from src.market.MarketRushSimulator import MarketRushSimulator
from src.visualization.Visualization import Visualization
from src.utils.config import Config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

class MarketServer:
    def __init__(self):
        self.market = Market()
        self.is_running = True
        self.setup_signal_handlers()

        # Get securities from environment or use defaults
        self.securities = self._get_securities_list()
        logger.info(f"Initializing market with securities: {self.securities}")

        # Initialize visualization
        self.visualization = Visualization(self.market)
        self.market.visualization = self.visualization

        # Initialize orderbooks for all securities
        for security in self.securities:
            self.market.create_orderbook(security)
            logger.info(f"Created orderbook for {security}")

        # Start market maker
        self.market_maker = MarketMaker(
            self.market,
            Config.MARKET_MAKER_ID,
            self.securities
        )
        self.market.deposit(self.market_maker.maker_id, 'cash', Decimal(Config.MARKET_MAKER_CASH))

        # Deposit securities for market maker
        for security in self.securities:
            self.market.deposit(self.market_maker.maker_id, security, Decimal(Config.MARKET_MAKER_SECURITIES))
            logger.info(f"Deposited {Config.MARKET_MAKER_SECURITIES} {security} for market maker")

        self.market_maker.start()
        
        # Start market rush simulator with higher throughput
        # Use first security as the primary for simulation, or the default
        primary_security = self.securities[0] if self.securities else Config.DEFAULT_SECURITY
        self.rush_simulator = MarketRushSimulator(
            market=self.market,
            security_id=primary_security,
            num_participants=Config.NUM_PARTICIPANTS,
            enable_simulated_sellers=Config.ENABLE_SIMULATED_SELLERS
        )
        logger.info(f"Market simulator using primary security: {primary_security}")
        # Configure simulator parameters for maximum throughput
        self.rush_simulator.batch_size = 500  # Increased from 200
        self.rush_simulator.worker_threads = 400  # Increased from 200
        self.rush_simulator.batch_delay = 0.0001  # Minimal delay for maximum throughput
        self.rush_simulator.order_size_min = 5  # Smaller orders for faster processing
        self.rush_simulator.order_size_max = 50  # Smaller max order for faster matching

        # Start the simulator
        self.rush_simulator.start_rush(duration_seconds=Config.SIMULATION_DURATION)
        
        # Start visualization server
        self.visualization.start_server(port=Config.PORT)
        
        # Start visualization updates in a separate thread
        import threading
        self.vis_thread = threading.Thread(target=self.visualization.run_visualization)
        self.vis_thread.daemon = True
        self.vis_thread.start()
        logger.info("Started visualization updates thread")
        
        # Start monitoring loop
        self.start_monitoring()

    def _get_securities_list(self):
        """Get list of securities from environment or config."""
        # Check for SECURITIES environment variable (comma-separated list)
        securities_env = os.getenv('SECURITIES', '')

        if securities_env:
            # Parse comma-separated list
            securities = [s.strip() for s in securities_env.split(',') if s.strip()]
            if securities:
                return securities

        # Check for individual SECURITY_N environment variables (up to 10)
        securities = []
        for i in range(1, 11):
            security = os.getenv(f'SECURITY_{i}')
            if security:
                securities.append(security)

        if securities:
            return securities

        # Fall back to config default
        return [Config.DEFAULT_SECURITY]

    def setup_signal_handlers(self):
        """Set up handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutting down market server...")
        
        # Stop the monitoring loop
        self.is_running = False
        
        # Stop market components in order
        if hasattr(self, 'rush_simulator'):
            logger.info("Stopping rush simulator...")
            self.rush_simulator.stop_rush()
            self.rush_simulator.is_running = False
        
        if hasattr(self, 'market_maker'):
            logger.info("Stopping market maker...")
            self.market_maker.stop()
        
        if hasattr(self, 'visualization'):
            logger.info("Stopping visualization server...")
            self.visualization.socketio.stop()
            
        logger.info("Shutdown complete")
        sys.exit(0)

    def start_monitoring(self):
        """Monitor system performance"""
        start_time = time.time()
        last_orders = 0
        last_trades = 0
        
        while self.is_running:
            try:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Get current stats
                stats = self.rush_simulator.get_stats()
                current_orders = stats['total_orders']
                current_trades = self.market.get_trade_count()
                
                # Calculate rates
                orders_per_sec = (current_orders - last_orders) / Config.STATS_UPDATE_INTERVAL
                trades_per_sec = (current_trades - last_trades) / Config.STATS_UPDATE_INTERVAL
                memory_mb = get_memory_usage()
                
                # Log metrics
                logger.info("\nPerformance Metrics:")
                logger.info(f"Memory Usage: {memory_mb:.2f} MB")
                logger.info(f"Order Throughput: {orders_per_sec:.2f} orders/sec")
                logger.info(f"Trade Throughput: {trades_per_sec:.2f} trades/sec")
                
                logger.info("\nRush Statistics:")
                logger.info(f"Total Orders: {stats['total_orders']}")
                logger.info(f"Successful Orders: {stats['successful_orders']}")
                logger.info(f"Failed Orders: {stats['failed_orders']}")
                logger.info(f"Current Price: {stats['current_price']}")
                logger.info(f"Price Movement: {stats['price_movement_percent']:.2f}%")
                logger.info(f"Volume: {stats['volume']}")
                logger.info(f"Total Trades: {current_trades}")
                
                # Update last values
                last_orders = current_orders
                last_trades = current_trades
                
                time.sleep(Config.STATS_UPDATE_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")

if __name__ == "__main__":
    server = MarketServer()
