#!/usr/bin/env python3
"""Entry point for running tests."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run market system tests')
    parser.add_argument('--test', '-t', choices=['crypto', 'basic', 'performance'],
                       default='crypto', help='Test to run (default: crypto)')

    args = parser.parse_args()

    if args.test == 'crypto':
        from src.tests.test_crypto import test_crypto_trading
        test_crypto_trading()
    elif args.test == 'basic':
        exec(open('src/tests/test.py').read())
    elif args.test == 'performance':
        exec(open('src/simulation/ExchangePerformanceTester.py').read())