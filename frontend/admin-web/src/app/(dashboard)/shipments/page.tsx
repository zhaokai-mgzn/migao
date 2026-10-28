'use client'

// 发货单列表页（issue #5939）—— 大菜单「仓储与物料 ▸ 发货单」的页面（page.tsx 本体 = 客户端组件，
// 与 `/inbound-orders` 同构）。
// 🔴 整页写在一个文件里**是有意的**：判据 12（`tests/unit_ci_workflows/test_agent_permission_parity.py`）
// 把「菜单节点码 ≡ 该页第一屏读端点码」锚在**本文件**上（`MENU_READ_ENDPOINT_ANCHORS['/shipments']`
// ⇒ `shipments/page.tsx` 里的 `shipmentApi.list`）—— 把调用搬到同目录的兄弟组件里会让那条判据
// 「解析不到第一屏调用」而红。

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { RotateCcw, Search, Truck } from 'lucide-react'
import { orderApi, shipmentApi } from '@/lib/api'
import { Button, Input, PageCard, PageHeader, TableSkeleton } from '@/components/ui'
// 来源展示口径（内部键不上屏，issue #6664 第 5 条）：与判据同一份模块
import { sourceLabel } from '@/components/orders/shipment-source'
import type { ShipmentListRow } from '@/types'
import { formatFullDateTime } from '@/lib/utils'

// ============================================================
// 发货单列表（issue #5939）—— 大菜单「仓储与物料 ▸ 发货单」的第一屏
// ============================================================
// 用户的报障（2026-10-02 原话）：「我让你开发过发货单的，但是在大菜单上没见到这个单据」。
// 病根：发货单此前**只有按单入口**（订单详情 →「发货」/「打印发货单」）—— 想知道「这个月发过哪些货」
// 必须先知道是哪张订单；而**入库单**（同样的仓储存货单据）一直有独立菜单项 ⇒ 对称性缺失。
//
// 本页三件事：
//   ① 全量发货单（本租户）—— 单号 / 订单号 / 客户 / 来源 / 发货人 / 发货时间 / 实发；
//   ② 筛选：关键词（发货单号 / 订单号 / 客户名，服务端 ILIKE，三列都匹配）；
//   ③ ~~补打~~ —— **已退场**（issue #7902，用户 2026-10-27 逐字「移除发货单打印」）：
//      发货单这张纸整体退场，纸统一在销售订单详情的打印层里出；本页只剩「记录 + 查订单」。
//      守卫 `tests/unit_ci_workflows/test_print_single_doc_on_paper.py` 仍要求页面里没有第二处 `window.print()`。
//
// 🔴 「实发」不在前端重算：数字来自服务端 `shippedTotals`（与按单读面 `orderApi.getOrderShipments`
// **同一份实现** `OrderShipmentService.totals()`）—— 前端只负责显示，不做第三套口径。


/**
 * 实发汇总 → 一行短文案（**缺值不填 0**）。
 *
 * 口径（与按单读面同源）：`by_unit` 按单位分行累计；`set_count` / `roll_count` **只对显式填过的行**
 * 求和 ⇒ 0 的语义是「这一维不适用」，故为 0 时**不显示**（显示成「0 套」= 把「不适用」说成「一件没发」）。
 * 一条明细都没有 ⇒ 显式写「无实发明细」（不是空白、不是 `0`）。
 */
export function shippedSummary(row: ShipmentListRow): string {
  const totals = row.shippedTotals
  const parts: string[] = []
  Object.entries(totals?.by_unit ?? {}).forEach(([unit, qty]) => parts.push(`${qty}${unit}`))
  if (totals?.set_count) parts.push(`${totals.set_count} 套`)
  if (totals?.roll_count) parts.push(`${totals.roll_count} 卷`)
  return parts.length > 0 ? parts.join(' / ') : '无实发明细'
}

/** 发货人：未采集（存量单 / 商家侧未填）⇒「-」，**不留白、不写「未知」**（纸面同口径，issue #3818） */
function shipperCell(row: ShipmentListRow): string {
  const name = (row.shippedByWorkerName || '').trim()
  return name || '-'
}

