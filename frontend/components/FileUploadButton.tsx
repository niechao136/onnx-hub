'use client';

import { useRef, useState } from 'react';
import { Button, CircularProgress, Tooltip } from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { api } from '@/lib/api';

interface Props {
  modelId: string;
  /** 相对模型目录的路径，需与模型定义中的 files[].path 一致 */
  filePath: string;
  label?: string;
  size?: 'small' | 'medium';
  variant?: 'text' | 'outlined' | 'contained';
  onUploaded: () => void;
  onError: (message: string) => void;
}

/** 选择本地文件并以原始字节流上传到模型目录 */
export default function FileUploadButton({
  modelId,
  filePath,
  label = '上传',
  size = 'small',
  variant = 'outlined',
  onUploaded,
  onError,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const handleChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ''; // 允许重复选择同一个文件
    if (!file) return;

    setBusy(true);
    try {
      await api.uploadModelFile(modelId, filePath, file);
      onUploaded();
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <input ref={inputRef} type="file" hidden onChange={(event) => void handleChange(event)} />
      <Tooltip title={`上传到 ${filePath}`}>
        <span>
          <Button
            size={size}
            variant={variant}
            disabled={busy}
            startIcon={busy ? <CircularProgress size={14} /> : <UploadFileIcon />}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? '上传中…' : label}
          </Button>
        </span>
      </Tooltip>
    </>
  );
}
