-- Exchange Database Schema
-- PostgreSQL initialization script

-- Create database if not exists
-- This is handled by docker-compose environment variables

-- Create schema
CREATE SCHEMA IF NOT EXISTS exchange;

-- Set search path
SET search_path TO exchange, public;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    api_key VARCHAR(255) UNIQUE,
    api_secret_hash VARCHAR(255),
    decoin_address VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    kyc_status VARCHAR(50) DEFAULT 'pending',
    daily_volume_limit DECIMAL(20, 8) DEFAULT 100000.00000000
);

CREATE INDEX idx_users_api_key ON users(api_key);
CREATE INDEX idx_users_email ON users(email);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(100) UNIQUE NOT NULL,
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),
    status VARCHAR(20) NOT NULL DEFAULT 'new',
    quantity DECIMAL(20, 8) NOT NULL,
    price DECIMAL(20, 8),
    stop_price DECIMAL(20, 8),
    filled_quantity DECIMAL(20, 8) DEFAULT 0,
    average_price DECIMAL(20, 8),
    time_in_force VARCHAR(10) DEFAULT 'GTC',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id VARCHAR(100) UNIQUE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    buyer_order_id VARCHAR(100) REFERENCES orders(order_id),
    seller_order_id VARCHAR(100) REFERENCES orders(order_id),
    buyer_user_id UUID REFERENCES users(id),
    seller_user_id UUID REFERENCES users(id),
    price DECIMAL(20, 8) NOT NULL,
    quantity DECIMAL(20, 8) NOT NULL,
    maker_side VARCHAR(10) NOT NULL,
    taker_fee DECIMAL(20, 8) DEFAULT 0,
    maker_fee DECIMAL(20, 8) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_buyer_user ON trades(buyer_user_id);
CREATE INDEX idx_trades_seller_user ON trades(seller_user_id);
CREATE INDEX idx_trades_created_at ON trades(created_at DESC);

-- Balances table
CREATE TABLE IF NOT EXISTS balances (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    currency VARCHAR(10) NOT NULL,
    available DECIMAL(20, 8) DEFAULT 0,
    locked DECIMAL(20, 8) DEFAULT 0,
    total DECIMAL(20, 8) GENERATED ALWAYS AS (available + locked) STORED,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, currency)
);

CREATE INDEX idx_balances_user_currency ON balances(user_id, currency);

-- Deposits table
CREATE TABLE IF NOT EXISTS deposits (
    id BIGSERIAL PRIMARY KEY,
    deposit_id VARCHAR(100) UNIQUE NOT NULL,
    user_id UUID REFERENCES users(id),
    currency VARCHAR(10) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    blockchain_tx_hash VARCHAR(255),
    confirmations INT DEFAULT 0,
    required_confirmations INT DEFAULT 6,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_deposits_user_id ON deposits(user_id);
CREATE INDEX idx_deposits_status ON deposits(status);

-- Withdrawals table
CREATE TABLE IF NOT EXISTS withdrawals (
    id BIGSERIAL PRIMARY KEY,
    withdrawal_id VARCHAR(100) UNIQUE NOT NULL,
    user_id UUID REFERENCES users(id),
    currency VARCHAR(10) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    fee DECIMAL(20, 8) DEFAULT 0,
    address VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    blockchain_tx_hash VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_withdrawals_user_id ON withdrawals(user_id);
CREATE INDEX idx_withdrawals_status ON withdrawals(status);

-- DeCoin ledger transfers (internal)
CREATE TABLE IF NOT EXISTS ledger_transfers (
    id BIGSERIAL PRIMARY KEY,
    transfer_id VARCHAR(100) UNIQUE NOT NULL,
    from_address VARCHAR(100) NOT NULL,
    to_address VARCHAR(100) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    status VARCHAR(20) DEFAULT 'completed',
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_transfers_from ON ledger_transfers(from_address);
CREATE INDEX idx_transfers_to ON ledger_transfers(to_address);
CREATE INDEX idx_transfers_created_at ON ledger_transfers(created_at DESC);

-- Market data (OHLCV)
CREATE TABLE IF NOT EXISTS candles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    interval VARCHAR(10) NOT NULL,
    open_time TIMESTAMP WITH TIME ZONE NOT NULL,
    close_time TIMESTAMP WITH TIME ZONE NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    trades_count INT DEFAULT 0,
    UNIQUE(symbol, interval, open_time)
);

CREATE INDEX idx_candles_symbol_interval ON candles(symbol, interval, open_time DESC);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_created_at ON audit_log(created_at DESC);

-- Create update timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply update trigger to tables with updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_balances_updated_at BEFORE UPDATE ON balances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create initial admin user (for testing)
INSERT INTO users (username, email, api_key, api_secret_hash, kyc_status)
VALUES ('admin', 'admin@exchange.local', 'test-api-key-admin', 'hashed_secret', 'verified')
ON CONFLICT (username) DO NOTHING;

-- Create test users
INSERT INTO users (username, email, decoin_address, kyc_status)
VALUES
    ('alice', 'alice@test.com', 'DEC_alice_address', 'verified'),
    ('bob', 'bob@test.com', 'DEC_bob_address', 'verified'),
    ('charlie', 'charlie@test.com', 'DEC_charlie_address', 'verified')
ON CONFLICT (username) DO NOTHING;

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA exchange TO exchange_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA exchange TO exchange_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA exchange TO exchange_user;

-- Create indexes for performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_active
    ON orders(symbol, status)
    WHERE status IN ('new', 'partially_filled');

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_recent
    ON trades(created_at DESC)
    WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '1 day';

-- Add comments for documentation
COMMENT ON TABLE users IS 'Exchange user accounts';
COMMENT ON TABLE orders IS 'All orders placed on the exchange';
COMMENT ON TABLE trades IS 'Executed trades between orders';
COMMENT ON TABLE balances IS 'User cryptocurrency balances';
COMMENT ON TABLE deposits IS 'Cryptocurrency deposits to the exchange';
COMMENT ON TABLE withdrawals IS 'Cryptocurrency withdrawals from the exchange';
COMMENT ON TABLE ledger_transfers IS 'Internal DeCoin ledger transfers';
COMMENT ON TABLE candles IS 'Market data OHLCV candles';
COMMENT ON TABLE audit_log IS 'Security and compliance audit trail';

-- Performance statistics view
CREATE OR REPLACE VIEW exchange_stats AS
SELECT
    (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
    (SELECT COUNT(*) FROM orders WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours') as daily_orders,
    (SELECT COUNT(*) FROM trades WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours') as daily_trades,
    (SELECT SUM(quantity * price) FROM trades WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours') as daily_volume,
    (SELECT COUNT(DISTINCT symbol) FROM orders WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours') as active_pairs;

COMMENT ON VIEW exchange_stats IS 'Real-time exchange statistics';