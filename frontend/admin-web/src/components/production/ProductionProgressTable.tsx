'use client'

import Badge from '@/components/ui/Badge'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
// 工序显示名的**唯一**口径（issue #4621）：逻辑名 · 部位 —— 本表**不得**直接渲染变体名
import { operationDisplayName } from '@/lib/operation-display'
import { PRICING_ENTRY_HREF } from '@/components/production/UnpricedNotice'
import Link from 'next/link'
import type { ProductionPosition } from '@/types'

/**
 * 工序进度表（issue #4000，M4-H 按需单据渲染）
 *
 * 按**套**（一樘窗 = 一套，issue #4686 用户裁定 2026-09-20）分组展示加工单的工序实例：工序名 /
 * 分组 / 应做数量+单位 / 计件单价 / 状态 / 已完成数量 / 报工人。组头按行业口径标 **第 N 套 / 共 M 套**
 * （真值源 `docs/curtain-production-rules.md` 的「**第 N 套/共 M 套**」口径 —— 按该文本检索，不写行号）。
 *
 * ⚠️ **套键取自读面追加的 `set_no` 键**（issue #4784）：读面 `ProductionService.buildPositions`
 * 返回的列表仍按 `order_item_id` = **部位**分组（#4388 冻结契约 —— 它**不是**套），
 * 它**追加**的 `set_no` 才是套键（= 计件报表 `per_set` 的**同一份口径**：V92 套号优先、
 * 无号回落樘窗组键 `craftLineId ?? itemId`）⇒ N = 该套在分组序列中的序号、M = 套数。
 * 🔴 改前本表**把每个部位块当一个「套」**（只数列表长度）⇒ 一樘「布 + 纱 + 帘头」显示 **3 套**，
 * 而同一张单的计件报表说 **1 套**（同一系统两个答案，且没有任何东西会因此变红）。
 * 缺 `set_no`（老数据 / 读面未升级）⇒ 退回「每个部位自成一套」（= 改前行为，不猜）。
 * ⚠️ 套分组**不是「部位」**（部位 = 布帘/纱帘/帘头，读面键 = `position_kind`）；`position_name`
 * 是**展示名**（加工产物名[+色号]），降为部位块副标题 —— 它回答的是「这一块是哪一件帘」。
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

/** 一个部位块 + 它所属的**套**（套头只在每套的第一个部位块上渲染一次）。 */
interface SetPosition {
  position: ProductionPosition
  /** 套序号（0 起；渲染时 +1） */
  setIndex: number
  /** 套数 = 不同套键的个数 */
  setCount: number
  /** 是否该套的第一个部位块（⇒ 由它渲染套头，避免同一套重复三遍） */
  firstOfSet: boolean
}

/**
 * 按**套键**（读面 `set_no`）把部位列表分组（issue #4784）。
 *
 * 口径 = 与计件报表 `per_set` **同一份**（后端 `ProductionService.setKey`，**不新造第二份**）。
 * 缺 `set_no`（老数据 / 读面未升级）⇒ 该部位**自成一套**（= 改前行为，逐字不变，不猜）。
 */
function groupBySet(positions: ProductionPosition[]): SetPosition[] {
  const keys = positions.map((p, i) => p.set_no ?? `\u0000position-${i}`)
  const setOrder: string[] = []
  keys.forEach((key) => {
    if (!setOrder.includes(key)) setOrder.push(key)
  })
  return positions.map((position, i) => ({
    position,
    setIndex: setOrder.indexOf(keys[i]),
    setCount: setOrder.length,
    firstOfSet: keys.indexOf(keys[i]) === i,
  }))
}

export default function ProductionProgressTable({ positions, className }: ProductionProgressTableProps) {
  // 套口径（issue #4784）：按读面的 `set_no`（樘窗组键）分组 —— **不再**按部位块个数当套数
  // （那正是「一樘布+纱+帘头 = 3 套」的口径分裂来源）。
  // 无工序的部位块先滤掉：否则「该套的第一个块恰好是空块」时套头会连块一起消失。
  const blocks = groupBySet((positions ?? []).filter((p) => (p.operations ?? []).length > 0))

  if (blocks.length === 0) {
    return (
      <div className={className} data-testid="production-progress-empty">
        <p className="py-8 text-center text-sm text-neutral-400">暂无工序数据</p>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className="space-y-6">
        {blocks.map(({ position, setIndex, setCount, firstOfSet }, blockIndex) => {
          const operations = position.operations ?? []
          const name = position.position_name || ''
          return (
            <div key={`${name}-${blockIndex}`} data-testid={`position-group-${name}`}>
              <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                {/* 套头**每套只渲染一次**（issue #4784）：同一套的每个部位块都重复一遍，
                    会被读成「三套都叫第 1 套」 */}
                {firstOfSet && (
                  <span className="text-sm font-medium text-neutral-900">
                    第 {setIndex + 1} 套 / 共 {setCount} 套
                  </span>
                )}
                {/* 副标题 = 这一块是**哪一件帘**（加工产物名[+色号]）；它不是「部位」 */}
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
                      {/* issue #4910：本列的值就是**计件单价**（部位价目矩阵格价，报工计件用）
                          ⇒ 列头逐字写作「计件单价」，避免被读成销售单价 */}
                      <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">计件单价</th>
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
                          {/* 未定价 ≠ ¥0.00（V90，issue #4696）：`unit_price` 为 null（或显式
                              `price_state='unpriced'`）⇒ 显示「未定价」+ 定价入口，**不得**折成 ¥0.00
                              （折 0 ⇒ 与「定价为 0 元」同形 ⇒ 商家看不出工人干了活拿不到钱）。 */}
                          <td className="px-4 py-3 text-neutral-600 whitespace-nowrap" data-testid="op-unit-price">
                            {op.price_state === 'unpriced' || op.unit_price == null ? (
                              <span
                                className="inline-flex items-center gap-2 text-amber-700"
                                data-testid="op-unit-price-unpriced"
                              >
                                未定价
                                <Link
                                  href={PRICING_ENTRY_HREF}
                                  data-testid="op-unit-price-pricing-link"
                                  className="rounded border border-amber-400 bg-white px-1.5 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                                >
                                  去定价
                                </Link>
                              </span>
                            ) : (
                              formatPrice(op.unit_price)
                            )}
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
