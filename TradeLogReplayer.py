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
import math
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
        self.target_stop_position = None  # Target position for auto-stop
        self.orderbook_data = {"bids": [], "asks": []}
        self.candlestick_data = []
        self.candlestick_interval = 1  # 1 second candles by default
        
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
                    
                elif command.get("action") == "get_speed":
                    # Return the current speed to the client
                    self.socketio.emit("speed_update", {
                        "speed": self.speed_factor
                    })
                    
                elif command.get("action") == "seek" or command.get("action") == "set_position":
                    # Support both 'seek' and 'set_position' actions for compatibility
                    position = int(command.get("position", 0))
                    self.seek(position)
                    
                elif command.get("action") == "play_to_position":
                    # Play until a specific position and then stop
                    target_position = int(command.get("position", 0))
                    auto_start = command.get("auto_start", False)
                    self.play_to_position(target_position, auto_start=auto_start)
                    
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
                    "status": "loading",
                    "message": "Loading trade data...",
                    "progress": 50  # Estimate progress
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
        """Initialize empty data structures for charts and displays"""
        # Initialize candlestick data
        self.candlestick_data = []
        # Empty order book
        self.order_book = {'bids': [], 'asks': []}
        # Empty volume data
        self.volume_data = []
        # Empty trade counter
        self.trade_count = 0
        # Empty event list
        self.events = []
        # Empty marker list
        self.markers = []
        
        # Log initialization
        logger.info("Initialized empty chart data for rendering")
    
    def calculate_moving_averages(self):
        """Calculate moving averages from candlestick data"""
        if len(self.candlestick_data) < 5:
            return []  # Not enough data for moving averages
            
        try:
            # Get closing prices
            closing_prices = [candle['close'] for candle in self.candlestick_data]
            
            # Calculate different period moving averages
            sma_data = []
            periods = [5, 10, 20]  # Different SMA periods
            
            # Get the timestamps from candlesticks
            timestamps = [candle['time'] for candle in self.candlestick_data]
            
            for period in periods:
                if len(closing_prices) >= period:
                    # Calculate moving averages for this period
                    sma_values = []
                    
                    for i in range(len(closing_prices) - period + 1):
                        window = closing_prices[i:i+period]
                        sma = sum(window) / period
                        
                        # Only include SMA points that correspond to candlesticks
                        sma_values.append({
                            'time': timestamps[i + period - 1],
                            'value': sma
                        })
                    
                    # Add SMA series data
                    sma_data.append({
                        'period': period,
                        'values': sma_values
                    })
            
            logger.debug(f"Calculated {len(sma_data)} moving average series")
            return sma_data
        except Exception as e:
            logger.error(f"Error calculating moving averages: {str(e)}")
            return []
    
    def emit_candlestick_update(self, full_refresh=False):
        """Emit candlestick update to the client"""
        try:
            if not self.candlestick_data:
                logger.warning("No candlestick data to emit")
                # Send empty array to initialize chart properly
                self.socketio.emit("candlestick", [])
                return
                
            # Ensure timestamps are integers and validate all numeric fields
            formatted_candles = []
            current_time = int(time.time())
            
            for candle in self.candlestick_data:
                try:
                    formatted_candle = candle.copy()
                    
                    # Ensure time is a valid integer timestamp
                    if 'time' in formatted_candle:
                        try:
                            # Convert to integer if it's not already
                            if not isinstance(formatted_candle['time'], int):
                                formatted_candle['time'] = int(float(formatted_candle['time']))
                            
                            # Ensure time is positive and reasonable (not in the future)
                            if formatted_candle['time'] <= 0 or formatted_candle['time'] > current_time + 86400:
                                logger.warning(f"Invalid timestamp in candle: {formatted_candle['time']}")
                                formatted_candle['time'] = current_time
                        except (ValueError, TypeError):
                            # If conversion fails, use current timestamp
                            formatted_candle['time'] = current_time
                    else:
                        # If no time field, use current time
                        formatted_candle['time'] = current_time
                    
                    # Validate numeric fields and ensure they are floats
                    for field in ['open', 'high', 'low', 'close']:
                        if field in formatted_candle:
                            try:
                                value = float(formatted_candle[field])
                                if math.isnan(value) or math.isinf(value):
                                    # Replace invalid values with a default
                                    logger.warning(f"Invalid {field} value in candle: {formatted_candle}")
                                    formatted_candle[field] = 1.0  # Use 1.0 as a safe default
                                else:
                                    formatted_candle[field] = value
                            except (ValueError, TypeError):
                                formatted_candle[field] = 1.0  # Use 1.0 as a safe default
                        else:
                            # If field is missing, use a default value
                            formatted_candle[field] = 1.0
                    
                    # Ensure high is never less than low (which can cause chart errors)
                    # Also ensure open and close are within high-low range
                    high_value = max(formatted_candle['high'], formatted_candle['low'], 
                                    formatted_candle['open'], formatted_candle['close'])
                    low_value = min(formatted_candle['high'], formatted_candle['low'], 
                                   formatted_candle['open'], formatted_candle['close'])
                    
                    formatted_candle['high'] = high_value
                    formatted_candle['low'] = low_value
                    
                    # Add to formatted candles if it passes all validations
                    formatted_candles.append(formatted_candle)
                except Exception as e:
                    logger.error(f"Error formatting candle: {str(e)}")
                
            # Sort candles by time to ensure proper sequence
            formatted_candles.sort(key=lambda x: x['time'])
            
            # Skip if we don't have valid data after filtering
            if not formatted_candles:
                logger.warning("No valid candlestick data after formatting")
                # Send empty array to initialize chart properly
                self.socketio.emit("candlestick_update", {"full_refresh": True, "candles": []})
                return
                
            # Create update data - always send full data to avoid timeline conflicts
            update_data = {
                "full_refresh": True,
                "candles": formatted_candles
            }
            
            # Log the first and last candle for debugging
            if formatted_candles:
                logger.debug(f"First candle: {formatted_candles[0]}")
                logger.debug(f"Last candle: {formatted_candles[-1]}")
            
            # Emit update
            logger.debug(f"Emitting candlestick update: candles={len(update_data['candles'])}")
            self.socketio.emit("candlestick_update", update_data)
            
            # Also update moving averages
            self.emit_moving_averages()
        except Exception as e:
            logger.error(f"Error emitting candlestick update: {str(e)}")
    
    def emit_moving_averages(self):
        """Calculate and emit moving averages to the client"""
        try:
            # Only calculate moving averages when we have enough data
            if len(self.candlestick_data) >= 5:
                moving_averages = self.calculate_moving_averages()
                
                # Ensure all time values are integers
                for sma in moving_averages:
                    if sma and 'values' in sma and sma['values']:
                        for point in sma['values']:
                            if 'time' in point and not isinstance(point['time'], int):
                                try:
                                    point['time'] = int(point['time'])
                                except (ValueError, TypeError):
                                    point['time'] = int(time.time())
                
                # Emit moving averages update
                if moving_averages:
                    logger.debug(f"Emitting moving averages: {len(moving_averages)} series")
                    self.socketio.emit("moving_averages", moving_averages)
                else:
                    logger.warning("No moving averages calculated")
            else:
                logger.debug(f"Not enough data for moving averages: {len(self.candlestick_data)} candles")
        except Exception as e:
            logger.error(f"Error emitting moving averages: {str(e)}")
    
    def update_candlestick(self, trade, emit=True):
        """Update candlestick data with the trade"""
        try:
            # Get trade timestamp
            trade_time = int(time.time())
            try:
                # Try to parse the timestamp from the trade - using standardized "time" field name
                dt = datetime.fromisoformat(trade["time"].replace('Z', '+00:00'))
                trade_time = int(dt.timestamp())
            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f"Could not parse trade time: {str(e)}, using system time")
                pass
                
            # Calculate the interval timestamp (e.g., for 1-second candles)
            interval_time = trade_time // self.candlestick_interval * self.candlestick_interval
            
            # Ensure we have a valid price
            try:
                trade_price = float(trade["price"])
                if math.isnan(trade_price) or math.isinf(trade_price):
                    logger.warning(f"Invalid trade price: {trade_price}")
                    return False
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Could not parse trade price: {str(e)}")
                return False
            
            # Debug log
            logger.debug(f"Updating candlestick for time {interval_time}, price {trade_price}")
            
            # Check if we need to create a new candle or update existing one
            new_candle = False
            if not self.candlestick_data or self.candlestick_data[-1]['time'] != interval_time:
                # Create a new candle
                new_candle = True
                self.candlestick_data.append({
                    'security_id': trade.get("security_id", "Unknown"),
                    'time': interval_time,  # Already an integer timestamp
                    'open': trade_price,
                    'high': trade_price,
                    'low': trade_price,
                    'close': trade_price
                })
                # Keep only last 200 candles to prevent memory bloat but still show good history
                if len(self.candlestick_data) > 200:
                    self.candlestick_data = self.candlestick_data[-200:]
                
                # Sort candlestick data by time to ensure chronological order
                self.candlestick_data.sort(key=lambda x: x['time'])
            else:
                # Update the last candle
                candle = self.candlestick_data[-1]
                candle['high'] = max(candle['high'], trade_price)
                candle['low'] = min(candle['low'], trade_price)
                candle['close'] = trade_price
            
            # Decide whether to emit an update
            # Only emit if the emit parameter is True
            if emit:
                # For new candles or large price movements, emit right away
                should_emit = new_candle or abs(trade_price - self.candlestick_data[-1]['open']) > 0.01
                
                # Emit candlestick updates with full refresh occasionally to ensure chart consistency
                if should_emit:
                    # Every 20 updates, do a full refresh
                    full_refresh = new_candle and len(self.candlestick_data) % 20 == 0
                    self.emit_candlestick_update(full_refresh=full_refresh)
            
            return new_candle
        except Exception as e:
            logger.error(f"Error updating candlestick: {str(e)}")
            return False
    
    def update_orderbook(self, trade, emit=True):
        """Simulate orderbook updates based on trade data"""
        try:
            # Skip orderbook updates at very high speeds unless explicitly requested
            # Don't throttle too aggressively - only skip when not explicitly requested
            if not emit:
                return  # Skip if emit not requested
                
            # Extract security_id from trade
            security_id = trade.get("security_id", "UNKNOWN")
            
            # Get trade price
            trade_price = float(trade.get("price", 0))
            if trade_price <= 0:
                return  # Skip if price is invalid
                
            # Generate synthetic order book data around the trade price
            # This creates a more realistic DOM visualization
            spread = trade_price * 0.001  # 0.1% spread
            
            # Create bid and ask levels
            bids = []
            asks = []
            
            # Adjust the number of levels based on speed for performance
            if self.speed_factor > 5000:
                # At very high speeds, use minimal levels
                levels = 3
            elif self.speed_factor > 1000:
                # At high speeds, use fewer levels
                levels = 5
            else:
                # At normal speeds, use full detail
                levels = 10
            
            # Create levels of bids below the price
            for i in range(1, levels + 1):
                bid_price = trade_price - (spread * i)
                # Generate somewhat random but realistic volumes
                volume = int(100 / i) + random.randint(1, 50)
                bids.append({"price": round(bid_price, 2), "size": volume})
            
            # Create levels of asks above the price
            for i in range(1, levels + 1):
                ask_price = trade_price + (spread * i)
                # Generate somewhat random but realistic volumes
                volume = int(100 / i) + random.randint(1, 50)
                asks.append({"price": round(ask_price, 2), "size": volume})
            
            # Sort bids and asks (bids high to low, asks low to high)
            bids.sort(key=lambda x: x["price"], reverse=True)
            asks.sort(key=lambda x: x["price"])
            
            # Update the orderbook
            self.order_book = {
                "bids": bids,
                "asks": asks,
                "security_id": security_id
            }
            
            # Only emit if requested and throttle at high speeds
            should_emit = False
            if emit:
                # At extreme speeds, only update occasionally but don't throttle too much
                if self.speed_factor > 10000:
                    should_emit = (self.current_position % 100 == 0)
                # At high speeds, update less frequently
                elif self.speed_factor > 1000:
                    should_emit = (self.current_position % 20 == 0)
                # At normal speeds, update regularly
                else:
                    should_emit = True
                    
                # Emit orderbook if needed
                if should_emit:
                    self.socketio.emit("orderbook", self.order_book)
                    
                    # Also emit DOM data in the format expected by the chart
                    # Only prepare and send DOM data if we're emitting the orderbook
                    dom_data = {
                        "bids": [[bid["price"], bid["size"]] for bid in bids],
                        "asks": [[ask["price"], ask["size"]] for ask in asks],
                        "security_id": security_id
                    }
                    self.socketio.emit("depth_of_market", dom_data)
            
            # Log orderbook update for debugging
            logger.debug(f"Updated orderbook for {security_id} with bids: {len(bids)}, asks: {len(asks)}")
        except Exception as e:
            logger.error(f"Error updating orderbook: {str(e)}")
    
    def emit_trade(self, trade, force_emit=False):
        """Emit a trade to the frontend with speed-based throttling"""
        try:
            # Always emit trades for the chart, but throttle other heavy operations
            # We'll use a separate flag to track if we should emit full trade details
            emit_full_details = force_emit
            
            # Determine if we should emit full details based on speed and position
            if not force_emit:
                if self.speed_factor > 10000:
                    # At extreme speeds, emit full details occasionally
                    emit_full_details = (self.current_position % 100 == 0)
                elif self.speed_factor > 5000:
                    # At very high speeds, emit full details more frequently
                    emit_full_details = (self.current_position % 50 == 0)
                elif self.speed_factor > 1000:
                    # At high speeds, emit full details regularly
                    emit_full_details = (self.current_position % 20 == 0)
                else:
                    # At normal speeds, always emit full details
                    emit_full_details = True
                    
            # Always prepare basic trade data for the chart
            trade_data = {
                "id": trade["id"],
                "time": int(time.time()),
                "security_id": trade["security_id"],
                "price": float(trade["price"]),
                "size": float(trade["size"])
            }
            
            # Only include buyer/seller IDs when emitting full details to reduce data size
            if emit_full_details:
                trade_data["buyer_id"] = trade["buyer_id"]
                trade_data["seller_id"] = trade["seller_id"]
            
            # Try to parse the timestamp from the trade - using standardized "time" field name
            try:
                dt = datetime.fromisoformat(trade["time"].replace('Z', '+00:00'))
                trade_data["time"] = int(dt.timestamp())
            except (ValueError, TypeError, KeyError) as e:
                # Don't log at high speeds to reduce overhead
                if self.speed_factor < 1000:
                    logger.debug(f"Could not parse trade time: {str(e)}, using system time")
                pass
            
            # Always emit trade to frontend for the chart
            if self.speed_factor < 1000:
                logger.debug(f"Emitting trade: {trade_data}")
            self.socketio.emit("trade", trade_data)
            
            # ALWAYS emit volume data regardless of speed
            # This ensures the volume chart continues to update even at very high speeds
            # No throttling at all - always send the data
                    
            aggregated_trade = {
                "time": trade_data["time"],
                "security_id": trade_data["security_id"],
                "total_volume": trade_data["size"],
                "average_price": trade_data["price"],
                "count": 1,
                "incremental": True
            }
            
            if self.speed_factor < 1000:
                logger.debug(f"Emitting aggregated trade: {aggregated_trade}")
            self.socketio.emit("aggregated_trade", aggregated_trade)
            
        except Exception as e:
            logger.error(f"Error emitting trade: {str(e)}")
    
    def _load_trades(self):
        """Load trades from CSV file"""
        try:
            # Initial status
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": "Preparing to load trade data...",
                "progress": 5
            })
            
            # Check if file exists
            if not os.path.exists(self.csv_file):
                error_msg = f"CSV file not found: {self.csv_file}"
                logger.error(error_msg)
                self.socketio.emit("loading_status", {
                    "status": "error",
                    "message": error_msg,
                    "progress": 0
                })
                return False
            
            # Get file size for better progress reporting
            file_size = os.path.getsize(self.csv_file)
            logger.info(f"Loading CSV file: {self.csv_file} ({file_size/1024/1024:.2f} MB)")
            
            # Emit file size information
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"File size: {file_size/1024/1024:.2f} MB",
                "progress": 10,
                "bytes_loaded": 0,
                "bytes_total": file_size
            })
            
            # Determine if this is a large file
            large_file = file_size > 50 * 1024 * 1024  # > 50MB is considered large
            
            # First count the number of rows to provide accurate progress updates
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": "Counting rows for progress tracking...",
                "progress": 15,
                "bytes_loaded": 0,
                "bytes_total": file_size
            })
            
            total_rows = 0
            chunk_size = 50000  # Use the same chunk size for counting and processing
            
            # For very large files, estimate row count instead of exact counting
            if file_size > 200 * 1024 * 1024:  # > 200MB
                # Estimate based on first chunk
                with open(self.csv_file, 'r') as f:
                    # Read header and first few lines to estimate
                    header = f.readline()
                    sample_lines = []
                    for _ in range(1000):  # Sample 1000 lines
                        line = f.readline()
                        if not line:
                            break
                        sample_lines.append(line)
                
                if sample_lines:
                    # Calculate average bytes per line
                    avg_bytes_per_line = sum(len(line) for line in sample_lines) / len(sample_lines)
                    # Estimate total rows (subtracting header size)
                    total_rows = int((file_size - len(header)) / avg_bytes_per_line)
                    logger.info(f"Estimated total rows: {total_rows} (based on sample)")
                else:
                    # Fallback if we couldn't read sample lines
                    total_rows = int(file_size / 100)  # Just a rough estimate
            else:
                # For smaller files, get exact row count
                with open(self.csv_file, 'r') as f:
                    total_rows = sum(1 for _ in f) - 1  # Subtract header row
                logger.info(f"Exact total rows: {total_rows}")
            
            # Calculate total chunks
            total_chunks = max(1, total_rows // chunk_size + (1 if total_rows % chunk_size > 0 else 0))
            logger.info(f"Will process data in {total_chunks} chunks of {chunk_size} rows")
            
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"Starting to load {total_rows:,} rows in {total_chunks} chunks",
                "progress": 20,
                "bytes_loaded": 0,
                "bytes_total": file_size
            })
            
            # Initialize empty list for trades
            self.trades = []
            
            # Required columns to check and their possible mappings
            column_mappings = {
                "id": ["id", "ID", "trade_id", "Trade ID", "TradeID"],
                "time": ["time", "Time", "timestamp", "Timestamp", "trade_time", "Trade Time"],
                "security_id": ["security_id", "Security ID", "SecurityID", "symbol", "Symbol"],
                "price": ["price", "Price"],
                "size": ["size", "Size", "quantity", "Quantity", "volume", "Volume"],
                "buyer_id": ["buyer_id", "Buyer ID", "BuyerID", "buyer", "Buyer"],
                "seller_id": ["seller_id", "Seller ID", "SellerID", "seller", "Seller"]
            }
            
            # Track chunk progress
            current_chunk = 0
            
            # Progress tracking variables
            progress_start = 20  # Starting progress percentage
            progress_chunk_range = 60  # Range allocated for chunk processing (20-80%)
            
            if large_file:
                logger.info("Using optimized loading for large file")
                # Use pandas to read the CSV in chunks
                
                # Emit loading message
                self.socketio.emit("loading_status", {
                    "status": "loading",
                    "message": f"Loading large file in chunks ({chunk_size:,} rows per chunk)",
                    "progress": progress_start,
                    "bytes_loaded": 0,
                    "bytes_total": file_size
                })
                
                try:
                    # Read CSV in chunks
                    for chunk in pd.read_csv(self.csv_file, chunksize=chunk_size):
                        # Validate required columns exist
                        if current_chunk == 0:  # Only check on first chunk
                            # Check for missing columns with multiple possible names
                            missing_columns = []
                            column_name_map = {}  # Store the actual column names to use
                            
                            for required_col, possible_names in column_mappings.items():
                                found = False
                                for possible_name in possible_names:
                                    if possible_name in chunk.columns:
                                        column_name_map[required_col] = possible_name
                                        found = True
                                        break
                                if not found:
                                    missing_columns.append(required_col)
                            
                            if missing_columns:
                                error_msg = f"CSV file missing required columns: {', '.join(missing_columns)}"
                                logger.error(error_msg)
                                self.socketio.emit("loading_status", {
                                    "status": "error",
                                    "message": error_msg,
                                    "progress": 0
                                })
                                return False
                            
                            # Log the column mapping being used
                            logger.info(f"Using column mapping: {column_name_map}")
                        
                        # Process this chunk
                        chunk_trades = []
                        for _, row in chunk.iterrows():
                            trade = {
                                "id": str(row[column_name_map["id"]]),
                                "time": str(row[column_name_map["time"]]),
                                "security_id": str(row[column_name_map["security_id"]]),
                                "price": float(row[column_name_map["price"]]),
                                "size": float(row[column_name_map["size"]]),
                                "buyer_id": str(row[column_name_map["buyer_id"]]),
                                "seller_id": str(row[column_name_map["seller_id"]])
                            }
                            chunk_trades.append(trade)
                        
                        self.trades.extend(chunk_trades)
                        
                        # Update progress
                        current_chunk += 1
                        chunk_progress = current_chunk / total_chunks
                        progress = progress_start + (progress_chunk_range * chunk_progress)
                        
                        # Calculate approximate bytes loaded based on chunk progress
                        bytes_loaded = int(file_size * (current_chunk / total_chunks))
                        
                        # Log progress every few chunks
                        if current_chunk % 5 == 0 or current_chunk == total_chunks:
                            logger.info(f"Loaded chunk {current_chunk}/{total_chunks} ({len(self.trades):,} trades so far, {bytes_loaded/1024/1024:.2f} MB)")
                        
                        # Send progress update to client
                        self.socketio.emit("loading_status", {
                            "status": "loading",
                            "message": f"Loading chunk {current_chunk}/{total_chunks} ({int(chunk_progress*100)}% complete, {bytes_loaded/1024/1024:.2f} MB)",
                            "progress": int(progress),
                            "bytes_loaded": bytes_loaded,
                            "bytes_total": file_size
                        })
                        
                except Exception as e:
                    error_msg = f"Error loading CSV in chunks: {str(e)}"
                    logger.error(error_msg)
                    logger.error(traceback.format_exc())
                    self.socketio.emit("loading_status", {
                        "status": "error",
                        "message": error_msg,
                        "progress": 0
                    })
                    return False
            else:
                logger.info("Loading smaller file all at once")
                # Load the entire file at once for smaller files
                try:
                    # Load CSV
                    df = pd.read_csv(self.csv_file)
                    
                    # Validate required columns exist
                    missing_columns = []
                    column_name_map = {}  # Store the actual column names to use
                    
                    for required_col, possible_names in column_mappings.items():
                        found = False
                        for possible_name in possible_names:
                            if possible_name in df.columns:
                                column_name_map[required_col] = possible_name
                                found = True
                                break
                        if not found:
                            missing_columns.append(required_col)
                    
                    if missing_columns:
                        error_msg = f"CSV file missing required columns: {', '.join(missing_columns)}"
                        logger.error(error_msg)
                        self.socketio.emit("loading_status", {
                            "status": "error",
                            "message": error_msg,
                            "progress": 0
                        })
                        return False
                    
                    # Log the column mapping being used
                    logger.info(f"Using column mapping: {column_name_map}")
                    
                    # Convert to list of dictionaries with standardized field names
                    self.trades = []
                    for _, row in df.iterrows():
                        trade = {
                            "id": str(row[column_name_map["id"]]),
                            "time": str(row[column_name_map["time"]]),
                            "security_id": str(row[column_name_map["security_id"]]),
                            "price": float(row[column_name_map["price"]]),
                            "size": float(row[column_name_map["size"]]),
                            "buyer_id": str(row[column_name_map["buyer_id"]]),
                            "seller_id": str(row[column_name_map["seller_id"]])
                        }
                        self.trades.append(trade)
                    
                    # Update progress
                    self.socketio.emit("loading_status", {
                        "status": "loading",
                        "message": f"Loaded {len(self.trades):,} trades all at once ({file_size/1024/1024:.2f} MB)",
                        "progress": progress_start + progress_chunk_range,
                        "bytes_loaded": file_size,
                        "bytes_total": file_size
                    })
                    
                except Exception as e:
                    error_msg = f"Error loading CSV: {str(e)}"
                    logger.error(error_msg)
                    logger.error(traceback.format_exc())
                    self.socketio.emit("loading_status", {
                        "status": "error",
                        "message": error_msg,
                        "progress": 0
                    })
                    return False
            
            # Sort trades by time
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"Sorting {len(self.trades):,} trades by time...",
                "progress": 85,
                "bytes_loaded": file_size,
                "bytes_total": file_size
            })
            
            # Sort trades by time
            self.trades.sort(key=lambda x: x["time"])
            
            # Finish loading
            logger.info(f"Successfully loaded {len(self.trades):,} trades")
            self.socketio.emit("loading_status", {
                "status": "loading",
                "message": f"Successfully loaded {len(self.trades):,} trades ({file_size/1024/1024:.2f} MB)",
                "progress": 95,
                "bytes_loaded": file_size,
                "bytes_total": file_size
            })
            
            # Initialize trading data with first trade
            self.initialize_empty_data()
            
            # Set initial current position
            self.current_position = 0
            
            # Set the timestamp range
            if self.trades:
                try:
                    self.min_time = self.trades[0]["time"]
                    self.max_time = self.trades[-1]["time"]
                    logger.info(f"Trade time range: {self.min_time} to {self.max_time}")
                except (KeyError, IndexError) as e:
                    logger.error(f"Error setting time range: {str(e)}")
                    # Set defaults if we can't get the actual times
                    self.min_time = "2023-01-01T00:00:00"
                    self.max_time = "2023-12-31T23:59:59"
            
            return True
            
        except Exception as e:
            error_msg = f"Error loading trades: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            self.socketio.emit("loading_status", {
                "status": "error",
                "message": error_msg,
                "progress": 0
            })
            return False
    
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
            
            # Initialize charts with empty data
            if not self.candlestick_data:
                logger.info("No candlestick data, initializing empty chart")
                self.socketio.emit("candlestick", [])
            else:
                # Format timestamps as integers for the chart library
                formatted_candles = []
                for candle in self.candlestick_data:
                    formatted_candle = candle.copy()
                    # Ensure time is an integer
                    if 'time' in formatted_candle and not isinstance(formatted_candle['time'], int):
                        try:
                            formatted_candle['time'] = int(formatted_candle['time'])
                        except (ValueError, TypeError):
                            # If conversion fails, use current timestamp
                            formatted_candle['time'] = int(time.time())
                    formatted_candles.append(formatted_candle)
                
                logger.info(f"Sending {len(formatted_candles)} initial candles")
                self.socketio.emit("candlestick", formatted_candles)
            
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
        """Run the replay loop"""
        if not self.trades:
            logger.error("No trades loaded")
            return
        
        logger.info(f"Starting replay with {len(self.trades)} trades at speed {self.speed_factor}x")
        
        # Initialize state
        self.is_running = True
        self.is_paused = False
        
        # Track processing stats
        start_time = time.time()
        last_emit_time = 0
        last_status_emit = 0
        status_interval = 0.5  # seconds
        last_candle_time = 0
        candle_update_interval = 0.1  # seconds
        last_orderbook_time = 0
        orderbook_update_interval = 0.2  # seconds
        
        # Track trades per second for stats
        trades_processed = 0
        last_stats_time = time.time()
        
        # Set to keep track of unique timestamps for throttling
        processed_times = set()
        
        # Track the last trade timestamp to ensure forward progress
        last_trade_timestamp = None
        
        # Enhanced logging for candle creation
        candles_created = 0
        last_candle_log = 0
        
        # Main replay loop
        try:
            while self.is_running and self.current_position < len(self.trades):
                # Handle pause
                if self.is_paused:
                    time.sleep(0.1)
                    continue
                
                # Process trades based on speed factor - use more aggressive processing for higher speeds
                if self.speed_factor > 100000:
                    # Use fast forward for extreme speeds
                    self.fast_forward(self.speed_factor)
                    # After fast-forwarding, if we've reached the end, break
                    if self.current_position >= len(self.trades):
                        break
                    
                # For high speeds (10,000-100,000), use batch processing
                elif self.speed_factor > 10000:
                    # Process multiple trades at once without emitting each one
                    # Scale batch size more aggressively with speed
                    batch_size = int(self.speed_factor / 10)  # 10x larger batches
                    end_position = min(self.current_position + batch_size, len(self.trades))
                    
                    # Collect trades for aggregated volume updates
                    batch_trades = []
                    sample_interval = max(1, batch_size // 20)  # Take about 20 samples from the batch
                    
                    # Process the batch of trades
                    for i in range(self.current_position, end_position):
                        self.current_position = i
                        trade = self.trades[i]
                        
                        # Collect key trades for batch processing
                        if i % sample_interval == 0:
                            batch_trades.append(trade)
                        
                        # Only process every Nth trade for candlestick efficiency
                        if i % 10 == 0:
                            self.update_candlestick(trade, emit=False)  # Update without emitting
                    
                    # Emit only one aggregated trade update for the entire batch
                    # This significantly reduces the number of socket.io messages
                    if batch_trades:
                        # Use the last trade for the update
                        self.emit_trade(batch_trades[-1], force_emit=True)
                    
                    # Emit only the final state after batch processing
                    if len(self.candlestick_data) > 0:
                        self.emit_candlestick_update(full_refresh=(self.current_position % 1000 == 0))
                    
                    # Update position for UI
                    self.socketio.emit("position_update", {
                        "position": self.current_position,
                        "total": len(self.trades)
                    })
                    
                    # No sleep to maximize speed
                    continue  # Skip the normal processing below
                    
                # For medium-high speeds (1,000-10,000), use smaller batch processing
                elif self.speed_factor > 1000:
                    # Process multiple trades at once without emitting each one
                    batch_size = int(self.speed_factor / 20)  # Scale batch size with speed
                    end_position = min(self.current_position + batch_size, len(self.trades))
                    
                    # Collect trades for aggregated volume updates
                    batch_trades = []
                    
                    # Process the batch of trades
                    for i in range(self.current_position, end_position):
                        self.current_position = i
                        trade = self.trades[i]
                        
                        # Collect trades for batch processing
                        batch_trades.append(trade)
                        
                        # Only process every 5th trade for candlestick efficiency
                        if i % 5 == 0:
                            self.update_candlestick(trade, emit=False)  # Update without emitting
                    
                    # Emit only one aggregated trade update for the entire batch
                    # This significantly reduces the number of socket.io messages
                    if batch_trades:
                        # Use the last trade for the update
                        self.emit_trade(batch_trades[-1], force_emit=True)
                    
                    # Emit only the final state after batch processing
                    if len(self.candlestick_data) > 0:
                        self.emit_candlestick_update(full_refresh=(self.current_position % 500 == 0))
                    
                    # Update position for UI
                    self.socketio.emit("position_update", {
                        "position": self.current_position,
                        "total": len(self.trades)
                    })
                    
                    # Very minimal sleep
                    time.sleep(0.0001)
                    continue  # Skip the normal processing below
                
                # Get current trade
                trade = self.trades[self.current_position]
                
                # Extract trade timestamp
                try:
                    # Get a numeric timestamp from the trade - using standardized "time" field name
                    trade_timestamp = 0
                    try:
                        # Try to parse the timestamp from the trade - using standardized "time" field name
                        dt = datetime.fromisoformat(trade["time"].replace('Z', '+00:00'))
                        trade_timestamp = int(dt.timestamp())
                    except (ValueError, TypeError, KeyError):
                        trade_timestamp = int(time.time())
                    
                    # If this is a new timestamp or we haven't created many candles yet, update charts
                    current_time = time.time()
                    should_update_candle = (
                        last_trade_timestamp is None or 
                        trade_timestamp != last_trade_timestamp or
                        candles_created < 10 or
                        (current_time - last_candle_time) >= candle_update_interval
                    )
                    
                    # Check if we should update the orderbook
                    should_update_orderbook = (
                        (current_time - last_orderbook_time) >= orderbook_update_interval
                    )
                    
                    # Emit trade data to UI with throttling based on speed
                    # More aggressive throttling at higher speeds
                    if self.speed_factor <= 100:
                        emit_throttle = max(1, int(self.speed_factor / 2))
                    elif self.speed_factor <= 1000:
                        emit_throttle = max(10, int(self.speed_factor / 3))
                    else:
                        emit_throttle = max(100, int(self.speed_factor / 4))
                        
                    if self.current_position % emit_throttle == 0:
                        self.emit_trade(trade)
                    
                    # Update candlestick chart
                    if should_update_candle:
                        self.update_candlestick(trade)
                        last_candle_time = current_time
                        last_trade_timestamp = trade_timestamp
                        candles_created += 1
                        
                        # Log candle creation periodically
                        if current_time - last_candle_log > 5:  # Log every 5 seconds
                            logger.info(f"Created {candles_created} candles so far")
                            last_candle_log = current_time
                    
                    # Update orderbook
                    if should_update_orderbook:
                        self.update_orderbook(trade)
                        last_orderbook_time = current_time
                except Exception as e:
                    logger.error(f"Error processing trade: {str(e)}")
                
                # Move to the next trade
                self.current_position += 1
                trades_processed += 1
                
                # Calculate sleep time based on speed
                # Use a more gradual scaling of sleep time across all speed ranges
                # Base delay is 100ms at 1x speed
                base_delay = 0.1
                
                if self.speed_factor <= 1:
                    # For normal or slow speeds, use the full base delay
                    sleep_time = base_delay
                elif self.speed_factor <= 100:
                    # For speeds 1x to 100x, gradually reduce sleep time
                    # This creates a smooth transition from 100ms at 1x to 1ms at 100x
                    sleep_time = base_delay / self.speed_factor
                elif self.speed_factor <= 500:
                    # For speeds 100x to 500x, use quadratic scaling
                    # This creates an exponential decrease in sleep time as speed increases
                    # At 100x: ~1ms, at 200x: ~0.25ms, at 300x: ~0.11ms
                    scale_factor = (self.speed_factor / 100) ** 2
                    sleep_time = max(0.00005, base_delay / (100 * scale_factor))
                else:
                    # For extreme speeds (500x-1000x), use cubic scaling for even faster playback
                    # This creates a very steep decrease in sleep time
                    # At 500x: ~0.04ms, at 750x: ~0.012ms, at 1000x: ~0.005ms
                    scale_factor = (self.speed_factor / 100) ** 3
                    sleep_time = max(0.000025, base_delay / (100 * scale_factor))
                
                # Apply the calculated sleep time
                time.sleep(sleep_time)
                
                # For very high speeds, check pause state more frequently
                # This makes the pause button more responsive
                # Scale the check frequency based on speed - higher speeds check more often
                check_interval = max(10, int(1000 / self.speed_factor))
                if self.speed_factor > 100 and self.current_position % check_interval == 0:
                    # Check if we've been paused
                    if self.is_paused:
                        continue
                
                # Emit status updates periodically
                if time.time() - last_status_emit > status_interval:
                    # Calculate TPS (trades per second)
                    current_stats_time = time.time()
                    tps = trades_processed / (current_stats_time - last_stats_time) if current_stats_time > last_stats_time else 0
                    trades_processed = 0
                    last_stats_time = current_stats_time
                    
                    # Log stats
                    logger.debug(f"Replay at position {self.current_position}/{len(self.trades)} ({tps:.1f} trades/sec)")
                    
                    # Emit status
                    self.socketio.emit("replay_status", {
                        "running": self.is_running,
                        "paused": self.is_paused,
                        "position": self.current_position,
                        "total": len(self.trades),
                        "speed": self.speed_factor,
                        "tps": int(tps)
                    })
                    
                    last_status_emit = time.time()
                
            # When complete, update UI
            if self.current_position >= len(self.trades):
                logger.info("Replay complete!")
                self.socketio.emit("replay_status", {
                    "running": False,
                    "paused": False,
                    "position": len(self.trades),
                    "total": len(self.trades),
                    "complete": True
                })
                self.is_running = False
                
        except Exception as e:
            logger.error(f"Error in replay loop: {str(e)}")
            logger.error(traceback.format_exc())
            self.socketio.emit("replay_status", {
                "error": str(e),
                "running": False
            })
            self.is_running = False
    
    def set_speed(self, speed_factor):
        """Set the replay speed factor"""
        try:
            # Clamp speed to reasonable values but allow much higher speeds
            # Increased from 1000000 to 10000000 to support even more extreme speeds
            speed_factor = max(0.1, min(10000000, float(speed_factor)))
            self.speed_factor = speed_factor
            logger.info(f"Set replay speed to {speed_factor}x")
            
            # Notify clients
            self.socketio.emit("speed_update", {"speed": speed_factor})
            
            # For extremely high speeds (>10000x), consider using the fast-forward method
            # This is handled separately in the replay command handler
            
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
        
        # Clear all chart data
        self.candlestick_data = []
        
        # Send empty data to clear charts
        logger.info("Clearing all charts on stop")
        self.socketio.emit("candlestick", [])
        self.socketio.emit("candlestick_update", {"full_refresh": True, "candles": []})
        self.socketio.emit("moving_averages", [])
        self.socketio.emit("orderbook", {"bids": [], "asks": []})
        self.socketio.emit("trade_volume", [])
        
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
            
            # If position is 0, clear all charts to start fresh
            if position == 0:
                logger.info("Position set to 0, clearing all charts")
                # Reset candlestick data
                self.candlestick_data = []
                # Send empty data to clear charts
                self.socketio.emit("candlestick", [])
                self.socketio.emit("candlestick_update", {"full_refresh": True, "candles": []})
                # Clear moving averages
                self.socketio.emit("moving_averages", [])
                # Clear order book
                self.socketio.emit("orderbook", {"bids": [], "asks": []})
                # Clear trade chart
                self.socketio.emit("trade_volume", [])
            # Otherwise update with current trade data
            elif 0 <= position < len(self.trades):
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
            logger.error(f"Error in seek: {str(e)}")
            return False
                
    def play_to_position(self, target_position, auto_start=False):
        """Play the replay until a specific position and then stop"""
        try:
            # Validate the target position
            target_position = int(target_position)
            target_position = max(0, min(len(self.trades) - 1, target_position))
            
            logger.info(f"Playing to position {target_position}/{len(self.trades)} (auto_start: {auto_start})")
            
            # Set a flag to indicate we're playing to a specific position
            self.target_stop_position = target_position
            
            if auto_start:
                logger.info("Auto-start is enabled, starting replay immediately")
                # Make sure we're not paused
                self.is_paused = False
                
                # Force stop any existing replay thread to ensure clean start
                if hasattr(self, 'replay_thread') and self.replay_thread and self.replay_thread.is_alive():
                    logger.info("Stopping existing replay thread")
                    self.is_running = False
                    time.sleep(0.2)  # Give the thread time to stop
                
                # Start a fresh replay
                logger.info("Starting new replay thread")
                self.is_running = True
                self.replay_thread = threading.Thread(target=self.run_replay)
                self.replay_thread.daemon = True
                self.replay_thread.start()
                logger.info("Replay thread started directly from play_to_position")
                
                # Send status update to clients
                self.socketio.emit("replay_status", {
                    "status": "playing",
                    "running": self.is_running,
                    "paused": self.is_paused,
                    "position": self.current_position,
                    "total": len(self.trades),
                    "speed": self.speed_factor,
                    "filename": os.path.basename(self.csv_file) if self.csv_file else ""
                })
            else:
                # Just set the target position without starting
                logger.info(f"Target position set to {target_position}, waiting for play command")
            
            # Start a background thread to monitor the position and stop when we reach the target
            def monitor_position():
                logger.info(f"Starting monitor thread for target position {self.target_stop_position}")
                # Wait a moment to ensure the replay thread has started
                time.sleep(0.5)
                
                # Check if the replay is actually running
                if not self.is_running:
                    logger.error("Monitor thread detected replay is not running, attempting to start it")
                    self.is_running = True
                    if not hasattr(self, 'replay_thread') or not self.replay_thread.is_alive():
                        self.replay_thread = threading.Thread(target=self.run_replay)
                        self.replay_thread.daemon = True
                        self.replay_thread.start()
                        logger.info("Replay thread started from monitor")
                
                # Monitor the position
                start_time = time.time()
                last_log_time = start_time
                last_position = self.current_position
                
                while self.is_running and self.current_position < self.target_stop_position:
                    # If paused, just wait
                    if self.is_paused:
                        time.sleep(0.1)
                        continue
                    
                    # Check if position is advancing
                    current_time = time.time()
                    if current_time - last_log_time >= 1.0:  # Log every second
                        position_change = self.current_position - last_position
                        logger.info(f"Progress: {self.current_position}/{self.target_stop_position} (+{position_change} in 1s)")
                        last_log_time = current_time
                        last_position = self.current_position
                        
                        # If position hasn't changed in 3 seconds, there might be an issue
                        if position_change == 0 and current_time - start_time > 3.0:
                            logger.warning("Position not advancing, replay might be stuck")
                    
                    time.sleep(0.1)  # Check every 100ms
                
                # If we've reached or passed the target position, stop the replay
                if self.is_running and self.current_position >= self.target_stop_position:
                    logger.info(f"Reached target position {self.target_stop_position}, stopping replay")
                    self.is_paused = True
                    self.target_stop_position = None  # Reset target position
                    
                    # Send status update
                    self.socketio.emit("replay_status", {
                        "status": "paused",
                        "running": self.is_running,
                        "paused": self.is_paused,
                        "position": self.current_position,
                        "total": len(self.trades),
                        "speed": self.speed_factor,
                        "filename": os.path.basename(self.csv_file) if self.csv_file else ""
                    })
                else:
                    logger.info(f"Monitor thread exiting without reaching target. Running: {self.is_running}, Position: {self.current_position}, Target: {self.target_stop_position}")
            
            # Start the monitoring thread
            monitor_thread = threading.Thread(target=monitor_position, daemon=True)
            monitor_thread.start()
            logger.info("Monitor thread started")
            
        except Exception as e:
            logger.error(f"Error in play_to_position: {str(e)}")
            return False

    def fast_forward(self, speed_factor):
        """Fast forward through trades at extreme speeds"""
        logger.info(f"Fast forwarding at {speed_factor}x speed")
        
        # Calculate how many trades to skip based on speed - more aggressive jumps
        if speed_factor > 1000000:
            # For extreme speeds (>1M), jump massive chunks
            jump_size = min(2000000, len(self.trades) // 3)
        elif speed_factor > 100000:
            # For very high speeds (100K-1M), process in large batches
            jump_size = min(200000, len(self.trades) // 5)
        else:
            # For high speeds (10K-100K), process in moderate batches
            jump_size = min(20000, len(self.trades) // 10)
            
        # Calculate target position with bounds checking
        target_position = min(self.current_position + jump_size, len(self.trades) - 1)
        
        if target_position <= self.current_position:
            # Nothing to fast forward to
            return
            
        # Log the jump
        logger.info(f"Fast forwarding from position {self.current_position} to {target_position}")
        
        # Process key trades along the way to maintain data integrity
        # For extremely high speeds, we'll sample trades at regular intervals but more sparsely
        # Collect sample trades for aggregated volume updates
        sample_trades = []
        
        if jump_size > 100000:
            # For very large jumps, take only 5 samples to minimize processing
            sample_interval = max(1, (target_position - self.current_position) // 5)
            
            # Process sampled trades to maintain chart continuity
            for sample_pos in range(self.current_position, target_position, sample_interval):
                if sample_pos < len(self.trades):
                    sample_trade = self.trades[sample_pos]
                    # Update candlestick without emitting to client
                    self.update_candlestick(sample_trade, emit=False)
                    # Collect for aggregated volume update
                    sample_trades.append(sample_trade)
        elif jump_size > 10000:
            # For large jumps, take 8 samples
            sample_interval = max(1, (target_position - self.current_position) // 8)
            
            # Process sampled trades to maintain chart continuity
            for sample_pos in range(self.current_position, target_position, sample_interval):
                if sample_pos < len(self.trades):
                    sample_trade = self.trades[sample_pos]
                    # Update candlestick without emitting to client
                    self.update_candlestick(sample_trade, emit=False)
                    # Collect for aggregated volume update
                    sample_trades.append(sample_trade)
        
        # Emit only one aggregated trade update for all samples
        # This significantly reduces the number of socket.io messages
        if sample_trades:
            # Use the last trade for the update
            self.emit_trade(sample_trades[-1], force_emit=True)
        
        # Get the trade at the target position for updating the UI
        if target_position < len(self.trades):
            target_trade = self.trades[target_position]
            
            # Update visualization with the target trade - force emit
            self.emit_trade(target_trade, force_emit=True)
            self.update_candlestick(target_trade, emit=True)
            
            # Log that we jumped
            logger.info(f"Updated charts with trade at position {target_position}")
            
        # Update position
        self.current_position = target_position
        
        # Emit status update
        self.socketio.emit("replay_status", {
            "running": self.is_running,
            "paused": self.is_paused,
            "position": self.current_position,
            "total": len(self.trades),
            "speed": self.speed_factor,
            "fast_forward": True
        })

    def play(self):
        """Play/resume the replay"""
        logger.info("Play/resume replay")
        
        # If starting from position 0, ensure charts are cleared
        if self.current_position == 0:
            logger.info("Starting replay from beginning, clearing all charts")
            # Reset candlestick data
            self.candlestick_data = []
            # Send empty data to clear charts
            self.socketio.emit("candlestick", [])
            self.socketio.emit("candlestick_update", {"full_refresh": True, "candles": []})
            self.socketio.emit("moving_averages", [])
            self.socketio.emit("orderbook", {"bids": [], "asks": []})
            self.socketio.emit("trade_volume", [])
        
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
        
        # If we're starting from the beginning, make sure charts are initialized
        if self.current_position == 0:
            # Reset chart data structures
            self.candlestick_data = []
        
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
