'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { batchStockApi, processingOrderApi } from '@/lib/api'
// 工艺规格展示的单一真值定义（设计文档 §4.9「一份 spec，三处渲染」）
import { craftSpecLine, craftSpecRows } from '@/lib/craft-display'
// 状态文案单一来源：与列表页共用（加工单状态机语义见 lib/processing-order.ts）
import { PROCESSING_ORDER_STATUS_LABELS as STATUS_TEXT } from '@/lib/processing-order'
// 米数展示口径（0.1 米粒度、去尾随 .0）—— 与库存/批次账同一份工具
import { formatStockQuantity } from '@/lib/stock-quantity'
import type {
  BatchCandidate,
  OrderItem,
  ProcessingOrder,
  ProcessingOrderGenerateBatch,
  ProcessingOrderItem,
} from '@/types'

interface Props {
  orderId: string
  orderStatus: string
  /** 订单是否含加工项（由父组件从明细判断） */
  hasProcessing: boolean
  /**
   * 订单明细（订单详情页已有数据）：生成加工单时据此取**逐面料行的派工候选**
   * （V116 / issue #5145 阶段 1）。缺省/空 ⇒ 该单无从指派批次，直接按原路径生成。
   */
  items?: OrderItem[]
  /** 加工单状态上报（issue #3889）：详情页据此守卫「含加工项且加工单未完成」的发货入口 */
  onStatusChange?: (po: ProcessingOrder | null) => void
}

const STEP_ORDER: ProcessingOrder['status'][] = ['generated', 'issued', 'in_processing', 'completed']

function formatAmount(v?: number): string {
  if (v == null) return '—'
  return String(v)
}

