/**
 * 下单页的**商品组卡**（一块布 = 一组）—— issue #8725 第一档切片产物。
 *
 * 单一职责：商品基础属性（选择商品 / 颜色 / 门幅 / 售卖形态 / 帘体）+ 净尺寸 + 组内那一套帘的排布；
 * 改了组级属性就**组内所有行同步**（它们是同一块布的属性）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { FONT_PX_11 } from '@/lib/design-tokens'
import { Package, Search, Trash2 } from 'lucide-react'
import { ORDER_DERIVATION_INPUT_KEYS } from '@/lib/image-recognize'
import { RecognizedBadge } from '@/components/image-recognize/ImageRecognizeButton'
import { cn, resolveImageUrl } from '@/lib/utils'
import { NumberInput, SELECT_CONTROL } from '@/components/ui'
import { METERS_SOURCE_MANUAL as LINE_METERS_SOURCE_MANUAL } from '@/lib/craft-calc-request'
import { CURTAIN_BODY_OPTIONS, type CurtainBody } from '@/lib/order-craft-fields'
import {
  SALE_FORM_FABRIC,
  SALE_FORM_FINISHED,
  type OrderLineItem,
  type OrderProductSku,
  type ProductGroup,
  type SaleForm,
} from '@/lib/order-create/types'
import { formatAmount, uniqueColors } from '@/lib/order-create/display'
import { sizeAutoBadgesOf } from '@/components/orders/order-create/SizeAutoBadges'
import { positiveOrNull } from '@/lib/order-create/calc'
import { FabricRow } from '@/components/orders/order-create/FabricRow'
import { CollapsibleHeader } from '@/components/orders/order-create/WizardStep'
import { Label } from '@/components/orders/order-create/primitives'

export interface ProductGroupBlockProps {
  index: number
  group: ProductGroup
  canRemove: boolean
  errors: Record<string, string>
  /**
   * **「哪儿缺了」的定向信号**（issue #5840）：`tick` 每次提交失败 / 点汇总条目都自增
   * ⇒ 本组件据此把**整卡与出错的那一步自动展开**（`key` = 要定位到哪一个报错项）。
   */
  errorFocus: { key: string; tick: number }
  /** 选择商品（组级）：选完写回**组内所有部位行** */
  onPickProduct: () => void
  /** 颜色（组级）：同一块布的颜色，组内同步 */
  onSelectColor: (colorId: string) => void
  /** 门幅 / 售卖方式（组级）：同上 */
  onSelectSku: (sku: OrderProductSku) => void
  /** 售卖形态（组级，issue #4493）：布料 / 成品帘 */
  onChangeSaleForm: (form: SaleForm) => void
  /** 帘体（组级，issue #4521；#4874 起只有 `布帘` / `纱帘` 两档） */
  onChangeCurtainBody: (body: CurtainBody) => void
  /** 删除整个商品组 */
  onRemoveGroup: () => void
  /**
   * **净尺寸**（2026-09-28 布局）：宽 / 高两格由组级渲染（商品 / 颜色之后、门幅之前）——
   * 与「门幅规则要等尺寸填齐才能自动选最优门幅」（#4877/#4899）同序。
   */
  onChangeWidth: (w: number | null) => void
  onChangeHeight: (h: number | null) => void
  /**
   * 渲染本组这一套帘（由页面传入，保证 props 装配只有一处）。
   *
   * `slots.spec` / `slots.specExtras` = **门幅 / 规格**节点（2026-09-30 第四批：它搬进①用料与规格，
   * 与用料米数 / 单价同一行）。节点的 **JSX 只有一份**（在组级算），经这里交给行内渲染
   * ⇒ 不会出现两处各写一遍门幅下拉的实现分叉。
   */
  renderPosition: (
    line: OrderLineItem,
    slots: { spec: React.ReactNode; specExtras: React.ReactNode }
  ) => React.ReactNode
  /** 布料行（无部位）的 米数 / 单价 回调（issue #4493） */
  onChangeQty: (lineId: string, qty: number) => void
  onChangePrice: (lineId: string, price: number) => void
  /**
   * **整卷售卖**（issue #5846，用户裁定 A）：布料行的 卷数 / 每卷实际米数。
   * `null` = 留空（卷数留空 ⇒ 两个键都不进 payload，服务端按货号卷长派生）。
   */
  onChangeRollCount: (lineId: string, rollCount: number | null) => void
  onChangeRollLength: (lineId: string, rollLengthM: number | null) => void
}

