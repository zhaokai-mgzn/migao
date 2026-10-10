import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// ── Path lists ──────────────────────────────────────────────────

// 注：ops.migaozn.com 人工审批入口已废弃（2026-08-30 起商家入驻由 AI 自动甄别开通）。

/** Corporate paths allowed on migaozn.com (bare domain), excluding root */
const CORPORATE_PREFIXES = [
  '/about',
  '/contact',
  '/services',
  '/register',
  '/login',
]

/** Dashboard paths: on bare domain, redirect to merchant */
const DASHBOARD_PREFIXES = [
  '/dashboard',
  '/products',
  '/orders',
  '/customers',
  '/chat',
  '/after-sales',
  '/categories',
  '/processing',
  '/employees',
  '/roles',
  '/finance',
  '/notifications',
  '/settings',
  '/knowledge',
  '/agent-workspace',
]

// ── Static assets ───────────────────────────────────────────────
// 静态资源（宽松口径：凡带已知静态扩展名的路径）不再进 proxy（issue #6665）。
// 此前 matcher 只排除了 `_next/static|_next/image|favicon.ico|images|fonts` ⇒
// `robots.txt` / `sitemap.xml` / `favicon.svg` / `og-image.png` 全被末段「未知路径 → 回首页」
// 吞成 **307**（生产实测四条全是 307 → `/`）—— 抓取指引与分享图第一眼就抓不到。
const STATIC_ASSET_RE = /\.(?:svg|png|jpe?g|webp|gif|ico|txt|xml|webmanifest|json|css|js|map|woff2?|ttf|eot)$/i

// ── Helpers ─────────────────────────────────────────────────────

/** Strip port from host header for domain comparison */
function getHostname(host: string): string {
  return host.split(':')[0]
}

function isApiAuth(pathname: string): boolean {
  return pathname.startsWith('/api/auth/')
}

function startsWithAny(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => pathname.startsWith(prefix))
}

// ── Proxy（Next 16 起 `middleware` 文件约定改名 `proxy`，导出名同步为 `proxy`）─────
// 迁移依据（Next 16 自带判据，非猜测）：`next build` 对 `middleware` 文件约定发
//   ⚠ The "middleware" file convention is deprecated. Please use "proxy" instead.
// 且 Next 运行时按 `isProxy ? mod.proxy : mod.middleware` 取处理函数、导出名不符即抛
//   `The Proxy file "..." must export a function named \`proxy\` or a default function.`
// 故本文件与导出名必须**同时**改名。`config.matcher` 语义不变。

export function proxy(request: NextRequest) {
  try {
    const host = request.headers.get('host') || ''
    const hostname = getHostname(host)
    const { pathname } = request.nextUrl

    return handleRequest(hostname, pathname, request)
  } catch (e) {
    console.error('proxy error:', e)
    return new NextResponse('Internal Server Error', { status: 500 })
  }
}

function handleRequest(hostname: string, pathname: string, request: NextRequest): NextResponse {

  // Local dev: skip all domain checks
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return NextResponse.next()
  }

  // ── merchant.migaozn.com ─────────────────────────────────────
  if (hostname === 'merchant.migaozn.com') {
    // 根路径 → 登录页（auth guard 会在登录后跳转到 dashboard）
    if (pathname === '/') {
      return NextResponse.redirect(new URL('/login', request.url))
    }
    return NextResponse.next()
  }

  // ── migaozn.com (bare domain) ────────────────────────────────
  if (hostname === 'migaozn.com' || hostname === 'www.migaozn.com') {
    // Allow API auth for SMS login
    if (isApiAuth(pathname)) {
      return NextResponse.next()
    }

    // Dashboard paths → redirect to merchant
    if (startsWithAny(pathname, DASHBOARD_PREFIXES)) {
      const merchantUrl = new URL(request.url)
      merchantUrl.hostname = 'merchant.migaozn.com'
      merchantUrl.port = '' // 去掉内部端口号，由 CDN/SLB 处理
      merchantUrl.protocol = 'https' // 强制 HTTPS
      return NextResponse.redirect(merchantUrl)
    }

    // Corporate paths pass through (root + listed prefixes) + static assets + 抓取指引
    if (
      pathname === '/' ||
      startsWithAny(pathname, CORPORATE_PREFIXES) ||
      STATIC_ASSET_RE.test(pathname) ||
      pathname === '/robots.txt' ||
      pathname === '/sitemap.xml'
    ) {
      return NextResponse.next()
    }

    // Unknown paths on bare domain: 交给 Next 出 404（**不再静默回首页**）
    // 静默 307 回首页会把所有 404 变成假 200 —— 爬虫会收录一堆同内容的垃圾 URL（issue #6665）。
    // rewrite 到一个不存在的路径 ⇒ Next 用 not-found 渲染 404，且状态码真是 404；
    // 坐标受 `/_not-found` 的静态配置剥离约束（本路径不含 `.` ⇒ 不会被 Next 静态化）。
    return NextResponse.rewrite(new URL('/__proxy-unknown-path', request.url))
  }

  // Unknown domain: pass through
  return NextResponse.next()
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - images (public images)
     * - fonts (public fonts)
     * - 静态扩展名（svg/png/txt/xml/…）与抓取指引（issue #6665）：
     *   否则 robots.txt / sitemap.xml / favicon.svg / og-image.png 会被末段「未知路径」吞成 307 回首页。
     */
    '/((?!_next/static|_next/image|favicon.ico|images|fonts|.*\\.(?:svg|png|jpe?g|webp|gif|ico|txt|xml|webmanifest|json|css|js|map|woff2?|ttf|eot)$).*)',
  ],
}
