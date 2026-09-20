'use client'

import Badge from '@/components/ui/Badge'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
// 工序显示名的**唯一**口径（issue #4621）：逻辑名 · 部位 —— 本表**不得**直接渲染变体名
import { operationDisplayName } from '@/lib/operation-display'
import type { ProductionPosition } from '@/types'

/**
 * 工序进度表（issue #4000，M4-H 按需单据渲染）
 *
 * 按**套**（一樘窗 = 一套，issue #4686 用户裁定 2026-09-20）分组展示加工单的工序实例：工序名 /
 * 分组 / 应做数量+单位 / 单价 / 状态 / 已完成数量 / 报工人。组头按行业口径标 **第 N 套 / 共 M 套**
 * （真值源 `docs/curtain-production-rules.md` 的「**第 N 套/共 M 套**」口径 —— 按该文本检索，不写行号）：
 * 读面已按 `order_item_id`
 * （= 一樘窗）分组返回**有序**列表（`ProductionService.buildPositions`）⇒ N = 该组在列表中的序号、
 * M = 列表长度，前端不另起一套口径。
 * ⚠️ 这里的分组**不是「部位」**（部位 = 布帘/纱帘/帘头，读面键 = `position_kind`）；`position_name`
 * 是**展示名**（加工产物名[+色号]），降为副标题 —— 它回答的是「这一套是哪一樘窗」。
 * 必完工序（is_must_finish，「此工序必须完成才可打包」）加「必完」badge —— 商家据此看进度、
 * 工人据此知道哪道不能漏（真值源：docs/curtain-production-rules.md §2 工序库）。
 * 应做数量由算料引擎给出、报工只确认（§3），故此处只读展示、不做手工计算。
 */
interface ProductionProgressTableProps {
  /** 后端 positions 段（snake_case 键）；缺省/空 → 空态 */
  positions?: ProductionPosition[]
  className?: string
}

/** 数量 + 单位（单位缺省时只显示数量，不留悬空空格） */
function formatQty(value?: number, unit?: string | null): string {
  const n = value ?? 0
  return unit ? `${n} ${unit}` : String(n)
}

function formatPrice(value?: number): string {
  return `¥${(value ?? 0).toFixed(2)}`
}

function statusChip(status?: string | null): { label: string; tone: 'success' | 'neutral' } {
  return status === 'done' ? { label: '已完成', tone: 'success' } : { label: '待做', tone: 'neutral' }
}

export default function ProductionProgressTable({ positions, className }: ProductionProgressTableProps) {
  // 套口径（issue #4686）：读面按 `order_item_id`（一樘窗 = 一套）分组返回**有序**列表
  // ⇒ 套号 / 套数直接由该列表派生（N = 序号、M = 列表长度），不在前端另数一遍。
  const sets = positions ?? []

  if (sets.every((s) => (s.operations ?? []).length === 0)) {
    return (
      <div className={className} data-testid="production-progress-empty">
        <p className="py-8 text-center text-sm text-neutral-400">暂无工序数据</p>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className="space-y-6">
        {sets.map((set, setIndex) => {
          const operations = set.operations ?? []
          if (operations.length === 0) return null
          const name = set.position_name || ''
          return (
            <div key={`${name}-${setIndex}`} data-testid={`position-group-${name}`}>
              <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-sm font-medium text-neutral-900">
                  第 {setIndex + 1} 套 / 共 {sets.length} 套
                </span>
                {/* 副标题 = 这一套是**哪一樘窗**（加工产物名[+色号]）；它不是「部位」 */}
                {name && <span className="text-xs text-neutral-500">{name}</span>}
                <span className="text-xs text-neutral-400">{operations.length} 道工序</span>
              </div>
              <div className="overflow-x-auto rounded-lg border border-neutral-200">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 bg-neutral-50/60">
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">工序</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">分组</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">应做数量</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">单价</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">状态</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">已完成数量</th>
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">报工人</th>
                    </tr>
                  </thead>
                  <tbody>
                    {operations.map((op) => {
                      const chip = statusChip(op.status)
                      return (
                        <tr
                          key={op.id}
                          data-testid={`operation-row-${op.id}`}
                          className="border-b border-neutral-100 last:border-b-0"
                        >
                          <td className="px-4 py-3">
                            <span className="mr-2 text-xs text-neutral-400">{op.seq ?? ''}</span>
                            <span className="text-neutral-900">{operationDisplayName(op)}</span>
                            {op.is_must_finish && (
                              <Badge variant="warning" className="ml-2" title="此工序必须完成才可打包">
                                必完
                              </Badge>
                            )}
                          </td>
                          <td className="px-4 py-3 text-neutral-600" data-testid="op-group">
                            {op.group || '—'}
                          </td>
                          <td className="px-4 py-3 text-neutral-900 whitespace-nowrap" data-testid="op-qty">
                            {formatQty(op.qty, op.unit)}
                          </td>
                          <td className="px-4 py-3 text-neutral-600 whitespace-nowrap" data-testid="op-unit-price">
                            {formatPrice(op.unit_price)}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap" data-testid="op-status">
                            <StatusBadge label={chip.label} color={chipToneClasses[chip.tone]} dot />
                          </td>
                          <td className="px-4 py-3 text-neutral-900 whitespace-nowrap" data-testid="op-done">
                            {formatQty(op.done_qty, op.unit)}
                          </td>
                          {/* 报工人（issue #4309）：后端 workers 已去重/排序/折「未署名」；无报工 ⇒ 「—」 */}
                          <td className="px-4 py-3 text-neutral-600" data-testid="op-workers">
                            {op.workers?.join('、') || '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
