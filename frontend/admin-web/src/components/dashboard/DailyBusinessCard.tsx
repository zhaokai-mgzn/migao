'use client'

import { useState } from 'react'
import { Sparkles, ChevronDown, ChevronUp } from 'lucide-react'
import BriefingCard from '@/components/dashboard/BriefingCard'
import { type TodayOverviewBarProps, TodayOverviewSentence } from '@/components/dashboard/TodayOverviewBar'

/**
 * 「黄金策 · 今日经营」合并卡（issue #8114）。
 *
 * 病灶（用户 2026-10-29 截图圈出两块）：看板顶部**同时**有
 *   ①「今日经营速览」速览条（今日订单 / 销售额 / 66 款商品库存偏低）
 *   ②「每日经营简报」卡（昨日回顾 … 66 个商品库存偏低 …）
 * 两块各占一张卡、各带 AI 标记，**重复说了同一件事**（违反 `migao-dev-flow` §31 P2「信息不重复」）。
 *
 * 改后**一张卡**（位置 = 原速览条的位置，仍在「待处理」之前）：
 *   - 收起态（默认）= 速览那一句话（`TodayOverviewSentence`，文案口径不变）；
 *   - 展开态       = 那句话 + 简报完整内容（昨日回顾 / 今日必办 / 风险预警 / 优化建议 / 主动检查）。
 * 四种状态都在**展开态**覆盖（收起态永远只有速览那一句，**不等简报**）：
 *   ① 简报开启 + 有数据 ⇒ 展开出完整简报；
 *   ② 简报开启 + 未生成 ⇒ 「今日简报尚未生成」+ 生成入口（沿用 `briefing-collapsed-hint`）；
 *   ③ 简报**未开启**      ⇒ 卡片**仍在**（速览不依赖简报开关！）展开说「每日经营简报未开启」+ 去开启入口；
 *   ④ 简报加载中          ⇒ 展开出简报骨架（收起态先显示速览）。
 *
 * 数据源不变：速览用页面派生值，简报仍走 briefing API（本卡只做**展示层**合并）。
 */
export interface DailyBusinessCardProps extends TodayOverviewBarProps {
  /** 企业简报开关；`null` = 开关还没回来 ⇒ 展开态按「加载中」处理（不先说「未开启」） */
  briefingEnabled: boolean | null
}

export default function DailyBusinessCard({ briefingEnabled, ...overview }: DailyBusinessCardProps) {
  /**
   * 默认收起（issue #8114）：看板第一职责是「今天该处理什么」，
   * 常驻面 = 速览那一句话（§31 P1 常驻面克制）。不持久化 —— 刷新回默认收起。
   */
  const [expanded, setExpanded] = useState(false)

  return (
    <section
      data-testid="daily-business-card"
      className="relative mb-6 overflow-hidden rounded-xl border border-primary-200/70 bg-white shadow-card"
    >
      {/* 顶部品牌渐变细条 */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary-500 via-accent-500 to-primary-500" />

      <div className="flex flex-wrap items-center gap-2 px-5 pt-4">
        <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-primary-600 to-primary-500 px-2.5 py-1 text-xs font-semibold text-white shadow-sm">
          <Sparkles className="h-3 w-3" />
          黄金策 · 今日经营
        </span>
        <span className="text-xs text-neutral-400">AI 生成内容仅供参考</span>
        {/* 展开 / 收起：可聚焦按钮 + `aria-expanded`（键盘可达） */}
        <button
          type="button"
          data-testid="briefing-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-50 hover:text-primary-700"
        >
          {expanded ? '收起' : '展开'}
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* 常驻面 = 速览那一句话（**不依赖简报开关 / 不等简报请求**） */}
      <div className="px-5 pb-4 pt-2.5">
        <TodayOverviewSentence {...overview} />
      </div>

      {/* 展开态 = 简报内容（四态由 BriefingCard 承载；卡片外壳/头部归本卡所有） */}
      {expanded && (
        <div data-testid="daily-business-card-briefing" className="border-t border-neutral-100 px-5 py-4">
          <BriefingCard enabled={briefingEnabled} embedded />
        </div>
      )}
    </section>
  )
}
