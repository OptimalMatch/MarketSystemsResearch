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

from Exchange import Market
from MarketMaker import MarketMaker
from MarketRushSimulator import MarketRushSimulator
from Visualization import Visualization
from config import Config
from logger import setup_logger

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
        
        # Initialize visualization
        self.visualization = Visualization(self.market)
        self.market.visualization = self.visualization
        
        # Start market maker
        self.market_maker = MarketMaker(
            self.market, 
            Config.MARKET_MAKER_ID, 
            [Config.DEFAULT_SECURITY]
        )
        self.market.deposit(self.market_maker.maker_id, 'cash', Decimal(Config.MARKET_MAKER_CASH))
        self.market.deposit(self.market_maker.maker_id, Config.DEFAULT_SECURITY, Decimal(Config.MARKET_MAKER_SECURITIES))
        self.market_maker.start()
        
        # Start market rush simulator with higher throughput
        self.rush_simulator = MarketRushSimulator(
            market=self.market,
            security_id=Config.DEFAULT_SECURITY,
            num_participants=Config.NUM_PARTICIPANTS,
            enable_simulated_sellers=Config.ENABLE_SIMULATED_SELLERS
        )
        # Configure simulator parameters for high throughput
        self.rush_simulator.batch_size = 200
        self.rush_simulator.worker_threads = 200
        self.rush_simulator.batch_delay = 0.001
        
        # Start the simulator
        self.rush_simulator.start_rush(duration_seconds=Config.SIMULATION_DURATION)
        
        # Start visualization server
        self.visualization.start_server(port=Config.PORT)
        
        # Start monitoring loop
        self.start_monitoring()

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
