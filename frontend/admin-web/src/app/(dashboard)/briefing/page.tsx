'use client'

import { useEffect, useState } from 'react'
import { Newspaper } from 'lucide-react'
import { briefingApi } from '@/lib/api'
import BriefingCard from '@/components/dashboard/BriefingCard'

/**
 * 智能每日经营简报页（issue #3468）
 * 侧边栏「每日简报」入口（企业开关开启才显示菜单）。
 * 页面内复用 BriefingCard 组件；开关关闭时显示引导（菜单已隐藏，直达 URL 兜底）。
 */
export default function BriefingPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null)

  useEffect(() => {
    briefingApi.getConfig()
      .then((res) => setEnabled(!!res.data.data?.enabled))
      .catch(() => setEnabled(false))
  }, [])

  // 加载中（避免开关状态未就绪时闪空态）
  if (enabled === null) {
    return (
      <div className="p-5 sm:p-6">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-neutral-900">每日经营简报</h1>
          <p className="mt-0.5 text-xs text-neutral-400">加载中...</p>
        </div>
      </div>
    )
  }

  if (!enabled) {
    return (
      <div className="p-5 sm:p-6">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-neutral-900">每日经营简报</h1>
          <p className="mt-0.5 text-xs text-neutral-400">数据更新时间：—</p>
        </div>
        <div className="flex flex-col items-center justify-center rounded-xl border border-neutral-200 bg-white py-16 text-center shadow-card">
          <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-50 to-indigo-50">
            <Newspaper className="h-6 w-6 text-primary-400" />
          </div>
          <p className="text-sm font-medium text-neutral-600">智能每日经营简报未开启</p>
          <p className="mt-1 max-w-md text-xs text-neutral-400">
            请在「企业基础信息 → 基本设置」中开启「智能每日经营简报」企业开关。开启后系统将在每日生成时刻自动整理经营要点，本页面与侧边栏入口将同步显示。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-5 sm:p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-neutral-900">每日经营简报</h1>
        <p className="mt-0.5 text-xs text-neutral-400">AI 每日自动生成 · 数字经校验 · 数据安全隔离</p>
      </div>
      <BriefingCard enabled />
    </div>
  )
}
