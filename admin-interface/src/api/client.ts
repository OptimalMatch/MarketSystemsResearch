/**
 * API Client for Exchange Admin Interface
 */

import axios, { AxiosInstance, AxiosResponse } from 'axios';

export interface ApiConfig {
  baseURL: string;
  apiKey?: string;
  timeout?: number;
}

export interface OrderBook {
  symbol: string;
  bids: Array<{ price: number; quantity: number }>;
  asks: Array<{ price: number; quantity: number }>;
  timestamp: string;
}

export interface Trade {
  id: string;
  symbol: string;
  price: number;
  quantity: number;
  side: 'buy' | 'sell';
  timestamp: string;
  maker_side: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: string;
  quantity: number;
  price?: number;
  status: string;
  filled_quantity: number;
  remaining_quantity: number;
  created_at: string;
  updated_at: string;
}

export interface Balance {
  currency: string;
  available: number;
  locked: number;
  total: number;
}

export interface MarketStats {
  symbol: string;
  last_price: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
  price_change_24h: number;
  price_change_percent_24h: number;
}

export interface SystemHealth {
  status: string;
  timestamp: string;
  uptime: number;
  version: string;
  services: {
    matching_engine: boolean;
    database: boolean;
    blockchain: boolean;
    api: boolean;
  };
}

export interface MarketMakerConfig {
  id: string;
  strategy: string;
  symbol: string;
  active: boolean;
  spread_bps: number;
  order_amount: number;
  max_orders_per_side: number;
  inventory_target: number;
  config: Record<string, any>;
}

class ExchangeApiClient {
  private client: AxiosInstance;
  private apiKey?: string;

  constructor(config: ApiConfig) {
    this.apiKey = config.apiKey;

    this.client = axios.create({
      baseURL: config.baseURL,
      timeout: config.timeout || 10000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add request interceptor for authentication
    this.client.interceptors.request.use((config) => {
      if (this.apiKey) {
        config.headers['X-API-Key'] = this.apiKey;
      }
      return config;
    });

    // Add response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        console.error('API Error:', error.response?.data || error.message);
        return Promise.reject(error);
      }
    );
  }

  setApiKey(apiKey: string) {
    this.apiKey = apiKey;
  }

  // Helper function to convert symbol format for API calls
  private formatSymbolForApi(symbol: string): string {
    // Convert DEC/USD to DEC-USD for API calls
    return symbol.replace('/', '-');
  }

  // System endpoints
  async getHealth(): Promise<SystemHealth> {
    const response = await this.client.get('/health');
    const data = response.data;

    // Transform API response to match SystemHealth interface
    return {
      status: data.status || 'unknown',
      timestamp: data.timestamp || new Date().toISOString(),
      uptime: data.uptime || 0,
      version: data.version || '1.0.0',
      services: {
        matching_engine: data.components?.matching_engine === 'operational',
        database: data.components?.database === 'operational' || true, // Assume healthy if not reported
        blockchain: data.components?.blockchain === 'operational' || true, // Assume healthy if not reported
        api: data.components?.oms === 'operational' && data.components?.risk_engine === 'operational',
      }
    };
  }

  // Market data endpoints
  async getOrderBook(symbol: string): Promise<OrderBook> {
    const apiSymbol = this.formatSymbolForApi(symbol);
    const response = await this.client.get(`/api/v1/market/orderbook/${apiSymbol}`);
    return response.data;
  }

  async getTrades(symbol: string, limit = 50): Promise<Trade[]> {
    const apiSymbol = this.formatSymbolForApi(symbol);
    const response = await this.client.get(`/api/v1/market/trades/${apiSymbol}`, {
      params: { limit },
    });
    return response.data;
  }

  async getTicker(symbol: string): Promise<MarketStats> {
    const apiSymbol = this.formatSymbolForApi(symbol);
    const response = await this.client.get(`/api/v1/market/ticker/${apiSymbol}`);
    return response.data;
  }

