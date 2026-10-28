'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Input, Modal, PageCard, PageHeader, TableSkeleton } from '@/components/ui'
import SkuPicker, { type SkuPickerChoice, skuLineLabel } from '@/components/products/SkuPicker'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { supplierApi, purchaseOrderApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { displayEnum } from '@/lib/enum-display'
import type { PurchaseOrderStatus, PurchaseOrderView, Supplier } from '@/types'

/**
 * 采购单 `/purchase-orders`（issue #7369 段 4）。
 *
 * <h3>issue #7567：明细**只从选品器来**</h3>
 * <p>用户 2026-10-23 逐字：「你新增的采购单和作业单中的 sku 输入框是不能作为生产系统使用的」。
 * 改前建单弹窗里是一格 `<input placeholder="SKU">`，要商家手抄 ≈19 位雪花号（`2097126615461462018` 量级）；
 * 填错后端也不校验 SKU 是否存在 ⇒ 能落成一张全是垃圾行的采购单。改后与入库单/价格本共用
 * `components/products/SkuPicker`（选真实商品 → 勾真实 SKU），页面上**不存在**可手打 SKU 的输入框
 * （类级守卫：`tests/unit/sku-id-input-guard.test.ts`）。</p>
 *
 * <p>收货面同理：改前逐行只印 `skuId`（内部标识上屏），改后由服务端在读面里给
 * 商品名 / 货号 / 颜色 / 门幅（`PurchaseOrderView.ItemView`），前端只拼接、不切字符串。</p>
 */

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

type PurchaseItem = PurchaseOrderView['items'][number]

/**
 * 明细的展示名（issue #7567）—— 收货面**不许**印 `skuId`（≈19 位雪花号，商家认不出是哪块布）。
 * 有商品名 ⇒「商品 / 颜色 / 门幅」；只有货号 ⇒ 货号；都没有 ⇒ 如实说信息缺失（不编一个名字）。
 */
export function purchaseItemLabel(item: PurchaseItem): string {
  const named = [item.productName, item.colorName, item.doorWidth].filter(Boolean).join(' / ')
  if (named) return named
  return item.skuCode ? `货号 ${item.skuCode}` : '商品信息缺失'
}

/** 建单草稿的一行：勾 SKU 时就把展示名冻下来（提交只取 id 与数量/单价）。 */
type DraftLine = {
  skuId: string
  productId: string
  label: string
  quantity: string
  unitPrice: string
}

type CreateForm = {
  supplierId: string
  orderDate: string
  expectedDate: string
  remark: string
  lines: DraftLine[]
}

type ReceiveLine = {
  itemId: string
  skuId: string
  label: string
  remaining: number
  quantity: string
}

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
      lines: [],
    })
  }

  /** 勾选 SKU ⇒ 加一行 / 摘一行明细（issue #7567：明细**只能**从真实 SKU 里选出来）。 */
  const toggleLine = ({ product, sku }: SkuPickerChoice) => {
    setForm((prev) => {
      if (!prev) return prev
      if (prev.lines.some((l) => l.skuId === sku.id)) {
        return { ...prev, lines: prev.lines.filter((l) => l.skuId !== sku.id) }
      }
      return {
        ...prev,
        lines: [
          ...prev.lines,
          {
            skuId: sku.id,
            productId: product.id,
            label: skuLineLabel(product, sku),
            quantity: '',
            unitPrice: '',
          },
        ],
      }
    })
  }

  /** 行内「×」：按 skuId 摘掉这一行（勾选器只认它右栏里列出的 SKU，摘行这条出口单独给）。 */
  const removeLine = (skuId: string) => {
    setForm((prev) =>
      prev ? { ...prev, lines: prev.lines.filter((l) => l.skuId !== skuId) } : prev,
    )
  }

  const patchLine = (skuId: string, patch: Partial<DraftLine>) => {
    setForm((prev) =>
      prev ? { ...prev, lines: prev.lines.map((l) => (l.skuId === skuId ? { ...l, ...patch } : l)) } : prev,
    )
  }

  const submitCreate = async () => {
    if (!form) return
    if (!form.supplierId) {
      setFormError('请选择供应商')
      return
    }
    if (form.lines.length === 0) {
      setFormError('至少要有一行明细：在上面勾选一个 SKU 就加一行')
      return
    }
    if (form.lines.some((l) => !Number.isFinite(Number(l.quantity)) || Number(l.quantity) <= 0)) {
      setFormError('每行都要填大于 0 的数量')
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
        items: form.lines.map((l) => ({
          skuId: l.skuId,
          productId: l.productId,
          quantity: Number(l.quantity),
          unitPrice: Number(l.unitPrice || 0),
        })),
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
        .map((it) => ({
          itemId: it.id,
          skuId: it.skuId,
          label: purchaseItemLabel(it),
          remaining: it.remainingQuantity,
          quantity: '',
        })),
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
    const over = receiving.lines.find((l) => l.quantity && Number(l.quantity) > l.remaining)
    if (over) {
      setReceiveError(`「${over.label}」本次收货超过未收数量（可收 ${over.remaining}）`)
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
        {/* issue #8048：加载态 = 通用表格骨架（#8036 口径），与 8 列对齐；
            不再印裸「加载中…」+ 空白表体。
            🔴 只在**首次加载**（列表为空）出骨架：建单 / 收货 / 关单会触发刷新，
            刷新时已有读数 ⇒ 表格照旧在场（同 `quality-inspections` 的
            `recordsLoading && pagedRecords.length === 0` 口径）。 */}
        {loading && orders.length === 0 ? (
          <TableSkeleton rows={8} columns={8} />
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

      {/* 新建采购单：明细**只从选品器来**（issue #7567）—— 页面上不存在可手打 SKU 的输入框 */}
      <Modal
        open={form !== null}
        onClose={() => setForm(null)}
        title="新建采购单"
        width={920}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} loading={saving} data-testid="purchase-form-submit">
              {saving ? '提交中…' : '确认下单'}
            </Button>
          </>
        }
      >
        {form && (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-neutral-700 mb-1.5">供应商</label>
                <select
                  className={SELECT_CONTROL_FIELD}
                  data-testid="purchase-form-supplier"
                  value={form.supplierId}
                  onChange={(e) => setForm({ ...form, supplierId: e.target.value })}
                >
                  <option value="">请选择供应商</option>
                  {suppliers.map((s) => (
                    <option key={s.id} value={s.id} disabled={s.status === 'inactive'}>
                      {s.name}
                      {s.status === 'inactive' ? '（已停用）' : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="下单日"
                  type="date"
                  data-testid="purchase-form-order-date"
                  value={form.orderDate}
                  onChange={(e) => setForm({ ...form, orderDate: e.target.value })}
                />
                <Input
                  label="预计到货"
                  type="date"
                  data-testid="purchase-form-expected-date"
                  value={form.expectedDate}
                  onChange={(e) => setForm({ ...form, expectedDate: e.target.value })}
                />
              </div>
            </div>

            <div className="mt-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-neutral-700">明细</span>
                <span className="text-xs text-neutral-500">
                  共 {form.lines.length} 行；勾选商品规格即加一行，数量与单价在行内填
                </span>
              </div>
              <div className="mt-2">
                <SkuPicker
                  testIdPrefix="purchase"
                  title="勾选要采购的 SKU（勾选即加入明细，一行 = 一个采购项）"
                  selectedSkuIds={form.lines.map((l) => l.skuId)}
                  onToggle={toggleLine}
                />
              </div>

              {form.lines.length > 0 ? (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-neutral-50 text-neutral-600">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium whitespace-nowrap">商品 / 颜色 / 门幅</th>
                        <th className="text-right px-3 py-2 font-medium w-28 whitespace-nowrap">数量*</th>
                        <th className="text-right px-3 py-2 font-medium w-32 whitespace-nowrap">单价(元)</th>
                        <th className="w-12 whitespace-nowrap" />
                      </tr>
                    </thead>
                    <tbody>
                      {form.lines.map((l, idx) => (
                        <tr
                          key={l.skuId}
                          data-testid={`purchase-form-line-${l.skuId}`}
                          className="border-t border-neutral-100"
                        >
                          <td className="px-3 py-2 text-neutral-700">{l.label}</td>
                          <td className="px-3 py-2">
                            <Input
                              type="number"
                              min={0}
                              step={0.01}
                              aria-label={`${l.label} 数量`}
                              data-testid={`purchase-form-qty-${idx}`}
                              value={l.quantity}
                              onChange={(e) => patchLine(l.skuId, { quantity: e.target.value })}
                              className="h-9 px-2 text-sm text-right"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <Input
                              type="number"
                              min={0}
                              step="0.01"
                              aria-label={`${l.label} 单价`}
                              data-testid={`purchase-form-price-${idx}`}
                              value={l.unitPrice}
                              onChange={(e) => patchLine(l.skuId, { unitPrice: e.target.value })}
                              className="h-9 px-2 text-sm text-right"
                            />
                          </td>
                          <td className="px-3 py-2 text-right">
                            <button
                              type="button"
                              aria-label={`移除 ${l.label}`}
                              data-testid={`purchase-form-remove-${idx}`}
                              onClick={() => removeLine(l.skuId)}
                              className="text-neutral-400 hover:text-red-600 px-2"
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p
                  data-testid="purchase-form-empty"
                  className="mt-3 text-sm text-neutral-400 text-center py-4 border border-dashed border-neutral-200 rounded-lg"
                >
                  还没有明细：在上面搜商品 → 勾选规格即加入
                </p>
              )}
            </div>

            <div className="mt-4">
              <label className="block text-sm font-medium text-neutral-700 mb-1.5">备注</label>
              <textarea
                rows={2}
                data-testid="purchase-form-remark"
                className="w-full px-3 py-2 rounded-lg border border-neutral-300 bg-white text-sm leading-relaxed resize-none placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                value={form.remark}
                onChange={(e) => setForm({ ...form, remark: e.target.value })}
                placeholder="可填交货要求、包装方式等（选填）"
              />
            </div>

            {formError && (
              <div className="mt-3 text-sm text-red-600" role="alert">
                {formError}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={closing !== null}
        onClose={() => setClosing(null)}
        title={closing ? `关闭采购单 · ${closing.order.poNo}` : '关闭采购单'}
        width={460}
        footer={
          <>
            <Button variant="secondary" onClick={() => setClosing(null)}>
              取消
            </Button>
            <Button onClick={() => void submitClose()} loading={saving} data-testid="purchase-close-submit">
              {saving ? '提交中…' : '确认关闭'}
            </Button>
          </>
        }
      >
        {closing && (
          <div>
            <p className="text-xs text-neutral-500 mb-3">
              关闭后这张单不能再收货，也不会被删 —— 原因留着备查（断货 / 取消 / 到不齐）。
            </p>
            <Input
              placeholder="关闭原因"
              data-testid="purchase-close-reason"
              value={closing.reason}
              onChange={(e) => setClosing({ ...closing, reason: e.target.value })}
            />
            {closeError && (
              <div className="mt-3 text-sm text-red-600" role="alert">
                {closeError}
              </div>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={receiving !== null}
        onClose={() => setReceiving(null)}
        title={receiving ? `登记收货 · ${receiving.order.poNo}` : '登记收货'}
        width={720}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReceiving(null)}>
              取消
            </Button>
            <Button onClick={() => void submitReceive()} loading={saving} data-testid="purchase-receive-submit">
              {saving ? '提交中…' : '确认收货'}
            </Button>
          </>
        }
      >
        {receiving && (
          <div>
            <p className="text-xs text-neutral-500 mb-3">
              填这次实际到了多少；本次不能超过「未收数量」。收齐后状态自动变「已收齐」，差一行就差整单。
            </p>
            <div className="space-y-2">
              {receiving.lines.map((line, idx) => (
                <div key={line.itemId} className="flex items-center gap-3">
                  <span className="flex-1 min-w-0 text-sm">
                    {line.label}
                    <span className="ml-2 text-xs text-neutral-500 whitespace-nowrap">未收 {line.remaining}</span>
                  </span>
                  {/* ⚠️ 宽度必须加在**包裹层**：`Input` 的 className 透传到 `<input>`，而它的外层是
                      `w-full` ⇒ 直接把 w-28 给 Input 会让外层吃满整行，把左侧商品名挤成一字一行
                      （2026-10-23 本地截图验收实测，长 CJK 名称当场折成竖排）。 */}
                  <div className="w-28 shrink-0">
                    <Input
                      className="h-9 px-2 text-sm"
                      placeholder="本次"
                      aria-label={`${line.label} 本次收货数量`}
                      data-testid={`purchase-receive-qty-${line.skuId}`}
                      value={line.quantity}
                      onChange={(e) => {
                        const lines = [...receiving.lines]
                        lines[idx] = { ...line, quantity: e.target.value }
                        setReceiving({ ...receiving, lines })
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <label className="block text-sm font-medium text-neutral-700 mt-4 mb-1.5">
              备注（缺货说明写这里）
            </label>
            <Input
              data-testid="purchase-receive-remark"
              value={receiving.remark}
              onChange={(e) => setReceiving({ ...receiving, remark: e.target.value })}
            />
            {receiveError && (
              <div className="mt-3 text-sm text-red-600" role="alert">
                {receiveError}
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
