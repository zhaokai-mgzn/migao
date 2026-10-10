// case_ids: UI-082
//
// 判据：**静态资源与抓取指引不得被 proxy 吞成「307 回首页」**（issue #6665）。
//
// 病根（实测，2026-10-10）：
//   `frontend/admin-web/src/proxy.ts` 的 matcher 只排除了 `_next/static|_next/image|favicon.ico|images|fonts`
//   ⇒ 裸域 `migaozn.com` 上 `og-image.png` / `robots.txt` / `sitemap.xml` / `favicon.svg` **全部 307 → `/`**
//   （实测三态读数：`og-image.png → 307 /`｜`robots.txt → 307 /`｜`sitemap.xml → 307 /`｜`favicon.svg → 307 /`），
//   而 `proxy.ts` 的落点正是「Unknown paths on bare domain → homepage」这一条。
//
// **机制口径**（别写成「函数内分支」）：线上 `robots.txt → 307 /` 的成因是 **matcher 没排除静态路径**
// ⇒ 请求真的进了 `proxy()` ⇒ 走到 `handleRequest` 末尾的「Unknown paths on bare domain → homepage」。
// 所以本文件同时判两层：
//   ① **matcher 面**：用 matcher 的正则**真跑一遍路径分类**（把路径重新交给 proxy ⇒ 必红）；
//   ② **函数面**：未知路径不得静默回首页（应给 404 形态）。
import { describe, it, expect } from 'vitest'
import { NextRequest } from 'next/server'
import { proxy, config } from '@/proxy'

/** 显式带上 Host 头（jsdom 的 `URL` 是 `http://localhost/…`，不设 host 会走 proxy 的本地开发分支）。 */
function call(pathname: string, host = 'migaozn.com') {
  const res = proxy(
    new NextRequest(new URL(pathname, `https://${host}`), { headers: { host } }),
  )
  return { status: res.status, location: res.headers.get('location') }
}

/** matcher 的判定：路径是否被 proxy 接管（build 期 Next 用同一条正则做分类）。 */
function matchedByProxy(pathname: string): boolean {
  const source = config.matcher.join('|')
  const re = new RegExp(`^${source}$`)
  return re.test(pathname)
}

/** 该请求是否被「吞成 3xx 回首页」（本缺陷的机器形态）。 */
function isSwallowedToHome(pathname: string, host = 'migaozn.com'): boolean {
  if (!matchedByProxy(pathname)) return false // 没进 proxy ⇒ 不可能被它吞（这正是修好后的形态）
  const { status, location } = call(pathname, host)
  if (status < 300 || status >= 400) return false
  return location === null || new URL(location, `https://${host}`).pathname === '/'
}

const STATIC_PATHS = ['/robots.txt', '/sitemap.xml', '/favicon.svg', '/logo.svg', '/og-image.png']

describe('静态资源与抓取指引不被 307 吞掉（issue #6665）', () => {
  it('裸域上 robots/sitemap/favicon/og 图都不是「3xx 到 /」', () => {
    const swallowed = STATIC_PATHS.filter((p) => isSwallowedToHome(p))
    expect(
      swallowed,
      `这些静态路径被 proxy 吞成「307 回首页」：${swallowed.join(', ')}。` +
        `后果：搜索引擎拿不到 robots/sitemap、微信钉钉分享抓不到 og 图、favicon 也拿不到 —— ` +
        `第一眼看着就像站点坏了。` +
        `修法：src/proxy.ts 的 matcher 排除静态资源路径（扩展名口径），让它们直达 Next / public。`,
    ).toEqual([])
  })

  it('matcher 逐条放行静态路径（这是线上那条 307 的真因面）', () => {
    const intercepted = STATIC_PATHS.filter((p) => matchedByProxy(p))
    expect(
      intercepted,
      `这些静态路径仍被 matcher 交给 proxy：${intercepted.join(', ')}。` +
        `matcher = ${config.matcher.join(' ')}`,
    ).toEqual([])
    // 反向对照：普通页面路径**必须**仍被 matcher 接管（否则整个域名分流失效）
    for (const p of ['/', '/about', '/orders', '/login']) {
      expect(matchedByProxy(p), `${p} 不该被排除在 matcher 之外`).toBe(true)
    }
  })

  it('不存在的路径给 404 形态（不是 307 静默回首页）', () => {
    const bogus = call('/this-path-does-not-exist-9f2c')
    expect(
      bogus.status,
      `裸域上不存在的路径返回 ${bogus.status}${bogus.location ? ` → ${bogus.location}` : ''}：` +
        `静默回首页会把 404 全变成假 200（爬虫会收录一堆同内容的垃圾 URL）。` +
        `修法：未知路径返回 404（NextResponse.rewrite 到 404 或 next() 由 not-found 处理）。`,
    ).not.toBe(307)
    const rootRedirect = call('/this-path-does-not-exist-9f2c', 'migaozn.com')
    if (rootRedirect.location) {
      expect(new URL(rootRedirect.location).pathname).not.toBe('/')
    }
  })
  it('受保护业务路径与首页的行为一条不放宽（负控）', () => {
    // ① 裸域访问业务路径 ⇒ 仍 307 去商家域（这条是既有契约，不能因为改 matcher 被顺手改掉）
    const orders = call('/orders')
    expect(orders.status).toBe(307)
    expect(orders.location).toContain('merchant.migaozn.com')

    // ② 首页照旧放行
    const home = call('/')
    expect(home.status).toBe(200)

    // ③ merchant 子域根路径 ⇒ 仍 307 去 /login
    const merchantRoot = call('/', 'merchant.migaozn.com')
    expect(merchantRoot.status).toBe(307)
    expect(new URL(merchantRoot.location!).pathname).toBe('/login')
  })

  it('判别力自证：matcher 确实排除静态资源扩展名（否则 proxy 会被静态请求叫醒）', () => {
    const matcher = config.matcher.join(' ')
    expect(matcher, `matcher 未排除静态资源：${matcher}`).toMatch(/\.(?:svg|png|txt|xml|ico)/)
  })
})
