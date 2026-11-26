'use client'

import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { WechatKfOnboarding } from '@/components/settings/WechatKfOnboarding'

/** 微信客服接入（issue #9230）：设置子页，无独立侧边栏节点。 */
export default function WechatKfSettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <Link href="/settings" className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
          <ArrowLeft className="h-4 w-4" />返回企业设置
        </Link>
        <h1 className="mt-3 text-xl font-semibold text-neutral-900">微信客服接入</h1>
        <p className="mt-1 text-sm text-neutral-500">
          把企业微信的客服账号接到生意管家，顾客在微信里发消息即可由米宝接待；接入后可在「在线接待」工作台查看会话。
        </p>
      </div>
      <WechatKfOnboarding />
    </div>
  )
}
