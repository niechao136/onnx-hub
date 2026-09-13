'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  AppBar,
  Box,
  Button,
  Container,
  IconButton,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import GraphicEqIcon from '@mui/icons-material/GraphicEq';
import type { ThemeMode } from '@/lib/types';

const NAV_ITEMS = [
  { href: '/models', label: '模型管理' },
  { href: '/keys', label: 'API Key' },
];

interface Props {
  children: React.ReactNode;
  mode: ThemeMode;
  onToggleMode: () => void;
}

export default function AppShell({ children, mode, onToggleMode }: Props) {
  const pathname = usePathname();

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppBar position="sticky" color="default" elevation={1}>
        <Toolbar sx={{ gap: 1 }}>
          <GraphicEqIcon color="primary" />
          <Typography variant="h6" sx={{ mr: 3, whiteSpace: 'nowrap' }}>
            Sherpa Model Hub
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexGrow: 1 }}>
            {NAV_ITEMS.map((item) => {
              const active = pathname?.startsWith(item.href);
              return (
                <Button
                  key={item.href}
                  component={Link}
                  href={item.href}
                  size="small"
                  variant={active ? 'contained' : 'text'}
                  disableElevation
                >
                  {item.label}
                </Button>
              );
            })}
          </Box>
          <Tooltip title={mode === 'dark' ? '切换到浅色主题' : '切换到深色主题'}>
            <IconButton
              size="small"
              color="inherit"
              onClick={onToggleMode}
              aria-label="切换主题"
              sx={{ mr: 1 }}
            >
              {mode === 'dark' ? (
                <Brightness7Icon fontSize="small" />
              ) : (
                <Brightness4Icon fontSize="small" />
              )}
            </IconButton>
          </Tooltip>
          <Button size="small" href="/docs" target="_blank" rel="noreferrer" component="a">
            API 文档
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 3, flexGrow: 1 }}>
        {children}
      </Container>

      <Box component="footer" sx={{ py: 2, textAlign: 'center', color: 'text.secondary' }}>
        <Typography variant="caption">
          Sherpa Model Hub · 推理全部由 sherpa-onnx 官方可执行文件完成，本项目只做进程管理与 API 转发
        </Typography>
      </Box>
    </Box>
  );
}
