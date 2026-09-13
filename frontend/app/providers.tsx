'use client';

import { useEffect, useMemo, useState } from 'react';
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { zhCN } from '@mui/material/locale';
import AppShell from '@/components/AppShell';
import type { ThemeMode } from '@/lib/types';

const STORAGE_KEY = 'sherpa-hub-theme-mode';

const FONT_FAMILY = [
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI"',
  'Roboto',
  '"PingFang SC"',
  '"Microsoft YaHei"',
  'sans-serif',
].join(',');

const LIGHT_PALETTE = {
  primary: { main: '#2c6bed' },
  secondary: { main: '#7b61ff' },
  background: { default: '#f5f7fb' },
};

const DARK_PALETTE = {
  primary: { main: '#7aa2ff' },
  secondary: { main: '#b39dff' },
  background: { default: '#0f1420', paper: '#151b28' },
};

export default function Providers({ children }: { children: React.ReactNode }) {
  // 初始值固定为 light：保证服务端渲染与首帧一致（避免 hydration 不匹配），
  // 挂载后再切换到用户偏好（仅一帧闪动）。
  const [mode, setMode] = useState<ThemeMode>('light');

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === 'light' || saved === 'dark') {
        setMode(saved);
        return;
      }
    } catch {
      /* localStorage 不可用（隐私模式等）时忽略 */
    }
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
      setMode('dark');
    }
  }, []);

  const toggleMode = () =>
    setMode((prev) => {
      const next: ThemeMode = prev === 'light' ? 'dark' : 'light';
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* 忽略写入失败 */
      }
      return next;
    });

  const theme = useMemo(
    () =>
      createTheme(
        {
          palette: {
            mode,
            ...(mode === 'dark' ? DARK_PALETTE : LIGHT_PALETTE),
          },
          shape: { borderRadius: 10 },
          typography: {
            fontFamily: FONT_FAMILY,
            h6: { fontWeight: 600 },
          },
        },
        zhCN,
      ),
    [mode],
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppShell mode={mode} onToggleMode={toggleMode}>
        {children}
      </AppShell>
    </ThemeProvider>
  );
}
