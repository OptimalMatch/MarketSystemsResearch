/**
 * System Status Component
 */

import React from 'react';
import {
  Paper,
  Typography,
  Box,
  Chip,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  LinearProgress,
  Divider,
} from '@mui/material';
import {
  CheckCircle,
  Error,
  Warning,
  Speed,
  Storage,
  Link,
  Computer,
} from '@mui/icons-material';
import { SystemHealth } from '../api/client';

interface SystemStatusProps {
  systemHealth: SystemHealth | null;
}

const SystemStatus: React.FC<SystemStatusProps> = ({ systemHealth }) => {
  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (days > 0) {
      return `${days}d ${hours}h ${minutes}m`;
    } else if (hours > 0) {
      return `${hours}h ${minutes}m`;
    } else {
      return `${minutes}m`;
    }
  };

  const getStatusIcon = (status: boolean) => {
    return status ? (
      <CheckCircle color="success" />
    ) : (
      <Error color="error" />
    );
  };

  const getStatusColor = (status: boolean) => {
    return status ? 'success' : 'error';
  };

  if (!systemHealth) {
    return (
      <Paper sx={{ p: 2, height: 400 }}>
        <Typography variant="h6" gutterBottom>
          System Status
        </Typography>
        <Box display="flex" justifyContent="center" alignItems="center" height="80%">
          <Typography color="textSecondary">Loading system status...</Typography>
        </Box>
      </Paper>
    );
  }

  const overallHealthy = systemHealth.services ? Object.values(systemHealth.services).every(status => status) : false;

  return (
    <Paper sx={{ p: 2, height: 400 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">
          System Status
        </Typography>
        <Chip
          label={systemHealth.status.toUpperCase()}
          color={overallHealthy ? 'success' : 'error'}
          variant="filled"
        />
      </Box>

      {/* Overall Status */}
      <Box mb={3}>
        <Typography variant="body2" color="textSecondary" gutterBottom>
          Overall Health
        </Typography>
        <LinearProgress
          variant="determinate"
          value={overallHealthy ? 100 : 50}
          color={overallHealthy ? 'success' : 'error'}
          sx={{ height: 8, borderRadius: 4 }}
        />
        <Box display="flex" justifyContent="space-between" mt={1}>
          <Typography variant="body2">
            Version: {systemHealth.version}
          </Typography>
          <Typography variant="body2">
            Uptime: {formatUptime(systemHealth.uptime)}
          </Typography>
        </Box>
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Service Status */}
      <Typography variant="body2" color="textSecondary" gutterBottom>
        Service Status
      </Typography>
      <List dense>
        <ListItem>
          <ListItemIcon>
            <Speed />
          </ListItemIcon>
          <ListItemText
            primary="Matching Engine"
            secondary="Order processing and execution"
          />
          <Box ml={2}>
            {getStatusIcon(systemHealth.services?.matching_engine || false)}
          </Box>
        </ListItem>

        <ListItem>
          <ListItemIcon>
            <Storage />
          </ListItemIcon>
          <ListItemText
            primary="Database"
            secondary="PostgreSQL persistence layer"
          />
          <Box ml={2}>
            {getStatusIcon(systemHealth.services?.database || false)}
          </Box>
        </ListItem>

        <ListItem>
          <ListItemIcon>
            <Link />
          </ListItemIcon>
          <ListItemText
            primary="Blockchain"
            secondary="DeCoin blockchain connection"
          />
          <Box ml={2}>
            {getStatusIcon(systemHealth.services?.blockchain || false)}
          </Box>
        </ListItem>

        <ListItem>
          <ListItemIcon>
            <Computer />
          </ListItemIcon>
          <ListItemText
            primary="API Gateway"
            secondary="REST and WebSocket endpoints"
          />
          <Box ml={2}>
            {getStatusIcon(systemHealth.services?.api || false)}
          </Box>
        </ListItem>
      </List>

      {/* Status Summary */}
      <Box mt={2}>
        <Typography variant="body2" color="textSecondary">
          Last updated: {new Date(systemHealth.timestamp).toLocaleString()}
        </Typography>
        <Box display="flex" gap={1} mt={1}>
          {systemHealth.services ? Object.entries(systemHealth.services).map(([service, status]) => (
            <Chip
              key={service}
              label={service.replace('_', ' ')}
              size="small"
              color={getStatusColor(status)}
              variant="outlined"
            />
          )) : null}
        </Box>
      </Box>
    </Paper>
  );
};

export default SystemStatus;