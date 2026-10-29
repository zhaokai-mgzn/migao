'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Search, Truck } from 'lucide-react'
import { toast } from 'sonner'
import { Button, PageCard, PageHeader, TableSkeleton } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { supplierApi } from '@/lib/api'
import { SELECT_CONTROL, SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { usePermission } from '@/lib/permission'
import type {
  Supplier,
  SupplierPayable,
  SupplierPayableSummary,
  SupplierPaymentMethod,
  UnassignedInboundSupplier,
} from '@/types'

/**
 * 供应商 `/suppliers`（issue #7369，P0-1 段 1）—— 大菜单「供应链 ▸ 供应商」的第一屏。
 *
 * ## 它是什么
 *
 * 供应商**档案**：一行 = 一家供货方（名称 / 联系人 / 电话 / 账期 / 状态 / 备注）。
 * 账期口径与客户授信同源：`NULL = 未设置`、`0 = 现结`、`正数 = 天数`。
 *
 * ## 🔴 为什么今天就要有
 *
 * 改前「供应商」在系统里只是入库单上的**一段文本** —— 同一家染厂可以被录成三种写法，
 * 「跟谁对账、账期几天、这家还收不收货」全部无从机判。这是 P0「管不住」的第一个缺口：
 * 后面几段（采购单 / 收货 / 应付）都要拿它当主数据。
 *
 * ## 边界（本段有意不做）
 *
 * ① **不与任何单据联动**：入库单仍写自己的文本供应商；`supplier_id` 引用是**段 2**。
 * ② **不做停用拦截**：停用只改状态位，段 2 在单据写面拦（本页不装第二套判定）。
 * ③ **只读出服务端值**：账期怎么算、停用能不能被选，一律不由本页决定。
 *
 * ## 权限
 *
 * 节点码 = `supplier:view`（issue #8087 拆码：档案面独立于入库单），写面 `inbound:create`
 * —— 复用既有码，**零授权 delta**（新造 `supplier:*` 会让页面与菜单对所有人不可见，#4203 同族坑）。
 */

/** 账期展示口径：未设置 / 现结 / N 天（与 V170 的列注释逐字一致）。 */
/** 金额上屏：两位小数、千分位留给浏览器；null/undefined 一律 0.00（不显示 NaN）。 */
function formatAmount(value: number | null | undefined): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return n.toFixed(2)
}

export function paymentTermsLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return '未设置'
  if (days === 0) return '现结'
  return `${days} 天`
}

/** 登记付款的表单态（金额留字符串：输入框原样，提交时才校验与转数）。 */
type PayFormState = {
  supplierId: string
  supplierName: string
  amount: string
  paidAt: string
  method: SupplierPaymentMethod
  referenceNo: string
  remark: string
}

type FormState = {
  id?: string
  name: string
  /** 档案类型（issue #7723）：material 采购供应商 / processor 外发加工厂（派单页的承接方下拉只列它） */
  type: 'material' | 'processor'
  contactName: string
  contactPhone: string
  paymentTermsDays: string
  status: 'active' | 'inactive'
  remark: string
}

const EMPTY_FORM: FormState = {
  name: '',
  type: 'material',
  contactName: '',
  contactPhone: '',
  paymentTermsDays: '',
  status: 'active',
  remark: '',
}

