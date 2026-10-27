'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui'
import DateTimeCell from '@/components/common/DateTimeCell'
import { orderApi } from '@/lib/api'
import { printDocTypeLabel, printMediaLabel } from '@/lib/print-doc'
import type { PrintLogView } from '@/types'

/**
 * 本单的**打印流水**（issue #7902）—— 订单详情页常驻区块。
 *
 * ## 为什么要留在订单上（而不是只做全局流水页）
 *
 * 商家的问题是「这张单的纸到底打过没有、谁打的、补打了几次」——答案是**这一单的属性**。
 * 用户的裁定（2026-10-27）：**只在订单详情里看本单的流水**，不做全局页。
 *
 * ## 常驻面克制（产品设计原则 P1）
 *
 * 打印次数会随补打增长，所以**常驻面最多 5 行**；更多的按需展开（`max-h + overflow-y-auto`），
 * 折叠态下**不渲染**逐条 DOM（不是 CSS 隐藏 —— 那样只是看不见，仍在屏上占位）。
 *
 * ## 缺值口径
 *
 * 操作人 / 纸型 / 订单状态都可能缺（存量行、早期记录、匿名会话）⇒ 一律「—」，
 * **不猜、不留空**；`docTitle` 优先用**打印当时的快照**（「加工单」还是「面料单」是那一刻的事实）。
 */
export interface PrintLogPanelProps {
  orderId: string
  /** 每次打印成功后 +1 ⇒ 本块重新读一次（读面是服务端真值，前端不自己拼一条本地流水） */
  refreshKey: number
}

const COLLAPSED_ROWS = 5

export default function PrintLogPanel({ orderId, refreshKey }: PrintLogPanelProps) {
  const [logs, setLogs] = useState<PrintLogView[] | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [failed, setFailed] = useState(false)

  const load = useCallback(async () => {
    setFailed(false)
    try {
      const res = await orderApi.listPrintLogs(orderId, 20)
      // 🔴 形状兜底：读面**不是数组**时不许把页面渲染打崩（fixture 替身 / 网关异常页 / 旧版本接口）。
      // 实测（CI Demo path specs）：替身把订单对象当流水返回 ⇒ `(logs ?? []).slice` 抛错
      // ⇒ 整张订单详情页白屏（流水是旁路，不该有这种权力）。
      setLogs(Array.isArray(res.data?.data) ? res.data.data : [])
    } catch {
      // 读失败 ≠「没打印过」：分开说（拦截器已 toast，这里只标失败态 + 给重试）
      setFailed(true)
    }
  }, [orderId])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const total = logs?.length ?? 0
  const visible = expanded ? (logs ?? []) : (logs ?? []).slice(0, COLLAPSED_ROWS)

  return (
    <div data-testid="order-print-logs">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-neutral-500">
          每次出纸记一条：时间 / 单据 / 操作人 / 纸型。最近打印在前。
        </p>
        {total > COLLAPSED_ROWS && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            data-testid="order-print-logs-toggle"
          >
            {expanded ? '收起' : `查看全部 ${total} 条`}
          </Button>
        )}
      </div>

      <div className="mt-3">
        {failed ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
            <span>打印流水读取失败 —— 请稍后重试</span>
            <Button variant="secondary" size="sm" onClick={() => void load()} data-testid="order-print-logs-retry">
              重试
            </Button>
          </div>
        ) : logs === null ? (
          <p className="text-sm text-neutral-400">加载中…</p>
        ) : total === 0 ? (
          <p className="text-sm text-neutral-400" data-testid="order-print-logs-empty">
            还没有打印记录
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-neutral-50 text-left text-neutral-600">
                  <th className="px-3 py-2 font-medium whitespace-nowrap">打印时间</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">单据</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">操作人</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">纸型</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">张数</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">通道</th>
                  <th className="px-3 py-2 font-medium whitespace-nowrap">结果</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((log) => (
                  <tr key={log.id} className="border-t border-neutral-100" data-testid={`print-log-${log.id}`}>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-700">
                      <DateTimeCell value={log.createdAt} />
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-800">
                      {log.docTitle || printDocTypeLabel(log.docType)}
                      {log.batchSize && log.batchSize > 1 && log.batchIndex ? (
                        <span className="ml-1 text-xs text-neutral-400">
                          （联合 {log.batchIndex}/{log.batchSize}）
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-700">
                      {log.operatorName || <span className="text-neutral-400">—</span>}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-600">{printMediaLabel(log.mediaId)}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-600">{log.sheets}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-600">
                      {log.channel === 'ble' ? '蓝牙直连' : '系统打印'}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {log.status === 'failed' ? (
                        <span className="text-red-600" title={log.failReason ?? undefined}>
                          失败
                        </span>
                      ) : (
                        <span className="text-emerald-700">已出纸</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
