import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// ── Path lists ──────────────────────────────────────────────────

/** Paths allowed on ops.migaozn.com (plus /api/auth/*) */
const OPS_ALLOWED_PREFIXES = [
  '/registrations',
  '/platform-dashboard',
  '/tenants',
  '/platform-settings',
  '/login',
]

/** Super-admin paths blocked on merchant.migaozn.com */
const SUPER_ADMIN_PREFIXES = [
  '/registrations',
  '/platform-dashboard',
  '/tenants',
  '/platform-settings',
]

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

// ── Middleware ───────────────────────────────────────────────────

export function middleware(request: NextRequest) {
  try {
    const host = request.headers.get('host') || ''
    const hostname = getHostname(host)
    const { pathname } = request.nextUrl

    return handleRequest(hostname, pathname, request)
  } catch (e) {
    console.error('middleware error:', e)
    return new NextResponse('Internal Server Error', { status: 500 })
  }
}

function handleRequest(hostname: string, pathname: string, request: NextRequest): NextResponse {

  // Local dev: skip all domain checks
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return NextResponse.next()
  }

  // ── ops.migaozn.com ──────────────────────────────────────────
  if (hostname === 'ops.migaozn.com') {
    if (startsWithAny(pathname, OPS_ALLOWED_PREFIXES) || isApiAuth(pathname)) {
      return NextResponse.next()
    }
    return NextResponse.redirect(new URL('/registrations', request.url))
  }

  // ── merchant.migaozn.com ─────────────────────────────────────
  if (hostname === 'merchant.migaozn.com') {
    // 根路径 → 登录页（auth guard 会在登录后跳转到 dashboard）
    if (pathname === '/') {
      return NextResponse.redirect(new URL('/login', request.url))
    }
    if (startsWithAny(pathname, SUPER_ADMIN_PREFIXES)) {
      return new NextResponse(null, { status: 404 })
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

    // Corporate paths pass through (root + listed prefixes)
    if (pathname === '/' || startsWithAny(pathname, CORPORATE_PREFIXES)) {
      return NextResponse.next()
    }

    // Unknown paths on bare domain → homepage
    return NextResponse.redirect(new URL('/', request.url))
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
     */
    '/((?!_next/static|_next/image|favicon.ico|images|fonts).*)',
  ],
}
