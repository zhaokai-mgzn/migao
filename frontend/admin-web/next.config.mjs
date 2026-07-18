/** @type {import('next').NextConfig} */
const nextConfig = {
  // 标准 Next.js SSR 模式，托管于 SAE (next start)
  // 动态路由由服务端渲染直接处理，不再需要 generateStaticParams + SPA fallback

  images: {
    unoptimized: true,
  },

  // 生产环境可通过 NEXT_PUBLIC_ASSET_PREFIX 配置 CDN 前缀
  assetPrefix: process.env.NEXT_PUBLIC_ASSET_PREFIX || undefined,

  // 信任 SLB/CDN 代理的 Host header（避免重定向 URL 带内部端口号 :3001）
  trustHost: true,

  // 限制可接受的 Host 域名，防止 Host Header 注入
  hosts: [
    'migaozn.com',
    'www.migaozn.com',
    'merchant.migaozn.com',
    'admin.migaozn.com',
    'ops.migaozn.com',
  ],
}

export default nextConfig
