#!/usr/bin/env python3
"""
Trade Log Replayer - Stream historical trade logs to the frontend visualization

This script reads a trade log CSV file and streams the data to the frontend
visualization at a configurable replay speed. This allows replaying and analyzing
historical trade data through the existing visualization interface.
"""

import os
import csv
import time
import argparse
from datetime import datetime
import pandas as pd
from decimal import Decimal
import threading
import random
from pathlib import Path
from flask import send_from_directory, Flask, render_template, send_file

from flask_socketio import SocketIO
from flask_cors import CORS

from config import Config
from logger import setup_logger

logger = setup_logger(__name__)

class TradeLogReplayer:
    """Replay trade logs to the visualization frontend"""
    
    def __init__(self, csv_file, speed_factor=1.0):
        """
        Initialize the Trade Log Replayer
        
        Args:
            csv_file (str): Path to the CSV trade log file
            speed_factor (float): Replay speed multiplier (1.0 = real-time)
        """
        self.csv_file = Path(csv_file)
        self.speed_factor = speed_factor
        self.is_running = False
        self.is_paused = False
        self.trades = []
        self.current_position = 0
        
        # Set up template directory (absolute path)
        self.template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        
        # Initialize Flask app and socketio
        self.app = Flask(__name__, template_folder=self.template_dir, static_folder=self.template_dir)
        CORS(self.app)
        self.socketio = SocketIO(
            self.app, 
            cors_allowed_origins="*",
            async_mode='threading',  # Changed from eventlet to threading for better debug support
            ping_timeout=30,
            ping_interval=5,
            max_http_buffer_size=1e8,
            logger=True,  # Enable socketio logger
            engineio_logger=True  # Enable engineio logger
        )
        
        # Configure Flask routes
        self._setup_routes()
        
        # Statistics and visualization data
        self.candlestick_data = []
        self.orderbook_data = {"bids": [], "asks": []}
        self.last_update_time = time.time()
        self.update_interval = 0.1  # seconds
        
        # OHLC aggregation by time interval
        self.current_interval = None
        self.current_candle = None
        self.candlestick_interval = Config.CANDLESTICK_INTERVAL
        
        # Load the CSV file
        self._load_trades()
        
    def _setup_routes(self):
        """Set up Flask routes with error handling"""
        
        @self.app.route('/')
        def index():
            """Serve the visualization page"""
            try:
                # Use the replay_index.html template instead of index.html
                return render_template('replay_index.html')
            except Exception as e:
                logger.error(f"Error rendering template: {str(e)}")
                return "Error loading page", 500
                
        @self.app.route('/static/<path:filename>')
        def serve_static(filename):
            """Serve static files from templates directory."""
            try:
                return send_from_directory('templates', filename)
            except Exception as e:
                logger.error(f"Error serving static file {filename}: {str(e)}")
                return "File not found", 404
                
        @self.app.route('/static/js/<path:filename>')
        def serve_js(filename):
            """Serve JavaScript files from templates directory."""
            try:
                return send_from_directory('templates', filename)
            except Exception as e:
                logger.error(f"Error serving static file {filename}: {str(e)}")
                return "File not found", 404
                
        @self.socketio.on("connect")
        def on_connect():
            """Send initial data to the client when connected"""
            try:
                logger.info("Client connected to replay server")
                
                # Send initial data to client
                logger.info(f"Sending initial orderbook data: {self.orderbook_data}")
                self.socketio.emit("orderbook", self.orderbook_data)
                
                # Send candlestick data using both event names for compatibility
                logger.info(f"Sending initial candlestick data: {self.candlestick_data}")
                self.socketio.emit("candlestick", self.candlestick_data)
                self.socketio.emit("candlestick_update", {
                    'full_refresh': True,
                    'candles': self.candlestick_data
                })
                
                # Also send depth of market data
                dom_data = {
                    "bids": [[bid["price"], bid["size"]] for bid in self.orderbook_data["bids"]],
                    "asks": [[ask["price"], ask["size"]] for ask in self.orderbook_data["asks"]],
                    "security_id": "SAMPLE"
                }
                self.socketio.emit("depth_of_market", dom_data)
                
                # Send initial replay status
                self.socketio.emit("replay_status", {
                    "running": self.is_running,
                    "paused": self.is_paused,
                    "position": self.current_position,
                    "total": len(self.trades),
                    "speed": self.speed_factor,
                    "filename": os.path.basename(self.csv_file)
                })
            except Exception as e:
                logger.error(f"Error during client connection: {str(e)}")
                
        @self.socketio.on("replay_command")
        def on_replay_command(command):
            """Handle replay commands from the client"""
            try:
                logger.info(f"Received replay command: {command}")
                
                if command.get("action") == "play":
                    if not self.is_running:
                        # If stopped, start from beginning
                        self.is_running = True
                        # Start replay thread if it's not running
                        if not hasattr(self, 'replay_thread') or not self.replay_thread.is_alive():
                            self.replay_thread = threading.Thread(target=self.run_replay)
                            self.replay_thread.daemon = True
                            self.replay_thread.start()
                            logger.info("Started new replay thread")
                    self.resume()  # Resume if paused
                    
                elif command.get("action") == "pause":
                    self.pause()
                    
                elif command.get("action") == "stop":
                    self.stop()
                    
                elif command.get("action") == "set_speed":
                    self.speed_factor = float(command.get("speed", 1.0))
                    logger.info(f"Speed set to {self.speed_factor}x")
                    
                elif command.get("action") == "seek":
                    position = int(command.get("position", 0))
                    self.seek(position)
                    
                # Send updated status immediately
                self.socketio.emit("replay_status", {
                    "running": self.is_running,
                    "paused": self.is_paused,
                    "position": self.current_position,
                    "total": len(self.trades),
                    "speed": self.speed_factor,
                    "filename": os.path.basename(self.csv_file)
                })
                
            except Exception as e:
                logger.error(f"Error handling replay command: {str(e)}")
    
    def _load_trades(self):
        """Load trades from the CSV file"""
        try:
            logger.info(f"Loading trades from {self.csv_file}")
            
            if not self.csv_file.exists():
                logger.error(f"Trade log file not found: {self.csv_file}")
                return
                
            # Determine file size for batch processing
            file_size = os.path.getsize(self.csv_file)
            logger.info(f"Trade log file size: {file_size/1024/1024:.2f} MB")
            
            # For very large files, we'll use pandas with chunking
            large_file = file_size > 50 * 1024 * 1024  # 50MB threshold
            
            if large_file:
                logger.info("Using optimized loading for large file")
                # Use pandas to read the CSV in chunks
                chunk_size = 100000  # Adjust based on memory constraints
                
                # Read the header separately
                with open(self.csv_file, 'r') as file:
                    header = next(csv.reader(file))
                
                # Check if the file has the expected columns
                expected_columns = ["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"]
                if not all(col in header for col in expected_columns):
                    logger.error(f"CSV file missing expected columns. Found: {header}")
                    return
                
                # Process in chunks to avoid memory issues
                chunks = pd.read_csv(
                    self.csv_file, 
                    chunksize=chunk_size,
                    dtype={
                        'Trade ID': str,
                        'Security ID': str, 
                        'Buyer ID': str,
                        'Seller ID': str,
                        'Price': float,
                        'Size': float,
                        'Timestamp': str
                    }
                )
                
                # Only load a subset of trades initially for better performance
                max_initial_trades = 10000
                trade_count = 0
                
                for chunk in chunks:
                    for _, row in chunk.iterrows():
                        trade = {
                            "id": row["Trade ID"],
                            "security_id": row["Security ID"],
                            "buyer_id": row["Buyer ID"],
                            "seller_id": row["Seller ID"],
                            "price": float(row["Price"]),
                            "size": float(row["Size"]),
                            "timestamp": row["Timestamp"]
                        }
                        self.trades.append(trade)
                        
                        trade_count += 1
                        if trade_count >= max_initial_trades:
                            logger.info(f"Loaded initial {max_initial_trades} trades (limiting for performance)")
                            break
                    
                    if trade_count >= max_initial_trades:
                        break
                
                logger.info(f"Loaded {len(self.trades)} trades from log file (limited sample)")
                logger.info("NOTE: For large files, only a subset of trades is loaded for better performance")
                
            else:
                # For smaller files, use standard CSV reading
                with open(self.csv_file, 'r') as file:
                    reader = csv.reader(file)
                    header = next(reader)  # Skip header row
                    
                    # Check if the file has the expected columns
                    expected_columns = ["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"]
                    if not all(col in header for col in expected_columns):
                        logger.error(f"CSV file missing expected columns. Found: {header}")
                        return
                        
                    # Build index mapping for each column
                    col_map = {col: header.index(col) for col in expected_columns}
                    
                    # Read all trades
                    for row in reader:
                        if len(row) < len(col_map):
                            continue  # Skip incomplete rows
                            
                        trade = {
                            "id": row[col_map["Trade ID"]],
                            "security_id": row[col_map["Security ID"]],
                            "buyer_id": row[col_map["Buyer ID"]],
                            "seller_id": row[col_map["Seller ID"]],
                            "price": float(row[col_map["Price"]]),
                            "size": float(row[col_map["Size"]]),
                            "timestamp": row[col_map["Timestamp"]]
                        }
                        self.trades.append(trade)
                    
                logger.info(f"Loaded {len(self.trades)} trades from log file")
            
            # Sort trades by timestamp
            self.trades.sort(key=lambda x: x["timestamp"])
            
        except Exception as e:
            logger.error(f"Error loading trades: {str(e)}")
    
    def initialize_empty_data(self):
        """Initialize empty chart data for initial rendering"""
        # Create empty candles for the chart to initialize correctly
        self.candlestick_data = []
        
        # Create sample timestamp
        timestamp = int(time.time())
        
        # Create initial empty candle
        if len(self.trades) > 0:
            # Use first trade for reference price
            first_trade = self.trades[0]
            price = float(first_trade["price"])
            security_id = first_trade["security_id"]
            
            # Create a sample candle with data from first trade
            self.candlestick_data.append({
                'security_id': security_id,
                'time': timestamp,
                'open': price,
                'high': price,
                'low': price,
                'close': price
            })
        else:
            # If no trades, create a sample candle
            self.candlestick_data.append({
                'security_id': 'SAMPLE',
                'time': timestamp,
                'open': 100,
                'high': 100,
                'low': 100,
                'close': 100
            })
            
        # Create empty orderbook
        self.orderbook_data = {
            "bids": [{"price": 99, "size": 10}],
            "asks": [{"price": 101, "size": 10}]
        }
        
        # Log initialization
        logger.info("Initialized empty chart data for rendering")
    
    def update_candlestick(self, trade):
        """Update candlestick data with the trade"""
        try:
            # Get trade timestamp
            trade_time = int(time.time())
            try:
                # Try to parse the timestamp from the trade
                dt = datetime.fromisoformat(trade["timestamp"].replace('Z', '+00:00'))
                trade_time = int(dt.timestamp())
            except (ValueError, TypeError):
                pass
                
            # Calculate the interval timestamp (e.g., for 5-second candles)
            interval_time = trade_time // self.candlestick_interval * self.candlestick_interval
            trade_price = float(trade["price"])
            
            # Debug log
            logger.debug(f"Updating candlestick for time {interval_time}, price {trade_price}")
            
            # Check if we need to create a new candle or update existing one
            new_candle = False
            if not self.candlestick_data or self.candlestick_data[-1]['time'] != interval_time:
                # Create a new candle
                new_candle = True
                self.candlestick_data.append({
                    'security_id': trade["security_id"],
                    'time': interval_time,
                    'open': trade_price,
                    'high': trade_price,
                    'low': trade_price,
                    'close': trade_price
                })
                # Keep only last 100 candles to prevent memory bloat
                if len(self.candlestick_data) > 100:
                    self.candlestick_data = self.candlestick_data[-100:]
            else:
                # Update the last candle
                candle = self.candlestick_data[-1]
                candle['high'] = max(candle['high'], trade_price)
                candle['low'] = min(candle['low'], trade_price)
                candle['close'] = trade_price
                
            # Emit only the updated candle to reduce data transfer
            if new_candle:
                # For a new candle, send the last 5 candles for context
                candles_to_send = self.candlestick_data[-5:]
                logger.debug(f"Emitting new candle with {len(candles_to_send)} candles")
                self.socketio.emit("candlestick_update", {
                    'full_refresh': False,
                    'candles': candles_to_send
                })
            else:
                # For an updated candle, just send the last one
                logger.debug("Emitting updated candle")
                self.socketio.emit("candlestick_update", {
                    'full_refresh': False,
                    'candles': [self.candlestick_data[-1]]
                })
                
        except Exception as e:
            logger.error(f"Error updating candlestick: {str(e)}")
    
    def update_orderbook(self, trade):
        """Simulate orderbook updates based on trade data"""
        try:
            # Generate simulated order book data based on the trade
            # This is a simplified simulation for visualization purposes
            trade_price = float(trade["price"])
            trade_size = float(trade["size"])
            
            # Generate a realistic looking orderbook around the trade price
            spread = trade_price * 0.001  # 0.1% spread
            
            # Generate bid prices slightly below trade price
            bids = []
            for i in range(10):
                price = trade_price - spread * (i + 1)
                # Size gets smaller as price moves away from trade price
                size = trade_size * (0.8 ** (i + 1)) * (1 + random.random() * 0.5)
                bids.append({"price": round(price, 4), "size": round(size, 2)})
                
            # Generate ask prices slightly above trade price
            asks = []
            for i in range(10):
                price = trade_price + spread * (i + 1)
                # Size gets smaller as price moves away from trade price
                size = trade_size * (0.8 ** (i + 1)) * (1 + random.random() * 0.5)
                asks.append({"price": round(price, 4), "size": round(size, 2)})
                
            # Update orderbook data
            self.orderbook_data = {
                "bids": bids,
                "asks": asks
            }
            
            # Emit orderbook update
            self.socketio.emit("orderbook", self.orderbook_data)
            
            # Also emit DOM data
            dom_data = {
                "bids": [[bid["price"], bid["size"]] for bid in bids],
                "asks": [[ask["price"], ask["size"]] for ask in asks],
                "security_id": trade["security_id"]
            }
            self.socketio.emit("depth_of_market", dom_data)
            
        except Exception as e:
            logger.error(f"Error updating orderbook: {str(e)}")
    
    def emit_trade(self, trade):
        """Emit a trade to the frontend"""
        try:
            # Convert trade to the format expected by the frontend
            trade_data = {
                "id": trade["id"],
                "time": int(time.time()),
                "security_id": trade["security_id"],
                "price": float(trade["price"]),
                "size": float(trade["size"]),
                "buyer_id": trade["buyer_id"],
                "seller_id": trade["seller_id"]
            }
            
            # Try to parse the timestamp from the trade
            try:
                dt = datetime.fromisoformat(trade["timestamp"].replace('Z', '+00:00'))
                trade_data["time"] = int(dt.timestamp())
            except (ValueError, TypeError):
                pass
            
            # Emit trade to frontend
            logger.debug(f"Emitting trade: {trade_data}")
            self.socketio.emit("trade", trade_data)
            
            # Also emit as aggregated trade for volume chart
            aggregated_trade = {
                "time": trade_data["time"],
                "security_id": trade_data["security_id"],
                "total_volume": trade_data["size"],
                "average_price": trade_data["price"],
                "count": 1,
                "incremental": True
            }
            logger.debug(f"Emitting aggregated trade: {aggregated_trade}")
            self.socketio.emit("aggregated_trade", aggregated_trade)
            
        except Exception as e:
            logger.error(f"Error emitting trade: {str(e)}")
    
    def run_replay(self):
        """Main replay loop"""
        logger.info("Starting trade log replay")
        self.is_running = True
        
        # First send full refresh of data
        if len(self.trades) > 0:
            logger.info("Sending initial data refresh...")
            # Force a full candlestick refresh
            if len(self.candlestick_data) > 0:
                self.socketio.emit("candlestick", self.candlestick_data)
                # Also send in the format for incremental updates
                self.socketio.emit("candlestick_update", {
                    'full_refresh': True,
                    'candles': self.candlestick_data
                })
                
            # Force an orderbook refresh
            self.update_orderbook(self.trades[0])
            # Give time for initial data to be sent
            time.sleep(0.5)
        
        try:
            # Process trades in batches for efficiency
            batch_size = 10  # Number of trades to process in each batch
            log_frequency = 50  # Log only every N trades
            
            while self.is_running and self.current_position < len(self.trades):
                if not self.is_paused:
                    # Process a batch of trades
                    end_position = min(self.current_position + batch_size, len(self.trades))
                    batch = self.trades[self.current_position:end_position]
                    
                    for i, trade in enumerate(batch):
                        # Only log occasionally to reduce spam
                        if (self.current_position + i) % log_frequency == 0:
                            logger.info(f"Processing trade {self.current_position + i}/{len(self.trades)}")
                        
                        # Process the trade
                        self.emit_trade(trade)
                        self.update_candlestick(trade)
                        # Only update orderbook once per batch to reduce overhead
                        if i == len(batch) - 1:
                            self.update_orderbook(trade)
                    
                    # Update position after batch
                    self.current_position = end_position
                    
                    # Update replay status
                    self.socketio.emit("replay_status", {
                        "running": self.is_running,
                        "paused": self.is_paused,
                        "position": self.current_position,
                        "total": len(self.trades),
                        "speed": self.speed_factor,
                        "filename": os.path.basename(self.csv_file)
                    })
                    
                    # Calculate batch delay based on speed factor
                    # Adjust for smoother playback with large files
                    delay = (0.1 * batch_size) / self.speed_factor
                    time.sleep(delay)
                else:
                    # While paused, just sleep a bit
                    time.sleep(0.1)
                    
            logger.info("Replay complete")
            self.is_running = False
            self.socketio.emit("replay_status", {
                "running": False,
                "paused": False,
                "position": self.current_position,
                "total": len(self.trades),
                "speed": self.speed_factor,
                "filename": os.path.basename(self.csv_file),
                "complete": True
            })
            
        except Exception as e:
            logger.error(f"Error in replay loop: {str(e)}")
            self.is_running = False
    
    def start(self, port=None):
        """Start the replay server and begin replay"""
        try:
            # Initialize with empty data for charts
            self.initialize_empty_data()
            
            # Set up the background task for replay
            @self.socketio.on('connect')
            def start_replay_after_connect():
                if not hasattr(self, '_replay_started') or not self._replay_started:
                    logger.info("Starting replay thread after client connection")
                    self._replay_started = True
                    self.socketio.start_background_task(self.run_replay)
            
            # Start web server
            port = port or Config.PORT
            logger.info(f"Starting replay server on port {port}")
            
            # Run the server (this blocks)
            self.app.config['DEBUG'] = Config.DEBUG
            self.socketio.run(
                self.app,
                host=Config.HOST,
                port=port,
                debug=Config.DEBUG,
                use_reloader=False
            )
            
        except Exception as e:
            logger.error(f"Error starting replay server: {str(e)}")
    
    def pause(self):
        """Pause the replay"""
        self.is_paused = True
        logger.info("Replay paused")
        # Force status update
        self.socketio.emit("replay_status", {
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file)
        })
    
    def resume(self):
        """Resume the replay"""
        self.is_paused = False
        logger.info("Replay resumed")
        # Force status update
        self.socketio.emit("replay_status", {
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file)
        })
    
    def stop(self):
        """Stop the replay"""
        self.is_running = False
        logger.info("Replay stopped")
        # Force status update
        self.socketio.emit("replay_status", {
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file)
        })
    
    def seek(self, position):
        """Seek to a specific position in the replay"""
        if 0 <= position < len(self.trades):
            self.current_position = position
            logger.info(f"Seeking to position {position}")
        else:
            logger.error(f"Invalid seek position: {position}")


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Replay trade logs to visualization frontend")
    parser.add_argument("csv_file", help="Path to the CSV trade log file")
    parser.add_argument("-s", "--speed", type=float, default=1.0,
                       help="Replay speed multiplier (1.0 = real-time)")
    parser.add_argument("-p", "--port", type=int, default=Config.PORT,
                       help=f"Web server port (default: {Config.PORT})")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    # Create and start the replayer
    replayer = TradeLogReplayer(args.csv_file, args.speed)
    
    # Create replay template from index.html
    try:
        # First check if we can modify the template
        template_path = Path("templates/index.html")
        replay_template_path = Path("templates/replay_index.html")
        
        if template_path.exists():
            content = template_path.read_text()
            
            # Create replay controls HTML
            replay_controls = """
<div id="replay-controls" style="padding: 10px; background-color: #333; color: white; margin-bottom: 10px;">
    <h3>Trade Log Replay</h3>
    <div style="display: flex; align-items: center;">
        <button id="play-btn" class="control-btn">Play</button>
        <button id="pause-btn" class="control-btn">Pause</button>
        <button id="stop-btn" class="control-btn">Stop</button>
        <div style="margin-left: 20px;">
            <label for="speed-slider">Speed: <span id="speed-value">1x</span></label>
            <input type="range" id="speed-slider" min="0.1" max="10" step="0.1" value="1">
        </div>
        <div style="margin-left: 20px; flex-grow: 1;">
            <label for="position-slider">Position: <span id="position-value">0/0</span></label>
            <input type="range" id="position-slider" min="0" max="100" value="0" style="width: 100%;">
        </div>
        <div style="margin-left: 20px;">
            <span id="filename">No file loaded</span>
        </div>
    </div>
</div>

<style>
    .control-btn {
        padding: 5px 15px;
        margin-right: 5px;
        background-color: #4CAF50;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
    }
    .control-btn:hover {
        background-color: #45a049;
    }
</style>
"""

            # Replay script for socket events
            replay_script = """
// Replay controls
const playBtn = document.getElementById('play-btn');
const pauseBtn = document.getElementById('pause-btn');
const stopBtn = document.getElementById('stop-btn');
const speedSlider = document.getElementById('speed-slider');
const speedValue = document.getElementById('speed-value');
const positionSlider = document.getElementById('position-slider');
const positionValue = document.getElementById('position-value');
const filename = document.getElementById('filename');

// Event listeners
playBtn.addEventListener('click', () => {
    socket.emit('replay_command', { action: 'play' });
});

pauseBtn.addEventListener('click', () => {
    socket.emit('replay_command', { action: 'pause' });
});

stopBtn.addEventListener('click', () => {
    socket.emit('replay_command', { action: 'stop' });
});

speedSlider.addEventListener('input', () => {
    const speed = parseFloat(speedSlider.value);
    speedValue.textContent = speed.toFixed(1) + 'x';
    socket.emit('replay_command', { action: 'set_speed', speed: speed });
});

positionSlider.addEventListener('change', () => {
    const position = parseInt(positionSlider.value);
    socket.emit('replay_command', { action: 'seek', position: position });
});

// Handle replay status updates
socket.on('replay_status', (status) => {
    // Update UI
    playBtn.disabled = status.running && !status.paused;
    pauseBtn.disabled = !status.running || status.paused;
    stopBtn.disabled = !status.running;
    
    // Update position slider
    if (status.total > 0) {
        positionSlider.max = status.total;
        positionSlider.value = status.position;
        positionValue.textContent = `${status.position}/${status.total}`;
    }
    
    // Update speed
    speedSlider.value = status.speed;
    speedValue.textContent = status.speed.toFixed(1) + 'x';
    
    // Update filename
    if (status.filename) {
        filename.textContent = status.filename;
    }
});
"""

            # Find body opening tag for insertion
            body_pos = content.find('<body>')
            if body_pos > 0:
                # Insert controls after body opening tag
                modified_content = content[:body_pos + 7] + '\n    ' + replay_controls + content[body_pos + 7:]
                
                # Find the end of the last script tag
                script_pos = modified_content.rfind('</script>')
                if script_pos > 0:
                    # Insert replay script before the script closing tag
                    modified_content = modified_content[:script_pos] + replay_script + '\n    ' + modified_content[script_pos:]
                    
                    # Write to replay_index.html
                    replay_template_path.write_text(modified_content)
                    logger.info(f"Created replay template at {replay_template_path}")
                else:
                    logger.error("Could not find script tag in template")
            else:
                logger.error("Could not find body tag in template")
        else:
            logger.error(f"Template file not found: {template_path}")
            
    except Exception as e:
        logger.error(f"Error creating replay template: {str(e)}")
    
    # Start the replayer
    replayer.start(args.port)
