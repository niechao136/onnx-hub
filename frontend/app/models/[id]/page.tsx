'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  LinearProgress,
  Stack,
  Switch,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import RefreshIcon from '@mui/icons-material/Refresh';
import StopIcon from '@mui/icons-material/Stop';
import ConfirmDialog from '@/components/ConfirmDialog';
import DownloadProgress from '@/components/DownloadProgress';
import { ModelChips } from '@/components/StatusChip';
import { api, websocketUrl } from '@/lib/api';
import { formatBytes, formatMegabytes } from '@/lib/format';
import type { ModelInfo } from '@/lib/types';
import { MODEL_TYPE_LABEL } from '@/lib/types';

export default function ModelDetailPage() {
  const params = useParams<{ id: string }>();
  const modelId = useMemo(() => decodeURIComponent(params?.id ?? ''), [params]);

  const [model, setModel] = useState<ModelInfo | null>(null);
  const [logs, setLogs] = useState('');
  const [logPath, setLogPath] = useState('');
  const [logLines, setLogLines] = useState(200);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [tab, setTab] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [wsState, setWsState] = useState<'idle' | 'connecting' | 'open' | 'error'>('idle');
  const [wsMessage, setWsMessage] = useState('');

  const loadModel = useCallback(async () => {
    if (!modelId) return;
    try {
      setModel(await api.getModel(modelId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [modelId]);

  const loadLogs = useCallback(async () => {
    if (!modelId) return;
    try {
      const payload = await api.getLogs(modelId, logLines);
      setLogs(payload.content);
      setLogPath(payload.log_path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [modelId, logLines]);

  useEffect(() => {
    void loadModel();
    void loadLogs();
  }, [loadModel, loadLogs]);

  useEffect(() => {
    const timer = setInterval(() => {
      void loadModel();
    }, 5000);
    return () => clearInterval(timer);
  }, [loadModel]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => {
      void loadLogs();
    }, 3000);
    return () => clearInterval(timer);
  }, [autoRefresh, loadLogs]);

  const runAction = async (action: 'start' | 'stop' | 'restart') => {
    if (!model) return;
    setBusy(true);
    try {
      const updated =
        action === 'start'
          ? await api.startModel(model.id)
          : action === 'stop'
            ? await api.stopModel(model.id)
            : await api.restartModel(model.id);
      setModel(updated);
      setNotice(`已${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}「${model.name}」`);
      await loadLogs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await loadModel();
    } finally {
      setBusy(false);
      setConfirmStop(false);
    }
  };

  const testWebSocket = () => {
    if (!model) return;
    const url = websocketUrl(model.gateway_path);
    setWsState('connecting');
    setWsMessage(`正在连接 ${url}`);
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (err) {
      setWsState('error');
      setWsMessage(`无法创建 WebSocket：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    socket.onopen = () => {
      setWsState('open');
      setWsMessage('连接成功，内部进程可访问（测试完成后自动关闭）');
      socket.close();
    };
    socket.onerror = () => {
      setWsState('error');
      setWsMessage(
        'WebSocket 连接失败。浏览器需要直连后端 8000 端口，请确认后端已启动、模型处于运行中，' +
          '或通过 NEXT_PUBLIC_WS_BASE / Nginx 转发 /ws。',
      );
    };
    socket.onclose = (event) => {
      // 1000/1005 属于正常关闭（测试完成主动断开），其余视为异常
      if (event.code !== 1000 && event.code !== 1005) {
        setWsState((prev) => (prev === 'open' ? prev : 'error'));
        setWsMessage(
          `连接关闭：code=${event.code}${event.reason ? ` ${event.reason}` : ''}`,
        );
      }
    };
  };

  if (!model) {
    return (
      <Box>
        <Button startIcon={<ArrowBackIcon />} component={Link} href="/models" sx={{ mb: 2 }}>
          返回列表
        </Button>
        {error ? <Alert severity="error">{error}</Alert> : <LinearProgress />}
      </Box>
    );
  }

  const isTts = model.type === 'tts';
  const wsUrl = websocketUrl(model.gateway_path);
  const curlSample = isTts
    ? `curl -X POST "${typeof window === 'undefined' ? '' : window.location.origin}/api/tts/${model.id}" \\\n  -H "X-API-Key: <你的 API Key>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"text":"你好，世界","speaker_id":0,"speed":1.0}' \\\n  --output out.wav`
    : `# 使用 websocat / wscat 连接（音频帧格式见 sherpa-onnx 文档）\nwscat -c "${wsUrl}?api_key=<你的 API Key>"`;

  return (
    <Box>
      <Stack direction="row" spacing={2} sx={{ mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Button startIcon={<ArrowBackIcon />} component={Link} href="/models">
          返回列表
        </Button>
        <Typography variant="h5">{model.name}</Typography>
        <ModelChips model={model} />
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
          {!model.running ? (
            <Button
              variant="contained"
              color="success"
              startIcon={<PlayArrowIcon />}
              disabled={busy || !model.downloaded}
              onClick={() => void runAction('start')}
            >
              启动
            </Button>
          ) : (
            <>
              <Button
                variant="contained"
                color="error"
                startIcon={<StopIcon />}
                disabled={busy}
                onClick={() => setConfirmStop(true)}
              >
                停止
              </Button>
              <Button disabled={busy} onClick={() => void runAction('restart')}>
                重启
              </Button>
            </>
          )}
          <Button startIcon={<RefreshIcon />} onClick={() => void loadLogs()}>
            刷新日志
          </Button>
        </Box>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {notice && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}
      {model.last_error && (
        <Alert severity="warning" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>
          {model.last_error}
        </Alert>
      )}

      {!model.downloaded && (
        <Card variant="outlined" sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              下载模型
            </Typography>
            <Typography variant="body2" color="text.secondary">
              该模型尚未下载，共 {model.files.length} 个文件。点击下方按钮开始下载（
              <code>POST /api/models/{model.id}/download</code>）。
            </Typography>
            <Button
              sx={{ mt: 2 }}
              variant="contained"
              onClick={() => {
                void api
                  .startDownload(model.id)
                  .then(() => setNotice('已开始下载'))
                  .catch((err: unknown) =>
                    setError(err instanceof Error ? err.message : String(err)),
                  );
              }}
            >
              开始下载
            </Button>
            {model.download_progress > 0 && model.download_progress < 1 && (
              <DownloadProgress modelId={model.id} onFinished={() => void loadModel()} />
            )}
          </CardContent>
        </Card>
      )}

      <Tabs value={tab} onChange={(_, value: number) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="模型信息" />
        <Tab label="文件清单" />
        <Tab label="运行日志" />
        <Tab label="调用方式" />
      </Tabs>

      {tab === 0 && (
        <Card variant="outlined">
          <CardContent>
            <Box
              sx={{
                display: 'grid',
                gap: 2,
                gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' },
              }}
            >
              <InfoItem label="模型 ID" value={model.id} />
              <InfoItem label="类型" value={MODEL_TYPE_LABEL[model.type]} />
              <InfoItem label="语言" value={model.language || '-'} />
              <InfoItem label="内存预估" value={formatMegabytes(model.memory_mb)} />
              <InfoItem label="磁盘占用" value={formatBytes(model.size_bytes)} />
              <InfoItem label="健康检查" value={model.health_check === 'http' ? 'HTTP 探活' : 'TCP 探活'} />
              <InfoItem label="上游仓库" value={model.source_repo || '-'} />
              <InfoItem
                label="运行状态"
                value={
                  model.running
                    ? `运行中 · 内部端口 ${model.port} · PID ${model.pid}`
                    : '未运行'
                }
              />
              <InfoItem label="自动重启次数" value={String(model.restart_count)} />
              <InfoItem label="网关地址" value={model.gateway_path} />
            </Box>

            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              启动命令模板
            </Typography>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                bgcolor: 'grey.100',
                borderRadius: 1,
                overflowX: 'auto',
                fontSize: 12,
              }}
            >
              {`${model.start_command} ${model.start_args.join(' ')}`}
            </Box>

            {model.tags.length > 0 && (
              <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 2, flexWrap: 'wrap' }}>
                {model.tags.map((tag) => (
                  <Chip key={tag} size="small" label={tag} variant="outlined" />
                ))}
              </Stack>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 1 && (
        <Card variant="outlined">
          <CardContent>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>占位符</TableCell>
                  <TableCell>文件</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell align="right">大小</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {model.files.map((file) => (
                  <TableRow key={file.key}>
                    <TableCell>
                      <code>{`{${file.key}}`}</code>
                    </TableCell>
                    <TableCell>{file.path}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={file.exists ? '已就绪' : '缺失'}
                        color={file.exists ? 'success' : 'warning'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell align="right">{formatBytes(file.size_bytes)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {tab === 2 && (
        <Card variant="outlined">
          <CardContent>
            <Stack direction="row" spacing={2} sx={{ mb: 1, alignItems: 'center', flexWrap: 'wrap' }}>
              <FormControlLabel
                control={
                  <Switch
                    size="small"
                    checked={autoRefresh}
                    onChange={(event) => setAutoRefresh(event.target.checked)}
                  />
                }
                label="自动刷新（3s）"
              />
              <Button size="small" onClick={() => setLogLines(100)}>
                100 行
              </Button>
              <Button size="small" onClick={() => setLogLines(500)}>
                500 行
              </Button>
              <Typography variant="caption" color="text.secondary">
                {logPath}
              </Typography>
            </Stack>
            <Box
              component="pre"
              sx={{
                m: 0,
                p: 2,
                bgcolor: '#0f172a',
                color: '#d7e3f4',
                borderRadius: 1,
                maxHeight: 480,
                overflow: 'auto',
                fontSize: 12,
                whiteSpace: 'pre-wrap',
              }}
            >
              {logs || '（暂无日志，启动模型后此处会输出子进程的 stdout/stderr）'}
            </Box>
          </CardContent>
        </Card>
      )}

      {tab === 3 && (
        <Stack spacing={2}>
          <Card variant="outlined">
            <CardContent>
              <Typography variant="h6" gutterBottom>
                外部服务如何调用
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                稳定路径由本服务提供，内部动态端口对调用方完全透明。未运行时网关会返回明确提示，
                请先调用 <code>POST /api/models/{model.id}/start</code>。
              </Typography>
              <InfoItem
                label={isTts ? 'HTTP 接口' : 'WebSocket 接口'}
                value={isTts ? `POST /api/tts/${model.id}` : model.gateway_path}
              />
              {!isTts && (
                <Box sx={{ mt: 1 }}>
                  <InfoItem label="完整地址" value={wsUrl} />
                </Box>
              )}
              <Box
                component="pre"
                sx={{
                  mt: 2,
                  m: 0,
                  p: 2,
                  bgcolor: 'grey.100',
                  borderRadius: 1,
                  overflowX: 'auto',
                  fontSize: 12,
                }}
              >
                {curlSample}
              </Box>
            </CardContent>
          </Card>

          {!isTts && (
            <Card variant="outlined">
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  连接测试
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  仅在模型处于运行中时可用；会直接连接内部进程端口以验证网关转发链路。
                </Typography>
                <Button variant="outlined" disabled={!model.running} onClick={testWebSocket}>
                  测试 WebSocket 连接
                </Button>
                {wsMessage && (
                  <Alert
                    sx={{ mt: 2 }}
                    severity={wsState === 'open' ? 'success' : wsState === 'error' ? 'error' : 'info'}
                  >
                    {wsMessage}
                  </Alert>
                )}
              </CardContent>
            </Card>
          )}
        </Stack>
      )}

      <ConfirmDialog
        state={
          confirmStop
            ? {
                action: 'stop',
                title: '停止运行中的模型',
                content: `「${model.name}」当前运行在内部端口 ${model.port}。停止后，所有通过网关调用该模型的服务都会收到错误提示。确认停止？`,
                confirmText: '停止',
                danger: true,
              }
            : null
        }
        busy={busy}
        onCancel={() => setConfirmStop(false)}
        onConfirm={() => void runAction('stop')}
      />
    </Box>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
        {value}
      </Typography>
    </Box>
  );
}
