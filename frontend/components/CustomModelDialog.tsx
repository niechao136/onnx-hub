'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { api } from '@/lib/api';
import type { ModelInfo, ModelSpecInput, ModelType } from '@/lib/types';
import { MODEL_TYPE_LABEL } from '@/lib/types';

interface Props {
  open: boolean;
  /** 传入表示编辑，null 表示新增 */
  model: ModelInfo | null;
  onClose: () => void;
  onSaved: (model: ModelInfo) => void;
}

interface FormState {
  id: string;
  name: string;
  type: ModelType;
  language: string;
  description: string;
  memory: string;
  tags: string;
  repo: string;
  mirrors: string;
  files: string;
  command: string;
  args: string;
  cwd: 'model_dir' | 'backend_dir';
  healthKind: 'tcp' | 'http';
  healthPath: string;
  grace: string;
}

const EMPTY: FormState = {
  id: '',
  name: '',
  type: 'asr-streaming',
  language: '',
  description: '',
  memory: '800',
  tags: '',
  repo: '',
  mirrors: '',
  files: 'encoder=encoder.onnx\ntokens=tokens.txt',
  command: 'sherpa-onnx-online-websocket-server',
  args: '--port={port}\n--tokens={tokens}',
  cwd: 'model_dir',
  healthKind: 'tcp',
  healthPath: '/health',
  grace: '1',
};

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function toForm(model: ModelInfo): FormState {
  return {
    id: model.id,
    name: model.name,
    type: model.type,
    language: model.language,
    description: model.description,
    memory: String(model.memory_mb || 0),
    tags: model.tags.join(', '),
    repo: model.source_repo,
    mirrors: model.source_mirrors.join('\n'),
    files: model.files.map((file) => `${file.key}=${file.path}`).join('\n'),
    command: model.start_command,
    args: model.start_args.join('\n'),
    cwd: model.start_cwd,
    healthKind: model.health_check,
    healthPath: model.health_path,
    grace: '1',
  };
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseFiles(value: string): { key: string; path: string }[] {
  return splitLines(value).map((line) => {
    const index = line.indexOf('=');
    if (index <= 0) {
      throw new Error(`文件清单格式错误：「${line}」，应为 key=path`);
    }
    return { key: line.slice(0, index).trim(), path: line.slice(index + 1).trim() };
  });
}

export default function CustomModelDialog({ open, model, onClose, onSaved }: Props) {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(model ? toForm(model) : EMPTY);
  }, [open, model]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const commandPreview = useMemo(() => {
    const args = splitLines(form.args).join(' ');
    return `${form.command} ${args}`.trim();
  }, [form.command, form.args]);

  const handleSubmit = async () => {
    setError(null);

    if (!ID_PATTERN.test(form.id.trim())) {
      setError('模型 ID 只能包含字母、数字、点、下划线和短横线，且以字母或数字开头');
      return;
    }
    if (!form.name.trim()) {
      setError('请填写模型名称');
      return;
    }
    if (!form.command.trim()) {
      setError('请填写启动命令');
      return;
    }

    let files: { key: string; path: string }[];
    try {
      files = parseFiles(form.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    if (files.length === 0) {
      setError('至少需要一个文件，格式为 key=path');
      return;
    }

    const payload: ModelSpecInput = {
      id: form.id.trim(),
      name: form.name.trim(),
      type: form.type,
      language: form.language.trim(),
      description: form.description.trim(),
      memory_mb: Number(form.memory) || 0,
      tags: form.tags
        .split(/[,，]/)
        .map((tag) => tag.trim())
        .filter(Boolean),
      source: {
        repo: form.repo.trim(),
        mirrors: splitLines(form.mirrors),
      },
      files,
      start: {
        command: form.command.trim(),
        args: splitLines(form.args),
        cwd: form.cwd,
        health: { kind: form.healthKind, path: form.healthPath.trim() || '/health' },
        startup_grace: Number(form.grace) || 0,
      },
    };

    setSaving(true);
    try {
      const saved = model
        ? await api.updateCustomModel(model.id, payload)
        : await api.createCustomModel(payload);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{model ? `编辑自定义模型：${model.name}` : '新增自定义模型'}</DialogTitle>
      <DialogContent dividers>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <TextField
            fullWidth
            required
            disabled={Boolean(model)}
            label="模型 ID"
            helperText="URL 中使用的唯一标识，创建后不可修改"
            value={form.id}
            onChange={(event) => update('id', event.target.value)}
          />
          <TextField
            fullWidth
            required
            label="名称"
            value={form.name}
            onChange={(event) => update('name', event.target.value)}
          />
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 2 }}>
          <FormControl fullWidth>
            <InputLabel>类型</InputLabel>
            <Select
              label="类型"
              value={form.type}
              onChange={(event) => update('type', event.target.value as ModelType)}
            >
              {(Object.keys(MODEL_TYPE_LABEL) as ModelType[]).map((type) => (
                <MenuItem key={type} value={type}>
                  {MODEL_TYPE_LABEL[type]}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            fullWidth
            label="语言"
            placeholder="zh / en / zh-en"
            value={form.language}
            onChange={(event) => update('language', event.target.value)}
          />
          <TextField
            fullWidth
            label="内存预估 (MB)"
            value={form.memory}
            onChange={(event) => update('memory', event.target.value)}
          />
        </Stack>

        <TextField
          fullWidth
          multiline
          minRows={2}
          sx={{ mt: 2 }}
          label="描述"
          value={form.description}
          onChange={(event) => update('description', event.target.value)}
        />

        <TextField
          fullWidth
          sx={{ mt: 2 }}
          label="标签"
          helperText="逗号分隔，仅用于展示与过滤"
          value={form.tags}
          onChange={(event) => update('tags', event.target.value)}
        />

        <Divider sx={{ my: 3 }} />

        <Typography variant="subtitle2" gutterBottom>
          文件与下载源
        </Typography>
        <Typography variant="caption" color="text.secondary">
          留空下载源表示「文件自行上传」：保存后到模型详情页逐个上传即可。
        </Typography>

        <TextField
          fullWidth
          sx={{ mt: 2 }}
          label="文件清单"
          helperText="每行一个，格式 key=path；key 会作为启动参数占位符，例如 tokens=tokens.txt"
          multiline
          minRows={3}
          value={form.files}
          onChange={(event) => update('files', event.target.value)}
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 2 }}>
          <TextField
            fullWidth
            label="上游仓库 (repo)"
            placeholder="org/model-name"
            value={form.repo}
            onChange={(event) => update('repo', event.target.value)}
          />
        </Stack>

        <TextField
          fullWidth
          sx={{ mt: 2 }}
          label="下载源模板"
          helperText="每行一个镜像地址，支持 {repo} 与 {file} 占位符，按顺序尝试"
          multiline
          minRows={2}
          value={form.mirrors}
          onChange={(event) => update('mirrors', event.target.value)}
        />

        <Divider sx={{ my: 3 }} />

        <Typography variant="subtitle2" gutterBottom>
          启动方式
        </Typography>

        <TextField
          fullWidth
          required
          sx={{ mt: 2 }}
          label="启动命令"
          helperText="可执行文件名或绝对路径；{python} 表示当前 Python 解释器"
          value={form.command}
          onChange={(event) => update('command', event.target.value)}
        />

        <TextField
          fullWidth
          sx={{ mt: 2 }}
          label="启动参数"
          helperText="每行一个；支持 {port} {model_dir} {data_dir} {backend_dir} {python} 与 files 中的 key"
          multiline
          minRows={3}
          value={form.args}
          onChange={(event) => update('args', event.target.value)}
        />

        <Box sx={{ mt: 2 }}>
          <Typography variant="caption" color="text.secondary">
            命令预览
          </Typography>
          <Box
            component="pre"
            sx={{
              m: 0,
              mt: 0.5,
              p: 1.5,
              bgcolor: 'grey.100',
              borderRadius: 1,
              fontSize: 12,
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
            }}
          >
            {commandPreview || '（尚未填写）'}
          </Box>
        </Box>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 2 }}>
          <FormControl fullWidth>
            <InputLabel>工作目录</InputLabel>
            <Select
              label="工作目录"
              value={form.cwd}
              onChange={(event) => update('cwd', event.target.value as FormState['cwd'])}
            >
              <MenuItem value="model_dir">模型目录 (model_dir)</MenuItem>
              <MenuItem value="backend_dir">后端目录 (backend_dir)</MenuItem>
            </Select>
          </FormControl>
          <FormControl fullWidth>
            <InputLabel>健康检查</InputLabel>
            <Select
              label="健康检查"
              value={form.healthKind}
              onChange={(event) =>
                update('healthKind', event.target.value as FormState['healthKind'])
              }
            >
              <MenuItem value="tcp">TCP 探活（WebSocket 服务）</MenuItem>
              <MenuItem value="http">HTTP 探活</MenuItem>
            </Select>
          </FormControl>
          {form.healthKind === 'http' && (
            <TextField
              fullWidth
              label="探活路径"
              value={form.healthPath}
              onChange={(event) => update('healthPath', event.target.value)}
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          取消
        </Button>
        <Button variant="contained" onClick={() => void handleSubmit()} disabled={saving}>
          {saving ? '保存中…' : model ? '保存修改' : '创建模型'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
