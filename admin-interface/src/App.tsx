/**
 * Main Application Component
 */

import React, { useState, useEffect } from 'react';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import {
  Box,
  CssBaseline,
  ThemeProvider,
  createTheme,
  AppBar,
  Toolbar,
  Typography,
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemButton,
  Divider,
  IconButton,
  Badge,
  Menu,
  MenuItem,
  FormControl,
  InputLabel,
  Select,
  Alert,
  Snackbar,
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  Assignment,
  TrendingUp,
  Settings,
  AccountCircle,
  Notifications,
  Menu as MenuIcon,
  Brightness4,
  Brightness7,
} from '@mui/icons-material';

import Dashboard from './components/Dashboard';
import OrderManagement from './components/OrderManagement';
import MarketMaking from './components/MarketMaking';
import Analytics from './components/Analytics';
import apiClient from './api/client';

const drawerWidth = 240;

// Dark/Light theme
const getTheme = (mode: 'light' | 'dark') =>
  createTheme({
    palette: {
      mode,
      primary: {
        main: '#1976d2',
      },
      secondary: {
        main: '#dc004e',
      },
    },
  });

interface NavigationItem {
  text: string;
  icon: React.ReactElement;
  path: string;
}

const navigationItems: NavigationItem[] = [
  { text: 'Dashboard', icon: <DashboardIcon />, path: '/dashboard' },
  { text: 'Order Management', icon: <Assignment />, path: '/orders' },
  { text: 'Market Making', icon: <TrendingUp />, path: '/market-making' },
  { text: 'Analytics', icon: <Settings />, path: '/analytics' },
];

