'use client'

import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProactiveRuleState, ProactiveStatus } from '@/types'

/**
 * 「主动检查」逐规则接线状态面板（issue #5955）
 *
 * 治的是「**今天为什么没有提示**」：日报「没命中」有三个**性质完全不同**的原因 ——
 *  ① 已检查、确实没问题（`wired`）；
 *  ② 系统**没做**这件事（`not_wired`，不可行动）；
 *  ③ 系统有、**该租户没开**（`not_enabled`，可行动：去开启）；
 *  ④ 接上了但**本次不完整**（`incomplete`：截断 / 维度缺值 / 有行未判定）。
 * ②③④ 都**不许**被读成「今天没问题」——「未知 ≠ 没问题」。所以每条规则一行、**具名 + 带原因**，
 * 且**只读**（卡片面不给任何处置入口：处置能力与写能力另议）。
 *
 * 口径边界（判据钉住，勿改）：
 * · `not_enabled`（可行动）与 `not_wired`（不可行动）**必须分开说**，不合并成「未接入」；
 * · `caveats`（如审计 fail-open 这类**数据源固有边界**）**恒在** —— 不许因为「绿」就不显示边界；
 * · 不制造告警噪音：面板用中性底色，**没有 `not_enabled` / `not_wired` 时不置警示色**；
 * · 状态为 null / 缺失 ⇒ 整个面板**不渲染**（未采集 ≠ 没问题，也不许用空壳冒充「已检查」）。
 */
export interface ProactiveStatusPanelProps {
  /** 逐规则四态（后端原样透传；null/undefined = 未采集 ⇒ 不渲染） */
  status?: ProactiveStatus | null
  /** `page` = 每条都展开原因（日报页）；`dashboard` = 绿色行收起、只写「已检查、无命中」 */
  variant?: 'page' | 'dashboard'
}

/** 四态 → 文案（**四个说法各不相同**，尤其 `not_enabled` 与 `not_wired`） */
const STATE_TEXT: Record<ProactiveRuleState, string> = {
  wired: '已检查、无命中',
  not_wired: '系统尚未接入',
  not_enabled: '你还没开启',
  incomplete: '本次数据不完整',
}

const STATE_STYLE: Record<ProactiveRuleState, string> = {
  wired: 'bg-neutral-100 text-neutral-500',
  not_wired: 'bg-amber-50 text-amber-700',
  not_enabled: 'bg-primary-50 text-primary-600',
  incomplete: 'bg-amber-50 text-amber-700',
}

function StateIcon({ state }: { state: ProactiveRuleState }) {
  const cls = 'h-3.5 w-3.5 flex-shrink-0'
  if (state === 'wired') return <CheckCircle2 className={cn(cls, 'text-neutral-400')} />
  // `not_enabled` = 系统有、该租户没开（**可行动**）⇒ 用「提示」而不是「错误」
  if (state === 'not_enabled') return <Info className={cn(cls, 'text-primary-500')} />
  if (state === 'not_wired') return <XCircle className={cn(cls, 'text-amber-500')} />
  return <AlertTriangle className={cn(cls, 'text-amber-500')} />
}

export default function ProactiveStatusPanel({ status, variant = 'dashboard' }: ProactiveStatusPanelProps) {
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
        <h3 className="text-xs font-semibold text-neutral-600">主动检查（逐规则）</h3>
        <span className="text-[11px] text-neutral-400">
          {notChecked.length
            ? `${notChecked.length} 项本次没有检查 / 检查不完整 —— 不等于「今天没问题」`
            : '全部已检查，无命中'}
        </span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {rows.map((rule) => {
          const caveats = rule.caveats ?? []
          // 有原因就显示原因：非 wired 的原因本身就是「为什么没检查」；
          // wired 的原因（引擎可能并入边界）也照显示，边界不许静默。
          const detail = rule.reason || ''
          return (
            <li key={rule.rule_id} className="rounded-md bg-white/70 px-2.5 py-1.5">
              <div className="flex items-center gap-2">
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
              {/* `page`：原因恒显示；`dashboard`：非绿行才显示（绿行原因省略，避免噪音） */}
              {detail && (variant === 'page' || rule.status !== 'wired') && (
                <p className="mt-0.5 pl-5 text-[11px] leading-relaxed text-neutral-500">{detail}</p>
              )}
              {caveats.length > 0 && (
                <ul className="mt-1 space-y-0.5 pl-5">
                  {caveats.map((item, i) => (
                    <li key={i} className="text-[11px] leading-relaxed text-neutral-400">
                      边界：{item}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      <p className="mt-2 text-[11px] text-neutral-400">
        本面板为只读说明（告诉您哪些方面本次没有数据），不含任何处置入口。
      </p>
    </div>
  )
}
