from gevent import monkey
monkey.patch_all()  # Apply gevent monkey patching globally

import time
from decimal import Decimal
import signal
import sys

from Exchange import Market
from MarketMaker import MarketMaker
from MarketRushSimulator import MarketRushSimulator, get_memory_usage
from Visualization import Visualization
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)

class MarketServer:
    def __init__(self):
        self.market = Market()
        self.visualization = None
        self.market_maker = None
        self.rush_simulator = None
        self.running = False
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Set up handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Received shutdown signal. Cleaning up...")
        self.cleanup()
        sys.exit(0)
    
    def initialize(self):
        """Initialize market components."""
        try:
            # Create orderbook
            self.market.create_orderbook(Config.DEFAULT_SECURITY)
            
            # Initialize market maker if enabled
            if Config.ENABLE_MARKET_MAKER:
                self.setup_market_maker()
            
            # Initialize rush simulator
            self.rush_simulator = MarketRushSimulator(
                self.market,
                Config.DEFAULT_SECURITY,
                num_participants=Config.NUM_PARTICIPANTS,
                enable_simulated_sellers=Config.ENABLE_SIMULATED_SELLERS
            )
            
            # Initialize visualization
            self.visualization = Visualization(self.market)
            self.market.set_visualization(self.visualization)
            
            logger.info("Market components initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize market components: {str(e)}")
            return False
    
    def setup_market_maker(self):
        """Set up the market maker."""
        maker_id = Config.MARKET_MAKER_ID
        self.market.deposit(maker_id, 'cash', Decimal(Config.MARKET_MAKER_CASH))
        self.market.deposit(maker_id, Config.DEFAULT_SECURITY, Decimal(Config.MARKET_MAKER_SECURITIES))
        self.market_maker = MarketMaker(self.market, maker_id, [Config.DEFAULT_SECURITY])
    
    def start(self):
        """Start the market server and simulation."""
        if not self.initialize():
            logger.error("Failed to start market server")
            return
        
        self.running = True
        
        try:
            # Start visualization server
            self.visualization.start_server(port=Config.PORT)
            logger.info(f"Visualization server started on port {Config.PORT}")
            
            # Start market components
            if self.market_maker:
                self.market_maker.start()
                logger.info("Market maker started")
            
            self.rush_simulator.start_rush(duration_seconds=Config.SIMULATION_DURATION)
            logger.info("Rush simulator started")
            
            # Main monitoring loop
            self.monitor_performance()
            
        except Exception as e:
            logger.error(f"Error during market operation: {str(e)}")
        finally:
            self.cleanup()
    
    def monitor_performance(self):
        """Monitor and log performance metrics."""
        start_time = time.time()
        
        while self.running and self.rush_simulator.is_running:
            try:
                elapsed_time = time.time() - start_time
                
                # Get simulator stats
                stats = self.rush_simulator.get_stats()
                trades_executed = self.market.get_trade_count()
                
                # Calculate throughput
                order_throughput = stats['total_orders'] / elapsed_time if elapsed_time > 0 else 0
                trade_throughput = trades_executed / elapsed_time if elapsed_time > 0 else 0
                
                # Log performance metrics
                self.log_performance_metrics(stats, trades_executed, order_throughput, trade_throughput)
                
                # Update visualization
                self.visualization.update_orderbook()
                self.visualization.update_candlestick()
                
                time.sleep(Config.STATS_UPDATE_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
    
    def log_performance_metrics(self, stats, trades_executed, order_throughput, trade_throughput):
        """Log various performance metrics."""
        memory_usage = get_memory_usage()
        
        logger.info("\nRush Statistics:")
        logger.info(f"Total Orders: {stats['total_orders']}")
        logger.info(f"Successful Orders: {stats['successful_orders']}")
        logger.info(f"Failed Orders: {stats['failed_orders']}")
        logger.info(f"Current Price: {stats['current_price']}")
        logger.info(f"Price Movement: {stats['price_movement_percent']:.2f}%")
        logger.info(f"Volume: {stats['volume']}")
        logger.info(f"Total Trades: {trades_executed}")
        
        logger.info("\nPerformance Metrics:")
        logger.info(f"Memory Usage: {memory_usage:.2f} MB")
        logger.info(f"Order Throughput: {order_throughput:.2f} orders/sec")
        logger.info(f"Trade Throughput: {trade_throughput:.2f} trades/sec")
    
    def cleanup(self):
        """Clean up resources and stop components."""
        self.running = False
        
        if self.rush_simulator:
            self.rush_simulator.stop_rush()
            logger.info("Rush simulator stopped")
        
        if self.market_maker:
            self.market_maker.stop()
            logger.info("Market maker stopped")
        
        if self.visualization:
            self.visualization.socketio.stop()
            logger.info("Visualization server stopped")
        
        self.market.finalize_trades()
        logger.info("Market finalized")

if __name__ == "__main__":
    server = MarketServer()
    server.start()
