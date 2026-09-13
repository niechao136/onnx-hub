'use client';

import Link from 'next/link';
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  Divider,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { formatMegabytes } from '@/lib/format';
import type { ModelInfo } from '@/lib/types';
import { MODEL_TYPE_LABEL } from '@/lib/types';
import DownloadProgress from './DownloadProgress';
import { ModelChips } from './StatusChip';

interface Props {
  model: ModelInfo;
  downloading: boolean;
  busy: boolean;
  onDownload: (model: ModelInfo, force?: boolean) => void;
  onCancelDownload: (model: ModelInfo) => void;
  onStart: (model: ModelInfo) => void;
  onStop: (model: ModelInfo) => void;
  onRestart: (model: ModelInfo) => void;
  onDownloadFinished: (modelId: string) => void;
}

export default function ModelCard({
  model,
  downloading,
  busy,
  onDownload,
  onCancelDownload,
  onStart,
  onStop,
  onRestart,
  onDownloadFinished,
}: Props) {
  const fileCount = model.files.length;
  const readyFiles = model.files.filter((file) => file.exists).length;
  const disabled = busy || downloading;

  return (
    <Card variant="outlined" sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="h6" gutterBottom>
          {model.name}
        </Typography>
        <Typography variant="caption" color="text.secondary" gutterBottom sx={{ display: 'block' }}>
          {model.id} · {MODEL_TYPE_LABEL[model.type]}
        </Typography>

        <Box sx={{ my: 1.5 }}>
          <ModelChips model={model} />
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ minHeight: 40 }}>
          {model.description || '暂无描述'}
        </Typography>

        <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1.5, flexWrap: 'wrap' }}>
          <Chip size="small" variant="outlined" label={`内存预估 ${formatMegabytes(model.memory_mb)}`} />
          <Chip size="small" variant="outlined" label={`文件 ${readyFiles}/${fileCount}`} />
          {model.language && <Chip size="small" variant="outlined" label={model.language} />}
          {model.tags.map((tag) => (
            <Chip key={tag} size="small" variant="outlined" label={tag} />
          ))}
        </Stack>

        {model.running && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: 'block' }}>
            内部端口 {model.port} · PID {model.pid} · 重启 {model.restart_count} 次
          </Typography>
        )}

        {downloading && (
          <DownloadProgress modelId={model.id} onFinished={onDownloadFinished} />
        )}

        {model.last_error && !downloading && (
          <Alert severity="error" sx={{ mt: 2, whiteSpace: 'pre-wrap' }}>
            <Tooltip title={model.last_error}>
              <Box sx={{ maxHeight: 120, overflow: 'auto', fontSize: 12 }}>{model.last_error}</Box>
            </Tooltip>
          </Alert>
        )}
      </CardContent>

      <Divider />

      <CardActions sx={{ flexWrap: 'wrap', gap: 1, justifyContent: 'flex-start' }}>
        <Button size="small" component={Link} href={`/models/${model.id}`}>
          详情
        </Button>

        {!model.downloaded && !downloading && (
          <Button size="small" variant="contained" onClick={() => onDownload(model)} disabled={disabled}>
            下载
          </Button>
        )}
        {model.downloaded && !downloading && (
          <Button size="small" onClick={() => onDownload(model, true)} disabled={disabled}>
            重新下载
          </Button>
        )}
        {downloading && (
          <Button size="small" color="warning" onClick={() => onCancelDownload(model)}>
            取消下载
          </Button>
        )}

        {!model.running && (
          <Button
            size="small"
            variant="contained"
            color="success"
            onClick={() => onStart(model)}
            disabled={disabled || !model.downloaded}
          >
            启动
          </Button>
        )}
        {model.running && (
          <>
            <Button size="small" color="error" onClick={() => onStop(model)} disabled={busy}>
              停止
            </Button>
            <Button size="small" onClick={() => onRestart(model)} disabled={busy}>
              重启
            </Button>
          </>
        )}
      </CardActions>
    </Card>
  );
}
