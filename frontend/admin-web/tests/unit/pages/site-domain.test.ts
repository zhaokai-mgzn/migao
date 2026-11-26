// case_ids: UI-082
//
// 判据：**站点域名只有一个构建期来源**（issue #8941 / 生产验收 P0-3、P1-1）。
//
// 病根：同一份 admin-web 产物被部署到测试域 `migaozn.com` 与生产域 `cytda.com`，而 5 处把
// `migaozn.com` 写死 ⇒ 生产环境 ① 官网「商家登录」把用户送去测试域 ② canonical / og:image /
// sitemap 把生产页登记成测试域 ③ `merchant.cytda.com/` 不跳登录页、`cytda.com/dashboard`
// 不跳商家域（`src/proxy.ts` 的 host 分支不认识该域名，未知域直接 `next()`）。
//
// 本文件钉三层：
//   ① **缺省值**（不设 env）⇒ 全部派生值与改前**逐字相同**（测试环境在跑，不许有行为变化）；
//   ② **显式 `NEXT_PUBLIC_SITE_DOMAIN=cytda.com`** ⇒ 五个落点（含 `next.config.mjs` / proxy）全部跟着走；
//   ③ **类级元守卫**：`src/**` 与 `next.config.mjs` 里不许再出现新的硬编码域名（只许留在唯一来源）。
import { describe, it, expect, vi, afterEach } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'
import { NextRequest } from 'next/server'

import { DEFAULT_SITE_DOMAIN } from '@/lib/site-domain'
import { metadata as corporateMetadata } from '@/app/(corporate)/layout'
import sitemap from '@/app/sitemap'
import robots from '@/app/robots'
import { proxy } from '@/proxy'
import nextConfig from '../../../next.config.mjs'

/** 走一遍 proxy（显式带 Host 头；jsdom 的 URL 是 localhost，不设 host 会命中本地开发分支）。 */
function callProxy(pathname: string, host: string) {
  const res = proxy(new NextRequest(new URL(pathname, `https://${host}`), { headers: { host } }))
  return {
    status: res.status,
    location: res.headers.get('location'),
    rewrite: res.headers.get('x-middleware-rewrite'),
  }
}

/** `next.config.mjs` 的 redirects 规则形状（`.mjs` 无类型 ⇒ 显式声明期望形状，不靠推断）。 */
type RedirectRule = {
  source: string
  has: Array<{ type: string; value: string }>
  destination: string
  permanent: boolean
}

/** 沙箱里 `next.config.mjs` 的 redirects 规则（`redirects()` 内部读 env ⇒ 可逐格给值）。 */
async function redirectRules(): Promise<RedirectRule[]> {
  const config = nextConfig as { redirects: () => Promise<RedirectRule[]> }
  return config.redirects()
}

afterEach(() => {
  vi.unstubAllEnvs()
})

/**
 * 改前的站点 origin（逐字锚点：缺省值下产物必须与它一模一样）。
 * 派生值本身（apex / www / merchant / 登录地址 / 归一化）在 `tests/unit/lib/site-domain.test.ts`；
 * 本文件钉的是**落点**：next.config 301 / proxy 分流 / metadataBase / sitemap / robots。
 */
const PRE_CHANGE_ORIGIN = 'https://www.migaozn.com'

describe('缺省值（不配置 NEXT_PUBLIC_SITE_DOMAIN）⇒ 与改前逐字相同', () => {
  it('sitemap / robots 的落点仍是 www.migaozn.com', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '')
    expect(sitemap().map((entry) => entry.url)).toEqual([
      `${PRE_CHANGE_ORIGIN}/`,
      `${PRE_CHANGE_ORIGIN}/about/`,
      `${PRE_CHANGE_ORIGIN}/services/`,
      `${PRE_CHANGE_ORIGIN}/contact/`,
      `${PRE_CHANGE_ORIGIN}/download/`,
    ])
    expect(robots().sitemap).toBe(`${PRE_CHANGE_ORIGIN}/sitemap.xml`)
  })

  it('(corporate) metadataBase 仍是 www.migaozn.com（导入期求值 ⇒ 默认 env）', () => {
    expect(corporateMetadata.metadataBase?.toString()).toBe(`${PRE_CHANGE_ORIGIN}/`)
  })

  it('next.config.mjs 的 www→裸域 301 仍指向 migaozn.com（且默认字面量与 TS 侧同源）', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '')
    const [rule] = await redirectRules()
    expect(rule.source).toBe('/:path*')
    expect(rule.has).toEqual([{ type: 'host', value: `www.${DEFAULT_SITE_DOMAIN}` }])
    expect(rule.destination).toBe(`https://${DEFAULT_SITE_DOMAIN}/:path*`)
    expect(rule.permanent).toBe(true)
  })

  it('proxy 的既有分流契约一条不放宽（负控）', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '')
    // ① 商家域根 → 307 /login；② 裸域业务路径 → 307 商家域；③ 未知路径 → 404 形态（rewrite）
    expect(callProxy('/', 'merchant.migaozn.com').location).toBe('https://merchant.migaozn.com/login')
    expect(callProxy('/dashboard', 'migaozn.com').location).toBe(
      'https://merchant.migaozn.com/dashboard',
    )
    expect(callProxy('/this-path-does-not-exist-9f2c', 'migaozn.com').rewrite).toBe(
      'https://migaozn.com/__proxy-unknown-path',
    )
    // ④ 未知域仍**放行**（既有安全语义：本地开发 / 预览环境不被拦截）—— 不是「拒绝」
    const unknown = callProxy('/dashboard', 'preview.migao.internal')
    expect(unknown.status).toBe(200)
    expect(unknown.location).toBeNull()
  })
})

