// case_ids: UI-082
//
// 实例判据：**匿名可见面整页在 SSR 阶段就要有正文与 `h1`**（issue #6665）。
//
// 形态类判据在 `anonymous-first-screen-gate.ssr.test.tsx`（直接测两个门组件）；
// 本文件把**真实根布局**（`frontend/admin-web/src/app/layout.tsx`）与**真实页面模块**拼起来跑一遍，
// 断言「首屏 HTML 里有 h1 / 有正文 / 没有『加载中...』骨架」——
// 这正是用户与爬虫、无 JS 环境真正拿到的那一份输出。
//
// 生产读数（2026-10-10 现取）：`curl https://migaozn.com/{,about,services,contact}`
// ⇒ 可见 DOM 恒 503 B、`h1/h2/nav` 各 0、正文只有「加载中...」。
import { describe, it, expect, vi } from 'vitest'
import { renderToString } from 'react-dom/server'
import { existsSync, readFileSync } from 'fs'
import { join } from 'path'
import type { ComponentType, ReactNode } from 'react'

let mockPathname = '/'

vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ replace: () => {}, push: () => {}, prefetch: () => {} }),
  redirect: (url: string) => {
    throw new Error(`redirect:${url}`)
  },
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

// 根布局里的 Toaster 在 SSR 判据里不参与断言（它渲染的是容器，不产生首屏正文）
vi.mock('sonner', () => ({
  Toaster: () => <div data-testid="toaster-stub" />,
  toast: { success: () => {}, error: () => {}, info: () => {} },
}))

import RootLayout from '@/app/layout'
import HomePage from '@/app/(corporate)/page'
import AboutPage from '@/app/(corporate)/about/page'
import ServicesPage from '@/app/(corporate)/services/page'
import ContactPage from '@/app/(corporate)/contact/page'
import LoginPage from '@/app/login/page'
import RegisterPage from '@/app/register/page'

/** 骨架字面量（`frontend/admin-web/src/components/providers/AuthProvider.tsx` 的加载态）。 */
const SHELL_LITERAL = '加载中...'

/** 匿名可见面 = 官网四页 + 登录 / 注册（实测六页首屏可见 DOM 均为 6 字符）。 */
const ANONYMOUS_SURFACE: Array<{ pathname: string; Page: ComponentType }> = [
  { pathname: '/', Page: HomePage },
  { pathname: '/about', Page: AboutPage },
  { pathname: '/services', Page: ServicesPage },
  { pathname: '/contact', Page: ContactPage },
  { pathname: '/login', Page: LoginPage },
  { pathname: '/register', Page: RegisterPage },
]

/** 跑一遍真实根布局 + 真实页面（不执行任何 `useEffect` ⇒ 等价于"无 JS / 水合前"）。 */
function firstScreen(pathname: string, Page: ComponentType): string {
  mockPathname = pathname
  return renderToString(
    <RootLayout>
      <Page />
    </RootLayout>,
  )
}

