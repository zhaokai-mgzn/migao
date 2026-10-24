'use client'

import { useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { processingOrderApi } from '@/lib/api'
// 作业单两型（issue #7079）：出库作业单**没有加工方、没有交期** ⇒ 不出「发加工」，取消也换措辞
import { orderKindOf } from '@/lib/processing-order'
import type { ProcessingOrder } from '@/types'

interface Props {
  /** 生产明细页已加载的作业单（本组件不取数，写面只发 PATCH） */
  po: ProcessingOrder
  /** 动作成功后的新单据：父级据此刷新状态徽标 / 时间线（本组件不留第二份状态） */
  onChanged?: (next: ProcessingOrder) => void
}

/** 本地时区今天（yyyy-MM-dd）：发加工交期 date 控件 min 与防御校验同口径（issue #3901） */
function todayLocal(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

/**
 * 作业单状态动作（issue #7634）：发加工 / 开始加工 / 加工完成 / 取消 四个写动作
 * 从销售订单「作业单」块**搬到这里**（用户裁定：销售订单只读，状态流转只在这张单的生产页发生）。
 * 行为逐字沿用原块（表单、确认弹框、失败提示、交期边界校验）。
 */
export default function ProcessingOrderActions({ po, onChanged }: Props) {
  const [form, setForm] = useState<null | {
    action: 'issue' | 'cancel'
    processor?: string
    date?: string
    reason?: string
  }>(null)
  const [busy, setBusy] = useState(false)
  /** 简单流转（开始加工 / 加工完成）待确认的那个动作（issue #6664 第 4 条） */
  const [simpleAction, setSimpleAction] = useState<'start' | 'complete' | null>(null)
  const [simpleBusy, setSimpleBusy] = useState(false)
  const [error, setError] = useState('')

  // 缺键 = 存量单 ⇒ 按加工单处理（不把存量单读成出库）
  const outbound = orderKindOf(po) === 'outbound'
  const canAct = !['completed', 'cancelled'].includes(po.status)

  const handleAction = async () => {
    if (!form) return
    // issue #3901：交期不允许早于今天（date 控件 min 之外的双保险，兜住非控件路径）
    if (form.action === 'issue' && form.date && form.date < todayLocal()) {
      setError('交付日期不能早于今天')
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await processingOrderApi.update(po.id, {
        action: form.action,
        processor: form.processor,
        expectedDeliveryDate: form.date,
        reason: form.reason,
      })
      const data = res.data?.data
      onChanged?.(data ?? po)
      setForm(null)
    } catch {
      setError('操作失败，请确认加工单状态与填写内容')
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
      setError('操作失败，请确认加工单状态')
    } finally {
      setSimpleBusy(false)
    }
  }

  const errorBlock = <p className="text-xs text-red-500">{error}</p>

  return (
    <>
      <div data-testid="processing-order-actions" className="po-no-print flex flex-wrap items-center gap-2">
        {canAct && po.status === 'generated' && !outbound && (
          <Button size="sm" data-testid="po-action-issue" onClick={() => setForm({ action: 'issue' })}>
            发加工
          </Button>
        )}
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
          <Button variant="secondary" size="sm" data-testid="po-action-cancel" onClick={() => setForm({ action: 'cancel' })}>
            {outbound ? '取消作业单' : '取消加工单'}
          </Button>
        )}
        {error && !form && simpleAction === null && <div>{errorBlock}</div>}
      </div>

      {/* 发加工/取消 内联表单 */}
      {form && (
        <div className="po-no-print mt-3 rounded-md border border-neutral-200 bg-neutral-50 p-3 text-sm">
          {form.action === 'issue' ? (
            <>
              <div className="mb-2 flex flex-wrap gap-2">
                <input
                  className="rounded border border-neutral-300 px-2 py-1 text-sm"
                  placeholder="加工方（如：朝阳加工厂）"
                  value={form.processor ?? ''}
                  onChange={(e) => setForm({ ...form, processor: e.target.value })}
                />
                <input
                  className="rounded border border-neutral-300 px-2 py-1 text-sm"
                  type="date"
                  min={todayLocal()}
                  placeholder="交期 yyyy-MM-dd"
                  value={form.date ?? ''}
                  onChange={(e) => setForm({ ...form, date: e.target.value })}
                />
              </div>
              <div className="flex gap-2">
                <Button size="sm" disabled={busy} onClick={handleAction}>确认发加工</Button>
                <Button variant="secondary" size="sm" onClick={() => setForm(null)}>取消</Button>
              </div>
              {error && <div className="mt-2">{errorBlock}</div>}
            </>
          ) : (
            <>
              <input
                className="mb-2 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
                placeholder="取消原因（必填，涉及订单状态联动）"
                value={form.reason ?? ''}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              />
              <div className="flex gap-2">
                <Button size="sm" disabled={busy || !form.reason} onClick={handleAction}>确认取消</Button>
                <Button variant="secondary" size="sm" onClick={() => setForm(null)}>返回</Button>
              </div>
              {error && <div className="mt-2">{errorBlock}</div>}
            </>
          )}
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
