'use client'

import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Plus, Trash2, Search, ShoppingCart } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi, productApi } from '@/lib/api'
import { Button, Card, Input, Modal } from '@/components/ui'
import type { Product, OrderItemFormData } from '@/types'

function formatAmount(amount: number): string {
  return `¥${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function NewOrderPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)

  // 客户信息
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [remark, setRemark] = useState('')

  // 订单明细
  const [items, setItems] = useState<OrderItemFormData[]>([])

  // 商品搜索弹窗
  const [productSearchOpen, setProductSearchOpen] = useState(false)
  const [productKeyword, setProductKeyword] = useState('')
  const [searchResults, setSearchResults] = useState<Product[]>([])
  const [searchLoading, setSearchLoading] = useState(false)

  // 表单验证错误
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 搜索商品
  const searchProducts = useCallback(async () => {
    if (!productKeyword.trim()) return
    setSearchLoading(true)
    try {
      const res = await productApi.getProducts({ keyword: productKeyword, page: 1, size: 20 })
      setSearchResults(res.data?.data?.items || [])
    } catch {
      toast.error('搜索商品失败')
    } finally {
      setSearchLoading(false)
    }
  }, [productKeyword])

  // 添加商品到订单
  const addProduct = (product: Product) => {
    const existing = items.find((i) => i.productId === product.id)
    if (existing) {
      toast.info('该商品已在订单中')
      return
    }
    const newItem: OrderItemFormData = {
      productId: product.id,
      productName: product.name,
      quantity: 1,
      unitPrice: product.price,
      subtotal: product.price,
    }
    setItems([...items, newItem])
    setProductSearchOpen(false)
    setProductKeyword('')
    setSearchResults([])
  }

  // 手动添加空白行
  const addEmptyItem = () => {
    setItems([
      ...items,
      {
        productName: '',
        quantity: 1,
        unitPrice: 0,
        subtotal: 0,
      },
    ])
  }

  // 更新明细
  const updateItem = (index: number, field: keyof OrderItemFormData, value: unknown) => {
    const newItems = [...items]
    const item = { ...newItems[index], [field]: value }
    // 重算小计
    item.subtotal = (item.quantity || 0) * (item.unitPrice || 0)
    newItems[index] = item
    setItems(newItems)
  }

  // 删除明细
  const removeItem = (index: number) => {
    setItems(items.filter((_, i) => i !== index))
  }

  // 计算总金额
  const totalAmount = items.reduce((sum, item) => sum + (item.subtotal || 0), 0)

  // 验证
  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!customerName.trim()) newErrors.customerName = '请输入客户姓名'
    if (!customerPhone.trim()) newErrors.customerPhone = '请输入联系电话'
    if (items.length === 0) newErrors.items = '请至少添加一个商品'
    items.forEach((item, index) => {
      if (!item.productName.trim()) newErrors[`item_${index}_name`] = '请输入商品名称'
      if (item.quantity <= 0) newErrors[`item_${index}_qty`] = '数量须大于0'
      if (item.unitPrice < 0) newErrors[`item_${index}_price`] = '单价不能为负'
    })
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // 提交
  const handleSubmit = async () => {
    if (!validate()) {
      toast.error('请填写完整订单信息')
      return
    }
    setSubmitting(true)
    try {
      await orderApi.createOrder({
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim() || undefined,
        remark: remark.trim() || undefined,
        items: items.map((item) => ({
          ...item,
          subtotal: (item.quantity || 0) * (item.unitPrice || 0),
        })),
      })
      toast.success('订单创建成功')
      router.push('/orders')
    } catch {
      toast.error('创建订单失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6">
      {/* 标题 */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => router.push('/orders')}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-gray-600" />
        </button>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">创建订单</h1>
          <p className="text-sm text-gray-500 mt-1">填写订单信息并添加商品</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：主表单 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 客户信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">客户信息</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Input
                  label="客户姓名"
                  placeholder="请输入客户姓名"
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  error={errors.customerName}
                  required
                />
                <Input
                  label="联系电话"
                  placeholder="请输入联系电话"
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  error={errors.customerPhone}
                  required
                />
              </div>
              <div className="mt-4">
                <Input
                  label="收货地址"
                  placeholder="请输入收货地址"
                  value={customerAddress}
                  onChange={(e) => setCustomerAddress(e.target.value)}
                />
              </div>
            </div>
          </Card>

          {/* 商品明细 */}
          <Card>
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">商品明细</h2>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setProductSearchOpen(true)}>
                    <Search className="w-4 h-4 mr-1" />
                    搜索商品
                  </Button>
                  <Button size="sm" variant="ghost" onClick={addEmptyItem}>
                    <Plus className="w-4 h-4 mr-1" />
                    手动添加
                  </Button>
                </div>
              </div>

              {errors.items && (
                <p className="text-sm text-red-600 mb-3">{errors.items}</p>
              )}

              {items.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <ShoppingCart className="w-10 h-10 mx-auto mb-2 text-gray-300" />
                  <p className="text-sm">暂无商品，请搜索添加或手动添加</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* 表头 */}
                  <div className="grid grid-cols-12 gap-2 text-xs font-semibold text-gray-500 pb-2 border-b">
                    <div className="col-span-4">商品名称</div>
                    <div className="col-span-2 text-center">数量</div>
                    <div className="col-span-2 text-center">单价 (¥)</div>
                    <div className="col-span-2 text-right">小计</div>
                    <div className="col-span-2 text-center">操作</div>
                  </div>

                  {items.map((item, index) => (
                    <div key={index} className="grid grid-cols-12 gap-2 items-center">
                      <div className="col-span-4">
                        <input
                          value={item.productName}
                          onChange={(e) => updateItem(index, 'productName', e.target.value)}
                          placeholder="商品名称"
                          className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500"
                        />
                        {errors[`item_${index}_name`] && (
                          <p className="text-xs text-red-500 mt-0.5">{errors[`item_${index}_name`]}</p>
                        )}
                      </div>
                      <div className="col-span-2">
                        <input
                          type="number"
                          min={1}
                          value={item.quantity}
                          onChange={(e) => updateItem(index, 'quantity', Number(e.target.value))}
                          className="w-full h-9 px-3 rounded border border-gray-300 text-sm text-center focus:outline-none focus:border-primary-500"
                        />
                      </div>
                      <div className="col-span-2">
                        <input
                          type="number"
                          min={0}
                          step={0.01}
                          value={item.unitPrice}
                          onChange={(e) => updateItem(index, 'unitPrice', Number(e.target.value))}
                          className="w-full h-9 px-3 rounded border border-gray-300 text-sm text-center focus:outline-none focus:border-primary-500"
                        />
                      </div>
                      <div className="col-span-2 text-right text-sm font-medium text-gray-900">
                        {formatAmount(item.subtotal || 0)}
                      </div>
                      <div className="col-span-2 text-center">
                        <button
                          onClick={() => removeItem(index)}
                          className="p-1.5 text-red-500 hover:bg-red-50 rounded transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* 备注 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">订单备注</h2>
              <textarea
                value={remark}
                onChange={(e) => setRemark(e.target.value)}
                placeholder="请输入订单备注（选填）"
                rows={3}
                className="w-full px-3 py-2 rounded border border-gray-300 text-sm resize-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              />
            </div>
          </Card>
        </div>

        {/* 右侧：价格汇总 + 提交 */}
        <div className="space-y-6">
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">价格汇总</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">商品数量</span>
                  <span className="text-gray-700">{items.length} 项</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">商品总额</span>
                  <span className="text-gray-700">{formatAmount(totalAmount)}</span>
                </div>
                <div className="border-t pt-3 flex justify-between text-base font-semibold">
                  <span className="text-gray-900">订单总额</span>
                  <span className="text-blue-600">{formatAmount(totalAmount)}</span>
                </div>
              </div>
            </div>
          </Card>

          <div className="flex flex-col gap-3">
            <Button onClick={handleSubmit} loading={submitting} className="w-full" size="lg">
              确认创建订单
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
        open={productSearchOpen}
        onClose={() => { setProductSearchOpen(false); setSearchResults([]); setProductKeyword('') }}
        title="搜索商品"
        width={640}
        footer={
          <Button variant="secondary" onClick={() => { setProductSearchOpen(false); setSearchResults([]); setProductKeyword('') }}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="输入商品名称搜索..."
              value={productKeyword}
              onChange={(e) => setProductKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchProducts()}
            />
            <Button onClick={searchProducts} loading={searchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[300px] overflow-y-auto">
            {searchResults.length === 0 ? (
              <p className="text-center text-gray-400 py-6 text-sm">
                {productKeyword ? '未找到相关商品' : '请输入关键词搜索商品'}
              </p>
            ) : (
              <div className="space-y-2">
                {searchResults.map((product) => (
                  <div
                    key={product.id}
                    className="flex items-center justify-between p-3 border border-gray-100 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => addProduct(product)}
                  >
                    <div>
                      <div className="font-medium text-gray-900 text-sm">{product.name}</div>
                      <div className="text-xs text-gray-400 mt-0.5">
                        {product.categoryName || '-'} · {product.unit}
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-gray-900">
                      ¥{(product.price ?? 0).toFixed(2)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}
