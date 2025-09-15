/**
 * Order Book Component
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
  Box,
  Chip,
} from '@mui/material';
import { OrderBook as OrderBookType } from '../api/client';

interface OrderBookProps {
  orderBook: OrderBookType | null;
  symbol: string;
}

const OrderBookComponent: React.FC<OrderBookProps> = ({ orderBook, symbol }) => {
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

  if (!orderBook || (!orderBook.bids.length && !orderBook.asks.length)) {
    return (
      <Paper sx={{ p: 2, height: 600 }}>
        <Typography variant="h6" gutterBottom>
          Order Book - {symbol}
        </Typography>
        <Box display="flex" justifyContent="center" alignItems="center" height="80%">
          <Typography color="textSecondary">No order book data available</Typography>
        </Box>
      </Paper>
    );
  }

  const bestBid = orderBook.bids.length > 0 ? orderBook.bids[0].price : 0;
  const bestAsk = orderBook.asks.length > 0 ? orderBook.asks[0].price : 0;
  const spread = bestAsk && bestBid ? bestAsk - bestBid : 0;
  const spreadPercent = spread && bestBid ? (spread / bestBid) * 100 : 0;

  return (
    <Paper sx={{ p: 2, height: 600 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">
          Order Book - {symbol}
        </Typography>
        {spread > 0 && (
          <Chip
            label={`Spread: ${formatCurrency(spread)} (${formatNumber(spreadPercent, 2)}%)`}
            size="small"
            color="info"
          />
        )}
      </Box>

      <TableContainer sx={{ height: 520 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell align="right">Price</TableCell>
              <TableCell align="right">Quantity</TableCell>
              <TableCell align="right">Total</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {/* Asks (Sells) - displayed in reverse order */}
            {orderBook.asks
              .slice(0, 10)
              .reverse()
              .map((ask, index) => (
                <TableRow
                  key={`ask-${index}`}
                  sx={{
                    backgroundColor: 'rgba(244, 67, 54, 0.05)',
                    '&:hover': { backgroundColor: 'rgba(244, 67, 54, 0.1)' },
                  }}
                >
                  <TableCell align="right" sx={{ color: 'error.main', fontFamily: 'monospace' }}>
                    {formatCurrency(ask.price)}
                  </TableCell>
                  <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                    {formatNumber(ask.quantity)}
                  </TableCell>
                  <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                    {formatCurrency(ask.price * ask.quantity)}
                  </TableCell>
                </TableRow>
              ))}

            {/* Spread Row */}
            {spread > 0 && (
              <TableRow>
                <TableCell colSpan={3} align="center" sx={{ py: 1, borderTop: 2, borderBottom: 2 }}>
                  <Typography variant="body2" color="textSecondary">
                    ← Spread: {formatCurrency(spread)} →
                  </Typography>
                </TableCell>
              </TableRow>
            )}

            {/* Bids (Buys) */}
            {orderBook.bids.slice(0, 10).map((bid, index) => (
              <TableRow
                key={`bid-${index}`}
                sx={{
                  backgroundColor: 'rgba(76, 175, 80, 0.05)',
                  '&:hover': { backgroundColor: 'rgba(76, 175, 80, 0.1)' },
                }}
              >
                <TableCell align="right" sx={{ color: 'success.main', fontFamily: 'monospace' }}>
                  {formatCurrency(bid.price)}
                </TableCell>
                <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                  {formatNumber(bid.quantity)}
                </TableCell>
                <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                  {formatCurrency(bid.price * bid.quantity)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Box mt={2} display="flex" justifyContent="space-between" alignItems="center">
        <Typography variant="body2" color="textSecondary">
          Last updated: {new Date(orderBook.timestamp).toLocaleTimeString()}
        </Typography>
        <Box display="flex" gap={1}>
          <Chip
            label={`Best Bid: ${formatCurrency(bestBid)}`}
            size="small"
            color="success"
            variant="outlined"
          />
          <Chip
            label={`Best Ask: ${formatCurrency(bestAsk)}`}
            size="small"
            color="error"
            variant="outlined"
          />
        </Box>
      </Box>
    </Paper>
  );
};

export default OrderBookComponent;