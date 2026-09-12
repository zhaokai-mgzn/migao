'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui'
import { processingOrderApi } from '@/lib/api'
import type { ProcessingOrder, ProcessingOrderItem } from '@/types'

interface Props {
  orderId: string
  orderStatus: string
  /** 订单是否含加工项（由父组件从明细判断） */
  hasProcessing: boolean
}

const STATUS_TEXT: Record<string, string> = {
  generated: '已生成',
  issued: '已发加工',
  in_processing: '加工中',
  completed: '加工完成',
  cancelled: '已取消',
}

const STEP_ORDER = ['generated', 'issued', 'in_processing', 'completed']

function formatAmount(v?: number): string {
  if (v == null) return '—'
  return String(v)
}

/** 加工单纯文本（复制给加工方/贴 Excel，一行一加工项） */
function toPlainText(po: ProcessingOrder): string {
  const lines: string[] = []
  lines.push(`加工单：${po.processingOrderNo}`)
  if (po.customerName) lines.push(`客户：${po.customerName}`)
  if (po.processor) lines.push(`加工方：${po.processor}`)
  if (po.expectedDeliveryDate) lines.push(`交期：${po.expectedDeliveryDate}`)
  lines.push(`状态：${STATUS_TEXT[po.status] ?? po.status}`)
  lines.push('')
  ;(po.items ?? []).forEach((it: ProcessingOrderItem, i: number) => {
    lines.push(`【${i + 1}】${it.productName ?? ''}${it.colorName ? `（${it.colorName}）` : ''}`)
    const attrs = [
      it.doorWidth ? `门幅:${it.doorWidth}` : '',
      it.sellingMethod ? `方式:${it.sellingMethod}` : '',
      it.width ? `宽:${it.width}m` : '',
      it.height ? `高:${it.height}m` : '',
      it.quantity != null ? `数量:${it.quantity}${it.unit ?? ''}` : '',
    ].filter(Boolean)
    if (attrs.length) lines.push(`  ${attrs.join('  ')}`)
    ;(it.processingItems ?? []).forEach((p) => {
      const opt = Array.isArray(p.options) && p.options.length ? `（${p.options.join('/')}）` : ''
      lines.push(`  加工：${p.name}${opt}${p.quantity != null ? ` × ${p.quantity}${p.unit ?? ''}` : ''}`)
    })
    if (it.remark) lines.push(`  备注：${it.remark}`)
    lines.push('')
  })
  if (po.remark) lines.push(`整体备注：${po.remark}`)
  if (po.cancelledReason) lines.push(`取消原因：${po.cancelledReason}`)
  return lines.join('\n')
}

