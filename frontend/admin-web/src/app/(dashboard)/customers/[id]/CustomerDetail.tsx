'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Phone, MapPin, Star, Plus, X, MessageSquare, ShoppingCart, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Badge, SELECT_CONTROL } from '@/components/ui'
import { useRouteId } from '@/lib/use-route-id'
import { customerApi } from '@/lib/api'
import type { CustomerDetail, CustomerTag, CustomerOrder, CustomerSession, CustomerChannel, CustomerDetailResponse, CustomerCreditStatus } from '@/types'
import { CustomerChannelLabels } from '@/types'
import { LOGISTICS_COMPANIES, LOGISTICS_TYPES } from '@/lib/logistics'
import dayjs from 'dayjs'
import { cn } from '@/lib/utils'

const fmtMoney = (v: number | null | undefined) =>
  v == null ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const TAG_COLORS = [
  '#48618f', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
  '#EC4899', '#06B6D4', '#F97316', '#14B8A6', '#6366F1',
]

// —— 后端详情响应 → 前端平铺 CustomerDetail 字段映射 ——
// 后端 GET /api/admin/customers/{id} 返回 { id, profile, tags, orders, sessions }，
// profile 使用 wechatNickname / sourceChannel / agentNotes / registeredAt 等原始字段。
// 默认收货信息与常用物流（issue #4419 / #3984）原样透传，供「收货信息」卡片读写。
function mapCustomerDetail(detail: CustomerDetailResponse): CustomerDetail {
  const profile = detail.profile ?? {}
  return {
    id: detail.id,
    name: profile.wechatNickname,
    phone: profile.phone,
    channel: profile.sourceChannel as CustomerChannel,
    vipLevel: profile.vipLevel,
    remark: profile.agentNotes,
    lastActiveAt: profile.lastActiveAt,
    createdAt: profile.registeredAt,
    tags: detail.tags ?? [],
    orders: detail.orders ?? [],
    sessions: detail.sessions ?? [],
    defaultReceiverName: profile.defaultReceiverName,
    defaultReceiverPhone: profile.defaultReceiverPhone,
    defaultReceiverAddress: profile.defaultReceiverAddress,
    defaultLogisticsType: profile.defaultLogisticsType,
    defaultLogisticsCompany: profile.defaultLogisticsCompany,
  }
}

/** 「收货信息」卡片的表单状态（客户默认收货地址 + 常用物流档案，issue #4419） */
interface ReceiverForm {
  name: string
  phone: string
  address: string
  logisticsType: string
  logisticsCompany: string
}

/** 字段中文名（仅用于「暂不支持清空」的提示文案，issue #4443） */
const RECEIVER_LABELS: Record<keyof ReceiverForm, string> = {
  name: '收货人姓名',
  phone: '收货人电话',
  address: '收货地址',
  logisticsType: '常用物流方式',
  logisticsCompany: '常用物流公司',
}

