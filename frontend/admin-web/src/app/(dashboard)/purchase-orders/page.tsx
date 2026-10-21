'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, PageCard, PageHeader } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { supplierApi, purchaseOrderApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { displayEnum } from '@/lib/enum-display'
import type { PurchaseOrderStatus, PurchaseOrderView, Supplier } from '@/types'

/** 状态上屏文案（后端派生，前端只翻译）。 */
const STATUS_LABEL: Record<PurchaseOrderStatus, string> = {
  ordered: '待收货',
  partially_received: '部分收货',
  received: '已收齐',
  closed: '已关闭',
}

/** 状态徽标配色：只区分「进行中 / 完成 / 关闭」，不按颜色堆语义。 */
const STATUS_CLASS: Record<PurchaseOrderStatus, string> = {
  ordered: 'bg-primary-50 text-primary-700',
  partially_received: 'bg-amber-50 text-amber-700',
  received: 'bg-emerald-50 text-emerald-700',
  closed: 'bg-neutral-100 text-neutral-500',
}

export function purchaseStatusLabel(status: PurchaseOrderStatus): string {
  // 出口安全（issue #6668）：未登记的枚举值给人话「其他」，绝不把服务端标识直接印上屏
  return displayEnum(STATUS_LABEL, status)
}

/** 金额上屏：两位小数；非法值一律 0.00（不显示 NaN）。 */
function formatAmount(value: number | null | undefined): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return n.toFixed(2)
}

type CreateForm = {
  supplierId: string
  orderDate: string
  expectedDate: string
  remark: string
  lines: { skuId: string; quantity: string; unitPrice: string }[]
}

type ReceiveLine = { itemId: string; quantity: string; skuId: string; remaining: number }

