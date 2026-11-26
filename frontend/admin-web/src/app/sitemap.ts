import type { MetadataRoute } from 'next'
import { siteOrigin } from '@/lib/site-domain'

/**
 * `/sitemap.xml`（issue #6665 / #8941）。
 *
 * 为什么是 route 形式而不是 `public/sitemap.xml`：`public/` 是**静态文件**，构建期不做任何替换
 * ⇒ 同一份产物部署到生产域（`cytda.com`）时，sitemap 里的 `<loc>` 全是测试域（SEO 把生产页
 * 登记成测试域）。route 形式读**同一个**域名来源（`src/lib/site-domain.ts`）。
 *
 * 面 = 官网（corporate）公开可收录页，锚点与改前逐条一致（5 条）：
 * `/`、`/about/`、`/services/`、`/contact/`、`/download/`。
 * 受保护业务面（`/dashboard`、`/orders` 等）一律不进本文件（对爬虫无意义，且要登录）。
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const origin = siteOrigin()
  return [
    { url: `${origin}/`, changeFrequency: 'weekly', priority: 1.0 },
    { url: `${origin}/about/`, changeFrequency: 'monthly', priority: 0.8 },
    { url: `${origin}/services/`, changeFrequency: 'monthly', priority: 0.9 },
    { url: `${origin}/contact/`, changeFrequency: 'monthly', priority: 0.8 },
    // 终端下载页（issue #8195）：公开面，商家会直接搜到它
    { url: `${origin}/download/`, changeFrequency: 'weekly', priority: 0.9 },
  ]
}
