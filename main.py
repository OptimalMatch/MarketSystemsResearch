#!/usr/bin/env python3
"""Main entry point for the Market Systems Research application."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.visualization.VisualServer import MarketServer

if __name__ == "__main__":
    server = MarketServer()