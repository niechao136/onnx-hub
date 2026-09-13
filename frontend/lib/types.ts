export type ModelType = 'asr-streaming' | 'asr-offline' | 'tts';

export type ModelStatus = 'stopped' | 'starting' | 'running' | 'stopping' | 'restarting' | 'error';

export interface ModelFileInfo {
  key: string;
  path: string;
  exists: boolean;
  size_bytes: number;
}

export interface ModelInfo {
  id: string;
  name: string;
  type: ModelType;
  language: string;
  description: string;
  memory_mb: number;
  tags: string[];

  downloaded: boolean;
  download_progress: number;
  size_bytes: number;
  running: boolean;
  status: ModelStatus;
  port: number | null;
  pid: number | null;
  restart_count: number;
  last_error: string | null;

  gateway_path: string;
  source_repo: string;
  source_mirrors: string[];
  files: ModelFileInfo[];
  start_command: string;
  start_args: string[];
  start_cwd: 'model_dir' | 'backend_dir';
  health_check: 'tcp' | 'http';
  health_path: string;
  origin: 'builtin' | 'custom';
  downloadable: boolean;
}

/** 自定义模型的新增/编辑入参，结构与 models.yaml 单条定义一致 */
export interface ModelSpecInput {
  id: string;
  name: string;
  type: ModelType;
  language?: string;
  description?: string;
  memory_mb?: number;
  tags?: string[];
  source?: { repo?: string; mirrors?: string[] };
  files: { key: string; path: string }[];
  start: {
    command: string;
    args?: string[];
    cwd?: 'model_dir' | 'backend_dir';
    health?: { kind: 'tcp' | 'http'; path?: string };
    startup_grace?: number;
  };
}

export interface DownloadProgressInfo {
  model_id: string;
  status: 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  total_files: number;
  completed_files: number;
  downloaded_bytes: number;
  current_file: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ModelLogs {
  model_id: string;
  lines: number;
  content: string;
  log_path: string;
}

export interface ApiKeyInfo {
  id: number;
  name: string;
  key_prefix: string;
  active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKeyInfo {
  key: string;
}

export interface ProcessUsage {
  model_id: string;
  pid: number;
  port: number;
  status: string;
  restart_count: number;
  uptime_seconds: number;
  cpu_percent: number;
  memory_mb: number;
}

export interface ResourceMetrics {
  running_models: number;
  max_running_models: number;
  port_pool_start: number;
  port_pool_end: number;
  system_cpu_percent: number;
  system_memory_percent: number;
  system_memory_used_mb: number;
  system_memory_total_mb: number;
  processes: ProcessUsage[];
}

export const MODEL_TYPE_LABEL: Record<ModelType, string> = {
  'asr-streaming': 'ASR 流式识别',
  'asr-offline': 'ASR 离线识别',
  tts: 'TTS 语音合成',
};
