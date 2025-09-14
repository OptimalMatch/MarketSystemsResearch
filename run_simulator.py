#!/usr/bin/env python3
"""Entry point for Market Rush Simulator."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.market.MarketRushSimulator import MarketRushSimulator
from src.core.Exchange import Market
from src.utils.config import Config

if __name__ == "__main__":
    market = Market()
    simulator = MarketRushSimulator(market, Config.NUM_PARTICIPANTS)
    simulator.start()