function App() {
  const [darkMode, setDarkMode] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [selectedSymbol, setSelectedSymbol] = useState('DEC/USD');
  const [currentPath, setCurrentPath] = useState('/dashboard');
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [apiKey, setApiKey] = useState('test-key');
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected' | 'error'>('disconnected');
  const [notification, setNotification] = useState<{ message: string; severity: 'info' | 'success' | 'warning' | 'error' } | null>(null);

  const theme = getTheme(darkMode ? 'dark' : 'light');

  useEffect(() => {
    // Initialize API client
    if (apiKey) {
      apiClient.setApiKey(apiKey);
      testConnection();
    }
  }, [apiKey]);

  const testConnection = async () => {
    try {
      await apiClient.getHealth();
      setConnectionStatus('connected');
      setNotification({ message: 'Connected to exchange API', severity: 'success' });
    } catch (error) {
      setConnectionStatus('error');
      setNotification({ message: 'Failed to connect to exchange API', severity: 'error' });
    }
  };

  const handleDrawerToggle = () => {
    setDrawerOpen(!drawerOpen);
  };

  const handleThemeToggle = () => {
    setDarkMode(!darkMode);
  };

  const handleMenuClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const handleSymbolChange = (symbol: string) => {
    setSelectedSymbol(symbol);
  };

  const getConnectionStatusColor = () => {
    switch (connectionStatus) {
      case 'connected': return 'success';
      case 'disconnected': return 'warning';
      case 'error': return 'error';
      default: return 'default';
    }
  };

  const drawer = (
    <Box>
      <Toolbar>
        <Typography variant="h6" noWrap component="div">
          Exchange Admin
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {navigationItems.map((item) => (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              selected={currentPath === item.path}
              onClick={() => setCurrentPath(item.path)}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.text} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
      <Divider />
      <Box sx={{ p: 2 }}>
        <FormControl fullWidth size="small">
          <InputLabel>Trading Symbol</InputLabel>
          <Select
            value={selectedSymbol}
            onChange={(e) => handleSymbolChange(e.target.value)}
            label="Trading Symbol"
          >
            <MenuItem value="DEC/USD">DEC/USD</MenuItem>
            <MenuItem value="BTC/USD">BTC/USD</MenuItem>
            <MenuItem value="ETH/USD">ETH/USD</MenuItem>
            <MenuItem value="DEC/BTC">DEC/BTC</MenuItem>
          </Select>
        </FormControl>
      </Box>
    </Box>
  );

  const renderContent = () => {
    switch (currentPath) {
      case '/dashboard':
        return <Dashboard selectedSymbol={selectedSymbol} onSymbolChange={handleSymbolChange} />;
      case '/orders':
        return <OrderManagement selectedSymbol={selectedSymbol} />;
      case '/market-making':
        return <MarketMaking selectedSymbol={selectedSymbol} />;
      case '/analytics':
        return <Analytics />;
      default:
        return <Dashboard selectedSymbol={selectedSymbol} onSymbolChange={handleSymbolChange} />;
    }
  };

  return (
    <ThemeProvider theme={theme}>
      <Box sx={{ display: 'flex' }}>
        <CssBaseline />

        {/* App Bar */}
        <AppBar
          position="fixed"
          sx={{
            width: { sm: `calc(100% - ${drawerWidth}px)` },
            ml: { sm: `${drawerWidth}px` },
          }}
        >
          <Toolbar>
            <IconButton
              color="inherit"
              aria-label="open drawer"
              edge="start"
              onClick={handleDrawerToggle}
              sx={{ mr: 2, display: { sm: 'none' } }}
            >
              <MenuIcon />
            </IconButton>

            <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
              DeCoin Exchange - {navigationItems.find(item => item.path === currentPath)?.text || 'Dashboard'}
            </Typography>

            <Badge
              color={getConnectionStatusColor()}
              variant="dot"
              sx={{ mr: 2 }}
            >
              <Typography variant="body2" sx={{ mr: 1 }}>
                {connectionStatus.toUpperCase()}
              </Typography>
            </Badge>

            <IconButton color="inherit" onClick={handleThemeToggle}>
              {darkMode ? <Brightness7 /> : <Brightness4 />}
            </IconButton>

            <IconButton color="inherit">
              <Badge badgeContent={0} color="error">
                <Notifications />
              </Badge>
            </IconButton>

            <IconButton
              color="inherit"
              onClick={handleMenuClick}
            >
              <AccountCircle />
            </IconButton>

            <Menu
              anchorEl={anchorEl}
              open={Boolean(anchorEl)}
              onClose={handleMenuClose}
            >
              <MenuItem onClick={handleMenuClose}>Profile</MenuItem>
              <MenuItem onClick={handleMenuClose}>Account Settings</MenuItem>
              <MenuItem onClick={handleMenuClose}>Logout</MenuItem>
            </Menu>
          </Toolbar>
        </AppBar>

        {/* Navigation Drawer */}
        <Box
          component="nav"
          sx={{ width: { sm: drawerWidth }, flexShrink: { sm: 0 } }}
        >
          <Drawer
            variant="temporary"
            open={drawerOpen}
            onClose={handleDrawerToggle}
            ModalProps={{
              keepMounted: true, // Better open performance on mobile.
            }}
            sx={{
              display: { xs: 'block', sm: 'none' },
              '& .MuiDrawer-paper': {
                boxSizing: 'border-box',
                width: drawerWidth,
              },
            }}
          >
            {drawer}
          </Drawer>
          <Drawer
            variant="permanent"
            sx={{
              display: { xs: 'none', sm: 'block' },
              '& .MuiDrawer-paper': {
                boxSizing: 'border-box',
                width: drawerWidth,
              },
            }}
            open
          >
            {drawer}
          </Drawer>
        </Box>

        {/* Main Content */}
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            width: { sm: `calc(100% - ${drawerWidth}px)` },
            mt: 8, // Account for AppBar height
          }}
        >
          {renderContent()}
        </Box>

        {/* Notifications */}
        <Snackbar
          open={Boolean(notification)}
          autoHideDuration={6000}
          onClose={() => setNotification(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        >
          {notification ? (
            <Alert
              onClose={() => setNotification(null)}
              severity={notification.severity}
              sx={{ width: '100%' }}
            >
              {notification.message}
            </Alert>
          ) : undefined}
        </Snackbar>
      </Box>
    </ThemeProvider>
  );
}

export default App;