'use client';

import { Chip, Stack } from '@mui/material';
import { formatBytes } from '@/lib/format';
import type { ModelInfo, ModelStatus } from '@/lib/types';

type ChipColor = 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning';

const STATUS_MAP: Record<ModelStatus, { label: string; color: ChipColor }> = {
  stopped: { label: '已停止', color: 'default' },
  starting: { label: '启动中', color: 'info' },
  running: { label: '运行中', color: 'success' },
  stopping: { label: '停止中', color: 'warning' },
  restarting: { label: '重启中', color: 'warning' },
  error: { label: '异常', color: 'error' },
};

export function StatusChip({ status }: { status: ModelStatus }) {
  const item = STATUS_MAP[status] ?? STATUS_MAP.stopped;
  return (
    <Chip
      size="small"
      label={item.label}
      color={item.color}
      variant={status === 'stopped' ? 'outlined' : 'filled'}
    />
  );
}

export function DownloadChip({ model }: { model: ModelInfo }) {
  if (model.downloaded) {
    return (
      <Chip
        size="small"
        color="success"
        variant="outlined"
        label={`已下载 ${formatBytes(model.size_bytes)}`}
      />
    );
  }
  if (model.download_progress > 0 && model.download_progress < 1) {
    return (
      <Chip
        size="small"
        color="info"
        variant="outlined"
        label={`下载中 ${Math.round(model.download_progress * 100)}%`}
      />
    );
  }
  return <Chip size="small" color="warning" variant="outlined" label="未下载" />;
}

export function ModelChips({ model }: { model: ModelInfo }) {
  return (
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
      <DownloadChip model={model} />
      <StatusChip status={model.status} />
      {model.origin === 'custom' && (
        <Chip size="small" color="secondary" variant="outlined" label="自定义" />
      )}
    </Stack>
  );
}
