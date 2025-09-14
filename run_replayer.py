#!/usr/bin/env python3
"""Entry point for Trade Log Replayer."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import after adding to path
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Replay trade logs through visualization')
    parser.add_argument('log_file', help='Path to the trade log CSV file')
    parser.add_argument('--speed', '-s', type=float, default=1.0,
                       help='Replay speed multiplier (default: 1.0)')
    parser.add_argument('--port', '-p', type=int, default=12084,
                       help='Web server port (default: 12084)')

    args = parser.parse_args()

    # Now import and run the replayer
    from src.visualization.TradeLogReplayer import TradeLogReplayer

    replayer = TradeLogReplayer(args.log_file, speed=args.speed, port=args.port)
    replayer.run()