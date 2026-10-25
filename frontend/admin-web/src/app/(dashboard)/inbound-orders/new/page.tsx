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

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, FileText, Package } from 'lucide-react'
import { toast } from 'sonner'
import { inboundOrderApi } from '@/lib/api'
import { Button, PageCard, PageHeader, Input, Select } from '@/components/ui'
import SkuPicker, { type SkuPickerChoice, skuLineLabel } from '@/components/products/SkuPicker'
import { cn } from '@/lib/utils'
import { checkStockQuantity } from '@/lib/stock-quantity'

/** 入库明细行（含 SKU 的展示快照，提交时只取 productId/skuId/quantity/unitCost/dyeLot/legacyBatchNo/rollLengthM） */
interface DraftLine {
  productId: string
  // 🔴 issue #5904：SKU id 是**雪花号字符串**（实测 ≈2.1e18，远超 JS 安全整数 9.007e15）——
  // 全程**原样透传**，不许 `Number()`（一转换就吞末位 ⇒ 服务端查不到该 SKU ⇒ 建单必失败）
  skuId: string
  label: string
  stock: number
  /**
   * 卷数（可选；issue #7644 / #7709）—— 与「卷长(米/卷)」一起构成**按卷录入**：
   * 两者齐备 ⇒ 数量格只读，格下显示「卷数 × 卷长 = 米数」的换算供核对；
   * 留空 ⇒ 回到「数量（米）」手填（散剪 / 尾料按米买走这条路）。
   *
   * 🔴 **本页不再负责乘**（issue #7709）：换算的唯一权威是服务端（`InboundOrderService.metersOfRolls`）——
   * 提交时把卷数原样带上（`rollCount`），由服务端算出 `inbound_order_items.quantity`（恒为米）。
   * 改前换算在前端（#7646），客户端没乘（旧 bundle / 直接填数量）就把「1 卷 × 70 米」记成 1 米。
   * 格下那行米数**只是预览**：它不进库存，服务端也不采信随行的 quantity。
   */
  rollCount: string
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

/**
 * 卷数 × 卷长 ⇒ 入库米数**预览**（商家端「按卷录入」的显示，issue #7709）。
 *
 * 🔴 它**只用于上屏核对**：真正的换算在服务端（`InboundOrderService.metersOfRolls`），
 * 提交时随行带的是 `rollCount` + `rollLengthM`，服务端据此算 `inbound_order_items.quantity`。
 * 改前这里是**权威换算**（#7646），客户端不乘就少记 70 倍
 * （实测 RK-20261024-0001：1 卷 × 70 米 ⇒ 库存 1 米，下单报「仅剩 1.0 米」）。
 *
 * 不静默取整：`1 卷 × 67.25 米 = 67.25` 原样返回，交给 `checkStockQuantity` 显式拒绝
 * （0.1 米粒度）；只把浮点尾差（`3 × 0.1 = 0.30000000000000004`）按 2 位归一。
 */
function metersFromRolls(rollCount: string, rollLengthM: string): string | null {
  if (rollCount.trim() === '' || rollLengthM.trim() === '') return null
  const count = Number(rollCount)
  const len = Number(rollLengthM)
  if (!Number.isFinite(count) || !Number.isFinite(len) || count <= 0 || len <= 0) return null
  return String(Number((count * len).toFixed(2)))
}

/**
 * **本地当天** `YYYY-MM-DD`（`<input type="date">` 的取值口径，issue #5912）。
 *
 * ⚠️ 不得写成 `new Date().toISOString().slice(0, 10)`：那是 **UTC 日**，在 UTC+8 的每天
 * 00:00~08:00（CST）会**倒退一天**（同族实证：issue #4783 / #4772；正确参照物 = 同仓
 * `orders/page.tsx` 与 `finance/page.tsx` 的私有 `formatDate`）。
 * 未抽公共函数的原因同 `products/page.tsx` 的 `formatLocalDate`：仓内没有本地日期工具，
 * 且这几个页面的用途各不相同 —— 为一处使用抽公共模块属过度建设，故就地最小实现。
 */
function localToday(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

export default function NewInboundOrderPage() {
  const router = useRouter()

  const [draftLines, setDraftLines] = useState<DraftLine[]>([])
  const [form, setForm] = useState({
    supplier: '',
    supplierDocNo: '',
    warehouse: '',
    inboundDate: localToday(), // 默认当天（后端在 `null` 时也取当天 —— 前端把同一语义**显式**摆给商家看）
    remark: '',
    source: 'purchase' as 'purchase' | 'opening',
  })
  const [submitting, setSubmitting] = useState(false)

  /** 勾选 SKU ⇒ 加入/移出草稿行（勾选器只报「哪个商品的哪个 SKU」，留不留原文不动） */
  const toggleSku = ({ product, sku }: SkuPickerChoice) => {
    setDraftLines((prev) => {
      if (prev.some((l) => l.skuId === sku.id)) {
        return prev.filter((l) => l.skuId !== sku.id)
      }
      return [
        ...prev,
        {
          productId: product.id,
          skuId: sku.id,
          label: skuLineLabel(product, sku),
          stock: sku.stock ?? 0,
          rollCount: '',
          quantity: '1',
          unitCost: '',
          dyeLot: '',
          legacyBatchNo: '',
          rollLengthM: '',
        },
      ]
    })
  }

  /** 行内「×」：按 skuId 摘掉这一行（不经勾选器 —— 勾选器只认它自己右栏里列出的 SKU） */
  const removeLine = (skuId: string) => {
    setDraftLines((prev) => prev.filter((l) => l.skuId !== skuId))
  }

  const patchLine = (skuId: string, patch: Partial<DraftLine>) => {
    setDraftLines((prev) =>
      prev.map((l) => {
        if (l.skuId !== skuId) return l
        const next = { ...l, ...patch }
        // 卷数/卷长任一变化 ⇒ 数量（米）由换算决定；卷数被清空 ⇒ 回到按米手填（issue #7644）
        if (patch.rollCount !== undefined || patch.rollLengthM !== undefined) {
          if (next.rollCount.trim() !== '') {
            next.quantity = metersFromRolls(next.rollCount, next.rollLengthM) ?? ''
          }
        }
        return next
      }),
    )
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
      // 按卷录入（issue #7644）：卷数必须是正整数；填了卷数就必须有卷长，且两者之积要能落成米数
      if (l.rollCount.trim() !== '') {
        const count = Number(l.rollCount)
        if (!Number.isInteger(count) || count <= 0) {
          toast.error(
            `「${l.label}」的卷数必须是正整数（散剪 / 尾料按米入库：卷数留空，数量（米）直接填）`,
          )
          return
        }
        if (l.rollLengthM.trim() === '') {
          toast.error(`「${l.label}」填了卷数就要填每卷米数（卷长）`)
          return
        }
        if (l.quantity === '') {
          toast.error(`「${l.label}」的卷数 × 卷长换算不出合法的入库米数`)
          return
        }
      }
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
          // 卷数（issue #7709）：**服务端据此算入库米数**（卷数 × 卷长），并据此忽略随行的 quantity
          // —— 换算的唯一权威在服务端，本页只是把商家填的卷数原样带上
          rollCount: l.rollCount === '' ? null : Number(l.rollCount),
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
      <div className="mb-6 flex items-center gap-3">
        <button
          type="button"
          onClick={() => router.push('/inbound-orders')}
          className="p-2 rounded-lg border border-neutral-200 hover:bg-neutral-50 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5 text-neutral-600" />
        </button>
        <PageHeader
          className="flex-1"
          title="新增入库单"
          subtitle={<>登记一张新的到货入库单 —— <strong>保存草稿不动库存</strong>，过账时才生成批次号并加库存</>}
        />
      </div>

      <div className="space-y-6">
        {/* ============= 单据信息 ============= */}
        <PageCard padded={false}>
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
              {/* 入库日期：**标准尺寸**的原生 date 控件（issue #5912）—— 改前它跨 2 列（#5871 为了消掉
                  末行右半的空白），于是输入框被栅格**拉伸到整行宽**，日历图标孤零零挂在最右侧。
                  用户 2026-10-01 裁定以「控件标准尺寸」为准 ⇒ 解除跨列，宽度由控件自己给死。
                  ⚠️ 宽度必须加在 `Input` 的 `className` 上（它把 className 透传到 `<input>`，同一次
                  `cn()` 里 `w-full` 会被 twMerge 顶掉）；加在包裹层上**不生效**，那是栅格子项、不是输入框。
                  ℹ️ 2 列 + 5 个字段 ⇒ 末行右半必然为空（计数事实）；空白现在挨着**本来就窄**的日期控件，
                  读起来是正常收尾，而不是「缺一个字段」。 */}
              <div data-testid="inbound-date-field">
                <Input
                  label="入库日期"
                  type="date"
                  value={form.inboundDate}
                  onChange={(e) => setForm({ ...form, inboundDate: e.target.value })}
                  className="w-44"
                />
              </div>
            </div>
            {/* 备注：**多行文本域**（issue #5912）—— 改前是单行 `Input`（备注天然是多行文本）。
                类名与共享 `Input` 同族（同圆角 / 同 focus ring），并补 `htmlFor` + `id` 让 label
                真关联到控件（`Input` 的 label 没有 htmlFor，是新写的这一处不必继承的缺口）。 */}
            <div className="mt-4">
              <label
                htmlFor="inbound-remark"
                className="block text-sm font-medium text-neutral-700 mb-1.5"
              >
                备注
              </label>
              <textarea
                id="inbound-remark"
                rows={3}
                value={form.remark}
                onChange={(e) => setForm({ ...form, remark: e.target.value })}
                placeholder="可填写收货注意、质检情况、随货单据等（选填）"
                className="w-full px-3 py-2 rounded-lg border border-neutral-300 bg-white text-sm leading-relaxed resize-none placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              />
            </div>
            <p className="mt-4 text-xs text-neutral-500 bg-neutral-50 border border-neutral-200 rounded-lg p-3 leading-relaxed">
              保存为草稿<strong>不会改动库存</strong>；批次号在<strong>过账</strong>时由系统逐行自动生成
              （形如 <span className="font-mono">PC-20261001-0001</span>，一行 = 一个批次），
              库存与成本也在过账时一次性写入（可核对后再过账）。
            </p>
          </div>
        </PageCard>

        {/* ============= 入库明细 ============= */}
        <PageCard padded={false}>
          <div className="p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <SectionTitle icon={<Package className="w-4 h-4" />} title="入库明细" />
              <span className="text-xs text-neutral-400">
                共 {draftLines.length} 行（一行 = 一个批次）
              </span>
            </div>

            {/* 选品：公共件（issue #7567）—— 左「搜商品」/ 右「勾 SKU」，两栏各自滚动。
                交互与读失败/空态的分离规则都收在 `SkuPicker` 里（采购单 / 价格本共用同一份）。 */}
            <div className="mt-4">
              <SkuPicker
                testIdPrefix="inbound"
                title="选择入库 SKU（勾选即加入明细，一行 = 一个批次）"
                selectedSkuIds={draftLines.map((l) => l.skuId)}
                onToggle={toggleSku}
              />
            </div>

            {/* 明细表 */}
            {draftLines.length > 0 ? (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 text-neutral-600">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium whitespace-nowrap">货号 / 颜色 / 门幅</th>
                      <th className="text-right px-3 py-2 font-medium w-24 whitespace-nowrap">卷数</th>
                      <th className="text-right px-3 py-2 font-medium w-32 whitespace-nowrap">卷长(米/卷)</th>
                      <th className="text-right px-3 py-2 font-medium w-28 whitespace-nowrap">数量（米）*</th>
                      <th className="text-right px-3 py-2 font-medium w-32 whitespace-nowrap">单价(元)</th>
                      <th className="text-left px-3 py-2 font-medium w-36 whitespace-nowrap">缸号</th>
                      {form.source === 'opening' && (
                        <th className="text-left px-3 py-2 font-medium w-40 whitespace-nowrap">旧系统批次号</th>
                      )}
                      <th className="text-left px-3 py-2 font-medium w-36 whitespace-nowrap">批次号</th>
                      <th className="w-12 whitespace-nowrap" />
                    </tr>
                  </thead>
                  <tbody>
                    {draftLines.map((l) => (
                      <tr key={l.skuId} className="border-t border-neutral-100">
                        <td className="px-3 py-2 text-neutral-700">{l.label}</td>
                        <td className="px-3 py-2">
                          {/* 卷数（issue #7644）：填了它 + 卷长 ⇒ 数量（米）自动换算并只读 */}
                          <Input
                            type="number"
                            min={1}
                            step={1}
                            aria-label={`${l.label} 卷数`}
                            placeholder="按卷填"
                            value={l.rollCount}
                            onChange={(e) => patchLine(l.skuId, { rollCount: e.target.value })}
                            className={cn(CELL_INPUT, 'text-right')}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min={0}
                            step="0.01"
                            aria-label={`${l.label} 卷长`}
                            placeholder="每卷米数"
                            value={l.rollLengthM}
                            onChange={(e) => patchLine(l.skuId, { rollLengthM: e.target.value })}
                            className={cn(CELL_INPUT, 'text-right')}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min={0.1}
                            step={0.1}
                            aria-label={`${l.label} 数量（米）`}
                            value={l.quantity}
                            readOnly={l.rollCount.trim() !== ''}
                            onChange={(e) => patchLine(l.skuId, { quantity: e.target.value })}
                            className={cn(
                              CELL_INPUT,
                              'text-right',
                              l.rollCount.trim() !== '' && 'bg-neutral-50 text-neutral-600',
                            )}
                          />
                          {l.rollCount.trim() !== '' && l.quantity !== '' && (
                            <p className="mt-1 text-xs text-neutral-400 text-right whitespace-nowrap">
                              {l.rollCount} 卷 × {l.rollLengthM} 米
                            </p>
                          )}
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
                        {/* 批次号：草稿不发号（过账时逐行生成）—— 列出来是为了建单时就知道追溯标识 */}
                        <td className="px-3 py-2 text-xs text-neutral-400 whitespace-nowrap">
                          过账后生成
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            aria-label={`移除 ${l.label}`}
                            onClick={() => removeLine(l.skuId)}
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
                  <strong className="text-neutral-500">按卷采购</strong>：填「卷数 + 卷长」⇒
                  <span className="font-mono">卷数 × 每卷米数</span> 就是入库米数（格下那行是换算预览，
                  过账时由服务端按同一口径记账）；<strong className="text-neutral-500">散剪 / 尾料按米买</strong>：
                  卷数留空，数量（米）直接填。数量按 0.1 米粒度、大于 0（0.5 米的尾料能登记；0 与 2.755 会被拒绝；
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
        </PageCard>
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
