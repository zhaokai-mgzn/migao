import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '联系我们 — 产品演示、落地评估与合作咨询',
  description:
    '联系观星台团队：想看产品演示、评估 AI 客服落地成本或洽谈合作，说明您的行业、企业规模与当前卡点，我们按您的情况回复。',
}

export default function ContactLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
