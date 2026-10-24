'use client'

import { AlertTriangle, Info, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProactiveRuleState, ProactiveStatus } from '@/types'

/**
 * 「主动检查」面板（issue #5955 建，issue #7195 收敛）
 *
 * 治的是「今天为什么没有提示」：已检查无命中 / 这次没有数据 / 你还没开启 / 本次不完整。
 *
 * 口径边界（判据钉住，勿改）：
 * · 🔴 **商家面只读 `display`**（引擎给的一句大白话）；`reason` / `caveats` 是诊断面
 *   （文件路径、issue 号、列名、「装配层」这类内部术语）—— **不许上屏**（`migao-dev-flow` §31 P3/P4）。
 * · 🔴 **常驻面克制**（§31 P1）：只列「本次没有结果」的规则，每条至多一行；全部已检查时整块只剩一行。
 *   （#7195 之前这里把六条规则的 `reason` + `caveats` 全量展开 ⇒ 一屏工程原文。）
 * · 不重复（§31 P2）：已检查的规则不再逐条念「已检查、无命中」，只进汇总。
 * · 状态为 null / 缺失 ⇒ 整个面板**不渲染**（未采集 ≠ 没问题，也不许用空壳冒充「已检查」）。
 */
export interface ProactiveStatusPanelProps {
  /** 逐规则四态（后端原样透传；null/undefined = 未采集 ⇒ 不渲染） */
  status?: ProactiveStatus | null
  /** 保留签名（日报页 / 看板共用同一份紧凑形态；#7195 起不再按形态分叉文案） */
  variant?: 'page' | 'dashboard'
}

/** 四态 → 商家可读的短标签（`not_enabled` 与「没有数据」必须分开说） */
const STATE_TEXT: Record<ProactiveRuleState, string> = {
  wired: '已检查',
  not_wired: '本次没有检查',
  not_enabled: '还没开启',
  incomplete: '数据不完整',
}

const STATE_STYLE: Record<ProactiveRuleState, string> = {
  wired: 'bg-neutral-100 text-neutral-500',
  not_wired: 'bg-amber-50 text-amber-700',
  not_enabled: 'bg-primary-50 text-primary-600',
  incomplete: 'bg-amber-50 text-amber-700',
}

function StateIcon({ state }: { state: ProactiveRuleState }) {
  const cls = 'h-3.5 w-3.5 flex-shrink-0'
  // `not_enabled` = 系统有、该租户没开（**可行动**）⇒ 用「提示」而不是「错误」
  if (state === 'not_enabled') return <Info className={cn(cls, 'text-primary-500')} />
  if (state === 'not_wired') return <XCircle className={cn(cls, 'text-amber-500')} />
  return <AlertTriangle className={cn(cls, 'text-amber-500')} />
}

export default function ProactiveStatusPanel({ status }: ProactiveStatusPanelProps) {
  // 未采集（null/缺失）或空表 ⇒ 不渲染：空壳会被读成「已检查、没有问题」
  const rows = status ? Object.values(status) : []
  if (!rows.length) return null

  const notChecked = rows.filter((r) => r.status !== 'wired')
  // 不制造告警噪音：全都已检查时不置警示色
  const tone = notChecked.length
    ? 'border-amber-200 bg-amber-50/40'
    : 'border-neutral-200 bg-neutral-50/40'

  return (
    <div className={cn('rounded-lg border px-4 py-3', tone)}>
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-neutral-600">主动检查</h3>
        <span className="text-[11px] text-neutral-400">
          {notChecked.length
            ? `${notChecked.length} 项本次没有结果（不代表没问题）`
            : '全部已检查，无命中'}
        </span>
      </div>
      {notChecked.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {notChecked.map((rule) => (
            <li key={rule.rule_id} className="rounded-md bg-white/70 px-2.5 py-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <StateIcon state={rule.status} />
                <span className="text-xs text-neutral-700">{rule.rule_name}</span>
                <span
                  className={cn(
                    'inline-flex h-5 items-center rounded-full px-1.5 text-[11px] font-medium',
                    STATE_STYLE[rule.status],
                  )}
                >
                  {STATE_TEXT[rule.status]}
                </span>
              </div>
              {/* 只显示引擎给的商家话术：没有就给状态标签（不拿 reason 顶替） */}
              {rule.display && (
                <p className="mt-0.5 pl-5 text-[11px] leading-relaxed text-neutral-500">{rule.display}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
