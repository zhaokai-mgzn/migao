'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Search, Package, User, Receipt, Settings2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi, productApi } from '@/lib/api'
import type { ProductProcessingItem } from '@/lib/api'
import { resolveImageUrl } from '@/lib/utils'
import { Button, Card, Input, Modal } from '@/components/ui'
import type { Product, OrderItemFormData } from '@/types'

interface OrderProductSku {
  id: number
  productId?: string
  colorId: number
  colorName?: string
  sellingMethod?: string
  doorWidth?: string
  price: number
  stock?: number
  skuCode?: string
}

interface ProductDetail extends Omit<Product, 'skus'> {
  skus?: OrderProductSku[]
  basePrice?: number
  supportsProcessing?: boolean
  hasProcessing?: boolean
}

interface OrderLineItem {
  id: string
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: number | null
  selectedSku: OrderProductSku | null
  quantity: number
  unitPrice: number
  processingItems: ProductProcessingItem[]
  processingLoading: boolean
  selectedProcessing: Record<string, { selected: boolean; qty: number }>
}

const sellingMethodLabel: Record<string, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
  per_meter: '按米',
  per_piece: '按件',
}

function formatAmount(amount: number): string {
  return `¥${(amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function genId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `li_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function createEmptyLineItem(): OrderLineItem {
  return {
    id: genId(),
    product: null,
    productLoading: false,
    selectedColorId: null,
    selectedSku: null,
    quantity: 1,
    unitPrice: 0,
    processingItems: [],
    processingLoading: false,
    selectedProcessing: {},
  }
}

export default function NewOrderPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)

  // ===== 行项数组 =====
  const [lineItems, setLineItems] = useState<OrderLineItem[]>(() => [createEmptyLineItem()])

  // ===== 商品搜索弹窗 =====
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [activeLineId, setActiveLineId] = useState<string | null>(null)
  const [productKeyword, setProductKeyword] = useState('')
  const [productResults, setProductResults] = useState<Product[]>([])
  const [productSearchLoading, setProductSearchLoading] = useState(false)

  // ===== 收货信息 =====
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [remark, setRemark] = useState('')

  // ===== 实收款 =====
  const [actualAmount, setActualAmount] = useState<string>('')
  const [actualTouched, setActualTouched] = useState(false)

  // 表单错误
  const [errors, setErrors] = useState<Record<string, string>>({})

  // ===== 行项更新工具 =====
  const updateLineItem = useCallback(
    (lineId: string, patch: Partial<OrderLineItem>) => {
      setLineItems((prev) => prev.map((it) => (it.id === lineId ? { ...it, ...patch } : it)))
    },
    []
  )

  const addLineItem = () => {
    setLineItems((prev) => [...prev, createEmptyLineItem()])
  }

  const removeLineItem = (lineId: string) => {
    setLineItems((prev) => (prev.length <= 1 ? prev : prev.filter((it) => it.id !== lineId)))
    setErrors({})
  }

  // ===== 商品搜索 =====
  const searchProducts = useCallback(async () => {
    setProductSearchLoading(true)
    try {
      const res = await productApi.getProducts({
        keyword: productKeyword.trim() || undefined,
        page: 1,
        size: 30,
      })
      setProductResults(res.data?.data?.items || [])
    } catch {
      toast.error('搜索商品失败')
    } finally {
      setProductSearchLoading(false)
    }
  }, [productKeyword])

  useEffect(() => {
    if (productModalOpen) {
      searchProducts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productModalOpen])

  const openProductModalFor = (lineId: string) => {
    setActiveLineId(lineId)
    setProductModalOpen(true)
  }

  // ===== 选中商品后加载详情 + 加工项 =====
  const handlePickProduct = async (product: Product) => {
    const lineId = activeLineId
    setProductModalOpen(false)
    if (!lineId) return

    updateLineItem(lineId, {
      productLoading: true,
      processingLoading: true,
      processingItems: [],
      selectedProcessing: {},
      selectedColorId: null,
      selectedSku: null,
      quantity: 1,
      unitPrice: 0,
    })

    // 1) 加载商品详情（含 SKU）
    let detail: ProductDetail | null = null
    try {
      const res = await productApi.getProduct(product.id)
      detail = res.data?.data as unknown as ProductDetail
    } catch {
      toast.error('加载商品详情失败')
      detail = product as unknown as ProductDetail
    }

    const fallbackPrice =
      Number(detail?.price) || Number(detail?.basePrice) || Number(product.price) || 0

    updateLineItem(lineId, {
      product: detail,
      productLoading: false,
      unitPrice: fallbackPrice,
    })

    // 2) 加载该商品的可选加工项
    const supports =
      detail?.supportsProcessing !== false && detail?.hasProcessing !== false
    if (!supports) {
      updateLineItem(lineId, {
        processingLoading: false,
        processingItems: [],
        selectedProcessing: {},
      })
      return
    }

    try {
      const res = await productApi.getProductProcessingItems(product.id)
      const items = res.data?.data || []
      updateLineItem(lineId, {
        processingItems: items,
        processingLoading: false,
        selectedProcessing: {},
      })
    } catch {
      updateLineItem(lineId, {
        processingItems: [],
        processingLoading: false,
        selectedProcessing: {},
      })
    }
  }

  // ===== 颜色 / 规格 选择 =====
  const handleSelectColor = (line: OrderLineItem, colorId: number) => {
    const skusOfColor = (line.product?.skus || []).filter((s) => s.colorId === colorId)
    if (skusOfColor.length === 1) {
      const sku = skusOfColor[0]
      updateLineItem(line.id, {
        selectedColorId: colorId,
        selectedSku: sku,
        unitPrice: Number(sku.price) || line.unitPrice,
      })
    } else {
      updateLineItem(line.id, { selectedColorId: colorId, selectedSku: null })
    }
  }

  const handleSelectSku = (line: OrderLineItem, sku: OrderProductSku) => {
    updateLineItem(line.id, {
      selectedSku: sku,
      unitPrice: Number(sku.price) || 0,
    })
  }

  const toggleProcessing = (
    line: OrderLineItem,
    pi: ProductProcessingItem,
    selected: boolean
  ) => {
    const prev = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
    updateLineItem(line.id, {
      selectedProcessing: {
        ...line.selectedProcessing,
        [pi.id]: { selected, qty: Math.max(1, prev.qty || 1) },
      },
    })
  }

  const updateProcessingQty = (
    line: OrderLineItem,
    piId: string,
    qty: number
  ) => {
    const prev = line.selectedProcessing[piId] || { selected: true, qty: 1 }
    updateLineItem(line.id, {
      selectedProcessing: {
        ...line.selectedProcessing,
        [piId]: { selected: true, qty: Math.max(1, qty || 1) },
      },
    })
    void prev
  }

  // ===== 费用汇总 =====
  const totals = useMemo(() => {
    let productSubtotal = 0
    let processingFee = 0

    lineItems.forEach((item) => {
      if (!item.product) return
      productSubtotal += (Number(item.quantity) || 0) * (Number(item.unitPrice) || 0)
      Object.entries(item.selectedProcessing).forEach(([piId, cfg]) => {
        if (!cfg.selected) return
        const pi = item.processingItems.find((p) => p.id === piId)
        if (!pi) return
        const price = Number(pi.finalPrice) || Number(pi.unitPrice) || 0
        const q = Math.max(1, Number(cfg.qty) || 1)
        processingFee += price * q
      })
    })

    return {
      productSubtotal,
      processingFee,
      total: productSubtotal + processingFee,
    }
  }, [lineItems])

  // 实收款联动
  useEffect(() => {
    if (!actualTouched) {
      setActualAmount(totals.total.toFixed(2))
    }
  }, [totals.total, actualTouched])

  // ===== 校验 =====
  const validate = (): boolean => {
    const e: Record<string, string> = {}

    if (lineItems.length === 0) {
      e.lineItems = '请至少添加一个商品'
    }

    lineItems.forEach((line, idx) => {
      const prefix = `line_${line.id}`
      if (!line.product) {
        e[`${prefix}_product`] = `第 ${idx + 1} 个商品未选择`
        return
      }
      const colorOptions = uniqueColors(line.product.skus)
      const skuOptions =
        line.selectedColorId != null
          ? (line.product.skus || []).filter((s) => s.colorId === line.selectedColorId)
          : []
      if (colorOptions.length > 0 && line.selectedColorId == null) {
        e[`${prefix}_color`] = `第 ${idx + 1} 个商品未选择颜色`
      }
      if (skuOptions.length > 0 && !line.selectedSku) {
        e[`${prefix}_spec`] = `第 ${idx + 1} 个商品未选择规格`
      }
      if (!line.quantity || line.quantity <= 0) {
        e[`${prefix}_quantity`] = '数量须大于 0'
      }
      if (line.unitPrice == null || line.unitPrice <= 0) {
        e[`${prefix}_unitPrice`] = '单价须大于 0'
      }
    })

    if (!customerName.trim()) e.customerName = '请输入收货人姓名'
    if (!customerPhone.trim()) e.customerPhone = '请输入手机号'
    else if (!/^1[3-9]\d{9}$/.test(customerPhone.trim())) e.customerPhone = '手机号格式不正确'
    if (!customerAddress.trim()) e.customerAddress = '请输入收货地址'

    setErrors(e)
    return Object.keys(e).length === 0
  }

  // ===== 提交 =====
  const handleSubmit = async () => {
    if (!validate()) {
      toast.error('请完善订单信息')
      return
    }

    const items: OrderItemFormData[] = lineItems
      .filter((l) => l.product)
      .map((line) => {
        const sku = line.selectedSku
        const colorName =
          uniqueColors(line.product!.skus).find((c) => c.id === line.selectedColorId)?.name

        const processingDetails = Object.entries(line.selectedProcessing)
          .filter(([, v]) => v.selected)
          .map(([piId, v]) => {
            const pi = line.processingItems.find((p) => p.id === piId)
            if (!pi) return null
            const unit = Number(pi.finalPrice) || Number(pi.unitPrice) || 0
            const qty = Math.max(1, Number(v.qty) || 1)
            return {
              id: pi.id,
              name: pi.name,
              unitPrice: unit,
              quantity: qty,
              unit: pi.unit,
              pricingMethod: pi.pricingMethod,
              subtotal: unit * qty,
            }
          })
          .filter(Boolean) as Array<Record<string, unknown>>

        const lineProcessingFee = processingDetails.reduce(
          (sum, d) => sum + ((d.unitPrice as number) || 0) * ((d.quantity as number) || 0),
          0
        )

        const productSub = (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)

        return {
          productId: line.product!.id,
          productName: line.product!.name,
          quantity: Number(line.quantity),
          unitPrice: Number(line.unitPrice),
          subtotal: productSub + lineProcessingFee,
          processingInfo:
            processingDetails.length > 0 || sku || colorName
              ? {
                  colorId: line.selectedColorId ?? undefined,
                  colorName,
                  skuId: sku?.id,
                  skuCode: sku?.skuCode,
                  sellingMethod: sku?.sellingMethod,
                  doorWidth: sku?.doorWidth,
                  processingFee: lineProcessingFee,
                  processingItems: processingDetails,
                }
              : undefined,
        } as OrderItemFormData
      })

    const actual = Number(actualAmount)
    let finalRemark = remark.trim()
    if (!Number.isNaN(actual) && Math.abs(actual - totals.total) > 0.001) {
      const note = `实收款：¥${actual.toFixed(2)}（订单总额 ¥${totals.total.toFixed(2)}）`
      finalRemark = finalRemark ? `${finalRemark}\n${note}` : note
    }

    setSubmitting(true)
    try {
      await orderApi.createOrder({
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim(),
        remark: finalRemark || undefined,
        items,
      })
      toast.success('订单创建成功')
      router.push('/orders')
    } catch (err) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
      toast.error(msg || '创建订单失败')
    } finally {
      setSubmitting(false)
    }
  }

  // ====== 渲染 ======
  return (
    <div className="p-6 max-w-[1280px] mx-auto">
      {/* 顶部：返回 + 标题 */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push('/orders')}
          className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5 text-gray-600" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">新增订单</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            支持添加多个商品，每个商品可单独配置加工项
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：商品行项 + 收货信息 */}
        <div className="lg:col-span-2 space-y-6">
          {/* ============= 商品信息（多行项） ============= */}
          <Card>
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <SectionTitle icon={<Package className="w-4 h-4" />} title="商品信息" />
                <span className="text-xs text-gray-400">
                  共 {lineItems.length} 个商品
                </span>
              </div>

              <div className="space-y-4">
                {lineItems.map((line, idx) => (
                  <LineItemBlock
                    key={line.id}
                    index={idx}
                    line={line}
                    canRemove={lineItems.length > 1}
                    errors={errors}
                    onPickProduct={() => openProductModalFor(line.id)}
                    onRemove={() => removeLineItem(line.id)}
                    onSelectColor={(colorId) => handleSelectColor(line, colorId)}
                    onSelectSku={(sku) => handleSelectSku(line, sku)}
                    onChangeQty={(q) => updateLineItem(line.id, { quantity: q })}
                    onChangePrice={(p) => updateLineItem(line.id, { unitPrice: p })}
                    onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                    onChangeProcessingQty={(piId, q) => updateProcessingQty(line, piId, q)}
                  />
                ))}
              </div>

              <button
                type="button"
                onClick={addLineItem}
                className="mt-4 w-full h-11 rounded-lg border border-dashed border-gray-300 bg-white text-sm text-gray-500 hover:border-primary-500 hover:text-primary-600 hover:bg-primary-50/30 transition-colors inline-flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                添加商品
              </button>
            </div>
          </Card>

          {/* ============= 收货信息 ============= */}
          <Card>
            <div className="p-6">
              <SectionTitle icon={<User className="w-4 h-4" />} title="收货信息" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Input
                  label="收货人姓名"
                  placeholder="请输入收货人姓名"
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  error={errors.customerName}
                  required
                />
                <Input
                  label="手机号"
                  placeholder="请输入 11 位手机号"
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  error={errors.customerPhone}
                  maxLength={11}
                  required
                />
              </div>
              <div className="mt-4">
                <Input
                  label="收货地址"
                  placeholder="请输入详细收货地址"
                  value={customerAddress}
                  onChange={(e) => setCustomerAddress(e.target.value)}
                  error={errors.customerAddress}
                  required
                />
              </div>
              <div className="mt-4">
                <label className="block text-sm font-medium text-gray-700 mb-1.5">备注</label>
                <textarea
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder="可填写发货要求、特殊说明等（选填）"
                  rows={3}
                  className="w-full px-3 py-2 rounded border border-gray-300 text-sm resize-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
              </div>
            </div>
          </Card>
        </div>

        {/* 右侧：费用明细 + 操作 */}
        <div className="space-y-6">
          <Card>
            <div className="p-6">
              <SectionTitle icon={<Receipt className="w-4 h-4" />} title="费用明细" />

              {/* 行项汇总列表 */}
              {lineItems.some((l) => l.product) && (
                <div className="mb-3 space-y-2 text-sm">
                  {lineItems
                    .filter((l) => l.product)
                    .map((line, idx) => {
                      const sub =
                        (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)
                      const procFee = Object.entries(line.selectedProcessing).reduce(
                        (s, [piId, cfg]) => {
                          if (!cfg.selected) return s
                          const pi = line.processingItems.find((p) => p.id === piId)
                          if (!pi) return s
                          const price = Number(pi.finalPrice) || Number(pi.unitPrice) || 0
                          return s + price * Math.max(1, cfg.qty || 1)
                        },
                        0
                      )
                      return (
                        <div
                          key={line.id}
                          className="flex items-start justify-between gap-2 py-1.5 border-b border-dashed border-gray-100 last:border-0"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-gray-700 truncate">
                              <span className="text-gray-400 mr-1">{idx + 1}.</span>
                              {line.product?.name}
                            </div>
                            <div className="text-xs text-gray-400 mt-0.5">
                              ×{line.quantity} · {formatAmount(line.unitPrice)}
                              {procFee > 0 && (
                                <span className="ml-2 text-orange-600">
                                  +加工 {formatAmount(procFee)}
                                </span>
                              )}
                            </div>
                          </div>
                          <span className="text-gray-800 font-medium shrink-0">
                            {formatAmount(sub + procFee)}
                          </span>
                        </div>
                      )
                    })}
                </div>
              )}

              <dl className="space-y-3 text-sm">
                <Row label="商品小计" value={formatAmount(totals.productSubtotal)} />
                <Row
                  label="加工费"
                  value={formatAmount(totals.processingFee)}
                  highlight={totals.processingFee > 0}
                />
                <div className="my-2 border-t border-dashed border-gray-200" />
                <div className="flex items-baseline justify-between">
                  <span className="text-gray-700">订单金额</span>
                  <span className="text-lg font-semibold text-primary-600">
                    {formatAmount(totals.total)}
                  </span>
                </div>

                <div className="pt-3 mt-2 border-t border-gray-100">
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">
                    实收款 (¥)
                  </label>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    value={actualAmount}
                    onChange={(e) => {
                      setActualTouched(true)
                      setActualAmount(e.target.value)
                    }}
                    className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-gray-400">默认与订单金额一致，可手动调整</p>
                </div>
              </dl>
            </div>
          </Card>

          <div className="flex flex-col gap-2">
            <Button onClick={handleSubmit} loading={submitting} className="w-full" size="lg">
              提交订单
            </Button>
            <Button
              variant="secondary"
              onClick={() => router.push('/orders')}
              className="w-full"
              size="lg"
              disabled={submitting}
            >
              取消
            </Button>
          </div>
        </div>
      </div>

      {/* 商品搜索弹窗 */}
      <Modal
        open={productModalOpen}
        onClose={() => setProductModalOpen(false)}
        title="选择商品"
        width={680}
        footer={
          <Button variant="secondary" onClick={() => setProductModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索商品名称 / 货号"
              value={productKeyword}
              onChange={(e) => setProductKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchProducts()}
            />
            <Button onClick={searchProducts} loading={productSearchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[420px] overflow-y-auto -mx-2 px-2">
            {productSearchLoading ? (
              <p className="text-center text-gray-400 py-8 text-sm">加载中…</p>
            ) : productResults.length === 0 ? (
              <p className="text-center text-gray-400 py-8 text-sm">
                {productKeyword ? '未找到相关商品' : '暂无可选商品'}
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {productResults.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handlePickProduct(p)}
                    className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 bg-white hover:border-primary-400 hover:bg-primary-50/40 transition-colors text-left"
                  >
                    {p.images?.[0] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolveImageUrl(p.images[0])}
                        alt={p.name}
                        className="w-12 h-12 rounded object-cover bg-gray-50 border border-gray-200 shrink-0"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-300 shrink-0">
                        <Package className="w-5 h-5" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900 truncate">{p.name}</div>
                      <div className="text-xs text-gray-400 mt-0.5 truncate">
                        {p.categoryName || '-'} · {p.skuCode || p.unit || '-'}
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-gray-900 shrink-0">
                      ¥{Number(p.price ?? 0).toFixed(2)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}

// ====== 行项卡片 ======
interface LineItemBlockProps {
  index: number
  line: OrderLineItem
  canRemove: boolean
  errors: Record<string, string>
  onPickProduct: () => void
  onRemove: () => void
  onSelectColor: (colorId: number) => void
  onSelectSku: (sku: OrderProductSku) => void
  onChangeQty: (q: number) => void
  onChangePrice: (p: number) => void
  onToggleProcessing: (pi: ProductProcessingItem, selected: boolean) => void
  onChangeProcessingQty: (piId: string, qty: number) => void
}

function LineItemBlock({
  index,
  line,
  canRemove,
  errors,
  onPickProduct,
  onRemove,
  onSelectColor,
  onSelectSku,
  onChangeQty,
  onChangePrice,
  onToggleProcessing,
  onChangeProcessingQty,
}: LineItemBlockProps) {
  const colorOptions = useMemo(
    () => uniqueColors(line.product?.skus),
    [line.product]
  )
  const skuOptions = useMemo(() => {
    if (!line.product?.skus || line.selectedColorId == null) return []
    return line.product.skus.filter((s) => s.colorId === line.selectedColorId)
  }, [line.product, line.selectedColorId])

  const supportsProcessing =
    line.product?.supportsProcessing !== false && line.product?.hasProcessing !== false

  const errProduct = errors[`line_${line.id}_product`]
  const errColor = errors[`line_${line.id}_color`]
  const errSpec = errors[`line_${line.id}_spec`]
  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      {/* 行项头部：序号 + 删除 */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 bg-gray-50/60 rounded-t-xl">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-primary-600 text-white text-xs font-semibold">
            {index + 1}
          </span>
          <span className="text-sm font-medium text-gray-700">商品 {index + 1}</span>
        </div>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-red-600 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        )}
      </div>

      <div className="p-4">
        {/* 商品选择 */}
        <div className="mb-4">
          <Label required>选择商品</Label>
          {line.product ? (
            <div className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 bg-gray-50/60">
              {line.product.images?.[0] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveImageUrl(line.product.images[0])}
                  alt={line.product.name}
                  className="w-14 h-14 rounded object-cover bg-white border border-gray-200"
                />
              ) : (
                <div className="w-14 h-14 rounded bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-300">
                  <Package className="w-6 h-6" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-900 truncate">
                  {line.product.name}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {line.product.categoryName || '-'} · 货号：{line.product.skuCode || '-'}
                </div>
              </div>
              <button
                onClick={onPickProduct}
                className="text-sm text-primary-600 hover:text-primary-700"
              >
                重新选择
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={onPickProduct}
              className="w-full h-11 rounded-lg border border-dashed border-gray-300 bg-white text-sm text-gray-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
            >
              <Search className="w-4 h-4" />
              点击搜索并选择商品
            </button>
          )}
          {errProduct && <p className="mt-1.5 text-sm text-red-600">{errProduct}</p>}
        </div>

        {/* 颜色 + 规格 */}
        {line.product && (
          <>
            {line.productLoading ? (
              <div className="text-sm text-gray-400 py-4">商品规格加载中…</div>
            ) : (
              <>
                {colorOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>颜色</Label>
                    <div className="flex flex-wrap gap-2">
                      {colorOptions.map((c) => {
                        const active = line.selectedColorId === c.id
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => onSelectColor(c.id)}
                            className={
                              'h-9 px-3 rounded border text-sm transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-gray-300 bg-white text-gray-700 hover:border-gray-400')
                            }
                          >
                            {c.name}
                          </button>
                        )
                      })}
                    </div>
                    {errColor && <p className="mt-1.5 text-sm text-red-600">{errColor}</p>}
                  </div>
                )}

                {line.selectedColorId != null && skuOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>规格</Label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {skuOptions.map((sku) => {
                        const active = line.selectedSku?.id === sku.id
                        return (
                          <button
                            key={sku.id}
                            type="button"
                            onClick={() => onSelectSku(sku)}
                            className={
                              'flex items-center justify-between gap-2 px-3 py-2 rounded border text-sm transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-gray-300 bg-white text-gray-700 hover:border-gray-400')
                            }
                          >
                            <div className="text-left">
                              <div className="font-medium">
                                {sku.doorWidth || '默认规格'}
                                {sku.sellingMethod && (
                                  <span className="ml-2 text-xs text-gray-500">
                                    {sellingMethodLabel[sku.sellingMethod] || sku.sellingMethod}
                                  </span>
                                )}
                              </div>
                              <div className="text-xs text-gray-400 mt-0.5">
                                库存 {sku.stock ?? 0}
                              </div>
                            </div>
                            <span className="text-sm font-semibold">
                              ¥{Number(sku.price).toFixed(2)}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                    {errSpec && <p className="mt-1.5 text-sm text-red-600">{errSpec}</p>}
                  </div>
                )}
              </>
            )}

            {/* 数量 + 单价 */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <div>
                <Label required>数量</Label>
                <input
                  type="number"
                  min={1}
                  value={line.quantity}
                  onChange={(e) => onChangeQty(Math.max(1, Number(e.target.value) || 1))}
                  className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
                {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
              </div>
              <div>
                <Label required>单价 (¥)</Label>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={line.unitPrice}
                  onChange={(e) => onChangePrice(Number(e.target.value) || 0)}
                  className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
                {errPrice && <p className="mt-1 text-sm text-red-600">{errPrice}</p>}
              </div>
            </div>

            {/* 加工选项（按商品过滤） */}
            {supportsProcessing && (
              <div className="pt-2 border-t border-gray-100">
                <div className="flex items-center gap-2 mb-3">
                  <Settings2 className="w-4 h-4 text-gray-500" />
                  <span className="text-sm font-medium text-gray-700">加工选项（可选）</span>
                </div>

                {line.processingLoading ? (
                  <div className="text-sm text-gray-400 py-2">加工项加载中…</div>
                ) : line.processingItems.length === 0 ? (
                  <div className="text-sm text-gray-400 py-2">该商品暂无可选加工项</div>
                ) : (
                  <div className="space-y-2">
                    {line.processingItems.map((pi) => {
                      const cfg = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
                      const finalPrice = Number(pi.finalPrice) || Number(pi.unitPrice) || 0
                      return (
                        <div
                          key={pi.id}
                          className={
                            'flex items-center gap-3 p-3 rounded border transition-colors ' +
                            (cfg.selected
                              ? 'border-primary-300 bg-primary-50/40'
                              : 'border-gray-200 bg-white')
                          }
                        >
                          <input
                            type="checkbox"
                            checked={cfg.selected}
                            onChange={(e) => onToggleProcessing(pi, e.target.checked)}
                            className="w-4 h-4 accent-primary-600"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-gray-900">{pi.name}</div>
                            <div className="text-xs text-gray-500 mt-0.5">
                              ¥{finalPrice.toFixed(2)} / {pi.unit || '项'}
                              {pi.customPrice != null && pi.customPrice !== pi.unitPrice && (
                                <span className="ml-2 text-gray-400 line-through">
                                  ¥{Number(pi.unitPrice).toFixed(2)}
                                </span>
                              )}
                            </div>
                          </div>
                          {cfg.selected && (
                            <input
                              type="number"
                              min={1}
                              value={cfg.qty}
                              onChange={(e) =>
                                onChangeProcessingQty(pi.id, Math.max(1, Number(e.target.value) || 1))
                              }
                              className="w-20 h-8 px-2 rounded border border-gray-300 text-sm text-center focus:outline-none focus:border-primary-500"
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ====== 工具函数 ======
function uniqueColors(skus?: OrderProductSku[]): Array<{ id: number; name: string }> {
  const map = new Map<number, string>()
  ;(skus || []).forEach((s) => {
    if (s.colorId != null) map.set(s.colorId, s.colorName || `颜色${s.colorId}`)
  })
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
}

// ====== 内联小组件 ======
function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 h-6 rounded bg-primary-50 text-primary-600 inline-flex items-center justify-center">
        {icon}
      </span>
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
    </div>
  )
}

function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-sm font-medium text-gray-700 mb-1.5">
      {children}
      {required && <span className="text-red-500 ml-1">*</span>}
    </label>
  )
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-gray-500">{label}</span>
      <span className={highlight ? 'text-orange-600 font-medium' : 'text-gray-800'}>{value}</span>
    </div>
  )
}
