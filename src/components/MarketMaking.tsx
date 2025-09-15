/**
 * Market Making Strategy Management Interface
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Button,
  Card,
  CardContent,
  CardActions,
  Grid,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Chip,
  Alert,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
} from '@mui/material';
import {
  Add,
  Delete,
  Edit,
  PlayArrow,
  Stop,
  Refresh,
  TrendingUp,
  GridOn,
  ShowChart,
  Science,
} from '@mui/icons-material';

import apiClient, { MarketMakerConfig } from '../api/client';

interface MarketMakingProps {
  selectedSymbol: string;
}

interface NewStrategyForm {
  strategy: string;
  symbol: string;
  spread_bps: string;
  order_amount: string;
  max_orders_per_side: string;
  inventory_target: string;
  grid_spacing?: string;
  risk_factor?: string;
  refresh_interval?: string;
}

const MarketMaking: React.FC<MarketMakingProps> = ({ selectedSymbol }) => {
  const [strategies, setStrategies] = useState<MarketMakerConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [strategyDialogOpen, setStrategyDialogOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<MarketMakerConfig | null>(null);
  const [newStrategy, setNewStrategy] = useState<NewStrategyForm>({
    strategy: 'grid',
    symbol: selectedSymbol,
    spread_bps: '20',
    order_amount: '10',
    max_orders_per_side: '5',
    inventory_target: '1000',
    grid_spacing: '0.1',
    risk_factor: '0.01',
    refresh_interval: '10',
  });

  useEffect(() => {
    loadStrategies();
    const interval = setInterval(loadStrategies, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setNewStrategy(prev => ({ ...prev, symbol: selectedSymbol }));
  }, [selectedSymbol]);

  const loadStrategies = async () => {
    try {
      setLoading(true);
      setError(null);
      const strategiesData = await apiClient.getMarketMakers();
      setStrategies(strategiesData);
    } catch (err) {
      // Fallback for demo - create mock data
      setStrategies([
        {
          id: 'grid_mm_1',
          strategy: 'grid',
          symbol: 'DEC/USD',
          active: true,
          spread_bps: 20,
          order_amount: 10,
          max_orders_per_side: 5,
          inventory_target: 1000,
          config: { grid_spacing: 0.1 }
        },
        {
          id: 'spread_mm_1',
          strategy: 'spread',
          symbol: 'BTC/USD',
          active: false,
          spread_bps: 10,
          order_amount: 0.001,
          max_orders_per_side: 3,
          inventory_target: 0.1,
          config: {}
        }
      ]);
      console.warn('Using mock market maker data - API endpoint not available');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateStrategy = async () => {
    try {
      setError(null);

      const strategyConfig: Omit<MarketMakerConfig, 'id'> = {
        strategy: newStrategy.strategy,
        symbol: newStrategy.symbol,
        active: false,
        spread_bps: parseInt(newStrategy.spread_bps),
        order_amount: parseFloat(newStrategy.order_amount),
        max_orders_per_side: parseInt(newStrategy.max_orders_per_side),
        inventory_target: parseFloat(newStrategy.inventory_target),
        config: {},
      };

      // Add strategy-specific config
      if (newStrategy.strategy === 'grid' && newStrategy.grid_spacing) {
        strategyConfig.config.grid_spacing = parseFloat(newStrategy.grid_spacing);
      }

      if (newStrategy.strategy === 'avellaneda_stoikov' && newStrategy.risk_factor) {
        strategyConfig.config.risk_factor = parseFloat(newStrategy.risk_factor);
      }

      if (newStrategy.refresh_interval) {
        strategyConfig.config.refresh_interval = parseInt(newStrategy.refresh_interval);
      }

      // For demo, add to local state
      const newId = `${newStrategy.strategy}_${Date.now()}`;
      setStrategies(prev => [...prev, { ...strategyConfig, id: newId }]);

      setStrategyDialogOpen(false);
      resetForm();
    } catch (err: any) {
      setError('Failed to create strategy');
    }
  };

  const handleToggleStrategy = async (strategyId: string, active: boolean) => {
    try {
      // For demo, update local state
      setStrategies(prev =>
        prev.map(strategy =>
          strategy.id === strategyId ? { ...strategy, active } : strategy
        )
      );
    } catch (err) {
      setError('Failed to toggle strategy');
    }
  };

  const handleDeleteStrategy = async (strategyId: string) => {
    try {
      // For demo, remove from local state
      setStrategies(prev => prev.filter(strategy => strategy.id !== strategyId));
    } catch (err) {
      setError('Failed to delete strategy');
    }
  };

  const resetForm = () => {
    setNewStrategy({
      strategy: 'grid',
      symbol: selectedSymbol,
      spread_bps: '20',
      order_amount: '10',
      max_orders_per_side: '5',
      inventory_target: '1000',
      grid_spacing: '0.1',
      risk_factor: '0.01',
      refresh_interval: '10',
    });
    setEditingStrategy(null);
  };

  const getStrategyIcon = (strategy: string) => {
    switch (strategy) {
      case 'grid': return <GridOn color="primary" />;
      case 'spread': return <ShowChart color="primary" />;
      case 'avellaneda_stoikov': return <Science color="primary" />;
      default: return <TrendingUp color="primary" />;
    }
  };

  const getStrategyDescription = (strategy: string) => {
    switch (strategy) {
      case 'grid':
        return 'Places buy and sell orders at regular price intervals';
      case 'spread':
        return 'Dynamic spread-based market making with inventory management';
      case 'avellaneda_stoikov':
        return 'Academic optimal market making model with risk controls';
      default:
        return 'Automated market making strategy';
    }
  };

  const formatNumber = (num: number, decimals = 4) => {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(num);
  };

  return (
    <Box sx={{ p: 3 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4">Market Making Strategies</Typography>
        <Box>
          <Button
            variant="outlined"
            onClick={loadStrategies}
            startIcon={<Refresh />}
            sx={{ mr: 2 }}
          >
            Refresh
          </Button>
          <Button
            variant="contained"
            onClick={() => setStrategyDialogOpen(true)}
            startIcon={<Add />}
          >
            New Strategy
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* Strategy Overview */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom variant="body2">
                Total Strategies
              </Typography>
              <Typography variant="h3">
                {strategies.length}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom variant="body2">
                Active Strategies
              </Typography>
              <Typography variant="h3" color="success.main">
                {strategies.filter(s => s.active).length}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography color="textSecondary" gutterBottom variant="body2">
                Symbols Covered
              </Typography>
              <Typography variant="h3" color="primary.main">
                {new Set(strategies.map(s => s.symbol)).size}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Strategy Cards */}
      <Grid container spacing={3}>
        {strategies.map((strategy) => (
          <Grid item xs={12} md={6} lg={4} key={strategy.id}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box display="flex" alignItems="center" mb={2}>
                  {getStrategyIcon(strategy.strategy)}
                  <Typography variant="h6" sx={{ ml: 1 }}>
                    {strategy.strategy.toUpperCase()}
                  </Typography>
                  <Box sx={{ ml: 'auto' }}>
                    <Chip
                      label={strategy.active ? 'Active' : 'Stopped'}
                      color={strategy.active ? 'success' : 'default'}
                      size="small"
                    />
                  </Box>
                </Box>

                <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
                  {getStrategyDescription(strategy.strategy)}
                </Typography>

                <Divider sx={{ my: 2 }} />

                <List dense>
                  <ListItem disablePadding>
                    <ListItemText
                      primary="Symbol"
                      secondary={strategy.symbol}
                    />
                  </ListItem>
                  <ListItem disablePadding>
                    <ListItemText
                      primary="Spread"
                      secondary={`${strategy.spread_bps} bps`}
                    />
                  </ListItem>
                  <ListItem disablePadding>
                    <ListItemText
                      primary="Order Size"
                      secondary={formatNumber(strategy.order_amount)}
                    />
                  </ListItem>
                  <ListItem disablePadding>
                    <ListItemText
                      primary="Max Orders/Side"
                      secondary={strategy.max_orders_per_side}
                    />
                  </ListItem>
                  <ListItem disablePadding>
                    <ListItemText
                      primary="Inventory Target"
                      secondary={formatNumber(strategy.inventory_target)}
                    />
                  </ListItem>
                  {strategy.config.grid_spacing && (
                    <ListItem disablePadding>
                      <ListItemText
                        primary="Grid Spacing"
                        secondary={formatNumber(strategy.config.grid_spacing, 2)}
                      />
                    </ListItem>
                  )}
                  {strategy.config.risk_factor && (
                    <ListItem disablePadding>
                      <ListItemText
                        primary="Risk Factor"
                        secondary={formatNumber(strategy.config.risk_factor, 3)}
                      />
                    </ListItem>
                  )}
                </List>
              </CardContent>

              <CardActions>
                <Button
                  size="small"
                  color={strategy.active ? 'error' : 'success'}
                  onClick={() => handleToggleStrategy(strategy.id, !strategy.active)}
                  startIcon={strategy.active ? <Stop /> : <PlayArrow />}
                >
                  {strategy.active ? 'Stop' : 'Start'}
                </Button>
                <Button
                  size="small"
                  onClick={() => {
                    setEditingStrategy(strategy);
                    setStrategyDialogOpen(true);
                  }}
                  startIcon={<Edit />}
                >
                  Edit
                </Button>
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => handleDeleteStrategy(strategy.id)}
                >
                  <Delete />
                </IconButton>
              </CardActions>
            </Card>
          </Grid>
        ))}

        {strategies.length === 0 && (
          <Grid item xs={12}>
            <Paper sx={{ p: 4, textAlign: 'center' }}>
              <Typography variant="h6" color="textSecondary" gutterBottom>
                No Market Making Strategies
              </Typography>
              <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
                Create your first strategy to start automated market making
              </Typography>
              <Button
                variant="contained"
                onClick={() => setStrategyDialogOpen(true)}
                startIcon={<Add />}
              >
                Create Strategy
              </Button>
            </Paper>
          </Grid>
        )}
      </Grid>

      {/* Strategy Creation/Edit Dialog */}
      <Dialog
        open={strategyDialogOpen}
        onClose={() => {
          setStrategyDialogOpen(false);
          resetForm();
        }}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {editingStrategy ? 'Edit Strategy' : 'Create New Strategy'}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Strategy Type</InputLabel>
                <Select
                  value={newStrategy.strategy}
                  onChange={(e) => setNewStrategy(prev => ({ ...prev, strategy: e.target.value }))}
                >
                  <MenuItem value="grid">Grid Trading</MenuItem>
                  <MenuItem value="spread">Spread-Based</MenuItem>
                  <MenuItem value="avellaneda_stoikov">Avellaneda-Stoikov</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel>Symbol</InputLabel>
                <Select
                  value={newStrategy.symbol}
                  onChange={(e) => setNewStrategy(prev => ({ ...prev, symbol: e.target.value }))}
                >
                  <MenuItem value="DEC/USD">DEC/USD</MenuItem>
                  <MenuItem value="BTC/USD">BTC/USD</MenuItem>
                  <MenuItem value="ETH/USD">ETH/USD</MenuItem>
                  <MenuItem value="DEC/BTC">DEC/BTC</MenuItem>
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Spread (basis points)"
                type="number"
                value={newStrategy.spread_bps}
                onChange={(e) => setNewStrategy(prev => ({ ...prev, spread_bps: e.target.value }))}
                helperText="1 bps = 0.01%"
              />
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Order Amount"
                type="number"
                value={newStrategy.order_amount}
                onChange={(e) => setNewStrategy(prev => ({ ...prev, order_amount: e.target.value }))}
                inputProps={{ step: "0.0001" }}
              />
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Max Orders Per Side"
                type="number"
                value={newStrategy.max_orders_per_side}
                onChange={(e) => setNewStrategy(prev => ({ ...prev, max_orders_per_side: e.target.value }))}
              />
            </Grid>

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Inventory Target"
                type="number"
                value={newStrategy.inventory_target}
                onChange={(e) => setNewStrategy(prev => ({ ...prev, inventory_target: e.target.value }))}
                inputProps={{ step: "0.0001" }}
              />
            </Grid>

            {newStrategy.strategy === 'grid' && (
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Grid Spacing"
                  type="number"
                  value={newStrategy.grid_spacing}
                  onChange={(e) => setNewStrategy(prev => ({ ...prev, grid_spacing: e.target.value }))}
                  inputProps={{ step: "0.01" }}
                  helperText="Price spacing between grid levels"
                />
              </Grid>
            )}

            {newStrategy.strategy === 'avellaneda_stoikov' && (
              <Grid item xs={12} sm={6}>
                <TextField
                  fullWidth
                  label="Risk Factor"
                  type="number"
                  value={newStrategy.risk_factor}
                  onChange={(e) => setNewStrategy(prev => ({ ...prev, risk_factor: e.target.value }))}
                  inputProps={{ step: "0.001" }}
                  helperText="Risk aversion parameter"
                />
              </Grid>
            )}

            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Refresh Interval (seconds)"
                type="number"
                value={newStrategy.refresh_interval}
                onChange={(e) => setNewStrategy(prev => ({ ...prev, refresh_interval: e.target.value }))}
                helperText="How often to update orders"
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setStrategyDialogOpen(false);
              resetForm();
            }}
          >
            Cancel
          </Button>
          <Button onClick={handleCreateStrategy} variant="contained">
            {editingStrategy ? 'Update' : 'Create'} Strategy
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default MarketMaking;