export default function ShipmentsPage() {
  const router = useRouter()
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<ShipmentListRow[]>([])
  const [loading, setLoading] = useState(false)
  /** 读面失败（与「暂无发货单」互斥）：故障不是业务事实，issue #6664 第 3 条 */
  const [loadError, setLoadError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await shipmentApi.list({ keyword: keyword.trim() || undefined })
      setRows(res.data.data ?? [])
      setLoadError(false)
    } catch {
      // request 拦截器已 toast；此处只标**失败态**、**不清零**（读面故障 ≠「没有发货单」）
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [keyword])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="p-6 space-y-4">
      {/* 页头 */}
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Truck className="w-5 h-5 text-primary-600" />
            发货单
          </span>
        }
        subtitle={<>管理发货单：<strong>可按单号、订单号、客户检索</strong>，并补打纸质发货单</>}
      />

      {/* 筛选 */}
      <PageCard className="flex items-center gap-3">
        <Input
          aria-label="搜索发货单"
          placeholder="发货单号 / 订单号 / 客户"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="max-w-xs"
        />
        <Button variant="secondary" onClick={() => void load()}>
          <Search className="w-4 h-4 mr-1.5" />
          查询
        </Button>
        <Button variant="ghost" onClick={() => setKeyword('')}>
          <RotateCcw className="w-4 h-4 mr-1.5" />
          重置
        </Button>
      </PageCard>

      {/* 列表 */}
      <PageCard padded={false} className="overflow-hidden">
        {/* issue #8048：加载态 = 通用表格骨架（#8036 口径：页面级三元），与 8 列对齐；
            不再在 tbody 里印裸「加载中…」+ 空白表体。 */}
        {loading ? (
          <TableSkeleton rows={8} columns={8} />
        ) : (
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-neutral-600">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium">发货单号</th>
              <th className="text-left px-4 py-2.5 font-medium">订单号</th>
              <th className="text-left px-4 py-2.5 font-medium">客户</th>
              <th className="text-left px-4 py-2.5 font-medium">来源</th>
              <th className="text-left px-4 py-2.5 font-medium">发货人</th>
              <th className="text-left px-4 py-2.5 font-medium">发货时间</th>
              <th className="text-left px-4 py-2.5 font-medium">实发</th>
              <th className="text-right px-4 py-2.5 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                data-testid="shipment-row"
                className="border-t border-neutral-100 hover:bg-neutral-50"
              >
                <td className="px-4 py-2.5 font-mono text-neutral-900">{row.shipmentNo}</td>
                <td className="px-4 py-2.5 font-mono text-neutral-600">{row.orderNo || '-'}</td>
                <td className="px-4 py-2.5 text-neutral-700">{row.customerName || '-'}</td>
                <td className="px-4 py-2.5 text-neutral-600">
                  {sourceLabel(row.source)}
                </td>
                <td className="px-4 py-2.5 text-neutral-600" data-testid="shipment-shipper">
                  {shipperCell(row)}
                </td>
                <td className="px-4 py-2.5 text-neutral-600" data-testid="shipment-shipped-at">
                  {/* 未发货（工人已打包但还没发）⇒ 显式「未发货」，**不填当前时间** */}
                  {row.shippedAt ? formatFullDateTime(row.shippedAt) : '未发货'}
                </td>
                <td className="px-4 py-2.5 text-neutral-700" data-testid="shipment-shipped">
                  {shippedSummary(row)}
                </td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/orders/${row.orderId}`)}
                  >
                    查看订单
                  </Button>                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-neutral-400">
                  {loadError ? (
                    // 失败态与空态**分离**（issue #6664 第 3 条）：故障说「加载失败」+ 重试出口
                    <span
                      data-testid="shipments-load-failed"
                      role="alert"
                      className="inline-flex items-center gap-3"
                    >
                      <span className="text-neutral-600">发货单加载失败，请检查网络后重试</span>
                      <Button
                        data-testid="shipments-load-failed-retry"
                        variant="secondary"
                        size="sm"
                        onClick={() => void load()}
                      >
                        重试
                      </Button>
                    </span>
                  ) : keyword ? (
                    // issue #8040：筛选下为空（换个条件再查）—— 与「真还没有发货单」分开说
                    <span data-testid="shipments-empty">没有符合筛选条件的发货单 —— 换个单号或客户名再查一次</span>
                  ) : (
                    <span data-testid="shipments-empty">还没有发货单 —— 在订单里点「发货」后会自动生成一张发货单</span>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        )}
      </PageCard>

    </div>
  )
}
