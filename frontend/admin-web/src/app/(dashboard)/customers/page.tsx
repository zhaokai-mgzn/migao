'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Tags, X, Star } from 'lucide-react'
import { toast } from 'sonner'
import { customerApi } from '@/lib/api'
import { resolveImageUrl } from '@/lib/utils'
import { Table, Pagination, Modal, Button, Badge, Select, PageHeader, PageCard, SearchPanel, TableSkeleton } from '@/components/ui'
import { SEARCH_CONTROL_CLASS } from '@/components/ui/SearchPanel'
import type { TableColumn, SearchFieldSpec } from '@/components/ui'
import type { Customer, CustomerTag, CustomerTagFormData, CustomerChannel, CustomerListParams } from '@/types'
import { CustomerChannelLabels } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import ListLoadError from '@/components/common/ListLoadError'

// 柔和标签颜色
const TAG_COLORS = [
  '#48618f', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
  '#EC4899', '#06B6D4', '#F97316', '#14B8A6', '#6366F1',
]

// —— 字段适配工具 ——
// 后端 CustomerProfile 直接序列化返回，字段名为 wechatNickname / sourceChannel / avatarUrl 等。
// 这里统一处理 name / channel / vipLevel / avatar 的兜底取值，避免 "-"/"?" 满屏。

// 手机号脱敏：13880127933 -> 138****7933
const maskPhone = (phone?: string | null): string => {
  if (!phone) return ''
  const p = String(phone).trim()
  if (p.length < 7) return p
  return p.slice(0, 3) + '****' + p.slice(-4)
}

// 客户显示名：name > wechatNickname > nickname > 脱敏手机号 > 未命名
const getDisplayName = (c: Customer): string => {
  const n = (c.name || c.wechatNickname || c.nickname || '').trim()
  if (n) return n
  if (c.phone) return maskPhone(c.phone)
  return '未命名'
}

// 头像文字：姓名首字 > 手机号末2位 > #
const getAvatarInitials = (c: Customer): string => {
  const n = (c.name || c.wechatNickname || c.nickname || '').trim()
  if (n) return n.slice(0, 1)
  if (c.phone) return String(c.phone).slice(-2)
  return '#'
}

// 来源渠道：兼容 channel / sourceChannel
const getChannel = (c: Customer): CustomerChannel | undefined => {
  const v = (c.channel || c.sourceChannel) as CustomerChannel | undefined
  return v || undefined
}

// VIP 等级：兼容数字 / 字符串（normal/vip1/vip2/vip3）
const getVipLevelNum = (v: number | string | null | undefined): number => {
  if (v == null) return 0
  if (typeof v === 'number') return v
  const s = String(v).trim().toLowerCase()
  if (!s || s === 'normal') return 0
  const m = s.match(/(\d+)/)
  return m ? Number(m[1]) : 0
}

// 标签数组：后端可能返回 null / 非数组 JSON；列表接口返回标签 ID 字符串数组（#3660 冒烟发现），
// 类型上容忍 string | CustomerTag 混合，渲染层统一解析
const getTags = (c: Customer): Array<string | CustomerTag> => {
  if (Array.isArray(c.tags)) return c.tags as Array<string | CustomerTag>
  return []
}

