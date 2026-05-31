'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Search, Package, User, Receipt, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi, productApi, processingItemApi } from '@/lib/api'
import { Button, Card, Input, Modal } from '@/components/ui'
import type { Product, ProcessingItem, OrderItemFormData } from '@/types'

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
}

function formatAmount(amount: number): string {
  return `¥${(amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const sellingMethodLabel: Record<string, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
  per_meter: '按米',
  per_piece: '按件',
}

export default function NewOrderPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)

  // ===== 商品选择 =====
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [productKeyword, setProductKeyword] = useState('')
  const [productResults, setProductResults] = useState<Product[]>([])
  const [productSearchLoading, setProductSearchLoading] = useState(false)
  const [productLoading, setProductLoading] = useState(false)

  // 已选商品（含 SKU 详情）
  const [selectedProduct, setSelectedProduct] = useState<ProductDetail | null>(null)

  // 颜色 / 规格 / 数量 / 单价
  const [selectedColorId, setSelectedColorId] = useState<number | null>(null)
  const [selectedSkuId, setSelectedSkuId] = useState<number | null>(null)
  const [quantity, setQuantity] = useState<number>(1)
  const [unitPrice, setUnitPrice] = useState<number>(0)

  // ===== 加工选项 =====
  const [processingItems, setProcessingItems] = useState<ProcessingItem[]>([])
  const [selectedProcessing, setSelectedProcessing] = useState<Record<string, { selected: boolean; qty: number }>>({})

  // ===== 收货信息 =====
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [remark, setRemark] = useState('')

  // ===== 实收款 =====
  const [actualAmount, setActualAmount] = useState<string>('')

  // 表单错误
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 加载加工项
  useEffect(() => {
    processingItemApi
      .getProcessingItems({ page: 1, size: 100 })
      .then((res) => setProcessingItems(res.data?.data?.items || []))
      .catch(() => undefined)
  }, [])

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

  // 打开商品弹窗时预加载列表
  useEffect(() => {
    if (productModalOpen) {
      searchProducts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productModalOpen])

  // ===== 选中商品后加载详情（含 SKU）=====
  const handlePickProduct = async (product: Product) => {
    setProductModalOpen(false)
    setProductLoading(true)
    try {
      const res = await productApi.getProduct(product.id)
      const detail = res.data?.data as unknown as ProductDetail
      setSelectedProduct(detail)
      // 重置选择
      setSelectedColorId(null)
      setSelectedSkuId(null)
      setQuantity(1)
      setUnitPrice(Number(detail?.price) || Number(detail?.basePrice) || 0)
      setSelectedProcessing({})
    } catch {
      toast.error('加载商品详情失败')
      setSelectedProduct(product as unknown as ProductDetail)
      setUnitPrice(product.price || 0)
    } finally {
      setProductLoading(false)
    }
  }

  // 颜色列表（去重）
  const colorOptions = useMemo(() => {
    const skus = selectedProduct?.skus || []
    const map = new Map<number, string>()
    skus.forEach((s) => {
      if (s.colorId != null) map.set(s.colorId, s.colorName || `颜色${s.colorId}`)
    })
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
  }, [selectedProduct])

  // 当前颜色下的规格 SKU
  const skuOptions = useMemo(() => {
    if (!selectedProduct?.skus || selectedColorId == null) return []
    return selectedProduct.skus.filter((s) => s.colorId === selectedColorId)
  }, [selectedProduct, selectedColorId])

  // 选择颜色后，自动重置规格
  const handleSelectColor = (colorId: number) => {
    setSelectedColorId(colorId)
    setSelectedSkuId(null)
    // 若该颜色仅有一个 SKU，自动选中
    const skusOfColor = (selectedProduct?.skus || []).filter((s) => s.colorId === colorId)
    if (skusOfColor.length === 1) {
      const sku = skusOfColor[0]
      setSelectedSkuId(sku.id)
      setUnitPrice(Number(sku.price) || unitPrice)
    }
  }

  // 选择规格后，带入价格
  const handleSelectSku = (sku: OrderProductSku) => {
    setSelectedSkuId(sku.id)
    setUnitPrice(Number(sku.price) || 0)
  }

  // ===== 加工费用 =====
  const processingTotal = useMemo(() => {
    return Object.entries(selectedProcessing).reduce((sum, [id, v]) => {
      if (!v.selected) return sum
      const item = processingItems.find((p) => String(p.id) === id)
      if (!item) return sum
      const price = Number(item.unitPrice) || 0
      const q = Math.max(1, Number(v.qty) || 1)
      return sum + price * q
    }, 0)
  }, [selectedProcessing, processingItems])

  // ===== 商品小计 =====
  const itemsSubtotal = useMemo(() => {
    return (Number(quantity) || 0) * (Number(unitPrice) || 0)
  }, [quantity, unitPrice])

  // ===== 订单总额 =====
  const totalAmount = itemsSubtotal + processingTotal

  // 实收款默认与总额联动（用户未手动改时）
  const [actualTouched, setActualTouched] = useState(false)
  useEffect(() => {
    if (!actualTouched) {
      setActualAmount(totalAmount.toFixed(2))
    }
  }, [totalAmount, actualTouched])

  // ===== 校验 =====
  const validate = (): boolean => {
    const e: Record<string, string> = {}
    if (!selectedProduct) e.product = '请选择商品'
    if (selectedProduct && colorOptions.length > 0 && selectedColorId == null) e.color = '请选择颜色'
    if (selectedProduct && skuOptions.length > 0 && selectedSkuId == null) e.spec = '请选择规格'
    if (!quantity || quantity <= 0) e.quantity = '数量须大于 0'
    if (unitPrice == null || unitPrice <= 0) e.unitPrice = '单价须大于 0'
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
    if (!selectedProduct) return

    const sku = selectedProduct.skus?.find((s) => s.id === selectedSkuId)
    const colorName = colorOptions.find((c) => c.id === selectedColorId)?.name

    // 加工详情
    const processingDetails = Object.entries(selectedProcessing)
      .filter(([, v]) => v.selected)
      .map(([id, v]) => {
        const item = processingItems.find((p) => String(p.id) === id)
        return item
          ? {
              id: item.id,
              name: item.name,
              unitPrice: Number(item.unitPrice) || 0,
              quantity: Math.max(1, Number(v.qty) || 1),
              unit: item.unit,
            }
          : null
      })
      .filter(Boolean) as Array<Record<string, unknown>>

    const item: OrderItemFormData = {
      productId: selectedProduct.id,
      productName: selectedProduct.name,
      quantity: Number(quantity),
      unitPrice: Number(unitPrice),
      subtotal: itemsSubtotal + processingTotal,
      processingInfo:
        processingDetails.length > 0 || sku || colorName
          ? {
              colorId: selectedColorId ?? undefined,
              colorName,
              skuId: sku?.id,
              skuCode: sku?.skuCode,
              sellingMethod: sku?.sellingMethod,
              doorWidth: sku?.doorWidth,
              processingFee: processingTotal,
              processingItems: processingDetails,
            }
          : undefined,
    }

    // 实收金额与订单总额不一致时，写入备注以便后端记录
    const actual = Number(actualAmount)
    let finalRemark = remark.trim()
    if (!Number.isNaN(actual) && Math.abs(actual - totalAmount) > 0.001) {
      const note = `实收款：¥${actual.toFixed(2)}（订单总额 ¥${totalAmount.toFixed(2)}）`
      finalRemark = finalRemark ? `${finalRemark}\n${note}` : note
    }

    setSubmitting(true)
    try {
      await orderApi.createOrder({
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim(),
        remark: finalRemark || undefined,
        items: [item],
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
          <p className="text-sm text-gray-500 mt-0.5">手动录入商品订单，包含商品、收货与费用信息</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：商品信息 + 收货信息 */}
        <div className="lg:col-span-2 space-y-6">
          {/* ============= 商品信息 ============= */}
          <Card>
            <div className="p-6">
              <SectionTitle icon={<Package className="w-4 h-4" />} title="商品信息" />

              {/* 商品选择 */}
              <div className="mb-4">
                <Label required>选择商品</Label>
                {selectedProduct ? (
                  <div className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 bg-gray-50/60">
                    {selectedProduct.images?.[0] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={selectedProduct.images[0]}
                        alt={selectedProduct.name}
                        className="w-14 h-14 rounded object-cover bg-white border border-gray-200"
                      />
                    ) : (
                      <div className="w-14 h-14 rounded bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-300">
                        <Package className="w-6 h-6" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-900 truncate">
                        {selectedProduct.name}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {selectedProduct.categoryName || '-'} · 货号：{selectedProduct.skuCode || '-'}
                      </div>
                    </div>
                    <button
                      onClick={() => setProductModalOpen(true)}
                      className="text-sm text-primary-600 hover:text-primary-700"
                    >
                      重新选择
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setProductModalOpen(true)}
                    className="w-full h-11 rounded-lg border border-dashed border-gray-300 bg-white text-sm text-gray-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
                  >
                    <Search className="w-4 h-4" />
                    点击搜索并选择商品
                  </button>
                )}
                {errors.product && <p className="mt-1.5 text-sm text-red-600">{errors.product}</p>}
              </div>

              {/* 颜色 + 规格 */}
              {selectedProduct && (
                <>
                  {productLoading ? (
                    <div className="text-sm text-gray-400 py-4">商品规格加载中…</div>
                  ) : (
                    <>
                      {colorOptions.length > 0 && (
                        <div className="mb-4">
                          <Label required>颜色</Label>
                          <div className="flex flex-wrap gap-2">
                            {colorOptions.map((c) => {
                              const active = selectedColorId === c.id
                              return (
                                <button
                                  key={c.id}
                                  type="button"
                                  onClick={() => handleSelectColor(c.id)}
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
                          {errors.color && <p className="mt-1.5 text-sm text-red-600">{errors.color}</p>}
                        </div>
                      )}

                      {selectedColorId != null && skuOptions.length > 0 && (
                        <div className="mb-4">
                          <Label required>规格</Label>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {skuOptions.map((sku) => {
                              const active = selectedSkuId === sku.id
                              return (
                                <button
                                  key={sku.id}
                                  type="button"
                                  onClick={() => handleSelectSku(sku)}
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
                                  <span className="text-sm font-semibold">¥{Number(sku.price).toFixed(2)}</span>
                                </button>
                              )
                            })}
                          </div>
                          {errors.spec && <p className="mt-1.5 text-sm text-red-600">{errors.spec}</p>}
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
                        value={quantity}
                        onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                        className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      />
                      {errors.quantity && <p className="mt-1 text-sm text-red-600">{errors.quantity}</p>}
                    </div>
                    <div>
                      <Label required>单价 (¥)</Label>
                      <input
                        type="number"
                        min={0}
                        step={0.01}
                        value={unitPrice}
                        onChange={(e) => setUnitPrice(Number(e.target.value) || 0)}
                        className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      />
                      {errors.unitPrice && <p className="mt-1 text-sm text-red-600">{errors.unitPrice}</p>}
                    </div>
                  </div>

                  {/* 加工选项 */}
                  {processingItems.length > 0 && (
                    <div className="pt-2 border-t border-gray-100">
                      <div className="flex items-center gap-2 mb-3">
                        <Settings2 className="w-4 h-4 text-gray-500" />
                        <span className="text-sm font-medium text-gray-700">加工选项（可选）</span>
                      </div>
                      <div className="space-y-2">
                        {processingItems.map((item) => {
                          const cfg = selectedProcessing[item.id] || { selected: false, qty: 1 }
                          return (
                            <div
                              key={item.id}
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
                                onChange={(e) =>
                                  setSelectedProcessing((prev) => ({
                                    ...prev,
                                    [item.id]: { qty: cfg.qty, selected: e.target.checked },
                                  }))
                                }
                                className="w-4 h-4 accent-primary-600"
                              />
                              <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium text-gray-900">{item.name}</div>
                                <div className="text-xs text-gray-500 mt-0.5">
                                  ¥{Number(item.unitPrice || 0).toFixed(2)} / {item.unit || '项'}
                                </div>
                              </div>
                              {cfg.selected && (
                                <input
                                  type="number"
                                  min={1}
                                  value={cfg.qty}
                                  onChange={(e) =>
                                    setSelectedProcessing((prev) => ({
                                      ...prev,
                                      [item.id]: { selected: true, qty: Math.max(1, Number(e.target.value) || 1) },
                                    }))
                                  }
                                  className="w-20 h-8 px-2 rounded border border-gray-300 text-sm text-center focus:outline-none focus:border-primary-500"
                                />
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
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

              <dl className="space-y-3 text-sm">
                <Row label="商品单价" value={formatAmount(unitPrice)} />
                <Row label="数量" value={`× ${quantity || 0}`} />
                <Row label="商品小计" value={formatAmount(itemsSubtotal)} />
                <Row label="加工费" value={formatAmount(processingTotal)} highlight={processingTotal > 0} />
                <div className="my-2 border-t border-dashed border-gray-200" />
                <div className="flex items-baseline justify-between">
                  <span className="text-gray-700">订单金额</span>
                  <span className="text-lg font-semibold text-primary-600">{formatAmount(totalAmount)}</span>
                </div>

                <div className="pt-3 mt-2 border-t border-gray-100">
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">实收款 (¥)</label>
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
                        src={p.images[0]}
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

// ====== 内联小组件 ======
function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
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
