from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import threading
import time
import json
from decimal import Decimal

class Visualization:
    def __init__(self, market):
        self.market = market
        self.orderbook_data = {"bids": [], "asks": []}
        self.candlestick_data = []
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app)
        self.server_thread = None

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

    def start_server(self, port=5000):
        """Start the Flask server in a separate thread."""
        self.server_thread = threading.Thread(
            target=lambda: self.socketio.run(self.app, port=port, debug=False, allow_unsafe_werkzeug=True)
        )
        self.server_thread.daemon = True
        self.server_thread.start()

    def update_orderbook(self):
        """Update the order book data."""
        for security_id, orderbook in self.market.orderbooks.items():
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
                candle['high'] = max(candle['high'], trade_price)
                candle['low'] = min(candle['low'], trade_price)
                candle['close'] = trade_price
            else:
                # Create a new candle
                self.candlestick_data.append({
                    'time': current_time,
                    'open': trade_price,
                    'high': trade_price,
                    'low': trade_price,
                    'close': trade_price
                })

            self.socketio.emit("candlestick", self.candlestick_data)
            print(f"Updated candlestick data: {self.candlestick_data}")  # Debug log

    def run_visualization(self):
        """Run continuous updates for visualization."""
        while True:
            self.update_orderbook()
            self.update_candlestick()
            time.sleep(1)  # Update every second