export default function CustomersPage() {
  const router = useRouter()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  /** 读面失败标记（issue #6703）：读失败时计数行不得照旧印 0（会被读成「没有客户」） */
  const [loadError, setLoadError] = useState(false)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchParams, setSearchParams] = useState({ keyword: '', channel: '', vipLevel: '' })

  // 筛选控件的**受控值**（issue #7007：`SearchBar` 自带 state ⇒ 换成无状态的 `SearchPanel` 后，
  // 这三个值由页面持有；`searchParams` 仍是「已提交的查询」，两者语义与改动前逐值一致）。
  const [keyword, setKeyword] = useState('')
  const [channel, setChannel] = useState('')
  const [vipLevel, setVipLevel] = useState('')

  /**
   * 空态分流（issue #8040）：只看**已提交**的 `searchParams`（草稿不算 —— 与 `loadData` 同源），
   * 把「筛选下为空」与「真还没有客户」分成两句话。
   */
  const hasActiveFilter = Boolean(searchParams.keyword || searchParams.channel || searchParams.vipLevel)

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
  // 后端接收参数名为 sourceChannel 与字符串 vipLevel（vip1/vip2/vip3/normal），这里适配传参。
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
        keyword: searchParams.keyword || undefined,
      }
      if (searchParams.channel) params.sourceChannel = searchParams.channel
      if (searchParams.vipLevel) params.vipLevel = searchParams.vipLevel
      const res = await customerApi.getCustomers(params as CustomerListParams)
      const data = res.data.data
      setCustomers(data?.items || [])
      setTotal(data?.total || 0)
      setLoadError(false)
    } catch (error) {
      setLoadError(true)
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

  const handleSearch = () => {
    setCurrent(1)
    setSearchParams({
      keyword: keyword || '',
      channel: channel || '',
      vipLevel: vipLevel || '',
    })
  }

  const handleReset = () => {
    // 原 `SearchBar` 的「重置」会同时清空控件内的值（它自己持有 state）⇒ 这里显式清控件值，
    // 保证「点重置 ⇒ 输入框/下拉都回到空」逐值不变。
    setKeyword('')
    setChannel('')
    setVipLevel('')
    setCurrent(1)
    setSearchParams({ keyword: '', channel: '', vipLevel: '' })
  }

  // 获取渠道 Badge
  const getChannelBadge = (channel: CustomerChannel | undefined | null) => {
    if (!channel) return <span className="text-xs text-neutral-400">-</span>
    const variantMap: Record<CustomerChannel, 'success' | 'info' | 'default' | 'warning'> = {
      wechat_mini: 'success',
      wechat_mp: 'info',
      web: 'default',
      h5: 'info',
      order: 'warning',
    }
    return <Badge variant={variantMap[channel] || 'default'}>{CustomerChannelLabels[channel] || channel}</Badge>
  }

  // VIP 星级显示
  const renderVipLevel = (level: number) => {
    if (level === 0) return <span className="text-xs text-neutral-400">普通</span>
    return (
      <div className="flex items-center gap-0.5">
        {Array.from({ length: Math.min(level, 5) }).map((_, i) => (
          <Star key={i} className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
        ))}
      </div>
    )
  }

  // 头像：优先头像图片 > 姓名首字 > 手机号末2位 > 默认 #
  const renderAvatar = (customer: Customer) => {
    const colors = ['bg-primary-500', 'bg-green-500', 'bg-accent-500', 'bg-amber-500', 'bg-rose-500']
    const colorIdx = (String(customer.id || '0')).charCodeAt(0) % colors.length
    const avatarSrc = customer.avatarUrl || customer.avatar
    if (avatarSrc) {
      return (
        <img
          src={resolveImageUrl(avatarSrc)}
          alt={getDisplayName(customer)}
          className="w-9 h-9 rounded-full object-cover"
        />
      )
    }
    const initials = getAvatarInitials(customer)
    return (
      <div className={`w-9 h-9 rounded-full ${colors[colorIdx]} flex items-center justify-center text-white text-sm font-medium`}>
        {initials}
      </div>
    )
  }

  // 标签管理
  const openTagManager = useCallback(() => {
    setEditingTag(null)
    setTagForm({ name: '', color: TAG_COLORS[0] })
    setTagModalOpen(true)
  }, [])

  // 深链（issue #7526）：客户详情「标签」空态里的「去添加标签」带 `?manageTags=1` 进来 ⇒ 直接打开
  // 标签管理，不让商家回到列表页再自己找一遍。用 `window.location` 而不是 `useSearchParams`
  // （与入库单深链 #7524 同口径：少一层 Suspense 约束，也不给整模块 hook 替身多要一个导出）。
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (new URLSearchParams(window.location.search).get('manageTags') === '1') openTagManager()
  }, [openTagManager])

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

  // 删除标签：客户会绑标签 ⇒ 破坏性动作必须先确认（issue #6669 第 4 条）。
  // 修前是「点 ✕ 当场删」，没有任何二次确认，也没有「不可撤销」说明。
  const [deletingTag, setDeletingTag] = useState<CustomerTag | null>(null)

  const handleDeleteTag = async (tag: CustomerTag) => {
    try {
      await customerApi.deleteCustomerTag(tag.id)
      setTags(tags.filter((t) => t.id !== tag.id))
      toast.success('标签已删除')
    } catch (error) {
      toast.error('删除失败')
    } finally {
      setDeletingTag(null)
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
      render: (record) => {
        const displayName = getDisplayName(record)
        const sub = record.nickname || (record.wechatNickname && record.wechatNickname !== displayName ? record.wechatNickname : '')
        return (
          <div>
            <div className="font-medium text-neutral-900">{displayName}</div>
            {sub && <div className="text-xs text-neutral-500">{sub}</div>}
          </div>
        )
      },
    },
    {
      key: 'phone',
      title: '手机号',
      width: '130px',
      render: (record) => <span className="text-neutral-600">{record.phone || '-'}</span>,
    },
    {
      key: 'channel',
      title: '来源渠道',
      width: '120px',
      render: (record) => getChannelBadge(getChannel(record)),
    },
    {
      key: 'vipLevel',
      title: 'VIP 等级',
      width: '120px',
      render: (record) => renderVipLevel(getVipLevelNum(record.vipLevel)),
    },
    {
      key: 'tags',
      title: '标签',
      width: '200px',
      render: (record) => {
        // 列表接口 tags 为标签 ID 字符串数组（详情接口才是对象数组）——统一解析为标签对象，
        // 避免 key={undefined} 的 React 警告与空 chip（冒烟 #3660 发现）
        const tagList = getTags(record).map((t) => {
          if (typeof t === 'string') {
            return tags.find((tag) => tag.id === t) || { id: t, name: '', color: '' }
          }
          return t
        })
        return (
          <div className="flex flex-wrap gap-1">
            {tagList.length === 0 && <span className="text-xs text-neutral-400">-</span>}
            {tagList.map((tag) => (
              <span
                key={tag.id}
                className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                style={{
                  backgroundColor: (tag.color || '#999') + '15',
                  color: tag.color || '#999',
                  border: `1px solid ${tag.color || '#999'}30`,
                }}
              >
                {tag.name || ''}
              </span>
            ))}
          </div>
        )
      },
    },
    {
      key: 'lastActiveAt',
      title: '最后互动',
      width: '140px',
      // 🔴 issue #6669 第 4 条：本域日期**收敛到既有唯一展示组件** DateTimeCell（YYYY-MM-DD / HH:mm 两行）。
      // 修前这里是 `dayjs(...).format('MM-DD HH:mm')` —— **无年份**，而同域客户详情页是 `YYYY-MM-DD HH:mm`，
      // 同一个「最后互动」在两页长得不一样（跨年的单看起来像今年）。别再就地写 format 字符串。
      render: (record) => <DateTimeCell value={record.lastActiveAt} />,
    },
  ]

  // 筛选字段（issue #7007）：原 `SearchBar` 的声明式 `{type,options}` 换成 `SearchPanel` 的
  // `{label, control}` —— 选项文案 / 顺序 / 值逐字不变，控件是受控的，state 在页面持有。
  const searchPanelFields: SearchFieldSpec[] = [
    {
      key: 'keyword',
      label: '关键词',
      control: (
        <input
          type="text"
          placeholder="客户名/手机号"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          className={SEARCH_CONTROL_CLASS}
        />
      ),
    },
    {
      key: 'channel',
      label: '来源渠道',
      control: (
        <Select
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          options={[
            { value: '', label: '全部' },
            { value: 'wechat_mini', label: '微信小程序' },
            { value: 'wechat_mp', label: '公众号' },
            { value: 'web', label: 'Web' },
            { value: 'order', label: '订单' },
          ]}
        />
      ),
    },
    {
      // 后端 vipLevel 为字符串：normal/vip1/vip2/vip3
      key: 'vipLevel',
      label: 'VIP 等级',
      control: (
        <Select
          value={vipLevel}
          onChange={(e) => setVipLevel(e.target.value)}
          options={[
            { value: '', label: '全部' },
            { value: 'normal', label: '普通' },
            { value: 'vip1', label: 'VIP 1' },
            { value: 'vip2', label: 'VIP 2' },
            { value: 'vip3', label: 'VIP 3' },
          ]}
        />
      ),
    },
  ]

  return (
    <div className="p-6 space-y-4">
      {/* 页面标题 */}
      <PageHeader
        title="客户管理"
        subtitle="管理客户信息、标签和互动记录"
        actions={
          <Button variant="secondary" onClick={openTagManager}>
            <Tags className="w-4 h-4 mr-1.5" />
            标签管理
          </Button>
        }
      />

      {/* 搜索栏 */}
      <SearchPanel fields={searchPanelFields} onSearch={handleSearch} onReset={handleReset} loading={loading} />

      {/* 数据表格 */}
      <PageCard testId="customers-empty">
        {loadError && (
          // 失败态 ≠ 空态（issue #6703）：说清「不是没有客户，是没读到」+ 真重发出口
          <div className="p-4 pb-0">
            <ListLoadError
              testId="customers-load-error"
              message="客户列表加载失败 —— 没读到数据，下面的条数不可信。请检查网络后重试。"
              onRetry={() => void loadData()}
              retrying={loading}
            />
          </div>
        )}
        {/* issue #8048：加载态 = 通用表格骨架（#8036 口径：页面级三元），与 7 列对齐；
            不再让共享 `Table` 的 loading 分支印裸「加载中…」+ 空白表体。
            🔴 只在**首次加载**（列表为空）出骨架：标签增删 / 查询会触发刷新，刷新时已有读数 ⇒
            表格照旧在场（同 `quality-inspections` 的 `recordsLoading && pagedRecords.length === 0` 口径）。 */}
        {loading && customers.length === 0 ? (
          <TableSkeleton rows={pageSize} columns={7} />
        ) : (
        <Table
          columns={columns}
          dataSource={customers}
          loading={loading}
          rowKey="id"
          onRowClick={(record) => router.push(`/customers/${record.id}`)}
          /* 🔴 issue #6728：读失败 ⇒ 表体**不得**印空态文案（那是「没有客户」的事实性断言，
             而真相是**没读到** —— 失败面已在上面，且条数已标不可信）。共享 `ui/Table` 的默认
             `emptyText` 是**全站默认值**（不动它）⇒ 本单**页面级**覆盖：失败时空串，
             读成功才印下面的空态文案。
             issue #8040：空态**分流**（筛选下为空 / 真还没有客户）+ 说清客户从哪来。 */
          emptyText={
            loadError
              ? ''
              : hasActiveFilter
                ? '没有符合筛选条件的客户 —— 换个关键词、渠道或客户等级再查一次'
                : '还没有客户 —— 客户在对话里留过联系方式、或下过单后会自动建档'
          }
        />
        )}
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          totalReliable={!loadError}
          onChange={setCurrent}
          onPageSizeChange={setPageSize}
        />
      </PageCard>

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
              <label className="block text-sm font-medium text-neutral-700 mb-1.5">
                {editingTag ? '编辑标签' : '新建标签'}
              </label>
              <input
                type="text"
                className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                placeholder="标签名称"
                value={tagForm.name}
                onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-neutral-700 mb-1.5">颜色</label>
              <div className="flex gap-1.5">
                {TAG_COLORS.slice(0, 6).map((color) => (
                  <button
                    key={color}
                    className={`w-7 h-7 rounded-full border-2 transition-all ${
                      tagForm.color === color ? 'border-neutral-900 scale-110' : 'border-transparent'
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
          <div className="border-t border-neutral-200 pt-4">
            <h4 className="text-sm font-medium text-neutral-700 mb-3">已有标签</h4>
            {tags.length === 0 ? (
              <p className="text-sm text-neutral-500 text-center py-4">
                还没有标签 —— 在上面的输入框里填名称新建一个，之后就能按标签筛客户
              </p>
            ) : (
              <div className="space-y-2">
                {tags.map((tag) => (
                  <div key={tag.id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-neutral-50">
                    <div className="flex items-center gap-2">
                      <span className="w-4 h-4 rounded-full" style={{ backgroundColor: tag.color }} />
                      <span className="text-sm font-medium text-neutral-900">{tag.name}</span>
                      {tag.customerCount !== undefined && (
                        <span className="text-xs text-neutral-400">({tag.customerCount})</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        className="p-1 text-neutral-400 hover:text-primary-600 transition-colors"
                        onClick={() => { setEditingTag(tag); setTagForm({ name: tag.name, color: tag.color }) }}
                      >
                        <span className="text-xs">编辑</span>
                      </button>
                      <button
                        className="p-1 text-neutral-400 hover:text-red-600 transition-colors"
                        aria-label={`删除标签 ${tag.name}`}
                        data-testid={`tag-delete-${tag.id}`}
                        onClick={() => setDeletingTag(tag)}
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

      {/* 删除标签确认（issue #6669 第 4 条）：标签会被客户绑定 ⇒ 破坏性动作先说清后果再动手 */}
      <Modal
        open={deletingTag !== null}
        onClose={() => setDeletingTag(null)}
        title="确认删除标签"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeletingTag(null)}>取消</Button>
            <Button
              variant="danger"
              data-testid="tag-delete-confirm"
              onClick={() => deletingTag && void handleDeleteTag(deletingTag)}
            >
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-neutral-600">
          删除标签 <span className="font-medium text-neutral-900">{deletingTag?.name}</span>
          {deletingTag?.customerCount !== undefined && deletingTag.customerCount > 0
            ? `（当前有 ${deletingTag.customerCount} 位客户绑着它）`
            : ''}
          ：客户档案上的这个标签会一并解除，删除后无法恢复。如需继续使用，请改用「编辑」。
        </p>
      </Modal>
    </div>
  )
}
