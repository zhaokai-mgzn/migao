/**
 * 认证重定向守卫 — 修复生产 P0：登录页无限重载死循环（issue #2757）
 *
 * 根因：AuthProvider 对所有页面（含 /login）执行 initialize() → 无 cookie 时
 * /api/auth/me 401 → axios 拦截器尝试 refresh → refresh 401 → 强制
 * window.location.href='/login' → 页面重载 → 又 initialize → 死循环（实测 237 次导航）。
 *
 * 修复：public route（登录/注册等）不需要会话恢复，AuthProvider 跳过 initialize；
 * 拦截器在 public route 也不强制跳转（避免循环）。
 */

/** 公开路由（与 auth-guard.tsx 保持一致） */
export const PUBLIC_ROUTES = ['/login', '/register', '/about', '/services', '/contact']

/** 是否公开路由（无需认证即可访问；精确匹配 + 子路径前缀；容忍 query string） */
export function isPublicRoute(pathname: string): boolean {
  if (!pathname) return false
  // 剥离 query/hash（Next.js usePathname 不含 query，但 window.location.pathname 场景防御）
  const clean = pathname.split(/[?#]/)[0]
  return PUBLIC_ROUTES.some((p) => clean === p || clean.startsWith(`${p}/`))
}

/**
 * 401 时是否应跳转登录页。
 * 已在公开路由（如登录页本身）时不跳转——避免 refresh 401 → 强制跳 /login →
 * 页面重载 → 又 initialize 的死循环。
 */
export function shouldRedirectToLogin(pathname: string | undefined): boolean {
  if (!pathname) return true
  return !isPublicRoute(pathname)
}
