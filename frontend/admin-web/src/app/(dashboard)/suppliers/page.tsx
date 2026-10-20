'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Search, Truck } from 'lucide-react'
import { toast } from 'sonner'
import { Button, PageCard, PageHeader } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { supplierApi } from '@/lib/api'
import type { Supplier } from '@/types'

/**
 * 供应商 `/suppliers`（issue #7369，P0-1 段 1）—— 大菜单「仓储与物料 ▸ 供应商」的第一屏。
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
 * 节点码 = `inbound:view`（与入库单同群：仓管看收货、财务看账期），写面 `inbound:create`
 * —— 复用既有码，**零授权 delta**（新造 `supplier:*` 会让页面与菜单对所有人不可见，#4203 同族坑）。
 */

/** 账期展示口径：未设置 / 现结 / N 天（与 V170 的列注释逐字一致）。 */
export function paymentTermsLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return '未设置'
  if (days === 0) return '现结'
  return `${days} 天`
}

type FormState = {
  id?: string
  name: string
  contactName: string
  contactPhone: string
  paymentTermsDays: string
  status: 'active' | 'inactive'
  remark: string
}

const EMPTY_FORM: FormState = {
  name: '',
  contactName: '',
  contactPhone: '',
  paymentTermsDays: '',
  status: 'active',
  remark: '',
}

export default function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async (kw?: string) => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await supplierApi.list(kw)
      setSuppliers(res.data.data || [])
    } catch (error) {
      // 加载失败必须可见（不许把「拉不到」渲染成「没有供应商」）
      setLoadError('failed')
      console.error('加载供应商失败:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => setForm({ ...EMPTY_FORM })

  const openEdit = (s: Supplier) => setForm({
    id: s.id,
    name: s.name,
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
      await load(keyword)
    } catch (error) {
      toast.error(form.id ? '更新供应商失败' : '新建供应商失败')
      console.error('保存供应商失败:', error)
    } finally {
      setSaving(false)
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
          <Button onClick={openCreate}>
            <Plus className="w-4 h-4 mr-1" />
            新建供应商
          </Button>
        }
      />

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
            message="供应商列表读不到（不是没有供应商）"
            onRetry={() => load(keyword)}
            retrying={loading}
          />
        )}

        {loading ? (
          <div className="py-10 text-center text-sm text-neutral-500">加载中...</div>
        ) : loadError ? null : suppliers.length === 0 ? (
          <div className="py-12 text-center text-sm text-neutral-500" data-testid="supplier-empty">
            <Truck className="w-8 h-8 mx-auto mb-2 text-neutral-300" />
            {keyword ? '没有匹配的供应商' : '还没有供应商档案 —— 点右上角「新建供应商」开始'}
          </div>
        ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="supplier-table">
            <thead>
              <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                <th className="py-2 whitespace-nowrap">名称</th>
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
                    <button className="text-primary-600 hover:underline mr-3" onClick={() => openEdit(s)}>编辑</button>
                    <button
                      className="text-neutral-500 hover:underline"
                      data-testid={`supplier-toggle-${s.id}`}
                      onClick={() => toggleStatus(s)}
                    >
                      {s.status === 'active' ? '停用' : '启用'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </PageCard>

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
