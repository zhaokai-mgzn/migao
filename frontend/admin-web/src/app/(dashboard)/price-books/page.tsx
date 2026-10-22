'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button, PageCard, PageHeader } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage, toastRequestError } from '@/lib/api-error'
import { priceBookApi } from '@/lib/api'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { usePermission } from '@/lib/permission'
import type { PriceBookRow, PriceBookView } from '@/types/pricing'

const VIP_LEVELS = ['vip1', 'vip2', 'vip3'] as const

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * 价格本（issue #7375 段 3）：协议价 / 等级价 / 阶梯价。
 *
 * <h3>为什么单独一页</h3>
 * <p>价格决定毛利，而改前价格本只能直接写库 —— 只有工程师能维护的价格体系等于没有。本页把三层价格
 * 放在一处：按 **SKU** 查（价格本按 SKU 维护），录入 / 停用都在这里。</p>
 *
 * <h3>三条纪律（与后端一致）</h3>
 * <ol>
 *   <li><b>价格必须 &gt; 0</b>：0 元 = 白送，前端先拦一次（后端也拦）；</li>
 *   <li><b>低于成本的改价要审批</b>：后端会拒并给出申请路径，页面把服务端原文显示出来；</li>
 *   <li><b>没有的那层就是没有</b>：某层 0 条 ⇒ 显示「未设置」，不画成 ¥0.00。</li>
 * </ol>
 */
