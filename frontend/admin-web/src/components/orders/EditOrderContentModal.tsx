'use client'

/**
 * 「修改订单」弹窗（issue #5842；用户 2026-10-01 裁定「买家未付款的订单要允许修改」）。
 *
 * 入口 = 订单详情页（**仅「待付款」状态**显示按钮 —— 与后端
 * `OrderStatusTransitions.assertContentEditable` 同一口径：只有 pending 可改，
 * 其余状态后端 422）。可改三面：
 *
 * 1. **收货信息**（收货人 / 联系电话 / 收货地址）；
 * 2. **商品明细**（商品名 / 数量 / 单价 / 宽 / 高；可增删行）；
 * 3. **加工项**（每一行：加工项目录里勾选 + 19 项特殊选项）。
 *
 * ## 金额：本组件**只展示**，不提交
 *
 * 🔴 请求体里没有 `subtotal` / `totalAmount`（见 `OrderContentUpdateParams`）——
 * 金额一律由服务端按新明细 + 新加工项重算。页面上那行「商品金额合计」是**给人看的估算**
 * （Σ 数量 × 单价），**不是**订单应收（应收还含加工费），所以它逐字标着「以保存后系统计算为准」，
 * 命名也不叫「应收」——用界面上一个算不准的数冒充权威金额，正是本单要避免的那类静默错账。
 *
 * ## 加工项：只改「做哪些活」两键，其余原样带回
 *
 * `processingInfo` 里除了 `processingItems[]` / `specialOptions[]` 还住着工艺规格与算料输出
 * （`#4354`：它们逐键透传进加工单快照，是**固化真相**）⇒ 本组件**只重建这两个键**，
 * 其余键（含 `craftLineId` 樘窗组键、`processingMeters` 米数）原样带回去。
 * 原有加工项的 `quantity` / `id` 按名字保留（勾掉再加回来不会把数量重置），新勾的默认 1。
 *
 * ## 库存与状态
 *
 * 「待付款」单**尚未扣库存**（扣减在确认收款）⇒ 改明细不回滚库存，但服务端会按新明细
 * **重跑库存校验**（不足则 422，本弹窗把后端中文文案原样弹出，不吞、不改写）。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Plus, Trash2, Info } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import Button from '@/components/ui/Button'
import { orderApi, processingItemApi } from '@/lib/api'
import { toastRequestError } from '@/lib/api-error'
import type { Order, OrderContentUpdateItem, ProcessingItem } from '@/types'
import OrderExtraOptions from './OrderExtraOptions'

export interface EditOrderContentModalProps {
  open: boolean
  /** 当前订单（弹窗初值取自它；parent 保存成功后重新拉单） */
  order: Order
  onClose: () => void
  /** 保存成功（父页面据此重新拉单，让页面显示服务端真值） */
  onSaved: () => void
}

/** 一行可编辑明细（数字用字符串存 —— 输入框中途的 `2.` / 空串不能被 parseFloat 吃掉） */
interface EditableLine {
  key: string
  productId?: string
  productName: string
  quantity: string
  unitPrice: string
  width: string
  height: string
  /** 加工项目录里勾选的名称 */
  processingNames: string[]
  /** 特殊选项（元/套那半） */
  specialOptions: string[]
  /** 原样带回的加工项其它键（工艺规格 / 算料输出 / 樘窗组键 …） */
  rest: Record<string, unknown>
  /** 原有加工项的数量与目录 id（按名字索引，勾选态来回切不丢） */
  keptItems: Record<string, { id?: unknown; quantity?: unknown }>
}

let lineSeq = 0
function nextKey(): string {
  lineSeq += 1
  return `line-${lineSeq}`
}

function num(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  const parsed = Number(value)
  return Number.isFinite(parsed) ? String(parsed) : ''
}

/** `processingInfo` 可能是对象（BaseMapper 路径）或 JSON 字符串（历史/自定义查询路径）⇒ 两种都认 */
function asInfo(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // 解析不了 ⇒ 当作没有加工项信息（不猜）
    }
  }
  return {}
}

function namesOf(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((entry) => (entry && typeof entry === 'object' ? (entry as Record<string, unknown>).name : entry))
    .filter((name): name is string => typeof name === 'string' && name.trim() !== '')
}

