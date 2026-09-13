import type { Metadata } from 'next';
import { AppRouterCacheProvider } from '@mui/material-nextjs/v16-appRouter';
import Providers from './providers';
import './globals.css';

export const metadata: Metadata = {
  title: 'Sherpa Model Hub',
  description: '基于 sherpa-onnx 的语音模型管理平台：选择、下载、部署 ONNX 语音模型',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AppRouterCacheProvider options={{ key: 'mui' }}>
          <Providers>{children}</Providers>
        </AppRouterCacheProvider>
      </body>
    </html>
  );
}