export default function PurchaseOrdersPage() {
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('inbound:create')

  const [orders, setOrders] = useState<PurchaseOrderView[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [form, setForm] = useState<CreateForm | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [receiving, setReceiving] = useState<{ order: PurchaseOrderView; lines: ReceiveLine[]; remark: string } | null>(null)
  const [receiveError, setReceiveError] = useState<string | null>(null)
  const [closing, setClosing] = useState<{ order: PurchaseOrderView; reason: string } | null>(null)
  const [closeError, setCloseError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await purchaseOrderApi.list()
      setOrders(res.data.data || [])
    } catch (error) {
      console.error('加载采购单失败:', error)
      // 失败态要说清**为什么**（403 没权限 / 500 服务端炸 / 断网 是三种处境，不能同一句话）
      setLoadError(loadErrorMessage(error, '采购单加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadSuppliers = useCallback(async () => {
    try {
      const res = await supplierApi.list()
      setSuppliers(res.data.data || [])
    } catch (error) {
      // 供应商只是建单时的选项：拉不到就让建单入口给出可行动提示，不影响列表可读
      setSuppliers([])
      console.error('加载供应商失败:', error)
    }
  }, [])

  useEffect(() => {
    load()
    loadSuppliers()
  }, [load, loadSuppliers])

  const openCreate = () => {
    setFormError(null)
    setForm({
      supplierId: suppliers.find((s) => s.status === 'active')?.id || '',
      orderDate: '',
      expectedDate: '',
      remark: '',
      lines: [{ skuId: '', quantity: '', unitPrice: '' }],
    })
  }

  const submitCreate = async () => {
    if (!form) return
    const lines = form.lines
      .filter((l) => l.skuId.trim() || l.quantity || l.unitPrice)
      .map((l) => ({
        skuId: l.skuId.trim(),
        quantity: Number(l.quantity),
        unitPrice: Number(l.unitPrice || 0),
      }))
    if (!form.supplierId) {
      setFormError('请选择供应商')
      return
    }
    if (lines.length === 0) {
      setFormError('至少要有一行明细')
      return
    }
    if (lines.some((l) => !l.skuId || !Number.isFinite(l.quantity) || l.quantity <= 0)) {
      setFormError('每行都要填 SKU 与大于 0 的数量')
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      await purchaseOrderApi.create({
        supplierId: form.supplierId,
        orderDate: form.orderDate || null,
        expectedDate: form.expectedDate || null,
        remark: form.remark || null,
        items: lines,
      })
      setForm(null)
      await load()
    } catch (error) {
      const err = error as { response?: { data?: { message?: string } } }
      setFormError(err.response?.data?.message || '建单失败')
    } finally {
      setSaving(false)
    }
  }

  const openReceive = (order: PurchaseOrderView) => {
    setReceiveError(null)
    setReceiving({
      order,
      remark: '',
      // 默认只列还没收齐的行（收齐的行不该再出现在收货面上）
      lines: order.items
        .filter((it) => it.remainingQuantity > 0)
        .map((it) => ({ itemId: it.id, skuId: it.skuId, remaining: it.remainingQuantity, quantity: '' })),
    })
  }

  const submitReceive = async () => {
    if (!receiving) return
    const lines = receiving.lines
      .filter((l) => l.quantity)
      .map((l) => ({ itemId: l.itemId, quantity: Number(l.quantity) }))
    if (lines.length === 0) {
      setReceiveError('至少要填一行收货数量')
      return
    }
    if (lines.some((l) => !Number.isFinite(l.quantity) || l.quantity <= 0)) {
      setReceiveError('收货数量必须大于 0')
      return
    }
    const over = receiving.lines.find(
      (l) => l.quantity && Number(l.quantity) > l.remaining,
    )
    if (over) {
      setReceiveError(`${over.skuId} 本次收货超过未收数量（可收 ${over.remaining}）`)
      return
    }
    setSaving(true)
    setReceiveError(null)
    try {
      await purchaseOrderApi.receive(receiving.order.id, {
        remark: receiving.remark || null,
        lines,
      })
      setReceiving(null)
      await load()
    } catch (error) {
      const err = error as { response?: { data?: { message?: string } } }
      setReceiveError(err.response?.data?.message || '登记收货失败')
    } finally {
      setSaving(false)
    }
  }

  const submitClose = async () => {
    if (!closing) return
    const reason = closing.reason.trim()
    if (!reason) {
      setCloseError('请写关闭原因（断货 / 取消 / 到不齐都要留一句）')
      return
    }
    setSaving(true)
    setCloseError(null)
    try {
      await purchaseOrderApi.close(closing.order.id, reason)
      setClosing(null)
      await load()
    } catch (error) {
      const err = error as { response?: { data?: { message?: string } } }
      setCloseError(err.response?.data?.message || '关闭失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    // 与全站页面对齐的外边距（其余页面同款 `p-6`）：缺了它内容会贴着侧边栏，
    // 标题、按钮、卡片三者不在同一条网格上（观感就是「页面是歪的」）。
    <div className="p-6">
      <PageHeader
        title="采购单"
        subtitle="下单、分次收货、关闭都在这一页；已收和未收按收货记录实时算"
        actions={
          canWrite ? (
            <Button onClick={openCreate} data-testid="purchase-create">
              新建采购单
            </Button>
          ) : null
        }
      />

      {loadError && <ListLoadError message={loadError} onRetry={load} testId="purchase-orders-load-error" />}

      <PageCard className="mt-4">
        {loading ? (
          <div className="text-sm text-neutral-500" data-testid="purchase-orders-loading">加载中…</div>
        ) : loadError ? (
          // 失败态已经在上面的 ListLoadError 里给出：这里**不许**再画「还没有采购单」——
          // 那是业务结论（真的一张都没有），拿它冒充加载失败会让商家以为单子丢了。
          null
        ) : orders.length === 0 ? (
          <div className="text-sm text-neutral-500" data-testid="purchase-orders-empty">
            {canWrite ? '还没有采购单 —— 点右上角「新建采购单」开始' : '还没有采购单'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="purchase-table">
              <thead>
                <tr className="text-left text-neutral-500 border-b border-neutral-100">
                  <th className="py-2 font-normal whitespace-nowrap">单号</th>
                  <th className="py-2 font-normal whitespace-nowrap">供应商</th>
                  <th className="py-2 font-normal whitespace-nowrap">下单日</th>
                  <th className="py-2 font-normal whitespace-nowrap">预计到货</th>
                  <th className="py-2 font-normal whitespace-nowrap">状态</th>
                  <th className="py-2 font-normal whitespace-nowrap">收货进度</th>
                  <th className="py-2 font-normal whitespace-nowrap text-right">金额</th>
                  <th className="py-2 font-normal whitespace-nowrap text-right sticky right-0 bg-white">操作</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const total = o.items.reduce((sum, it) => sum + it.quantity, 0)
                  const received = o.items.reduce((sum, it) => sum + it.receivedQuantity, 0)
                  return (
                    <tr key={o.id} className="border-b border-neutral-50" data-testid={`purchase-row-${o.poNo}`}>
                      <td className="py-2 whitespace-nowrap font-medium">{o.poNo}</td>
                      <td className="py-2 whitespace-nowrap">{o.supplierName || '—'}</td>
                      <td className="py-2 whitespace-nowrap text-neutral-500">{o.orderDate}</td>
                      <td className="py-2 whitespace-nowrap text-neutral-500">{o.expectedDate || '—'}</td>
                      <td className="py-2 whitespace-nowrap">
                        <span className={`px-2 py-0.5 rounded text-xs ${STATUS_CLASS[o.status]}`}>
                          {purchaseStatusLabel(o.status)}
                        </span>
                        {o.closedReason && (
                          <span className="ml-2 text-xs text-neutral-400">{o.closedReason}</span>
                        )}
                      </td>
                      <td className="py-2 whitespace-nowrap text-neutral-600">
                        {received} / {total}
                      </td>
                      <td className="py-2 whitespace-nowrap text-right">¥{formatAmount(o.totalAmount)}</td>
                      <td className="py-2 whitespace-nowrap text-right sticky right-0 bg-white">
                        {canWrite ? (
                          <>
                            <button
                              className="text-primary-600 hover:underline mr-3"
                              data-testid={`purchase-receive-${o.poNo}`}
                              disabled={o.status === 'received' || o.status === 'closed'}
                              onClick={() => openReceive(o)}
                            >
                              收货
                            </button>
                            <button
                              className="text-neutral-500 hover:underline"
                              data-testid={`purchase-close-${o.poNo}`}
                              disabled={o.status === 'received' || o.status === 'closed'}
                              onClick={() => {
                                setCloseError(null)
                                setClosing({ order: o, reason: '' })
                              }}
                            >
                              关闭
                            </button>
                          </>
                        ) : (
                          <span className="text-xs text-neutral-400">只读</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </PageCard>

      {form && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-5 w-[560px] max-h-[80vh] overflow-y-auto">
            <h3 className="text-base font-medium mb-3">新建采购单</h3>

            <label className="block text-sm mb-1">供应商</label>
            <select
              className={`w-full mb-3 ${SELECT_CONTROL_FIELD}`}
              data-testid="purchase-form-supplier"
              value={form.supplierId}
              onChange={(e) => setForm({ ...form, supplierId: e.target.value })}
            >
              <option value="">请选择供应商</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id} disabled={s.status === 'inactive'}>
                  {s.name}{s.status === 'inactive' ? '（已停用）' : ''}
                </option>
              ))}
            </select>

            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-sm mb-1">下单日</label>
                <input
                  type="date"
                  className="w-full border border-neutral-200 rounded px-3 py-2"
                  data-testid="purchase-form-order-date"
                  value={form.orderDate}
                  onChange={(e) => setForm({ ...form, orderDate: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm mb-1">预计到货</label>
                <input
                  type="date"
                  className="w-full border border-neutral-200 rounded px-3 py-2"
                  data-testid="purchase-form-expected-date"
                  value={form.expectedDate}
                  onChange={(e) => setForm({ ...form, expectedDate: e.target.value })}
                />
              </div>
            </div>

            <label className="block text-sm mb-1">明细</label>
            {form.lines.map((line, idx) => (
              <div key={idx} className="grid grid-cols-[1fr_90px_90px_40px] gap-2 mb-2">
                <input
                  className="border border-neutral-200 rounded px-3 py-2"
                  placeholder="SKU"
                  data-testid={`purchase-form-sku-${idx}`}
                  value={line.skuId}
                  onChange={(e) => {
                    const lines = [...form.lines]
                    lines[idx] = { ...line, skuId: e.target.value }
                    setForm({ ...form, lines })
                  }}
                />
                <input
                  className="border border-neutral-200 rounded px-3 py-2"
                  placeholder="数量"
                  data-testid={`purchase-form-qty-${idx}`}
                  value={line.quantity}
                  onChange={(e) => {
                    const lines = [...form.lines]
                    lines[idx] = { ...line, quantity: e.target.value }
                    setForm({ ...form, lines })
                  }}
                />
                <input
                  className="border border-neutral-200 rounded px-3 py-2"
                  placeholder="单价"
                  data-testid={`purchase-form-price-${idx}`}
                  value={line.unitPrice}
                  onChange={(e) => {
                    const lines = [...form.lines]
                    lines[idx] = { ...line, unitPrice: e.target.value }
                    setForm({ ...form, lines })
                  }}
                />
                <button
                  className="text-neutral-400 hover:text-red-600"
                  data-testid={`purchase-form-remove-${idx}`}
                  onClick={() => setForm({ ...form, lines: form.lines.filter((_, i) => i !== idx) })}
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              className="text-sm text-primary-600 hover:underline mb-3"
              data-testid="purchase-form-add-line"
              onClick={() => setForm({ ...form, lines: [...form.lines, { skuId: '', quantity: '', unitPrice: '' }] })}
            >
              + 加一行
            </button>

            <label className="block text-sm mb-1">备注</label>
            <textarea
              className="w-full border border-neutral-200 rounded px-3 py-2 mb-3"
              data-testid="purchase-form-remark"
              value={form.remark}
              onChange={(e) => setForm({ ...form, remark: e.target.value })}
            />

            {formError && <div className="text-sm text-red-600 mb-2" role="alert">{formError}</div>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setForm(null)}>取消</Button>
              <Button onClick={submitCreate} disabled={saving} data-testid="purchase-form-submit">
                {saving ? '提交中…' : '确认下单'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {closing && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-5 w-[420px]">
            <h3 className="text-base font-medium mb-1">关闭采购单 · {closing.order.poNo}</h3>
            <p className="text-xs text-neutral-500 mb-3">
              关闭后这张单不能再收货，也不会被删 —— 原因留着备查（断货 / 取消 / 到不齐）。
            </p>
            <input
              className="w-full border border-neutral-200 rounded px-3 py-2 mb-3"
              placeholder="关闭原因"
              data-testid="purchase-close-reason"
              value={closing.reason}
              onChange={(e) => setClosing({ ...closing, reason: e.target.value })}
            />
            {closeError && <div className="text-sm text-red-600 mb-2" role="alert">{closeError}</div>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setClosing(null)}>取消</Button>
              <Button onClick={submitClose} disabled={saving} data-testid="purchase-close-submit">
                {saving ? '提交中…' : '确认关闭'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {receiving && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-5 w-[520px]">
            <h3 className="text-base font-medium mb-1">登记收货 · {receiving.order.poNo}</h3>
            <p className="text-xs text-neutral-500 mb-3">
              填这次实际到了多少；本次不能超过「未收数量」。收齐后状态自动变「已收齐」，差一行就差整单。
            </p>
            {receiving.lines.map((line, idx) => (
              <div key={line.itemId} className="flex items-center gap-2 mb-2">
                <span className="flex-1 text-sm">
                  {line.skuId}
                  <span className="ml-2 text-xs text-neutral-500">未收 {line.remaining}</span>
                </span>
                <input
                  className="w-28 border border-neutral-200 rounded px-3 py-2"
                  placeholder="本次"
                  data-testid={`purchase-receive-qty-${line.skuId}`}
                  value={line.quantity}
                  onChange={(e) => {
                    const lines = [...receiving.lines]
                    lines[idx] = { ...line, quantity: e.target.value }
                    setReceiving({ ...receiving, lines })
                  }}
                />
              </div>
            ))}
            <label className="block text-sm mb-1 mt-2">备注（缺货说明写这里）</label>
            <input
              className="w-full border border-neutral-200 rounded px-3 py-2 mb-3"
              data-testid="purchase-receive-remark"
              value={receiving.remark}
              onChange={(e) => setReceiving({ ...receiving, remark: e.target.value })}
            />
            {receiveError && <div className="text-sm text-red-600 mb-2" role="alert">{receiveError}</div>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setReceiving(null)}>取消</Button>
              <Button onClick={submitReceive} disabled={saving} data-testid="purchase-receive-submit">
                {saving ? '提交中…' : '确认收货'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