function toLine(item: NonNullable<Order['items']>[number]): EditableLine {
  const info = asInfo(item.processingInfo)
  const rawItems = Array.isArray(info.processingItems) ? (info.processingItems as unknown[]) : []
  const keptItems: Record<string, { id?: unknown; quantity?: unknown }> = {}
  rawItems.forEach((entry) => {
    if (!entry || typeof entry !== 'object') return
    const row = entry as Record<string, unknown>
    const name = typeof row.name === 'string' ? row.name : ''
    if (name) keptItems[name] = { id: row.id, quantity: row.quantity }
  })
  // 其余键原样带回（工艺规格 / 算料输出 / 樘窗组键 …）—— 只摘掉本组件重建的那两个键
  const rest: Record<string, unknown> = { ...info }
  delete rest.processingItems
  delete rest.specialOptions
  return {
    key: nextKey(),
    productId: item.productId,
    productName: item.productName ?? '',
    quantity: num(item.quantity),
    unitPrice: num(item.unitPrice),
    width: num(item.width),
    height: num(item.height),
    processingNames: namesOf(info.processingItems),
    specialOptions: namesOf(info.specialOptions),
    rest,
    keptItems,
  }
}

/** 一行 → 提交用的 `processingInfo`：只重建两键，其余原样带回；两个键都空且原本没有 ⇒ 不带该字段 */
function buildProcessingInfo(line: EditableLine): Record<string, unknown> | undefined {
  const nothingSelected = line.processingNames.length === 0 && line.specialOptions.length === 0
  if (nothingSelected && Object.keys(line.rest).length === 0) return undefined
  const processingItems = line.processingNames.map((name) => {
    const kept = line.keptItems[name]
    const row: Record<string, unknown> = { name }
    if (kept?.id !== undefined && kept?.id !== null) row.id = kept.id
    const quantity = Number(kept?.quantity)
    row.quantity = Number.isFinite(quantity) && quantity > 0 ? quantity : 1
    return row
  })
  const info: Record<string, unknown> = { ...line.rest }
  if (processingItems.length > 0) info.processingItems = processingItems
  else delete info.processingItems
  if (line.specialOptions.length > 0) info.specialOptions = line.specialOptions
  else delete info.specialOptions
  return Object.keys(info).length > 0 ? info : undefined
}

