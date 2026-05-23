/** @type {import('next').NextConfig} */
const nextConfig = {
  // 静态导出，用于 OSS 静态网站托管部署
  output: 'export',

  images: {
    unoptimized: true,
  },

  // 静态导出时 trailingSlash 确保 OSS 路由回退正常
  trailingSlash: true,

  // 生产环境可通过 NEXT_PUBLIC_ASSET_PREFIX 配置 CDN 前缀
  // 例如: https://cdn.migaozn.com 加速静态资源
  assetPrefix: process.env.NEXT_PUBLIC_ASSET_PREFIX || undefined,

  // 环境变量透传到客户端（构建时替换）
  env: {
    NEXT_PUBLIC_BUILD_TIME: new Date().toISOString(),
  },
}

export default nextConfig
