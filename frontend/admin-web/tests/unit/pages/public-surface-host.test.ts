// case_ids: UI-155
//
// 判据：**公开面的 host 必须是「不产生跳转」的那个 host**（issue #8968）。
//
// 病根（2026-11-21 生产实测 + 2026-11-26 复核，两个域都一样）：
//   `https://www.cytda.com/`   ⇒ 308 → `https://cytda.com/`
//   `https://www.migaozn.com/` ⇒ 308 → `https://migaozn.com/`
//   而 sitemap 的 5 条 `<loc>` / `robots.txt` 的 `Sitemap:` / canonical / `metadataBase`
//   全写 `https://www.<domain>` ⇒ 爬虫每条都要先吃一次 308，canonical 与真实落点不一致。
//
// 308 的产出点（**现取，不是猜**）：
//   · `frontend/admin-web/next.config.mjs` 的 `redirects()` 里那条
//     `has: [{ type: 'host', value: 'www.<域>' }]` + `permanent: true`；
//   · Next 把 `permanent` 映射成 `RedirectStatusCode.PermanentRedirect` = **308**
//     （现取 `frontend/admin-web/node_modules/next/dist/lib/redirect-status.js` 与
//       `next/dist/client/components/redirect-status-code.js`）；改前注释写的「301」与实现不符；
//   · 规则按 `NEXT_PUBLIC_SITE_DOMAIN` 参数化 ⇒ **对任意 `<domain>` 通用**（两个域实测都是 308）。
//   ⇒ 公开面只能是 apex（`siteOrigin()`），www 只留给跳转判定。
//
// 本文件钉四层，**一律与真值源函数的输出比，不比字面量**：
//   ① 跳转集合（从 `next.config.mjs` 现取）里**不得**含公开面 host，且跳转落点 == 公开面 host；
//   ② `sitemap()` 每条 `<loc>` 的 host == 公开面 host；
//   ③ `robots()` 的 `Sitemap:` 与 `siteOrigin()` 同源；
//   ④ `metadataBase` / canonical 与上面同源（缺省域 + 生产域两格）。
// 判别力自证在最后一条：判据内核拿 www 当公开面必须**出声违规**（否则本文件是空断言）。
import { describe, it, expect, vi, afterEach } from 'vitest'

import { siteDomain, siteOrigin, wwwHost } from '@/lib/site-domain'
import sitemap from '@/app/sitemap'
import robots from '@/app/robots'
import { metadata as corporateMetadata } from '@/app/(corporate)/layout'
import nextConfig from '../../../next.config.mjs'

/** `next.config.mjs` 的 redirects 规则形状（`.mjs` 无类型 ⇒ 显式声明期望形状，不靠推断）。 */
type RedirectRule = {
  source: string
  has?: Array<{ type: string; value: string }>
  destination: string
  permanent?: boolean
  statusCode?: number
}

async function redirectRules(): Promise<RedirectRule[]> {
  const config = nextConfig as unknown as { redirects: () => Promise<RedirectRule[]> }
  return config.redirects()
}

function hostOf(url: string): string {
  return new URL(url).host
}

/**
 * 公开面判据的**内核**（纯函数，便于判别力自证）：
 * 公开面 host 若同时是「会整站跳转的 host」⇒ 爬虫拿到的每条 `<loc>` / canonical 都是假落点。
 */
function publicSurfaceViolations(originHost: string, redirectHosts: string[]): string[] {
  return redirectHosts.includes(originHost)
    ? [
        `公开面 host ${originHost} 本身就会 308 跳走 —— ` +
          `sitemap / robots / canonical 的每条绝对地址都成了跳转前的假落点（issue #8968）`,
      ]
    : []
}

/** 两格口径：缺省域（不配 env）+ 生产域。公开面在两边都必须自洽。 */
const DOMAINS = ['', 'cytda.com'] as const

