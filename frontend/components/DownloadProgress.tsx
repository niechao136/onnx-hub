'use client';

import { useEffect, useState } from 'react';
import { Alert, Box, LinearProgress, Typography } from '@mui/material';
import { api } from '@/lib/api';
import { formatBytes } from '@/lib/format';
import type { DownloadProgressInfo } from '@/lib/types';

interface Props {
  modelId: string;
  /** 必须用 useCallback 包裹，否则会导致 SSE 反复重连 */
  onFinished: (modelId: string) => void;
}

export default function DownloadProgress({ modelId, onFinished }: Props) {
  const [progress, setProgress] = useState<DownloadProgressInfo | null>(null);

  useEffect(() => {
    let alive = true;
    const source = new EventSource(api.progressStreamUrl(modelId));

    source.addEventListener('progress', (event) => {
      if (!alive) return;
      try {
        setProgress(JSON.parse((event as MessageEvent).data) as DownloadProgressInfo);
      } catch {
        /* 忽略解析失败的帧 */
      }
    });

    source.addEventListener('done', () => {
      source.close();
      if (alive) onFinished(modelId);
    });

    source.onerror = () => {
      source.close();
    };

    return () => {
      alive = false;
      source.close();
    };
  }, [modelId, onFinished]);

  if (!progress) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography variant="caption" color="text.secondary">
          正在获取下载进度…
        </Typography>
        <LinearProgress sx={{ mt: 1 }} />
      </Box>
    );
  }

  if (progress.status === 'failed') {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        下载失败：{progress.error ?? '未知错误'}
      </Alert>
    );
  }

  if (progress.status === 'cancelled') {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        下载已取消
      </Alert>
    );
  }

  const percent = Math.round(progress.progress * 100);

  return (
    <Box sx={{ mt: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: '70%' }}>
          {progress.current_file
            ? `正在下载 ${progress.current_file}`
            : `已完成 ${progress.completed_files}/${progress.total_files} 个文件`}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {percent}% · {formatBytes(progress.downloaded_bytes)}
        </Typography>
      </Box>
      <LinearProgress variant="determinate" value={percent} />
    </Box>
  );
}