export default function PriceBooksPage() {
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('product:create')

  const [skuId, setSkuId] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [book, setBook] = useState<PriceBookView | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [form, setForm] = useState<{ kind: 'protocol' | 'vip' | 'tier'; price: string; target: string; maxQty: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const id = Number(skuId)
    if (!skuId.trim() || Number.isNaN(id) || id <= 0) {
      setBook(null)
      setLoadError(null)
      return
    }
    setLoading(true)
    setLoadError(null)
    try {
      const res = await priceBookApi.list({ skuId: id, customerId: customerId.trim() || undefined })
      setBook(res.data.data || null)
    } catch (error) {
      console.error('加载价格本失败:', error)
      setLoadError(loadErrorMessage(error, '价格本加载失败'))
      setBook(null)
    } finally {
      setLoading(false)
    }
  }, [skuId, customerId])

  useEffect(() => {
    // ⚠️ 必须**直接调用** `load()`（而不是 `setTimeout(load, 300)`）：判据 12 的「第一屏读端点」
    // 只认 `useEffect` 块体里被 `name(` 调用到的本地函数 —— 把函数当参数传进去会让 api 调用
    // 掉出 effect 驱动面（实测：判据当场判「锚点声明的调用不在 effect 驱动面上」）。
    const timer = setTimeout(() => { void load() }, 300)   // 输入 SKU 时防抖：避免每敲一个字都打一次接口
    return () => clearTimeout(timer)
  }, [load])

  const submit = async () => {
    if (!form) return
    const price = Number(form.price)
    const id = Number(skuId)
    if (!form.price.trim() || Number.isNaN(price) || price <= 0) {
      setFormError('价格必须大于 0（0 元等于白送；未定价就不要录）')
      return
    }
    if (form.kind === 'protocol' && !form.target.trim()) {
      setFormError('协议价要指定客户')
      return
    }
    if (form.kind === 'tier' && (!form.target.trim() || Number(form.target) <= 0)) {
      setFormError('阶梯价要填起订量（大于 0）')
      return
    }
    setSaving(true)
    setFormError(null)
    try {
      if (form.kind === 'protocol') {
        await priceBookApi.upsertProtocol({ customerId: form.target.trim(), skuId: id, price })
      } else if (form.kind === 'vip') {
        await priceBookApi.upsertVipLevel({ vipLevel: form.target, skuId: id, price })
      } else {
        await priceBookApi.upsertTier({
          skuId: id,
          minQty: Number(form.target),
          maxQty: form.maxQty.trim() ? Number(form.maxQty) : undefined,
          price,
        })
      }
      setForm(null)
      toast.success('已保存')
      await load()
    } catch (error) {
      // 低于成本的后端会拒（要给「改价」审批）⇒ 把它那句话显示出来，而不是一句「保存失败」
      const message = loadErrorMessage(error, '保存失败')
      setFormError(message)
      toastRequestError(error, message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (kind: 'protocol' | 'vip-level' | 'tier', id: string) => {
    try {
      await priceBookApi.remove(kind, id)
      toast.success('已停用')
      await load()
    } catch (error) {
      toastRequestError(error, loadErrorMessage(error, '停用失败'))
    }
  }

  const rows: { kind: 'protocol' | 'vip-level' | 'tier'; label: string; items: PriceBookRow[] }[] = book
    ? [
        { kind: 'protocol', label: '协议价（客户专属）', items: book.protocol },
        { kind: 'vip-level', label: '等级价（按 VIP 等级）', items: book.vipLevels },
        { kind: 'tier', label: '阶梯价（按数量）', items: book.tiers },
      ]
    : []

  return (
    <div className="p-6">
      <PageHeader
        title="价格本"
        subtitle="同一个商品对不同客户、不同等级、不同数量可以是不同的价 —— 协议价优先于等级价，等级价优先于阶梯价"
        actions={
          canWrite && book ? (
            <Button
              icon={<Plus className="w-4 h-4" />}
              onClick={() => { setForm({ kind: 'protocol', price: '', target: '', maxQty: '' }); setFormError(null) }}
            >
              新增价格
            </Button>
          ) : null
        }
      />

      <PageCard className="mt-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-neutral-600">
            <span className="block mb-1">SKU 编号</span>
            <input
              data-testid="price-books-sku"
              className="w-40 rounded border border-neutral-200 px-3 py-2 text-sm"
              value={skuId}
              onChange={(e) => setSkuId(e.target.value)}
              placeholder="如 1024"
              inputMode="numeric"
            />
          </label>
          <label className="text-sm text-neutral-600">
            <span className="block mb-1">只看这个客户（可选）</span>
            <input
              data-testid="price-books-customer"
              className="w-52 rounded border border-neutral-200 px-3 py-2 text-sm"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              placeholder="客户 id"
            />
          </label>
        </div>
      </PageCard>

      {loadError && <ListLoadError message={loadError} onRetry={load} testId="price-books-load-error" />}

      {form && (
        <PageCard className="mt-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm text-neutral-600">
              <span className="block mb-1">价格类型</span>
              <select
                data-testid="price-books-kind"
                className={SELECT_CONTROL_FIELD}
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as typeof form.kind, target: '' })}
              >
                <option value="protocol">协议价（客户）</option>
                <option value="vip">等级价（VIP）</option>
                <option value="tier">阶梯价（数量）</option>
              </select>
            </label>
            <label className="text-sm text-neutral-600">
              <span className="block mb-1">
                {form.kind === 'protocol' ? '客户 id' : form.kind === 'vip' ? 'VIP 等级' : '起订量（米）'}
              </span>
              {form.kind === 'vip' ? (
                <select
                  data-testid="price-books-target"
                  className={SELECT_CONTROL_FIELD}
                  value={form.target}
                  onChange={(e) => setForm({ ...form, target: e.target.value })}
                >
                  <option value="">选择等级</option>
                  {VIP_LEVELS.map((level) => <option key={level} value={level}>{level}</option>)}
                </select>
              ) : (
                <input
                  data-testid="price-books-target"
                  className="w-40 rounded border border-neutral-200 px-3 py-2 text-sm"
                  value={form.target}
                  onChange={(e) => setForm({ ...form, target: e.target.value })}
                />
              )}
            </label>
            {form.kind === 'tier' && (
              <label className="text-sm text-neutral-600">
                <span className="block mb-1">上限（可空 = 不限）</span>
                <input
                  data-testid="price-books-max"
                  className="w-32 rounded border border-neutral-200 px-3 py-2 text-sm"
                  value={form.maxQty}
                  onChange={(e) => setForm({ ...form, maxQty: e.target.value })}
                />
              </label>
            )}
            <label className="text-sm text-neutral-600">
              <span className="block mb-1">单价（元）</span>
              <input
                data-testid="price-books-price"
                className="w-32 rounded border border-neutral-200 px-3 py-2 text-sm"
                value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value })}
                inputMode="decimal"
              />
            </label>
            <Button onClick={submit} disabled={saving} data-testid="price-books-save">
              {saving ? '保存中…' : '保存'}
            </Button>
            <Button variant="ghost" onClick={() => setForm(null)}>取消</Button>
          </div>
          {formError && (
            <p className="mt-2 text-sm text-red-600" data-testid="price-books-form-error">{formError}</p>
          )}
        </PageCard>
      )}

      {loading ? (
        <p className="mt-4 text-sm text-neutral-500" data-testid="price-books-loading">加载中…</p>
      ) : !skuId.trim() ? (
        <p className="mt-4 text-sm text-neutral-500" data-testid="price-books-hint">
          输入 SKU 编号查看这个 SKU 的三层价格（协议价 / 等级价 / 阶梯价）
        </p>
      ) : book ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {rows.map(({ kind, label, items }) => (
            <PageCard key={kind}>
              <div className="flex items-baseline justify-between">
                <h2 className="text-base font-medium text-neutral-800">{label}</h2>
                <span className="text-xs text-neutral-500">{items.length} 条</span>
              </div>
              {items.length === 0 ? (
                <p className="mt-3 text-sm text-neutral-500" data-testid={`price-books-empty-${kind}`}>
                  未设置 —— 这一层没有专属价，下单会继续往下找
                </p>
              ) : (
                <ul className="mt-3 space-y-2 text-sm" data-testid={`price-books-list-${kind}`}>
                  {items.map((row) => (
                    <li key={row.id} className="flex items-center justify-between gap-2">
                      <span className="text-neutral-600">
                        {kind === 'protocol' ? row.customer_id
                          : kind === 'vip-level' ? row.vip_level
                          : `满 ${row.min_qty} 米${row.max_qty ? ` · 至 ${row.max_qty} 米` : ' 起'}`}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="tabular-nums">{money(row.price)}</span>
                        {canWrite && (
                          <button
                            type="button"
                            aria-label="停用"
                            data-testid={`price-books-remove-${row.id}`}
                            className="text-neutral-400 hover:text-red-600"
                            onClick={() => remove(kind, row.id)}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </PageCard>
          ))}
        </div>
      ) : null}
    </div>
  )
}