/**
 * **商品组**（issue #4485；issue #4521 起 = **一套帘**）：一块布（同商品 / 同色 / 同门幅）
 * 下渲染**一份** ①尺寸与数量 ②工艺规格 ③加工项 ④特殊选项。
 *
 * ⚠️ issue #4874（用户 2026-09-21 需求批次）—— 下单页**两步化**：区块 1 = 尺寸与数量 + 工艺规格、
 * 区块 2 = 加工项 + 特殊选项（原四段手风琴的序号 / 摘要 / 展开态全部按新结构走）；
 * 「布帘+纱帘」档整族删除；「加工项」区块新增**加工费组合明细块**（可就地改未定价单价）；
 * 收货信息补**常用物流/快递 + 常用物流公司**两个可编辑控件；收货信息里的「套窗」等术语统一为「套 / 帘」。
 *
 * 用户 2026-09-19 口径：「新增部位应该在**已选择的商品下**去新增，现在像是两个商品，
 * 商品的**基础属性应该共用**」→ 随后进一步裁定「**移除部位功能，其实完全不需要**」：
 * 一个商品组 = 一套帘，需要纱帘时改**帘体**（`curtainBody`），而不是再加一行。
 *
 * 为什么这样切：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径，与展示无关
 * —— 旧实现把落库口径直接当成了 UI 结构（复制一行 = 复制整张商品卡）⇒ 同一商品的两个部位
 * 看起来像两个商品、颜色与门幅还要各选一遍。
 *
 * 本组件只负责**商品基础属性**（选择商品 / 颜色 / 门幅·售卖方式 / 售卖形态 / 帘体）与那一套帘的排布；
 * 组内改颜色、门幅、售卖形态或帘体 ⇒ **组内所有行同步**（它们是同一块布的属性）。
 */
