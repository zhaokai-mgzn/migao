// case_ids: UI-144
//
// 类级判据：**官网对外面（`(corporate)` 路由组）的每个页面都必须"匿名可访问"**。
//
// ## 病（2026-11-24 现场取证，不是推断）
//
// 用无 cookie 的全新浏览器打开 `https://migaozn.com/download`：
//   `nav = ["…/download", "…/download", "…/login", "…/login"]` ⇒ **匿名访客被弹去登录页**。
// 根因 = 官网路由要在**两处**登记，`/download` 只登记了一处：
//
// | 白名单 | 出处 | `/download` |
// |---|---|---|
// | 代理层（裸域不被改写 404） | `src/proxy.ts` 的 `CORPORATE_PREFIXES` | ✅ 有（#8195 加的） |
// | 认证守卫（匿名不被弹去登录） | `src/lib/auth-redirect.ts` 的 `PUBLIC_ROUTES` | ❌ **没有** |
//
// ⇒ `AuthGuard` 把它当受保护页去 `initialize()` → 无 cookie 时 `/api/auth/me` 401 →
// axios 拦截器强制 `window.location.href='/login'`。商家点开下载页看到的是登录框。
// 与 issue #4903 是**同一种病**（当时漏的是 `/`），所以这次不只补 `/download`，
// 把「官网路由 × 两处白名单」做成**类级判据**：新增官网页面漏登记 ⇒ 当场判红。
//
// 为什么之前的测试没抓住：`corporate-download.test.tsx` 只断言了 `proxy.ts` 含 `/download`，
// 认证侧那条清单**没有任何判据在看**（#4903 的教训只写进了注释，没写进测试）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

import { PUBLIC_ROUTES, isPublicRoute } from '@/lib/auth-redirect'

const PKG = process.cwd()
const CORPORATE_DIR = join(PKG, 'src/app/(corporate)')

/** 递归收集 `(corporate)` 下的路由（`page.tsx` 所在目录即路由；路由组本身不进 URL）。 */
function corporateRoutes(dir: string = CORPORATE_DIR, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      corporateRoutes(full, acc)
      continue
    }
    if (name !== 'page.tsx') continue
    const rel = relative(CORPORATE_DIR, dir).replace(/\\/g, '/')
    acc.push(rel === '' ? '/' : `/${rel}`)
  }
  return acc.sort()
}

/** 按「精确匹配 + 子路径前缀」判某路由是否被清单覆盖（与 `isPublicRoute` 同口径）。 */
function coveredBy(list: readonly string[], route: string): boolean {
  return list.some((p) => route === p || route.startsWith(`${p}/`))
}

/** 从 `proxy.ts` 源码里取 `CORPORATE_PREFIXES` 的字面量（不 import：proxy 依赖 next/server）。 */
function proxyCorporatePrefixes(): string[] {
  const src = readFileSync(join(PKG, 'src', 'proxy.ts'), 'utf-8')
  const m = src.match(/const CORPORATE_PREFIXES = \[([\s\S]*?)\]/)
  if (!m) throw new Error('proxy.ts 里找不到 CORPORATE_PREFIXES —— 本判据坐标失效')
  return [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1])
}

const ROUTES = corporateRoutes()

describe('官网对外面：每个页面都必须匿名可访问（2026-11-24 现场取证）', () => {
  it('面自证：官网路由被真的扫到（空集会让下面两条变成空跑）', () => {
    expect(ROUTES.length, `只扫到 ${ROUTES.length} 个官网路由 —— 判据坐标失效`).toBeGreaterThanOrEqual(5)
    for (const expected of ['/', '/about', '/contact', '/services', '/download']) {
      expect(ROUTES, `面内缺 ${expected}`).toContain(expected)
    }
  })

  it('每个官网路由都在认证守卫的 PUBLIC_ROUTES 里（否则匿名访客被弹去登录页）', () => {
    const offenders = ROUTES.filter((route) => !coveredBy(PUBLIC_ROUTES, route))
    expect(
      offenders,
      `这些官网页面没登记进 src/lib/auth-redirect.ts 的 PUBLIC_ROUTES：${offenders.join(', ')}\n` +
        `后果（实测）：无 cookie 打开该页 ⇒ AuthGuard 判定为受保护页 ⇒ /api/auth/me 401 ⇒ 强制跳 /login，` +
        `商家看到的是登录框而不是页面（2026-11-24 用真实浏览器在 https://migaozn.com/download 复现）。\n` +
        `修法：把路由加进 PUBLIC_ROUTES（单一源，别处不许再抄一份）。`,
    ).toEqual([])
  })

  it('每个官网路由都在 proxy.ts 的 CORPORATE_PREFIXES 里（否则裸域访问被改写 404）', () => {
    const prefixes = proxyCorporatePrefixes()
    const offenders = ROUTES.filter((route) => route !== '/' && !coveredBy(prefixes, route))
    expect(
      offenders,
      `这些官网页面没登记进 src/proxy.ts 的 CORPORATE_PREFIXES：${offenders.join(', ')}\n` +
        `后果：裸域（migaozn.com）访问会被末段「未知路径」改写 404。`,
    ).toEqual([])
  })

  it('🔴 `/download` 是公开路由（本条是上面类级判据的实例判据，报错时点名）', () => {
    expect(isPublicRoute('/download'), '`/download` 仍被当作受保护路由 —— 匿名访客会看到登录页').toBe(true)
    expect(isPublicRoute('/download/'), '带尾斜杠的 /download/ 也必须判公开（trailingSlash 兼容）').toBe(true)
    // 受保护业务页一条都不许放宽（防止「为了消红把 PUBLIC_ROUTES 写成 /」）
    for (const guarded of ['/downloads', '/dashboard', '/orders']) {
      expect(isPublicRoute(guarded), `${guarded} 不该是公开路由`).toBe(false)
    }
  })

  it('判别力自证：漏登记的路由会被判红、登记对的不会（否则是空断言）', () => {
    expect(coveredBy(PUBLIC_ROUTES, '/download')).toBe(true)
    expect(coveredBy(['/', '/login', '/about', '/services', '/contact'], '/download')).toBe(false)
    expect(coveredBy(['/download'], '/download')).toBe(true)
    expect(coveredBy(['/'], '/download')).toBe(false)
    // 前缀匹配不能把「名字前缀相同的另一页」误判为覆盖（/downloads ≠ /download）
    expect(coveredBy(['/download'], '/downloads')).toBe(false)
  })
})