export default function EditOrderContentModal({ open, order, onClose, onSaved }: EditOrderContentModalProps) {
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [discount, setDiscount] = useState('')
  const [actual, setActual] = useState('')
  const [lines, setLines] = useState<EditableLine[]>([])
  const [catalog, setCatalog] = useState<ProcessingItem[]>([])
  const [catalogFailed, setCatalogFailed] = useState(false)
  const [saving, setSaving] = useState(false)

  // 打开时用订单真值初始化（**保留订单原值**：优惠/实收默认带出，服务端未传即沿用，
  // 这里显式带出是为了让商家看见"改完金额会校验哪两个数"）
  useEffect(() => {
    if (!open) return
    setCustomerName(order.customerName ?? '')
    setCustomerPhone(order.customerPhone ?? '')
    setCustomerAddress(order.customerAddress ?? '')
    setDiscount(num(order.discountAmount ?? 0))
    setActual(num(order.actualAmount ?? 0))
    setLines((order.items ?? []).map(toLine))
    setSaving(false)
  }, [open, order])

  // 加工项目录（勾选项的来源）；取不到 ⇒ 显式提示且**不**让"勾选区"看起来是空的
  useEffect(() => {
    if (!open) return
    let alive = true
    ;(async () => {
      try {
        const res = await processingItemApi.getProcessingItems({ page: 1, size: 200 })
        if (!alive) return
        const items = res.data?.data?.items ?? []
        setCatalog(items)
        setCatalogFailed(false)
      } catch {
        if (!alive) return
        setCatalog([])
        setCatalogFailed(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [open])

  // ESC 关闭 + 锁背景滚动（与 CloseOrderModal 同范式）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open && !saving) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, saving])

  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  const goodsTotal = useMemo(
    () =>
      lines.reduce((sum, line) => {
        const quantity = Number(line.quantity)
        const unitPrice = Number(line.unitPrice)
        if (!Number.isFinite(quantity) || !Number.isFinite(unitPrice)) return sum
        return sum + quantity * unitPrice
      }, 0),
    [lines],
  )

  const patchLine = useCallback((key: string, patch: Partial<EditableLine>) => {
    setLines((prev) => prev.map((line) => (line.key === key ? { ...line, ...patch } : line)))
  }, [])

  const toggleProcessingName = useCallback((key: string, name: string, checked: boolean) => {
    setLines((prev) =>
      prev.map((line) => {
        if (line.key !== key) return line
        const next = checked
          ? Array.from(new Set([...line.processingNames, name]))
          : line.processingNames.filter((n) => n !== name)
        return { ...line, processingNames: next }
      }),
    )
  }, [])

  const addLine = useCallback(() => {
    setLines((prev) => [
      ...prev,
      {
        key: nextKey(),
        productName: '',
        quantity: '1',
        unitPrice: '',
        width: '',
        height: '',
        processingNames: [],
        specialOptions: [],
        rest: {},
        keptItems: {},
      },
    ])
  }, [])

  const removeLine = useCallback((key: string) => {
    setLines((prev) => prev.filter((line) => line.key !== key))
  }, [])

  const validate = (): string | null => {
    if (!customerName.trim()) return '请填写收货人'
    if (!/^1[3-9]\d{9}$/.test(customerPhone.trim())) return '请填写 11 位手机号'
    if (lines.length === 0) return '至少保留一行商品明细'
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i]
      if (!line.productName.trim()) return `第 ${i + 1} 行请填写商品名称`
      const quantity = Number(line.quantity)
      if (!Number.isFinite(quantity) || quantity < 1) return `第 ${i + 1} 行的数量不能小于 1`
      const unitPrice = Number(line.unitPrice)
      if (!Number.isFinite(unitPrice) || unitPrice <= 0) return `第 ${i + 1} 行的单价必须大于 0`
    }
    return null
  }

  const handleSubmit = async () => {
    const problem = validate()
    if (problem) {
      toast.error(problem)
      return
    }
    setSaving(true)
    try {
      const payload = {
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim(),
        discountAmount: Number(discount || 0),
        actualAmount: Number(actual || 0),
        items: lines.map<OrderContentUpdateItem>((line) => ({
          productId: line.productId,
          productName: line.productName.trim(),
          quantity: Number(line.quantity),
          unitPrice: Number(line.unitPrice),
          width: line.width === '' ? undefined : Number(line.width),
          height: line.height === '' ? undefined : Number(line.height),
          processingInfo: buildProcessingInfo(line),
        })),
      }
      await orderApi.updateOrderContent(order.id, payload)
      toast.success('订单已修改')
      onSaved()
    } catch (e) {
      // 后端中文文案原样弹出（状态不可改 / 库存不足 / 实收与应收不一致 …），不吞、不改写
      toastRequestError(e, '修改订单失败')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50" data-testid="edit-order-content-modal">
      <div className="absolute inset-0 bg-black/45" onClick={saving ? undefined : onClose} />
      <div className="absolute inset-0 flex items-center justify-center p-4 overflow-y-auto">
        <div
          className="relative bg-white rounded-lg shadow-xl w-full max-w-[760px] my-6"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-200">
            <h3 className="text-lg font-semibold text-neutral-900">修改订单</h3>
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="p-1 text-neutral-400 hover:text-neutral-600 hover:bg-neutral-100 rounded transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="px-6 py-5 space-y-6 max-h-[70vh] overflow-y-auto">
            {/* 收货信息 */}
            <section>
              <div className="text-sm font-medium text-neutral-900 mb-3">收货信息</div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm text-neutral-700">
                  收货人
                  <input
                    data-testid="edit-customer-name"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    className={inputClass}
                  />
                </label>
                <label className="text-sm text-neutral-700">
                  联系电话
                  <input
                    data-testid="edit-customer-phone"
                    value={customerPhone}
                    onChange={(e) => setCustomerPhone(e.target.value)}
                    className={inputClass}
                  />
                </label>
                <label className="text-sm text-neutral-700 col-span-2">
                  收货地址
                  <input
                    data-testid="edit-customer-address"
                    value={customerAddress}
                    onChange={(e) => setCustomerAddress(e.target.value)}
                    className={inputClass}
                  />
                </label>
              </div>
            </section>

            {/* 商品明细 */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm font-medium text-neutral-900">商品明细</div>
                <button
                  type="button"
                  data-testid="edit-add-line"
                  onClick={addLine}
                  className="inline-flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700"
                >
                  <Plus className="w-4 h-4" />
                  添加一行
                </button>
              </div>
              <div className="space-y-4">
                {lines.map((line, index) => (
                  <div key={line.key} className="border border-neutral-200 rounded-lg p-3">
                    <div className="grid grid-cols-12 gap-2 items-end">
                      <label className="text-xs text-neutral-600 col-span-4">
                        商品名称
                        <input
                          data-testid={`edit-line-name-${index}`}
                          value={line.productName}
                          onChange={(e) => patchLine(line.key, { productName: e.target.value })}
                          className={inputClass}
                        />
                      </label>
                      <label className="text-xs text-neutral-600 col-span-2">
                        数量
                        <input
                          data-testid={`edit-line-quantity-${index}`}
                          type="number"
                          min={1}
                          value={line.quantity}
                          onChange={(e) => patchLine(line.key, { quantity: e.target.value })}
                          className={inputClass}
                        />
                      </label>
                      <label className="text-xs text-neutral-600 col-span-2">
                        单价（元）
                        <input
                          data-testid={`edit-line-price-${index}`}
                          type="number"
                          min={0}
                          value={line.unitPrice}
                          onChange={(e) => patchLine(line.key, { unitPrice: e.target.value })}
                          className={inputClass}
                        />
                      </label>
                      <label className="text-xs text-neutral-600 col-span-1">
                        宽（米）
                        <input
                          value={line.width}
                          onChange={(e) => patchLine(line.key, { width: e.target.value })}
                          className={inputClass}
                        />
                      </label>
                      <label className="text-xs text-neutral-600 col-span-1">
                        高（米）
                        <input
                          value={line.height}
                          onChange={(e) => patchLine(line.key, { height: e.target.value })}
                          className={inputClass}
                        />
                      </label>
                      <div className="col-span-2 flex justify-end">
                        <button
                          type="button"
                          data-testid={`edit-remove-line-${index}`}
                          onClick={() => removeLine(line.key)}
                          disabled={lines.length === 1}
                          className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-red-600 disabled:opacity-40"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          删除
                        </button>
                      </div>
                    </div>

                    {/* 加工项 */}
                    <div className="mt-3 pt-3 border-t border-neutral-100">
                      <div className="text-xs text-neutral-600 mb-2">加工项</div>
                      {catalogFailed ? (
                        <div className="text-xs text-amber-600">
                          加工项目录未能加载，暂时无法修改加工项；商品与收货信息仍可保存
                        </div>
                      ) : catalog.length === 0 ? (
                        <div className="text-xs text-neutral-400">加工项目录为空</div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {catalog.map((entry) => {
                            const checked = line.processingNames.includes(entry.name)
                            return (
                              <label
                                key={entry.id}
                                className={cn(
                                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs cursor-pointer',
                                  checked
                                    ? 'border-primary-500 bg-primary-50 text-primary-700'
                                    : 'border-neutral-200 text-neutral-600 hover:border-neutral-300',
                                )}
                              >
                                <input
                                  type="checkbox"
                                  data-testid={`edit-line-${index}-processing-${entry.name}`}
                                  checked={checked}
                                  onChange={(e) => toggleProcessingName(line.key, entry.name, e.target.checked)}
                                  className="w-3.5 h-3.5"
                                />
                                {entry.name}
                              </label>
                            )
                          })}
                        </div>
                      )}

                      <div className="mt-3">
                        <div className="text-xs text-neutral-600 mb-2">特殊选项</div>
                        <OrderExtraOptions
                          value={line.specialOptions}
                          onChange={(next) => patchLine(line.key, { specialOptions: next })}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* 金额 */}
            <section>
              <div className="text-sm font-medium text-neutral-900 mb-3">金额</div>
              <div className="grid grid-cols-3 gap-3">
                <label className="text-sm text-neutral-700">
                  优惠金额（元）
                  <input
                    data-testid="edit-discount"
                    type="number"
                    min={0}
                    value={discount}
                    onChange={(e) => setDiscount(e.target.value)}
                    className={inputClass}
                  />
                </label>
                <label className="text-sm text-neutral-700">
                  实收款（元）
                  <input
                    data-testid="edit-actual"
                    type="number"
                    min={0}
                    value={actual}
                    onChange={(e) => setActual(e.target.value)}
                    className={inputClass}
                  />
                </label>
                <div className="text-sm text-neutral-700">
                  商品金额合计
                  <div className="mt-1.5 px-3 py-2 rounded border border-neutral-200 bg-neutral-50 text-neutral-700">
                    {goodsTotal.toFixed(2)} 元
                  </div>
                </div>
              </div>
              <div className="mt-3 flex items-start gap-2 text-xs text-neutral-500">
                <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span>
                  订单应收与实收款由系统在保存时按新明细、新加工项重新计算（加工费按加工费组合取价）；
                  上面的「商品金额合计」只是商品部分的估算，以保存后系统计算为准。
                  实收款与应收（应收 − 优惠）不一致时无法保存。
                </span>
              </div>
            </section>
          </div>

          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-neutral-200">
            <Button variant="secondary" onClick={onClose} disabled={saving}>
              取消
            </Button>
            <Button data-testid="edit-submit" onClick={handleSubmit} loading={saving}>
              保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

const inputClass = cn(
  'mt-1.5 w-full px-3 py-2 text-sm rounded border border-neutral-300 bg-white',
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
)
