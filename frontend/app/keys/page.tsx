'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  LinearProgress,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/DeleteOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';
import ConfirmDialog, { type ConfirmState } from '@/components/ConfirmDialog';
import { api } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import type { ApiKeyInfo } from '@/lib/types';

export default function KeysPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setKeys(await api.listKeys());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const created = await api.createKey(newName || 'default');
      setCreatedKey(created.key);
      setCreateOpen(false);
      setNewName('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm) return;
    setBusy(true);
    try {
      await api.deleteKey(confirm.payload as number);
      setNotice('API Key 已删除');
      setConfirm(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setNotice('已复制到剪贴板');
    } catch {
      setNotice('复制失败，请手动选择文本复制');
    }
  };

  return (
    <Box>
      <Stack
        direction="row"
        sx={{ mb: 2, alignItems: 'center', justifyContent: 'space-between' }}
      >
        <Box>
          <Typography variant="h5">API Key 管理</Typography>
          <Typography variant="body2" color="text.secondary">
            外部服务调用 <code>WS /ws/asr/&#123;model_id&#125;</code> 与{' '}
            <code>POST /api/tts/&#123;model_id&#125;</code> 时，需携带
            <code> Authorization: Bearer &lt;key&gt;</code>、<code>X-API-Key</code>
            或查询参数 <code>?api_key=</code>。
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button startIcon={<RefreshIcon />} onClick={() => void refresh()}>
            刷新
          </Button>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            生成 Key
          </Button>
        </Stack>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card variant="outlined">
        <CardContent>
          {loading && <LinearProgress sx={{ mb: 2 }} />}
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>名称</TableCell>
                <TableCell>Key 前缀</TableCell>
                <TableCell>状态</TableCell>
                <TableCell>创建时间</TableCell>
                <TableCell>最近使用</TableCell>
                <TableCell align="right">操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {keys.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>{item.name}</TableCell>
                  <TableCell>
                    <code>{item.key_prefix}…</code>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      variant="outlined"
                      color={item.active ? 'success' : 'default'}
                      label={item.active ? '启用' : '禁用'}
                    />
                  </TableCell>
                  <TableCell>{formatDateTime(item.created_at)}</TableCell>
                  <TableCell>{formatDateTime(item.last_used_at)}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="删除">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() =>
                          setConfirm({
                            action: 'delete-key',
                            title: '删除 API Key',
                            content: `删除后使用该 Key 的外部服务将立即失效，且无法恢复。确认删除「${item.name}」？`,
                            confirmText: '删除',
                            danger: true,
                            payload: item.id,
                          })
                        }
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
              {!loading && keys.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 3 }}>
                      还没有 API Key，点击右上角「生成 Key」创建第一个
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 创建 Key */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>生成 API Key</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            margin="dense"
            label="用途备注"
            placeholder="例如：字幕服务"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)} disabled={creating}>
            取消
          </Button>
          <Button variant="contained" onClick={() => void handleCreate()} disabled={creating}>
            {creating ? '生成中…' : '生成'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 明文只展示一次 */}
      <Dialog open={Boolean(createdKey)} onClose={() => setCreatedKey(null)} maxWidth="sm" fullWidth>
        <DialogTitle>请立即保存该 Key</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            明文只在本次生成时展示一次，服务端仅保存哈希值，关闭后无法再次查看。
          </Alert>
          <Box
            component="pre"
            sx={{
              m: 0,
              p: 2,
              bgcolor: 'action.hover',
              color: 'text.primary',
              borderRadius: 1,
              overflowX: 'auto',
              fontSize: 13,
              wordBreak: 'break-all',
              whiteSpace: 'pre-wrap',
            }}
          >
            {createdKey}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button startIcon={<ContentCopyIcon />} onClick={() => void copy(createdKey ?? '')}>
            复制
          </Button>
          <Button variant="contained" onClick={() => setCreatedKey(null)}>
            我已保存
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        state={confirm}
        busy={busy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void handleDelete()}
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
