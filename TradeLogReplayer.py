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
    """Replay trade log from CSV file"""
    
    def __init__(self, csv_file, template_dir=None):
        """Initialize the replayer"""
        # Setup the CSV file path
        self.csv_file = Path(csv_file)
        
        # Set the template directory
        self.template_dir = template_dir or "templates"
        
        # Initialize replay state
        self.trades = []
        self.is_running = False
        self.is_paused = False
        self.current_position = 0
        self.speed_factor = 1.0
        self.orderbook_data = {"bids": [], "asks": []}
        self.candlestick_data = []
        self.candlestick_interval = 60  # 1 minute candles by default
        
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
            logger=False,  # Disable verbose socketio logging
            engineio_logger=False  # Disable verbose engineio logging
        )
        
        # Configure Flask routes
        self._setup_routes()
        self._setup_socket_handlers()  # Make sure this is called
        
        # Initialize empty data to avoid nulls
        self.initialize_empty_data()
        
        # Set file loaded flag
        self.file_loaded = False
        
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
            logger.info(f"Received replay command: {command}")
            
            try:
                # Handle different command actions
                if command.get("action") == "play":
                    # Use the play method which handles both initial play and resume
                    self.play()
                    
                elif command.get("action") == "pause":
                    self.pause()
                    
                elif command.get("action") == "stop":
                    self.stop()
                    
                elif command.get("action") == "set_speed":
                    self.set_speed(command.get("speed", 1.0))
                    
                elif command.get("action") == "seek" or command.get("action") == "set_position":
                    # Support both 'seek' and 'set_position' actions for compatibility
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
    
    def _setup_socket_handlers(self):
        """Set up Socket.IO event handlers"""
        
        @self.socketio.on('connect')
        def on_connect():
            """Send initial data to the client when connected"""
            logger.info("Client connected")
            
            # Emit connection successful event
            self.socketio.emit('connection_status', {'status': 'connected'})
            
            # Send initial data
            if self.file_loaded:
                # If file is already loaded, send status
                logger.info("Sending loaded file info to newly connected client")
                filename = os.path.basename(self.csv_file)
                total_trades = len(self.trades)
                self.socketio.emit('file_info', {
                    'filename': filename,
                    'total_trades': total_trades,
                    'status': 'loaded'
                })
                
                # Also send position update
                self.socketio.emit('position_update', {
                    'position': self.current_position,
                    'total': len(self.trades)
                })
            else:
                # If file is still loading, send loading status
                logger.info("File still loading, sending status to new client")
                self.socketio.emit('loading_status', {
                    'status': 'loading',
                    'message': 'Loading trade data...',
                    'progress': 50  # Estimate progress
                })
        
        @self.socketio.on('replay_command')
        def on_replay_command(command):
            """Handle replay commands from client"""
            logger.info(f"Received replay command: {command}")
            
            try:
                # Handle different command actions
                if command.get("action") == "play":
                    self.play()
                elif command.get("action") == "pause":
                    self.pause()
                elif command.get("action") == "stop":
                    self.stop()
                elif command.get("action") == "set_position":
                    position = command.get("position", 0)
                    self.set_position(position)
                elif command.get("action") == "set_speed":
                    speed = command.get("speed", 1.0)
                    
                    # Add TURBO MODE for extremely high speeds
                    if float(speed) > 50000 and self.is_running:
                        # For TURBO speeds, use the fast-forward method
                        logger.info(f"TURBO MODE ACTIVATED: Speed {speed}x")
                        self.fast_forward(float(speed))
                    else:
                        # Normal speed setting
                        self.set_speed(speed)
                
                # Acknowledge command with format matching client expectations
                self.socketio.emit('command_status', {
                    'status': 'success',
                    'command': command.get('action', 'unknown')
                })
                
            except Exception as e:
                logger.error(f"Error handling replay command: {str(e)}")
                self.socketio.emit('command_status', {
                    'status': 'error',
                    'command': command.get('action', 'unknown'),
                    'error': str(e)
                })
        
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
    
    def _load_trades(self):
        """Load trades from the CSV file"""
        try:
            logger.info(f"Loading trades from {self.csv_file}")
            
            # Send initial loading status
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"Starting to load {self.csv_file.name}...",
                "progress": 5
            })
            
            if not self.csv_file.exists():
                error_msg = f"Trade log file not found: {self.csv_file}"
                logger.error(error_msg)
                self.socketio.emit("loading_status", {
                    "status": "error",
                    "message": error_msg,
                    "progress": 0
                })
                return
                
            # Determine file size for batch processing
            file_size = os.path.getsize(self.csv_file)
            total_size_mb = file_size/1024/1024
            logger.info(f"Trade log file size: {total_size_mb:.2f} MB")
            
            # Send file size info
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"File size: {total_size_mb:.2f} MB",
                "progress": 10
            })
            
            # For very large files, we'll use pandas with chunking
            large_file = file_size > 50 * 1024 * 1024  # 50MB threshold
            
            if large_file:
                logger.info("Using optimized loading for large file")
                # Use pandas to read the CSV in chunks
                chunk_size = 50000  # Use larger chunks for better performance
                
                # Emit loading message
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": f"Large file detected ({total_size_mb:.1f} MB). Using optimized loading...",
                    "progress": 15
                })
                
                # First pass to count rows (for progress calculation)
                total_rows = 0
                try:
                    # Quick method to estimate total rows
                    with open(self.csv_file, 'r') as f:
                        # Count header
                        header = next(csv.reader(f))
                        # Sample the first 1000 rows to get average line length
                        sample_size = 1000
                        sample_lines = []
                        for _ in range(min(sample_size, 10000)):
                            line = f.readline()
                            if not line:
                                break
                            sample_lines.append(line)
                        
                        # Calculate average line length
                        if sample_lines:
                            avg_line_length = sum(len(line) for line in sample_lines) / len(sample_lines)
                            # Estimate total rows based on file size and average line length
                            total_rows = int(file_size / avg_line_length)
                            logger.info(f"Estimated total rows: {total_rows}")
                    
                    self.socketio.emit("loading_status", {
                        "status": "loading",
                        "message": f"Estimated rows: {total_rows:,}",
                        "progress": 20
                    })
                except Exception as e:
                    logger.error(f"Error estimating rows: {str(e)}")
                    total_rows = 0
                
                # Read the header separately
                with open(self.csv_file, 'r') as file:
                    header = next(csv.reader(file))
                
                # Check if the file has the expected columns
                expected_columns = ["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"]
                if not all(col in header for col in expected_columns):
                    error_msg = f"CSV file missing expected columns. Found: {header}"
                    logger.error(error_msg)
                    
                    # Emit error event
                    self.socketio.emit("loading_status", {
                        "status": "error",
                        "message": error_msg,
                        "progress": 0
                    })
                    return
                
                # Dictionary to store trades grouped by timestamp
                trades_by_time = {}
                total_trades = 0
                rows_processed = 0
                
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
                
                # To count chunks for progress
                chunk_list = []
                try:
                    # Peek at first chunk to get count (hacky but effective)
                    for i, _ in enumerate(pd.read_csv(
                        self.csv_file, 
                        chunksize=chunk_size,
                        nrows=1  # Just peek to get chunks
                    )):
                        chunk_list.append(i)
                        if i > 100:  # Limit checking for very large files
                            break
                except:
                    pass
                
                total_chunks = len(chunk_list) or 1
                logger.info(f"Processing approximately {total_chunks} chunks")
                
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": f"Processing approximately {total_chunks} chunks...",
                    "progress": 25
                })
                
                # Process all chunks (no row limit)
                for chunk_idx, chunk in enumerate(chunks):
                    # Calculate progress (30% to 80% of loading process)
                    chunk_progress = chunk_idx / max(total_chunks, 1)
                    progress = 30 + (chunk_progress * 50)
                    
                    # Emit progress event
                    self.socketio.emit("loading_status", {
                        "status": "loading",
                        "message": f"Processing chunk {chunk_idx+1}/{total_chunks}: {len(chunk)} rows",
                        "progress": int(progress)
                    })
                    
                    logger.info(f"Processing chunk {chunk_idx+1} with {len(chunk)} rows")
                    
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
                        
                        # Group by timestamp
                        timestamp = trade["timestamp"]
                        if timestamp not in trades_by_time:
                            trades_by_time[timestamp] = []
                        trades_by_time[timestamp].append(trade)
                        total_trades += 1
                        rows_processed += 1
                
                # Convert grouped trades to time-ordered list
                logger.info(f"Sorting {len(trades_by_time)} unique timestamps...")
                
                # Emit sorting status
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": f"Sorting {len(trades_by_time):,} unique timestamps...",
                    "progress": 85
                })
                
                self.trades = []
                for timestamp in sorted(trades_by_time.keys()):
                    self.trades.extend(trades_by_time[timestamp])
                
                # Emit completion
                self.socketio.emit("loading_status", {
                    "status": "complete",
                    "message": f"Loaded {total_trades:,} trades from {len(trades_by_time):,} unique timestamps",
                    "progress": 100
                })
                
                logger.info(f"Loaded all {total_trades} trades from {len(trades_by_time)} unique timestamps")
            
            else:
                # For smaller files, use standard CSV reading but still group by timestamp
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": "Processing regular-sized file...",
                    "progress": 30
                })
                
                trades_by_time = {}
                
                with open(self.csv_file, 'r') as file:
                    reader = csv.reader(file)
                    header = next(reader)  # Skip header row
                    
                    # Check if the file has the expected columns
                    expected_columns = ["Trade ID", "Security ID", "Buyer ID", "Seller ID", "Price", "Size", "Timestamp"]
                    if not all(col in header for col in expected_columns):
                        error_msg = f"CSV file missing expected columns. Found: {header}"
                        logger.error(error_msg)
                        self.socketio.emit("loading_status", {
                            "status": "error",
                            "message": error_msg,
                            "progress": 0
                        })
                        return
                        
                    # Read all rows
                    total_rows = 0
                    for row in reader:
                        if len(row) < len(expected_columns):
                            continue  # Skip incomplete rows
                            
                        # Check if we have all required fields
                        try:
                            trade = {
                                "id": row[header.index("Trade ID")],
                                "security_id": row[header.index("Security ID")],
                                "buyer_id": row[header.index("Buyer ID")],
                                "seller_id": row[header.index("Seller ID")],
                                "price": float(row[header.index("Price")]),
                                "size": float(row[header.index("Size")]),
                                "timestamp": row[header.index("Timestamp")]
                            }
                            
                            # Update progress every 10,000 rows
                            total_rows += 1
                            if total_rows % 10000 == 0:
                                progress = min(70, 30 + (total_rows / 50000) * 40)  # Cap at 70%
                                self.socketio.emit("loading_status", {
                                    "status": "loading",
                                    "message": f"Processing row {total_rows:,}...",
                                    "progress": int(progress)
                                })
                                
                            # Group by timestamp
                            timestamp = trade["timestamp"]
                            if timestamp not in trades_by_time:
                                trades_by_time[timestamp] = []
                            trades_by_time[timestamp].append(trade)
                            
                        except (ValueError, IndexError) as e:
                            logger.warning(f"Error processing row: {e}")
                            continue
                            
                # Sort and flatten trades
                logger.info(f"Sorting {len(trades_by_time)} unique timestamps...")
                
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": f"Sorting {len(trades_by_time):,} unique timestamps...",
                    "progress": 80
                })
                
                # Create ordered list of trades
                self.trades = []
                for timestamp in sorted(trades_by_time.keys()):
                    self.trades.extend(trades_by_time[timestamp])
                    
                # Done loading
                logger.info(f"Loaded {len(self.trades):,} trades with {len(trades_by_time):,} unique timestamps")
                
                self.socketio.emit("loading_status", {
                    "status": "complete",
                    "message": f"Loaded {len(self.trades):,} trades successfully",
                    "progress": 100
                })
                
        except Exception as e:
            error_msg = f"Error loading trades: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            self.socketio.emit("loading_status", {
                "status": "error",
                "message": error_msg,
                "progress": 0
            })
    
    def _load_and_replay(self):
        """Load the trade file and start replay after loading"""
        try:
            # Load trades first
            self._load_trades()
            
            # Set the file loaded flag
            self.file_loaded = True
            
            # Send file info to the client
            filename = os.path.basename(self.csv_file)
            self.socketio.emit('file_info', {
                'filename': filename,
                'total_trades': len(self.trades),
                'status': 'loaded'
            })
            
            # Start the replay
            logger.info("File loaded, starting replay...")
            self.socketio.emit("loading_status", {
                "status": "complete",
                "message": "File loaded successfully. Ready to start replay.",
                "progress": 100
            })
            
            # Start replay after a short delay
            time.sleep(0.5)
            self.run_replay()
            
        except Exception as e:
            logger.error(f"Error in load and replay: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Notify the frontend
            self.socketio.emit("loading_status", {
                "status": "error",
                "message": f"Error loading file: {str(e)}",
                "progress": 0
            })

    def run_replay(self):
        """Main replay loop"""
        try:
            # Setup replay state
            self.is_running = True
            self.is_paused = False
            
            # Emit initial position and file info
            filename = os.path.basename(self.csv_file)
            self.socketio.emit('file_info', {
                'filename': filename,
                'total_trades': len(self.trades),
                'status': 'playing'
            })
            
            self.socketio.emit('position_update', {
                'position': self.current_position,
                'total': len(self.trades)
            })
            
            # Main replay loop
            last_time = time.time()
            last_update_time = last_time
            last_position = self.current_position
            
            while self.is_running:
                if not self.is_paused and self.current_position < len(self.trades):
                    current_time = time.time()
                    elapsed = current_time - last_time
                    
                    # EXTREME OPTIMIZATION FOR HIGH SPEEDS
                    # For speeds above 10,000x, we don't need to emit every trade
                    # Just jump ahead and only update UI periodically
                    if self.speed_factor > 10000:
                        # Calculate jump size based on speed
                        if self.speed_factor > 100000:
                            # For extreme speeds (>100K), jump massive chunks
                            jump_size = min(100000, len(self.trades) // 10)
                            jump_to = min(self.current_position + jump_size, len(self.trades) - 1)
                            
                            # Just update position and skip all visual updates
                            self.current_position = jump_to
                            
                            # Log occasional jumps
                            logger.info(f"EXTREME SPEED {self.speed_factor}x: Jumped {jump_size} positions to {self.current_position}")
                            
                            # Update UI occasionally
                            if current_time - last_update_time > 0.2:  # Update UI every 200ms
                                self.socketio.emit("position_update", {
                                    "position": self.current_position,
                                    "total": len(self.trades)
                                })
                                
                                # Also update the orderbook and charts with latest data
                                if self.current_position < len(self.trades):
                                    trade = self.trades[self.current_position]
                                    self.update_orderbook(trade)
                                    self.update_candlestick(trade)
                                
                                last_update_time = current_time
                            
                            # Sleep minimally to allow UI updates
                            time.sleep(0.001)
                        else:
                            # For very high speeds (10K-100K), process in big batches
                            trades_to_process = min(10000, len(self.trades) - self.current_position)
                            
                            # Process last trade for visualization
                            last_trade_idx = min(self.current_position + trades_to_process - 1, len(self.trades) - 1)
                            if last_trade_idx >= 0 and last_trade_idx < len(self.trades):
                                trade = self.trades[last_trade_idx]
                                self.emit_trade(trade)
                                self.update_orderbook(trade)
                                self.update_candlestick(trade)
                            
                            # Jump to the end position
                            self.current_position += trades_to_process
                            
                            # Log batch processing
                            logger.info(f"HIGH SPEED {self.speed_factor}x: Processed batch of {trades_to_process} trades")
                            
                            # Update UI
                            self.socketio.emit("position_update", {
                                "position": self.current_position,
                                "total": len(self.trades)
                            })
                            
                            # Minimal sleep
                            time.sleep(0.001)
                    else:
                        # NORMAL SPEED HANDLING (1x to 10,000x)
                        # Calculate how many trades to process based on speed
                        # At speed 1x, process 10 trades per second
                        # At speed 100x, process 1000 trades per second
                        trades_to_process = max(1, int(self.speed_factor * 10 * elapsed))
                        
                        # Cap trades_to_process to prevent processing too much at once
                        trades_to_process = min(trades_to_process, 1000, len(self.trades) - self.current_position)
                        
                        # Log speed effect at high speeds
                        if self.speed_factor > 100 and trades_to_process > 10 and current_time - last_update_time > 1.0:
                            processing_rate = (self.current_position - last_position) / (current_time - last_update_time)
                            logger.info(f"Speed {self.speed_factor}x: Processing at rate of {processing_rate:.1f} trades/sec")
                            last_position = self.current_position
                            last_update_time = current_time
                        
                        # Process multiple trades at once for high speeds
                        for i in range(trades_to_process):
                            if self.current_position >= len(self.trades):
                                break
                                
                            # Get current trade
                            trade = self.trades[self.current_position]
                            
                            # Only emit trade data for the last few trades in batch or if speed is low
                            # This reduces network traffic at high speeds
                            if i >= trades_to_process - 3 or self.speed_factor <= 10:
                                self.emit_trade(trade)
                            
                            # Always update orderbook and candlestick for the last trade in batch
                            if i == trades_to_process - 1:
                                self.update_orderbook(trade)
                                self.update_candlestick(trade)
                            
                            # Increment position
                            self.current_position += 1
                        
                        # Emit current position for progress tracking
                        if self.current_position % 10 == 0 or self.current_position == len(self.trades) - 1:
                            self.socketio.emit("position_update", {
                                "position": self.current_position,
                                "total": len(self.trades)
                            })
                        
                        # Reset timer after processing
                        last_time = time.time()
                        
                        # Add a small delay to prevent UI freezing
                        # Smaller delay at higher speeds
                        if self.speed_factor <= 1:
                            time.sleep(0.1)  # Normal speed
                        elif self.speed_factor <= 100:
                            time.sleep(0.01)  # Medium speed
                        else:
                            time.sleep(0.001)  # High speed
                    
                    # If we're at the end, pause
                    if self.current_position >= len(self.trades):
                        logger.info("Reached end of trade data")
                        self.is_paused = True
                        self.socketio.emit("replay_status", {"status": "paused", "reason": "end"})
                else:
                    # When paused, sleep to reduce CPU usage
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Error in replay loop: {str(e)}")
            logger.error(traceback.format_exc())
            self.stop()
    
    def set_speed(self, speed_factor):
        """Set the replay speed factor"""
        try:
            # Clamp speed to reasonable values
            speed_factor = max(0.1, min(100000, float(speed_factor)))
            self.speed_factor = speed_factor
            logger.info(f"Set replay speed to {speed_factor}x")
            
            # Notify clients
            self.socketio.emit("speed_update", {"speed": speed_factor})
            
            return True
        except Exception as e:
            logger.error(f"Error setting speed: {str(e)}")
            return False
    
    def start(self, port=None):
        """Start the replay server and begin replay"""
        try:
            # Initialize with empty data for charts
            self.initialize_empty_data()
            
            # Set up the background task for loading and replay
            @self.socketio.on('connect')
            def start_after_connect():
                if not hasattr(self, '_file_loading_started') or not self._file_loading_started:
                    logger.info("Starting file loading after client connection")
                    self._file_loading_started = True
                    self.socketio.start_background_task(self._load_and_replay)
            
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
        
        # Send full status update for UI consistency
        self.socketio.emit("replay_status", {
            "status": "paused",
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file) if self.csv_file else ""
        })
        
    def resume(self):
        """Resume the replay"""
        self.is_paused = False
        logger.info("Replay resumed")
        
        # Send full status update for UI consistency
        self.socketio.emit("replay_status", {
            "status": "playing",
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file) if self.csv_file else ""
        })
        
    def stop(self):
        """Stop the replay"""
        self.is_running = False
        self.is_paused = True
        self.current_position = 0
        logger.info("Replay stopped")
        
        # Send full status update for UI consistency
        self.socketio.emit("replay_status", {
            "status": "stopped",
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file) if self.csv_file else ""
        })
    
    def seek(self, position):
        """Seek to a specific position in the replay"""
        try:
            position = int(position)
            position = max(0, min(len(self.trades) - 1, position))
            self.current_position = position
            logger.info(f"Seek to position {position}/{len(self.trades)}")
            
            # If available, get trade at position for UI update
            if 0 <= position < len(self.trades):
                trade = self.trades[position]
                # Update visualizations without sending trade event
                self.update_orderbook(trade)
                self.update_candlestick(trade)
                
            # Notify of position update
            self.socketio.emit("position_update", {
                "position": position,
                "total": len(self.trades)
            })
            
            return True
        except Exception as e:
            logger.error(f"Error seeking: {str(e)}")
            return False

    def fast_forward(self, speed_factor):
        """Ultra-fast playback for extreme speeds"""
        try:
            if not self.is_running or self.is_paused or not self.file_loaded:
                return False
                
            logger.info(f"Fast-forward activated at {speed_factor}x speed")
            
            # Calculate position jump based on speed
            total_trades = len(self.trades)
            remaining_trades = total_trades - self.current_position
            
            # For extreme speeds, jump by large percentages
            if speed_factor > 500000:  # >500K speed
                # Jump to 95% completion or by 100,000 trades, whichever is more
                jump_size = max(int(remaining_trades * 0.95), min(100000, remaining_trades))
            elif speed_factor > 100000:  # >100K speed
                # Jump to 80% completion or by 50,000 trades, whichever is more
                jump_size = max(int(remaining_trades * 0.8), min(50000, remaining_trades))
            else:  # >50K speed
                # Jump to 50% completion or by 10,000 trades, whichever is more
                jump_size = max(int(remaining_trades * 0.5), min(10000, remaining_trades))
            
            # Calculate new position
            new_position = min(self.current_position + jump_size, total_trades - 1)
            
            logger.info(f"TURBO JUMP: From position {self.current_position} to {new_position} (jumped {new_position - self.current_position} trades)")
            
            # Update to the new position
            if new_position < total_trades:
                # Update position
                self.current_position = new_position
                
                # Process the trade at the new position for visualization
                trade = self.trades[new_position]
                self.emit_trade(trade)
                self.update_orderbook(trade)
                self.update_candlestick(trade)
                
                # Update position on UI
                self.socketio.emit("position_update", {
                    "position": self.current_position,
                    "total": total_trades
                })
                
                # Notify clients that we've jumped ahead
                self.socketio.emit("replay_status", {
                    "status": "playing",
                    "message": f"Fast-forwarded to trade {new_position}"
                })
            
            return True
            
        except Exception as e:
            logger.error(f"Error in fast-forward: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def play(self):
        """Play/resume the replay"""
        logger.info("Play/resume replay")
        # Resume from paused state or run if not running
        if not self.is_running:
            self.run_replay_async()
        else:
            self.resume()

    def run_replay_async(self):
        """Start the replay in a background thread"""
        logger.info("Starting replay in background thread")
        self.is_running = True
        self.is_paused = False
        
        # Create and start the replay thread
        if not hasattr(self, 'replay_thread') or not self.replay_thread.is_alive():
            self.replay_thread = threading.Thread(target=self.run_replay)
            self.replay_thread.daemon = True
            self.replay_thread.start()
            logger.info("Replay thread started")
        
        # Send status update to clients
        self.socketio.emit("replay_status", {
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "filename": os.path.basename(self.csv_file)
        })
        
        return True

class TimeGroupedTradeProcessor:
    """Process trades grouped by timestamp"""
    
    def __init__(self, trades, socketio):
        """Initialize the processor"""
        self.trades = trades
        self.socketio = socketio
        self.trades_by_time = self._group_trades()
        self.time_points = sorted(self.trades_by_time.keys())
        self.current_time_index = 0
        
    def _group_trades(self):
        """Group trades by timestamp"""
        trades_by_time = {}
        for trade in self.trades:
            timestamp = trade["timestamp"]
            if timestamp not in trades_by_time:
                trades_by_time[timestamp] = []
            trades_by_time[timestamp].append(trade)
        return trades_by_time
        
    def get_next_group(self):
        """Get the next group of trades by timestamp"""
        if self.current_time_index >= len(self.time_points):
            return None
            
        timestamp = self.time_points[self.current_time_index]
        trades = self.trades_by_time[timestamp]
        self.current_time_index += 1
        return trades
        
    def get_total_groups(self):
        """Get the total number of time groups"""
        return len(self.time_points)
        
    def get_current_position(self):
        """Get the current position in the time sequence"""
        return self.current_time_index
        
    def seek_to_time(self, time_index):
        """Seek to a specific time index"""
        if 0 <= time_index < len(self.time_points):
            self.current_time_index = time_index
            return True
        return False
        
    def reset(self):
        """Reset to beginning"""
        self.current_time_index = 0


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Trade Log Replayer")
    parser.add_argument("csv_file", help="Path to CSV trade log file")
    parser.add_argument("--speed", type=float, default=1.0, help="Initial replay speed factor")
    parser.add_argument("--port", type=int, default=None, help="Port for the web server")
    return parser.parse_args()


if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_args()
    
    # Create and start the replayer
    replayer = TradeLogReplayer(args.csv_file)
    
    # Create replay template from index.html
    try:
        # Check if replay_index.html exists, if not create it from index.html
        replay_template = Path("templates/replay_index.html")
        if not replay_template.exists():
            logger.info("Creating replay template from index.html")
            index_template = Path("templates/index.html")
            if index_template.exists():
                replay_content = index_template.read_text()
                replay_template.write_text(replay_content)
    except Exception as e:
        logger.error(f"Error creating replay template: {str(e)}")
    
    # Start the replayer
    replayer.start(args.port)
