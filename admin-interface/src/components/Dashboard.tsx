/**
 * Main Trading Dashboard Component
 */

import React, { useState, useEffect } from 'react';
import {
  Grid,
  Paper,
  Typography,
  Box,
  Card,
  CardContent,
  Chip,
  Alert,
  CircularProgress,
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  ShowChart,
  AccountBalance,
  Speed,
} from '@mui/icons-material';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts';

import apiClient, { MarketStats, SystemHealth, OrderBook, Trade } from '../api/client';
import OrderBookComponent from './OrderBook';
import TradeHistory from './TradeHistory';
import SystemStatus from './SystemStatus';

interface DashboardProps {
  selectedSymbol: string;
  onSymbolChange: (symbol: string) => void;
}

interface PriceData {
  timestamp: string;
  price: number;
  volume: number;
}

const Dashboard: React.FC<DashboardProps> = ({ selectedSymbol, onSymbolChange }) => {
  const [marketStats, setMarketStats] = useState<MarketStats | null>(null);
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null);
  const [orderBook, setOrderBook] = useState<OrderBook | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [priceHistory, setPriceHistory] = useState<PriceData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    loadInitialData();
    setupWebSocket();

    const interval = setInterval(() => {
      loadMarketData();
    }, 5000);

    return () => {
      clearInterval(interval);
    };
  }, [selectedSymbol]);

  const loadInitialData = async () => {
    try {
      setLoading(true);
      await Promise.all([
        loadMarketData(),
        loadSystemHealth(),
      ]);
    } catch (err) {
      setError('Failed to load dashboard data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadMarketData = async () => {
    try {
      const [statsData, bookData, tradesData] = await Promise.all([
        apiClient.getTicker(selectedSymbol),
        apiClient.getOrderBook(selectedSymbol),
        apiClient.getTrades(selectedSymbol, 20),
      ]);

      setMarketStats(statsData);
      setOrderBook(bookData);
      setTrades(tradesData);

      // Update price history
      if (statsData.last_price) {
        setPriceHistory(prev => {
          const newData = [...prev, {
            timestamp: new Date().toISOString(),
            price: statsData.last_price,
            volume: statsData.volume_24h,
          }];
          return newData.slice(-50); // Keep last 50 points
        });
      }
    } catch (err) {
      console.error('Failed to load market data:', err);
    }
  };

  const loadSystemHealth = async () => {
    try {
      const health = await apiClient.getHealth();
      setSystemHealth(health);
    } catch (err) {
      console.error('Failed to load system health:', err);
    }
  };

  const setupWebSocket = () => {
    try {
      const ws = apiClient.createWebSocket(
        (data) => {
          // console.log('WebSocket message received:', data.type, data.symbol, selectedSymbol);

          if (data.type === 'trade' && data.symbol === selectedSymbol) {
            setTrades(prev => [data.data, ...prev.slice(0, 19)]);

            // Update price history
            setPriceHistory(prev => {
              const timestamp = new Date().toISOString();
              const newData = [...prev, {
                timestamp,
                price: data.data.price,
                volume: data.data.quantity,
              }];
              const result = newData.slice(-50);
              // Commented out to reduce console noise
              // console.log('Price history updated:', {
              //   timestamp,
              //   price: data.data.price,
              //   totalPoints: result.length
              // });
              return result;
            });
          }

          if (data.type === 'ticker' && data.symbol === selectedSymbol) {
            // Update market stats from ticker data
            const tickerData = data.data;
            // console.log('Processing ticker for', data.symbol, 'selectedSymbol:', selectedSymbol);
            // console.log('Ticker data fields:', Object.keys(tickerData));
            // console.log('Ticker data values:', {
            //   last: tickerData.last,
            //   volume_24h: tickerData.volume_24h,
            //   price_change_percent_24h: tickerData.price_change_percent_24h
            // });

            const newMarketStats = {
              symbol: selectedSymbol,
              last_price: tickerData.last || 0,
              price_change_24h: tickerData.price_change_24h || 0,
              price_change_percent_24h: tickerData.price_change_percent_24h || 0,
              volume_24h: tickerData.volume_24h || 0,
              high_24h: tickerData.high_24h || 0,
              low_24h: tickerData.low_24h || 0,
              timestamp: new Date().toISOString()
            };

            // console.log('Setting new market stats:', newMarketStats);
            setMarketStats(newMarketStats);
          }

          if (data.type === 'orderbook' && data.symbol === selectedSymbol) {
            // Transform orderbook arrays to objects
            const transformedOrderBook = {
              ...data.data,
              bids: (data.data.bids || []).map(([price, quantity]: [number, number]) => ({ price, quantity })),
              asks: (data.data.asks || []).map(([price, quantity]: [number, number]) => ({ price, quantity }))
            };
            setOrderBook(transformedOrderBook);
          }
        },
        (connected) => {
          // console.log('WebSocket connection state changed:', connected);
          setWsConnected(connected);
        }
      );

      return () => {
        ws.close();
      };
    } catch (err) {
      console.error('WebSocket setup failed:', err);
      setWsConnected(false);
    }
  };

  const formatNumber = (num: number, decimals = 2) => {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(num);
  };

  const formatCurrency = (num: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(num);
  };

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="400px">
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  return (
    <Box sx={{ flexGrow: 1, p: 3 }}>
      {/* Header Stats */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    Last Price
                  </Typography>
                  <Typography variant="h5">
                    {marketStats ? formatCurrency(marketStats.last_price) : '-'}
                  </Typography>
                  {marketStats && (
                    <Box display="flex" alignItems="center" mt={1}>
                      {marketStats.price_change_24h >= 0 ? (
                        <TrendingUp color="success" fontSize="small" />
                      ) : (
                        <TrendingDown color="error" fontSize="small" />
                      )}
                      <Typography
                        variant="body2"
                        color={marketStats.price_change_24h >= 0 ? 'success.main' : 'error.main'}
                        sx={{ ml: 0.5 }}
                      >
                        {formatNumber(marketStats.price_change_percent_24h, 2)}%
                      </Typography>
                    </Box>
                  )}
                </Box>
                <ShowChart color="primary" fontSize="large" />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    24h Volume
                  </Typography>
                  <Typography variant="h5">
                    {marketStats ? formatNumber(marketStats.volume_24h, 0) : '-'}
                  </Typography>
                  <Typography variant="body2" color="textSecondary">
                    {selectedSymbol.split('/')[0]}
                  </Typography>
                </Box>
                <AccountBalance color="primary" fontSize="large" />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    24h High
                  </Typography>
                  <Typography variant="h6">
                    {marketStats ? formatCurrency(marketStats.high_24h) : '-'}
                  </Typography>
                  <Typography color="textSecondary" gutterBottom variant="body2" sx={{ mt: 1 }}>
                    24h Low
                  </Typography>
                  <Typography variant="h6">
                    {marketStats ? formatCurrency(marketStats.low_24h) : '-'}
                  </Typography>
                </Box>
                <TrendingUp color="primary" fontSize="large" />
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center" justifyContent="space-between">
                <Box>
                  <Typography color="textSecondary" gutterBottom variant="body2">
                    System Status
                  </Typography>
                  <Box display="flex" alignItems="center" gap={1}>
                    <Chip
                      label={wsConnected ? "Live" : "Disconnected"}
                      color={wsConnected ? "success" : "error"}
                      size="small"
                    />
                    {systemHealth && (
                      <Chip
                        label={systemHealth.status}
                        color={systemHealth.status === 'healthy' ? "success" : "warning"}
                        size="small"
                      />
                    )}
                  </Box>
                </Box>
                <Speed color="primary" fontSize="large" />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Price Chart */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} lg={8}>
          <Paper sx={{ p: 2, height: 400 }}>
            <Typography variant="h6" gutterBottom>
              Price Chart - {selectedSymbol} ({priceHistory.length} points)
            </Typography>
            <ResponsiveContainer width="100%" height="90%">
              <AreaChart data={priceHistory}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tickFormatter={(value) => formatCurrency(value)}
                  domain={['dataMin - 0.1', 'dataMax + 0.1']}
                  scale="linear"
                />
                <Tooltip
                  labelFormatter={(value) => new Date(value).toLocaleString()}
                  formatter={(value: number) => [formatCurrency(value), 'Price']}
                />
                <Area
                  type="monotone"
                  dataKey="price"
                  stroke="#1976d2"
                  fill="url(#colorPrice)"
                  strokeWidth={2}
                />
                <defs>
                  <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1976d2" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#1976d2" stopOpacity={0} />
                  </linearGradient>
                </defs>
              </AreaChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} lg={4}>
          <SystemStatus systemHealth={systemHealth} />
        </Grid>
      </Grid>

      {/* Order Book and Trade History */}
      <Grid container spacing={3}>
        <Grid item xs={12} lg={6}>
          <OrderBookComponent orderBook={orderBook} symbol={selectedSymbol} />
        </Grid>

        <Grid item xs={12} lg={6}>
          <TradeHistory trades={trades} symbol={selectedSymbol} />
        </Grid>
      </Grid>
    </Box>
  );
};

export default Dashboard;