#!/usr/bin/env python3
"""
WebSocket Data Feed Service
Real-time market data distribution
"""

import asyncio
import os
import signal
import sys
from .websocket_server import WebSocketDataFeed

class DataFeedService:
    def __init__(self):
        # Configuration
        self.host = "0.0.0.0"
        self.port = int(os.getenv('WEBSOCKET_PORT', 13765))
        self.use_binary = os.getenv('USE_BINARY_PROTOCOL', 'true').lower() == 'true'

        # Initialize WebSocket server
        self.server = WebSocketDataFeed(
            host=self.host,
            port=self.port,
            use_binary=self.use_binary
        )

        print(f"WebSocket Data Feed Service initialized")
        print(f"Listening on: ws://{self.host}:{self.port}")
        print(f"Protocol: {'Binary (MessagePack)' if self.use_binary else 'JSON'}")

    async def run(self):
        """Start the WebSocket server"""
        await self.server.start()

    def shutdown(self, signum, frame):
        """Graceful shutdown"""
        print("\nShutting down WebSocket Data Feed Service...")
        sys.exit(0)

if __name__ == "__main__":
    service = DataFeedService()

    # Set up signal handlers
    signal.signal(signal.SIGINT, service.shutdown)
    signal.signal(signal.SIGTERM, service.shutdown)

    # Run service
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        pass