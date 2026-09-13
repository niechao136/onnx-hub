'use client';

import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { zhCN } from '@mui/material/locale';
import AppShell from '@/components/AppShell';

const theme = createTheme(
  {
    palette: {
      mode: 'light',
      primary: { main: '#2c6bed' },
      secondary: { main: '#7b61ff' },
      background: { default: '#f5f7fb' },
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: [
        '-apple-system',
        'BlinkMacSystemFont',
        '"Segoe UI"',
        'Roboto',
        '"PingFang SC"',
        '"Microsoft YaHei"',
        'sans-serif',
      ].join(','),
      h6: { fontWeight: 600 },
    },
  },
  zhCN,
);

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppShell>{children}</AppShell>
    </ThemeProvider>
  );
}
