/** @type {import('next').NextConfig} */
const nextConfig = {
  // 标准 Next.js SSR 模式，托管于 SWAS 容器 (next start)
  // 动态路由由服务端渲染直接处理，不再需要 generateStaticParams + SPA fallback

  images: {
    unoptimized: true,
  },

  // 生产环境可通过 NEXT_PUBLIC_ASSET_PREFIX 配置 CDN 前缀
  assetPrefix: process.env.NEXT_PUBLIC_ASSET_PREFIX || undefined,

  // ── 已删除两个**无效**顶层键：`trustHost` / `hosts` ────────────────────────────
  // 它们从未是 Next 的配置项（Next 14.2.35 与 16.3.5 的 config schema 里都没有；
  // 旧版只是**静默忽略**，Next 16 起每次构建都会告警：
  //   ⚠ Invalid next.config.mjs options detected: Unrecognized key(s) in object: 'trustHost', 'hosts'
  // ⇒ 原注释宣称的「信任 SLB/CDN 代理的 Host header」「限制可接受的 Host 域名，
  //    防止 Host Header 注入」**两项保护都不存在**（死配置）。
  //
  // 这不是本次升级引入的回归：`docs/audit-2026-08/07-security-and-llm-attack-audit.md`
  // 的 P2-17 早已记录「`next.config.mjs` Host 白名单无效」。
  // 现状的 Host 处理全部在 `frontend/admin-web/src/proxy.ts`（Next 16 前名为 middleware）：
  // 按 hostname 分流 + 显式 `merchantUrl.port = ''` 去掉内部端口 —— 重定向 URL 的端口问题
  // 由它解决，不依赖本文件。
  // ⚠️ 真正的 Host header 白名单加固**未在本包完成**（见 PR body「剩余清单」）：Next 没有
  //    开箱的 hosts allowlist，须在 `src/proxy.ts` 里做 fail-closed 校验或由 SLB/CDN 承担。
}

export default nextConfig