export function ProductGroupBlock({
  index,
  group,
  canRemove,
  errors,
  errorFocus,
  onPickProduct,
  onSelectColor,
  onSelectSku,
  onChangeSaleForm,
  onChangeCurtainBody,
  onRemoveGroup,
  onChangeWidth,
  onChangeHeight,
  renderPosition,
  onChangeQty,
  onChangePrice,
  onChangeRollCount,
  onChangeRollLength,
}: ProductGroupBlockProps) {
  /**
   * **整卡折叠态**（issue #4679，用户原话「这里加个可折叠的交互」）—— 组头整行是开关。
   * **默认展开**（不改现有默认行为）；状态落在**本组件** ⇒ 多商品时各卡独立、互不影响。
   * 与卡体内四步手风琴（#4511）正交：那是「哪一步展开」，这是「整卡展开」。
   */
  const [open, setOpen] = useState(true)
  // ⚠️ 2026-09-29（用户裁定「移除这种设计」）：门幅 chips 常态就展开 ——
  // `skuPickerOpen` 连同「只读摘要 + 点『改』」一并删除（规则解仍由页面自动选中，直接点 chips 换一支）。
  const colorOptions = useMemo(() => uniqueColors(group.product?.skus), [group.product])
  const skuOptions = useMemo(() => {
    if (!group.product?.skus || group.selectedColorId == null) return []
    return group.product.skus.filter((s) => s.colorId === group.selectedColorId)
  }, [group.product, group.selectedColorId])

  const first = group.lines[0]
  const errProduct = errors[`line_${first.id}_product`]
  const errColor = errors[`line_${first.id}_color`]
  const errSpec = errors[`line_${first.id}_spec`]
  // 净尺寸（2026-09-28 提到组级）的就地报错 + 识别徽标来源，与行内同源
  const errWidth = errors[`line_${first.id}_width`]
  const errHeight = errors[`line_${first.id}_height`]
  const sizeAutoBadges = sizeAutoBadgesOf(first)

  /**
   * 本组的**错误计数**（issue #5840）—— 出现在组头与①步骤标题上 ⇒ **整卡或该步收起时也看得见**
   * 「这儿缺 N 项」，不必先展开再逐格找。计数口径 = 该组各行在 `errors` 里的键。
   */
  const groupErrorCount = group.lines.reduce(
    (n, l) => n + Object.keys(errors).filter((k) => k.startsWith(`line_${l.id}_`)).length,
    0
  )
  const containerRef = useRef<HTMLDivElement>(null)
  /** 本次定位是不是冲本组来的 —— 只有它滚屏，避免一次提交让多张卡同时滚 */
  const ownsFocusKey = group.lines.some((l) => errorFocus.key.startsWith(`line_${l.id}_`))
  /**
   * **提交失败 / 点了汇总里某一条 ⇒ 整卡自动展开**（issue #5840）。
   *
   * 不展开的后果（本单要消灭的形态）：整卡收起时，卡里的宽高 / 数量 / 单价 / 自动识别报错
   * **一个字都看不见**，页面上只弹一句 toast ⇒ 商家只能反复点提交。
   * （步骤①自身的展开在 `LineItemBlock` 里 —— 只有它持有 `openStep`。）
   *
   * ⚠️ 依赖 `tick` 而不是 `key`：同一处连按两次也要重新展开（只跟 key 的话第二次不触发）。
   */
  useEffect(() => {
    if (errorFocus.tick === 0 || groupErrorCount === 0) return
    setOpen(true)
    if (ownsFocusKey) containerRef.current?.scrollIntoView?.({ block: 'center' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errorFocus.tick])

  /**
   * **门幅 / 规格**节点（issue #4877 裁定 C 未变：多门幅时按门幅规则自动选最省的 ⇒ 商家常态**零点击**）。
   *
   * 🔴 **2026-09-30 第四批**：用户逐字「门幅放进用料与规格中，和用料米数、单价放一行」
   * —— 它和用料米数 / 单价一样是「**系统给的值、商家可就地改**」，三个数同一行最省空间，
   * 也把动线说清（门幅决定用料与单价 ⇒ 三个数同屏）。
   * ⚠️ 节点**只此一份**：成品帘经 `renderPosition` 的 `slots.spec` 交给 ①用料与规格，
   * 布料经 `FabricRow` 的 `specPicker`（布料没有「用料与规格」这一步，但「按什么规格买」仍是它的输入）。
   * ⚠️ 「为什么是这一支」仍说人话（`sku-choice-reason`）；**顺序口径不在本文件复述**
   * （真值源 = 设计文档，复述会被 `test_craft_calc_ranking_order_single_source.py` 判红）。
   */
  const specPicker =
    group.selectedColorId != null && skuOptions.length > 0 ? (
      <>
        <Label required>门幅 / 规格</Label>
        <div className="flex flex-wrap items-center gap-2">
          <select
            data-testid="sku-select"
            aria-label="门幅 / 规格"
            value={group.selectedSku ? String(group.selectedSku.id) : ''}
            onChange={(e) => {
              const picked = skuOptions.find((sku) => String(sku.id) === e.target.value)
              if (picked) onSelectSku(picked)
            }}
            className={cn(SELECT_CONTROL, 'min-w-[15rem]', 'max-w-full')}
          >
            {group.selectedSku === null && <option value="">请选择规格</option>}
            {skuOptions.map((sku) => (
              <option key={sku.id} value={String(sku.id)}>
                {sku.doorWidth || '默认规格'} · ¥{Number(sku.price).toFixed(2)}/米 · 库存{' '}
                {sku.stock ?? 0}
              </option>
            ))}
          </select>
        </div>
        {errSpec && <p className="mt-1.5 text-sm text-red-600">{errSpec}</p>}
      </>
    ) : null

  /**
   * 门幅的**推导细节**（2026-09-29 新增；2026-09-30 随门幅搬进 ① 的标题右侧栏）：
   * 规则解 / 服务端依据 / 候选门幅 —— 「为什么是这一支」的**唯一**落点。
   *
   * 🔴 **2026-09-30 第五批：删掉两块重复文案**（用户逐字「这种文字我觉得没有添加的必要，可以移除掉吧」）：
   * ① `sku-summary`（`门幅 2.8米 · ¥23.80/米 · 库存 100`）—— 与 `<select>` 里选中项**同一串字**，隔一行再写一遍；
   * ② `sku-choice-reason`（`系统按窗宽 6 米挑了最省料的门幅 —— 要换直接改上面的下拉`）—— 同一句在下面
   *    `door-width-details` 的「规则解 + 系统依据」里说得更全（且那里可展开）。
   * ⚠️ 「这个门幅是系统挑的还是你手选的」**没有丢**：用料方案的逐项读数会给手选过的那项标「（人工）」
   * （`craft-plan-items` + `planSources.doorWidth`），判据仍在（OR-052 判据 4 改钉）。
   *
   * ⚠️ **只给成品帘**：这套文案讲的是「按窗宽挑最省料的门幅 / 分幅 / 接高」，而布料没有净尺寸、
   * 也没有分幅与加工 ⇒ 对布料说这句是**假话**（本批顺手去掉）。
   */
  const specExtras =
    group.saleForm !== SALE_FORM_FABRIC && group.selectedColorId != null && skuOptions.length > 0 ? (
      <>
        {/* **门幅推导细节**（2026-09-29 新增）：把「为什么是这一支」的依据与候选摆出来。
            ⚠️ 规则解与依据都来自**服务端** `doorWidthPlan`（前端不编一句、不自己算可行性）。
            🔴 2026-09-30 第六批：这里**不再是折叠项** —— 整块推导细节只有一个折叠区
            （`derivation-panel`），本块退回「① 的标题行 + 内容」（编号即标题）。 */}
        <div data-testid="door-width-details" className="rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2">
          <p className="text-xs text-neutral-600">
            <span className="font-medium">① 门幅</span>
            {group.selectedSku?.doorWidth ? ` · ${group.selectedSku.doorWidth}` : ''}
          </p>
          <div className={`mt-1 rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2 ${FONT_PX_11} text-neutral-500`}>
            <p data-testid="door-width-candidates">
              候选门幅（该颜色共 {skuOptions.length} 支）：
              {skuOptions.map((sku, i) => (
                <span key={sku.id}>
                  {i > 0 ? ' / ' : ''}
                  {sku.doorWidth || '默认规格'}
                  {sku.id === group.selectedSku?.id ? '（当前）' : ''}
                </span>
              ))}
            </p>
            <p data-testid="door-width-rule-solution">
              规则解：
              {first.doorWidthPlan?.door_width != null
                ? `${first.doorWidthPlan.door_width} 米`
                : '不可判定（缺尺寸 / 该颜色没有可用门幅）'}
            </p>
            {first.doorWidthPlan?.reason ? (
              <p data-testid="door-width-plan-reason">系统依据：{first.doorWidthPlan.reason}</p>
            ) : null}
            {/* 「这一支是系统挑的还是你手选的」**没丢**，只是收进这里（用户 2026-09-30：
                常态那一行是噪声）—— 自动挑中时**一个字都不多**，手选过才出现。 */}
            {!first.skuAutoSelected && group.selectedSku && (
              <p data-testid="door-width-manual-note">
                当前门幅是你手动选的（系统规则解见上）；系统只提示、不替你改。
              </p>
            )}
            <p>选了非规则解时，系统只提示、不替你改。</p>
          </div>
        </div>
      </>
    ) : null
  const colorName = colorOptions.find((c) => c.id === group.selectedColorId)?.name
  const groupAmount = group.lines.reduce(
    (s, l) => s + (Number(l.quantity) || 0) * (Number(l.unitPrice) || 0),
    0
  )
  /** 收起时组头仍要能看出「这是哪一行」（#4679 判据 5）：顺手带出尺寸 / 米数 */
  const collapsedSummary = [
    first.width && first.height ? `${first.width} × ${first.height} m` : null,
    first.quantity ? `${first.quantity} 米` : null,
    // **用料来源在收起态也必须看得见**（issue #5840；用户 2026-10-01：「推算的用料米数和实际填入的
    // 不匹配上，都要提示用户」）—— 手填值意味着「数量 ≠ 系统推导值」，而它既是商品金额的分母，
    // 又是加工费米数。展开态里已有三处告知，这里补的正是**收起态**那一半。
    first.metersSource === LINE_METERS_SOURCE_MANUAL ? '用料手填' : null,
  ]
    .filter(Boolean)
    .join(' · ')

  // **空商品组**（issue #4508，用户实测反馈「进入新增商品页面不应该有个默认商品 1」）：
  // 还没选商品 ⇒ **只渲染「选择商品」入口**，不渲染组壳（组头序号/商品名/N 个部位/金额、
  // 部位行、「新增部位」、售卖形态）—— 否则刚进页面就看起来"已经有一个商品了"。
  // ⚠️ 内部仍保留这一行（`lineItems` 初值不变）⇒ 提交 / 算料 / 取价的装配路径一律不动。
  if (!group.product) {
    const firstLine = group.lines[0]
    return (
      <div className="rounded-xl border border-dashed border-neutral-300 bg-white p-4">
        <Label required>选择商品</Label>
        <button
          type="button"
          onClick={onPickProduct}
          className="w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
        >
          <Search className="w-4 h-4" />
          点击搜索并选择商品
        </button>
        {errors[`line_${firstLine.id}_product`] && (
          <p className="mt-1.5 text-sm text-red-600">
            {errors[`line_${firstLine.id}_product`]}
          </p>
        )}
      </div>
    )
  }

  return (
    <div ref={containerRef} className="rounded-xl border border-neutral-200 bg-white">
      {/* 组头 = **商品基础属性**（一组一份）+ **整卡折叠开关**（issue #4679）：
          点组头整行 ⇒ 收起/展开卡片体。「删除」是开关的**兄弟节点**（不在 `<button>` 内）
          ⇒ 点删除只删、不被折叠吞掉；收起后它仍可用（不随卡片体卸载）。 */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-neutral-100 bg-neutral-50/60 rounded-t-xl">
        <CollapsibleHeader
          open={open}
          onToggle={() => setOpen(!open)}
          className="flex-1 min-w-0"
          summary={collapsedSummary}
          trailing={
            <span className="text-sm font-semibold text-neutral-900 shrink-0">
              {formatAmount(groupAmount)}
            </span>
          }
        >
          <span className="inline-flex items-center justify-center w-6 h-6 shrink-0 rounded-full bg-primary-600 text-white text-xs font-semibold">
            {index + 1}
          </span>
          <span className="text-sm font-medium text-neutral-900 truncate">
            {group.product?.name ?? `商品 ${index + 1}`}
          </span>
          {colorName && <span className="text-xs text-primary-600 shrink-0">{colorName}</span>}
          {/* 组头报**帘体**（issue #4521）：部位行已移除 ⇒ 原来的「N 个部位」不再有意义 */}
          <span className="text-xs text-neutral-400 shrink-0">
            {group.saleForm === SALE_FORM_FABRIC ? SALE_FORM_FABRIC : group.curtainBody}
          </span>
          {/* **整卡收起时也看得见「这儿缺 N 项」**（issue #5840）——
              否则商家只知道"提交失败"，不知道是哪张卡 */}
          {groupErrorCount > 0 && (
            <span
              data-testid="group-error-badge"
              className="shrink-0 rounded bg-red-50 px-1.5 text-xs font-medium text-red-600"
            >
              缺 {groupErrorCount} 项
            </span>
          )}
        </CollapsibleHeader>
        {canRemove && (
          <button
            type="button"
            onClick={onRemoveGroup}
            className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-red-600 transition-colors shrink-0"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        )}
      </div>

      {open && (
      <div className="p-4">
        {/* 商品选择 */}
        <div className="mb-4">
          <Label required>选择商品</Label>
          {group.product ? (
            <div className="flex items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-neutral-50/60">
              {group.product.images?.[0] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveImageUrl(group.product.images[0])}
                  alt={group.product.name}
                  className="w-14 h-14 rounded object-cover bg-white border border-neutral-200"
                />
              ) : (
                <div className="w-14 h-14 rounded bg-neutral-100 border border-neutral-200 flex items-center justify-center text-neutral-300">
                  <Package className="w-6 h-6" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-neutral-900 truncate">
                  {group.product.name}
                  {/* 来源标注（issue #5345 判据 3）：这一行是**识别人选**建的 ⇒ 与手填的行长得不同 */}
                  {first.recognizedLine && <RecognizedBadge fieldKey={`line-${first.id}`} />}
                </div>
                <div className="text-xs text-neutral-500 mt-0.5">
                  {group.product.categoryName || '-'} · 货号：{group.product.skuCode || '-'}
                </div>
                {first.recognizedLine && (first.recognizedPriceHint || first.recognizedNote) && (
                  <div data-testid="recognized-line-note" className="text-xs text-amber-700 mt-0.5">
                    {first.recognizedPriceHint
                      ? `图上写「${first.recognizedPriceHint}」—— 行价取自目录 / SKU（识别的价格不是真值）`
                      : first.recognizedNote}
                  </div>
                )}
              </div>
              <button
                onClick={onPickProduct}
                className="text-sm text-primary-600 hover:text-primary-700"
              >
                重新选择
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={onPickProduct}
              className="w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
            >
              <Search className="w-4 h-4" />
              点击搜索并选择商品
            </button>
          )}
          {errProduct && <p className="mt-1.5 text-sm text-red-600">{errProduct}</p>}
        </div>

        {/* 颜色 + 规格 */}
        {group.product && (
          <>
            {group.productLoading ? (
              <div className="text-sm text-neutral-400 py-4">商品规格加载中…</div>
            ) : (
              <>
                {colorOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required small>颜色</Label>
                    {/* ⚠️ chips 尺寸 / 字号与「售卖形态 · 帘体」那排**逐字一致**（h-8 px-2.5 text-xs）——
                        颜色动辄十几支，用 text-sm/h-9 会白占两三行（用户 2026-09-30 实测反馈）。 */}
                    <div className="flex flex-wrap gap-1.5">
                      {colorOptions.map((c) => {
                        const active = group.selectedColorId === c.id
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => onSelectColor(c.id)}
                            className={
                              'h-8 px-2.5 rounded border text-xs transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                            }
                          >
                            {c.name}
                          </button>
                        )
                      })}
                    </div>
                    {errColor && <p className="mt-1.5 text-sm text-red-600">{errColor}</p>}
                  </div>
                )}

                {/* ===== 组级「输入行」：售卖形态 + 帘体 + 净尺寸（2026-09-30 第四批裁定）=====
                    用户逐字「**净尺寸能否和售卖形态放一行？**」—— 能：三者都是**组级输入**
                    （商家唯二要选 / 要填的东西：怎么卖 · 什么帘 · 多大）⇒ 合并成**一行**，
                    省掉改前那张「净尺寸」独占的卡片（≈60px）与三段各占一行的说明。
                    动线因此是三层：**输入行**（这里）→ **①用料与规格**（系统据此给的三个数：
                    门幅 / 用料 / 单价）→ **②加工项**（要做什么工序）。
                    ⚠️ 不放进组头：组头是 `<button>`（`CollapsibleHeader`），里面再嵌 radio 是**非法嵌套**。
                    ⚠️ 净尺寸那句长说明搬进 `title`（悬浮可见）：一行里塞不下三段解释，
                    而标签本身已经写了单位（米）。 */}
                <div
                  data-testid="group-input-row"
                  className="mb-4 flex flex-wrap items-end gap-x-5 gap-y-3"
                >
                  <div className="flex items-center gap-2 pb-2">
                    <span className="text-xs font-medium text-neutral-600">售卖形态</span>
                    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="售卖形态">
                      {([SALE_FORM_FINISHED, SALE_FORM_FABRIC] as SaleForm[]).map((form) => {
                        const active = group.saleForm === form
                        return (
                          <button
                            key={form}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            onClick={() => onChangeSaleForm(form)}
                            className={
                              'h-8 px-2.5 rounded border text-xs transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                            }
                          >
                            {form}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {group.saleForm !== SALE_FORM_FABRIC && (
                    <div className="flex items-center gap-2 pb-2">
                      {/* 帘体（issue #4521；#4874 收窄为两档）——**商品组级**：它决定这条明细行的
                          **部位**（`curtainType`）与**落库几行**，也决定「定型」的默认档（真值源 §10）。
                          ⚠️ **用料算法与帘体无关**（2026-09-21 裁定：纱帘与布帘**完全一致**）。 */}
                      <span className="text-xs font-medium text-neutral-600">帘体</span>
                      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="帘体">
                        {CURTAIN_BODY_OPTIONS.map((body) => {
                          const active = group.curtainBody === body
                          return (
                            <button
                              key={body}
                              type="button"
                              role="radio"
                              aria-checked={active}
                              onClick={() => onChangeCurtainBody(body)}
                              className={
                                'h-8 px-2.5 rounded border text-xs transition-colors ' +
                                (active
                                  ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                  : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                              }
                            >
                              {body}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  {/* **净尺寸**（2026-09-28 提到组级 × 2026-09-30 并进同一行）：商家**最先**要填的两格。
                      门幅规则要**等尺寸填齐**才能自动选最优门幅（#4877 裁定 C / #4899）⇒ 顺序一字未动
                      （净尺寸 → 门幅 / 用料），只是不再独占一块。 */}
                  {group.saleForm !== SALE_FORM_FABRIC && (
                    <div data-testid="size-row" className="flex items-end gap-3">
                      <span
                        className="pb-2 text-xs font-medium text-neutral-600"
                        title="按窗户净尺寸填，单位米（成品宽 = 窗宽、成品高 = 窗高）—— 一套帘共用一份尺寸"
                      >
                        净尺寸
                      </span>
                      <div>
                        <Label required>窗宽 (米)</Label>
                        <div className="flex items-center gap-1">
                          {/* 宽度由**外层**约束（`w-24`）—— 输入框自己的 className 仍是 `w-full …`
                              与旧实现逐字一致（`orders-new-number-parity` 的形态判据 + UI 回退检测都钉着它）。 */}
                          <div className="w-24">
                            <NumberInput
                              value={first.width}
                              onChange={(next) => onChangeWidth(positiveOrNull(next))}
                              decimals={3}
                              placeholder="如 6.6"
                              aria-label="窗宽 (米)"
                              className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                            />
                          </div>
                          {/* 识别来的尺寸要**标出来**（issue #5349 判据 4：识别输入 ≠ 系统推导） */}
                          {(first.recognizedSizeKeys ?? []).includes(ORDER_DERIVATION_INPUT_KEYS.width) && (
                            <RecognizedBadge fieldKey={ORDER_DERIVATION_INPUT_KEYS.width} />
                          )}
                        </div>
                        {errWidth && <p className="mt-1 text-sm text-red-600">{errWidth}</p>}
                      </div>
                      <div>
                        <Label required>窗高 (米)</Label>
                        <div className="flex items-center gap-1">
                          <div className="w-24">
                            <NumberInput
                              value={first.height}
                              onChange={(next) => onChangeHeight(positiveOrNull(next))}
                              decimals={3}
                              placeholder="如 2.6"
                              aria-label="窗高 (米)"
                              className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                            />
                          </div>
                          {(first.recognizedSizeKeys ?? []).includes(ORDER_DERIVATION_INPUT_KEYS.height) && (
                            <RecognizedBadge fieldKey={ORDER_DERIVATION_INPUT_KEYS.height} />
                          )}
                        </div>
                        {errHeight && <p className="mt-1 text-sm text-red-600">{errHeight}</p>}
                      </div>
                      {sizeAutoBadges}
                    </div>
                  )}
                  <span className="pb-2 text-xs text-neutral-400">
                    {group.saleForm === SALE_FORM_FABRIC
                      ? '布料：按米卖，没有加工（不出现宽高 / 工艺规格 / 加工项，也不生成加工单）'
                      : '成品帘：做成帘，需要宽高 / 工艺规格与加工项'}
                  </span>
                </div>

                {/* ===== 门幅 / 规格 =====
                    🔴 **2026-09-30 第四批：整块搬进 ①用料与规格**（与用料米数 / 单价同一行）——
                    节点 = 上面的 `specPicker` / `specExtras`（**只此一份** JSX），
                    成品帘经 `renderPosition` 的 `slots` 传入、布料经 `FabricRow` 的 `specPicker` 传入。 */}
              </>
            )}
          </>
        )}

        {group.saleForm === SALE_FORM_FABRIC ? (
          /* 布料单（issue #4493）：只有 规格 / 米数 / 单价 —— 没有宽高、工艺规格、部位、加工项。
             ⚠️ 2026-09-30 第四批：**门幅 / 规格**也并进这一行（布料的「按什么规格买」与数量 / 单价同屏）。
             若该颜色还没选出可用规格（`specPicker` 为 null）⇒ 退回原来的两格。 */
          <FabricRow
            line={group.lines[0]}
            errors={errors}
            specPicker={specPicker}
            onChangeQty={(q) => onChangeQty(group.lines[0].id, q)}
            onChangePrice={(v) => onChangePrice(group.lines[0].id, v)}
            onChangeRollCount={(n) => onChangeRollCount(group.lines[0].id, n)}
            onChangeRollLength={(n) => onChangeRollLength(group.lines[0].id, n)}
          />
        ) : (
          /* 一套帘（issue #4521）：一个商品组 = 一套帘 ⇒ 只渲染**一份** ①~④。
             「新增部位」已移除（用户裁定「移除部位功能，其实完全不需要」）——
             需要纱帘时改**帘体**，不是再加一行。
             ⚠️ 2026-09-30 第四批：门幅 / 规格节点（`specPicker`）经 `slots` 交给行内
             —— 它在 ①用料与规格 里与用料米数 / 单价同一行（节点只有一份 JSX）。 */
          <div className="space-y-3">
            {renderPosition(group.lines[0], { spec: specPicker, specExtras })}
          </div>
        )}
      </div>
      )}
    </div>
  )
}
