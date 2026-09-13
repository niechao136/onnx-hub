import type {
  ApiKeyCreated,
  ApiKeyInfo,
  DownloadProgressInfo,
  ModelInfo,
  ModelLogs,
  ResourceMetrics,
} from './types';

/** 为空时走同源（Next.js rewrites 或 Nginx 代理） */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '';
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? '';

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(`无法连接后端服务（${API_BASE || '同源'}），请确认已启动`, 0);
  }

  const text = await response.text();
  const payload = text ? safeParse(text) : null;

  if (!response.ok) {
    const detail =
      (payload as { detail?: string } | null)?.detail ?? `请求失败（HTTP ${response.status}）`;
    throw new ApiError(detail, response.status, (payload as { code?: string } | null)?.code);
  }

  return payload as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

const encode = encodeURIComponent;

export const api = {
  listModels: () => request<ModelInfo[]>('/api/models'),

  getModel: (modelId: string) => request<ModelInfo>(`/api/models/${encode(modelId)}`),

  // ---- 下载 ----
  startDownload: (modelId: string, force = false) =>
    request<DownloadProgressInfo>(
      `/api/models/${encode(modelId)}/download${force ? '?force=true' : ''}`,
      { method: 'POST' },
    ),
  downloadProgress: (modelId: string) =>
    request<DownloadProgressInfo>(`/api/models/${encode(modelId)}/download/progress`),
  cancelDownload: (modelId: string) =>
    request<DownloadProgressInfo>(`/api/models/${encode(modelId)}/download`, { method: 'DELETE' }),
  progressStreamUrl: (modelId: string) =>
    `${API_BASE}/api/models/${encode(modelId)}/download/progress/stream`,

  // ---- 进程 ----
  startModel: (modelId: string) =>
    request<ModelInfo>(`/api/models/${encode(modelId)}/start`, { method: 'POST' }),
  stopModel: (modelId: string) =>
    request<ModelInfo>(`/api/models/${encode(modelId)}/stop`, { method: 'POST' }),
  restartModel: (modelId: string) =>
    request<ModelInfo>(`/api/models/${encode(modelId)}/restart`, { method: 'POST' }),
  getLogs: (modelId: string, lines = 200) =>
    request<ModelLogs>(`/api/models/${encode(modelId)}/logs?lines=${lines}`),
  reloadRegistry: () =>
    request<{ reloaded: number; models: string[] }>('/api/registry/reload', { method: 'POST' }),

  // ---- 监控 ----
  getMetrics: () => request<ResourceMetrics>('/api/system/metrics'),
  getHealth: () => request<{ status: string; running_models: number }>('/api/system/health'),

  // ---- API Key ----
  listKeys: () => request<ApiKeyInfo[]>('/api/keys'),
  createKey: (name: string) =>
    request<ApiKeyCreated>('/api/keys', { method: 'POST', body: JSON.stringify({ name }) }),
  deleteKey: (keyId: number) => request<{ deleted: number }>(`/api/keys/${keyId}`, { method: 'DELETE' }),
};

/** WebSocket 网关地址：优先使用 NEXT_PUBLIC_WS_BASE，否则直连后端 8000 端口 */
export function websocketUrl(path: string): string {
  if (WS_BASE) {
    return `${WS_BASE.replace(/\/$/, '')}${path}`;
  }
  if (typeof window === 'undefined') {
    return path;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  return `${protocol}//${host}:8000${path}`;
}
