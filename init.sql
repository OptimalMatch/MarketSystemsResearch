-- Exchange Database Initialization Script

-- Create schema
CREATE SCHEMA IF NOT EXISTS exchange;

-- Set default schema
SET search_path TO exchange;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active'
);

-- DeCoin transfers table
CREATE TABLE IF NOT EXISTS decoin_transfers (
    id VARCHAR(64) PRIMARY KEY,
    from_address VARCHAR(64) NOT NULL,
    to_address VARCHAR(64) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL,
    tx_hash VARCHAR(64),
    block_height INTEGER,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- DeCoin balances table
CREATE TABLE IF NOT EXISTS decoin_balances (
    address VARCHAR(64) PRIMARY KEY,
    balance DECIMAL(20, 8) NOT NULL DEFAULT 0,
    pending DECIMAL(20, 8) NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8),
    filled_quantity DECIMAL(20, 8) DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    buyer_order_id BIGINT,
    seller_order_id BIGINT,
    price DECIMAL(20, 8) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    buyer_user_id VARCHAR(64),
    seller_user_id VARCHAR(64),
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Risk profiles table
CREATE TABLE IF NOT EXISTS risk_profiles (
    user_id VARCHAR(64) PRIMARY KEY,
    max_position_size DECIMAL(20, 8),
    max_daily_loss DECIMAL(20, 8),
    max_order_size DECIMAL(20, 8),
    max_leverage DECIMAL(10, 2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Market data snapshots table
CREATE TABLE IF NOT EXISTS market_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    best_bid DECIMAL(20, 8),
    best_ask DECIMAL(20, 8),
    last_price DECIMAL(20, 8),
    volume_24h DECIMAL(20, 8),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_transfers_from ON decoin_transfers(from_address, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_transfers_to ON decoin_transfers(to_address, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_transfers_status ON decoin_transfers(status);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol, status);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_users ON trades(buyer_user_id, seller_user_id);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA exchange TO exchange_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA exchange TO exchange_user;

-- Insert initial data
INSERT INTO users (user_id, email) VALUES
    ('system', 'system@exchange.local'),
    ('market_maker', 'mm@exchange.local')
ON CONFLICT (user_id) DO NOTHING;

-- Initial risk profiles
INSERT INTO risk_profiles (user_id, max_position_size, max_daily_loss, max_order_size, max_leverage) VALUES
    ('market_maker', 1000000, 50000, 10000, 10)
ON CONFLICT (user_id) DO NOTHING;