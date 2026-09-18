'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import Badge from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import type { ProductionPosition } from '@/types'

/**
 * 加工单任务卡（可打印纸面，issue #4000 / M4-H 按需单据渲染）
 *
 * 贴在筐上/挂流水线的任务卡：加工单号 + **二维码**（内容 = 加工单 `qr_token`，工人扫码进小程序报工）
 * + 工序清单（工序名/应做数量/单位 + 手工勾选位，纸质勾选与小程序报工并存）。
 * 真值源：docs/curtain-production-rules.md §1（加工单打印物含二维码，二维码是扫码报工入口）/ §5 扫码报工闭环。
 *
 * 打印隔离沿用项目既有范式（见 components/orders/ShipmentDoc.tsx 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：页面已有屏幕布局，本组件 `display:none` + `@media print` 显形，
 *    屏幕上零视觉改动、打印时只有这张卡。
 * 2. **portal 到 body + display:none 隔离**：`body > *:not(.task-card-print-area) { display:none !important }`
 *    —— display:none 不占版面高度，避免按隐藏内容高度分页打出空白第二页。
 *    `.task-card-print-area` 必须是 portal 容器本身的 class（不能再包一层）。
 * 3. 不得放进 Modal（面板 max-h 会裁掉多页明细）；每页只挂一份（全局选择器）。
 * 4. 二维码内容只放 `qr_token`（token 化、可撤销），不放单号拼接串 —— 报工入口以后端 token 为准。
 */
interface TaskCardPrintProps {
  processingOrderNo: string
  orderNo?: string
  /** 加工单二维码 token（工人扫码报工）；为空时给占位提示，不画假码 */
  qrToken?: string | null
  /** 二维码缺失时的占位文案（缺省＝待生成）；撤销后传「已撤销」，避免纸面指向不存在的按钮 */
  qrPlaceholderHint?: string
  positions?: ProductionPosition[]
  className?: string
}

function formatQty(value?: number, unit?: string | null): string {
  const n = value ?? 0
  return unit ? `${n} ${unit}` : String(n)
}

export default function TaskCardPrint({
  processingOrderNo,
  orderNo,
  qrToken,
  qrPlaceholderHint,
  positions,
  className,
}: TaskCardPrintProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  const operations = (positions ?? []).flatMap((position) =>
    (position.operations ?? []).map((op) => ({ ...op, positionName: position.position_name || '' })),
  )

  return createPortal(
    <div className={cn('task-card-print-area text-neutral-900', className)}>
      <style>{`
        .task-card-print-area { display: none; }
        @page { size: A4; margin: 12mm; }
        @media print {
          body > *:not(.task-card-print-area) { display: none !important; }
          .task-card-print-area {
            display: block;
            position: static;
            width: 100%;
            font-size: 12px;
          }
          /* 防御：页面其他组件残留的 "body * { visibility: hidden }" 打印隔离
             （如 ProcessingOrderBlock）会连同本卡一起藏掉 —— 显式恢复自身可见 */
          .task-card-print-area, .task-card-print-area * { visibility: visible; }
        }
      `}</style>

      <div className="border-2 border-neutral-800 p-4">
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold tracking-wide">加工单任务卡</div>
            <div className="mt-2 text-sm text-neutral-500">加工单号</div>
            <div className="text-2xl font-bold tracking-wide" data-testid="task-card-no">
              {processingOrderNo}
            </div>
            {orderNo && (
              <div className="mt-1 text-xs text-neutral-500">
                订单号：<span data-testid="task-card-order-no">{orderNo}</span>
              </div>
            )}
          </div>

          <div className="text-center">
            {qrToken ? (
              <QRCodeSVG
                value={qrToken}
                size={132}
                level="M"
                title={qrToken}
                data-testid="task-card-qr"
                className="border border-neutral-300 p-1"
              />
            ) : (
              <div
                data-testid="task-card-qr-placeholder"
                className="flex h-[140px] w-[140px] items-center justify-center border border-dashed border-neutral-400 text-center text-xs text-neutral-500"
              >
                {qrPlaceholderHint ?? (
                  <>
                    二维码待生成
                    <br />
                    （本页点「补生成工序」即可）
                  </>
                )}
              </div>
            )}
            <div className="mt-1 text-xs text-neutral-600">扫码报工</div>
          </div>
        </div>

        <div className="mb-3 border border-neutral-400 bg-neutral-50 px-2 py-1.5 text-xs">
          工人扫码 → 小程序选本工序 → 填完成数量 → 计件自动登记（本卡勾选仅作车间纸质标记）
        </div>

        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="w-[8%] border border-neutral-400 px-2 py-1.5 text-left font-semibold">#</th>
              <th className="w-[18%] border border-neutral-400 px-2 py-1.5 text-left font-semibold">部位</th>
              <th className="w-[42%] border border-neutral-400 px-2 py-1.5 text-left font-semibold">工序</th>
              <th className="w-[20%] border border-neutral-400 px-2 py-1.5 text-left font-semibold">应做数量</th>
              <th className="w-[12%] border border-neutral-400 px-2 py-1.5 text-left font-semibold">完成</th>
            </tr>
          </thead>
          <tbody>
            {operations.length === 0 && (
              <tr>
                <td className="border border-neutral-400 px-2 py-3 text-center text-neutral-500" colSpan={5}>
                  该加工单暂无工序
                </td>
              </tr>
            )}
            {operations.map((op, index) => (
              <tr key={op.id ?? index} data-testid={`task-card-op-${index}`}>
                <td className="border border-neutral-400 px-2 py-1.5">{op.seq ?? index + 1}</td>
                <td className="border border-neutral-400 px-2 py-1.5" data-testid="task-card-op-position">
                  {op.positionName || '—'}
                </td>
                <td className="border border-neutral-400 px-2 py-1.5">
                  {op.operation}
                  {op.is_must_finish && (
                    <Badge variant="warning" className="ml-2">
                      必完
                    </Badge>
                  )}
                </td>
                <td className="border border-neutral-400 px-2 py-1.5" data-testid="task-card-op-qty">
                  {formatQty(op.qty, op.unit)}
                </td>
                <td className="border border-neutral-400 px-2 py-1.5">
                  {/* 手工勾选位（纸面标记；正式报工在小程序完成） */}
                  <span
                    data-testid="task-card-check"
                    aria-hidden="true"
                    className="inline-block h-4 w-4 border border-neutral-600 align-middle"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-3 flex justify-between text-xs text-neutral-500">
          <span>计件口径：合格数量 × 工序单价 × 系数（返工/报废不计件）</span>
          <span>共 {operations.length} 道工序</span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
