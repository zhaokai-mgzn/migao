import type { Metadata, Viewport } from 'next'
import CorporateNav from '@/components/corporate/CorporateNav'
import CorporateFooter from '@/components/corporate/CorporateFooter'

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#3a4e75',
}

export const metadata: Metadata = {
  // 站点级绝对地址的**唯一真值源**（issue #6665 第 4 条）：
  // 在此之前全仓 `metadataBase` 命中数为 0，而 `www.migaozn.com` 与裸域都能 200 ⇒ 两份内容。
  // 归一动作在 next.config.mjs 的 `redirects()`（www → 裸域 301）。
  metadataBase: new URL('https://www.migaozn.com'),
  title: {
    default: '观星台 — 布艺行业的 AI 经营平台',
    template: '%s — 观星台',
  },
  alternates: {
    canonical: '/',
  },
  description:
    '杭州词元通达科技有限公司出品的观星台平台：面向布艺 / 窗帘商家的多租户 AI 经营平台。顾客侧元元 7×24 小时接待咨询、算料报价、下单与售后；经营侧黄金策覆盖商品、订单、生产、库存与财务。',
  keywords: [
    '观星台',
    'AI 智能客服',
    '布艺 SaaS',
    '窗帘',
    '窗帘算料',
    '加工单',
    '计件工资',
    'AI 经营助手',
    '元元',
    '黄金策',
  ],
  authors: [{ name: '杭州词元通达科技有限公司' }],
  openGraph: {
    type: 'website',
    locale: 'zh_CN',
    siteName: '观星台 MIGAO',
    title: '观星台 — 布艺行业的 AI 经营平台',
    description:
      '布艺行业的 AI 客服与经营平台：元元承接顾客服务，黄金策承接生产管理，四个终端共用数据底座。',
    // 相对路径 ⇒ 由 metadataBase 解析；不再硬编码 www（那是第二个真值源）
    images: [
      {
        url: '/og-image.png',
        width: 1200,
        height: 630,
        alt: '观星台 AI 经营平台',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: '观星台 — 布艺行业的 AI 经营平台',
    description:
      '布艺行业的 AI 客服与经营平台：元元承接顾客服务，黄金策承接生产管理，四个终端共用数据底座。',
  },
  robots: {
    index: true,
    follow: true,
  },
}

export default function CorporateLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen flex-col bg-neutral-50">
      <CorporateNav />
      <main className="flex-1">{children}</main>
      <CorporateFooter />
    </div>
  )
}
