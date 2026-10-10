// case_ids: UI-082
//
// 判据：**分享 / 抓取元数据只有一个真值源**（issue #6665）。
//
// 病根（实测，2026-10-10）：
//   · `frontend/admin-web/src/app/(corporate)/layout.tsx` 的 `og:image` 指向 `https://www.migaozn.com/og-image.png`，
//     而 `frontend/admin-web/public/` 里**没有该文件**（指向 404 的声明比不声明更差）；
//   · `og:url` 硬编码 `www.migaozn.com`，全仓 `metadataBase` 命中数为 0，且无 `alternates.canonical`
//     ⇒ `www.migaozn.com` 与 `migaozn.com` 两份内容都能 200（重复内容）；
//   · `robots.txt` / `sitemap.xml` 全被 `frontend/admin-web/src/proxy.ts` 的 matcher 吞成 307 → `/`。
//
// 本文件钉三件事：
//   ① 元数据真值源**只有一处**（`(corporate)/layout.tsx`），页面层不得再各写一遍；
//   ② 声明的 `og:image` 必须真存在，且尺寸与声明一致（1200×630，PNG 头逐字节读）；
//   ③ 站点级 `robots` / `canonical` / `metadataBase` 存在且取值同源。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, existsSync, statSync } from 'fs'
import { join, relative } from 'path'

import { metadata as corporateMetadata } from '@/app/(corporate)/layout'

/** 站点真值源（唯一：`(corporate)/layout.tsx`；本测试文件是它的判据，不是第二份真值）。 */
const SITE_ORIGIN = 'https://www.migaozn.com'

const APP_DIR = join(process.cwd(), 'src/app')
const CORPORATE_DIR = join(APP_DIR, '(corporate)')

/** 递归收集 `(corporate)` 下的 `page.tsx` / `layout.tsx`（加页面时自动进面）。 */
function corporateMetaFiles(dir: string = CORPORATE_DIR): string[] {
  const found: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) found.push(...corporateMetaFiles(full))
    else if (name === 'page.tsx' || name === 'layout.tsx') found.push(relative(process.cwd(), full))
  }
  return found.sort()
}

/** 逐字节读 PNG 头：返回 {width, height}（非 PNG 或读不出返回 null）。 */
function readPngSize(file: string): { width: number; height: number } | null {
  if (!existsSync(file)) return null
  const buf = readFileSync(file)
  const signature = '89504e470d0a1a0a'
  if (buf.length < 24 || buf.subarray(0, 8).toString('hex') !== signature) return null
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

describe('官网元数据单一真值源 + og/robots/canonical/sitemap（issue #6665）', () => {
  it('站点级 metadataBase / canonical / og:image 都在 (corporate)/layout.tsx 一处声明', () => {
    expect(
      corporateMetadata.metadataBase?.toString(),
      'metadataBase 缺失 ⇒ 相对资源（og:image 等）无法解析成绝对 URL，Next 会在构建期报错或产出相对路径',
    ).toBe(new URL(SITE_ORIGIN).toString())

    const canonical = corporateMetadata.alternates?.canonical
    expect(
      canonical,
      'canonical 缺失 ⇒ www 与裸域两份内容都被收录（重复内容）',
    ).toBe('/')

    const images = corporateMetadata.openGraph?.images
    expect(Array.isArray(images) ? images.length : 0, 'og:image 声明必须恰好一条').toBe(1)
    const image = (images as Array<{ url: string | URL }>)[0]
    expect(
      image.url.toString(),
      'og:image 必须说清是哪个文件（剖掉裸域/协议，本判据不重复真值源）',
    ).toBe('/og-image.png')
    expect(corporateMetadata.robots, '站点级 robots 声明缺失').toBeTruthy()
  })

  it('页面层不得各写一份 og/canonical/robots（信息不重复 = 单一真值源）', () => {
    const pages = corporateMetaFiles().filter((rel) => rel.endsWith('page.tsx'))
    // 面自证：至少四页在面内（否则本判据是空跑）
    expect(pages.length, `(corporate) 下的 page.tsx 只有 ${pages.length} 个 —— 判据坐标失效`).toBeGreaterThanOrEqual(4)

    const offenders: string[] = []
    for (const rel of pages) {
      const src = readFileSync(join(process.cwd(), rel), 'utf-8')
      if (/openGraph\s*:/.test(src) || /alternates\s*:/.test(src) || /metadataBase\s*:/.test(src)) {
        offenders.push(rel)
      }
    }
    expect(
      offenders,
      `这些页面自己又写了一份分享/抓取元数据（四页各写一遍必然漂移）：${offenders.join(', ')}。` +
        `修法：站点级真值只留在 frontend/admin-web/src/app/(corporate)/layout.tsx；页面只写自有的 title/description。`,
    ).toEqual([])
  })

  it('声明的 og:image 真存在，且尺寸与声明一致（1200×630）', () => {
    const image = (corporateMetadata.openGraph?.images as Array<{ width?: number; height?: number }>)[0]
    const file = join(process.cwd(), 'public', 'og-image.png')
    const size = readPngSize(file)
    expect(
      size,
      'public/og-image.png 不存在或不是合法 PNG ⇒ 微信 / 钉钉分享抓到 404，连图都不显示' +
        '（指向 404 的声明比不声明更差）。修法：补一张真 PNG 进 public/，或撤掉该声明。',
    ).not.toBeNull()
    expect(size).toEqual({ width: image.width, height: image.height })
  })

  it('robots.txt / sitemap.xml 真在 public/ 且内容指向唯一站点真值源', () => {
    const robots = readFileSync(join(process.cwd(), 'public', 'robots.txt'), 'utf-8')
    expect(robots).toContain(`Sitemap: ${SITE_ORIGIN}/sitemap.xml`)

    const sitemap = readFileSync(join(process.cwd(), 'public', 'sitemap.xml'), 'utf-8')
    // 站点真值源只在一处：sitemap 里的每条 loc 都必须用 SITE_ORIGIN 前缀
    const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1])
    expect(locs.length, 'sitemap 里一条 <loc> 都没有 —— 面为空，判据没有判别力').toBeGreaterThan(0)
    const offDomain = locs.filter((loc) => !loc.startsWith(`${SITE_ORIGIN}/`))
    expect(
      offDomain,
      `sitemap 里的 loc 不在站点真值源域名下（裸域/别的域会各生成一份内容）：${offDomain.join(', ')}`,
    ).toEqual([])
    // 官网四页必须都在（都是匿名可见面）
    for (const path of ['/', '/about/', '/services/', '/contact/']) {
      expect(locs, `sitemap 缺 ${path}`).toContain(`${SITE_ORIGIN}${path}`)
    }
  })

  it('判别力自证：尺寸读取器对真实 PNG 与伪造文件给出不同读数', () => {
    expect(readPngSize(join(process.cwd(), 'public', 'favicon.svg')), 'SVG 不该被当成 PNG 读出尺寸').toBeNull()
    expect(readPngSize(join(process.cwd(), 'public', '__不存在__.png'))).toBeNull()
  })
})
