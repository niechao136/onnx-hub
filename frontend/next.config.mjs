/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';

const nextConfig = {
  // Docker 部署时产出精简的 standalone 服务端
  output: 'standalone',
  reactStrictMode: true,
  // 把 /api 反代到后端，浏览器侧无需关心跨域；WebSocket 请直连后端或由 Nginx 转发
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
