"""Configuration settings for the Market Systems Research application."""

class Config:
    # Server settings
    HOST = '0.0.0.0'
    PORT = 8084
    DEBUG = False
    
    # Market settings
    DEFAULT_SECURITY = 'AAPL'
    MARKET_MAKER_ID = 'mm001'
    MARKET_MAKER_CASH = '100000000000'
    MARKET_MAKER_SECURITIES = '1000000000'
    ENABLE_MARKET_MAKER = True
    
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
