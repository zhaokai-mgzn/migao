'use client'

import { useEffect, useState, useCallback } from 'react'
import { Plus, Edit2, Trash2, Calculator } from 'lucide-react'
import { toast } from 'sonner'
import { processingItemApi, processingCategoryApi } from '@/lib/api'
import { Table, Pagination, Modal, Button, Badge, SearchBar, Input, Select } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { ProcessingItem, ProcessingCategory, ProcessingItemFormData } from '@/types'

export default function ProcessingPage() {
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [categories, setCategories] = useState<ProcessingCategory[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchParams, setSearchParams] = useState({
    keyword: '',
    categoryId: '',
  })

  // 模态框状态
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<ProcessingItem | null>(null)
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deletingItem, setDeletingItem] = useState<ProcessingItem | null>(null)
  
  // 价格计算器状态
  const [calcModalOpen, setCalcModalOpen] = useState(false)
  const [calculatingItem, setCalculatingItem] = useState<ProcessingItem | null>(null)
  const [calcParams, setCalcParams] = useState({ width: '', height: '' })
  const [calcResult, setCalcResult] = useState<number | null>(null)
  const [calcLoading, setCalcLoading] = useState(false)

  // 表单数据
  const [formData, setFormData] = useState<ProcessingItemFormData>({
    name: '',
    categoryId: '',
    unit: '米',
    basePrice: 0,
    status: 'active',
    pricingRules: {},
    description: '',
  })
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [itemsRes, catsRes] = await Promise.all([
        processingItemApi.getProcessingItems({
          page: current,
          size: pageSize,
          ...searchParams,
        }),
        processingCategoryApi.getProcessingCategories(),
      ])
      const pageData = itemsRes.data?.data
      setItems(pageData?.items || [])
      setTotal(pageData?.total || 0)
      setCategories(catsRes.data?.data || [])
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchParams])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 获取分类名称
  const getCategoryName = (categoryId: string) => {
    const cat = categories.find((c) => c.id === categoryId)
    return cat?.name || '-'
  }

  // 搜索
  const handleSearch = (values: Record<string, string>) => {
    setCurrent(1)
    setSearchParams({
      keyword: values.keyword || '',
      categoryId: values.categoryId || '',
    })
  }

  // 重置
  const handleReset = () => {
    setCurrent(1)
    setSearchParams({ keyword: '', categoryId: '' })
  }

  // 打开新增/编辑模态框
  const openEditModal = (item?: ProcessingItem) => {
    if (item) {
      setEditingItem(item)
      setFormData({
        name: item.name,
        categoryId: item.categoryId,
        unit: item.unit,
        basePrice: item.basePrice,
        status: item.status,
        pricingRules: item.pricingRules || {},
        description: item.description || '',
      })
    } else {
      setEditingItem(null)
      setFormData({
        name: '',
        categoryId: categories[0]?.id || '',
        unit: '米',
        basePrice: 0,
        status: 'active',
        pricingRules: {},
        description: '',
      })
    }
    setFormErrors({})
    setEditModalOpen(true)
  }

  // 验证表单
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}
    if (!formData.name.trim()) {
      errors.name = '请输入加工项名称'
    }
    if (!formData.categoryId) {
      errors.categoryId = '请选择加工分类'
    }
    if (formData.basePrice < 0) {
      errors.basePrice = '基础价格不能为负数'
    }
    if (!formData.unit.trim()) {
      errors.unit = '请输入单位'
    }
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  // 保存加工项
  const handleSave = async () => {
    if (!validateForm()) return

    setSaving(true)
    try {
      if (editingItem) {
        await processingItemApi.updateProcessingItem(editingItem.id, formData)
        toast.success('更新成功')
      } else {
        await processingItemApi.createProcessingItem(formData)
        toast.success('创建成功')
      }
      setEditModalOpen(false)
      loadData()
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 删除加工项
  const handleDelete = (item: ProcessingItem) => {
    setDeletingItem(item)
    setDeleteModalOpen(true)
  }

  // 确认删除
  const confirmDelete = async () => {
    if (!deletingItem) return
    try {
      await processingItemApi.deleteProcessingItem(deletingItem.id)
      toast.success('删除成功')
      loadData()
    } catch (error) {
      toast.error('删除失败')
    } finally {
      setDeleteModalOpen(false)
      setDeletingItem(null)
    }
  }

  // 打开价格计算器
  const openCalcModal = (item: ProcessingItem) => {
    setCalculatingItem(item)
    setCalcParams({ width: '', height: '' })
    setCalcResult(null)
    setCalcModalOpen(true)
  }

  // 计算价格
  const handleCalculate = async () => {
    if (!calculatingItem) return
    
    const width = parseFloat(calcParams.width)
    const height = parseFloat(calcParams.height)
    
    if (!width || !height) {
      toast.error('请输入宽度和高度')
      return
    }

    setCalcLoading(true)
    try {
      const res = await processingItemApi.calculatePrice({
        processingItemId: calculatingItem.id,
        params: { width, height },
      })
      setCalcResult(res.data.data.price)
    } catch (error) {
      toast.error('计算失败')
    } finally {
      setCalcLoading(false)
    }
  }

  // 表格列
  const columns: TableColumn<ProcessingItem>[] = [
    {
      key: 'name',
      title: '名称',
      dataIndex: 'name',
    },
    {
      key: 'category',
      title: '加工分类',
      width: '120px',
      render: (record) => getCategoryName(record.categoryId),
    },
    {
      key: 'unit',
      title: '单位',
      width: '80px',
      dataIndex: 'unit',
    },
    {
      key: 'basePrice',
      title: '基础价格',
      width: '100px',
      render: (record) => `¥${(record.basePrice ?? 0).toFixed(2)}`,
    },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      render: (record) => (
        <Badge variant={record.status === 'active' ? 'success' : 'default'}>
          {record.status === 'active' ? '启用' : '停用'}
        </Badge>
      ),
    },
    {
      key: 'action',
      title: '操作',
      width: '200px',
      align: 'center',
      render: (record) => (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation()
              openCalcModal(record)
            }}
            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors"
            title="价格计算"
          >
            <Calculator className="w-4 h-4" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              openEditModal(record)
            }}
            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors"
            title="编辑"
          >
            <Edit2 className="w-4 h-4" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleDelete(record)
            }}
            className="p-1.5 text-red-600 hover:bg-red-50 rounded transition-colors"
            title="删除"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ),
    },
  ]

  // 搜索字段
  const searchFields = [
    {
      key: 'keyword',
      label: '关键词',
      type: 'input' as const,
      placeholder: '请输入加工项名称',
    },
    {
      key: 'categoryId',
      label: '加工分类',
      type: 'select' as const,
      placeholder: '请选择分类',
      options: [
        { value: '', label: '全部' },
        ...categories.map((cat) => ({ value: cat.id, label: cat.name })),
      ],
    },
  ]

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">加工项管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            管理窗帘加工项目，如打孔、折边等
          </p>
        </div>
        <Button onClick={() => openEditModal()}>
          <Plus className="w-4 h-4 mr-1.5" />
          新增加工项
        </Button>
      </div>

      {/* 搜索栏 */}
      <SearchBar
        fields={searchFields}
        onSearch={handleSearch}
        onReset={handleReset}
        loading={loading}
        className="mb-4"
      />

      {/* 数据表格 */}
      <div className="bg-white rounded-lg border border-gray-200">
        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey="id"
        />
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={setPageSize}
        />
      </div>

      {/* 新增/编辑模态框 */}
      <Modal
        open={editModalOpen}
        onClose={() => setEditModalOpen(false)}
        title={editingItem ? '编辑加工项' : '新增加工项'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditModalOpen(false)}>
              取消
            </Button>
            <Button onClick={handleSave} loading={saving}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="加工项名称"
            placeholder="如：打孔、折边、定型"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            error={formErrors.name}
            required
          />
          <div className="grid grid-cols-2 gap-4">
            <Select
              label="加工分类"
              placeholder="请选择分类"
              options={categories.map((cat) => ({ value: cat.id, label: cat.name }))}
              value={formData.categoryId}
              onChange={(e) => setFormData({ ...formData, categoryId: e.target.value })}
              error={formErrors.categoryId}
              required
            />
            <Select
              label="状态"
              options={[
                { value: 'active', label: '启用' },
                { value: 'inactive', label: '停用' },
              ]}
              value={formData.status}
              onChange={(e) => setFormData({ ...formData, status: e.target.value as 'active' | 'inactive' })}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="基础价格"
              type="number"
              placeholder="请输入基础价格"
              value={formData.basePrice || ''}
              onChange={(e) => setFormData({ ...formData, basePrice: parseFloat(e.target.value) || 0 })}
              error={formErrors.basePrice}
              required
            />
            <Input
              label="计价单位"
              placeholder="如：米、个、套"
              value={formData.unit}
              onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
              error={formErrors.unit}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              定价规则 (JSON)
            </label>
            <textarea
              rows={4}
              className="w-full px-3 py-2 rounded border border-gray-300 text-sm font-mono placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder={`{\n  "formula": "basePrice * width * height",\n  "minPrice": 10\n}`}
              value={JSON.stringify(formData.pricingRules || {}, null, 2)}
              onChange={(e) => {
                try {
                  const rules = JSON.parse(e.target.value)
                  setFormData({ ...formData, pricingRules: rules })
                } catch {
                  // 允许输入不合法的 JSON，不报错
                }
              }}
            />
            <p className="text-xs text-gray-500 mt-1">
              请输入有效的 JSON 格式定价规则
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              描述
            </label>
            <textarea
              rows={2}
              className="w-full px-3 py-2 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="请输入加工项描述"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
        </div>
      </Modal>

      {/* 删除确认模态框 */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteModalOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmDelete}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除加工项 <span className="font-medium text-gray-900">{deletingItem?.name}</span> 吗？
          此操作不可恢复。
        </p>
      </Modal>

      {/* 价格计算器模态框 */}
      <Modal
        open={calcModalOpen}
        onClose={() => setCalcModalOpen(false)}
        title={`价格计算 - ${calculatingItem?.name}`}
        width={400}
        footer={
          <Button onClick={() => setCalcModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="宽度 (米)"
              type="number"
              step="0.01"
              placeholder="如：2.5"
              value={calcParams.width}
              onChange={(e) => setCalcParams({ ...calcParams, width: e.target.value })}
            />
            <Input
              label="高度 (米)"
              type="number"
              step="0.01"
              placeholder="如：3.0"
              value={calcParams.height}
              onChange={(e) => setCalcParams({ ...calcParams, height: e.target.value })}
            />
          </div>
          <Button
            onClick={handleCalculate}
            loading={calcLoading}
            className="w-full"
          >
            <Calculator className="w-4 h-4 mr-1.5" />
            计算价格
          </Button>
          
          {calcResult !== null && (
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-sm text-gray-600 mb-1">计算结果</p>
              <p className="text-2xl font-bold text-blue-600">
                ¥{(calcResult ?? 0).toFixed(2)}
              </p>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
