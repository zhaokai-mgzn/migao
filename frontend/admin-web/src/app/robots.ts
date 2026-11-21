import type { MetadataRoute } from 'next'
import { siteOrigin } from '@/lib/site-domain'

/**
 * `/robots.txt`（issue #6665 / #8941）。
 *
 * 为什么是 route 形式而不是 `public/robots.txt`：`public/` 是静态文件、构建期不做替换 ⇒
 * 同一份产物部署到生产域时，`Sitemap:` 仍指向测试域（抓取指引把爬虫带去另一个站）。
 * route 形式读**同一个**域名来源（`src/lib/site-domain.ts`）。
 *
 * `Disallow` 列表与改前**逐条一致**（顺序也一致）：受保护业务面不对爬虫开放。
 */
const DISALLOW = [
  '/dashboard',
  '/products',
  '/orders',
  '/customers',
  '/chat',
  '/finance',
  '/settings',
  '/login',
  '/register',
]

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: DISALLOW }],
    // 抓取指引（issue #6665：此前被 proxy 吞成 307 回首页，爬虫根本读不到本站的 sitemap）
    sitemap: `${siteOrigin()}/sitemap.xml`,
  }
}
