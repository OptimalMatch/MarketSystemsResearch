from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import threading
import time
import json
from decimal import Decimal
from flask_cors import CORS
import os

class Visualization:
    def __init__(self, market):
        self.market = market
        self.orderbook_data = {"bids": [], "asks": []}
        self.candlestick_data = []
        self.band_data = []  # Store SMA data for bands
        self.markers = []  # To store emitted markers
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app)
        self.server_thread = None
        self.max_markers = 10  # Cap markers to prevent memory issues

        # Configure Flask routes
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            """Serve the TradingView visualization page."""
            return render_template("index.html")

        @self.socketio.on("connect")
        def on_connect():
            """Send initial data to the client when connected."""
            emit("orderbook", self.orderbook_data)
            emit("candlestick", self.candlestick_data)
            # Send stored markers to the client
            for marker in self.markers:
                emit("market_maker_marker", marker)

    def start_server(self, port=8084):
        """Start the Flask server in a separate thread."""
        self.server_thread = threading.Thread(
            target=lambda: self.socketio.run(self.app, host=os.getenv('IP', '0.0.0.0'), port=port, debug=False)
        )
        self.server_thread.daemon = True
        self.server_thread.start()

    def update_orderbook(self):
        """Update the order book data and emit it for the DOM chart."""
        for security_id, orderbook in self.market.orderbooks.items():
            # Prepare data for general orderbook usage
            self.orderbook_data = {
                "bids": [
                    {"price": float(order.price), "size": float(order.size - order.filled)}
                    for order in orderbook.bids[:10]
                ],
                "asks": [
                    {"price": float(order.price), "size": float(order.size - order.filled)}
                    for order in orderbook.asks[:10]
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

    def update_candlestick(self, interval=5):
        """Update candlestick data with the latest trades."""
        trades = self.market.orderbooks[next(iter(self.market.orderbooks))].trades
        if trades:
            current_time = int(time.time() // interval * interval)  # Align to the interval
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

            # Update the band data (SMA)
            self.update_band_data()

            self.socketio.emit("candlestick", self.candlestick_data)



    def update_band_data(self, period=5):
        """Calculate a simple moving average (SMA) band."""
        if len(self.candlestick_data) >= period:
            sma_values = []
            for i in range(len(self.candlestick_data) - period + 1):
                sma = sum(candle["close"] for candle in self.candlestick_data[i:i+period]) / period
                sma_values.append({
                    "time": self.candlestick_data[i + period - 1]["time"],
                    "value": sma
                })
            self.band_data = sma_values
            self.socketio.emit("band", self.band_data)

    def emit_market_maker_trade(self, marker):
        """Emit and track market maker trade markers."""
        if len(self.markers) >= self.max_markers:
            self.markers.pop(0)  # Maintain size limit
        self.markers.append(marker)
        #self.socketio.emit("market_maker_marker", marker)

    # def emit_market_maker_trade(self, marker):
    #     """Emit a market maker trade as a marker for the chart."""
    #     # Store the marker for future reference
    #     self.markers.append(marker)
    #
    #     #print(f"Added {marker}")
    #
    #     # Emit the marker via socket.io
    #     self.socketio.emit('market_maker_marker', {
    #         'time': marker['time'],  # Timestamp
    #         'position': marker['position'],  # Position on the chart
    #         'color': marker['color'],  # Color for the marker
    #         'shape': marker['shape'],  # Shape of the marker
    #         'text': marker['text'],  # Text to display
    #         'details': {  # Additional details for contextual information
    #             'price': marker['price'],
    #             'size': marker['size'],
    #             'security_id': marker['security_id'],
    #             'buyer_id': marker['buyer_id'],
    #             'seller_id': marker['seller_id']
    #         }
    #     })

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
