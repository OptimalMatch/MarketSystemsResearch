"""Configuration settings for the Market Systems Research application."""

class Config:
    # Server settings
    HOST = '0.0.0.0'
    PORT = 12084
    DEBUG = False

    # Market settings
    DEFAULT_SECURITY = 'AAPL'
    MARKET_MAKER_ID = 'mm001'
    MARKET_MAKER_CASH = '100000000000'
    MARKET_MAKER_SECURITIES = '1000000000'
    ENABLE_MARKET_MAKER = True

    # Supported securities
    SECURITIES = {
        'AAPL': {
            'name': 'Apple Inc.',
            'type': 'equity',
            'initial_price': '150.00'
        },
        'BTC': {
            'name': 'Bitcoin',
            'type': 'cryptocurrency',
            'initial_price': '45000.00',
            'decimals': 8
        },
        'DEC': {
            'name': 'DeCoin',
            'type': 'cryptocurrency',
            'initial_price': '100.00',
            'decimals': 8
        }
    }
    
    # Simulation settings
    SIMULATION_DURATION = 300  # seconds
    NUM_PARTICIPANTS = 10000
    ENABLE_SIMULATED_SELLERS = True
    
    # Visualization settings
    ORDERBOOK_DEPTH = 10
    CANDLESTICK_INTERVAL = 5  # seconds
    MAX_MARKERS = 10
    SMA_PERIOD = 5
    
    # Performance settings
    STATS_UPDATE_INTERVAL = 5  # seconds
    
    # Logging settings
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Trade export settings
    EXPORT_TRADES = False  # Set to True to enable trade log export
    TRADE_LOG_DIR = "logs"  # Directory to store trade logs
