// case_ids: UI-082
//
// 判据：**会话门控必须按「路由是否公开」在首屏就分流**（issue #6665）。
//
// 为什么单独成文件：QA Growth Gate 要求 `src/components/providers/AuthProvider.tsx` 有配对的实例判据
// （形态判据在 `tests/unit/pages/anonymous-first-screen-gate.ssr.test.tsx`，本文件是本组件的**实例**判据）。
//
// 机制：`isReady` 的初值由 `isPublicRoute(pathname)` 算出（此前恒为 false、只在 useEffect 里置真 ⇒ SSR 必然骨架）。
import { describe, it, expect, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import type { ReactNode } from 'react'

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

const MARKER = '子页面正文-8c1d'

function ssr(pathname: string): string {
  mockPathname = pathname
  return renderToString(
    <AuthProvider>
      <p>{MARKER}</p>
    </AuthProvider>,
  )
}

describe('AuthProvider：公开路由首屏不渲染「加载中...」骨架（issue #6665）', () => {
  it('公开路由：首次服务端渲染（不执行 useEffect）直接吐 children', () => {
    for (const pathname of ['/', '/login', '/register', '/about', '/services', '/contact']) {
      const html = ssr(pathname)
      expect(html.includes(MARKER), `${pathname} 的首屏没有子页面正文（被骨架顶掉了）`).toBe(true)
      expect(html.includes('加载中...'), `${pathname} 的首屏仍是骨架`).toBe(false)
    }
  })

  it('受保护路由：首屏仍是骨架（会话恢复前不吐业务正文 —— 这条是负控，不许放宽）', () => {
    const html = ssr('/orders')
    expect(html.includes(MARKER)).toBe(false)
    expect(html.includes('加载中...')).toBe(true)
  })

  it('子路径判定与单一真值源一致：/login 的公开性来自 PUBLIC_ROUTES，不是本组件自己另立清单', () => {
    // 反向对照：把路径换成「像公开路由但不是」的形态（/loginfoo）⇒ 仍走受保护分支
    expect(ssr('/loginfoo').includes(MARKER)).toBe(false)
    // 正向：带尾斜杠的公开路由仍是公开（isPublicRoute 容错）
    expect(ssr('/about/').includes(MARKER)).toBe(true)
  })
})
