'use client'

// ============================================================
// 新增入库单（**独立整页**，issue #5844）—— 商品布料入库建单
// ============================================================
// 为什么是整页而不是弹窗（用户 2026-10-01 逐字：「新增入库单的布局很怪异，应该和订单，商品
// 设计风格对齐」）：`新增订单` /orders/new 与 `新增商品` /products/new 都是**一等页面**
// （页头返回 + 标题 + `Card` 分区卡片 + `Input/Select` 标签在上 + 吸底汇总条）；而改造前的建单
// 弹窗里商品搜索结果被页脚截断、搜索框双边框、入库日期独占半行 —— 版式件与全站不同族。
// 本页按 orders/new 的版式件重建：`Card` + `SectionTitle` + `Input/Select` + `sticky bottom-0` 汇总条。
//
// 🔴 本次**只动版式与入口，不动建单契约**：提交 payload 逐字段与改造前**一字不差**
//   （`source` / `items[]` 的 productId,skuId,quantity,unitCost,dyeLot,legacyBatchNo,rollLengthM）。
//   数量口径仍是「大于 0 且最多 1 位小数」（issue #5063 / #5153）—— 与后端**同一判据**，
//   见 lib/stock-quantity.ts；超 1 位小数**显式拒绝**（不静默取整）。
//
// 批次号（issue #5844 只做「看得见」，**生成时机不变**）：`PC-yyyyMMdd-NNNN`，**过账时逐行生成**
//   （一行 = 一个批次），与入库单号 `RK-yyyyMMdd-NNNN`、加工单 `JG-*`、售后 `AS-*` 同族。
//   草稿**不发号**（批次号 = 「真的收货了」的标识）⇒ 本页明细列的批次号恒为「过账后生成」，
//   列在这里是为了让商家建单时就知道「这批货将来靠哪个号追溯」。

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, FileText, Layers, Package, Search } from 'lucide-react'
import { toast } from 'sonner'
import { inboundOrderApi, productApi } from '@/lib/api'
import { Button, Card, Input, Select } from '@/components/ui'
import type { Product, ProductSku } from '@/types'
import { cn } from '@/lib/utils'
import { checkStockQuantity, formatStockQuantity } from '@/lib/stock-quantity'

/** 入库明细行（含 SKU 的展示快照，提交时只取 productId/skuId/quantity/unitCost/dyeLot/legacyBatchNo/rollLengthM） */
interface DraftLine {
  productId: string
  skuId: number
  label: string
  stock: number
  quantity: string
  unitCost: string
  dyeLot: string
  /** 旧系统批次号（只录入期建账时才提交；系统批次号由服务端生成，两者不得互相冒充） */
  legacyBatchNo: string
  rollLengthM: string
}

/** 单据来源（V117；`opening` = 期初建账/批次初始化） */
const SOURCE_OPTIONS: { value: 'purchase' | 'opening'; label: string }[] = [
  { value: 'purchase', label: '采购收货（正常入库）' },
  { value: 'opening', label: '期初建账（按实物登记在库批次）' },
]

/** 明细行输入框：与 `Input` 同族（h-9 / rounded-lg / 同一 focus ring），只是窄一档放进表格 */
const CELL_INPUT = 'h-9 px-2 text-sm'

