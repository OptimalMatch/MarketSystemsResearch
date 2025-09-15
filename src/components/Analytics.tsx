/**
 * Analytics and System Monitoring Component
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Grid,
  Paper,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  LinearProgress,
  CircularProgress,
  Alert,
} from '@mui/material';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  Speed,
  TrendingUp,
  Assignment,
  AccountBalance,
  Warning,
  CheckCircle,
} from '@mui/icons-material';

import apiClient from '../api/client';

interface PerformanceMetrics {
  timestamp: string;
  orders_per_second: number;
  trades_per_second: number;
  latency_p50: number;
  latency_p95: number;
  latency_p99: number;
  memory_usage: number;
  cpu_usage: number;
}

interface TradingVolume {
  symbol: string;
  volume_24h: number;
  trades_count: number;
  unique_users: number;
}

const Analytics: React.FC = () => {
  const [performanceData, setPerformanceData] = useState<PerformanceMetrics[]>([]);
  const [volumeData, setVolumeData] = useState<TradingVolume[]>([]);
  const [systemMetrics, setSystemMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadAnalyticsData();
    const interval = setInterval(loadAnalyticsData, 30000); // Update every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const loadAnalyticsData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Generate mock performance data since real analytics endpoints don't exist yet
      const mockPerformanceData = generateMockPerformanceData();
      const mockVolumeData = generateMockVolumeData();
      const mockSystemMetrics = generateMockSystemMetrics();

      setPerformanceData(mockPerformanceData);
      setVolumeData(mockVolumeData);
      setSystemMetrics(mockSystemMetrics);

    } catch (err) {
      setError('Failed to load analytics data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const generateMockPerformanceData = (): PerformanceMetrics[] => {
    const data: PerformanceMetrics[] = [];
    const now = new Date();

    for (let i = 23; i >= 0; i--) {
      const timestamp = new Date(now.getTime() - i * 60 * 60 * 1000);
      data.push({
        timestamp: timestamp.toISOString(),
        orders_per_second: 800000 + Math.random() * 200000,
        trades_per_second: 1000 + Math.random() * 500,
        latency_p50: 0.5 + Math.random() * 1,
        latency_p95: 2 + Math.random() * 3,
        latency_p99: 5 + Math.random() * 5,
        memory_usage: 60 + Math.random() * 20,
        cpu_usage: 30 + Math.random() * 40,
      });
    }
    return data;
  };

  const generateMockVolumeData = (): TradingVolume[] => {
    return [
      { symbol: 'DEC/USD', volume_24h: 1250000, trades_count: 8500, unique_users: 342 },
      { symbol: 'BTC/USD', volume_24h: 850000, trades_count: 5200, unique_users: 189 },
      { symbol: 'ETH/USD', volume_24h: 720000, trades_count: 4100, unique_users: 156 },
      { symbol: 'DEC/BTC', volume_24h: 320000, trades_count: 1800, unique_users: 78 },
    ];
  };

  const generateMockSystemMetrics = () => {
    return {
      uptime: 172800, // 2 days in seconds
      total_orders: 2847592,
      total_trades: 156742,
      total_volume_usd: 89452673.45,
      active_users: 1247,
      matching_engine_health: 99.8,
      database_health: 99.9,
      api_health: 99.7,
      blockchain_health: 98.5,
    };
  };

  const formatNumber = (num: number, decimals = 0) => {
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

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${days}d ${hours}h ${minutes}m`;
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

  const COLORS = ['#8884d8', '#82ca9d', '#ffc658', '#ff7300'];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        System Analytics & Monitoring
      </Typography>

      {/* Key Metrics Overview */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center">
                <Speed color="primary" sx={{ mr: 2 }} />
                <Box>
                  <Typography color="textSecondary" variant="body2">
                    Orders/Second
                  </Typography>
                  <Typography variant="h5">
                    {formatNumber(performanceData[performanceData.length - 1]?.orders_per_second || 0, 0)}
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center">
                <TrendingUp color="success" sx={{ mr: 2 }} />
                <Box>
                  <Typography color="textSecondary" variant="body2">
                    Total Volume (24h)
                  </Typography>
                  <Typography variant="h5">
                    {formatCurrency(systemMetrics?.total_volume_usd || 0)}
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center">
                <Assignment color="info" sx={{ mr: 2 }} />
                <Box>
                  <Typography color="textSecondary" variant="body2">
                    Total Orders
                  </Typography>
                  <Typography variant="h5">
                    {formatNumber(systemMetrics?.total_orders || 0)}
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center">
                <AccountBalance color="warning" sx={{ mr: 2 }} />
                <Box>
                  <Typography color="textSecondary" variant="body2">
                    Active Users
                  </Typography>
                  <Typography variant="h5">
                    {formatNumber(systemMetrics?.active_users || 0)}
                  </Typography>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Performance Charts */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} lg={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Performance Metrics (24h)
            </Typography>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={performanceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(value) => new Date(value).toLocaleTimeString()}
                />
                <YAxis yAxisId="left" />
                <YAxis yAxisId="right" orientation="right" />
                <Tooltip
                  labelFormatter={(value) => new Date(value).toLocaleString()}
                  formatter={(value: number, name: string) => [
                    formatNumber(value, name.includes('latency') ? 2 : 0),
                    name.replace('_', ' ').toUpperCase()
                  ]}
                />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="orders_per_second"
                  stroke="#8884d8"
                  strokeWidth={2}
                  name="Orders/Second"
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="latency_p95"
                  stroke="#82ca9d"
                  strokeWidth={2}
                  name="Latency P95 (ms)"
                />
              </LineChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} lg={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              System Health
            </Typography>
            <Box sx={{ mb: 2 }}>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="body2">Matching Engine</Typography>
                <Typography variant="body2">{systemMetrics?.matching_engine_health}%</Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={systemMetrics?.matching_engine_health}
                color="success"
                sx={{ mb: 1 }}
              />
            </Box>

            <Box sx={{ mb: 2 }}>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="body2">Database</Typography>
                <Typography variant="body2">{systemMetrics?.database_health}%</Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={systemMetrics?.database_health}
                color="success"
                sx={{ mb: 1 }}
              />
            </Box>

            <Box sx={{ mb: 2 }}>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="body2">API Gateway</Typography>
                <Typography variant="body2">{systemMetrics?.api_health}%</Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={systemMetrics?.api_health}
                color="success"
                sx={{ mb: 1 }}
              />
            </Box>

            <Box sx={{ mb: 2 }}>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="body2">Blockchain</Typography>
                <Typography variant="body2">{systemMetrics?.blockchain_health}%</Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={systemMetrics?.blockchain_health}
                color="warning"
                sx={{ mb: 1 }}
              />
            </Box>

            <Box mt={2}>
              <Typography variant="body2" color="textSecondary">
                System Uptime: {formatUptime(systemMetrics?.uptime || 0)}
              </Typography>
            </Box>
          </Paper>
        </Grid>
      </Grid>

      {/* Trading Volume by Symbol */}
      <Grid container spacing={3}>
        <Grid item xs={12} lg={8}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Trading Volume by Symbol (24h)
            </Typography>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={volumeData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="symbol" />
                <YAxis />
                <Tooltip
                  formatter={(value: number) => [formatNumber(value), 'Volume']}
                />
                <Bar dataKey="volume_24h" fill="#8884d8" />
              </BarChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>

        <Grid item xs={12} lg={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Symbol Distribution
            </Typography>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={volumeData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ symbol, percent }) => `${symbol} (${(percent * 100).toFixed(0)}%)`}
                  outerRadius={80}
                  fill="#8884d8"
                  dataKey="volume_24h"
                >
                  {volumeData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number) => [formatNumber(value), 'Volume']}
                />
              </PieChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>
      </Grid>

      {/* Detailed Metrics Table */}
      <Grid container spacing={3} sx={{ mt: 1 }}>
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              Detailed Symbol Metrics
            </Typography>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Symbol</TableCell>
                    <TableCell align="right">24h Volume</TableCell>
                    <TableCell align="right">Trades</TableCell>
                    <TableCell align="right">Unique Users</TableCell>
                    <TableCell align="right">Avg Trade Size</TableCell>
                    <TableCell align="center">Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {volumeData.map((row) => (
                    <TableRow key={row.symbol}>
                      <TableCell>
                        <Chip label={row.symbol} variant="outlined" />
                      </TableCell>
                      <TableCell align="right">
                        {formatNumber(row.volume_24h)}
                      </TableCell>
                      <TableCell align="right">
                        {formatNumber(row.trades_count)}
                      </TableCell>
                      <TableCell align="right">
                        {formatNumber(row.unique_users)}
                      </TableCell>
                      <TableCell align="right">
                        {formatNumber(row.volume_24h / row.trades_count, 2)}
                      </TableCell>
                      <TableCell align="center">
                        <Chip
                          label="Active"
                          color="success"
                          size="small"
                          icon={<CheckCircle />}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};

export default Analytics;