export default function SuppliersPage() {
  // 写面按 `inbound:create` 门控（#5983 范式）：无写码的岗位**看不到**建/改入口，
  // 而不是点下去才 403（菜单节点码是读码 `supplier:view`）。
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('inbound:create')
  // 付款是财务动作（后端 finance:create）⇒ 按钮按该码门控，不按档案写码
  const canPay = hasPermission('finance:create')
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [unassigned, setUnassigned] = useState<UnassignedInboundSupplier[]>([])
  const [payables, setPayables] = useState<SupplierPayableSummary | null>(null)
  /** 两块补充读面的失败态（issue #8066）：与主列表读失败**分立**，各自有锚 + 重试。 */
  const [unassignedReadError, setUnassignedReadError] = useState(false)
  const [payablesReadError, setPayablesReadError] = useState(false)
  const [payForm, setPayForm] = useState<PayFormState | null>(null)
  const [payError, setPayError] = useState<string | null>(null)
  const [paySaving, setPaySaving] = useState(false)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async (kw?: string) => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await supplierApi.list(kw)
      setSuppliers(res.data.data || [])
    } catch (error) {
      // 加载失败必须可见（不许把「拉不到」渲染成「没有供应商」），且要带上服务端原文
      setLoadError(loadErrorMessage(error, '供应商加载失败'))
      console.error('加载供应商失败:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  // 待指派清单（issue #7369 段 2）：A 口径「匹配不上不猜」的人工出口 —— 不列出来那批单据就是沉默的。
  // 它是**补充信息**：单独拉、失败**不拖垮主列表**（主列表的读失败仍由 ListLoadError 承接，二者不混）。
  // 🔴 issue #8066：改前 catch 里 `setUnassigned([])` ⇒ 整块条件渲染消失 = 「没有待指派」的假象。
  const loadUnassigned = useCallback(async () => {
    setUnassignedReadError(false)
    try {
      const res = await supplierApi.unassignedInbound()
      setUnassigned(res.data.data || [])
    } catch (error) {
      setUnassignedReadError(true)
      console.error('加载待指派清单失败:', error)
    }
  }, [])

  // 应付对账（issue #7369 段 3-A）：只读汇总，与本页列表相互独立 —— 它失败不该让档案列表变空。
  // 🔴 issue #8066：改前 catch 里 `setPayables(null)` ⇒ 整块条件渲染消失 = 「没有应付」的假象。
  const loadPayables = useCallback(async () => {
    setPayablesReadError(false)
    try {
      const res = await supplierApi.payables()
      setPayables(res.data.data || null)
    } catch (error) {
      setPayablesReadError(true)
      console.error('加载应付对账失败:', error)
    }
  }, [])

  useEffect(() => {
    load()
    loadUnassigned()
    loadPayables()
  }, [load, loadUnassigned, loadPayables])

  const openCreate = () => setForm({ ...EMPTY_FORM })

  const openEdit = (s: Supplier) => setForm({
    id: s.id,
    name: s.name,
    type: s.type ?? 'material',
    contactName: s.contactName || '',
    contactPhone: s.contactPhone || '',
    paymentTermsDays: s.paymentTermsDays === null || s.paymentTermsDays === undefined
      ? ''
      : String(s.paymentTermsDays),
    status: s.status,
    remark: s.remark || '',
  })

  const submit = async () => {
    if (!form) return
    const name = form.name.trim()
    if (!name) {
      toast.error('请填写供应商名称')
      return
    }
    const rawTerms = form.paymentTermsDays.trim()
    const terms = rawTerms === '' ? null : Number(rawTerms)
    if (terms !== null && (Number.isNaN(terms) || terms < 0 || terms > 365)) {
      toast.error('账期天数须在 0~365 之间（0 = 现结，留空 = 未设置）')
      return
    }
    const payload: Partial<Supplier> = {
      name,
      type: form.type,
      contactName: form.contactName.trim() || null,
      contactPhone: form.contactPhone.trim() || null,
      paymentTermsDays: terms,
      status: form.status,
      remark: form.remark.trim() || null,
    }
    setSaving(true)
    try {
      if (form.id) {
        await supplierApi.update(form.id, payload)
        toast.success('供应商已更新')
      } else {
        await supplierApi.create(payload)
        toast.success('供应商已建档')
      }
      setForm(null)
      await Promise.all([load(keyword), loadUnassigned(), loadPayables()])
    } catch (error) {
      toast.error(form.id ? '更新供应商失败' : '新建供应商失败')
      console.error('保存供应商失败:', error)
    } finally {
      setSaving(false)
    }
  }

  const openPay = (p: SupplierPayable) => {
    setPayError(null)
    setPayForm({ supplierId: p.supplierId, supplierName: p.supplierName, amount: '', paidAt: '', method: 'transfer', referenceNo: '', remark: '' })
  }

  const submitPay = async () => {
    if (!payForm) return
    const amount = Number(payForm.amount)
    if (!Number.isFinite(amount) || amount <= 0) {
      setPayError('付款金额必须大于 0')
      return
    }
    setPaySaving(true)
    setPayError(null)
    try {
      // 不传 allocations = 整笔挂账（预付 / 待勾对）——这是真实业务，不是缺陷
      await supplierApi.createPayment({
        supplierId: payForm.supplierId,
        amount,
        paidAt: payForm.paidAt || null,
        method: payForm.method,
        referenceNo: payForm.referenceNo || null,
        remark: payForm.remark || null,
      })
      setPayForm(null)
      await Promise.all([load(keyword), loadPayables()])
    } catch (error) {
      const err = error as { response?: { data?: { message?: string } } }
      setPayError(err.response?.data?.message || '登记付款失败')
    } finally {
      setPaySaving(false)
    }
  }

  const toggleStatus = async (s: Supplier) => {
    const next: 'active' | 'inactive' = s.status === 'active' ? 'inactive' : 'active'
    try {
      await supplierApi.update(s.id, {
        name: s.name,
        contactName: s.contactName ?? null,
        contactPhone: s.contactPhone ?? null,
        paymentTermsDays: s.paymentTermsDays ?? null,
        status: next,
        remark: s.remark ?? null,
      })
      toast.success(next === 'inactive' ? `已停用「${s.name}」` : `已启用「${s.name}」`)
      await load(keyword)
    } catch (error) {
      toast.error('状态更新失败')
      console.error('更新供应商状态失败:', error)
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="供应商"
        subtitle="谁在供货、账期几天、还收不收货 —— 一处维护，单据侧引用（采购/收货）随后接上"
        actions={
          canWrite ? (
            <Button onClick={openCreate}>
              <Plus className="w-4 h-4 mr-1" />
              新建供应商
            </Button>
          ) : null
        }
      />

      {/* 待指派清单读失败（issue #8066）：块不出现**不等于**没有待建档的供应商 —— 必须说出来 + 重试。 */}
      {unassignedReadError && (
        <div className="mt-4">
          <ListLoadError
            testId="supplier-unassigned-error"
            message="待指派清单读取失败 —— 不是「没有待建档的供应商」，请重新加载"
            onRetry={() => void loadUnassigned()}
          />
        </div>
      )}

      {unassigned.length > 0 && (
        <PageCard className="mt-4">
          <div data-testid="supplier-unassigned">
          <div className="text-sm text-neutral-700 mb-1">
            有 <strong>{unassigned.length}</strong> 个入库单上的供应商名还没建档（这些单据暂按名字统计不到供应商）
          </div>
          <div className="text-xs text-neutral-500 mb-3">
            按名称精确匹配能对上的已自动挂上；对不上或同名多家的一律不猜，留给你决定（历史单据的文本一字未改）。
          </div>
          <ul className="divide-y divide-neutral-100">
            {unassigned.map((u) => (
              <li key={u.supplierName} className="py-2 flex items-center justify-between text-sm" data-testid={`unassigned-${u.supplierName}`}>
                <span className="text-neutral-900">
                  {u.supplierName}
                  <span className="ml-2 text-xs text-neutral-500">{u.orderCount} 张入库单{u.lastInboundDate ? ` · 最近 ${u.lastInboundDate}` : ''}</span>
                </span>
                {canWrite && (
                  <button
                    className="text-primary-600 hover:underline"
                    data-testid={`unassigned-create-${u.supplierName}`}
                    onClick={() => setForm({ ...EMPTY_FORM, name: u.supplierName })}
                  >
                    建档
                  </button>
                )}
              </li>
            ))}
          </ul>
          </div>
        </PageCard>
      )}

      {/* 应付对账读失败（issue #8066）：块不出现**不等于**没有应付 —— 必须说出来 + 重试。 */}
      {payablesReadError && (
        <div className="mt-4">
          <ListLoadError
            testId="supplier-payables-error"
            message="应付对账读取失败 —— 不是「没有应付」，请重新加载"
            onRetry={() => void loadPayables()}
          />
        </div>
      )}

      {payables && payables.suppliers.length > 0 && (
        <PageCard className="mt-4">
          <div data-testid="supplier-payables">
            <div className="flex items-center justify-between mb-1">
              <div className="text-sm text-neutral-700">
                按供应商累计收货额（应付对账）
              </div>
              <div className="text-sm text-neutral-900">
                合计 <span className="font-medium">¥{formatAmount(payables.totalReceived)}</span>
              </div>
            </div>
            <div className="text-xs text-neutral-500 mb-3">
              {payables.paymentsRecorded
                ? `尚欠合计 ¥${formatAmount(payables.totalOutstanding)}`
                : '付款登记还没做：这里给出的是累计收货额（应付发生额），不是「尚欠」'}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-neutral-500 border-b border-neutral-100">
                    <th className="py-2 font-normal whitespace-nowrap">供应商</th>
                    <th className="py-2 font-normal whitespace-nowrap text-right">累计收货额</th>
                    <th className="py-2 font-normal whitespace-nowrap text-right">入库单</th>
                    <th className="py-2 font-normal whitespace-nowrap">最近入库</th>
                    <th className="py-2 font-normal whitespace-nowrap text-right">已付</th>
                    <th className="py-2 font-normal whitespace-nowrap text-right">尚欠</th>
                  </tr>
                </thead>
                <tbody>
                  {payables.suppliers.map((p2) => (
                    <tr key={p2.supplierId} className="border-b border-neutral-50" data-testid={`payable-${p2.supplierId}`}>
                      <td className="py-2 whitespace-nowrap">
                        {p2.supplierName}
                        {p2.status === 'inactive' && <span className="ml-2 text-xs text-neutral-400">已停用</span>}
                        {canPay && (
                          <button
                            className="ml-3 text-xs text-primary-600 hover:underline"
                            data-testid={`payable-pay-${p2.supplierId}`}
                            onClick={() => openPay(p2)}
                          >
                            登记付款
                          </button>
                        )}
                      </td>
                      <td className="py-2 whitespace-nowrap text-right">¥{formatAmount(p2.receivedAmount)}</td>
                      <td className="py-2 whitespace-nowrap text-right">{p2.orderCount}</td>
                      <td className="py-2 whitespace-nowrap text-neutral-500">{p2.lastInboundDate || '—'}</td>
                      <td className="py-2 whitespace-nowrap text-right text-neutral-500">
                        {p2.paymentsRecorded ? `¥${formatAmount(p2.paidAmount)}` : '未登记'}
                      </td>
                      <td className="py-2 whitespace-nowrap text-right">
                        {p2.outstanding < 0
                          ? <span className="text-primary-600">预付 ¥{formatAmount(-p2.outstanding)}</span>
                          : `¥${formatAmount(p2.outstanding)}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </PageCard>
      )}

      <PageCard className="mt-4">
        <div className="flex items-center gap-2 mb-4">
          <input
            data-testid="supplier-keyword"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') load(keyword)
            }}
            placeholder="搜名称 / 联系人 / 电话"
            className="w-64 px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <Button variant="secondary" size="sm" onClick={() => load(keyword)}>
            <Search className="w-4 h-4 mr-1" />
            搜索
          </Button>
        </div>

        {loadError && (
          <ListLoadError
            testId="suppliers-load-error"
            message={loadError}
            onRetry={() => load(keyword)}
            retrying={loading}
          />
        )}

        {/* issue #8048：加载态 = 通用表格骨架（#8036 口径），与 7 列对齐；
            不再印裸「加载中…」+ 空白表体。
            🔴 只在**首次加载**（列表为空）出骨架：建档 / 停用 / 登记付款 / 搜索会触发刷新，
            刷新时已有读数 ⇒ 表格照旧在场（同 `quality-inspections` 的
            `recordsLoading && pagedRecords.length === 0` 口径）。 */}
        {loading && suppliers.length === 0 ? (
          <TableSkeleton rows={8} columns={7} />
        ) : loadError ? null : suppliers.length === 0 ? (
          <div className="py-12 text-center text-sm text-neutral-500" data-testid="supplier-empty">
            <Truck className="w-8 h-8 mx-auto mb-2 text-neutral-300" />
            {keyword ? '没有匹配的供应商' : canWrite ? '还没有供应商档案 —— 点右上角「新建供应商」开始' : '还没有供应商档案'}
          </div>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="supplier-table">
            <thead>
              <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                <th className="py-2 whitespace-nowrap">名称</th>
                <th className="py-2 whitespace-nowrap">类型</th>
                <th className="py-2 whitespace-nowrap">联系人</th>
                <th className="py-2 whitespace-nowrap">电话</th>
                <th className="py-2 whitespace-nowrap">账期</th>
                <th className="py-2 whitespace-nowrap">状态</th>
                <th className="py-2 text-right whitespace-nowrap sticky right-0 bg-white">操作</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr key={s.id} className="border-b border-neutral-100" data-testid={`supplier-row-${s.id}`}>
                  <td className="py-2 font-medium text-neutral-900">{s.name}</td>
                  <td className="py-2 text-neutral-600" data-testid={`supplier-type-${s.id}`}>
                    {s.type === 'processor' ? '加工厂' : '供应商'}
                  </td>
                  <td className="py-2 text-neutral-600">{s.contactName || '—'}</td>
                  <td className="py-2 text-neutral-600">{s.contactPhone || '—'}</td>
                  <td className="py-2 text-neutral-600" data-testid={`supplier-terms-${s.id}`}>
                    {paymentTermsLabel(s.paymentTermsDays)}
                  </td>
                  <td className="py-2">
                    <span
                      className={s.status === 'active'
                        ? 'text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700'
                        : 'text-xs px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-500'}
                    >
                      {s.status === 'active' ? '在用' : '停用'}
                    </span>
                  </td>
                  <td className="py-2 text-right whitespace-nowrap sticky right-0 bg-white">
                    {canWrite ? (
                      <>
                        <button className="text-primary-600 hover:underline mr-3" onClick={() => openEdit(s)}>编辑</button>
                        <button
                          className="text-neutral-500 hover:underline"
                          data-testid={`supplier-toggle-${s.id}`}
                          onClick={() => toggleStatus(s)}
                        >
                          {s.status === 'active' ? '停用' : '启用'}
                        </button>
                      </>
                    ) : (
                      <span className="text-xs text-neutral-400">只读</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </PageCard>

      {payForm && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-5 w-[420px]">
            <h3 className="text-base font-medium mb-1">登记付款 · {payForm.supplierName}</h3>
            <p className="text-xs text-neutral-500 mb-3">
              只登记实付金额（挂在与该供应商的往来账上）。要冲抵具体入库单，走后续的按单勾对：
              这里不会替你猜「这笔钱付的是哪几张单」。
            </p>
            <label className="block text-sm mb-1">金额</label>
            <input
              className="w-full border border-neutral-200 rounded px-3 py-2 mb-3"
              data-testid="pay-amount"
              value={payForm.amount}
              onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })}
              placeholder="0.00"
            />
            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-sm mb-1">付款日期</label>
                <input
                  type="date"
                  className="w-full border border-neutral-200 rounded px-3 py-2"
                  data-testid="pay-date"
                  value={payForm.paidAt}
                  onChange={(e) => setPayForm({ ...payForm, paidAt: e.target.value })}
                />
              </div>
              <div>
                <label className="block text-sm mb-1">方式</label>
                <select
                  // 业务面下拉必须引用共享铬（issue #7397），不许自己拼
                  className={`w-full ${SELECT_CONTROL_FIELD}`}
                  data-testid="pay-method"
                  value={payForm.method}
                  onChange={(e) => setPayForm({ ...payForm, method: e.target.value as SupplierPaymentMethod })}
                >
                  <option value="transfer">银行转账</option>
                  <option value="cash">现金</option>
                  <option value="wechat">微信</option>
                  <option value="alipay">支付宝</option>
                  <option value="other">其他</option>
                </select>
              </div>
            </div>
            <label className="block text-sm mb-1">回单号（可选）</label>
            <input
              className="w-full border border-neutral-200 rounded px-3 py-2 mb-3"
              data-testid="pay-reference"
              value={payForm.referenceNo}
              onChange={(e) => setPayForm({ ...payForm, referenceNo: e.target.value })}
            />
            {payError && <div className="text-sm text-red-600 mb-2" role="alert">{payError}</div>}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setPayForm(null)}>取消</Button>
              <Button onClick={submitPay} disabled={paySaving} data-testid="pay-submit">
                {paySaving ? '提交中…' : '确认登记'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {form && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[480px]" data-testid="supplier-form">
            <h3 className="text-base font-semibold mb-4">{form.id ? '编辑供应商' : '新建供应商'}</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-neutral-500 mb-1">名称（必填）</label>
                <input
                  data-testid="supplier-form-name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="block text-xs text-neutral-500 mb-1">类型</label>
                <select
                  data-testid="supplier-form-type"
                  value={form.type}
                  onChange={(e) => setForm({ ...form, type: e.target.value as 'material' | 'processor' })}
                  className={SELECT_CONTROL}
                >
                  <option value="material">供应商（采购 / 入库）</option>
                  <option value="processor">加工厂（外发作业）</option>
                </select>
                <p className="mt-1 text-xs text-neutral-400">加工厂会出现在「智能派单」的承接方下拉里</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-neutral-500 mb-1">联系人</label>
                  <input
                    data-testid="supplier-form-contact"
                    value={form.contactName}
                    onChange={(e) => setForm({ ...form, contactName: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-neutral-500 mb-1">电话</label>
                  <input
                    data-testid="supplier-form-phone"
                    value={form.contactPhone}
                    onChange={(e) => setForm({ ...form, contactPhone: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-neutral-500 mb-1">账期天数（0 = 现结，留空 = 未设置）</label>
                <input
                  data-testid="supplier-form-terms"
                  type="number"
                  min={0}
                  max={365}
                  value={form.paymentTermsDays}
                  onChange={(e) => setForm({ ...form, paymentTermsDays: e.target.value })}
                  className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
              <div>
                <label className="block text-xs text-neutral-500 mb-1">备注</label>
                <textarea
                  data-testid="supplier-form-remark"
                  value={form.remark}
                  onChange={(e) => setForm({ ...form, remark: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 text-sm border border-neutral-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <Button variant="secondary" onClick={() => setForm(null)} disabled={saving}>取消</Button>
              <Button onClick={submit} disabled={saving}>{saving ? '保存中...' : '保存'}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