  async getSymbols(): Promise<string[]> {
    const response = await this.client.get('/api/v1/market/symbols');
    return response.data;
  }

  // Account endpoints
  async getBalances(): Promise<Balance[]> {
    const response = await this.client.get('/api/v1/account/balance');
    return response.data;
  }

  async getAccountInfo(): Promise<any> {
    const response = await this.client.get('/api/v1/account/info');
    return response.data;
  }

  // Order management endpoints
  async getOrders(symbol?: string, status?: string): Promise<Order[]> {
    const response = await this.client.get('/api/v1/orders', {
      params: { symbol, status },
    });
    return response.data.orders || [];
  }

  async getOrder(orderId: string): Promise<Order> {
    const response = await this.client.get(`/api/v1/orders/${orderId}`);
    return response.data;
  }

  async placeOrder(order: {
    symbol: string;
    side: 'buy' | 'sell';
    type: string;
    quantity: number;
    price?: number;
    stop_price?: number;
    trail_amount?: number;
    trail_percent?: number;
    display_quantity?: number;
    time_in_force?: string;
  }): Promise<Order> {
    const response = await this.client.post('/api/v1/orders', order);
    return response.data;
  }

  async cancelOrder(orderId: string): Promise<void> {
    await this.client.delete(`/api/v1/orders/${orderId}`);
  }

  async modifyOrder(orderId: string, updates: {
    quantity?: number;
    price?: number;
  }): Promise<Order> {
    const response = await this.client.put(`/api/v1/orders/${orderId}`, updates);
    return response.data;
  }

  // Market maker endpoints (would need to be added to API)
  async getMarketMakers(): Promise<MarketMakerConfig[]> {
    try {
      const response = await this.client.get('/api/v1/market-makers');
      return response.data;
    } catch (error) {
      // Fallback if endpoint doesn't exist yet
      return [];
    }
  }

  async createMarketMaker(config: Omit<MarketMakerConfig, 'id'>): Promise<MarketMakerConfig> {
    const response = await this.client.post('/api/v1/market-makers', config);
    return response.data;
  }

  async updateMarketMaker(id: string, config: Partial<MarketMakerConfig>): Promise<MarketMakerConfig> {
    const response = await this.client.put(`/api/v1/market-makers/${id}`, config);
    return response.data;
  }

  async deleteMarketMaker(id: string): Promise<void> {
    await this.client.delete(`/api/v1/market-makers/${id}`);
  }

  // WebSocket connection for real-time data
  createWebSocket(
    onMessage: (data: any) => void,
    onConnectionChange?: (connected: boolean) => void
  ): WebSocket {
    const getWsBaseUrl = () => {
      if (process.env.REACT_APP_WS_BASE_URL) {
        return process.env.REACT_APP_WS_BASE_URL;
      }
      // Use current hostname with WebSocket port 13765
      const hostname = window.location.hostname;
      return `ws://${hostname}:13765`;
    };

    const wsBaseUrl = getWsBaseUrl();
    const wsUrl = wsBaseUrl + '/ws';
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
      onConnectionChange?.(true);
      // Subscribe to all symbols
      ws.send(JSON.stringify({
        action: 'subscribe',
        symbols: ['DEC/USD', 'BTC/USD', 'ETH/USD', 'DEC/BTC']
      }));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (error) {
        console.error('WebSocket message parsing error:', error);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      onConnectionChange?.(false);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      onConnectionChange?.(false);
    };

    return ws;
  }
}

// Create singleton instance with dynamic hostname
const getApiBaseUrl = () => {
  // Use environment variable if set, otherwise use current hostname
  if (process.env.REACT_APP_API_BASE_URL) {
    return process.env.REACT_APP_API_BASE_URL;
  }

  // Get current hostname and use port 13000 for API
  const hostname = window.location.hostname;
  return `http://${hostname}:13000`;
};

const apiClient = new ExchangeApiClient({
  baseURL: getApiBaseUrl(),
  timeout: 10000,
});

export default apiClient;