describe('匿名可见面首屏：真实根布局 + 真实页面 ⇒ 必须有 h1 与正文（issue #6665）', () => {
  it('面自证：六条匿名可见路由都在面内（校举不能是空集，也不能只覆盖官网四页）', () => {
    expect(ANONYMOUS_SURFACE.map((r) => r.pathname)).toEqual([
      '/',
      '/about',
      '/services',
      '/contact',
      '/login',
      '/register',
    ])
  })

  it('每条匿名可见路由的首屏 HTML 里都有 h1（爬虫 / 无 JS / 慢网第一眼看到的就是它）', () => {
    const missing: string[] = []
    for (const { pathname, Page } of ANONYMOUS_SURFACE) {
      const html = firstScreen(pathname, Page)
      if (!/<h1[\s>]/.test(html)) missing.push(pathname)
    }
    expect(
      missing,
      `这些路由的首屏 HTML 里没有 h1：${missing.join(', ')}。` +
        `生产实测（2026-10-10 现取）：官网四页 curl 回来 \`h1=0 | h2=0 | nav=0\`、可见 DOM 恒 503 B，` +
        `只有一个居中转圈「${SHELL_LITERAL}」—— 而正文全在 RSC 载荷里，第一眼看不到。` +
        `本判据不执行 useEffect ⇒ 门控若依赖水合后才放行，这里必红。`,
    ).toEqual([])
  })

  it('每条匿名可见路由的首屏 HTML 里都**没有**「加载中...」骨架（骨架不再是首屏形态）', () => {
    const shelled: string[] = []
    for (const { pathname, Page } of ANONYMOUS_SURFACE) {
      const html = firstScreen(pathname, Page)
      if (html.includes(SHELL_LITERAL)) shelled.push(pathname)
    }
    expect(
      shelled,
      `这些路由的首屏 HTML 里仍出现「${SHELL_LITERAL}」骨架：${shelled.join(', ')}。` +
        `门控必须对公开路由不渲染骨架（判据源 = frontend/admin-web/src/lib/auth-redirect.ts 的 PUBLIC_ROUTES 单一源）。`,
    ).toEqual([])
  })

  it('正文确实进了首屏（以 /contact 为例逐字锚定：H1 标题 + 页头导语）', () => {
    const html = firstScreen('/contact', ContactPage)
    expect(html).toContain('联系我们')
    expect(html).toContain('常见问题解答')
  })

  it('负控：受保护业务页的首屏仍不得吐业务正文（登录门控一条不放宽）', () => {
    mockPathname = '/orders'
    const html = renderToString(
      <RootLayout>
        <div data-probe="protected-body">未登录不该看到的业务正文</div>
      </RootLayout>,
    )
    expect(html.includes('未登录不该看到的业务正文')).toBe(false)
  })

  it('判别力自证（注入式红证）：把公开路由当成受保护路由 ⇒ 首屏 h1 断言必红', () => {
    // 注入 = 复现旧门控的判据形态（所有路由都走受保护分支）：
    // 用受保护路径渲染同一个页面组件，断言形态与第 2 条一致 ⇒ 它红了就证明第 2 条有判别力。
    const injected = firstScreen('/orders', ContactPage)
    expect(
      /<h1[\s>]/.test(injected),
      '注入对照失效：受保护路径下本该被门控拦住（h1 不出现），却出现了 —— 说明本自证写错了',
    ).toBe(false)
  })

  it('（有 next build 产物时）六条路由的**静态预渲染 HTML** 里就有 h1 与正文、且没有「加载中...」', () => {
    // 这是 `next build` 那一层的判据：`renderToString` 证明不了「静态预渲染是否成功」——
    // 实测（issue #6665）：门控放行公开面后 `next build` 直接失败在
    // `Error occurred prerendering page "/login"`（`/login` 用了 useSearchParams），
    // 而 vitest / tsc **都看不见**这一层。
    // 口径：无 `.next/server/app/**` 产物时跳过（本地默认 `npm test` 不该逼一次全量构建；
    // CI 的 admin-web 腿按 `next build` → `vitest` 的顺序 ⇒ 这条在那里是真跑的）。
    const artifacts = ANONYMOUS_SURFACE.map(({ pathname }) => ({
      pathname,
      file: join(
        process.cwd(),
        '.next/server/app',
        pathname === '/' ? 'index.html' : `${pathname.slice(1)}.html`,
      ),
    }))
    if (!artifacts.some((a) => existsSync(a.file))) {
      console.log('[skip] 无 next build 产物（先跑一次 npx next build 再看这条）')
      return
    }

    const bad: string[] = []
    for (const { pathname, file } of artifacts) {
      if (!existsSync(file)) {
        bad.push(`${pathname}（缺产物 ${file}）`)
        continue
      }
      const html = readFileSync(file, 'utf-8')
      const hasH1 = /<h1[\s>]/.test(html)
      if (!hasH1 || html.includes(SHELL_LITERAL)) {
        bad.push(`${pathname}（h1=${hasH1}，骨架=${html.includes(SHELL_LITERAL)}）`)
      }
    }
    expect(
      bad,
      `这些路由的静态预渲染产物不达标：${bad.join('；')}。` +
        `修法：客户端页面不得用 useSearchParams（会触发 Next 的 missing-suspense-with-csr-bailout ` +
        `⇒ 预渲染失败或首屏只剩 fallback）。`,
    ).toEqual([])
  })

  it('登录页不得用 useSearchParams（它会让 /login 的静态预渲染失败 ⇒ 首屏又变空壳）', () => {
    // 红证（实测）：把 `useSearchParams()` 放回登录页 ⇒ `next build` 在静态预渲染阶段直接失败，
    //   `Error occurred prerendering page "/login" ... Export encountered an error on /login/page`
    //   （Next 的 missing-suspense-with-csr-bailout），而包进 `<Suspense>` 后首屏 HTML 只剩 fallback
    //   ⇒ 与本文件第 2 条「首屏要有 h1」直接冲突。所以口径是：**只在提交处理器里读地址栏**。
    const raw = readFileSync(join(process.cwd(), 'src/app/login/page.tsx'), 'utf-8')
    // 只看**代码行**：说明性文字里提这个符号名不算「用上了」（同 git 引用纪律：注解不是指令）
    const code = raw
      .split(/\r?\n/)
      .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
      .join('\n')
    expect(
      code.includes('useSearchParams'),
      '登录页又用上了 useSearchParams ⇒ `next build` 会在 /login 的静态预渲染阶段失败（首屏退回空壳）。' +
        '改用 src/app/login/page.tsx 的 callbackUrlFromLocation()（读 window.location.search）。',
    ).toBe(false)
    // 正向锚：落点仍然可配（不是把 callbackUrl 一起删掉）
    expect(code).toContain(`new URLSearchParams(window.location.search).get('callbackUrl')`)
  })
})
