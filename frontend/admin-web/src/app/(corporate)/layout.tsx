import type { Metadata, Viewport } from 'next'
import CorporateNav from '@/components/corporate/CorporateNav'
import CorporateFooter from '@/components/corporate/CorporateFooter'

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#2563eb',
}

export const metadata: Metadata = {
  title: {
    default: '米高 — AI驱动的新一代企业智能管理平台',
    template: '%s — 米高',
  },
  description:
    '米高SaaS平台为布艺行业提供米宝智能工作助手与小布AI客服，双AI助手驱动商品管理、订单跟踪、客户服务全链路智能化，助力企业降本增效。',
  keywords: ['米高', 'AI智能客服', 'SaaS', '布艺', '窗帘', '电商管理', 'AI助手', '米宝', '小布'],
  authors: [{ name: '词元通达' }],
  openGraph: {
    type: 'website',
    locale: 'zh_CN',
    url: 'https://www.migaozn.com',
    siteName: '米高 MIGAO',
    title: '米高 — AI驱动的新一代企业智能管理平台',
    description:
      '为布艺行业配备专属AI助手——米宝智能工作助手与小布智能客服，从内部运营到客户服务全方位驱动业务增长。',
    images: [
      {
        url: 'https://www.migaozn.com/og-image.png',
        width: 1200,
        height: 630,
        alt: '米高 AI 智能管理平台',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: '米高 — AI驱动的新一代企业智能管理平台',
    description:
      '为布艺行业配备专属AI助手——米宝智能工作助手与小布智能客服，从内部运营到客户服务全方位驱动业务增长。',
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
    <div className="min-h-screen flex flex-col bg-white">
      <CorporateNav />
      <main className="flex-1">{children}</main>
      <CorporateFooter />
    </div>
  )
}
