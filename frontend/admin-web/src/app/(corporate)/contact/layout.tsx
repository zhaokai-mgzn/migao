import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '联系我们',
  description:
    '联系米高团队，了解更多关于AI智能电商管理平台的信息。电话：400-888-8888，邮箱：contact@migao-ai.com。',
}

export default function ContactLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
