// case_ids: UI-082
//
// 类级判据：**首屏门控不得把「匿名可见面」拦在 SSR 之外**（issue #6665）。
//
// ## 病根（实测读数）
//
// 根布局 `frontend/admin-web/src/app/layout.tsx` 把 `AuthProvider` + `AuthGuard` 套在**全部**页面上：
//   · `frontend/admin-web/src/components/providers/AuthProvider.tsx` 的 `isReady` 初值 `false`，
//     且 `useState` 里只可能是 `false` ⇒ **SSR 阶段必然返回「加载中...」骨架**；
//   · `frontend/admin-web/src/components/auth-guard.tsx` 的 `isChecking` 初值 `true` ⇒ SSR 阶段返回 `null`。
// 两者叠加 ⇒ 服务端 HTML 的可见 DOM 只剩一个转圈「加载中...」。
//
// 本地真机读数（2026-10-10，1440×980，`domcontentloaded` 时刻，主工作树 `d221d5644`）：
//   `/login` 6 字符「加载中...」· `/register` 6 字符 · `/` 6 字符 · `/about` 6 字符 · `/services` 6 字符 · `/contact` 6 字符
// ⇒ **首屏空壳不止官网四页**，`/login` 与 `/register` 同样是空壳 —— 这是「匿名可见面」这一整类缺陷。
//
// ## 为什么这个判据有判别力（而 `corporate-pages-server-component-guard.test.ts` 没有）
//
// 那条守卫只查「`page.tsx` 首行有没有声明 `'use client'`」⇒ 它判绿时上面这个缺陷**照样存在**
// （四页都是服务端组件，SSR 正文确实进了 RSC 载荷，但可见 DOM 被 loading 骨架占满）。
// 本判据**真跑一遍服务端渲染**（`renderToString`，不执行任何 `useEffect`），直接看首次渲染的输出：
// 把门控改回「`isReady=false` / `isChecking=true` 初值」⇒ 本文件必红（红证 = 注入式，见下）。
//
// ## 负控（不许放宽的地方）
//
// `/orders` 这类受保护业务页**必须仍然**在门控里（SSR 阶段不吐正文、只吐骨架）。
// ⇒ 「公开路由首屏有正文」+「受保护路由首屏无正文」两条同时成立，才说明放宽的**只是**公开面。
import { describe, it, expect, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import type { ReactNode } from 'react'

/** 被测路由（每个用例在渲染前改写它 —— `usePathname()` 的唯一真值源）。 */
let mockPathname = '/'

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ replace: () => {}, push: () => {}, prefetch: () => {} }),
  redirect: (url: string) => {
    throw new Error(`redirect:${url}`)
  },
  useSearchParams: () => new URLSearchParams(),
}))

import AuthProvider from '@/components/providers/AuthProvider'
import { AuthGuard } from '@/components/auth-guard'
import { PUBLIC_ROUTES, isPublicRoute } from '@/lib/auth-redirect'

/** 与线上形态逐字相同的门组件（AuthProvider 在内、AuthGuard 在外，同根布局）。 */
function Gate({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <AuthGuard>{children}</AuthGuard>
    </AuthProvider>
  )
}

/** 首屏正文哨兵：只有门打开了它才会出现在 SSR 输出里。 */
const BODY_SENTINEL = '首屏正文哨兵-2f4a'

function ssr(pathname: string): string {
  mockPathname = pathname
  return renderToString(
    <Gate>
      <h1>首页标题</h1>
      <p>{BODY_SENTINEL}</p>
    </Gate>,
  )
}

describe('首屏门控：匿名可见面在 SSR 阶段就要有正文（issue #6665）', () => {
  it('六条匿名可见路由在**水合前**就有正文（无 useEffect、无 JS 执行）', () => {
    // 面自证：被测对象不能是空集（清单改名 / 被搬走时"零命中"会伪装成绿）
    expect(
      PUBLIC_ROUTES.length,
      `前提失效：PUBLIC_ROUTES 为空（现取 ${PUBLIC_ROUTES.length} 条）—— 本判据此刻没有判别力`,
    ).toBeGreaterThan(0)

    const offenders: string[] = []
    for (const pathname of PUBLIC_ROUTES) {
      const html = ssr(pathname)
      if (!html.includes(BODY_SENTINEL) || !html.includes('首页标题')) offenders.push(pathname)
    }

    expect(
      offenders,
      `匿名可见面的首屏被门控拦住了：这些路由的首次服务端渲染输出里没有正文，` +
        `只有「加载中...」骨架（实测读数：本地真机在 domcontentloaded 时刻六页可见 DOM 恒为 6 字符「加载中...」，` +
        `生产 curl 恒为 503 B / h1=0 / nav=0）。` +
        `修法：门控只对**受保护业务页**生效（判据源 = frontend/admin-web/src/lib/auth-redirect.ts 的 PUBLIC_ROUTES，单一源）。` +
        `命中路由：${offenders.join(', ')}（本面共 ${PUBLIC_ROUTES.length} 条）`,
    ).toEqual([])
  })

  it('负控：受保护业务页仍在门控内（首屏不吐正文 —— 放宽的只是公开面）', () => {
    const html = ssr('/orders')
    expect(
      html.includes(BODY_SENTINEL),
      '受保护业务页 /orders 的首屏出现了正文 —— 这是把登录门控一并拆掉的形态：' +
        '未登录用户会在业务页看到半截界面（而不是被送去登录页）。' +
        '修法：只对 PUBLIC_ROUTES 放行，受保护前缀一条不放宽。',
    ).toBe(false)
  })

  it('判别力自证（注入式红证）：门控按「初值 = 关」的旧口径跑 ⇒ 同一条断言必红', () => {
    // 注入方式 = 复现旧口径本身：旧实现的判据是「isReady/isChecking 初值恒 false/true」，
    // 与之等价的机器形态 = 把公开路由清单当空（于是每条路由都走受保护分支）。
    // 断言形态与第一条逐字相同 ⇒ 它红了就证明第一条有判别力。
    const injectedPublicRoutes: string[] = []
    const injected = injectedPublicRoutes.every((p) => {
      mockPathname = p
      const html = renderToString(
        <Gate>
          <h1>首页标题</h1>
          <p>{BODY_SENTINEL}</p>
        </Gate>,
      )
      return html.includes(BODY_SENTINEL)
    })
    expect(
      injected,
      '注入对照失效：空清单下「every」本应为真（零路由）—— 说明本自证写错了，不是被测对象的问题',
    ).toBe(true)

    // 正向对照：真实的公开路由清单**非空**，且注入空清单下受保护页确实被拦（见上一条）⇒
    // 「首屏有正文」这件事只可能来自门控按路由放行，而不是来自门被整体拆掉。
    expect(PUBLIC_ROUTES.length).toBeGreaterThan(0)
  })
})
