'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ConfirmDialog, { type ConfirmState } from '@/components/ConfirmDialog';
import ModelCard from '@/components/ModelCard';
import ResourceMonitor from '@/components/ResourceMonitor';
import { api } from '@/lib/api';
import type { ModelInfo, ModelType, ResourceMetrics } from '@/lib/types';
import { MODEL_TYPE_LABEL } from '@/lib/types';

const TYPE_ORDER: ModelType[] = ['asr-streaming', 'asr-offline', 'tts'];
const POLL_INTERVAL_MS = 5000;

type Filter = 'all' | ModelType;

export default function ModelsPage() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [metrics, setMetrics] = useState<ResourceMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [keyword, setKeyword] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [list, systemMetrics] = await Promise.all([api.listModels(), api.getMetrics()]);
      setModels(list);
      setMetrics(systemMetrics);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // 首次加载：把仍在进行中的下载任务恢复为「下载中」状态
  useEffect(() => {
    let alive = true;
    void (async () => {
      await refresh();
      try {
        const list = await api.listModels();
        const pending: string[] = [];
        await Promise.all(
          list
            .filter((model) => !model.downloaded)
            .map(async (model) => {
              try {
                const progress = await api.downloadProgress(model.id);
                if (progress.status === 'running' || progress.status === 'pending') {
                  pending.push(model.id);
                }
              } catch {
                /* 单个模型查询失败不影响列表 */
              }
            }),
        );
        if (alive) setDownloading(pending);
      } catch {
        /* 忽略 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [refresh]);

  // 轮询运行状态
  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const runAction = useCallback(
    async (model: ModelInfo, action: () => Promise<unknown>, successMessage: string) => {
      setBusyId(model.id);
      try {
        await action();
        setNotice(successMessage);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        await refresh();
      } finally {
        setBusyId(null);
      }
    },
    [refresh],
  );

  const handleDownload = useCallback(
    (model: ModelInfo, force = false) => {
      if (force) {
        setConfirm({
          action: 'redownload',
          title: '重新下载模型',
          content: `将重新下载「${model.name}」的全部文件，已有的文件会被跳过或覆盖。确认继续？`,
          confirmText: '重新下载',
          payload: model,
        });
        return;
      }
      void (async () => {
        setDownloading((prev) => [...prev, model.id]);
        try {
          await api.startDownload(model.id);
          setNotice(`已开始下载「${model.name}」`);
        } catch (err) {
          setDownloading((prev) => prev.filter((id) => id !== model.id));
          setError(err instanceof Error ? err.message : String(err));
        }
      })();
    },
    [],
  );

  const handleCancelDownload = useCallback((model: ModelInfo) => {
    void (async () => {
      try {
        await api.cancelDownload(model.id);
        setDownloading((prev) => prev.filter((id) => id !== model.id));
        setNotice('已取消下载');
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, []);

  const handleDownloadFinished = useCallback(
    (modelId: string) => {
      setDownloading((prev) => prev.filter((id) => id !== modelId));
      void refresh();
    },
    [refresh],
  );

  const onConfirm = useCallback(async () => {
    if (!confirm) return;
    const target = confirm.payload as ModelInfo | undefined;
    setBusyId(target?.id ?? null);
    try {
      if (confirm.action === 'stop' && target) {
        await api.stopModel(target.id);
        setNotice(`已停止「${target.name}」`);
      } else if (confirm.action === 'restart' && target) {
        await api.restartModel(target.id);
        setNotice(`已重启「${target.name}」`);
      } else if (confirm.action === 'redownload' && target) {
        setDownloading((prev) => [...prev, target.id]);
        await api.startDownload(target.id, true);
        setNotice(`已开始重新下载「${target.name}」`);
      }
      setConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setConfirm(null);
    } finally {
      setBusyId(null);
      await refresh();
    }
  }, [confirm, refresh]);

  const filtered = useMemo(() => {
    const term = keyword.trim().toLowerCase();
    return models.filter((model) => {
      if (filter !== 'all' && model.type !== filter) return false;
      if (!term) return true;
      return (
        model.name.toLowerCase().includes(term) ||
        model.id.toLowerCase().includes(term) ||
        model.tags.some((tag) => tag.toLowerCase().includes(term))
      );
    });
  }, [models, filter, keyword]);

  const grouped = useMemo(() => {
    const map = new Map<ModelType, ModelInfo[]>();
    for (const type of TYPE_ORDER) {
      const items = filtered.filter((model) => model.type === type);
      if (items.length) map.set(type, items);
    }
    return map;
  }, [filtered]);

  return (
    <Box>
      <Stack
        direction="row"
        sx={{ mb: 2, alignItems: 'center', justifyContent: 'space-between' }}
      >
        <Box>
          <Typography variant="h5">模型广场</Typography>
          <Typography variant="body2" color="text.secondary">
            选择、下载并启动 ONNX 语音模型，启动后可通过统一网关地址对外提供服务
          </Typography>
        </Box>
        <Button startIcon={<RefreshIcon />} onClick={() => void refresh()} disabled={loading}>
          刷新
        </Button>
      </Stack>

      <ResourceMonitor metrics={metrics} />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <Tabs
          value={filter}
          onChange={(_, value: Filter) => setFilter(value)}
          variant="scrollable"
          scrollButtons="auto"
        >
          <Tab value="all" label="全部" />
          <Tab value="asr-streaming" label={MODEL_TYPE_LABEL['asr-streaming']} />
          <Tab value="asr-offline" label={MODEL_TYPE_LABEL['asr-offline']} />
          <Tab value="tts" label={MODEL_TYPE_LABEL.tts} />
        </Tabs>
        <TextField
          size="small"
          label="搜索模型"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          sx={{ ml: { sm: 'auto' }, minWidth: 220 }}
        />
      </Stack>

      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {!loading && filtered.length === 0 && (
        <Alert severity="info">没有匹配的模型。可编辑 backend/app/config/models.yaml 新增，或在搜索框更换关键词。</Alert>
      )}

      {[...grouped.entries()].map(([type, items]) => (
        <Box key={type} sx={{ mb: 4 }}>
          <Typography variant="h6" sx={{ mb: 1.5 }}>
            {MODEL_TYPE_LABEL[type]}（{items.length}）
          </Typography>
          <Box
            sx={{
              display: 'grid',
              gap: 2,
              gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' },
            }}
          >
            {items.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                downloading={downloading.includes(model.id)}
                busy={busyId === model.id}
                onDownload={handleDownload}
                onCancelDownload={handleCancelDownload}
                onStart={(target) =>
                  void runAction(target, () => api.startModel(target.id), `「${target.name}」已启动`)
                }
                onStop={(target) =>
                  setConfirm({
                    action: 'stop',
                    title: '停止运行中的模型',
                    content: `「${target.name}」当前运行在内部端口 ${target.port}，停止后该模型的对网关地址将不可用。确认停止？`,
                    confirmText: '停止',
                    danger: true,
                    payload: target,
                  })
                }
                onRestart={(target) =>
                  setConfirm({
                    action: 'restart',
                    title: '重启模型',
                    content: `将重启「${target.name}」，期间服务会短暂中断。确认继续？`,
                    confirmText: '重启',
                    payload: target,
                  })
                }
                onDownloadFinished={handleDownloadFinished}
              />
            ))}
          </Box>
        </Box>
      ))}

      <ConfirmDialog
        state={confirm}
        busy={busyId !== null}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void onConfirm()}
      />

      <Snackbar
        open={Boolean(notice)}
        autoHideDuration={3000}
        onClose={() => setNotice(null)}
        message={notice}
      />
    </Box>
  );
}
