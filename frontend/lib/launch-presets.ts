/** 常用 sherpa-onnx 启动脚本预设。

除手动填写外，可在「新增 / 编辑自定义模型」表单里一键套用，
避免每次手写命令与参数模板（占位符拼写错误是最常见的启动失败原因）。
占位符说明见 README「新增模型」章节。
*/

export interface LaunchPresetFile {
  key: string;
  path: string;
}

export interface LaunchPreset {
  id: string;
  label: string;
  description: string;
  command: string;
  args: string[];
  cwd: 'model_dir' | 'backend_dir';
  health: { kind: 'tcp' | 'http'; path: string };
  /** 建议的文件清单骨架，会在文件清单为空时自动填入 */
  files: LaunchPresetFile[];
}

export const LAUNCH_PRESETS: LaunchPreset[] = [
  {
    id: 'online-transducer',
    label: '流式 ASR · Transducer（Zipformer / Conformer）',
    description:
      'sherpa-onnx 官方在线 WebSocket 服务，适合实时字幕、语音助手。文件需含 encoder / decoder / joiner / tokens。',
    command: 'sherpa-onnx-online-websocket-server',
    args: [
      '--port={port}',
      '--tokens={tokens}',
      '--encoder={encoder}',
      '--decoder={decoder}',
      '--joiner={joiner}',
      '--num-threads=2',
      '--decoding-method=greedy_search',
    ],
    cwd: 'model_dir',
    health: { kind: 'tcp', path: '/health' },
    files: [
      { key: 'encoder', path: 'encoder.onnx' },
      { key: 'decoder', path: 'decoder.onnx' },
      { key: 'joiner', path: 'joiner.onnx' },
      { key: 'tokens', path: 'tokens.txt' },
    ],
  },
  {
    id: 'online-paraformer',
    label: '流式 ASR · Paraformer',
    description: '阿里 Paraformer 在线流式版本，同样走官方在线 WebSocket 服务。',
    command: 'sherpa-onnx-online-websocket-server',
    args: [
      '--port={port}',
      '--tokens={tokens}',
      '--paraformer-encoder={encoder}',
      '--paraformer-decoder={decoder}',
      '--num-threads=2',
    ],
    cwd: 'model_dir',
    health: { kind: 'tcp', path: '/health' },
    files: [
      { key: 'encoder', path: 'encoder.onnx' },
      { key: 'decoder', path: 'decoder.onnx' },
      { key: 'tokens', path: 'tokens.txt' },
    ],
  },
  {
    id: 'offline-paraformer',
    label: '离线 ASR · Paraformer',
    description: '整段音频一次性识别，准确率更高，适合转写录音文件。',
    command: 'sherpa-onnx-offline-websocket-server',
    args: ['--port={port}', '--tokens={tokens}', '--paraformer={model}', '--num-threads=2'],
    cwd: 'model_dir',
    health: { kind: 'tcp', path: '/health' },
    files: [
      { key: 'model', path: 'model.onnx' },
      { key: 'tokens', path: 'tokens.txt' },
    ],
  },
  {
    id: 'offline-whisper',
    label: '离线 ASR · Whisper',
    description: 'OpenAI Whisper 的 ONNX 版本，支持多语言。',
    command: 'sherpa-onnx-offline-websocket-server',
    args: [
      '--port={port}',
      '--tokens={tokens}',
      '--whisper-encoder={encoder}',
      '--whisper-decoder={decoder}',
      '--num-threads=2',
    ],
    cwd: 'model_dir',
    health: { kind: 'tcp', path: '/health' },
    files: [
      { key: 'encoder', path: 'encoder.onnx' },
      { key: 'decoder', path: 'decoder.onnx' },
      { key: 'tokens', path: 'tokens.txt' },
    ],
  },
  {
    id: 'tts-vits',
    label: 'TTS · VITS（本平台附带 runner）',
    description:
      '官方未提供 TTS 的 server 可执行文件，用本项目附带的 app/runners.tts_server（仅做 HTTP 适配，推理仍走官方 OfflineTts）。',
    command: '{python}',
    args: [
      '-m',
      'app.runners.tts_server',
      '--port={port}',
      '--vits-model={model}',
      '--tokens={tokens}',
      '--lexicon={lexicon}',
      '--num-threads=2',
    ],
    cwd: 'backend_dir',
    health: { kind: 'http', path: '/health' },
    files: [
      { key: 'model', path: 'model.onnx' },
      { key: 'tokens', path: 'tokens.txt' },
      { key: 'lexicon', path: 'lexicon.txt' },
    ],
  },
];

export function filesToText(files: LaunchPresetFile[]): string {
  return files.map((file) => `${file.key}=${file.path}`).join('\n');
}

/** 判断某个模型当前使用的启动命令是否命中预设（用于回显与详情页展示） */
export function matchLaunchPreset(command: string, args: string[]): LaunchPreset | null {
  const normalizedCommand = (command || '').trim();
  const normalizedArgs = args.map((arg) => arg.trim()).filter(Boolean).join('\n');
  return (
    LAUNCH_PRESETS.find(
      (preset) =>
        preset.command === normalizedCommand && preset.args.join('\n') === normalizedArgs,
    ) ?? null
  );
}
