/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: {
    unoptimized: true,
  },
  // 静态导出时 trailingSlash 可确保路由正常
  trailingSlash: true,
}

export default nextConfig
