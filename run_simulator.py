#!/usr/bin/env python3
"""Entry point for the Market Rush Simulator.

Delegates to run_simulation() in the simulator module, which creates a
market, an AAPL order book, an optional market maker, and the rush
simulator with the correct constructor arguments. The previous version of
this file passed Config.NUM_PARTICIPANTS as the `security_id` argument and
called a nonexistent .start() method.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.market.MarketRushSimulator import run_simulation

if __name__ == "__main__":
    # --no-market-maker runs order flow without the passive maker.
    enable_mm = "--no-market-maker" not in sys.argv
    run_simulation(enable_market_maker=enable_mm)
