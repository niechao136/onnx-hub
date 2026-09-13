'use client';

import {
  Box,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { formatBytes, formatUptime } from '@/lib/format';
import type { ResourceMetrics } from '@/lib/types';

export default function ResourceMonitor({ metrics }: { metrics: ResourceMetrics | null }) {
  if (!metrics) {
    return (
      <Card variant="outlined" sx={{ mb: 3 }}>
        <CardContent>
          <Typography color="text.secondary">正在读取资源占用…</Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card variant="outlined" sx={{ mb: 3 }}>
      <CardContent>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={3}
          sx={{ alignItems: { xs: 'flex-start', md: 'center' } }}
        >
          <Box sx={{ minWidth: 180 }}>
            <Typography variant="overline" color="text.secondary">
              运行中的模型
            </Typography>
            <Typography variant="h5">
              {metrics.running_models}
              <Typography component="span" variant="body2" color="text.secondary">
                {' '}
                / {metrics.max_running_models}
              </Typography>
            </Typography>
            <Typography variant="caption" color="text.secondary">
              端口池 {metrics.port_pool_start}-{metrics.port_pool_end}
            </Typography>
          </Box>

          <Box sx={{ flexGrow: 1, minWidth: 220 }}>
            <Typography variant="caption" color="text.secondary">
              系统 CPU {metrics.system_cpu_percent.toFixed(1)}%
            </Typography>
            <LinearProgress
              variant="determinate"
              value={Math.min(metrics.system_cpu_percent, 100)}
              sx={{ my: 0.5 }}
            />
            <Typography variant="caption" color="text.secondary">
              系统内存 {metrics.system_memory_percent.toFixed(1)}%（
              {formatBytes(metrics.system_memory_used_mb * 1024 * 1024)} /{' '}
              {formatBytes(metrics.system_memory_total_mb * 1024 * 1024)}）
            </Typography>
            <LinearProgress
              variant="determinate"
              color={metrics.system_memory_percent > 85 ? 'error' : 'primary'}
              value={Math.min(metrics.system_memory_percent, 100)}
              sx={{ my: 0.5 }}
            />
          </Box>
        </Stack>

        {metrics.processes.length > 0 && (
          <Box sx={{ mt: 2, overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>模型</TableCell>
                  <TableCell>PID</TableCell>
                  <TableCell>内部端口</TableCell>
                  <TableCell>CPU</TableCell>
                  <TableCell>内存</TableCell>
                  <TableCell>运行时长</TableCell>
                  <TableCell>重启次数</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {metrics.processes.map((process) => (
                  <TableRow key={process.model_id}>
                    <TableCell>{process.model_id}</TableCell>
                    <TableCell>{process.pid}</TableCell>
                    <TableCell>
                      <Chip size="small" label={process.port} />
                    </TableCell>
                    <TableCell>{process.cpu_percent.toFixed(1)}%</TableCell>
                    <TableCell>{process.memory_mb.toFixed(1)} MB</TableCell>
                    <TableCell>{formatUptime(process.uptime_seconds)}</TableCell>
                    <TableCell>{process.restart_count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
