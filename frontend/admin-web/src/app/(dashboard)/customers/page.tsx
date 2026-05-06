'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Tags, X, Star } from 'lucide-react'
import { toast } from 'sonner'
import { customerApi } from '@/lib/api'
import { Table, Pagination, Modal, Button, Badge, SearchBar } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { Customer, CustomerTag, CustomerTagFormData, CustomerChannel, CustomerListParams } from '@/types'
import { CustomerChannelLabels } from '@/types'
import dayjs from 'dayjs'

// 柔和标签颜色
const TAG_COLORS = [
  '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
  '#EC4899', '#06B6D4', '#F97316', '#14B8A6', '#6366F1',
]

export default function CustomersPage() {
  const router = useRouter()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchParams, setSearchParams] = useState({ keyword: '', channel: '', vipLevel: '' })

  // 标签管理状态
  const [tagModalOpen, setTagModalOpen] = useState(false)
  const [tags, setTags] = useState<CustomerTag[]>([])
  const [tagForm, setTagForm] = useState<CustomerTagFormData>({ name: '', color: TAG_COLORS[0] })
  const [editingTag, setEditingTag] = useState<CustomerTag | null>(null)
  const [tagLoading, setTagLoading] = useState(false)

  // 加载标签
  const loadTags = useCallback(async () => {
    try {
      const res = await customerApi.getCustomerTags()
      setTags(res.data.data || [])
    } catch (error) {
      console.error('加载标签失败:', error)
    }
  }, [])

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await customerApi.getCustomers({
        page: current,
        size: pageSize,
        keyword: searchParams.keyword || undefined,
        channel: (searchParams.channel as CustomerChannel) || undefined,
        vipLevel: searchParams.vipLevel ? Number(searchParams.vipLevel) : undefined,
      })
      const data = res.data.data
      setCustomers(data?.items || [])
      setTotal(data?.total || 0)
    } catch (error) {
      toast.error('加载客户数据失败')
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchParams])

  useEffect(() => {
    loadTags()
  }, [loadTags])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleSearch = (values: Record<string, string>) => {
    setCurrent(1)
    setSearchParams({
      keyword: values.keyword || '',
      channel: values.channel || '',
      vipLevel: values.vipLevel || '',
    })
  }

  const handleReset = () => {
    setCurrent(1)
    setSearchParams({ keyword: '', channel: '', vipLevel: '' })
  }

  // 获取渠道 Badge
  const getChannelBadge = (channel: CustomerChannel) => {
    const variantMap: Record<CustomerChannel, 'success' | 'info' | 'default'> = {
      wechat_mini: 'success',
      wechat_mp: 'info',
      web: 'default',
    }
    return <Badge variant={variantMap[channel]}>{CustomerChannelLabels[channel]}</Badge>
  }

  // VIP 星级显示
  const renderVipLevel = (level: number) => {
    if (level === 0) return <span className="text-xs text-gray-400">普通</span>
    return (
      <div className="flex items-center gap-0.5">
        {Array.from({ length: Math.min(level, 5) }).map((_, i) => (
          <Star key={i} className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
        ))}
      </div>
    )
  }

  // 头像
  const renderAvatar = (customer: Customer) => {
    const initials = customer.name.slice(0, 1)
    const colors = ['bg-blue-500', 'bg-green-500', 'bg-purple-500', 'bg-amber-500', 'bg-rose-500']
    const colorIdx = customer.id.charCodeAt(0) % colors.length
    return (
      <div className={`w-9 h-9 rounded-full ${colors[colorIdx]} flex items-center justify-center text-white text-sm font-medium`}>
        {initials}
      </div>
    )
  }

  // 标签管理
  const openTagManager = () => {
    setEditingTag(null)
    setTagForm({ name: '', color: TAG_COLORS[0] })
    setTagModalOpen(true)
  }

  const handleSaveTag = async () => {
    if (!tagForm.name.trim()) {
      toast.error('请输入标签名称')
      return
    }
    setTagLoading(true)
    try {
      if (editingTag) {
        await customerApi.updateCustomerTag(editingTag.id, tagForm)
        toast.success('标签更新成功')
      } else {
        await customerApi.createCustomerTag(tagForm)
        toast.success('标签创建成功')
      }
      await loadTags()
      setEditingTag(null)
      setTagForm({ name: '', color: TAG_COLORS[0] })
    } catch (error) {
      toast.error('操作失败')
    } finally {
      setTagLoading(false)
    }
  }

  const handleDeleteTag = async (tag: CustomerTag) => {
    try {
      await customerApi.deleteCustomerTag(tag.id)
      setTags(tags.filter((t) => t.id !== tag.id))
      toast.success('标签已删除')
    } catch (error) {
      toast.error('删除失败')
    }
  }

  // 表格列
  const columns: TableColumn<Customer>[] = [
    {
      key: 'avatar',
      title: '头像',
      width: '60px',
      render: (record) => renderAvatar(record),
    },
    {
      key: 'name',
      title: '客户名',
      render: (record) => (
        <div>
          <div className="font-medium text-gray-900">{record.name}</div>
          {record.nickname && <div className="text-xs text-gray-500">{record.nickname}</div>}
        </div>
      ),
    },
    {
      key: 'phone',
      title: '手机号',
      width: '130px',
      render: (record) => <span className="text-gray-600">{record.phone || '-'}</span>,
    },
    {
      key: 'channel',
      title: '来源渠道',
      width: '120px',
      render: (record) => getChannelBadge(record.channel),
    },
    {
      key: 'vipLevel',
      title: 'VIP 等级',
      width: '120px',
      render: (record) => renderVipLevel(record.vipLevel),
    },
    {
      key: 'tags',
      title: '标签',
      width: '200px',
      render: (record) => (
        <div className="flex flex-wrap gap-1">
          {record.tags.length === 0 && <span className="text-xs text-gray-400">-</span>}
          {record.tags.map((tag) => (
            <span
              key={tag.id}
              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
              style={{
                backgroundColor: tag.color + '15',
                color: tag.color,
                border: `1px solid ${tag.color}30`,
              }}
            >
              {tag.name}
            </span>
          ))}
        </div>
      ),
    },
    {
      key: 'lastActiveAt',
      title: '最后互动',
      width: '140px',
      render: (record) =>
        record.lastActiveAt ? dayjs(record.lastActiveAt).format('MM-DD HH:mm') : '-',
    },
  ]

  const searchFields = [
    { key: 'keyword', label: '关键词', type: 'input' as const, placeholder: '客户名/手机号' },
    {
      key: 'channel', label: '来源渠道', type: 'select' as const, placeholder: '请选择',
      options: [
        { value: '', label: '全部' },
        { value: 'wechat_mini', label: '微信小程序' },
        { value: 'wechat_mp', label: '公众号' },
        { value: 'web', label: 'Web' },
      ],
    },
    {
      key: 'vipLevel', label: 'VIP 等级', type: 'select' as const, placeholder: '请选择',
      options: [
        { value: '', label: '全部' },
        { value: '0', label: '普通' },
        { value: '1', label: 'VIP 1' },
        { value: '2', label: 'VIP 2' },
        { value: '3', label: 'VIP 3' },
        { value: '4', label: 'VIP 4' },
        { value: '5', label: 'VIP 5' },
      ],
    },
  ]

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">客户管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理客户信息、标签和互动记录</p>
        </div>
        <Button variant="secondary" onClick={openTagManager}>
          <Tags className="w-4 h-4 mr-1.5" />
          标签管理
        </Button>
      </div>

      {/* 搜索栏 */}
      <SearchBar fields={searchFields} onSearch={handleSearch} onReset={handleReset} loading={loading} className="mb-4" />

      {/* 数据表格 */}
      <div className="bg-white rounded-lg border border-gray-200">
        <Table
          columns={columns}
          dataSource={customers}
          loading={loading}
          rowKey="id"
          onRowClick={(record) => router.push(`/customers/${record.id}`)}
        />
        <Pagination current={current} pageSize={pageSize} total={total} onChange={setCurrent} onPageSizeChange={setPageSize} />
      </div>

      {/* 标签管理模态框 */}
      <Modal
        open={tagModalOpen}
        onClose={() => setTagModalOpen(false)}
        title="标签管理"
        width={560}
        footer={<Button variant="secondary" onClick={() => setTagModalOpen(false)}>关闭</Button>}
      >
        <div className="space-y-4">
          {/* 创建/编辑标签表单 */}
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                {editingTag ? '编辑标签' : '新建标签'}
              </label>
              <input
                type="text"
                className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                placeholder="标签名称"
                value={tagForm.name}
                onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">颜色</label>
              <div className="flex gap-1.5">
                {TAG_COLORS.slice(0, 6).map((color) => (
                  <button
                    key={color}
                    className={`w-7 h-7 rounded-full border-2 transition-all ${
                      tagForm.color === color ? 'border-gray-900 scale-110' : 'border-transparent'
                    }`}
                    style={{ backgroundColor: color }}
                    onClick={() => setTagForm({ ...tagForm, color })}
                  />
                ))}
              </div>
            </div>
            <Button size="sm" onClick={handleSaveTag} loading={tagLoading}>
              {editingTag ? '更新' : '添加'}
            </Button>
            {editingTag && (
              <Button size="sm" variant="secondary" onClick={() => { setEditingTag(null); setTagForm({ name: '', color: TAG_COLORS[0] }) }}>
                取消
              </Button>
            )}
          </div>

          {/* 标签列表 */}
          <div className="border-t border-gray-200 pt-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">已有标签</h4>
            {tags.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-4">暂无标签</p>
            ) : (
              <div className="space-y-2">
                {tags.map((tag) => (
                  <div key={tag.id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-gray-50">
                    <div className="flex items-center gap-2">
                      <span className="w-4 h-4 rounded-full" style={{ backgroundColor: tag.color }} />
                      <span className="text-sm font-medium text-gray-900">{tag.name}</span>
                      {tag.customerCount !== undefined && (
                        <span className="text-xs text-gray-400">({tag.customerCount})</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        className="p-1 text-gray-400 hover:text-blue-600 transition-colors"
                        onClick={() => { setEditingTag(tag); setTagForm({ name: tag.name, color: tag.color }) }}
                      >
                        <span className="text-xs">编辑</span>
                      </button>
                      <button
                        className="p-1 text-gray-400 hover:text-red-600 transition-colors"
                        onClick={() => handleDeleteTag(tag)}
                      >
                        <X className="w-4 h-4" />
                      </button>
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
