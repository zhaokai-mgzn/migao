'use client'

import { useEffect, useState, useCallback } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { processingItemApi, processingCategoryApi } from '@/lib/api'
import { Modal, Button } from '@/components/ui'
import type { ProcessingItem, ProcessingCategory, PricingMethod } from '@/types'

// 行编辑数据类型
interface RowData {
  id?: string // 有id表示已保存的项
  name: string
  unitPrice: string
  pricingMethod: PricingMethod | ''
  discount: string // 优惠类型
  discountQty: string // 满X件
  discountRate: string // 折扣力度
  isEditing: boolean
  isNew: boolean
  errors: Record<string, string>
}

// 计价方式选项
const PRICING_METHOD_OPTIONS = [
  { value: 'per_meter', label: '按购买米数计价' },
  { value: 'per_piece', label: '按购买套数计价' },
]

// 优惠类型选项
const DISCOUNT_OPTIONS = [
  { value: '', label: '无优惠' },
  { value: 'amount_off', label: '按金额满减' },
]

// 满X件选项（2-99）
const QTY_OPTIONS = Array.from({ length: 98 }, (_, i) => ({
  value: String(i + 2),
  label: `满${i + 2}件`,
}))

export default function ProcessingPage() {
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [categories, setCategories] = useState<ProcessingCategory[]>([])
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<RowData[]>([])
  const [saving, setSaving] = useState(false)

  // 确认对话框
  const [editConfirmOpen, setEditConfirmOpen] = useState(false)
  const [editConfirmIndex, setEditConfirmIndex] = useState<number | null>(null)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleteConfirmIndex, setDeleteConfirmIndex] = useState<number | null>(null)

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [itemsRes, catsRes] = await Promise.all([
        processingItemApi.getProcessingItems({ page: 1, size: 999 }),
        processingCategoryApi.getProcessingCategories(),
      ])
      const pageData = itemsRes.data?.data
      const loadedItems = pageData?.items || []
      setItems(loadedItems)
      setCategories(catsRes.data?.data || [])

      // 将已保存的项转为行数据（只读状态）
      const savedRows: RowData[] = loadedItems.map((item) => ({
        id: item.id,
        name: item.name,
        unitPrice: String(item.unitPrice ?? item.basePrice ?? 0),
        pricingMethod: item.pricingMethod || 'per_meter',
        discount: '',
        discountQty: '2',
        discountRate: '',
        isEditing: false,
        isNew: false,
        errors: {},
      }))
      setRows(savedRows)
    } catch (error) {
      console.error('加载数据失败:', error)
      toast.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 添加新行
  const handleAddRow = () => {
    setRows((prev) => [
      ...prev,
      {
        name: '',
        unitPrice: '',
        pricingMethod: '',
        discount: '',
        discountQty: '2',
        discountRate: '',
        isEditing: true,
        isNew: true,
        errors: {},
      },
    ])
  }

  // 更新行数据
  const updateRow = (index: number, field: keyof RowData, value: string) => {
    setRows((prev) => {
      const updated = [...prev]
      updated[index] = { ...updated[index], [field]: value, errors: { ...updated[index].errors, [field]: '' } }
      return updated
    })
  }

  // 请求编辑确认
  const requestEdit = (index: number) => {
    setEditConfirmIndex(index)
    setEditConfirmOpen(true)
  }

  // 确认编辑
  const confirmEdit = () => {
    if (editConfirmIndex !== null) {
      setRows((prev) => {
        const updated = [...prev]
        updated[editConfirmIndex] = { ...updated[editConfirmIndex], isEditing: true }
        return updated
      })
    }
    setEditConfirmOpen(false)
    setEditConfirmIndex(null)
  }

  // 请求删除确认
  const requestDelete = (index: number) => {
    setDeleteConfirmIndex(index)
    setDeleteConfirmOpen(true)
  }

  // 确认删除
  const confirmDelete = async () => {
    if (deleteConfirmIndex === null) return
    const row = rows[deleteConfirmIndex]

    try {
      if (row.id && !row.isNew) {
        // 已保存的项需调用API删除
        await processingItemApi.deleteProcessingItem(row.id)
      }
      setRows((prev) => prev.filter((_, i) => i !== deleteConfirmIndex))
      toast.success('删除成功')
    } catch (error) {
      toast.error('删除失败')
    } finally {
      setDeleteConfirmOpen(false)
      setDeleteConfirmIndex(null)
    }
  }

  // 校验单行
  const validateRow = (row: RowData): Record<string, string> => {
    const errors: Record<string, string> = {}
    if (!row.name.trim()) {
      errors.name = '请输入加工项名称'
    } else if (row.name.trim().length > 20) {
      errors.name = '名称不能超过20个字符'
    }

    const price = parseFloat(row.unitPrice)
    if (!row.unitPrice.trim()) {
      errors.unitPrice = '请输入加工项价格'
    } else if (isNaN(price) || price < 0.10 || price > 999.99) {
      errors.unitPrice = '价格范围 0.10 ~ 999.99'
    } else if (row.unitPrice.includes('.') && row.unitPrice.split('.')[1]?.length > 2) {
      errors.unitPrice = '最多2位小数'
    }

    if (!row.pricingMethod) {
      errors.pricingMethod = '请选择计价方式'
    }

    return errors
  }

  // 保存修改
  const handleSave = async () => {
    // 找出需要保存的行（新增或编辑中的）
    const editingRows = rows.filter((r) => r.isEditing || r.isNew)
    if (editingRows.length === 0) {
      toast.info('没有需要保存的修改')
      return
    }

    // 校验所有编辑中的行
    let hasError = false
    const updatedRows = rows.map((row) => {
      if (row.isEditing || row.isNew) {
        const errors = validateRow(row)
        if (Object.keys(errors).length > 0) {
          hasError = true
          return { ...row, errors }
        }
      }
      return row
    })
    setRows(updatedRows)

    if (hasError) {
      toast.error('请修正表单中的错误')
      return
    }

    setSaving(true)
    try {
      const defaultCategoryId = categories[0]?.id || 'default'

      for (const row of updatedRows) {
        if (!row.isEditing && !row.isNew) continue

        const formData = {
          name: row.name.trim(),
          categoryId: defaultCategoryId,
          pricingMethod: row.pricingMethod as PricingMethod,
          unitPrice: parseFloat(row.unitPrice),
          unit: row.pricingMethod === 'per_meter' ? '米' : '套',
          status: 'active' as const,
        }

        if (row.id && !row.isNew) {
          // 更新已有项
          await processingItemApi.updateProcessingItem(row.id, formData)
        } else {
          // 创建新项
          await processingItemApi.createProcessingItem(formData)
        }
      }

      toast.success('保存成功')
      await loadData()
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 获取计价方式显示文字
  const getPricingMethodLabel = (method: string) => {
    const opt = PRICING_METHOD_OPTIONS.find((o) => o.value === method)
    return opt?.label || method
  }

  // 是否有编辑中的行
  const hasEditingRows = rows.some((r) => r.isEditing || r.isNew)

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <h1 className="text-xl font-semibold text-gray-900 mb-6">加工项配置</h1>

      {/* 顶部操作栏 */}
      <div className="flex items-center justify-end gap-3 mb-4">
        <Button onClick={handleAddRow}>
          <Plus className="w-4 h-4 mr-1.5" />
          添加加工项
        </Button>
        <Button
          variant="secondary"
          onClick={handleSave}
          loading={saving}
          disabled={!hasEditingRows}
        >
          保存修改
        </Button>
      </div>

      {/* 行内编辑表格 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-900 w-[25%]">
                加工项名称<span className="text-red-500">*</span>
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-blue-600 w-[15%]">
                加工项价格<span className="text-red-500">*</span>
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-red-500 w-[20%]">
                加工项计价方式<span className="text-red-500">*</span>
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600 w-[22%]">
                设置优惠
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-600 w-[18%]">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-gray-500">
                  <div className="flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
                    加载中...
                  </div>
                </td>
              </tr>
            ) : rows.length === 0 ? (
              /* 空状态引导行 */
              <tr className="border-b border-gray-100">
                <td className="px-4 py-4 text-sm text-gray-400">请输入加工项名称</td>
                <td className="px-4 py-4 text-sm text-gray-400">请输入加工项价格</td>
                <td className="px-4 py-4 text-sm text-gray-400">
                  <span className="inline-flex items-center gap-1">
                    按购买套数计价 <span className="text-gray-300">▼</span>
                  </span>
                </td>
                <td className="px-4 py-4 text-sm text-gray-400">
                  <span className="inline-flex items-center gap-1">
                    按金额满减 <span className="text-gray-300">▼</span>
                  </span>
                </td>
                <td className="px-4 py-4 text-sm text-gray-400">删除</td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={row.id || `new-${index}`} className="border-b border-gray-100">
                  {/* 加工项名称 */}
                  <td className="px-4 py-3">
                    {row.isEditing ? (
                      <div>
                        <input
                          type="text"
                          className={`w-full h-9 px-3 rounded border text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                            row.errors.name ? 'border-red-500' : 'border-gray-300'
                          }`}
                          placeholder="请输入加工项名称"
                          maxLength={20}
                          value={row.name}
                          onChange={(e) => updateRow(index, 'name', e.target.value)}
                        />
                        {row.errors.name && (
                          <p className="mt-1 text-xs text-red-600">{row.errors.name}</p>
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-gray-900">{row.name}</span>
                    )}
                  </td>

                  {/* 加工项价格 */}
                  <td className="px-4 py-3">
                    {row.isEditing ? (
                      <div>
                        <input
                          type="number"
                          className={`w-full h-9 px-3 rounded border text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                            row.errors.unitPrice ? 'border-red-500' : 'border-gray-300'
                          }`}
                          placeholder="请输入加工项价格"
                          step="0.01"
                          min="0.10"
                          max="999.99"
                          value={row.unitPrice}
                          onChange={(e) => updateRow(index, 'unitPrice', e.target.value)}
                        />
                        {row.errors.unitPrice && (
                          <p className="mt-1 text-xs text-red-600">{row.errors.unitPrice}</p>
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-gray-900">{row.unitPrice}</span>
                    )}
                  </td>

                  {/* 计价方式 */}
                  <td className="px-4 py-3">
                    {row.isEditing ? (
                      <div>
                        <select
                          className={`w-full h-9 px-3 pr-8 rounded border bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                            row.errors.pricingMethod ? 'border-red-500' : 'border-gray-300'
                          }`}
                          value={row.pricingMethod}
                          onChange={(e) => updateRow(index, 'pricingMethod', e.target.value)}
                        >
                          <option value="" disabled>
                            请选择计价方式
                          </option>
                          {PRICING_METHOD_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                        {row.errors.pricingMethod && (
                          <p className="mt-1 text-xs text-red-600">{row.errors.pricingMethod}</p>
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-gray-900">
                        {getPricingMethodLabel(row.pricingMethod)}
                      </span>
                    )}
                  </td>

                  {/* 设置优惠 */}
                  <td className="px-4 py-3">
                    {row.isEditing ? (
                      <div className="space-y-2">
                        <select
                          className="w-full h-9 px-3 pr-8 rounded border border-gray-300 bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                          value={row.discount}
                          onChange={(e) => updateRow(index, 'discount', e.target.value)}
                        >
                          {DISCOUNT_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                        {row.discount === 'amount_off' && (
                          <div className="flex items-center gap-2">
                            <select
                              className="h-9 px-3 pr-8 rounded border border-gray-300 bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                              value={row.discountQty}
                              onChange={(e) => updateRow(index, 'discountQty', e.target.value)}
                            >
                              {QTY_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                            <div className="flex items-center">
                              <input
                                type="text"
                                className="w-28 h-9 px-3 rounded-l border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                                placeholder="请输入折扣力度"
                                value={row.discountRate}
                                onChange={(e) => updateRow(index, 'discountRate', e.target.value)}
                              />
                              <span className="h-9 px-2 flex items-center border border-l-0 border-gray-300 rounded-r bg-gray-50 text-sm text-gray-600">
                                折
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-sm text-gray-400">—</span>
                    )}
                  </td>

                  {/* 操作 */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      {!row.isNew && !row.isEditing && (
                        <button
                          onClick={() => requestEdit(index)}
                          className="text-sm text-gray-700 hover:text-primary-600 transition-colors"
                        >
                          编辑
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (row.isNew) {
                            // 新增行直接删除不需确认
                            setRows((prev) => prev.filter((_, i) => i !== index))
                          } else {
                            requestDelete(index)
                          }
                        }}
                        className="text-sm text-gray-700 hover:text-red-600 transition-colors"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 编辑确认对话框 */}
      <Modal
        open={editConfirmOpen}
        onClose={() => setEditConfirmOpen(false)}
        title="确认编辑"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditConfirmOpen(false)}>
              取消
            </Button>
            <Button onClick={confirmEdit}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-gray-600 text-sm leading-relaxed">
          编辑后，现有商品已关联的加工项老数据将被编辑后的新数据覆盖，但不会影响买家已经提交的历史订单数据。确定要进行编辑吗？
        </p>
      </Modal>

      {/* 删除确认对话框 */}
      <Modal
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteConfirmOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmDelete}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-gray-600 text-sm leading-relaxed">
          删除后，当用户再购买已关联当前加工项的商品时，将不会再看到当前加工项。确定要删除当前加工项吗？
        </p>
      </Modal>
    </div>
  )
}