/** 本地时区今天（yyyy-MM-dd）：发加工交期 date 控件 min 与防御校验同口径（issue #3901） */
function todayLocal(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

// ══════════════════════════════════════════════════════════════════════════════
// 派工指定批次（V116 / issue #5145 阶段 1）：系统给候选 + 建议值，文员确认、可改
// ══════════════════════════════════════════════════════════════════════════════

/** 可派工的面料行（来源 = 订单明细，非发明字段） */
interface AssignSource {
  /** = `order_items.id` = 加工单快照行的 `itemId`（后端据此认行） */
  itemId: string
  productId: string
  skuId?: number
  label: string
  /** 行米数（后端按「向上进位到 0.1」判余量是否够） */
  meters: number
}

/** 对话框里的一行（= 一个面料行 + 它的候选批次） */
interface AssignRow extends Omit<AssignSource, 'productId' | 'skuId'> {
  /** 候选批次（含余量不够的：列出来但**不可选**，免得选到必被后端拒的那一批） */
  candidates: BatchCandidate[]
  /** 可选项（余量够本行）；空 ⇒ 本行不指派 */
  selectable: BatchCandidate[]
  /** 不可指派的原因（无候选 / 缺 SKU 标识 / 查询失败） */
  reason?: string
}

/**
 * 订单明细 → 可派工的面料行。行筛选与后端 `ProcessingOrderService.buildSnapshot` **同口径**
 * （前端多列一行会让后端整批拒；少列一行则文员无法指派）：有加工项的行 + 卖布行（`saleForm=布料`）。
 */
function assignSourcesOf(items: OrderItem[]): AssignSource[] {
  const rows: AssignSource[] = []
  for (const it of items) {
    const info = (it.processingInfo ?? {}) as Record<string, unknown>
    const procs = Array.isArray(info.processingItems) ? info.processingItems : []
    if (procs.length === 0 && info.saleForm !== '布料') continue
    const meters = Number(it.quantity)
    const skuId = Number(info.skuId)
    if (!it.id || !it.productId || !Number.isFinite(meters) || meters <= 0) continue
    const color = info.colorName ?? it.color
    rows.push({
      itemId: it.id,
      productId: it.productId,
      skuId: Number.isInteger(skuId) && skuId > 0 ? skuId : undefined,
      label: `${it.productName ?? ''}${color ? `（${color}）` : ''}`,
      meters,
    })
  }
  return rows
}

/** 候选下拉的选项文案：批次号 + 剩余米数 + 收货日期（余量不够本行的显式标注） */
function candidateLabel(c: BatchCandidate): string {
  const date = c.receivedDate ? `收货 ${c.receivedDate}` : '收货日期未记'
  return `${c.batchNo}（余 ${formatStockQuantity(c.remainingMeters)} 米 · ${date}${c.enough ? '' : ' · 不足本行'}）`
}

/** 默认选中后端建议值；建议值缺席/不够本行时回落到候选首位（FIFO 序由后端给） */
function defaultPickOf(row: AssignRow): string {
  const suggested = row.candidates.find((c) => c.suggested && c.enough)
  return (suggested ?? row.selectable[0])?.batchNo ?? ''
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
    // 工艺规格（issue #4355 / 设计文档 §4.9 ③）：加工方拿到的文本必须带工艺，否则车间按老习惯做
    const specRows = craftSpecRows(it)
    if (specRows.length) lines.push(`  工艺规格：${specRows.map(craftSpecLine).join('  ')}`)
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

export default function ProcessingOrderBlock({ orderId, orderStatus, hasProcessing, items, onStatusChange }: Props) {
  const [po, setPo] = useState<ProcessingOrder | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState<null | { action: 'issue' | 'cancel'; processor?: string; date?: string; reason?: string }>(null)
  const [error, setError] = useState('')
  /** 生成失败时后端给的可行动建议（原样展示，与 message 分行 —— 缺料 fail-closed 的落点） */
  const [errorHint, setErrorHint] = useState('')
  /** 批次指派对话框；null = 未打开（一行都指派不了时**不开**，直接按原路径生成） */
  const [assign, setAssign] = useState<AssignRow[] | null>(null)
  const [picks, setPicks] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await processingOrderApi.detail(orderId)
      const data = res.data?.data ?? null
      setPo(data)
      setNotFound(!data)
      onStatusChange?.(data)
    } catch {
      setNotFound(true)
      setPo(null)
      onStatusChange?.(null)
    } finally {
      setLoading(false)
    }
  }, [orderId, onStatusChange])

  useEffect(() => {
    if (orderId) load()
  }, [orderId, load])

  const canGenerate = notFound && hasProcessing && (orderStatus === 'confirmed' || orderStatus === 'producing')
  const canAct = po && !['completed', 'cancelled'].includes(po.status)

  /** 取本单各面料行的派工候选（逐行独立；取不到 ⇒ 该行不指派，**绝不猜**候选） */
  const loadAssignRows = useCallback(async (): Promise<AssignRow[]> => {
    return Promise.all(
      assignSourcesOf(items ?? []).map(async (s): Promise<AssignRow> => {
        const base = { itemId: s.itemId, label: s.label, meters: s.meters }
        // 明细没记 SKU ⇒ 候选无法定位到具体 SKU（会串色/串门幅），本行不指派
        if (s.skuId == null) {
          return { ...base, candidates: [], selectable: [], reason: '明细未记录 SKU，无法核对批次归属' }
        }
        try {
          const res = await batchStockApi.candidates({
            productId: s.productId,
            skuId: s.skuId,
            meters: s.meters,
          })
          const candidates = res.data?.data?.candidates ?? []
          const selectable = candidates.filter((c) => c.enough)
          return selectable.length > 0
            ? { ...base, candidates, selectable }
            : { ...base, candidates, selectable, reason: '现有批次余量都不够本行' }
        } catch {
          return { ...base, candidates: [], selectable: [], reason: '候选批次查询失败' }
        }
      }),
    )
  }, [items])

  /** 生成加工单（可带逐行批次指派）：失败时 message + suggestion 原样展示 */
  const submitGenerate = async (batches: ProcessingOrderGenerateBatch[]) => {
    setBusy(true)
    setError('')
    setErrorHint('')
    try {
      // 没有指派任何行 ⇒ **单参调用**：请求体只有 orderIds，行为与今天逐字相同
      const res = batches.length > 0
        ? await processingOrderApi.generate([orderId], batches)
        : await processingOrderApi.generate([orderId])
      const r = res.data?.data?.[0]
      if (r?.success) {
        setAssign(null)
        await load()
      } else {
        setError(r?.message ?? '生成失败')
        // 后端建议**逐字转发**（不改写、不吞掉）
        setErrorHint(r?.suggestion ?? '')
      }
    } catch {
      setError('生成失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  /**
   * 点「生成加工单」：先取候选 —— 有可指派的行 ⇒ 让文员确认/改选批次；
   * **一行都指派不了**（无候选 / 无 SKU 标识 / 查不到）⇒ 不弹空对话框挡路，按原路径生成。
   */
  const handleGenerate = async () => {
    setBusy(true)
    setError('')
    setErrorHint('')
    // 取候选失败 ⇒ 各行按「不可指派」处理（回落到原路径生成，绝不因候选查询把生成卡住）
    const rows = await loadAssignRows().catch(() => [] as AssignRow[])
    setBusy(false)
    if (!rows.some((r) => r.selectable.length > 0)) {
      await submitGenerate([])
      return
    }
    setPicks(Object.fromEntries(rows.map((r) => [r.itemId, defaultPickOf(r)])))
    setAssign(rows)
  }

  /** 确认指派：没选批次的行**不进** batches（= 该行不指派、不扣批次库存） */
  const confirmAssign = () => {
    const batches: ProcessingOrderGenerateBatch[] = (assign ?? [])
      .map((r) => ({ orderId, itemId: r.itemId, batchNo: picks[r.itemId] ?? '' }))
      .filter((b) => b.batchNo !== '')
    submitGenerate(batches)
  }

  const handleAction = async () => {
    if (!po || !form) return
    // issue #3901：交期不允许早于今天（date 控件 min 之外的双保险，兜住非控件路径）
    if (form.action === 'issue' && form.date && form.date < todayLocal()) {
      setError('交付日期不能早于今天')
      return
    }
    setBusy(true)
    setError('')
    setErrorHint('')
    try {
      const res = await processingOrderApi.update(po.id, {
        action: form.action,
        processor: form.processor,
        expectedDeliveryDate: form.date,
        reason: form.reason,
      })
      const data = res.data?.data
      setPo(data ?? po)
      onStatusChange?.(data ?? po)
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
    setErrorHint('')
    try {
      const res = await processingOrderApi.update(po.id, { action })
      const data = res.data?.data
      setPo(data ?? po)
      onStatusChange?.(data ?? po)
    } catch {
      setError('操作失败，请确认加工单状态')
    } finally {
      setBusy(false)
    }
  }

  /** 失败提示：message（后端逐字）+ suggestion（后端逐字，分行） */
  const errorBlock = (
    <>
      <p className="text-xs text-red-500">{error}</p>
      {errorHint && <p className="mt-1 text-xs text-amber-700">{errorHint}</p>}
    </>
  )

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
          {/* 对话框开着时失败提示在对话框里（两处只会有一处可见，避免同一句话出现两遍） */}
          {error && !assign && <div className="mt-2">{errorBlock}</div>}
        </div>
      )}

      {!loading && notFound && !canGenerate && (
        <p className="mt-2 text-sm text-neutral-400">该订单无加工单（无加工项订单无需加工环节）。</p>
      )}

      {/* 批次指派（issue #5145 阶段 1）：系统按 FIFO 给建议值，文员可改；不选的行不指派 */}
      <Modal
        open={assign !== null}
        onClose={() => setAssign(null)}
        title="选择批次"
        width={720}
        footer={
          <>
            {error && <div className="mr-auto">{errorBlock}</div>}
            <Button variant="secondary" onClick={() => setAssign(null)}>取消</Button>
            <Button disabled={busy} onClick={confirmAssign}>{busy ? '生成中…' : '确认生成'}</Button>
          </>
        }
      >
        <p className="mb-3 text-xs text-neutral-500">
          每行面料从哪一批裁由你定：系统按「入库日期早者优先」给建议值，可自行改选；
          选「不指派」的行不扣批次库存（余量不够本行的批次不可选）。
        </p>
        <div className="space-y-3">
          {(assign ?? []).map((row) => (
            <div key={row.itemId} className="rounded-md border border-neutral-200 bg-neutral-50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium text-neutral-900">{row.label}</span>
                <span className="text-xs text-neutral-500">{formatStockQuantity(row.meters)} 米</span>
              </div>
              {row.selectable.length > 0 ? (
                <select
                  data-testid={`batch-select-${row.itemId}`}
                  aria-label={`${row.label}批次`}
                  className="mt-2 w-full rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm"
                  value={picks[row.itemId] ?? ''}
                  onChange={(e) => setPicks({ ...picks, [row.itemId]: e.target.value })}
                >
                  <option value="">不指派（不扣批次库存）</option>
                  {row.candidates.map((c) => (
                    <option key={c.batchNo} value={c.batchNo} disabled={!c.enough}>
                      {candidateLabel(c)}
                    </option>
                  ))}
                </select>
              ) : (
                <p data-testid={`batch-unavailable-${row.itemId}`} className="mt-2 text-xs text-amber-700">
                  无可用批次 —— {row.reason ?? '该 SKU 没有可用批次'}
                </p>
              )}
            </div>
          ))}
        </div>
      </Modal>

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
            {(po.items ?? []).map((it, idx) => {
              // 工艺规格（issue #4355 / 设计文档 §4.9 ③）：渲染快照里固化的那一份，缺值行已丢弃
              const specRows = craftSpecRows(it)
              return (
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
                {/* 工艺规格：无任何工艺键（存量单）时整块不出现 */}
                {specRows.length > 0 && (
                  <div className="mt-1.5 space-y-0.5" data-testid="po-item-craft-spec">
                    <div className="text-xs font-medium text-neutral-600">工艺规格</div>
                    {specRows.map((row) => (
                      <div key={row.label} className="flex flex-wrap gap-x-2 text-xs">
                        <span className="text-neutral-400">{row.label}</span>
                        <span className="text-neutral-700">{row.value}</span>
                      </div>
                    ))}
                  </div>
                )}
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
              )
            })}
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
            {error && !assign && <div>{errorBlock}</div>}
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