function stubDomain(domain: string) {
  vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', domain)
}

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('公开面 host = 不产生跳转的那个 host（issue #8968）', () => {
  it('www→apex 跳转规则真实存在；会整站跳转的 host 里不含公开面，且跳转落点 == 公开面 host', async () => {
    for (const domain of DOMAINS) {
      stubDomain(domain)
      const rules = await redirectRules()
      // 面自证：本判据的坐标是「跳转规则」—— 规则没了，判据就失去对象（不许静默通过）
      expect(
        rules.length,
        'next.config.mjs 里连 www→apex 的归一规则都没了 —— 本判据的坐标失效：' +
          '要么恢复跳转，要么同批改判公开面口径（不要静默通过）',
      ).toBeGreaterThan(0)

      const hostRules = rules.filter((rule) =>
        (rule.has ?? []).some((condition) => condition.type === 'host'),
      )
      const redirectHosts = hostRules.flatMap((rule) =>
        (rule.has ?? []).filter((c) => c.type === 'host').map((c) => c.value),
      )
      // 面自证：www 是这条规则真正匹配的 host（不是空集合平均主义）
      expect(redirectHosts).toContain(wwwHost())

      const originHost = hostOf(siteOrigin())
      // ① 公开面不许落在跳转集合里（这条就是本单的判据）
      expect(
        publicSurfaceViolations(originHost, redirectHosts),
        `域 = ${siteDomain()}：公开面 ${siteOrigin()} 与跳转规则冲突`,
      ).toEqual([])
      // ② 跳转落点必须就是公开面（口径收敛：跳到哪里，就声明哪里）
      for (const rule of hostRules) {
        expect(hostOf(rule.destination)).toBe(originHost)
        // `permanent: true` 在 Next 里是 308（不是 301）—— 用一个读数把状态码语义钉在这里
        expect(rule.permanent).toBe(true)
      }
      // ③ 反向：www 不再是公开面
      expect(originHost).not.toBe(wwwHost())
    }
  })

  it('sitemap() 每条 <loc> 的 host == 公开面 host（与 siteOrigin() 输出比，不比字面量）', () => {
    for (const domain of DOMAINS) {
      stubDomain(domain)
      const originHost = hostOf(siteOrigin())
      const locs = sitemap().map((entry) => entry.url)
      // 面自证：条目集合非空，且 **只有一个** host（多 host = sitemap 在自己承认两个落点）
      expect(new Set(locs.map(hostOf)).size, `域 = ${siteDomain()}：sitemap 出现了多个 host`).toBe(1)
      expect(locs.length).toBeGreaterThanOrEqual(5)
      const offOrigin = locs.filter((loc) => hostOf(loc) !== originHost)
      expect(
        offOrigin,
        `sitemap 的 <loc> 落在公开面 ${originHost} 之外（爬虫要么吃 308，要么被登记到另一个站）：${offOrigin.join(', ')}`,
      ).toEqual([])
    }
  })

  it('robots() 的 Sitemap: 与 siteOrigin() 同源', () => {
    for (const domain of DOMAINS) {
      stubDomain(domain)
      const declared = robots().sitemap
      expect(declared).toBe(`${siteOrigin()}/sitemap.xml`)
      expect(hostOf(declared as string)).toBe(hostOf(siteOrigin()))
    }
  })

  it('metadataBase / canonical 与 sitemap / robots 同源（缺省域；生产域用 resetModules 重新求值）', async () => {
    // 缺省域：模块导入期求值（import 时 env 未设）⇒ 直接比
    expect(hostOf(corporateMetadata.metadataBase?.toString() as string)).toBe(hostOf(siteOrigin()))
    expect(
      hostOf(new URL(corporateMetadata.alternates?.canonical as string, String(corporateMetadata.metadataBase)).toString()),
      'canonical 解析后的 host 必须与 metadataBase / sitemap 同一个（否则 canonical 指向会 308 的那一面）',
    ).toBe(hostOf(siteOrigin()))

    // 生产域：模块级常量 ⇒ resetModules 后重新求值
    stubDomain('cytda.com')
    vi.resetModules()
    const { metadata } = await import('@/app/(corporate)/layout')
    expect(hostOf(metadata.metadataBase?.toString() as string)).toBe(hostOf(siteOrigin()))
    expect(
      hostOf(new URL(metadata.alternates?.canonical as string, String(metadata.metadataBase)).toString()),
    ).toBe(hostOf(siteOrigin()))
  })

  it('判别力自证：拿 www 当公开面必须出声违规（否则上面的判据是空断言）', () => {
    const redirectHosts = ['www.migaozn.com']
    expect(publicSurfaceViolations('www.migaozn.com', redirectHosts)).toHaveLength(1)
    expect(publicSurfaceViolations('migaozn.com', redirectHosts)).toEqual([])
  })
})
