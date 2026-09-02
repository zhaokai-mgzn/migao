/**
 * auth-redirect 守卫单测 — 修复生产 P0 登录页无限重载死循环（issue #2757）
 *
 * 场景：无 cookie 访问 /login → initialize() 401 → refresh 401 → 旧逻辑强制跳 /login
 * → 页面重载 → 死循环（实测 237 次导航）。守卫应让 public route 不触发跳转。
 */
// case_ids: DF-014, OB-001
import { describe, it, expect } from 'vitest'
import { isPublicRoute, shouldRedirectToLogin, PUBLIC_ROUTES } from '../../../src/lib/auth-redirect'

describe('isPublicRoute', () => {
  it('登录页为公开路由', () => {
    expect(isPublicRoute('/login')).toBe(true)
    expect(isPublicRoute('/login/')).toBe(true)
  })

  it('注册/关于/服务/联系页为公开路由', () => {
    for (const p of ['/register', '/about', '/services', '/contact']) {
      expect(isPublicRoute(p)).toBe(true)
    }
  })

  it('受保护业务页非公开路由', () => {
    for (const p of ['/dashboard', '/orders', '/products', '/employees', '/agent-workspace']) {
      expect(isPublicRoute(p)).toBe(false)
    }
  })

  it('公开路由的子路径也算公开（兼容 query 前缀）', () => {
    expect(isPublicRoute('/login?callbackUrl=%2Fdashboard')).toBe(true)
  })
})

describe('shouldRedirectToLogin（401 跳转守卫 — 防死循环核心）', () => {
  it('在登录页本身 401 时不应再跳转（否则死循环）', () => {
    expect(shouldRedirectToLogin('/login')).toBe(false)
    expect(shouldRedirectToLogin('/register')).toBe(false)
  })

  it('在受保护页面 401 时应跳转登录', () => {
    expect(shouldRedirectToLogin('/dashboard')).toBe(true)
    expect(shouldRedirectToLogin('/orders')).toBe(true)
  })

  it('pathname 未知/缺失时保守跳转', () => {
    expect(shouldRedirectToLogin(undefined)).toBe(true)
    expect(shouldRedirectToLogin('')).toBe(true)
  })

  it('PUBLIC_ROUTES 与 auth-guard.tsx 的 publicRoutes 保持一致（防漏配）', () => {
    // auth-guard.tsx 的 publicRoutes = ['/login','/register','/about','/services','/contact']
    expect(PUBLIC_ROUTES.sort()).toEqual(['/about', '/contact', '/login', '/register', '/services'])
  })
})
