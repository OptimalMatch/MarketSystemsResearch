/**
 * Order Management Interface
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Alert,
  Tabs,
  Tab,
  Grid,
} from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import {
  Add,
  Cancel,
  Edit,
  Refresh,
  TrendingUp,
  TrendingDown,
} from '@mui/icons-material';

import apiClient, { Order } from '../api/client';

interface OrderManagementProps {
  selectedSymbol: string;
}

interface NewOrderForm {
  symbol: string;
  side: 'buy' | 'sell';
  type: string;
  quantity: string;
  price: string;
  stop_price: string;
  trail_amount: string;
  trail_percent: string;
  display_quantity: string;
  time_in_force: string;
}

const OrderManagement: React.FC<OrderManagementProps> = ({ selectedSymbol }) => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orderDialogOpen, setOrderDialogOpen] = useState(false);
  const [selectedTab, setSelectedTab] = useState(0);
  const [newOrder, setNewOrder] = useState<NewOrderForm>({
    symbol: selectedSymbol,
    side: 'buy',
    type: 'limit',
    quantity: '',
    price: '',
    stop_price: '',
    trail_amount: '',
    trail_percent: '',
    display_quantity: '',
    time_in_force: 'GTC',
  });

  useEffect(() => {
    loadOrders();
    const interval = setInterval(loadOrders, 5000);
    return () => clearInterval(interval);
  }, [selectedSymbol]);

  useEffect(() => {
    setNewOrder(prev => ({ ...prev, symbol: selectedSymbol }));
  }, [selectedSymbol]);

  const loadOrders = async () => {
    try {
      setLoading(true);
      setError(null);
      const ordersData = await apiClient.getOrders(selectedSymbol);
      setOrders(ordersData);
    } catch (err) {
      setError('Failed to load orders');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handlePlaceOrder = async () => {
    try {
      setError(null);

      const orderData: any = {
        symbol: newOrder.symbol,
        side: newOrder.side,
        type: newOrder.type,
        quantity: parseFloat(newOrder.quantity),
        time_in_force: newOrder.time_in_force,
      };

      // Add conditional fields based on order type
      if (newOrder.type === 'limit' || newOrder.type === 'stop_limit') {
        orderData.price = parseFloat(newOrder.price);
      }

      if (newOrder.type === 'stop_loss' || newOrder.type === 'stop_limit') {
        orderData.stop_price = parseFloat(newOrder.stop_price);
      }

      if (newOrder.type === 'trailing_stop') {
        if (newOrder.trail_amount) {
          orderData.trail_amount = parseFloat(newOrder.trail_amount);
        }
        if (newOrder.trail_percent) {
          orderData.trail_percent = parseFloat(newOrder.trail_percent);
        }
      }

      if (newOrder.type === 'iceberg' && newOrder.display_quantity) {
        orderData.display_quantity = parseFloat(newOrder.display_quantity);
      }

      await apiClient.placeOrder(orderData);
      setOrderDialogOpen(false);
      loadOrders();

      // Reset form
      setNewOrder({
        symbol: selectedSymbol,
        side: 'buy',
        type: 'limit',
        quantity: '',
        price: '',
        stop_price: '',
        trail_amount: '',
        trail_percent: '',
        display_quantity: '',
        time_in_force: 'GTC',
      });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to place order');
    }
  };

  const handleCancelOrder = async (orderId: string) => {
    try {
      await apiClient.cancelOrder(orderId);
      loadOrders();
    } catch (err) {
      setError('Failed to cancel order');
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value);
  };

  const formatNumber = (value: number, decimals = 4) => {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);
  };

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'filled': return 'success';
      case 'cancelled': return 'error';
      case 'partially_filled': return 'warning';
      case 'new': return 'info';
      default: return 'default';
    }
  };

  const filterOrdersByStatus = (status: string) => {
    if (status === 'all') return orders;
    return orders.filter(order => order.status.toLowerCase() === status);
  };

  const activeOrders = filterOrdersByStatus('new').concat(filterOrdersByStatus('partially_filled'));
  const filledOrders = filterOrdersByStatus('filled');
  const cancelledOrders = filterOrdersByStatus('cancelled');

  const columns: GridColDef[] = [
    {
      field: 'id',
      headerName: 'Order ID',
      width: 120,
      renderCell: (params) => (
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          {params.value.slice(-8)}
        </Typography>
      ),
    },
    {
      field: 'symbol',
      headerName: 'Symbol',
      width: 100,
    },
    {
      field: 'side',
      headerName: 'Side',
      width: 80,
      renderCell: (params) => (
        <Chip
          label={params.value.toUpperCase()}
          color={params.value === 'buy' ? 'success' : 'error'}
          size="small"
          icon={params.value === 'buy' ? <TrendingUp /> : <TrendingDown />}
        />
      ),
    },
    {
      field: 'type',
      headerName: 'Type',
      width: 100,
      renderCell: (params) => (
        <Chip label={params.value} size="small" variant="outlined" />
      ),
    },
    {
      field: 'quantity',
      headerName: 'Quantity',
      width: 120,
      align: 'right',
      renderCell: (params) => formatNumber(params.value),
    },
    {
      field: 'price',
      headerName: 'Price',
      width: 120,
      align: 'right',
      renderCell: (params) => params.value ? formatCurrency(params.value) : '-',
    },
    {
      field: 'filled_quantity',
      headerName: 'Filled',
      width: 120,
      align: 'right',
      renderCell: (params) => formatNumber(params.value),
    },
    {
      field: 'remaining_quantity',
      headerName: 'Remaining',
      width: 120,
      align: 'right',
      renderCell: (params) => formatNumber(params.value),
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 120,
      renderCell: (params) => (
        <Chip
          label={params.value}
          color={getStatusColor(params.value)}
          size="small"
        />
      ),
    },
    {
      field: 'created_at',
      headerName: 'Created',
      width: 150,
      renderCell: (params) => new Date(params.value).toLocaleString(),
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 120,
      sortable: false,
      renderCell: (params: GridRowParams) => (
        <Box>
          {(params.row.status === 'new' || params.row.status === 'partially_filled') && (
            <Button
              size="small"
              color="error"
              onClick={() => handleCancelOrder(params.row.id)}
              startIcon={<Cancel />}
            >
              Cancel
            </Button>
          )}
        </Box>
      ),
    },
  ];

  const getTabData = () => {
    switch (selectedTab) {
      case 0: return activeOrders;
      case 1: return filledOrders;
      case 2: return cancelledOrders;
      case 3: return orders;
      default: return orders;
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Order Management</Typography>
        <Box>
          <Button
            variant="outlined"
            onClick={loadOrders}
            startIcon={<Refresh />}
            sx={{ mr: 2 }}
          >
            Refresh
          </Button>
          <Button
            variant="contained"
            onClick={() => setOrderDialogOpen(true)}
            startIcon={<Add />}
          >
            New Order
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* Order Tabs */}
      <Paper sx={{ mb: 3 }}>
        <Tabs
          value={selectedTab}
          onChange={(_, newValue) => setSelectedTab(newValue)}
          indicatorColor="primary"
          textColor="primary"
        >
          <Tab label={`Active (${activeOrders.length})`} />
          <Tab label={`Filled (${filledOrders.length})`} />
          <Tab label={`Cancelled (${cancelledOrders.length})`} />
          <Tab label={`All (${orders.length})`} />
        </Tabs>
      </Paper>

      {/* Orders Table */}
      <Paper>
        <DataGrid
          rows={getTabData()}
          columns={columns}
          pageSize={25}
          rowsPerPageOptions={[25, 50, 100]}
          loading={loading}
          autoHeight
          disableSelectionOnClick
          sx={{
            '& .MuiDataGrid-cell': {
              borderBottom: '1px solid #f0f0f0',
            },
          }}
        />
      </Paper>

      {/* New Order Dialog */}
      <Dialog
        open={orderDialogOpen}
        onClose={() => setOrderDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Place New Order</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Symbol</InputLabel>
                <Select
                  value={newOrder.symbol}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, symbol: e.target.value }))}
                >
                  <MenuItem value="DEC/USD">DEC/USD</MenuItem>
                  <MenuItem value="BTC/USD">BTC/USD</MenuItem>
                  <MenuItem value="ETH/USD">ETH/USD</MenuItem>
                  <MenuItem value="DEC/BTC">DEC/BTC</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Side</InputLabel>
                <Select
                  value={newOrder.side}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, side: e.target.value as 'buy' | 'sell' }))}
                >
                  <MenuItem value="buy">Buy</MenuItem>
                  <MenuItem value="sell">Sell</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Order Type</InputLabel>
                <Select
                  value={newOrder.type}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, type: e.target.value }))}
                >
                  <MenuItem value="limit">Limit</MenuItem>
                  <MenuItem value="market">Market</MenuItem>
                  <MenuItem value="stop_loss">Stop Loss</MenuItem>
                  <MenuItem value="stop_limit">Stop Limit</MenuItem>
                  <MenuItem value="trailing_stop">Trailing Stop</MenuItem>
                  <MenuItem value="iceberg">Iceberg</MenuItem>
                  <MenuItem value="take_profit">Take Profit</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Quantity"
                type="number"
                value={newOrder.quantity}
                onChange={(e) => setNewOrder(prev => ({ ...prev, quantity: e.target.value }))}
                inputProps={{ step: "0.0001" }}
              />
            </Grid>

            {(newOrder.type === 'limit' || newOrder.type === 'stop_limit') && (
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Price"
                  type="number"
                  value={newOrder.price}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, price: e.target.value }))}
                  inputProps={{ step: "0.01" }}
                />
              </Grid>
            )}

            {(newOrder.type === 'stop_loss' || newOrder.type === 'stop_limit' || newOrder.type === 'take_profit') && (
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Stop Price"
                  type="number"
                  value={newOrder.stop_price}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, stop_price: e.target.value }))}
                  inputProps={{ step: "0.01" }}
                />
              </Grid>
            )}

            {newOrder.type === 'trailing_stop' && (
              <>
                <Grid item xs={12} sm={6}>
                  <TextField
                    fullWidth
                    label="Trail Amount"
                    type="number"
                    value={newOrder.trail_amount}
                    onChange={(e) => setNewOrder(prev => ({ ...prev, trail_amount: e.target.value }))}
                    inputProps={{ step: "0.01" }}
                    helperText="Fixed amount trailing"
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <TextField
                    fullWidth
                    label="Trail Percent"
                    type="number"
                    value={newOrder.trail_percent}
                    onChange={(e) => setNewOrder(prev => ({ ...prev, trail_percent: e.target.value }))}
                    inputProps={{ step: "0.1" }}
                    helperText="Percentage trailing"
                  />
                </Grid>
              </>
            )}

            {newOrder.type === 'iceberg' && (
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Display Quantity"
                  type="number"
                  value={newOrder.display_quantity}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, display_quantity: e.target.value }))}
                  inputProps={{ step: "0.0001" }}
                  helperText="Visible portion"
                />
              </Grid>
            )}

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Time in Force</InputLabel>
                <Select
                  value={newOrder.time_in_force}
                  onChange={(e) => setNewOrder(prev => ({ ...prev, time_in_force: e.target.value }))}
                >
                  <MenuItem value="GTC">Good Till Cancelled</MenuItem>
                  <MenuItem value="IOC">Immediate or Cancel</MenuItem>
                  <MenuItem value="FOK">Fill or Kill</MenuItem>
                  <MenuItem value="DAY">Day Order</MenuItem>
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOrderDialogOpen(false)}>Cancel</Button>
          <Button onClick={handlePlaceOrder} variant="contained">
            Place Order
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default OrderManagement;