export default function ProcessingOrderBlock({ orderId, orderStatus, hasProcessing }: Props) {
  const [po, setPo] = useState<ProcessingOrder | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState<null | { action: 'issue' | 'cancel'; processor?: string; date?: string; reason?: string }>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await processingOrderApi.detail(orderId)
      const data = res.data?.data ?? null
      setPo(data)
      setNotFound(!data)
    } catch {
      setNotFound(true)
      setPo(null)
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    if (orderId) load()
  }, [orderId, load])

  const canGenerate = notFound && hasProcessing && (orderStatus === 'confirmed' || orderStatus === 'producing')
  const canAct = po && !['completed', 'cancelled'].includes(po.status)

  const handleGenerate = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await processingOrderApi.generate([orderId])
      const r = res.data?.data?.[0]
      if (r?.success) {
        await load()
      } else {
        setError(r?.message ?? '生成失败')
      }
    } catch {
      setError('生成失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  const handleAction = async () => {
    if (!po || !form) return
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
      setPo(data ?? po)
      setForm(null)
    } catch {
      setError('操作失败，请确认加工单状态与填写内容')
    } finally {
      setBusy(false)
    }
  }

  const handleCopy = async () => {
    if (!po) return
    try {
      await navigator.clipboard.writeText(toPlainText(po))
    } catch {
      // 剪贴板不可用时退化为选中文本
      setError('复制失败，请手动选择文本复制')
    }
  }

  /** start/complete 简单流转（轻量 confirm 后直接调用） */
  const handleSimpleAction = async (action: 'start' | 'complete') => {
    if (!po) return
    const label = action === 'start' ? '开始加工' : '加工完成'
    if (!window.confirm(`确认将加工单 ${po.processingOrderNo} 标记为「${label}」？`)) return
    setBusy(true)
    setError('')
    try {
      const res = await processingOrderApi.update(po.id, { action })
      const data = res.data?.data
      setPo(data ?? po)
    } catch {
      setError('操作失败，请确认加工单状态')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-6">
      <style>{`
        @media print {
          body * { visibility: hidden; }
          .po-print-area, .po-print-area * { visibility: visible; }
          .po-print-area { position: absolute; left: 0; top: 0; width: 100%; }
          .po-no-print { display: none !important; }
        }
      `}</style>

      <div className="flex items-center justify-between po-no-print">
        <h3 className="text-base font-semibold text-neutral-900">加工单</h3>
        {po && (
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={handleCopy}>复制全部</Button>
            <Button variant="secondary" size="sm" onClick={() => window.print()}>打印</Button>
          </div>
        )}
      </div>

      {loading && <div className="py-4 text-sm text-neutral-400">加载中…</div>}

      {!loading && canGenerate && (
        <div className="mt-3 rounded-lg border border-primary-100 bg-primary-50/50 p-4">
          <p className="text-sm text-neutral-600">该订单含加工项，可生成加工单发给加工方（订单将进入「生产中」）。</p>
          <Button className="mt-3" size="sm" disabled={busy} onClick={handleGenerate}>
            {busy ? '生成中…' : '生成加工单'}
          </Button>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>
      )}

      {!loading && notFound && !canGenerate && (
        <p className="mt-2 text-sm text-neutral-400">该订单无加工单（无加工项订单无需加工环节）。</p>
      )}

      {po && (
        <div className="po-print-area mt-3 rounded-lg border border-neutral-200 p-4">
          {/* 头部 */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 pb-3">
            <div>
              <span className="text-lg font-semibold text-neutral-900">{po.processingOrderNo}</span>
              <span className="ml-2 rounded bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-700">
                {STATUS_TEXT[po.status] ?? po.status}
              </span>
            </div>
            <div className="text-sm text-neutral-500">
              {po.processor && <span className="mr-3">加工方：{po.processor}</span>}
              {po.expectedDeliveryDate && <span>交期：{po.expectedDeliveryDate}</span>}
            </div>
          </div>

          {/* 状态时间线 */}
          {po.status !== 'cancelled' && (
            <div className="mt-3 flex items-center gap-1 text-xs">
              {STEP_ORDER.map((s, i) => {
                const done = STEP_ORDER.indexOf(po.status) >= i
                return (
                  <span key={s} className="flex items-center gap-1">
                    <span className={`rounded-full px-2 py-0.5 ${done ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-400'}`}>
                      {STATUS_TEXT[s]}
                    </span>
                    {i < STEP_ORDER.length - 1 && <span className="text-neutral-300">→</span>}
                  </span>
                )
              })}
            </div>
          )}
          {po.status === 'cancelled' && po.cancelledReason && (
            <p className="mt-3 text-xs text-red-500">取消原因：{po.cancelledReason}</p>
          )}

          {/* 快照明细（不含销售价——决策 2） */}
          <div className="mt-3 space-y-3">
            {(po.items ?? []).map((it, idx) => (
              <div key={idx} className="rounded-md bg-neutral-50 p-3 text-sm">
                <div className="font-medium text-neutral-900">
                  {it.productName}
                  {it.colorName && <span className="ml-2 text-primary-600">{it.colorName}</span>}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {[
                    it.doorWidth && `门幅 ${it.doorWidth}`,
                    it.sellingMethod && `方式 ${it.sellingMethod}`,
                    it.width != null && `宽 ${it.width}m`,
                    it.height != null && `高 ${it.height}m`,
                    it.quantity != null && `数量 ${it.quantity}${it.unit ?? ''}`,
                  ].filter(Boolean).join(' · ')}
                </div>
                {(it.processingItems ?? []).length > 0 && (
                  <ul className="mt-1.5 space-y-0.5 text-xs text-amber-700">
                    {(it.processingItems ?? []).map((p, pi) => (
                      <li key={pi}>
                        加工：{p.name}
                        {Array.isArray(p.options) && p.options.length > 0 && `（${(p.options as string[]).join('/')}）`}
                        {p.quantity != null && ` × ${p.quantity}${p.unit ?? ''}`}
                      </li>
                    ))}
                  </ul>
                )}
                {it.remark && <div className="mt-1 text-xs text-neutral-500">备注：{it.remark}</div>}
              </div>
            ))}
          </div>
          {po.remark && <p className="mt-2 text-xs text-neutral-500">整体备注：{po.remark}</p>}

          {/* 操作区 */}
          <div className="po-no-print mt-4 flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-3">
            {canAct && po.status === 'generated' && (
              <Button size="sm" onClick={() => setForm({ action: 'issue' })}>发加工</Button>
            )}
            {canAct && po.status === 'issued' && (
              <Button size="sm" onClick={() => handleSimpleAction('start')}>开始加工</Button>
            )}
            {canAct && po.status === 'in_processing' && (
              <Button size="sm" onClick={() => handleSimpleAction('complete')}>加工完成</Button>
            )}
            {canAct && (
              <Button variant="secondary" size="sm" onClick={() => setForm({ action: 'cancel' })}>取消加工单</Button>
            )}
            {po.status === 'completed' && (
              <span className="text-xs text-green-600">加工已完成，可发货（发货需在订单物流中填写运单）</span>
            )}
            {error && <span className="text-xs text-red-500">{error}</span>}
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
                      placeholder="交期 yyyy-MM-dd"
                      value={form.date ?? ''}
                      onChange={(e) => setForm({ ...form, date: e.target.value })}
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={busy} onClick={handleAction}>确认发加工</Button>
                    <Button variant="secondary" size="sm" onClick={() => setForm(null)}>取消</Button>
                  </div>
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
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
