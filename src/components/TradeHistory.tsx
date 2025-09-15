/**
 * Trade History Component
 */

import React from 'react';
import {
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Box,
} from '@mui/material';
import { Trade } from '../api/client';

interface TradeHistoryProps {
  trades: Trade[];
  symbol: string;
}

const TradeHistory: React.FC<TradeHistoryProps> = ({ trades, symbol }) => {
  const formatNumber = (num: number, decimals = 4) => {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(num);
  };

  const formatCurrency = (num: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(num);
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  if (!trades.length) {
    return (
      <Paper sx={{ p: 2, height: 600 }}>
        <Typography variant="h6" gutterBottom>
          Recent Trades - {symbol}
        </Typography>
        <Box display="flex" justifyContent="center" alignItems="center" height="80%">
          <Typography color="textSecondary">No recent trades</Typography>
        </Box>
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 2, height: 600 }}>
      <Typography variant="h6" gutterBottom>
        Recent Trades - {symbol}
      </Typography>

      <TableContainer sx={{ height: 520 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Time</TableCell>
              <TableCell align="right">Price</TableCell>
              <TableCell align="right">Quantity</TableCell>
              <TableCell align="center">Side</TableCell>
              <TableCell align="right">Total</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {trades.map((trade, index) => (
              <TableRow
                key={trade.id || index}
                sx={{
                  backgroundColor: trade.side === 'buy'
                    ? 'rgba(76, 175, 80, 0.05)'
                    : 'rgba(244, 67, 54, 0.05)',
                  '&:hover': {
                    backgroundColor: trade.side === 'buy'
                      ? 'rgba(76, 175, 80, 0.1)'
                      : 'rgba(244, 67, 54, 0.1)',
                  },
                }}
              >
                <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                  {formatTime(trade.timestamp)}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{
                    fontFamily: 'monospace',
                    color: trade.side === 'buy' ? 'success.main' : 'error.main',
                    fontWeight: 'medium',
                  }}
                >
                  {formatCurrency(trade.price)}
                </TableCell>
                <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                  {formatNumber(trade.quantity)}
                </TableCell>
                <TableCell align="center">
                  <Chip
                    label={trade.side.toUpperCase()}
                    size="small"
                    color={trade.side === 'buy' ? 'success' : 'error'}
                    variant="outlined"
                  />
                </TableCell>
                <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                  {formatCurrency(trade.price * trade.quantity)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Box mt={2} display="flex" justifyContent="space-between" alignItems="center">
        <Typography variant="body2" color="textSecondary">
          Showing {trades.length} recent trades
        </Typography>
        {trades.length > 0 && (
          <Box display="flex" gap={1}>
            <Typography variant="body2" color="textSecondary">
              Latest: {formatTime(trades[0].timestamp)}
            </Typography>
          </Box>
        )}
      </Box>
    </Paper>
  );
};

export default TradeHistory;