export default function NewInboundOrderPage() {
  const router = useRouter()

  const [productKeyword, setProductKeyword] = useState('')
  const [productOptions, setProductOptions] = useState<Product[]>([])
  const [pickedProduct, setPickedProduct] = useState<Product | null>(null)
  const [productSkus, setProductSkus] = useState<ProductSku[]>([])
  const [skuLoading, setSkuLoading] = useState(false)
  const [draftLines, setDraftLines] = useState<DraftLine[]>([])
  const [form, setForm] = useState({
    supplier: '',
    supplierDocNo: '',
    warehouse: '',
    inboundDate: '',
    remark: '',
    source: 'purchase' as 'purchase' | 'opening',
  })
  const [submitting, setSubmitting] = useState(false)

  // ---- 商品搜索（防抖） ----
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const res = await productApi.getProducts({
          keyword: productKeyword || undefined,
          page: 1,
          size: 20,
        })
        setProductOptions(res.data.data?.items ?? [])
      } catch {
        setProductOptions([])
      }
    }, 300)
    return () => clearTimeout(t)
  }, [productKeyword])

  const pickProduct = async (p: Product) => {
    setPickedProduct(p)
    setSkuLoading(true)
    try {
      const res = await productApi.getProduct(p.id)
      setProductSkus(res.data.data?.skus ?? [])
    } catch {
      setProductSkus([])
    } finally {
      setSkuLoading(false)
    }
  }

  /** 勾选 SKU ⇒ 加入/移出草稿行（保留已填的数量/单价/缸号/旧系统批次号） */
  const toggleSku = (sku: ProductSku) => {
    const product = pickedProduct
    if (!product) return
    setDraftLines((prev) => {
      const exists = prev.some((l) => l.skuId === Number(sku.id))
      if (exists) {
        return prev.filter((l) => l.skuId !== Number(sku.id))
      }
      return [
        ...prev,
        {
          productId: product.id,
          skuId: Number(sku.id),
          label: `${product.name} / ${sku.colorName || '默认色'} / ${sku.doorWidth || '默认门幅'}`,
          stock: sku.stock ?? 0,
          quantity: '1',
          unitCost: '',
          dyeLot: '',
          legacyBatchNo: '',
          rollLengthM: '',
        },
      ]
    })
  }

  const patchLine = (skuId: number, patch: Partial<DraftLine>) => {
    setDraftLines((prev) => prev.map((l) => (l.skuId === skuId ? { ...l, ...patch } : l)))
  }

  const draftTotal = useMemo(
    () =>
      draftLines.reduce((sum, l) => {
        const q = Number(l.quantity)
        const c = Number(l.unitCost)
        if (!Number.isFinite(q) || !Number.isFinite(c) || l.unitCost === '') return sum
        return sum + q * c
      }, 0),
    [draftLines],
  )

  const submitCreate = async () => {
    if (draftLines.length === 0) {
      toast.error('请至少勾选一个 SKU 作为入库明细')
      return
    }
    // 数量必须**大于 0** 且**最多 1 位小数**（0.1 米粒度）—— 与后端同一判据。
    // 下限由「≥1 米」放宽（issue #5153）：0.5 米的尾料是**实物事实**，挡在门外 = 系统说谎。
    // 超 1 位小数**显式拒绝**，绝不静默取整/截断（账面库存要照米数对得上）。
    for (const l of draftLines) {
      const reason = checkStockQuantity(l.quantity)
      if (reason) {
        toast.error(`「${l.label}」的${reason}`)
        return
      }
      if (l.unitCost !== '' && !(Number(l.unitCost) > 0)) {
        toast.error(`「${l.label}」的入库单价必须大于 0（不记单价请留空）`)
        return
      }
    }
    setSubmitting(true)
    try {
      await inboundOrderApi.create({
        supplier: form.supplier || null,
        supplierDocNo: form.supplierDocNo || null,
        warehouse: form.warehouse || null,
        inboundDate: form.inboundDate || null,
        remark: form.remark || null,
        // 来源（V117 既有件）：期初建账与正常采购在库里可区分 —— 基线冻结点靠它
        source: form.source,
        items: draftLines.map((l) => ({
          productId: l.productId,
          skuId: l.skuId,
          quantity: Number(l.quantity),
          unitCost: l.unitCost === '' ? null : Number(l.unitCost),
          dyeLot: l.dyeLot || null,
          // 旧系统批次号**只在期初建账时提交**（采购入库填了后端会拒 —— 两列两义，不得互相冒充）
          legacyBatchNo: form.source === 'opening' ? l.legacyBatchNo || null : null,
          rollLengthM: l.rollLengthM === '' ? null : Number(l.rollLengthM),
        })),
      })
      toast.success(
        form.source === 'opening'
          ? '期初建账单已建（草稿，未动库存）—— 核对无误后请过账：过账即冻结基线'
          : '入库单已建（草稿，未动库存）—— 核对无误后请过账',
      )
      // 建完回列表：新单在列表里（草稿态）→ 点「详情」核对 → 过账时逐行发批次号
      router.push('/inbound-orders')
    } catch {
      // 拦截器已提示
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 max-w-[1280px] mx-auto pb-28">
      {/* 页头：返回 + 标题（版式同 /orders/new、/products/new） */}
      <div className="flex items-center gap-3 mb-6">
        <button
          type="button"
          onClick={() => router.push('/inbound-orders')}
          className="p-2 rounded-lg border border-neutral-200 hover:bg-neutral-50 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5 text-neutral-600" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-neutral-900">新增入库单</h1>
          <p className="text-sm text-neutral-500 mt-0.5">
            建单只登记、<strong>不动库存</strong>；过账时系统逐行生成批次号（PC-yyyyMMdd-NNNN，
            一行 = 一个批次）并加库存、按移动加权平均重算成本
          </p>
        </div>
      </div>

      <div className="space-y-6">
        {/* ============= 单据信息 ============= */}
        <Card>
          <div className="p-6">
            <SectionTitle icon={<FileText className="w-4 h-4" />} title="单据信息" />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <Select
                label="单据来源"
                aria-label="单据来源"
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value as 'purchase' | 'opening' })}
                options={SOURCE_OPTIONS}
              />
              <Input
                label="供应商"
                value={form.supplier}
                onChange={(e) => setForm({ ...form, supplier: e.target.value })}
                placeholder="如：柯桥××布行"
              />
              <Input
                label="供应商送货单号"
                value={form.supplierDocNo}
                onChange={(e) => setForm({ ...form, supplierDocNo: e.target.value })}
              />
              <Input
                label="仓库 / 仓位"
                value={form.warehouse}
                onChange={(e) => setForm({ ...form, warehouse: e.target.value })}
              />
              {/* 奇数个字段的**最后一个满行**（家族先例：`/orders/new` 收货信息的「收货地址」）——
                  issue #5871：改前第 3 行右半留空。
                  ⚠️ **跨度只能加在包裹层**：`Input` 把 `className` 透传到 `<input>` 上，而栅格的
                  子项是它外层那个 `w-full` div ⇒ 把 `md:col-span-2` 传给 `Input` 等于没加（不报错、也不生效）。 */}
              <div className="md:col-span-2" data-testid="inbound-date-field">
                <Input
                  label="入库日期"
                  type="date"
                  value={form.inboundDate}
                  onChange={(e) => setForm({ ...form, inboundDate: e.target.value })}
                />
              </div>
            </div>
            <div className="mt-4">
              <Input
                label="备注"
                value={form.remark}
                onChange={(e) => setForm({ ...form, remark: e.target.value })}
              />
            </div>
            <p className="mt-4 text-xs text-neutral-500 bg-neutral-50 border border-neutral-200 rounded-lg p-3 leading-relaxed">
              保存为草稿<strong>不会改动库存</strong>；批次号在<strong>过账</strong>时由系统自动生成
              （<span className="font-mono">PC-yyyyMMdd-NNNN</span>，一行 = 一个批次），
              库存与成本也在过账时一次性写入（可核对后再过账）。
            </p>
          </div>
        </Card>

        {/* ============= 入库明细 ============= */}
        <Card>
          <div className="p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <SectionTitle icon={<Package className="w-4 h-4" />} title="入库明细" />
              <span className="text-xs text-neutral-400">
                共 {draftLines.length} 行（一行 = 一个批次）
              </span>
            </div>

            {/* 选品：左「搜商品」/ 右「勾 SKU」—— 两栏各自滚动，不再被页脚截断 */}
            <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="rounded-lg border border-neutral-200 overflow-hidden">
                <div className="flex items-center gap-2 px-3 h-10 border-b border-neutral-100 bg-neutral-50/60">
                  <Search className="w-4 h-4 text-neutral-400 shrink-0" />
                  <input
                    aria-label="搜索商品"
                    placeholder="商品名称 / 货号"
                    value={productKeyword}
                    onChange={(e) => setProductKeyword(e.target.value)}
                    className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none placeholder:text-neutral-400"
                  />
                </div>
                <div className="max-h-72 overflow-auto">
                  {productOptions.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => void pickProduct(p)}
                      className={cn(
                        'w-full text-left px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50',
                        pickedProduct?.id === p.id && 'bg-primary-50',
                      )}
                    >
                      {p.name}
                      {p.skuCode ? <span className="text-neutral-400 ml-2">({p.skuCode})</span> : null}
                    </button>
                  ))}
                  {productOptions.length === 0 && (
                    <div className="px-3 py-6 text-sm text-neutral-400 text-center">
                      输入关键词搜索商品
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-lg border border-neutral-200 overflow-hidden">
                <div className="flex items-center gap-2 px-3 h-10 border-b border-neutral-100 bg-neutral-50/60">
                  <Layers className="w-4 h-4 text-neutral-400 shrink-0" />
                  <span className="text-sm text-neutral-600">
                    选择入库 SKU（勾选即加入明细，一行 = 一个批次）
                  </span>
                </div>
                <div className="max-h-72 overflow-auto">
                  {!pickedProduct && (
                    <div className="px-3 py-6 text-sm text-neutral-400 text-center">
                      先在左侧选一个商品
                    </div>
                  )}
                  {pickedProduct &&
                    productSkus.map((sku) => {
                      const checked = draftLines.some((l) => l.skuId === Number(sku.id))
                      return (
                        <label
                          key={sku.id}
                          className="flex items-center gap-3 px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50 cursor-pointer"
                        >
                          <input type="checkbox" checked={checked} onChange={() => toggleSku(sku)} />
                          <span className="flex-1 min-w-0">
                            {sku.colorName || '默认色'} / {sku.doorWidth || '默认门幅'}
                          </span>
                          <span className="text-neutral-500 shrink-0">
                            当前库存 {formatStockQuantity(sku.stock ?? 0)}
                          </span>
                        </label>
                      )
                    })}
                  {pickedProduct && !skuLoading && productSkus.length === 0 && (
                    <div className="px-3 py-6 text-sm text-neutral-400 text-center">
                      该商品还没有 SKU，请先在商品详情维护 SKU
                    </div>
                  )}
                  {pickedProduct && skuLoading && (
                    <div className="px-3 py-6 text-sm text-neutral-400 text-center">加载中…</div>
                  )}
                </div>
              </div>
            </div>

            {/* 明细表 */}
            {draftLines.length > 0 ? (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 text-neutral-600">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium">货号 / 颜色 / 门幅</th>
                      <th className="text-right px-3 py-2 font-medium w-28">数量*</th>
                      <th className="text-right px-3 py-2 font-medium w-32">单价(元)</th>
                      <th className="text-left px-3 py-2 font-medium w-36">缸号</th>
                      {form.source === 'opening' && (
                        <th className="text-left px-3 py-2 font-medium w-40">旧系统批次号</th>
                      )}
                      <th className="text-right px-3 py-2 font-medium w-32">卷长(米)</th>
                      <th className="text-left px-3 py-2 font-medium w-36">批次号</th>
                      <th className="w-12" />
                    </tr>
                  </thead>
                  <tbody>
                    {draftLines.map((l) => (
                      <tr key={l.skuId} className="border-t border-neutral-100">
                        <td className="px-3 py-2 text-neutral-700">{l.label}</td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min={0.1}
                            step={0.1}
                            aria-label={`${l.label} 数量`}
                            value={l.quantity}
                            onChange={(e) => patchLine(l.skuId, { quantity: e.target.value })}
                            className={cn(CELL_INPUT, 'text-right')}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min={0}
                            step="0.01"
                            aria-label={`${l.label} 单价`}
                            value={l.unitCost}
                            onChange={(e) => patchLine(l.skuId, { unitCost: e.target.value })}
                            className={cn(CELL_INPUT, 'text-right')}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            aria-label={`${l.label} 缸号`}
                            value={l.dyeLot}
                            onChange={(e) => patchLine(l.skuId, { dyeLot: e.target.value })}
                            className={CELL_INPUT}
                          />
                        </td>
                        {form.source === 'opening' && (
                          <td className="px-3 py-2">
                            <Input
                              aria-label={`${l.label} 旧系统批次号`}
                              placeholder="旧系统的批次号"
                              value={l.legacyBatchNo}
                              onChange={(e) => patchLine(l.skuId, { legacyBatchNo: e.target.value })}
                              className={CELL_INPUT}
                            />
                          </td>
                        )}
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min={0}
                            step="0.01"
                            aria-label={`${l.label} 卷长`}
                            value={l.rollLengthM}
                            onChange={(e) => patchLine(l.skuId, { rollLengthM: e.target.value })}
                            className={cn(CELL_INPUT, 'text-right')}
                          />
                        </td>
                        {/* 批次号：草稿不发号（过账时逐行生成）—— 列出来是为了建单时就知道追溯标识 */}
                        <td className="px-3 py-2 text-xs text-neutral-400 whitespace-nowrap">
                          过账后生成
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            aria-label={`移除 ${l.label}`}
                            onClick={() => toggleSku({ id: String(l.skuId) } as ProductSku)}
                            className="text-neutral-400 hover:text-red-600 px-2"
                          >
                            ×
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-xs text-neutral-400 mt-2 leading-relaxed">
                  数量按 0.1 米粒度、大于 0 即可（0.5 米的尾料能登记；0 与 2.755 会被拒绝；
                  超 1 位小数不会四舍五入）；单价留空 = 只加数量、不算成本（均价保持原值）；
                  缸号与旧系统批次号都是外部事实，与系统生成的批次号是三件不同的事。
                </p>
              </div>
            ) : (
              <p className="mt-5 text-sm text-neutral-400 text-center py-6 border border-dashed border-neutral-200 rounded-lg">
                还没有明细：左侧搜商品 → 勾选 SKU 即加入（一行 = 一个批次）
              </p>
            )}
          </div>
        </Card>
      </div>

      {/* 底部吸底汇总条（同 /orders/new 的 fee-summary-bar：常态只占一行） */}
      <div
        data-testid="inbound-create-summary-bar"
        className="sticky bottom-0 z-20 mt-6 rounded-xl border border-neutral-200 bg-white/95 px-4 py-3 backdrop-blur shadow-[0_-2px_12px_rgba(0,0,0,0.05)]"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-neutral-500">合计金额</span>
            <span
              data-testid="inbound-create-total"
              className="text-xl font-semibold text-primary-600"
            >
              ¥{draftTotal.toFixed(2)}
            </span>
            <span className="text-xs text-neutral-400">
              共 {draftLines.length} 行；过账后逐行生成批次号
            </span>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => router.push('/inbound-orders')}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} loading={submitting}>
              保存为草稿
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** 分区标题（版式与 /orders/new 的 `SectionTitle` 同款：主色图标底 + 标题） */
function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 h-6 rounded bg-primary-50 text-primary-600 inline-flex items-center justify-center">
        {icon}
      </span>
      <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
    </div>
  )
}
