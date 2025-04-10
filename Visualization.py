from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
import threading
import time
import json
from decimal import Decimal
from flask_cors import CORS
import os
import logging

from config import Config
from logger import setup_logger

# Disable noisy socketio logging
logging.getLogger('socketio').setLevel(logging.ERROR)
logging.getLogger('engineio').setLevel(logging.ERROR)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

logger = setup_logger(__name__)

class Visualization:
    def __init__(self, market):
        self.market = market
        self.orderbook_data = {"bids": [], "asks": []}
        self.candlestick_data = []
        self.band_data = []  # Store SMA data for bands
        self.markers = []  # To store emitted markers
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for all routes
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins="*",
            async_mode='eventlet',
            ping_timeout=5,
            ping_interval=1,
            max_http_buffer_size=1e8,
            logger=False,
            engineio_logger=False
        )
        self.server_thread = None
        self.max_markers = Config.MAX_MARKERS

        # Configure Flask routes
        self._setup_routes()
        logger.info("Visualization initialized")

    def _setup_routes(self):
        """Set up Flask routes with error handling."""
        @self.app.route("/")
        def index():
            """Serve the TradingView visualization page."""
            try:
                return render_template("index.html")
            except Exception as e:
                logger.error(f"Error serving index page: {str(e)}")
                return "Error loading visualization", 500

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
            """Send initial data to the client when connected."""
            try:
                emit("orderbook", self.orderbook_data)
                emit("candlestick", self.candlestick_data)
                # Send stored markers to the client
                for marker in self.markers:
                    emit("market_maker_marker", marker)
                logger.info("Client connected and initialized with data")
            except Exception as e:
                logger.error(f"Error during client connection: {str(e)}")

    def start_server(self, port=None):
        """Start the Flask server in a separate thread."""
        try:
            port = port or Config.PORT
            self.server_thread = threading.Thread(
                target=lambda: self.socketio.run(
                    self.app,
                    host=Config.HOST,
                    port=port,
                    debug=Config.DEBUG
                )
            )
            self.server_thread.daemon = True
            self.server_thread.start()
            logger.info(f"Visualization server started on port {port}")
        except Exception as e:
            logger.error(f"Failed to start visualization server: {str(e)}")
            raise

    def update_orderbook(self):
        """Update the order book data and emit it for the DOM chart."""
        try:
            for security_id, orderbook in self.market.orderbooks.items():
                # Prepare data for general orderbook usage
                self.orderbook_data = {
                    "bids": [
                        {"price": float(order.price), "size": float(order.size - order.filled)}
                        for order in orderbook.bids[:Config.ORDERBOOK_DEPTH]
                    ],
                    "asks": [
                        {"price": float(order.price), "size": float(order.size - order.filled)}
                        for order in orderbook.asks[:Config.ORDERBOOK_DEPTH]
                    ]
                }
                self.socketio.emit("orderbook", self.orderbook_data)

                # Prepare data for the Depth of Market (DOM) chart
                dom_data = {
                    "bids": [
                        [float(order.price), float(order.size - order.filled)]
                        for order in orderbook.bids
                    ],
                    "asks": [
                        [float(order.price), float(order.size - order.filled)]
                        for order in orderbook.asks
                    ],
                    "security_id": security_id
                }
                self.socketio.emit("depth_of_market", dom_data)
        except Exception as e:
            logger.error(f"Error updating orderbook: {str(e)}")

    def update_candlestick(self, interval=None):
        """Update candlestick data with the latest trades."""
        try:
            interval = interval or Config.CANDLESTICK_INTERVAL
            trades = self.market.orderbooks[next(iter(self.market.orderbooks))].trades
            
            if trades:
                current_time = int(time.time() // interval * interval)
                last_trade = trades[-1]
                trade_price = float(last_trade.price)

                if self.candlestick_data and self.candlestick_data[-1]['time'] == current_time:
                    # Update the last candle
                    candle = self.candlestick_data[-1]
                    candle['security_id'] = last_trade.security_id
                    candle['high'] = max(candle['high'], trade_price)
                    candle['low'] = min(candle['low'], trade_price)
                    candle['close'] = trade_price
                else:
                    # Create a new candle
                    self.candlestick_data.append({
                        'security_id': last_trade.security_id,
                        'time': current_time,
                        'open': trade_price,
                        'high': trade_price,
                        'low': trade_price,
                        'close': trade_price
                    })

                # Emit updated candlestick data
                self.socketio.emit("candlestick", self.candlestick_data[-100:])  # Send last 100 candles
                
                # Update and emit moving averages
                self.update_band_data()
                
        except Exception as e:
            logger.error(f"Error updating candlestick data: {str(e)}")

    def add_marker(self, marker_data):
        """Add a marker to the chart."""
        try:
            if len(self.markers) >= self.max_markers:
                self.markers.pop(0)  # Remove oldest marker
            self.markers.append(marker_data)
            self.socketio.emit("market_maker_marker", marker_data)
        except Exception as e:
            logger.error(f"Error adding marker: {str(e)}")

    def stop(self):
        """Stop the visualization server."""
        try:
            if self.socketio:
                self.socketio.stop()
            logger.info("Visualization server stopped")
        except Exception as e:
            logger.error(f"Error stopping visualization server: {str(e)}")

    def emit_market_maker_trade(self, marker):
        """Emit and track market maker trade markers."""
        self.add_marker(marker)

    def emit_trade(self, trade):
        """Emit individual trade data."""
        self.socketio.emit('trade', trade)

    def emit_aggregated_trade(self, aggregated_trade):
        """Emit aggregated trade data."""
        self.socketio.emit('aggregated_trade', aggregated_trade)

    def run_visualization(self):
        """Run continuous updates for visualization."""
        while True:
            self.update_orderbook()
            self.update_candlestick()

            time.sleep(1)  # Update every second

    def update_band_data(self, period=None):
        """Calculate a simple moving average (SMA) band."""
        try:
            period = period or Config.SMA_PERIOD
            if len(self.candlestick_data) >= period:
                # Get the last 100 candles for calculation
                recent_candles = self.candlestick_data[-100:]
                closes = [float(candle["close"]) for candle in recent_candles]
                
                sma_values = []
                # Calculate SMA for each point after we have enough data
                for i in range(period - 1, len(closes)):
                    window = closes[i - period + 1:i + 1]
                    sma = sum(window) / period
                    sma_values.append({
                        "time": recent_candles[i]["time"],
                        "value": sma
                    })
                
                if sma_values:
                    self.band_data = sma_values
                    self.socketio.emit("band", self.band_data)
                    logger.info(f"Updated SMA data with {len(sma_values)} points")
        except Exception as e:
            logger.error(f"Error updating band data: {str(e)}")
