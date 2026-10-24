'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal, PageCard, PageHeader } from '@/components/ui'
import FormPanel, { Field, FormGrid, fieldControl } from '@/components/ui/FormPanel'
import CustomerPicker, { type CustomerChoice } from '@/components/customers/CustomerPicker'
import SkuPicker, { type SkuPickerChoice, skuLineLabel } from '@/components/products/SkuPicker'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage, toastRequestError } from '@/lib/api-error'
import RequestApprovalModal from '@/components/approvals/RequestApprovalModal'
import { priceChangeDraft, type ApprovalDraft } from '@/lib/approval-request'
import { priceBookApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { cn } from '@/lib/utils'
import type { PriceBookRow, PriceBookView } from '@/types/pricing'

const VIP_LEVELS = ['vip1', 'vip2', 'vip3'] as const

/** 三层价：协议价优先于等级价，等级价优先于阶梯价 */
type PriceLayer = 'protocol' | 'vip' | 'tier'

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** 价必须 > 0（0 元 = 白送）：三层共用**同一条**口径，报错只落在触发它的那一层。 */
function priceProblem(raw: string): string | null {
  if (!raw.trim()) return '单价必填'
  const value = Number(raw)
  if (Number.isNaN(value) || value <= 0) return '价格必须大于 0（0 元等于白送；未定价就不要录）'
  return null
}

/**
 * 价格本（issue #7375 段 3；交互改版 = issue #7622）。
 *
 * <h3>为什么单独一页</h3>
 * <p>价格决定毛利，而改前价格本只能直接写库 —— 只有工程师能维护的价格体系等于没有。本页把三层价格
 * 放在一处：按 **SKU** 查（价格本按 SKU 维护），录入 / 停用都在这里。</p>
 *
 * <h3>issue #7567：SKU 只从选品器里选</h3>
 * <p>改前是一格 `<input placeholder="如 1024">` + `Number(skuId)` —— 而 SKU id 是**雪花号字符串**
 * （≈2.1e18 > 2^53）⇒ `Number()` 一转换就吞末位，查不到该 SKU（#5904 同族）。现在与入库单/采购单
 * 共用 `components/products/SkuPicker`（单选态）：选中即按**原样字符串**查这个 SKU 的三层价。</p>
 *
 * <h3>issue #7622：新增走弹窗、三层平铺、客户只能选（用户 2026-10-24 两张截图）</h3>
 * <ul>
 *   <li><b>弹窗</b>：改前表单原地展开在页面中间（把页面撑长、离「新增价格」入口很远）；
 *       现在它是一个对话框，录完关闭，页面不留常驻表单。</li>
 *   <li><b>三层平铺</b>：改前要先在「价格类型」下拉里选一种才出现对应字段 —— 三层是**并列**关系，
 *       不该藏进下拉；现在三块同时摆出，各自一个保存、各自的报错留在自己那一块（不串层）。</li>
 *   <li><b>客户只能选</b>：「只看这个客户」筛选与协议价的客户都改走公共件
 *       `components/customers/CustomerPicker`（按姓名 / 手机号搜），不再让人手抄客户 id。</li>
 * </ul>
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
  /** 选中 SKU 的展示名（页面上要说清「正在维护哪个 SKU」，不印雪花号） */
  const [skuLabel, setSkuLabel] = useState('')
  /** 「只看这个客户」筛选（可选）：走客户选择器，不再是手填 id */
  const [filterCustomer, setFilterCustomer] = useState<CustomerChoice | null>(null)
  const [book, setBook] = useState<PriceBookView | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  // ===== 新增价格弹窗（issue #7622）：三层平铺、各自录入、各自保存 =====
  const [addOpen, setAddOpen] = useState(false)
  const [protocol, setProtocol] = useState<{ customer: CustomerChoice | null; price: string }>({
    customer: null,
    price: '',
  })
  const [vip, setVip] = useState<{ level: string; price: string }>({ level: '', price: '' })
  const [tier, setTier] = useState<{ minQty: string; maxQty: string; price: string }>({
    minQty: '',
    maxQty: '',
    price: '',
  })
  const [savingLayer, setSavingLayer] = useState<PriceLayer | null>(null)
  /** 报错按层存：三层各录各的，一层错了不该把另外两层的提示也顶掉 */
  const [layerErrors, setLayerErrors] = useState<Partial<Record<PriceLayer, string>>>({})
  // 被「低于成本」拒时，就地开一张改价审批（issue #7374 段 3）：ref = 该 SKU id，金额门槛 = 成本价
  const [approvalDraft, setApprovalDraft] = useState<ApprovalDraft | null>(null)

  const load = useCallback(async () => {
    if (!skuId.trim()) {
      setBook(null)
      setLoadError(null)
      return
    }
    setLoading(true)
    setLoadError(null)
    try {
      // 🔴 skuId 原样交给后端（字符串）：雪花号经 `Number()` 会吞末位（#5904 同族）
      const res = await priceBookApi.list({ skuId, customerId: filterCustomer?.id })
      setBook(res.data.data || null)
    } catch (error) {
      console.error('加载价格本失败:', error)
      setLoadError(loadErrorMessage(error, '价格本加载失败'))
      setBook(null)
    } finally {
      setLoading(false)
    }
  }, [skuId, filterCustomer])

  useEffect(() => {
    // ⚠️ 必须**直接调用** `load()`（而不是 `setTimeout(load, 300)`）：判据 12 的「第一屏读端点」
    // 只认 `useEffect` 块体里被 `name(` 调用到的本地函数 —— 把函数当参数传进去会让 api 调用
    // 掉出 effect 驱动面（实测：判据当场判「锚点声明的调用不在 effect 驱动面上」）。
    // 防抖只服务于「客户筛选」那一格输入（避免每敲一个字都打一次接口）；
    // SKU 已由选品器**显式选定**（issue #7567），不再逐字请求。
    const timer = setTimeout(() => { void load() }, 300)
    return () => clearTimeout(timer)
  }, [load])

  /** 单选：点另一个 SKU 就换人；再点当前这个不取消（避免一次误点把正在维护的价格视图清空）。 */
  const pickSku = ({ product, sku }: SkuPickerChoice) => {
    if (sku.id === skuId) return
    setSkuId(sku.id)
    setSkuLabel(skuLineLabel(product, sku))
    setBook(null)
    // 弹窗里的三层是「这个 SKU 的价」—— 换 SKU 就必须关掉，否则会把 A 的录入存到 B 上
    setAddOpen(false)
  }

  const openAdd = () => {
    setProtocol({ customer: null, price: '' })
    setVip({ level: '', price: '' })
    setTier({ minQty: '', maxQty: '', price: '' })
    setLayerErrors({})
    setAddOpen(true)
  }

  const setLayerError = (layer: PriceLayer, message: string | undefined) =>
    setLayerErrors((prev) => ({ ...prev, [layer]: message }))

  const saveLayer = async (layer: PriceLayer) => {
    if (!skuId) return
    setLayerError(layer, undefined)

    const rawPrice = layer === 'protocol' ? protocol.price : layer === 'vip' ? vip.price : tier.price
    const problem = priceProblem(rawPrice)
    if (problem) {
      setLayerError(layer, problem)
      return
    }
    if (layer === 'protocol' && !protocol.customer) {
      setLayerError(layer, '协议价要先选客户')
      return
    }
    if (layer === 'vip' && !vip.level) {
      setLayerError(layer, '等级价要先选 VIP 等级')
      return
    }
    if (layer === 'tier' && !(Number(tier.minQty) > 0)) {
      setLayerError(layer, '阶梯价要填起订量（大于 0 米）')
      return
    }

    setSavingLayer(layer)
    try {
      if (layer === 'protocol') {
        await priceBookApi.upsertProtocol({ customerId: protocol.customer!.id, skuId, price: Number(protocol.price) })
        // 只清这一层：另外两层可能还录着一半
        setProtocol({ customer: null, price: '' })
      } else if (layer === 'vip') {
        await priceBookApi.upsertVipLevel({ vipLevel: vip.level, skuId, price: Number(vip.price) })
        setVip({ level: '', price: '' })
      } else {
        await priceBookApi.upsertTier({
          skuId,
          minQty: Number(tier.minQty),
          maxQty: tier.maxQty.trim() ? Number(tier.maxQty) : undefined,
          price: Number(tier.price),
        })
        setTier({ minQty: '', maxQty: '', price: '' })
      }
      toast.success('已保存')
      await load()
    } catch (error) {
      // 低于成本的后端会拒（要给「改价」审批）⇒ 把它那句话显示出来，而不是一句「保存失败」
      const message = loadErrorMessage(error, '保存失败')
      setLayerError(layer, message)
      toastRequestError(error, message)
      // 服务端原文里带着「必须先有已通过的『改价』审批」⇒ 顺手把申请入口摆出来（不必手抄 SKU id）
      if (/改价/.test(message)) {
        setApprovalDraft(priceChangeDraft({ skuId, skuLabel: skuLabel || '当前 SKU' }))
      }
    } finally {
      setSavingLayer(null)
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

  /** 一层的操作条：保存 + 这一层的报错（三层形态一致，报错不会被误读成另一层的问题） */
  const layerFooter = (layer: PriceLayer, label: string) => (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <Button
        variant="secondary"
        data-testid={`price-books-save-${layer}`}
        loading={savingLayer === layer}
        onClick={() => void saveLayer(layer)}
      >
        {label}
      </Button>
      {layerErrors[layer] ? (
        <p role="alert" data-testid={`price-books-error-${layer}`} className="text-sm text-red-600">
          {layerErrors[layer]}
        </p>
      ) : null}
    </div>
  )

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
            <Button icon={<Plus className="w-4 h-4" />} onClick={openAdd}>
              新增价格
            </Button>
          ) : null
        }
      />

      <PageCard className="mt-4">
        <Field label="只看这个客户（可选）" className="w-72">
          <CustomerPicker
            value={filterCustomer}
            onChange={setFilterCustomer}
            testIdPrefix="price-books-customer-filter"
            placeholder="搜索客户姓名 / 手机号"
          />
        </Field>
        <div className="mt-3">
          <SkuPicker
            mode="single"
            testIdPrefix="price-books"
            title="选一个 SKU（这一页维护它的三层价格）"
            selectedSkuIds={skuId ? [skuId] : []}
            onToggle={pickSku}
          />
        </div>
        {skuId && (
          <p data-testid="price-books-selected" className="mt-3 text-sm text-neutral-700">
            正在维护：<span className="font-medium">{skuLabel}</span>
          </p>
        )}
      </PageCard>

      {loadError && <ListLoadError message={loadError} onRetry={load} testId="price-books-load-error" />}

      {loading ? (
        <p className="mt-4 text-sm text-neutral-500" data-testid="price-books-loading">加载中…</p>
      ) : !skuId.trim() ? (
        <p className="mt-4 text-sm text-neutral-500" data-testid="price-books-hint">
          在上面选一个 SKU —— 它的三层价格（协议价 / 等级价 / 阶梯价）都在这一页维护
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
                        {kind === 'protocol' ? (row.customer_name || '未命名客户')
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

      {/* 新增价格（issue #7622）：**弹窗** + 三层**平铺**、各自录入各自保存（改前是页内横排 + 类型下拉） */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="新增价格"
        width={780}
        footer={
          <Button variant="secondary" onClick={() => setAddOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-neutral-500" data-testid="price-books-add-target">
            正在维护：<span className="font-medium text-neutral-700">{skuLabel}</span>
          </p>

          <FormPanel
            testid="price-books-section-protocol"
            title="协议价（按客户）"
            hint="只给选定客户的价 —— 下单时优先于等级价与阶梯价"
          >
            <FormGrid cols={2}>
              <Field label="客户">
                <CustomerPicker
                  value={protocol.customer}
                  onChange={(customer) => setProtocol((prev) => ({ ...prev, customer }))}
                  testIdPrefix="price-books-protocol-customer"
                  placeholder="搜索客户姓名 / 手机号"
                />
              </Field>
              <Field label="单价" unit="元">
                <input
                  data-testid="price-books-protocol-price"
                  aria-label="协议价单价"
                  className={fieldControl('元')}
                  value={protocol.price}
                  inputMode="decimal"
                  onChange={(e) => setProtocol((prev) => ({ ...prev, price: e.target.value }))}
                />
              </Field>
            </FormGrid>
            {layerFooter('protocol', '保存协议价')}
          </FormPanel>

          <FormPanel
            testid="price-books-section-vip"
            title="等级价（按 VIP 等级）"
            hint="按客户等级统一定的价 —— 客户没有协议价时用它"
          >
            <FormGrid cols={2}>
              <Field label="VIP 等级">
                <div role="group" aria-label="VIP 等级" className="flex gap-2">
                  {VIP_LEVELS.map((level) => {
                    const active = vip.level === level
                    return (
                      <button
                        key={level}
                        type="button"
                        aria-pressed={active}
                        data-testid={`price-books-vip-level-${level}`}
                        onClick={() => setVip((prev) => ({ ...prev, level }))}
                        className={cn(
                          'h-9 min-w-20 rounded-lg border px-3 text-sm transition-colors',
                          active
                            ? 'border-primary-500 bg-primary-50 text-primary-700'
                            : 'border-neutral-200 text-neutral-600 hover:border-neutral-300',
                        )}
                      >
                        {level.toUpperCase()}
                      </button>
                    )
                  })}
                </div>
              </Field>
              <Field label="单价" unit="元">
                <input
                  data-testid="price-books-vip-price"
                  aria-label="等级价单价"
                  className={fieldControl('元')}
                  value={vip.price}
                  inputMode="decimal"
                  onChange={(e) => setVip((prev) => ({ ...prev, price: e.target.value }))}
                />
              </Field>
            </FormGrid>
            {layerFooter('vip', '保存等级价')}
          </FormPanel>

          <FormPanel
            testid="price-books-section-tier"
            title="阶梯价（按数量）"
            hint="按购买数量分档 —— 上面两层都没有时才用它"
          >
            <FormGrid cols={3}>
              <Field label="起订量" unit="米">
                <input
                  data-testid="price-books-tier-min"
                  aria-label="起订量"
                  className={fieldControl('米')}
                  value={tier.minQty}
                  inputMode="decimal"
                  onChange={(e) => setTier((prev) => ({ ...prev, minQty: e.target.value }))}
                />
              </Field>
              <Field label="上限" unit="米" hint="留空 = 不限">
                <input
                  data-testid="price-books-tier-max"
                  aria-label="数量上限"
                  className={fieldControl('米')}
                  value={tier.maxQty}
                  inputMode="decimal"
                  onChange={(e) => setTier((prev) => ({ ...prev, maxQty: e.target.value }))}
                />
              </Field>
              <Field label="单价" unit="元">
                <input
                  data-testid="price-books-tier-price"
                  aria-label="阶梯价单价"
                  className={fieldControl('元')}
                  value={tier.price}
                  inputMode="decimal"
                  onChange={(e) => setTier((prev) => ({ ...prev, price: e.target.value }))}
                />
              </Field>
            </FormGrid>
            {layerFooter('tier', '保存阶梯价')}
          </FormPanel>
        </div>
      </Modal>

      {/* 改价审批（issue #7374 段 3）：ref 用当前 SKU id，金额门槛见提示 —— 批错金额等于白批 */}
      <RequestApprovalModal
        open={approvalDraft !== null}
        onClose={() => setApprovalDraft(null)}
        draft={approvalDraft}
        onSubmitted={() => void load()}
      />
    </div>
  )
}