describe('NEXT_PUBLIC_SITE_DOMAIN=cytda.com ⇒ 生产域五个落点全部跟着走（issue #8941）', () => {
  it('sitemap / robots 的绝对地址落在 cytda.com', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    expect(sitemap().map((entry) => entry.url)).toEqual([
      'https://www.cytda.com/',
      'https://www.cytda.com/about/',
      'https://www.cytda.com/services/',
      'https://www.cytda.com/contact/',
      'https://www.cytda.com/download/',
    ])
    expect(robots().sitemap).toBe('https://www.cytda.com/sitemap.xml')
  })

  it('(corporate) metadataBase 落在 cytda.com（模块级常量 ⇒ resetModules 后重新求值）', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    vi.resetModules()
    const { metadata } = await import('@/app/(corporate)/layout')
    expect(metadata.metadataBase?.toString()).toBe('https://www.cytda.com/')
  })

  it('next.config.mjs 的 www→裸域 301 跟着域名走', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    const [rule] = await redirectRules()
    expect(rule.has).toEqual([{ type: 'host', value: 'www.cytda.com' }])
    expect(rule.destination).toBe('https://cytda.com/:path*')
  })

  it('proxy：生产三面分流（P0-3 / P1-1b 的机器形态）', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    // ① merchant.cytda.com/ ⇒ 307 /login（改前不跳，直接返回官网首页）
    const merchantRoot = callProxy('/', 'merchant.cytda.com')
    expect(merchantRoot.status).toBe(307)
    expect(new URL(merchantRoot.location as string).pathname).toBe('/login')
    // ② cytda.com/dashboard ⇒ 307 merchant.cytda.com（改前不跳，返回后台壳）
    const dashboard = callProxy('/dashboard', 'cytda.com')
    expect(dashboard.status).toBe(307)
    expect(dashboard.location).toBe('https://merchant.cytda.com/dashboard')
    // ③ www.cytda.com 与裸域一致：官网首页放行、未知路径仍是 404 形态
    expect(callProxy('/', 'www.cytda.com').status).toBe(200)
    expect(callProxy('/this-path-does-not-exist-9f2c', 'cytda.com').rewrite).toBe(
      'https://cytda.com/__proxy-unknown-path',
    )
  })

  it('判别力自证：域名是**唯一**来源 —— 切到 cytda 后 migaozn 变成未知域（不会两边都认）', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    const legacy = callProxy('/dashboard', 'migaozn.com')
    expect(legacy.status).toBe(200)
    expect(legacy.location).toBeNull()
  })

})

describe('抓取指引只剩 route 形式（public/ 下的静态副本已删除）', () => {
  it('public/robots.txt 与 public/sitemap.xml 都不存在', () => {
    // 静态文件在构建期不做替换 ⇒ 留着它就会把测试域 baked 进生产产物（且 route 形式会被盖住）
    expect(existsSync(join(process.cwd(), 'public', 'robots.txt'))).toBe(false)
    expect(existsSync(join(process.cwd(), 'public', 'sitemap.xml'))).toBe(false)
  })
})

// ── 类级元守卫（铁律 8）：新增硬编码域名进不来 ────────────────────────────────
//
// 扫描面 = `src/**/*.{ts,tsx}` + `next.config.mjs`；只认**引号里的**出现 ——
// 反引号里的说明文字（`` `www.migaozn.com` ``）是文档，不算硬编码。
const HOST_LITERAL_RE = /(['"])[^'"\n]*migaozn\.com[^'"\n]*\1/

/** 唯二合法落点：① TS 侧缺省值；② `.mjs` 侧缺省值（无法 import TS ⇒ 由本文件的判据钉同源）。 */
const DOMAIN_LITERAL_ALLOWED = new Set(['src/lib/site-domain.ts', 'next.config.mjs'])

function sourceFiles(dir: string = join(process.cwd(), 'src')): string[] {
  const found: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) found.push(...sourceFiles(full))
    else if (/\.(ts|tsx)$/.test(name)) found.push(relative(process.cwd(), full))
  }
  return found
}

describe('类级元守卫：站点域名只许出现在唯一来源（issue #8941）', () => {
  it('src/** 与 next.config.mjs 里没有新增的硬编码站点域名', () => {
    const files = [...sourceFiles(), 'next.config.mjs']
    // 面自证：扫描面不能是空的（否则本守卫是空断言）
    expect(files.length, `扫描面只有 ${files.length} 个源文件 —— 判据坐标失效`).toBeGreaterThan(30)

    const offenders = files.filter((rel) => {
      if (DOMAIN_LITERAL_ALLOWED.has(rel)) return false
      return HOST_LITERAL_RE.test(readFileSync(join(process.cwd(), rel), 'utf-8'))
    })
    expect(
      offenders,
      `这些文件又写死了站点域名（改成从 src/lib/site-domain.ts 派生：siteDomain / wwwHost / merchantHost / siteOrigin / merchantLoginUrl）：${offenders.join(', ')}`,
    ).toEqual([])
  })

  it('判别力自证：守卫认得真硬编码，也不把说明文字当命中', () => {
    expect(HOST_LITERAL_RE.test('const u = "https://merchant.migaozn.com/login"')).toBe(true)
    expect(HOST_LITERAL_RE.test("const host = 'www.migaozn.com'")).toBe(true)
    // 反引号说明文字 / 裸注释不算（本仓注释里大量引用域名做解释）
    expect(HOST_LITERAL_RE.test('// 写死 www.migaozn.com 会把用户送去测试域')).toBe(false)
  })
})