export default function CustomerDetailPage() {
  const router = useRouter()
  const id = useRouteId('id')

  const [customer, setCustomer] = useState<CustomerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  // 🔴 只有「订单历史 / 会话历史」两个页签（issue #6669 第 1 条）：原第三个页签「跟进记录」的正文
  // 逐字是「暂无跟进记录，功能开发中...」—— 试用现场点一次就等于把「没做完」写在商家脸上。
  // 该功能**本期不做** ⇒ 直接**收起页签**（判据：`queryByText('跟进记录')` 取不到，见
  // frontend/admin-web/tests/unit/pages/customer-detail.test.tsx 的「未完成页签不出入口」）。
  // ⚠️ 别只把文案改软 —— 「点得到但永远说没有」仍是同一个缺陷形态。
  const [activeTab, setActiveTab] = useState<'orders' | 'sessions'>('orders')
  const [remark, setRemark] = useState('')
  const [savingRemark, setSavingRemark] = useState(false)

  // 收货信息（客户默认收货地址 + 常用物流档案，issue #4419）
  const [receiver, setReceiver] = useState<ReceiverForm>({
    name: '', phone: '', address: '', logisticsType: 'express', logisticsCompany: '',
  })
  // 服务端真值快照：判断「用户改了什么 / 清空了什么」的基准（issue #4443）
  const [receiverBaseline, setReceiverBaseline] = useState<ReceiverForm>({
    name: '', phone: '', address: '', logisticsType: 'express', logisticsCompany: '',
  })
  const [savingReceiver, setSavingReceiver] = useState(false)

  // 授信与往来（issue #7370）
  const [credit, setCredit] = useState<CustomerCreditStatus | null>(null)
  const [creditLimitInput, setCreditLimitInput] = useState('')
  const [creditTermsInput, setCreditTermsInput] = useState('')
  const [savingCredit, setSavingCredit] = useState(false)

  // 标签管理
  const [allTags, setAllTags] = useState<CustomerTag[]>([])
  const [showTagPicker, setShowTagPicker] = useState(false)

  const loadCustomer = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      // 并行加载：客户详情 + 全量标签定义
      const [detailRes, tagsRes, creditRes] = await Promise.all([
        customerApi.getCustomer(id),
        customerApi.getCustomerTags(),
        customerApi.getCredit(id),
      ])
      const detail = detailRes.data.data
      setAllTags(tagsRes.data.data || [])
      const creditData = creditRes.data.data
      setCredit(creditData)
      setCreditLimitInput(creditData?.creditLimit == null ? '' : String(creditData.creditLimit))
      setCreditTermsInput(creditData?.paymentTermsDays == null ? '' : String(creditData.paymentTermsDays))
      const mapped = mapCustomerDetail(detail)
      setCustomer(mapped)
      setRemark(mapped.remark || '')
      const loadedReceiver: ReceiverForm = {
        name: mapped.defaultReceiverName || '',
        phone: mapped.defaultReceiverPhone || '',
        address: mapped.defaultReceiverAddress || '',
        // 缺省 express 与 customer_profiles.default_logistics_type 的列默认值一致（V47）
        logisticsType: mapped.defaultLogisticsType || 'express',
        logisticsCompany: mapped.defaultLogisticsCompany || '',
      }
      setReceiver(loadedReceiver)
      setReceiverBaseline(loadedReceiver)
    } catch (error) {
      toast.error('加载客户信息失败')
      console.error('加载客户信息失败:', error)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadCustomer()
  }, [loadCustomer])

  const handleSaveRemark = async () => {
    if (!customer) return
    setSavingRemark(true)
    try {
      await customerApi.updateCustomer(id, { remark })
      setCustomer({ ...customer, remark })
      toast.success('备注已保存')
    } catch (error) {
      toast.error('保存失败')
      console.error('保存备注失败:', error)
    } finally {
      setSavingRemark(false)
    }
  }

  // 保存收货信息 + 常用物流档案（issue #4419；**反馈口径**见 #4443）。
  // 后端 updateCustomer 是「非空拷贝」语义：空白**一律不覆盖**（#4419 有意为之，由
  // CustomerReceiverAddressPersistTest.updateCustomer_BlankReceiverFieldsDoNotWipeExisting 钉住）。
  // ⇒ 前端不得把「清空」报成成功：① 空白键不下发；② 清空了原本非空的字段时**明确告知不支持**，
  //    并把输入框恢复成服务端真值（否则界面显示空白 = 又一次谎报）；③ 完全没改动时不报「已保存」。
  const handleSaveReceiver = async () => {
    if (!customer) return

    const changedKeys = (Object.keys(receiver) as (keyof ReceiverForm)[])
      .filter((k) => receiver[k] !== receiverBaseline[k])
    if (changedKeys.length === 0) {
      toast.info('收货信息没有改动')
      return
    }
    // 清空 = 后端不会执行 ⇒ 这些字段要恢复显示服务端真值，并如实告知
    const clearedKeys = changedKeys.filter((k) => receiver[k].trim() === '')
    const clearedLabel = clearedKeys.map((k) => RECEIVER_LABELS[k]).join('、')
    const commitReceiverState = () => {
      const next: ReceiverForm = { ...receiver }
      for (const k of clearedKeys) next[k] = receiverBaseline[k]
      setReceiver(next)
      setReceiverBaseline(next)
    }

    // 只有清空、没有可落库的改动 ⇒ 一个请求都不该发，更不能报成功
    if (clearedKeys.length === changedKeys.length) {
      toast.warning(`暂不支持清空：${clearedLabel}`)
      commitReceiverState()
      return
    }

    const payload = {
      defaultReceiverName: receiver.name.trim(),
      defaultReceiverPhone: receiver.phone.trim(),
      defaultReceiverAddress: receiver.address.trim(),
      defaultLogisticsType: receiver.logisticsType,
      defaultLogisticsCompany: receiver.logisticsCompany.trim(),
    }
    // 空白键不下发（下发也无效，只会让人以为已清空）
    const sendable: Partial<typeof payload> = Object.fromEntries(
      Object.entries(payload).filter(([, v]) => v !== ''),
    )

    setSavingReceiver(true)
    try {
      await customerApi.updateCustomer(id, sendable)
      setCustomer({ ...customer, ...sendable })
      commitReceiverState()
      if (clearedKeys.length > 0) {
        toast.warning(`已保存其余改动；暂不支持清空：${clearedLabel}`)
      } else {
        toast.success('收货信息已保存')
      }
    } catch (error) {
      toast.error('保存失败')
      console.error('保存收货信息失败:', error)
    } finally {
      setSavingReceiver(false)
    }
  }

  const handleSaveCredit = async () => {
    if (!id) return
    const limit = creditLimitInput.trim() === '' ? null : Number(creditLimitInput)
    const terms = creditTermsInput.trim() === '' ? null : Number(creditTermsInput)
    if (limit != null && (Number.isNaN(limit) || limit < 0)) {
      toast.error('授信额度必须是不小于 0 的数字（留空 = 不启用授信）')
      return
    }
    if (terms != null && (Number.isNaN(terms) || terms < 0 || terms > 365)) {
      toast.error('账期天数须在 0~365 之间（0 = 现结）')
      return
    }
    setSavingCredit(true)
    try {
      const res = await customerApi.updateCredit(id, { creditLimit: limit, paymentTermsDays: terms })
      setCredit(res.data.data)
      toast.success('授信设置已保存')
    } catch (error) {
      toast.error('保存授信失败')
      console.error('保存授信失败:', error)
    } finally {
      setSavingCredit(false)
    }
  }

  const handleAddTag = async (tag: CustomerTag) => {
    if (!customer) return
    const tags = customer.tags || []
    if (tags.find((t) => t.id === tag.id)) {
      toast.info('该标签已存在')
      return
    }
    try {
      // 先落库，成功后再更新本地状态
      await customerApi.addTagToCustomer(id, tag.id)
      setCustomer({ ...customer, tags: [...tags, tag] })
      setShowTagPicker(false)
      toast.success(`已添加标签「${tag.name}」`)
    } catch (error) {
      toast.error('添加标签失败')
      console.error('添加标签失败:', error)
    }
  }

  const handleRemoveTag = async (tagId: string) => {
    if (!customer) return
    try {
      // 先落库，成功后再更新本地状态
      await customerApi.removeTagFromCustomer(id, tagId)
      setCustomer({ ...customer, tags: (customer.tags || []).filter((t) => t.id !== tagId) })
      toast.success('已移除标签')
    } catch (error) {
      toast.error('移除标签失败')
      console.error('移除标签失败:', error)
    }
  }

  const getChannelLabel = (channel: CustomerChannel | string | undefined) => {
    if (!channel) return ''
    return CustomerChannelLabels[channel as CustomerChannel] || String(channel)
  }

  const getOrderStatusLabel = (status: string) => {
    const map: Record<string, { label: string; variant: 'success' | 'warning' | 'info' | 'default' | 'error' }> = {
      pending: { label: '待确认', variant: 'warning' },
      confirmed: { label: '已确认', variant: 'info' },
      producing: { label: '生产中', variant: 'info' },
      completed: { label: '已完成', variant: 'success' },
      cancelled: { label: '已取消', variant: 'default' },
    }
    return map[status] || { label: status, variant: 'default' as const }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="flex items-center gap-2 text-neutral-500">
          <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          加载中...
        </div>
      </div>
    )
  }

  if (!customer) {
    return (
      <div className="p-6 text-center text-neutral-500">
        <p>客户不存在</p>
        <Button variant="secondary" className="mt-4" onClick={() => router.back()}>返回</Button>
      </div>
    )
  }

  const initials = (customer.name || '?').slice(0, 1)
  const availableTags = allTags.filter((t) => !((customer.tags || []).find((ct) => ct.id === t.id)))
  const vipLevelNum = typeof customer.vipLevel === 'number'
    ? customer.vipLevel
    : (() => {
        const m = String(customer.vipLevel ?? '').toLowerCase().match(/(\d+)/)
        return m ? Number(m[1]) : 0
      })()

  return (
    <div className="p-6">
      {/* 返回按钮 */}
      <button onClick={() => router.back()} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-900 mb-4 transition-colors">
        <ArrowLeft className="w-4 h-4" />
        返回客户列表
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：客户信息卡片 */}
        <div className="lg:col-span-1 space-y-4">
          {/* 授信与往来（issue #7370）：额度 / 账期 / 已欠 / 可用 */}
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-neutral-900">授信与往来</h3>
              <span className="text-xs text-neutral-500" data-testid="credit-available">
                {credit?.creditLimit == null ? '未启用授信' : `可用 ¥${fmtMoney(credit?.available)}`}
              </span>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-neutral-500 mb-1">授信额度（元，留空 = 不启用）</label>
                <input
                  data-testid="credit-limit"
                  type="number"
                  min={0}
                  step="0.01"
                  value={creditLimitInput}
                  onChange={(e) => setCreditLimitInput(e.target.value)}
                  placeholder="不限"
                  className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="block text-xs text-neutral-500 mb-1">账期天数（0 = 现结）</label>
                <input
                  data-testid="credit-terms"
                  type="number"
                  min={0}
                  max={365}
                  value={creditTermsInput}
                  onChange={(e) => setCreditTermsInput(e.target.value)}
                  placeholder="未设置"
                  className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div className="flex items-center justify-between text-xs text-neutral-500">
                <span>已欠 ¥{fmtMoney(credit?.outstanding)}</span>
              </div>
              <Button size="sm" onClick={handleSaveCredit} disabled={savingCredit}>
                {savingCredit ? '保存中...' : '保存授信'}
              </Button>
            </div>
          </div>

          {/* 基本信息 */}
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <div className="flex items-center gap-4 mb-4">
              <div className="w-16 h-16 rounded-full bg-primary-500 flex items-center justify-center text-white text-2xl font-bold">
                {initials}
              </div>
              <div>
                <h2 className="text-lg font-semibold text-neutral-900">{customer.name || '未知客户'}</h2>
                {customer.nickname && <p className="text-sm text-neutral-500">{customer.nickname}</p>}
                <div className="flex items-center gap-1 mt-1">
                  {vipLevelNum > 0 ? (
                    Array.from({ length: vipLevelNum }).map((_, i) => (
                      <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                    ))
                  ) : (
                    <span className="text-xs text-neutral-400">普通客户</span>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2 text-neutral-600">
                <Phone className="w-4 h-4 text-neutral-400" />
                <span>{customer.phone || '未填写'}</span>
              </div>
              <div className="flex items-center gap-2 text-neutral-600">
                <MapPin className="w-4 h-4 text-neutral-400" />
                <Badge variant="info">{getChannelLabel(customer.channel)}</Badge>
              </div>
              <div className="text-xs text-neutral-400 pt-2 border-t border-neutral-100">
                <div>注册时间：{dayjs(customer.createdAt).format('YYYY-MM-DD')}</div>
                <div>最后互动：{dayjs(customer.lastActiveAt).format('YYYY-MM-DD HH:mm')}</div>
              </div>
            </div>
          </div>

          {/* 收货信息 + 常用物流档案（issue #4419）：客户默认收货地址与常用承运商，
              新增订单选客户时逐字带出（defaultReceiverAddress 优先），发货页带出常用物流方式/公司。 */}
          <div className="bg-white border border-neutral-200 rounded-lg p-6" data-testid="receiver-card">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-neutral-900">收货信息</h3>
              <Button
                size="sm"
                variant="ghost"
                data-testid="save-receiver"
                onClick={handleSaveReceiver}
                loading={savingReceiver}
              >
                <Save className="w-3.5 h-3.5 mr-1" />
                保存
              </Button>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-neutral-500">收货人姓名</span>
                <input
                  className="mt-1 w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  placeholder="收货人姓名"
                  value={receiver.name}
                  onChange={(e) => setReceiver({ ...receiver, name: e.target.value })}
                />
              </label>
              <label className="block">
                <span className="text-xs text-neutral-500">收货人电话</span>
                <input
                  className="mt-1 w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  placeholder="收货人电话"
                  value={receiver.phone}
                  onChange={(e) => setReceiver({ ...receiver, phone: e.target.value })}
                />
              </label>
              <label className="block">
                <span className="text-xs text-neutral-500">收货地址</span>
                <textarea
                  rows={2}
                  className="mt-1 w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
                  placeholder="省市区 + 详细地址"
                  value={receiver.address}
                  onChange={(e) => setReceiver({ ...receiver, address: e.target.value })}
                />
              </label>
              <label className="block">
                <span className="text-xs text-neutral-500">常用物流方式</span>
                <select
                  className={cn(SELECT_CONTROL, 'mt-1', 'w-full')}
                  value={receiver.logisticsType}
                  onChange={(e) => setReceiver({ ...receiver, logisticsType: e.target.value })}
                >
                  {LOGISTICS_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-neutral-500">常用物流公司</span>
                {/* datalist = 预置承运商下拉 + 允许自定义（承运商列是自由文本，不做白名单校验） */}
                <input
                  list="receiver-logistics-companies"
                  className="mt-1 w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  placeholder="选择或输入承运商"
                  value={receiver.logisticsCompany}
                  onChange={(e) => setReceiver({ ...receiver, logisticsCompany: e.target.value })}
                />
                <datalist id="receiver-logistics-companies">
                  {LOGISTICS_COMPANIES.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </label>
            </div>
          </div>

          {/* 标签管理 */}
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-neutral-900">标签</h3>
              <div className="relative">
                <button
                  className="p-1 text-neutral-400 hover:text-primary-600 transition-colors"
                  aria-label="添加标签"
                  aria-expanded={showTagPicker}
                  aria-haspopup="true"
                  onClick={() => setShowTagPicker(!showTagPicker)}
                >
                  <Plus className="w-4 h-4" />
                </button>
                {/* 面板**每次**都要出现（issue #7526）：修前面板被 `availableTags.length > 0` 门控 ⇒
                    系统没有任何标签（或客户已打满全部标签）时点「+」零反馈，按钮像坏了。
                    没有标签可加 ⇒ 说清原因 + 给出可点的去处（客户管理 → 标签管理）。 */}
                {showTagPicker && (
                  <div className="absolute right-0 top-8 bg-white border border-neutral-200 rounded-lg shadow-lg py-2 min-w-[150px] z-10">
                    {availableTags.length > 0 ? (
                      availableTags.map((tag) => (
                        <button
                          key={tag.id}
                          className="w-full text-left px-3 py-1.5 text-sm hover:bg-neutral-50 flex items-center gap-2"
                          onClick={() => handleAddTag(tag)}
                        >
                          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                          {tag.name}
                        </button>
                      ))
                    ) : (
                      <div className="px-3 py-2 w-60" data-testid="customer-tag-empty">
                        <p className="text-xs text-neutral-500 leading-relaxed mb-2">
                          {allTags.length === 0
                            ? '系统还没有标签。先创建一个标签，再回来给客户打标。'
                            : '这个客户已经用上系统里全部标签了。'}
                        </p>
                        <Button
                          size="sm"
                          variant="secondary"
                          className="w-full"
                          onClick={() => router.push('/customers?manageTags=1')}
                        >
                          {allTags.length === 0 ? '去添加标签' : '管理标签'}
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {(!customer.tags || customer.tags.length === 0) && <span className="text-xs text-neutral-400">暂无标签</span>}
              {(customer.tags || []).map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium group"
                  style={{
                    backgroundColor: tag.color + '15',
                    color: tag.color,
                    border: `1px solid ${tag.color}30`,
                  }}
                >
                  {tag.name}
                  <button
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleRemoveTag(tag.id)}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          {/* 客户备注 */}
          <div className="bg-white border border-neutral-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-neutral-900">备注</h3>
              <Button size="sm" variant="ghost" data-testid="save-remark" onClick={handleSaveRemark} loading={savingRemark}>
                <Save className="w-3.5 h-3.5 mr-1" />
                保存
              </Button>
            </div>
            <textarea
              rows={4}
              className="w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="添加客户备注..."
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
            />
          </div>
        </div>

        {/* 右侧：订单和会话历史 */}
        <div className="lg:col-span-2">
          <div className="bg-white border border-neutral-200 rounded-lg">
            {/* Tab 栏 */}
            <div className="flex border-b border-neutral-200">
              {[
                { key: 'orders' as const, label: '订单历史', icon: ShoppingCart, count: customer.orders?.length },
                { key: 'sessions' as const, label: '会话历史', icon: MessageSquare, count: customer.sessions?.length },
              ].map((tab) => (
                <button
                  key={tab.key}
                  className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-neutral-500 hover:text-neutral-900'
                  }`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                  {tab.count !== undefined && (
                    <span className="text-xs bg-neutral-100 rounded-full px-2 py-0.5">{tab.count}</span>
                  )}
                </button>
              ))}
            </div>

            {/* Tab 内容 */}
            <div className="p-6">
              {/* 订单历史 */}
              {activeTab === 'orders' && (
                <div className="space-y-3">
                  {(!customer.orders || customer.orders.length === 0) ? (
                    <p className="text-center text-neutral-500 py-8 text-sm">暂无订单记录</p>
                  ) : (
                    customer.orders.map((order) => {
                      const statusInfo = getOrderStatusLabel(order.status)
                      return (
                        <div key={order.id} className="flex items-center justify-between p-4 border border-neutral-100 rounded-lg hover:bg-neutral-50 transition-colors">
                          <div>
                            <div className="font-medium text-neutral-900">{order.orderNo || '-'}</div>
                            <div className="text-xs text-neutral-500 mt-1">
                              {order.createdAt ? dayjs(order.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="text-base font-semibold text-neutral-900">
                              ¥{(order.totalAmount ?? 0).toFixed(2)}
                            </span>
                            <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              )}

              {/* 会话历史 */}
              {activeTab === 'sessions' && (
                <div className="space-y-3">
                  {(!customer.sessions || customer.sessions.length === 0) ? (
                    <p className="text-center text-neutral-500 py-8 text-sm">暂无会话记录</p>
                  ) : (
                    customer.sessions.map((session) => (
                      <div key={session.id} className="flex items-start gap-3 p-4 border border-neutral-100 rounded-lg hover:bg-neutral-50 transition-colors">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${session.isAI ? 'bg-accent-100' : 'bg-primary-100'}`}>
                          <MessageSquare className={`w-4 h-4 ${session.isAI ? 'text-accent-600' : 'text-primary-600'}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant={session.isAI ? 'default' : 'info'}>
                              {session.isAI ? 'AI 对话' : '人工客服'}
                            </Badge>
                            <span className="text-xs text-neutral-400">
                              {dayjs(session.createdAt).format('MM-DD HH:mm')}
                            </span>
                          </div>
                          <p className="text-sm text-neutral-600 truncate">{session.lastMessage}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
