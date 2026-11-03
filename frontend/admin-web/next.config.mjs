/**
 * ── 本地 dev / build 的**输出目录物理隔离**（issue #6692）─────────────────────────────
 * 病：`next dev` 与 `next build` 共用 `.next` ⇒ 互相写坏。两个实测形态：
 *   ① dev 侧**已存在的路由 404**（可复现：先 `npm run build` 再起 dev；`rm -rf .next` 即恢复）；
 *   ② build 侧读到 dev 的**半写**生成物 `.next/dev/types/routes.d.ts`，报 9 条 TS 错误。
 * 机制（Next 16.4.3 源码现取，不是推断）：
 *   · dev 阶段的 distDir 被追加 `/dev`（`server/config.js`：`if (phase === PHASE_DEVELOPMENT_SERVER)
 *     result.distDir = join(result.distDir, 'dev')`）；
 *   · build 起手清 distDir 但**保留** `cache|dev|lock|trace`（`build/index.js`）⇒ 两个模式仍共用
 *     `.next` 根与其下的 `cache`；
 *   · build 的类型检查走**项目本地 tsc**（`experimental.useTypeScriptCli` 默认 true）⇒ 查的是
 *     **tsconfig 选中的整个项目**，`.next/dev/types` 在读面上**没有**豁免（Next 源码注释原话：
 *     "including test files and `.next/dev/types` when included"）。
 * 修法：**两个模式用两个目录**（物理隔离 > 每次清理 —— 清理只治一次，隔离治形态）。
 *   · build 保持 `.next`（部署契约不动：Dockerfile `npm run build` → `next start`、CI、`.gitignore`）；
 *   · dev 改到 `.next-dev`（Next 会再追加 `/dev` ⇒ dev 的中间态实际落在 `.next-dev/dev/`）。
 * 选择依据 = `NODE_ENV`：`next` CLI 的 `preAction` 里 `dev → development`、其余 `→ production`，
 * 且**尊重外部已设值** ⇒ `next build` / `next start` / Docker 一律 `.next`，任何形态的 `next dev`
 * （含 Playwright webServer 的 `npx next dev`、`scripts/ui_smoke_merchant.sh` 的 `npm run dev`）都是 `.next-dev`。
 * 牵连面**逐处核对**（漏一处就是新的假绿）：判据 = `tests/unit_ci_workflows/test_next_dev_build_isolation.py`，
 * 台账 = `tests/unit_ci_workflows/next_dev_build_isolation_ledger.json`。
 * ⚠️ 边界：显式 `NODE_ENV=production next dev` 会落到 build 目录（Next 自己也告警）——这是有意保留的
 *    逃生口，不为它再加一层命令嗅探（那等于第二份「当前是哪个模式」的口径）。
 */
const DEV_DIST_DIR = '.next-dev'
const BUILD_DIST_DIR = '.next'

/** @type {import('next').NextConfig} */
const nextConfig = {
  // issue #6692：dev 与 build 各写各的目录（整段理由见上方注释）。
  distDir: process.env.NODE_ENV === 'development' ? DEV_DIST_DIR : BUILD_DIST_DIR,

  // 标准 Next.js SSR 模式，托管于 SWAS 容器 (next start)
  // 动态路由由服务端渲染直接处理，不再需要 generateStaticParams + SPA fallback

  images: {
    unoptimized: true,
  },

  // 生产环境可通过 NEXT_PUBLIC_ASSET_PREFIX 配置 CDN 前缀
  assetPrefix: process.env.NEXT_PUBLIC_ASSET_PREFIX || undefined,

  // `www` → 裸域 301 归一（issue #6665 第 4 条）：两个主机名都能 200 ⇒ 同一份内容两个地址。
  // 301（而非 308）是长期规范：让浏览器与搜索引擎把这层归一缓存下来。
  async redirects() {
    return [
      {
        source: '/:path*',
        has: [{ type: 'host', value: 'www.migaozn.com' }],
        destination: 'https://migaozn.com/:path*',
        permanent: true,
      },
    ]
  },

  // ── 终端发布清单的**同源转发**（issue #8195）──────────────────────────────────
  // 清单真身在 `app.migaozn.com/terminal/`（终端程序硬编码的更新检查地址），而下载页在官网
  // 域名（`migaozn.com` / `www`）⇒ 浏览器直接跨域 GET 拿不到响应体（app 域没有 CORS 头，
  // 给静态下载面加 CORS 是另一个写面、对 `<a download>` 也毫无必要）。
  // 这里改成**服务端同源转发**：页面只请求 `/terminal/...`，浏览器看不到跨域。
  // 下载链接不走这条转发 —— 它指向清单里的绝对地址（`app.migaozn.com`），由 nginx 直接发二进制。
  // 覆盖点：本地演练可把 `TERMINAL_MANIFEST_ORIGIN` 指到别的落地面。
  async rewrites() {
    const terminalOrigin = process.env.TERMINAL_MANIFEST_ORIGIN || 'https://app.migaozn.com'
    return [
      {
        source: '/terminal/:path*',
        destination: `${terminalOrigin}/terminal/:path*`,
      },
    ]
  },

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
