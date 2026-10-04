import type { Metadata, Viewport } from 'next'
import CorporateNav from '@/components/corporate/CorporateNav'
import CorporateFooter from '@/components/corporate/CorporateFooter'

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#3a4e75',
}

export const metadata: Metadata = {
  title: {
    default: '米高 — 布艺行业的 AI 经营平台',
    template: '%s — 米高',
  },
  description:
    '杭州词元通达科技有限公司出品的米高平台：面向布艺 / 窗帘商家的多租户 AI 经营平台。顾客侧小布 7×24 接待咨询、算料报价、下单与售后；经营侧米宝打理商品、订单、生产、库存与财务。',
  keywords: [
    '米高',
    'AI 智能客服',
    '布艺 SaaS',
    '窗帘',
    '窗帘算料',
    '加工单',
    '计件工资',
    'AI 经营助手',
    '小布',
    '米宝',
  ],
  authors: [{ name: '杭州词元通达科技有限公司' }],
  openGraph: {
    type: 'website',
    locale: 'zh_CN',
    url: 'https://www.migaozn.com',
    siteName: '米高 MIGAO',
    title: '米高 — 布艺行业的 AI 经营平台',
    description:
      '两个 AI，把一间窗帘店从询价管到发货：小布接待顾客，米宝打理经营，四位终端共用同一套业务数据。',
    images: [
      {
        url: 'https://www.migaozn.com/og-image.png',
        width: 1200,
        height: 630,
        alt: '米高 AI 经营平台',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: '米高 — 布艺行业的 AI 经营平台',
    description:
      '两个 AI，把一间窗帘店从询价管到发货：小布接待顾客，米宝打理经营，四位终端共用同一套业务数据。',
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
