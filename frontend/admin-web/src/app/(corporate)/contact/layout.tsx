import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '联系我们 — 产品演示、落地评估与合作咨询',
  description:
    '联系观星台团队：想看产品演示、评估 AI 客服落地成本或洽谈合作，在留言中说明你的行业、企业规模与当前卡点，我们在工作时间内回复。',
}

export default function ContactLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
