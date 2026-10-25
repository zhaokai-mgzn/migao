'use client'

import { useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { processingOrderApi } from '@/lib/api'
// 作业单两型（issue #7079）：出库作业单**没有加工方、没有交期** ⇒ 取消用「取消作业单」的措辞
import { orderKindOf } from '@/lib/processing-order'
import type { ProcessingOrder } from '@/types'

interface Props {
  /** 生产明细页已加载的作业单（本组件不取数，写面只发 PATCH） */
  po: ProcessingOrder
  /** 动作成功后的新单据：父级据此刷新状态徽标 / 时间线（本组件不留第二份状态） */
  onChanged?: (next: ProcessingOrder) => void
}

/**
 * 作业单状态动作（issue #7634 搬到这里；issue #7723 移除「发加工」）。
 *
 * 保留三个写动作：开始加工 / 加工完成 / 取消。
 *
 * 🔴 **为什么不再有「发加工」**（用户 2026-10-25 裁定 A）：
 * ① 生产入口已收敛到**智能派单**（#7634），「已生成」只可能由派单产生 ⇒ 再点一次「发加工」
 *    不代表任何人工判断；② 外发（加工厂 + 回厂日）是「**谁干**」，改在**派单**录入 ——
 *    它是派单的属性，不是作业单的属性（中途收回自做 / 换厂都不该改作业单历史）；
 * ③ 订单 `confirmed→producing` 的时点随之下沉到**派单**（#7723），不再由本页驱动。
 * 首工序报满仍会把作业单推进「加工中」（`generated` 与 `issued` 都可进，A6 后半已裁定）。
 */
export default function ProcessingOrderActions({ po, onChanged }: Props) {
  const [form, setForm] = useState<null | { reason?: string }>(null)
  const [busy, setBusy] = useState(false)
  /** 简单流转（开始加工 / 加工完成）待确认的那个动作（issue #6664 第 4 条） */
  const [simpleAction, setSimpleAction] = useState<'start' | 'complete' | null>(null)
  const [simpleBusy, setSimpleBusy] = useState(false)
  const [error, setError] = useState('')

  // 缺键 = 存量单 ⇒ 按加工单处理（不把存量单读成出库）
  const outbound = orderKindOf(po) === 'outbound'
  const canAct = !['completed', 'cancelled'].includes(po.status)

  /** 取消（原因必填，涉及订单状态联动） */
  const handleCancel = async () => {
    if (!form) return
    setBusy(true)
    setError('')
    try {
      const res = await processingOrderApi.update(po.id, { action: 'cancel', reason: form.reason })
      const data = res.data?.data
      onChanged?.(data ?? po)
      setForm(null)
    } catch {
      setError('操作失败，请确认作业单状态与填写内容')
    } finally {
      setBusy(false)
    }
  }

  /** start/complete 简单流转：先弹框确认（issue #6664 第 4 条：不用 window.confirm），
   *  在飞时按钮 disabled（防连点重复请求） */
  const runSimpleAction = async () => {
    if (!simpleAction) return
    if (simpleBusy) return
    setSimpleBusy(true)
    setError('')
    try {
      const res = await processingOrderApi.update(po.id, { action: simpleAction })
      const data = res.data?.data
      onChanged?.(data ?? po)
      setSimpleAction(null)
    } catch {
      setError('操作失败，请确认作业单状态')
    } finally {
      setSimpleBusy(false)
    }
  }

  const errorBlock = <p className="text-xs text-red-500">{error}</p>

  return (
    <>
      <div data-testid="processing-order-actions" className="po-no-print flex flex-wrap items-center gap-2">
        {canAct && po.status === 'issued' && (
          <Button size="sm" disabled={simpleBusy} data-testid="po-action-start" onClick={() => setSimpleAction('start')}>
            开始加工
          </Button>
        )}
        {canAct && po.status === 'in_processing' && (
          <Button size="sm" disabled={simpleBusy} data-testid="po-action-complete" onClick={() => setSimpleAction('complete')}>
            加工完成
          </Button>
        )}
        {canAct && (
          <Button variant="secondary" size="sm" data-testid="po-action-cancel" onClick={() => setForm({})}>
            {outbound ? '取消作业单' : '取消加工单'}
          </Button>
        )}
        {error && !form && simpleAction === null && <div>{errorBlock}</div>}
      </div>

      {/* 取消 内联表单（原因必填） */}
      {form && (
        <div className="po-no-print mt-3 rounded-md border border-neutral-200 bg-neutral-50 p-3 text-sm">
          <input
            className="mb-2 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
            placeholder="取消原因（必填，涉及订单状态联动）"
            value={form.reason ?? ''}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || !form.reason} onClick={() => void handleCancel()}>确认取消</Button>
            <Button variant="secondary" size="sm" onClick={() => setForm(null)}>返回</Button>
          </div>
          {error && <div className="mt-2">{errorBlock}</div>}
        </div>
      )}

      {/* 简单流转确认弹框（issue #6664 第 4 条）：取消 ⇒ 不发请求；在飞 ⇒ 按钮 disabled */}
      <Modal
        open={simpleAction !== null}
        onClose={() => { if (!simpleBusy) setSimpleAction(null) }}
        title="确认状态流转"
        footer={
          <>
            <Button variant="secondary" disabled={simpleBusy} onClick={() => setSimpleAction(null)}>取消</Button>
            <Button loading={simpleBusy} onClick={() => void runSimpleAction()}>确认</Button>
          </>
        }
      >
        <p className="text-sm text-neutral-600">
          将作业单 {po.processingOrderNo} 标记为「{simpleAction === 'start' ? '开始加工' : '加工完成'}」。
        </p>
        <p className="mt-2 text-sm text-neutral-500">
          该动作会写入作业单状态、不可撤销，请确认后再提交。
        </p>
        {error && <div className="mt-2">{errorBlock}</div>}
      </Modal>
    </>
  )
}
