/**
 * auth-redirect 守卫单测 — 修复生产 P0 登录页无限重载死循环（issue #2757）
 *
 * 场景：无 cookie 访问 /login → initialize() 401 → refresh 401 → 旧逻辑强制跳 /login
 * → 页面重载 → 死循环（实测 237 次导航）。守卫应让 public route 不触发跳转。
 *
 * 2026-09-20（issue #4903）：根路径 `/` 漏在公开白名单外 ⇒ 未登录访问 migaozn.com 官网首页
 * 被判成「受保护页」⇒ AuthProvider 对首页执行 initialize() → /api/auth/me 401 →
 * axios 拦截器强制 window.location.href='/login'（生产实测：页面先渲染再被跳走）。
 * 官网首页必须常开：未登录者不跳转，登录只由用户主动发起；**受保护业务页的跳转一条不放宽**。
 */
// case_ids: DF-014, OB-001, UI-060
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

  it('官网首页（根路径）是公开路由 —— migaozn.com 首页不得把未登录访客挡在门外（issue #4903）', () => {
    expect(isPublicRoute('/')).toBe(true)
    // 带 query 的落地页（投放短链）同样不跳转
    expect(isPublicRoute('/?utm_source=wechat')).toBe(true)
    expect(isPublicRoute('/#hero')).toBe(true)
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

  it('官网首页 401 不跳转 —— 只有用户主动点「商家登录」才去登录页（issue #4903）', () => {
    expect(shouldRedirectToLogin('/')).toBe(false)
  })

  it('在受保护页面 401 时应跳转登录', () => {
    expect(shouldRedirectToLogin('/dashboard')).toBe(true)
    expect(shouldRedirectToLogin('/orders')).toBe(true)
    expect(shouldRedirectToLogin('/customers')).toBe(true)
  })

  it('pathname 未知/缺失时保守跳转', () => {
    expect(shouldRedirectToLogin(undefined)).toBe(true)
    expect(shouldRedirectToLogin('')).toBe(true)
  })
})

describe('PUBLIC_ROUTES（公开面单一源，防漏配 / 防顺手放宽）', () => {
  it('恰好是「首页 + 认证页 + 官网公开页」六项', () => {
    expect([...PUBLIC_ROUTES].sort()).toEqual([
      '/',
      '/about',
      '/contact',
      '/login',
      '/register',
      '/services',
    ])
  })

  it('不含任何受保护业务页（放宽首页不得连带放宽业务面）', () => {
    for (const p of ['/dashboard', '/orders', '/products', '/customers', '/chat', '/settings']) {
      expect(PUBLIC_ROUTES).not.toContain(p)
      expect(shouldRedirectToLogin(p)).toBe(true)
    }
  })
})
