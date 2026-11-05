'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FONT_PX_11 } from '@/lib/design-tokens'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, MapPin, Package, Phone, Plus, Receipt, User, UserPlus, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { loadErrorMessage, toastRequestError } from '@/lib/api-error'
import RequestApprovalModal from '@/components/approvals/RequestApprovalModal'
import { creditDraftFromRejection, type ApprovalDraft } from '@/lib/approval-request'
import { urgencyRequestFields } from '@/lib/order-urgency'
import { ORDER_DERIVATION_INPUT_KEYS, buildOrderPrefill, referenceFields, sizeTargetLineIndex } from '@/lib/image-recognize'
import ImageRecognizeButton, { RecognizedBadge } from '@/components/image-recognize/ImageRecognizeButton'
import OrderLinePicker, { type PickerEntryState } from '@/components/image-recognize/OrderLinePicker'
import {
  NO_MATCH_CHOICE,
  NO_MATCH_LABEL,
  buildableChoices,
  parseDetailEntries,
  pickerOptionsFor,
  recognizedLinePatchOf,
  type DetailEntry,
} from '@/lib/order-line-match'
import { PAGE_FILL_SOURCE_RECOGNIZED, fieldsOfSource, subscribePageFill } from '@/lib/agent-page-fill'
import {
  autoFeaturesApi,
  craftCalcApi,
  customerApi,
  doorWidthPlanApi,
  feePreviewApi,
  orderApi,
  processingItemApi,
  productApi,
  productionApi,
  type AutoFeaturesParams,
  type AutoFeaturesResult,
  type CraftCalcParams,
  type CraftCalcResult,
  type DoorWidthPlanParams,
  type DoorWidthPlanResult,
  type FeePreviewResult,
  type RecognizedField,
} from '@/lib/api'
import { cn, resolveImageUrl } from '@/lib/utils'
import { useOrderAmounts } from '@/hooks/useOrderAmounts'
import { Button, Card, Input, Modal, PageHeader, SELECT_CONTROL } from '@/components/ui'
import { INSTALL_COMMUNITY_MAX_LENGTH } from '@/lib/install-info'
import {
  METERS_SOURCE_FORMULA,
  METERS_SOURCE_MANUAL as LINE_METERS_SOURCE_MANUAL,
  craftCalcErrorText,
  craftCalcParamsOf,
  craftCalcSignature,
} from '@/lib/craft-calc-request'
import {
  COMPONENT_ROLE_EDGE,
  CURTAIN_BODY_CLOTH,
  CURTAIN_BODY_SHEER,
  DEFAULT_CUTTING_MODE,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  buildEdgeLineCraftSpec,
  craftItemKeyOf,
  curtainTypeOfBody,
  resolveSpecialOptionName,
  type CurtainBody,
} from '@/lib/order-craft-fields'
import { LOGISTICS_TYPES, describeLogisticsProfile, logisticsCompaniesFor } from '@/lib/logistics'
import { buildFeeDetailDisplay } from '@/lib/order-fee-display'
import {
  type CraftCalcConfig,
  type Customer,
  type OrderItemFormData,
  type ProcessingItem,
  type Product,
} from '@/types'
import {
  SALE_FORM_FABRIC,
  type AutoFeatureDecision,
  type OrderLineItem,
  type OrderProductSku,
  type ProductDetail,
  type ProductGroup,
  type SaleForm,
} from '@/lib/order-create/types'
import {
  OPEN_COUNT_LABEL,
  PRICING_ENTRY,
  feePreviewErrorText,
  formatAmount,
  uniqueColors,
  unpricedCombinationLabel,
} from '@/lib/order-create/display'
import {
  CRAFT_CALC_DEBOUNCE_MS,
  DEFAULT_CRAFT_ITEM_NAME,
  FEE_PREVIEW_DEBOUNCE_MS,
  SHAPED_ITEM_NAME,
  autoFeatureParamsOf,
  autoFeatureParamsSignature,
  autoFeaturesBlockReason,
  buildLineProcessingInfo,
  calcInputOf,
  createEmptyLineItem,
  defaultRollLengthOf,
  deriveProcessingQty,
  doorWidthParamsOf,
  doorWidthParamsSignature,
  edgeMetersOf,
  edgeUnitPriceOf,
  heightFromDoorWidth,
  mergePlanOverrides,
  pickAutoSkuForColor,
  recommendedItemNamesOf,
  requantifyProcessing,
  rollFieldsOf,
  withRecommendedItemDefaults,
} from '@/lib/order-create/calc'
import { ProductGroupBlock } from '@/components/orders/order-create/ProductGroupBlock'
import { LineItemBlock } from '@/components/orders/order-create/LineItemBlock'
import { CostRow, Row, SectionTitle } from '@/components/orders/order-create/primitives'

export default function NewOrderPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)
  // 超授信被拦时就地开一张授信审批（issue #7374 段 4）：ref = 客户手机号，金额 = 本次超出额
  const [approvalDraft, setApprovalDraft] = useState<ApprovalDraft | null>(null)

  // ===== 行项数组 =====
  const [lineItems, setLineItems] = useState<OrderLineItem[]>(() => [createEmptyLineItem()])

  // ===== 商品搜索弹窗 =====
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [activeLineId, setActiveLineId] = useState<string | null>(null)
  const [productKeyword, setProductKeyword] = useState('')
  const [productResults, setProductResults] = useState<Product[]>([])
  const [productSearchLoading, setProductSearchLoading] = useState(false)

  // ===== 收货信息 =====
  /**
   * **费用明细展开态**（2026-09-29 第三次裁定）：明细收进**底部吸底条**，常态只占一行
   * （订单金额 + 未定价提示 + 提交/取消），点「费用明细」才展开逐行。
   */
  const [feeDetailOpen, setFeeDetailOpen] = useState(false)
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  /**
   * **安装小区**（issue #7856；用户 2026-10-26 逐字「还有客户要求我们备注窗帘未来安装给哪个小区」）
   * —— 订单级、整单一个值：这批帘子**最终装进的那一户人家所在的小区**（可带楼栋/单元/门牌）。
   *
   * 🔴 **不是收货地址**（货发给下单的窗帘店）：两个地址是**两个事实**，不合并、不互相回填。
   * 选填；只随货上纸，不参与算料 / 计价 / 派工 / 库存。落点 = 建单请求**顶层** `installCommunity`
   * （服务端单点扇出到每行 JSONB，前端**不逐行写**同一个字符串）。
   */
  const [installCommunity, setInstallCommunity] = useState('')
  const [remark, setRemark] = useState('')
  // 图片识别预填过的字段（issue #5321 包 1）：只驱动 `[图片识别]` 徽标，提醒商家复核
  const [recognizedFields, setRecognizedFields] = useState<string[]>([])

  // ===== 识别到的明细 ⇒ **选品**面板（issue #5345）=====
  // 🔴 识别**不建行**：先给候选（名称/规格相似度 + 可读理由），商家选了才建行；「都不是」⇒ 不建行。
  const [linePicker, setLinePicker] = useState<PickerEntryState[]>([])
  /** 候选查询到的目录 —— 放行口 `buildableChoices` 用它复核「该商品在这个条目的候选里出现过」 */
  const [lineCatalog, setLineCatalog] = useState<Product[]>([])

  /**
   * 按条目查目录（**复用既有商品搜索端点**，不另写一套匹配服务）⇒ 排序与理由由纯函数
   * `pickerOptionsFor` 给（唯一实现，判据 2）。
   * 查询失败 ⇒ **fail-closed**：该条目只剩「都不是」（宁可少给候选，也不猜商品）。
   */
  const loadLinePicker = useCallback(async (entries: DetailEntry[]) => {
    setLinePicker(entries.map((entry) => ({ entry, options: [], loading: true, resolved: null, failed: false })))
    const loaded = await Promise.all(
      entries.map(async (entry) => {
        try {
          const res = await productApi.getProducts({ keyword: entry.name, page: 1, size: 10 })
          const items = (res.data?.data?.items || []) as Product[]
          return { state: { entry, options: pickerOptionsFor(entry, items), loading: false, resolved: null, failed: false }, catalog: items }
        } catch {
          // 查询**失败**（不是「目录里没有」）—— 分开记账，面板上如实分开说（issue #6529）
          return {
            state: { entry, options: pickerOptionsFor(entry, []), loading: false, resolved: null, failed: true },
            catalog: [] as Product[],
          }
        }
      })
    )
    // 面板可能已被商家关掉（`prev` 为空）⇒ **不复活它**（否则"关掉又跳出来"）
    setLinePicker((prev) => (prev.length === 0 ? prev : loaded.map((l) => l.state)))
    setLineCatalog(loaded.flatMap((l) => l.catalog))
  }, [])

  // 图片识别预填（issue #5321 包 1）——**只在字段为空时才填**（不覆盖用户已输入的内容：
  // 收货信息填错 = 货发错人）；明细/数量/规格不进 lineItems，拼一行进备注。
  // 徽标只增不减：同一字段被识别填过就一直提醒复核。
  const handleRecognized = useCallback(
    (fields: RecognizedField[]) => {
      const prefill = buildOrderPrefill(fields, {
        customerName,
        customerPhone,
        customerAddress,
        remark,
      })
      if (prefill.customerName !== undefined) setCustomerName(prefill.customerName)
      if (prefill.customerPhone !== undefined) setCustomerPhone(prefill.customerPhone)
      if (prefill.customerAddress !== undefined) setCustomerAddress(prefill.customerAddress)
      if (prefill.remark !== undefined) setRemark(prefill.remark)

      // 尺寸（帘宽 / 帘高，issue #5349）：**推导链的原始输入** —— 写进行状态后，既有推导链
      // **自然生效**（试算 / 加工类型 / 分幅 / 拼接 / 接高 / 接宽 / 超高 / 超宽全是输入驱动的），
      // 识别侧**一行推导都不写**（判据 2：同一真值两处推导 = 页面显示 ≠ 落库）。
      // 落点由 `sizeTargetLineIndex` 定：**第一行宽高都还空着**的行；没有 ⇒ 一行都不动
      // （不覆盖商家已经敲进去的尺寸 —— 尺寸错 ⇒ 米数错 ⇒ 钱错）。
      const sizeKeys: string[] = Object.values(ORDER_DERIVATION_INPUT_KEYS).filter((key) =>
        prefill.recognizedFields.includes(key)
      )
      // **客户写明的工艺要求**（issue #5794）：打开方式 / 款式 / 加工项 —— 与尺寸**同一行**
      // （图上写的是一套帘的要求）。⚠️ 与收货信息「只填空字段」的口径**不同**：这里是**客户显式
      // 要求**，必须盖过系统默认 —— 用户口径「根据图中客户要求来决定工艺规格和加工项选择了，
      // **不能选错**」；覆盖**留痕可见**（`recognizedCraftText` 在 ①用料与规格 里逐字展示）。
      const craftSpecRecognized = prefill.openCount !== undefined || prefill.style !== undefined
      const itemNames = prefill.processingItemNames ?? []
      const hasItemRequest = itemNames.length > 0

      if (sizeKeys.length > 0 || craftSpecRecognized || hasItemRequest) {
        // 先取成局部常量：`setLineItems` 的回调是**延迟执行**的，TS 对属性访问的收窄跨不过它
        const curtainWidth = prefill.curtainWidth
        const curtainHeight = prefill.curtainHeight
        const openCount = prefill.openCount
        const style = prefill.style
        void craftSpecRecognized
        setLineItems((prev) => {
          const emptySizeIndex = sizeTargetLineIndex(prev)
          // 尺寸仍**只落在空尺寸行**（不覆盖商家敲进去的数 —— 尺寸错 ⇒ 米数错 ⇒ 钱错）；
          // 工艺要求是**整套帘的口径**，不能因为"尺寸已经填过"就不生效 ⇒ 退到第 0 行。
          const target = emptySizeIndex >= 0 ? emptySizeIndex : prev.length > 0 ? 0 : -1
          if (target < 0) return prev
          const line = prev[target]
          const next = [...prev]
          const patched: OrderLineItem = { ...line }
          if (sizeKeys.length > 0 && emptySizeIndex >= 0) {
            patched.recognizedSizeKeys = sizeKeys
            if (curtainWidth !== undefined) patched.width = curtainWidth
            if (curtainHeight !== undefined) patched.height = curtainHeight
          }
          if (craftSpecRecognized || hasItemRequest) {
            // 识别到的加工项里哪些**本租户目录里没有** ⇒ 只提示、不勾选（不替客户造一个不存在的项）。
            // ⚠️ 目录取自**这一行**的 `processingItems`（页面唯一那份目录）—— 用页面级 state 会在
            // 它的初始化之前被引用（TDZ），也会让这个回调多一个会漂的依赖。
            // ⚠️ 比较一律走**规范 key**（`craftItemKeyOf`）：目录里可能是「韩折」而识别值已归一到
            // 「韩褶」，直接比字符串会**静默不勾选**（2026-09-29 云测试环境实测的同一形态）。
            const catalogKeys = new Set(patched.processingItems.map((pi) => craftItemKeyOf(pi.name)))
            const requestedKeys = new Set(itemNames.map((name) => craftItemKeyOf(name)))
            const unmatchedItems = itemNames.filter(
              (name) => !catalogKeys.has(craftItemKeyOf(name))
            )
            patched.recognizedCraftText = [
              openCount !== undefined
                ? `打开方式 ${OPEN_COUNT_LABEL[openCount] ?? `${openCount} 开`}`
                : null,
              style !== undefined ? `款式 ${style}` : null,
              hasItemRequest
                ? `加工项 ${itemNames.join('、')}` +
                  (unmatchedItems.length > 0
                    ? `（${unmatchedItems.join('、')} 目录里没有 ⇒ 未勾选，请手工核对）`
                    : '')
                : null,
            ]
              .filter(Boolean)
              .join(' · ')
            patched.craft = {
              ...patched.craft,
              ...(openCount !== undefined ? { openCount } : {}),
              ...(style !== undefined ? { style } : {}),
            }
            // 留痕：识别是**外来的明确要求** ⇒ 之后补推荐默认时不得再动它
            if (openCount !== undefined) patched.openCountTouched = true
            if (hasItemRequest) {
              const selected = { ...patched.selectedProcessing }
              // ① 客户写明的项 ⇒ 勾上（按**规范 key** 比）
              for (const item of patched.processingItems) {
                if (requestedKeys.has(craftItemKeyOf(item.name))) {
                  selected[item.id] = {
                    selected: true,
                    qty: selected[item.id]?.qty ?? deriveProcessingQty(patched.quantity),
                  }
                }
              }
              // ② 系统**推荐默认**里、客户没提的项 ⇒ 取消 —— 否则「默认韩褶 + 定型」会把客户的单子
              //    改成系统以为的样子（用户说的「不能选错」正是这个形态）
              const recommendedKeys = new Set(
                recommendedItemNamesOf(patched).map((name) => craftItemKeyOf(name))
              )
              for (const item of patched.processingItems) {
                if (recommendedKeys.has(craftItemKeyOf(item.name)) && !requestedKeys.has(craftItemKeyOf(item.name))) {
                  selected[item.id] = { selected: false, qty: selected[item.id]?.qty ?? 1 }
                }
              }
              patched.selectedProcessing = selected
              patched.craftItemTouched = true
              patched.shapedItemTouched = true
            }
          }
          next[target] = patched
          return next
        })
      }

      // ⚠️ 尺寸键**不进**页面级 `recognizedFields`（那是一屏多行共用清单 ⇒ 会给每一行都打上徽标，
      //    而识别只落在**一行**）：尺寸徽标走行状态 `recognizedSizeKeys`。
      const pageKeys = prefill.recognizedFields.filter((key) => !sizeKeys.includes(key))
      setRecognizedFields((prev) => Array.from(new Set([...prev, ...pageKeys])))

      // 明细 → 匹配候选 → **人选** → 建订单行（issue #5345）：识别到的明细**不自动建行**，
      // 先按名称/规格给候选，等商家在面板上选（判据 1/7）；匹配不到 ⇒ 只剩「都不是」。
      const entries = parseDetailEntries(fields)
      if (entries.length > 0) void loadLinePicker(entries)
    },
    [customerName, customerPhone, customerAddress, remark, loadLinePicker]
  )

  // 深通道（issue #5368 包 2）：黄金策识别结果经 **SSE → store → 浏览器内存事件**推到本页
  // （浮动面板在建单页上就在表单上方，不需要跳转；走内存通道 ⇒ 收货信息不进 URL / 日志 / 历史）。
  // 🔴 订单侧**只收识别来源**（`[图片识别]`）：黄金策的解读在订单侧**只解释、一格都不填**
  // （客户信息错 ⇒ 货发错人）—— 内核已保证这类格子 `value` 为空，这里因此自然排除。
  // 填表口径与快通道**完全同一条**（复用 `handleRecognized`：只填空字段、不覆盖已输入内容）。
  useEffect(
    () =>
      subscribePageFill('order', (plan) => {
        // 有值的识别格进表单；「参考格」（图上读到、没采纳，issue #6529）**只随行带去查目录**
        // —— 它的 `value` 为空，任何映射函数都写不进表单。
        handleRecognized([
          ...fieldsOfSource(plan, PAGE_FILL_SOURCE_RECOGNIZED),
          ...referenceFields(plan.fields),
        ])
      }),
    [handleRecognized]
  )

  // ===== 客户选择弹窗（#3102：选已有客户快捷回填收货信息，保留手动兜底）=====
  const [customerModalOpen, setCustomerModalOpen] = useState(false)
  const [customerKeyword, setCustomerKeyword] = useState('')
  const [customerResults, setCustomerResults] = useState<Customer[]>([])
  const [customerSearchLoading, setCustomerSearchLoading] = useState(false)
  /**
   * **常用物流/快递**与**常用物流公司**（issue #4874，用户 2026-09-21：「新增订单时**收货信息**中
   * 缺少用户的常用物流/快递以及常用公司，选择客户后要默认带出」）—— 两个**可编辑**控件，
   * 选客户时按客户档案带出（`Customer.defaultLogisticsType` / `defaultLogisticsCompany`）。
   *
   * 缺省 `''` = **未指定**：**不编造**默认值（客户没录过常用物流时渲染成「快递」看起来像已配置），
   * 提交时缺值不写（`logisticsType` / `logisticsCompany` 是顶层可选字段）。
   */
  const [logisticsType, setLogisticsType] = useState('')
  const [logisticsCompany, setLogisticsCompany] = useState('')
  /**
   * **折叠态下要能看出「现在带出的是哪一家」**（issue #6589，用户 2026-10-09 逐字：「订单这里
   * 折叠情况下应该要展示隐藏的具体信息」）。
   *
   * 为什么需要它：改前 `logistics-section` 的 `<summary>` 是一句**静态**提示，与上面这两个值
   * **零绑定** ⇒ 收起时商家只看得到「常用物流（必填 · 选客户时自动带出）」，看不出**已经带出 /
   * 改成了什么**（本页同类形态的先例 = issue #6399 的收起态读数 `craft-plan-current`）。
   *
   * 口径**不新造**：值 = `lib/logistics.ts::describeLogisticsProfile`（客户档案 / 发货页同一份）；
   * 两者都缺 ⇒ 空串 ⇒ 退回通用提示 —— **不编造**默认值（#4419：「未指定」是真值）。
   */
  const logisticsSummary = describeLogisticsProfile(logisticsType, logisticsCompany)

  /**
   * **加急**与**要求到货日**（issue #5177，做在**订单**上 —— 不是售后页）。
   *
   * 🔴 缺省不变：`isUrgent` 缺省 `false`（= **不勾**）、`requiredDeliveryDate` 缺省 `''`（= **未指定**）
   * ⇒ 提交时**这两个键都不出现在请求体里**（后端库列 `NOT NULL DEFAULT FALSE` / `NULL`）。
   * **不得默认勾上加急** —— 勾了就是替商家编造一个「插队」事实。
   * 与售后工单的 `priority` **零联动**（不 import、不读写任何售后字段）。
   */
  const [isUrgent, setIsUrgent] = useState(false)
  /** 外发加工标记（V194，issue #7746 后续）：缺省不勾；勾了 ⇒ 该单不进成批候选、派单必须选承接方 */
  const [isOutsourced, setIsOutsourced] = useState(false)
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('')

  // 表单错误
  const [errors, setErrors] = useState<Record<string, string>>({})
  /**
   * **「哪儿缺了」的定向入口**（issue #5840）。
   *
   * 为什么需要它：本页有 5 类折叠区（商品组整卡 / 组内两步手风琴 / 推导细节 / 物流 / 费用明细），
   * 而提交失败**只弹一句 toast** ⇒ 商家在折叠态下根本找不到是哪儿缺（用户 2026-10-01 点名的那半）。
   * 它携带出错键 + 一个**每次定位都自增**的 `tick`（只看 key 的话，同一处连按两次第二次不触发）。
   */
  const [errorFocus, setErrorFocus] = useState<{ key: string; tick: number }>({ key: '', tick: 0 })
  /** 「常用物流」折叠区：两个物流字段出错的项在里边 ⇒ 提交失败时**自动展开** */
  const logisticsRef = useRef<HTMLDetailsElement>(null)

  /**
   * 报错项的**展示顺序**（issue #5840）—— 按商家在页面上的动线排，不按验证时的插键顺序：
   * 商品明细 → 收货信息 → 物流 → 加工费。汇总条与「先跳到哪一条」共用这一份口径。
   */
  const errorKeyRank = (key: string): number => {
    const order: Array<[string, boolean]> = [
      ['line_', true],
      ['customer', true],
      ['logistics', true],
      ['processingFee', false],
      ['feePreview', false],
    ]
    const hit = order.findIndex(([prefix, isPrefix]) =>
      isPrefix ? key.startsWith(prefix) : key === prefix
    )
    return hit === -1 ? order.length : hit
  }
  const sortErrorKeys = (keys: string[]): string[] =>
    keys
      .map((key, idx) => ({ key, idx }))
      .sort((a, b) => errorKeyRank(a.key) - errorKeyRank(b.key) || a.idx - b.idx)
      .map(({ key }) => key)

  /**
   * 提交失败后要摆到台面上的清单（issue #5840）：**吸底条常显**，逐条可点 ⇒ 点了就到现场。
   */
  const errorEntries = useMemo(
    () =>
      sortErrorKeys(Object.keys(errors)).map((key) => ({ key, message: errors[key] })),
    // `sortErrorKeys` / `errorKeyRank` 是纯函数（不进依赖）
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [errors]
  )

  /**
   * **把某个报错项带到现场**（issue #5840）：展开它所在的折叠区 + 滚动 + 聚焦。
   * 行内错误（`line_<id>_*`）交给 `ProductGroupBlock` 自己按同一个 `tick` 展开
   * —— 只有它持有整卡 `open` 与该步 `openStep`。
   */
  const focusError = useCallback((key: string) => {
    setErrorFocus((prev) => ({ key, tick: prev.tick + 1 }))
    if (key === 'logisticsType' || key === 'logisticsCompany') {
      if (logisticsRef.current) logisticsRef.current.open = true
      logisticsRef.current?.scrollIntoView?.({ block: 'center' })
      return
    }
    if (key === 'processingFee' || key === 'feePreview') {
      setFeeDetailOpen(true)
    }
  }, [])

  // ===== 加工项目录（店铺级，独立于商品）=====
  // issue #4371：加工项与商品解耦 —— 目录只加载一次，商品选择不再过滤/触发加工项请求
  const [processingCatalog, setProcessingCatalog] = useState<ProcessingItem[]>([])
  const [processingCatalogLoading, setProcessingCatalogLoading] = useState(false)
  /**
   * 加工项目录读失败（issue #6691）：改前只 `setProcessingCatalog([])` ⇒ 行上的加工项列表空着、
   * 与「这家店根本没配加工项」**看不出区别**（商家会去加工项管理白建一遍）。
   */
  const [processingCatalogFailed, setProcessingCatalogFailed] = useState(false)

  /**
   * 处理一条明细（选品面板的回调）—— **建行的唯一入口**（issue #5345 判据 1/7）。
   *
   * - 「都不是」/ 选了一个**没给过该条目**的商品 ⇒ 标记跳过，**不建行**（明细留在备注）；
   * - 选到候选 ⇒ `buildableChoices` 复核（页面**不得**替用户挑一个没给过他的商品）⇒
   *   取商品详情（含 SKU）⇒ 追加一行；来源标 `[图片识别]`，单价只来自所选 SKU（判据 6）。
   * 🔴 **不落库**：这里只改页面行状态 —— 不调用任何建单 / 保存端点（提交永远是商家点按钮，判据 4）。
   */
  const handlePickEntry = useCallback(
    async (entry: DetailEntry, productId: string) => {
      const resolve = (resolved: { productId: string; label: string }) =>
        setLinePicker((prev) =>
          prev.map((it) => (it.entry === entry ? { ...it, resolved } : it))
        )
      const built = buildableChoices([{ entry, productId }], lineCatalog)
      if (built.length === 0) {
        // 没给过这个商品的候选（或点了「都不是」）⇒ 不建行 —— 与「都不是」同一条出口，不猜
        resolve({ productId: NO_MATCH_CHOICE, label: NO_MATCH_LABEL })
        return
      }
      const picked = built[0].product
      // 详情才带 SKU（列表项可能没有）⇒ 取不到就退回列表项（与 `handlePickProduct` 同一处置）
      let detail: ProductDetail
      try {
        const res = await productApi.getProduct(picked.id)
        detail = (res.data?.data as unknown as ProductDetail) || (picked as unknown as ProductDetail)
      } catch {
        detail = picked as unknown as ProductDetail
      }
      // 行补丁：数量 / 单价（只来自 SKU）/ 唯一规格时的颜色与门幅；门幅**不在这里**（判据 5）
      const patch = recognizedLinePatchOf(entry, detail.skus ?? [])
      setLineItems((prev) => [
        ...prev,
        {
          ...createEmptyLineItem(),
          product: detail,
          processingItems: processingCatalog,
          skuAutoSelected: patch.selectedSku !== null,
          // 整卷售卖（issue #5846）：识别建出来的行同样默认带出商品卷长
          rollLengthM: defaultRollLengthOf(detail),
          ...patch,
        },
      ])
      resolve({ productId: picked.id, label: picked.name })
      // 全部处理完 ⇒ 关掉面板；还有待选的 ⇒ 留着让商家继续选
      setLinePicker((prev) => (prev.every((it) => it.resolved !== null) ? [] : prev))
      toast.success(`已建订单行：${picked.name} —— 请在行上核对数量 / 规格 / 单价`)
    },
    [lineCatalog, processingCatalog]
  )

  /** 「都不建行（跳过剩余）」：一次性放弃剩下的明细 —— **不建行**，它们只留在备注里（判据 1） */
  const handleSkipAll = useCallback(() => {
    setLinePicker([])
    toast.success('已跳过识别到的明细：没有建任何订单行，明细只留在备注里')
  }, [])

  /**
   * **算料配置**（issue #4874）—— 与「工艺配置 → 算料配置」**同源**：公式名与档位一律从
   * `GET /api/admin/production/craft-calc-config` 读，**前端不写死第二份**。
   *
   * ⚠️ 加载失败**不阻断录入**：页面对 `null` 的处理 = 公式走 `defaultCraftCalcFormula(null)`
   * （`pleat`）+ 档位走 `defaultCraftCalcTier(null)`（`standard`），并在界面上**显式提示**
   * 「配置未加载」——静默按缺省走 = 商家以为按自己配的口径算（算错钱且无人知道）。
   */
  const [calcConfig, setCalcConfig] = useState<CraftCalcConfig | null>(null)

  /**
   * 加工项目录读面（店铺级，只加载一次）。读失败 ⇒ 标 `processingCatalogFailed`（issue #6691），
   * 屏上给「目录加载失败 + 重试」；**不**把故障画成「目录是空的」。
   * 抽成 `useCallback` 是为了重试按钮能重跑同一份读面（不复制一遍请求代码）。
   */
  const loadProcessingCatalog = useCallback(async () => {
    setProcessingCatalogLoading(true)
    setProcessingCatalogFailed(false)
    try {
      const res = await processingItemApi.getProcessingItems({ page: 1, size: 100 })
      setProcessingCatalog(res.data?.data?.items || [])
    } catch (e) {
      // 拦截器已 toast（`e` 保留给 console 调试）；只标失败态，不清成「空目录」
      console.error('加载加工项目录失败:', e)
      setProcessingCatalogFailed(true)
    } finally {
      setProcessingCatalogLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProcessingCatalog()
  }, [loadProcessingCatalog])

  // 目录到达后同步到各行项（行项可能在目录加载完成前就已选好商品）
  useEffect(() => {
    if (processingCatalogLoading) return
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.processingItems === processingCatalog) return it
        const next: OrderLineItem = { ...it, processingItems: processingCatalog }
        // 目录到达 ⇒ 补**推荐组合**的默认勾选（定型 #4566 + 韩褶，2026-09-28；商家手改过的不覆盖）
        return { ...next, selectedProcessing: withRecommendedItemDefaults(next) }
      })
    )
  }, [processingCatalog, processingCatalogLoading])

  /**
   * **算料配置**加载（issue #4874）—— 只加载一次，失败**只提示不阻断**（`calcConfig` 保持 `null`
   * ⇒ 页面按缺省口径走 + 显式提示）。旧请求返回时不再写状态（`cancelled`）⇒ 不会用过期配置覆盖。
   */
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await productionApi.getCraftCalcConfig()
        if (cancelled) return
        setCalcConfig(res.data?.data?.config ?? null)
      } catch (e) {
        // 读不到 ⇒ 保持 `null`（issue #6691 口径：**不清成空** —— `calcConfig` 初值就是「没读到」的语义，
        // 而下游 `OrderCraftFields` 把 `null` 渲染成显式「算料配置未加载」提示）。
        // ⚠️ 本 catch **不得**再写 `setCalcConfig(null)`：那会被类级守卫（issue #6663）
        // 读成「清空读数且不表达失败」的病灶形态。
        console.error('加载算料配置失败:', e)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  // ===== 行项更新工具 =====
  const updateLineItem = useCallback(
    (
      lineId: string,
      patch: Partial<OrderLineItem> | ((line: OrderLineItem) => Partial<OrderLineItem>)
    ) => {
      setLineItems((prev) =>
        prev.map((it) =>
          it.id === lineId ? { ...it, ...(typeof patch === 'function' ? patch(it) : patch) } : it
        )
      )
    },
    []
  )

  /**
   * 自动识别特征的**裁决**（issue #4657）—— 生效值 = `推算 ∪ 强制加 − 不采纳`。
   *
   * - `reject` = **不采纳**（推算错会直接算错加工费，商家必须能纠正）；
   * - `add` = **强制加**（系统漏判，如 SKU 没录门幅 ⇒ 按默认 2.8 兜底 ⇒ 本该超宽却没推）；
   * - `adopt` = **恢复系统推算**（同时清掉强制加 —— 两个来源不会同时留下同一个名字）。
   *
   * 裁决随**行状态**走，落库的是**生效值**（`processingDetailsOf`）⇒ 日后推算判据修正
   * **不影响**已下的单（快照，零迁移：`processingInfo` JSON 已能承载）。
   */
  const decideAutoFeature = useCallback(
    (lineId: string, name: string, decision: AutoFeatureDecision) => {
      updateLineItem(lineId, (it) => {
        const without = (list: string[] | undefined) => (list ?? []).filter((n) => n !== name)
        if (decision === 'reject') {
          return {
            rejectedAutoFeatures: [...new Set([...(it.rejectedAutoFeatures ?? []), name])],
            manualAutoFeatures: without(it.manualAutoFeatures),
          }
        }
        if (decision === 'add') {
          return {
            rejectedAutoFeatures: without(it.rejectedAutoFeatures),
            manualAutoFeatures: [...new Set([...(it.manualAutoFeatures ?? []), name])],
          }
        }
        return {
          rejectedAutoFeatures: without(it.rejectedAutoFeatures),
          manualAutoFeatures: without(it.manualAutoFeatures),
        }
      })
    },
    [updateLineItem]
  )

  /**
   * 「推导出的特殊选项」的**裁决**（issue #5211：拼N次 / 接高）—— 与 {@link decideAutoFeature}
   * 同族纪律：这些项会进 `processingInfo.specialOptions`（**插工序 + 计件**）⇒ 推导错 = 多插一道
   * 工序、多算工钱 ⇒ 商家必须能**不采纳** / **恢复采纳**。
   *
   * 按**选项名**留痕（不是布尔位）：日后推导换成别的项时，对新的那一项不作废
   * （同 `rejectedAutoFeatures` 的按名裁决）。
   */
  const decideDerivedOption = useCallback(
    (lineId: string, name: string, decision: 'adopt' | 'reject') => {
      updateLineItem(lineId, (it) => {
        const without = (it.rejectedDerivedOptions ?? []).filter((n) => n !== name)
        return {
          rejectedDerivedOptions:
            decision === 'adopt' ? without : [...new Set([...without, name])],
        }
      })
    },
    [updateLineItem]
  )

  const addLineItem = () => {
    setLineItems((prev) => [...prev, createEmptyLineItem()])
  }

  /**
   * **帘体**（**组级**，issue #4521）：一个商品组 = 一套帘 ⇒ 组内同步。
   *
   * 两条口径：
   * 1. **是否定型默认跟着帘体走**（真值源 §10 布帘是 / 纱帘否）—— 但**只在商家没手改过时**
   *    （`shapedItemTouched` 落在行状态里，同 `openCountTouched` 的纪律：手改过的值只能显式改回）。
   *    ⚠️ issue #4566：它现在写的是「定型」**加工项**的勾选态（`withShapedDefault`），
   *    不再是工艺规格里的字段（字段已随裁定退场）；
   * 2. **用料来源**：两种帘体**同一条**算料链路 ⇒ 一律回到「公式计算」
   *    （`人工指定` 只能由商家手改数量进入，见 `handleLineQtyChange`）。
   *
   * ⚠️ **2026-09-21 用户裁定（口径反转）**：原第 3 条边界「切到纱帘就清掉算料结果/错误
   * （纱帘不算料）」**已退场** —— 纱帘不再是不算料的特例 ⇒ 不得因为切帘体而丢弃/跳过算料结果。
   */
  const handleCurtainBodyChange = (groupId: string, body: CurtainBody) => {
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = {
          ...it,
          curtainBody: body,
          // 纱帘与布帘**同一算法**（2026-09-21 裁定）⇒ 切帘体后一律回到「公式计算」
          metersSource: METERS_SOURCE_FORMULA,
          // 🔴 布/纱派生键**跟随帘种**（issue #8007）：切到纱帘 ⇒ 已勾的族成员换成 `余料带回-纱`
          //    （不重派 = 布帘下勾的键被带进纱帘行，语义与落库都对不上）
          craft: {
            ...it.craft,
            specialOptions: it.craft.specialOptions?.map((name) =>
              resolveSpecialOptionName(name, curtainTypeOfBody(body))
            ),
          },
        }
        // 定型默认随帘体（#4566）：写「定型」加工项的勾选态，商家手改过则不覆盖
        // （⚠️ 与用料算法无关，不动）；韩褶（工艺默认，2026-09-28）同批按同一入口补
        next.selectedProcessing = withRecommendedItemDefaults(next)
        return next
      })
    )
  }

  /**
   * 组内同步（issue #4485）：把 patch 写到同 `groupId` 的**所有**行 ——
   * 商品 / 颜色 / 门幅·售卖方式 / 售卖形态都是**一组一份**的属性（部位共用）。
   */
  const patchGroup = useCallback((groupId: string, patch: Partial<OrderLineItem>) => {
    setLineItems((prev) => prev.map((it) => (it.groupId === groupId ? { ...it, ...patch } : it)))
  }, [])

  /**
   * 颜色（**组级**，issue #4485）：同一块布的颜色 ⇒ 组内所有部位行同步。
   * 顺带按门幅给「高」填默认值（用户 2026-09-19 裁定，可改）。
   */
  const handleSelectColorForGroup = (groupId: string, colorId: string) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    const skusOfColor = (sample?.product?.skus || []).filter((s) => s.colorId === colorId)
    // issue #4877 裁定 C：多门幅时按**门幅规则**选默认（可行集最小门幅 / 定宽买高分幅最少）
    const autoSku = sample ? pickAutoSkuForColor(sample, skusOfColor) : null
    patchGroup(groupId, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      skuAutoSelected: Boolean(autoSku),
      ...(autoSku ? { unitPrice: Number(autoSku.price) } : {}),
    })
  }

  /** 门幅 / 售卖方式（**组级**）：同上；并把「高」默认成门幅（仅定高买宽，可改） */
  const handleSelectSkuForGroup = (
    groupId: string,
    sku: OrderProductSku,
    source: 'auto' | 'manual' = 'manual'
  ) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    const isFixedHeight = (sample?.craft.cuttingMode ?? DEFAULT_CUTTING_MODE) === DEFAULT_CUTTING_MODE
    const defaultHeight = isFixedHeight ? heightFromDoorWidth(sku.doorWidth) : null
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = {
          ...it,
          selectedSku: sku,
          unitPrice: Number(sku.price) || 0,
          skuAutoSelected: source === 'auto',
        }
        // 只在「还没填高」时补默认值 —— 商家填过的值不覆盖（同「手改留痕」纪律）
        if (defaultHeight !== null && it.height === null) next.height = defaultHeight
        return next
      })
    )
  }

  /**
   * 尺寸 / 加工类型变化后：该组**还没选门幅** ⇒ 按**门幅规则**补一个默认（issue #4877 裁定 C）。
   *
   * ⚠️ 只在 `selectedSku` **为空**时补 —— 客服手选过就**不覆盖**（同「手改留痕」纪律）；
   * 规则判不了（缺尺寸 / 门幅未维护 / 多个 SKU 同门幅）⇒ **什么都不做**（不猜）。
   */
  const autoSelectSkuByRuleForGroup = (groupId: string, patch: Partial<OrderLineItem>) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    if (!sample) return
    // **客服手选过 ⇒ 不覆盖**（只提示可换最优，用户裁定）；**规则自己选的 ⇒ 要能重算**（issue #4899）
    if (sample.selectedSku && !sample.skuAutoSelected) return
    const next = { ...sample, ...patch }
    const skusOfColor = (next.product?.skus ?? []).filter((s) => s.colorId === next.selectedColorId)
    const sku = pickAutoSkuForColor(next, skusOfColor)
    // 规则解没变 ⇒ 不动作（避免无谓 setState 与单价抖动）
    if (sku && sku.id !== sample.selectedSku?.id) handleSelectSkuForGroup(groupId, sku, 'auto')
  }

  /**
   * 售卖形态（**组级**，issue #4493）：布料 ⇒ 组内**只保留一行**（布料没有部位），
   * 并清掉工艺规格 / 加工项 / 宽高（布料单无加工）；成品帘 ⇒ 组内所有行标回成品帘。
   */
  const handleSaleFormChange = (groupId: string, form: SaleForm) => {
    setLineItems((prev) => {
      const groupLines = prev.filter((l) => l.groupId === groupId)
      if (groupLines.length === 0) return prev
      if (form !== SALE_FORM_FABRIC) {
        return prev.map((l) => {
          if (l.groupId !== groupId) return l
          const next: OrderLineItem = { ...l, saleForm: form }
          // 布料 ⇒ 成品帘：推荐组合按帘体重新预选（布料组整组无加工 ⇒ 切回来要把默认补回来；
          // 商家撤过的那一位有手改留痕 ⇒ 不会被勾回）- 2026-09-28
          return { ...next, selectedProcessing: withRecommendedItemDefaults(next) }
        })
      }
      const at = prev.findIndex((l) => l.groupId === groupId)
      const kept: OrderLineItem = {
        ...groupLines[0],
        saleForm: form,
        craft: {},
        selectedProcessing: {},
        width: null,
        height: null,
        calc: null,
        calcError: null,
        metersSource: METERS_SOURCE_FORMULA,
        // 布料单没有帘体（issue #4521）：切回成品帘时从「布帘」重新开始。
        // ⚠️ issue #4874：`布帘+纱帘` 档已删除 ⇒ 不再需要清「纱帘米数 / 纱帘单价」
        curtainBody: CURTAIN_BODY_CLOTH,
        processingFeeOverride: null,
      }
      const next = prev.filter((l) => l.groupId !== groupId)
      next.splice(at, 0, kept)
      return next
    })
  }

  /**
   * **净尺寸**（2026-09-28 下单页布局）：窗宽 / 窗高是商家**最先**要填的两格 ⇒ 已从行内「区块 1」
   * 提到**组级**（商品 / 颜色之后、门幅之前），与「门幅规则要等尺寸填齐才能自动选」同序。
   *
   * 尺寸仍是**行状态**（一套帘共用一份）⇒ 回调按行 id 落；两条联动与改前**逐字同源**：
   * ① 宽 → 打开方式（真值源 §10 的启发式；手改过 `openCountTouched` ⇒ 不覆盖）；
   * ② 尺寸齐了 ⇒ 该组还没选门幅时按**门幅规则**补默认（issue #4877 裁定 C）。
   */
  const handleLineWidthChange = (line: OrderLineItem, w: number | null) => {
    // ⚠️ 2026-09-29（用户裁定）：改窗宽**不再**联动打开方式 —— 旧启发式 `deriveOpenCount` 已删除，
    // 开数只由商家显式改（`openCountTouched` 留痕不变）。尺寸齐了仍按门幅规则补默认门幅。
    updateLineItem(line.id, { width: w })
    autoSelectSkuByRuleForGroup(line.groupId, { width: w })
  }

  /** 净窗高 —— 同 {@link handleLineWidthChange}（高变 ⇒ 门幅规则可能改判 ⇒ 补默认） */
  const handleLineHeightChange = (line: OrderLineItem, h: number | null) => {
    updateLineItem(line.id, { height: h })
    autoSelectSkuByRuleForGroup(line.groupId, { height: h })
  }

  /** 删除整个商品组（含其下所有部位行）；至少保留一组 */
  const removeGroup = (groupId: string) => {
    setLineItems((prev) => {
      const next = prev.filter((l) => l.groupId !== groupId)
      return next.length === 0 ? prev : next
    })
    setErrors({})
  }

  // ===== 商品搜索 =====
  const searchProducts = useCallback(async () => {
    setProductSearchLoading(true)
    try {
      const res = await productApi.getProducts({
        keyword: productKeyword.trim() || undefined,
        page: 1,
        size: 30,
      })
      setProductResults(res.data?.data?.items || [])
    } catch (e) {
      toastRequestError(e, '搜索商品失败')
    } finally {
      setProductSearchLoading(false)
    }
  }, [productKeyword])

  useEffect(() => {
    if (productModalOpen) {
      searchProducts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productModalOpen])

  const openProductModalFor = (lineId: string) => {
    setActiveLineId(lineId)
    setProductModalOpen(true)
  }

  // ===== 客户搜索（#3102）=====
  const searchCustomers = useCallback(async () => {
    setCustomerSearchLoading(true)
    try {
      const res = await customerApi.getCustomers({
        keyword: customerKeyword.trim() || undefined,
        page: 1,
        size: 30,
      })
      setCustomerResults(res.data?.data?.items || [])
    } catch (e) {
      toastRequestError(e, '搜索客户失败')
    } finally {
      setCustomerSearchLoading(false)
    }
  }, [customerKeyword])

  useEffect(() => {
    if (customerModalOpen) {
      searchCustomers()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerModalOpen])

  // 选中客户 → 自动回填收货信息（仍可手动修改）
  // 取值优先级（issue #4419）：客户档案的**默认收货地址**优先（客户管理「收货信息」卡片维护的
  // defaultReceiverName/Phone/Address）；档案没录收货信息时才回退到 #3102 的旧口径
  // （姓名=昵称 / 手机号=phone / 地址=省市区前缀）。
  const handlePickCustomer = (c: Customer) => {
    const name = c.defaultReceiverName || c.wechatNickname || c.name || c.nickname || ''
    const phone = c.defaultReceiverPhone || c.phone || ''
    const region = [c.regionProvince, c.regionCity, c.regionDistrict].filter(Boolean).join(' ')
    const address = c.defaultReceiverAddress || region
    if (name) setCustomerName(name)
    if (phone) setCustomerPhone(phone)
    if (address) setCustomerAddress(address)
    // 常用物流（issue #4874）：按**客户档案**带出，**可改**。档案没录 ⇒ 置空（未指定），
    // 不编造「快递」默认值、也不把上一个客户的档案留在界面上。
    setLogisticsType(c.defaultLogisticsType ?? '')
    setLogisticsCompany(c.defaultLogisticsCompany ?? '')
    setCustomerModalOpen(false)
    setCustomerKeyword('')
    setCustomerResults([])
  }

  // ===== 选中商品后加载详情 =====
  const handlePickProduct = async (product: Product) => {
    const lineId = activeLineId
    setProductModalOpen(false)
    if (!lineId) return

    updateLineItem(lineId, {
      productLoading: true,
      selectedProcessing: {},
      selectedColorId: null,
      selectedSku: null,
      quantity: 1,
      unitPrice: 0,
    })

    // 加载商品详情（含 SKU）；加工项不再随商品加载（issue #4371：与商品解耦，走店铺级目录）
    let detail: ProductDetail | null = null
    try {
      const res = await productApi.getProduct(product.id)
      detail = res.data?.data as unknown as ProductDetail
    } catch (e) {
      toastRequestError(e, '加载商品详情失败')
      detail = product as unknown as ProductDetail
    }

    const fallbackPrice =
      Number(detail?.price) || Number(detail?.basePrice) || Number(product.price) || 0

    updateLineItem(lineId, (it) => {
      const next: OrderLineItem = {
        ...it,
        product: detail,
        productLoading: false,
        unitPrice: fallbackPrice,
        processingItems: processingCatalog,
        selectedProcessing: {},
      }
      return {
        product: next.product,
        productLoading: next.productLoading,
        unitPrice: next.unitPrice,
        processingItems: next.processingItems,
        // 整卷售卖（issue #5846）：换商品 ⇒ 卷数**清空**（旧商品的卷数不属于新商品），
        // 每卷米数**重新带出**新商品的卷长（默认值，用户可在行上改）
        rollCount: null,
        rollLengthM: defaultRollLengthOf(next.product),
        // 换商品 = 清空勾选 ⇒ 按帘体补**推荐组合**的默认勾选（定型 #4566 + 韩褶，2026-09-28）
        selectedProcessing: withRecommendedItemDefaults(next),
      }
    })
  }

  // ===== 颜色 / 规格 选择 =====
  const handleSelectColor = (line: OrderLineItem, colorId: string) => {
    const skusOfColor = (line.product?.skus || []).filter((s) => s.colorId === colorId)
    // issue #4877 裁定 C：多门幅时按**门幅规则**选默认（可行集最小门幅 / 定宽买高分幅最少）
    const autoSku = pickAutoSkuForColor(line, skusOfColor)
    updateLineItem(line.id, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      skuAutoSelected: Boolean(autoSku),
      unitPrice: autoSku ? Number(autoSku.price) : line.unitPrice,
    })
  }

  const handleSelectSku = (line: OrderLineItem, sku: OrderProductSku) => {
    updateLineItem(line.id, {
      selectedSku: sku,
      unitPrice: Number(sku.price) || 0,
    })
  }

  /**
   * 勾选 / 取消一个加工项。
   *
   * **工艺单值护栏**（issue #4566）：路线键的工艺维是**单值** ⇒ 新勾的项带 `craftHint` 时，
   * 自动取消**另一个**带 `craftHint`（不同名）的已勾项，并 `toast` 说明换了哪一个
   * （**不静默**：同一张单出现两套工艺声明 = 两套工序，商家必须看见换了）。
   *
   * 勾/取消「定型」⇒ 记下「商家手动改过」（`shapedItemTouched`）⇒ 之后改帘体不再覆盖默认档。
   */
  const toggleProcessing = (
    line: OrderLineItem,
    pi: ProcessingItem,
    selected: boolean
  ) => {
    const prev = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
    const nextSelected: Record<string, { selected: boolean; qty: number }> = {
      ...line.selectedProcessing,
      // 选中即按当前面料米数推导数量（per_meter=米数，其余=1）；取消勾选保留原值（issue #3005 回滚 #2986）
      [pi.id]: { selected, qty: selected ? deriveProcessingQty(line.quantity) : prev.qty },
    }

    // 工艺单值护栏：一张单只能有一个工艺声明
    let replaced: ProcessingItem | undefined
    if (selected && pi.craftHint) {
      replaced = line.processingItems.find(
        (other) =>
          other.id !== pi.id &&
          Boolean(other.craftHint) &&
          other.craftHint !== pi.craftHint &&
          nextSelected[other.id]?.selected === true
      )
      if (replaced) {
        nextSelected[replaced.id] = { ...nextSelected[replaced.id], selected: false }
      }
    }

    updateLineItem(line.id, {
      selectedProcessing: nextSelected,
      // 加工项一变 ⇒ **组合键就变** ⇒ 上一组合的人工改价**必须清掉**（issue #4878 独立复核 P1）。
      // 不清的后果：`buildLineProcessingInfo` 只按「有值」就把 override 写进 processingInfo
      // ⇒ 商家为「组合 A」输的价会**静默给组合 B 定价**（后端按 manual 采用），
      // 而 fee_source 翻 manual 后改价输入框消失 ⇒ 商家连"改过价"都看不见（错钱且无感）。
      processingFeeOverride: null,
      // 手改过定型（勾或取消）⇒ 留痕，改帘体不再覆盖
      ...(pi.name === SHAPED_ITEM_NAME ? { shapedItemTouched: true } : {}),
      // 手改过**工艺项**（勾 / 取消 —— 「全不采纳」也走这里）⇒ 留痕：之后换商品 / 改帘体 /
      // 目录到达都不再把推荐组合勾回来（2026-09-28，同族纪律）
      ...(pi.craftHint ? { craftItemTouched: true } : {}),
    })

    if (replaced) {
      toast.info(`一张单只能有一个工艺：已把「${replaced.name}」换成「${pi.name}」`)
    }
  }

  /**
   * **推荐组合的采纳 / 全不采纳**（2026-09-28 用户裁定）。
   *
   * 为什么不是「逐项调 `toggleProcessing`」：那会各写一次**全量** `selectedProcessing`，
   * 后一次读到的是**旧 props** ⇒ 前一项的勾选被覆盖（连环调只在选中项相同时才碰巧正确）。
   * ⇒ 本函数**一次**算完整份对象再写。
   *
   * 两条留痕：删过 / 采纳过都算商家的表态 —— `craftItemTouched` / `shapedItemTouched`
   * 只在**该项真在推荐集里**时才置位（否则「纱帘只推荐韩褶」会把定型也锁死）。
   */
  const decideRecommendedItems = (line: OrderLineItem, decision: 'adopt' | 'reject') => {
    const names = recommendedItemNamesOf(line)
    const recommended = line.processingItems.filter((pi) => names.includes(pi.name))
    if (recommended.length === 0) return
    const want = decision === 'adopt'
    const nextSelected = { ...line.selectedProcessing }
    /** 被推荐组合顶掉的工艺项（**工艺单值护栏**，与 `toggleProcessing` 同口径） */
    let replaced: ProcessingItem | undefined
    for (const pi of recommended) {
      const prev = nextSelected[pi.id]
      if (want && pi.craftHint) {
        // 一张单只能有一个工艺声明：采纳工艺项 ⇒ 取消**别的**已选工艺项（推荐集之外的才算「别的」）
        replaced ??= line.processingItems.find(
          (other) =>
            other.id !== pi.id &&
            Boolean(other.craftHint) &&
            !names.includes(other.name) &&
            other.craftHint !== pi.craftHint &&
            nextSelected[other.id]?.selected === true
        )
        if (replaced) nextSelected[replaced.id] = { ...nextSelected[replaced.id], selected: false }
      }
      nextSelected[pi.id] = {
        selected: want,
        // 采纳 ⇒ 数量按当前米数推导（与 `toggleProcessing` 同一口径）；撤回 ⇒ 保留原数量
        qty: want && !prev?.selected ? deriveProcessingQty(line.quantity) : prev?.qty ?? 1,
      }
    }
    updateLineItem(line.id, {
      selectedProcessing: nextSelected,
      // 加工项一变 ⇒ 组合键就变 ⇒ 上一组合的人工改价必须清掉（同 `toggleProcessing`，#4878）
      processingFeeOverride: null,
      ...(names.map(craftItemKeyOf).includes(craftItemKeyOf(SHAPED_ITEM_NAME))
        ? { shapedItemTouched: true }
        : {}),
      ...(names.map(craftItemKeyOf).includes(craftItemKeyOf(DEFAULT_CRAFT_ITEM_NAME))
        ? { craftItemTouched: true }
        : {}),
    })
    if (replaced) {
      toast.info(`一张单只能有一个工艺：已把「${replaced.name}」换成「${DEFAULT_CRAFT_ITEM_NAME}」`)
    }
  }

  // 行商品数量（面料米数）**手工改**（issue #4434）：
  // ① 标记来源「人工指定」⇒ 后续算料试算**不得静默改回**（真值源 §8：褶数/用料必须带来源）；
  // ② 已选中加工项数量联动重算（per_meter=面料米数，其余=1）（issue #3005 回滚 #2986）；
  // ③ **记下改这一笔时的入参签名**（issue #5202 · 根因 2）：此后宽/高/门幅/工艺若变 ⇒
  //    页面显式告知「已人工指定，未跟随」+ 一键恢复（**不静默覆盖**，也不让商家自己猜）。
  const handleLineQtyChange = (line: OrderLineItem, qty: number) => {
    updateLineItem(line.id, {
      quantity: qty,
      metersSource: LINE_METERS_SOURCE_MANUAL,
      metersManualSignature: craftCalcSignature(craftCalcParamsOf(calcInputOf(line, calcConfig))),
      selectedProcessing: requantifyProcessing(line, qty),
    })
  }

  /** 「恢复按公式计算」（issue #4434）：显式切回 ⇒ 下一次试算重新预填数量（并清掉「未跟随」告知） */
  const restoreFormulaMeters = (line: OrderLineItem) => {
    updateLineItem(line.id, {
      metersSource: METERS_SOURCE_FORMULA,
      calcError: null,
      metersManualSignature: undefined,
    })
  }

  // ===== 算料试算（issue #4434 · 前置 #4421）=====
  //
  // 三条口径：
  // ① **单一真值**：用料米数由算料引擎（后端端点）算，前端**不复制任何公式**；公式串也由后端产出；
  // ② **只预填「公式计算」的行**：商家手改过数量的行（`人工指定`）不得被静默改回（真值源 §8）；
  // ③ **失败不静默**：400（拼次纸表未登记 / 非韩褶）在行内显式提示，数量保持原样，**不退回估算值**。
  const calcSignature = useMemo(
    () =>
      lineItems
        .map(
          (l) =>
            `${l.id}:${l.metersSource}:${craftCalcSignature(craftCalcParamsOf(calcInputOf(l, calcConfig)))}`
        )
        .join(';'),
    [lineItems, calcConfig]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: CraftCalcParams }> = []
    for (const line of lineItems) {
      if (line.metersSource !== METERS_SOURCE_FORMULA) continue
      const params = craftCalcParamsOf(calcInputOf(line, calcConfig))
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; calc: CraftCalcResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await craftCalcApi.preview(params)
              return { id, calc: (res.data?.data ?? null) as CraftCalcResult | null, error: null }
            } catch (e) {
              return { id, calc: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          if (hit.error) return { ...it, calcError: hit.error }
          const meters = Number(hit.calc?.fabric_meters)
          if (!Number.isFinite(meters) || meters <= 0) {
            return {
              ...it,
              calcError: '算料未返回有效用料米数（数量保持原样，请核对宽高与工艺）',
            }
          }
          return {
            ...it,
            calc: hit.calc,
            calcError: null,
            quantity: meters,
            selectedProcessing: requantifyProcessing(it, meters),
          }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // 依赖**只含入参签名**：试算会写回 quantity，若用行数组当依赖会自激成请求风暴
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calcSignature])

  // ===== 自动特征判定（issue #4976 包 2b：判定移到服务端）=====
  //
  // 与上面的试算 effect **同形态**（防抖 + 取消 + 只按入参签名触发），但**入参不同**：
  // 试算受 `CALC_CRAFTS` 门控（穿杆/平幔 不发；存量单的 `四爪钩` 同理），判定**每一行都发**。
  const autoFeatureSignature = useMemo(
    () =>
      lineItems
        .map((l) => `${l.id}:${autoFeatureParamsSignature(autoFeatureParamsOf(l, calcConfig))}`)
        .join(';'),
    // ⚠️ `calcConfig` 必须进依赖：两个**企业阈值**是判定入参的一部分（issue #5130）——
    // 漏了它 ⇒ 商家改完算料配置存盘后，页面**停在旧判定**上（可配却不生效的静默形态）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lineItems, calcConfig]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: AutoFeaturesParams }> = []
    for (const line of lineItems) {
      const params = autoFeatureParamsOf(line, calcConfig)
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; data: AutoFeaturesResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await autoFeaturesApi.preview(params)
              return { id, data: res.data?.data ?? null, error: null }
            } catch (e) {
              return { id, data: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          // 判定**只**写这两个字段：不碰数量/加工项（判定不产生米数）
          return { ...it, autoFeatures: hit.data, autoFeaturesError: hit.error }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFeatureSignature])

  // ===== 门幅规则（issue #5043 包 2b：规则移到服务端）=====
  //
  // 与上面两个 effect **同形态**（防抖 + 取消 + 只按入参签名触发）。
  // ⚠️ **必须在试算之前拿到**：`cuttingModeOf` 读本结果 ⇒ 它会进 `calcSignature` ⇒ 规则落行后
  // 试算会带着**正确**的加工类型再算一次（这正是「规则与试算同源」要的时序）。
  const doorWidthSignature = useMemo(
    () =>
      lineItems
        .map((l) => `${l.id}:${doorWidthParamsSignature(doorWidthParamsOf(l, calcConfig))}`)
        .join(';'),
    [lineItems, calcConfig]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: DoorWidthPlanParams }> = []
    for (const line of lineItems) {
      const params = doorWidthParamsOf(line, calcConfig)
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; data: DoorWidthPlanResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await doorWidthPlanApi.preview(params)
              return { id, data: res.data?.data ?? null, error: null }
            } catch (e) {
              return { id, data: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          const withPlan: OrderLineItem = { ...it, doorWidthPlan: hit.data, doorWidthPlanError: hit.error }
          // 规则**不产生米数** ⇒ 只写规则字段 + （规则到了才做得了的）**默认 SKU 补选**。
          if (!hit.data || hit.data.state !== 'single_panel') return withPlan
          // 只在「还没选」或「上次也是规则自动选的」时补 —— 客服手选过就**不覆盖**（同「手改留痕」纪律）
          if (withPlan.selectedSku !== null && !withPlan.skuAutoSelected) return withPlan
          const skusOfColor = (withPlan.product?.skus ?? []).filter(
            (sku) => sku.colorId === withPlan.selectedColorId
          )
          const autoSku = pickAutoSkuForColor(withPlan, skusOfColor)
          if (!autoSku) return withPlan
          return {
            ...withPlan,
            selectedSku: autoSku,
            unitPrice: Number(autoSku.price) || 0,
            skuAutoSelected: true,
          }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doorWidthSignature])

  // ===== 加工费计价预览（issue #4450 · 前置 #4406）=====
  //
  // **为什么必须有它**：本页此前本地自算（Σ 加工项），而服务端创建订单按**选配组合取价**
  // ⇒ 页面总额 ≠ 服务端总额 ⇒ 命中创建路径「实收金额与应收不一致」校验 ⇒ **拒单**。
  // 用服务端**同一份**取价实现提前拿到结果 ⇒ 页面显示 === 落库。
  //
  // ⚠️ 入参 = **即将提交的那一份** `processingInfo`（同一个 `buildLineProcessingInfo`）——
  //    预览与提交各拼一份就是「显示 ≠ 落库」的第二次分叉。
  /**
   * **商品组**（issue #4485）：按 `groupId` 把扁平行数组分组（保持出现顺序）。
   *
   * 为什么仍保留扁平数组：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径 ——
   * 提交 / 校验 / 算料 / 取价都按扁平数组走；分组**只是展示与编辑归属**，模型一字不改。
   */
  const productGroups = useMemo<ProductGroup[]>(() => {
    const order: string[] = []
    const byId = new Map<string, ProductGroup>()
    for (const line of lineItems) {
      let g = byId.get(line.groupId)
      if (!g) {
        g = {
          id: line.groupId,
          product: line.product,
          productLoading: line.productLoading,
          selectedColorId: line.selectedColorId,
          selectedSku: line.selectedSku,
          saleForm: line.saleForm,
          curtainBody: line.curtainBody,
          lines: [],
        }
        byId.set(line.groupId, g)
        order.push(line.groupId)
      }
      g.lines.push(line)
    }
    return order.map((id) => byId.get(id)!)
  }, [lineItems])

  /** 参与计价的行（与提交时的过滤条件**同一口径**：必须有商品） */
  const pricedLines = useMemo(() => lineItems.filter((l) => l.product), [lineItems])

  const feePreviewPayload = useMemo(
    () => ({
      items: pricedLines.map((l) => ({
        processingInfo: buildLineProcessingInfo(l, calcConfig),
      })),
    }),
    [pricedLines, calcConfig]
  )

  /** 行 id → 取价行下标（`pricedLines` 与 `feePreview.items` 同序） */
  const feeIndexByLineId = useMemo(() => {
    const m = new Map<string, number>()
    pricedLines.forEach((l, i) => m.set(l.id, i))
    return m
  }, [pricedLines])

  const feePreviewSignature = useMemo(() => JSON.stringify(feePreviewPayload), [feePreviewPayload])

  const [feePreview, setFeePreview] = useState<FeePreviewResult | null>(null)
  const [feePreviewError, setFeePreviewError] = useState<string | null>(null)
  const [feePreviewPending, setFeePreviewPending] = useState(false)

  useEffect(() => {
    // 没商品 ⇒ 没有可计价的行（本页初始态）⇒ 不请求
    if (pricedLines.length === 0) {
      setFeePreview(null)
      setFeePreviewError(null)
      setFeePreviewPending(false)
      return
    }
    setFeePreviewPending(true)
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const res = await feePreviewApi.preview(feePreviewPayload)
        if (cancelled) return
        setFeePreview(res.data?.data ?? null)
        setFeePreviewError(null)
      } catch (e) {
        if (cancelled) return
        setFeePreview(null)
        setFeePreviewError(feePreviewErrorText(e))
      } finally {
        if (!cancelled) setFeePreviewPending(false)
      }
    }, FEE_PREVIEW_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // 依赖只含**入参签名**：结果写回 totals 不改动入参 ⇒ 不会自激成请求风暴
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feePreviewSignature, pricedLines.length])

  /** 未定价的行数（服务端按 0 计）—— 必须显式可见：`¥0.00` 与「本来就不收」分不清 */
  // ⚠️ **布料行不计入「未定价」**（issue #4493）：布料无加工 ⇒ 服务端按 0 计是**正常**的，
  // 把它算成「未定价」会让每一张布料单都挂一条假警报。
  /**
   * 未定价行**按组合归并**（issue #4590）：只报行数 = 商家不知道该给哪个组合定价
   * （用户原话：「这里要把具体的加工项组合告知用户，不然用户不知道设置哪个组合」）。
   *
   * 组合名与**行名**（商品名 + 帘体）都取自既有真值：名字 = `items.join(' + ')`
   * （与「加工费组合」页同一写法，见 {@link unpricedCombinationLabel}）；
   * 行名 = 费用明细里已有的「商品名」（一个商品组 = 一套帘 ⇒ 同组同名，去重后即「哪些行」）。
   * 同一组合命中多行 ⇒ **合并计数**（「布帘 + 韩褶（2 行）」）；多个组合 ⇒ 逐条列。
   */
  const unpricedGroups = useMemo(() => {
    const byComposition = new Map<
      string,
      {
        composition: string
        label: string
        lineNames: string[]
        count: number
        optionTotal: number
      }
    >()
    ;(feePreview?.items ?? []).forEach((row, i) => {
      const line = pricedLines[i]
      if (!line || line.saleForm === SALE_FORM_FABRIC) return
      const detail = row.processingFeeDetail as
        | { fee_source?: string; composition?: unknown; items?: unknown; special_options_total?: unknown }
        | undefined
      if (detail?.fee_source !== 'unpriced') return
      const composition = typeof detail.composition === 'string' ? detail.composition : ''
      const entry = byComposition.get(composition) ?? {
        composition,
        label: unpricedCombinationLabel(detail),
        lineNames: [],
        count: 0,
        optionTotal: 0,
      }
      entry.count += 1
      // 选项那半照常计入行金额（issue #4594）—— 告警要说清「哪半 0、哪半照计」
      entry.optionTotal += Number(detail.special_options_total) || 0
      const name = line.product?.name?.trim()
      if (name && !entry.lineNames.includes(name)) entry.lineNames.push(name)
      byComposition.set(composition, entry)
    })
    return [...byComposition.values()]
  }, [feePreview, pricedLines])

  /** 未定价行数（= 各组合命中行数之和；告警里的「N 行」就是它） */
  const unpricedCount = unpricedGroups.reduce((n, g) => n + g.count, 0)

  /** 未定价行里**已定价特殊选项**的合计（issue #4594）：这半**照常计入订单金额** */
  const unpricedOptionTotal = unpricedGroups.reduce((sum, g) => sum + g.optionTotal, 0)

  // ===== 费用汇总 =====
  const totals = useMemo(() => {
    let productSubtotal = 0
    let edgeSubtotal = 0

    lineItems.forEach((item) => {
      if (!item.product) return
      productSubtotal += (Number(item.quantity) || 0) * (Number(item.unitPrice) || 0)
      // 双拼配布边（§4.8）：配布边是一条**独立面料明细行** ⇒ 金额必须计入订单总额，
      // 否则后端「应收 - 优惠 ≈ 实收」校验会拒单（金额 = 商家自己填的单价 × 米数，
      // 本包不引入任何工艺加价 —— 加价口径待 issue #4341 裁定）。
      const edgePrice = edgeUnitPriceOf(item)
      if (edgePrice !== null) {
        edgeSubtotal += edgeMetersOf(item) * edgePrice
      }
      // ⚠️ issue #4874：`布帘+纱帘` 那一族（含 `totals.sheerSubtotal` 与费用明细「纱帘」行）
      // 已**整体删除** —— 需要纱帘时它是**独立商品组**的一行（走本函数的商品小计），
      // 不再由主布行派生。
    })

    // 加工费 = **服务端取价结果**（issue #4450）。
    // 此前这里是本地 `Σ 加工项单价 × 数量`，与服务端 #4406 的组合取价口径不同 ⇒ 提交必被拒。
    // 预览未就绪时按 0 —— 由提交闸门拦住（不得用本地估算值提交）。
    const processingFee = feePreview?.processingFeeTotal ?? 0

    return {
      productSubtotal,
      edgeSubtotal,
      processingFee,
      total: productSubtotal + edgeSubtotal + processingFee,
    }
  }, [lineItems, feePreview])

  // ===== 优惠金额 + 实收款 双向联动逻辑 =====
  const {
    discountAmount,
    setDiscountAmount,
    commitDiscount,
    actualAmount,
    setActualAmount,
    commitActual,
  } = useOrderAmounts(totals.total)

  // 提交用数值：输入中间态（''/非法）兜底为默认值，负数 clamp 0
  const discountNumber = (() => {
    const num = Number(discountAmount)
    return Number.isNaN(num) || num < 0 ? 0 : num
  })()
  const actualNumber = (() => {
    const num = Number(actualAmount)
    return Number.isNaN(num) || num < 0 ? totals.total : num
  })()

  // ===== 校验 =====
  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {}

    if (lineItems.length === 0) {
      e.lineItems = '请至少添加一个商品'
    }

    // 加工费计价闸门（issue #4450）：**页面总额必须就是服务端将算出的总额**，
    // 否则提交会被创建路径的「实收金额与应收不一致」拒单。
    // ⇒ 计价未就绪 / 失败时**一律不许提交**（宁可让商家等一下，也不要发一个必被拒的单）。
    if (pricedLines.length > 0) {
      if (feePreviewError) {
        e.feePreview = feePreviewError
      } else if (!feePreview || feePreviewPending) {
        e.feePreview = '加工费计价中，请稍候再提交'
      }
    }

    // **加工费组合未定价闸门**（issue #5840，用户 2026-10-01 报障）：
    // 「未输入加工费组合价格但是提交成功了，缺少了必要的校验」—— 此前未定价只有一条**告警**
    // （`unpriced-fee-alert`），文案却写着「请为下列加工项组合定价后再下单」⇒ 承诺了一道不存在的闸门。
    // 口径（用户同批裁定）：
    //   · **组合键非空**（商家确实选了加工项，只是这一档没配价）⇒ **阻断** —— 钱算不出来，
    //     不允许落一张「加工费按 0 计」的错单；
    //   · **组合键为空**（根本没勾加工项 = 缺选配信息）⇒ **不阻断**，只提示
    //     （与「工艺缺失 ⇒ 允许提交，只显著提示」同一条裁定，见 `UNPRICED_NO_COMPOSITION`）。
    const unpricedWithKey = unpricedGroups.filter((g) => g.composition.trim() !== '')
    if (unpricedWithKey.length > 0) {
      const rows = unpricedWithKey.reduce((n, g) => n + g.count, 0)
      e.processingFee =
        `有 ${rows} 行加工费未定价（组合那半按 0 计）⇒ 请先定价再下单：` +
        unpricedWithKey.map((g) => g.label).join('、') +
        '。可就地改单价，或去「加工费组合」定价'
    }

    lineItems.forEach((line, idx) => {
      const prefix = `line_${line.id}`
      // 自动特征判定闸门（issue #4976 包 2b）：判定缺席 ⇒ 组合键少一项 ⇒ 取价错
      // （与上面的加工费计价闸门同口径；判定不产生米数，所以放在逐行校验之前）
      const autoBlock = autoFeaturesBlockReason([line], calcConfig)
      if (autoBlock) e[`${prefix}_autoFeatures`] = autoBlock
      if (!line.product) {
        e[`${prefix}_product`] = `第 ${idx + 1} 个商品未选择`
        return
      }
      const colorOptions = uniqueColors(line.product.skus)
      const skuOptions =
        line.selectedColorId != null
          ? (line.product.skus || []).filter((s) => s.colorId === line.selectedColorId)
          : []
      if (colorOptions.length > 0 && line.selectedColorId == null) {
        e[`${prefix}_color`] = `第 ${idx + 1} 个商品未选择颜色`
      }
      if (skuOptions.length > 0 && !line.selectedSku) {
        e[`${prefix}_spec`] = `第 ${idx + 1} 个商品未选择规格`
      }
      // 宽 / 高**必填**（issue #4420）——但**仅成品帘**（issue #4493，用户裁定）：
      // 布料按米卖，没有成品尺寸 ⇒ 布料单既不显示也不校验宽高
      // （否则布料单会被「未填宽」直接卡住提交，实测形态）。
      if (line.saleForm !== SALE_FORM_FABRIC) {
        // 它们是**不可推导的原始输入**（设计 §5.9.3）—— 丢了永远拿不回来，而用料 / 幅数 /
        // 加工单复核全靠它。只存米数 = 把输入扔了只留输出（#4273 的根因形态）。
        if (!(Number(line.width) > 0)) {
          e[`${prefix}_width`] = `第 ${idx + 1} 个商品未填宽（米）`
        }
        if (!(Number(line.height) > 0)) {
          e[`${prefix}_height`] = `第 ${idx + 1} 个商品未填高（米）`
        }
      }
      if (!line.quantity || line.quantity <= 0) {
        e[`${prefix}_quantity`] = '数量须大于 0'
      }
      if (line.unitPrice == null || line.unitPrice <= 0) {
        e[`${prefix}_unitPrice`] = '单价须大于 0'
      }
      // 整卷售卖（issue #5846）：这里**只**做边界校验 —— 用户 2026-10-01 二次裁定
      // **取消「成对」契约** ⇒「只给卷数」「只给每卷米数」都是合法输入（缺的那半由服务端回落）。
      // 两条与 `OrderService.parseExplicitRollCount` / `assertExplicitRollLengthUsable` 逐字同源：
      // 卷数 < 0 / 非整数 / 每卷米数 ≤ 0 ⇒ 显式拒绝（**不静默取整、不静默补值**）。
      if (typeof line.rollCount === 'number') {
        if (!Number.isInteger(line.rollCount)) {
          e[`${prefix}_rollCount`] = '卷数必须是整数'
        } else if (line.rollCount < 0) {
          e[`${prefix}_rollCount`] = '卷数不能为负数'
        }
      }
      if (typeof line.rollLengthM === 'number' && line.rollLengthM <= 0) {
        e[`${prefix}_rollLengthM`] = '每卷米数必须大于 0'
      }
      // ⚠️ issue #4874：原「带纱帘 ⇒ 纱帘单价必填」的校验已随 `布帘+纱帘` 档**整体删除**
      // （帘体不再有该档；独立纱帘组那一行的单价由既有的「单价须大于 0」兜住）。
    })

    if (!customerName.trim()) e.customerName = '请输入收货人姓名'
    if (!customerPhone.trim()) e.customerPhone = '请输入手机号'
    else if (!/^1[3-9]\d{9}$/.test(customerPhone.trim())) e.customerPhone = '手机号格式不正确'
    if (!customerAddress.trim()) e.customerAddress = '请输入收货地址'
    // **物流两项必填**（issue #5840；用户 2026-10-01 逐字：「物流信息改成客户信息，不能只校验物流，
    // 客户信息都是必填」+ 就本题选定「两个物流字段也必填」）。
    // 🔴 这是对 issue #4872 既有口径（「未传 ⇒ 不写，不猜」）的**有意覆盖**：字段语义仍是
    // 「未指定 ≠ 快递」（缺省值不变、不编造），改的是**准入** —— 建单必须显式给出这两项。
    if (!logisticsType) e.logisticsType = '请选择常用物流/快递'
    if (!logisticsCompany.trim()) e.logisticsCompany = '请填写常用物流公司'

    setErrors(e)
    return e
  }

  // ===== 提交 =====
  const handleSubmit = async () => {
    const found = validate()
    if (Object.keys(found).length > 0) {
      toast.error('请完善订单信息')
      // 「哪儿缺了」必须看得见（issue #5840）：① 出错的折叠区**自动展开**
      // （费用明细 / 物流 details 在这里；商品组卡与向导步骤由各自的 effect 按同一个 tick 展开）
      // ② 吸底条出现**逐条可点**的汇总（见 `submit-error-summary`）
      if (found.processingFee || found.feePreview) setFeeDetailOpen(true)
      if (found.logisticsType || found.logisticsCompany) {
        if (logisticsRef.current) logisticsRef.current.open = true
      }
      const firstKey = sortErrorKeys(Object.keys(found))[0] ?? ''
      setErrorFocus((prev) => ({ key: firstKey, tick: prev.tick + 1 }))
      return
    }

    // 套窗跨行分组已移除（issue #4486）；`craftLineId` 仍由 `buildLineProcessingInfo`
    // 按**本行自指**写入，供 §4.8 配布边行被主布行吸收（不是跨行分组）。
    const items: OrderItemFormData[] = pricedLines.flatMap((line, lineIndex) => {
      // 加工费 = **服务端取价结果**（issue #4450）：页面显示 === 落库。
      // 预览行与 `pricedLines` **同序**（服务端按下标一一对应）。
      const lineFee = Number(feePreview?.items[lineIndex]?.processingFee) || 0

      // `processingInfo` 由**同一个** `buildLineProcessingInfo` 构造（预览也是它）
      const baseInfo = buildLineProcessingInfo(line, calcConfig)
      const productSub = (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)
      const edgePrice = edgeUnitPriceOf(line)
      const pairKey = line.id

      const rows: OrderItemFormData[] = [
        {
          productId: line.product!.id,
          productName: line.product!.name,
          quantity: Number(line.quantity),
          unitPrice: Number(line.unitPrice),
          // 整卷售卖（issue #5846）：**成对**进 payload，且**只在卷数填了**时进 ——
          // 卷数留空 ⇒ 两个键都不出现（服务端按货号卷长派生，请求体与改造前**逐字节相同**）。
          // ⚠️ 半对（只有卷数）在这里就**不发**：服务端会 422，但那是兜底；能拦住就别发一份必被拒的单。
          ...rollFieldsOf(line),
          // 宽 / 高（issue #4420）：`order_items.width/height` 是**部位级**原生列，
          // 后端 DTO 已带 `@DecimalMin(0)`（#4089 A17）。此前这页一个都不写 ⇒
          // 订单详情 / 加工单 / 任务卡的宽高渲染永远拿不到值（#4403 的根因）。
          width: Number(line.width),
          height: Number(line.height),
          subtotal: productSub + lineFee,
          processingInfo: baseInfo
            ? // `processingFee` 用**服务端试算值**；`processingFeeDetail` **不送** ——
              // 服务端创建时按同一份取价写入权威构成，送一份客户端副本只会多一个可漂移的面。
              { ...baseInfo, processingFee: lineFee }
            : undefined,
        } as OrderItemFormData,
      ]

      // 配布边行（§4.8 一套窗 = 主布行 + 配布边行）：
      // - **不携带工艺规格**（褶数/开数/幅数是一套窗的属性 ⇒ 两行都带会让工序与计件翻倍）
      // - **不挂加工项**（硬约束：加工费只挂主布行）
      // - **不关联主布商品**（后端按 productId 聚合库存/销量 ⇒ 复用会双扣库存、双计销量）
      // - **绑组键与所在套窗同一个**（issue #4395）：配布边行与主布行同属一套窗 ⇒ 用 `pairKey`
      //   而不是本行自指（主布行被并进别的套窗时，自指会把配布边行丢在组外）
      if (edgePrice !== null) {
        const sku = line.selectedSku
        const colorName = uniqueColors(line.product!.skus).find(
          (c) => c.id === line.selectedColorId
        )?.name
        const edgeMeters = edgeMetersOf(line)
        rows.push({
          productName: COMPONENT_ROLE_EDGE,
          quantity: edgeMeters,
          unitPrice: edgePrice,
          subtotal: edgeMeters * edgePrice,
          processingInfo: {
            colorName,
            skuCode: sku?.skuCode,
            doorWidth: sku?.doorWidth,
            ...buildEdgeLineCraftSpec(
              pairKey,
              line.edgeMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
            ),
          },
        } as OrderItemFormData)
      }

      // ⚠️ issue #4874：原「纱帘行」（`布帘+纱帘` 档的第二条明细行，携带同一份工艺规格、
      // 同 `craftLineId`）已**整体删除** —— 该档不再存在。纱帘若要单独成行，走**独立商品组**
      // （帘体 = 纱帘 ⇒ 该行显式写 `curtainType=纱帘`，部位语义与工序路线一字未动）。

      return rows
    })
    const actual = actualNumber
    let finalRemark = remark.trim()
    if (Math.abs(actual - totals.total) > 0.001) {
      const note = `实收款：¥${actual.toFixed(2)}（订单总额 ¥${totals.total.toFixed(2)}，优惠 ¥${discountNumber.toFixed(2)}）`
      finalRemark = finalRemark ? `${finalRemark}\n${note}` : note
    }

    setSubmitting(true)
    try {
      await orderApi.createOrder({
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim(),
        // **安装小区**（issue #7856）：订单级、**顶层**一个值（服务端扇出到每行 JSONB）。
        // 缺值 ⇒ **键不出现**（与 `urgencyRequestFields` 同口径：未填 ≠ 写了一串空）。
        ...(installCommunity.trim() ? { installCommunity: installCommunity.trim() } : {}),
        actualAmount: actual,
        // 后端校验 应收 - 优惠 ≈ 实收（容差 0.01），必须随单携带，否则实收≠应收会被拒
        discountAmount: discountNumber,
        // **常用物流/快递 + 常用物流公司**（issue #4874）随建单落 `orders` 两列（后端 #4872）。
        // 缺值**不写**（`undefined`）——「未指定」与「快递」是两个真值，写死默认值 = 编造。
        logisticsType: logisticsType || undefined,
        logisticsCompany: logisticsCompany.trim() || undefined,
        // **加急 / 要求到货日**（issue #5177，做在订单上）：**未勾/未填 ⇒ 键不出现** ——
        // 「没填」与「显式不加急」在请求体上必须能区分（后端库列 NOT NULL DEFAULT FALSE / NULL）。
        // 不写死默认值（#4419 同族口径）；与售后 priority 零联动。
        ...urgencyRequestFields(isUrgent, requiredDeliveryDate, isOutsourced),
        remark: finalRemark || undefined,
        items,
      })
      toast.success('订单创建成功')
      router.push('/orders')
    } catch (err) {
      toastRequestError(err, '创建订单失败')
      // 🔴 授信闸门拒时，服务端原文里带「尚缺 ¥X」——就地开出申请入口，
      //    金额预填「尚缺」那个数（不是订单总额：批多了会白占额度），拿不到就退回订单总额。
      // 服务端原话在 `response.data.message`（不是 axios 的 `err.message`）⇒ 用统一提取器；
      // 解析与兜底都在 `creditDraftFromRejection`（纯函数，可逐句断言），页面只负责挂弹窗
      const draft = creditDraftFromRejection(loadErrorMessage(err, '创建订单失败'), {
        customerPhone,
        customerName: customerName.trim() || null,
        fallbackAmount: actual,
      })
      if (draft) setApprovalDraft(draft)
    } finally {
      setSubmitting(false)
    }
  }

  // ====== 渲染 ======
  return (
    <div className="p-6 max-w-[1280px] mx-auto">
      {/* 授信审批弹窗（issue #7374 段 4）：被「超出客户授信额度」拒时就地申请，
          ref = 客户手机号、金额预填「尚缺」那个数 —— 门槛与 ref 口径见 `lib/approval-request.ts` */}
      <RequestApprovalModal
        open={approvalDraft !== null}
        onClose={() => setApprovalDraft(null)}
        draft={approvalDraft}
      />
      {/* 顶部：返回 + 标题 */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push('/orders')}
          className="p-2 rounded-lg border border-neutral-200 hover:bg-neutral-50 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5 text-neutral-600" />
        </button>
        <div className="flex-1">
          <PageHeader
            title="新增订单"
            subtitle={<>填写新订单：<strong>可添加多个商品，每个商品单独配加工项</strong></>}
          />
        </div>
      </div>

      {/* **单列全宽**（2026-09-29 第三次裁定）：右栏（加急/到货日 + 费用明细）原来吃掉 1/3 宽，
          商品列表被挤窄 ⇒ 费用明细改**底部吸底条**、主区全宽（加急/到货日压成一行）。
          ⚠️ 吸底条的 `sticky bottom-0` 生效于页面滚动根 —— 明细展开时内部自己滚（`max-h`），
          不把整条撑高。 */}
      <div className="space-y-6">
          {/* ============= 商品信息（多行项） ============= */}
          {/* 加工项目录读失败（issue #6691）：常驻面**一行**（§31 P1），不随数据增长占屏 */}
          {processingCatalogFailed && (
            <div
              data-testid="orders-new-processing-catalog-error"
              role="alert"
              className="flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
            >
              <span>加工项目录加载失败 —— 行上的加工项列表会显示为空，请重试</span>
              <Button variant="secondary" size="sm" data-testid="orders-new-processing-catalog-retry" onClick={() => void loadProcessingCatalog()}>
                重试
              </Button>
            </div>
          )}

          <Card>
            <div className="p-6">
              {/* 识别入口挂在**商品信息**标题行（2026-09-28 用户裁定，红框即本行）——
                  它一次产出「明细（要走选品面板建行）+ 收货信息 + 备注」，产出最多的一块就是这里；
                  收货信息只占其中一小块 ⇒ 入口不再挂在那边（避免「拍照入口属于收货信息」的错觉）。 */}
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <SectionTitle icon={<Package className="w-4 h-4" />} title="商品信息" />
                <div className="flex items-center gap-3">
                  {/* issue #6530：与建品页**同一个入口形态** —— 「拍照 / 上传识别」+「补充一句（可选）」，
                      走同一条一次性推理链（不经过黄金策对话窗口）。订单侧的解读仍然**一格都不填**
                      （客户信息错 ⇒ 货发错人）：那句话只用来消歧与给依据，值一律由 `[图片识别]` 来。 */}
                  <ImageRecognizeButton targetType="order" interpret onRecognized={handleRecognized} />
                  <span className="text-xs text-neutral-400">
                    共 {lineItems.length} 个商品
                  </span>
                </div>
              </div>

              <div className="space-y-4">
                {productGroups.map((group, gi) => (
                  <ProductGroupBlock
                    key={group.id}
                    index={gi}
                    group={group}
                    canRemove={productGroups.length > 1}
                    errors={errors}
                    errorFocus={errorFocus}
                    onPickProduct={() => openProductModalFor(group.lines[0].id)}
                    onSelectColor={(colorId) => handleSelectColorForGroup(group.id, colorId)}
                    onSelectSku={(sku) => handleSelectSkuForGroup(group.id, sku)}
                    onChangeSaleForm={(form) => handleSaleFormChange(group.id, form)}
                    onChangeCurtainBody={(body) => handleCurtainBodyChange(group.id, body)}
                    onRemoveGroup={() => removeGroup(group.id)}
                    // 净尺寸（2026-09-28）：两格尺寸提到组级（商品 / 颜色之后）—— 落在本组主行上
                    onChangeWidth={(w) => handleLineWidthChange(group.lines[0], w)}
                    onChangeHeight={(h) => handleLineHeightChange(group.lines[0], h)}
                    onChangeQty={(lineId, q) => {
                      const target = lineItems.find((l) => l.id === lineId)
                      if (target) handleLineQtyChange(target, q)
                    }}
                    onChangePrice={(lineId, p) => updateLineItem(lineId, { unitPrice: p })}
                    // 整卷售卖（issue #5846）：**逐行**落行状态（组级商品属性，但这三个数是行级的 ——
                    // 一组的多个部位行各发各的卷，写组级会把卷数复制到每一行 ⇒ 双计）
                    onChangeRollCount={(lineId, n) => updateLineItem(lineId, { rollCount: n })}
                    onChangeRollLength={(lineId, n) => updateLineItem(lineId, { rollLengthM: n })}
                    renderPosition={(line, slots) => (
                      <LineItemBlock
                        key={line.id}
                        line={line}
                        errors={errors}
                        errorFocus={errorFocus}
                        processingLoading={processingCatalogLoading}
                        onChangeQty={(q) => handleLineQtyChange(line, q)}
                        onRestoreFormula={() => restoreFormulaMeters(line)}
                        onChangePrice={(p) => updateLineItem(line.id, { unitPrice: p })}
                        // 部位备注（issue #5685）：只进行状态 —— 落库由 `buildLineProcessingInfo` 单点完成
                        onChangeRemark={(r) => updateLineItem(line.id, { remark: r })}
                        // 安装位置（issue #7856）：同上 —— 落库由 `buildLineProcessingInfo` 单点完成
                        onChangeInstallRoom={(room) => updateLineItem(line.id, { installRoom: room })}
                        onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                        onChangeCraft={(patch) => {
                          updateLineItem(line.id, {
                            craft: { ...line.craft, ...patch },
                            // 商家手改了打开方式 ⇒ 记下来（行状态），之后改宽不再覆盖
                            ...(patch.openCount !== undefined
                              ? { openCountTouched: true }
                              : {}),
                            // 加工类型**点过就是人工覆盖**（issue #5202 · 裁定 6）：连点「未指定」
                            // 也算点过 —— 否则默认档会继续替商家说话（默认档 ≠ 他的选择）。
                            ...('cuttingMode' in patch ? { cuttingModeTouched: true } : {}),
                          })
                          // 加工类型（定高买宽 / 定宽买高）变了 ⇒ 规则解可能变 ⇒ 未选门幅时补默认
                          autoSelectSkuByRuleForGroup(line.groupId, {
                            craft: { ...line.craft, ...patch },
                          })
                        }}
                        onAutoFeatureDecision={(name, decision) =>
                          decideAutoFeature(line.id, name, decision)
                        }
                        onEdgeMetersChange={(m) => updateLineItem(line.id, { edgeMeters: m })}
                        onEdgeUnitPriceChange={(p) =>
                          updateLineItem(line.id, { edgeUnitPrice: p })
                        }
                        // 加工费组合明细（issue #4874）：取价行（未定价 ⇒ 可就地改单价）
                        feeRow={
                          feeIndexByLineId.get(line.id) === undefined
                            ? null
                            : feePreview?.items[feeIndexByLineId.get(line.id)!] ?? null
                        }
                        calcConfig={calcConfig}
                        // 人工加 / 改推导项（issue #5202 · 裁定 4/6）：`null` = 清掉该项（回到由推导决定）
                        onChangePlanOverrides={(patch) =>
                          updateLineItem(line.id, (it) => ({
                            planOverrides: mergePlanOverrides(it.planOverrides, patch),
                          }))
                        }
                        // 推导出的特殊选项的裁决（issue #5211）：不采纳 ⇒ 该项不进 specialOptions
                        // （不插工序、不计件）
                        onDerivedOptionDecision={(name, decision) =>
                          decideDerivedOption(line.id, name, decision)
                        }
                        onProcessingFeeOverrideChange={(p) =>
                          updateLineItem(line.id, { processingFeeOverride: p })
                        }
                        // 推荐组合的采纳 / 全不采纳（2026-09-28）：一次写整份勾选态
                        onRecommendedDecision={(decision) =>
                          decideRecommendedItems(line, decision)
                        }
                        // 门幅 / 规格（2026-09-30 第四批）：与用料米数 / 单价同一行；
                        // 节点的 JSX 由组级算（`ProductGroupBlock`）经 `slots` 传进来 ⇒ 只此一份。
                        specPicker={slots.spec}
                        specExtras={slots.specExtras}
                      />
                    )}
                  />
                ))}
              </div>

              <button
                type="button"
                onClick={addLineItem}
                className="mt-4 w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 hover:bg-primary-50/30 transition-colors inline-flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                添加商品
              </button>
            </div>
          </Card>

          {/* ============= 收货信息 ============= */}
          <Card>
            <div className="p-6">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <SectionTitle icon={<User className="w-4 h-4" />} title="收货信息" />
                {/* #3102: 选择已有客户快捷回填收货信息 —— 🔴 2026-09-29 第三次裁定把它升为**主路径**：
                    选客户即带出姓名 / 电话 / 地址 / 常用物流（用户口径「未来都是选择客户带出其他信息，
                    新增客户的情况可能一开始会多，未来就能简化选择」）⇒ 手工填写退为**兜底**，不再抢视线。 */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-neutral-400">
                    选客户自动带出姓名 / 电话 / 地址 / 常用物流
                  </span>
                  <Button type="button" size="sm" onClick={() => setCustomerModalOpen(true)}>
                    <UserPlus className="w-4 h-4 mr-1.5" />
                    选择客户
                  </Button>
                </div>
              </div>
              {/* 图片识别快通道（issue #5321 包 1；**2026-09-28 起入口挂在「商品信息」标题行**）——
                  本卡不再放入口：识别一次产出的是「明细 + 收货信息 + 备注」，
                  商家在商品信息那里点一次即预填本卡（识别到的收货字段仍带 `RecognizedBadge`）。 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-start gap-2">
                  <Input
                    label="收货人姓名"
                    placeholder="请输入收货人姓名"
                    value={customerName}
                    onChange={(e) => setCustomerName(e.target.value)}
                    error={errors.customerName}
                    required
                  />
                  {recognizedFields.includes('customerName') && (
                    <RecognizedBadge fieldKey="customerName" />
                  )}
                </div>
                <div className="flex items-start gap-2">
                  <Input
                    label="手机号"
                    placeholder="请输入 11 位手机号"
                    value={customerPhone}
                    onChange={(e) => setCustomerPhone(e.target.value)}
                    error={errors.customerPhone}
                    maxLength={11}
                    required
                  />
                  {recognizedFields.includes('customerPhone') && (
                    <RecognizedBadge fieldKey="customerPhone" />
                  )}
                </div>
              </div>
              <div className="mt-4">
                <div className="flex items-start gap-2">
                  <Input
                    label="收货地址"
                    placeholder="请输入详细收货地址"
                    value={customerAddress}
                    onChange={(e) => setCustomerAddress(e.target.value)}
                    error={errors.customerAddress}
                    required
                  />
                  {recognizedFields.includes('customerAddress') && (
                    <RecognizedBadge fieldKey="customerAddress" />
                  )}
                </div>
              </div>
              {/* **安装小区**（issue #7856，用户 2026-10-26）：「客户要求我们备注窗帘未来安装给哪个小区」。
                  它是**订单级**的一个值，且与上面的收货地址**不是同一个事实**（货发给窗帘店、
                  帘子装进客户家）⇒ 并排摆开、各自独立录入。选填：不参与必填校验、不阻塞提交。 */}
              <div className="mt-4">
                <Input
                  label="安装小区"
                  placeholder="例：春江花园 3栋2单元（选填，随货打印给安装/分拣用）"
                  value={installCommunity}
                  onChange={(e) => setInstallCommunity(e.target.value)}
                  maxLength={INSTALL_COMMUNITY_MAX_LENGTH}
                />
              </div>
              {/* **常用物流 / 快递** + **常用物流公司**（issue #4874，用户 2026-09-21：
                  「新增订单时收货信息中缺少用户的常用物流/快递以及常用公司，选择客户后要默认带出」）
                  —— 两个**可编辑**控件（词表唯一真值 = `lib/logistics.ts`），选客户时按档案带出，
                  随建单提交顶层 `logisticsType` / `logisticsCompany`（后端 #4872 落 `orders` 两列）。
                  ⚠️ 原先那条**只读**提示 `picked-logistics-hint` 已删除（不留两份口径）。
                  🔴 issue #6589（2026-10-09 用户逐字「订单这里折叠情况下应该要展示隐藏的具体信息」）：
                  **收起态**的 `<summary>` 直接把 `logisticsSummary`（已带出的具体物流）摆出来 ——
                  改前它与两个控件的值零绑定，收起时商家只能看见通用提示、看不出选了什么。 */}
              <details
                data-testid="logistics-section"
                ref={logisticsRef}
                className="mt-4 rounded border border-neutral-200 bg-neutral-50/40 px-3 py-2"
              >
                <summary
                  data-testid="logistics-summary"
                  className="cursor-pointer text-xs text-neutral-500 hover:text-neutral-700"
                >
                  {logisticsSummary ? (
                    <>
                      常用物流：
                      <span className="font-medium text-primary-700">{logisticsSummary}</span>
                    </>
                  ) : (
                    '常用物流（必填 · 选客户时自动带出）'
                  )}
                </summary>
                <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="order-logistics-type"
                    className="block text-sm font-medium text-neutral-700 mb-1.5"
                  >
                    常用物流/快递
                  </label>
                  <select
                    id="order-logistics-type"
                    data-testid="order-logistics-type"
                    value={logisticsType}
                    onChange={(e) => setLogisticsType(e.target.value)}
                    className={cn(SELECT_CONTROL, 'w-full')}
                  >
                    {/* 「未指定」是真值：客户没录过常用物流时**不编造**「快递」（#4419 口径） */}
                    <option value="">未指定</option>
                    {LOGISTICS_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  {errors.logisticsType && (
                    <p className="mt-1 text-sm text-red-600">{errors.logisticsType}</p>
                  )}
                </div>
                <div>
                  <label
                    htmlFor="order-logistics-company"
                    className="block text-sm font-medium text-neutral-700 mb-1.5"
                  >
                    常用物流公司
                  </label>
                  {/* 候选来自 `lib/logistics.ts` 并按「常用物流/快递」收敛（issue #8079），
                      但**允许自定义**（词表只是候选，不是白名单） */}
                  <input
                    id="order-logistics-company"
                    data-testid="order-logistics-company"
                    list="order-logistics-company-options"
                    placeholder="如 四季安物流"
                    value={logisticsCompany}
                    onChange={(e) => setLogisticsCompany(e.target.value)}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <datalist id="order-logistics-company-options">
                    {logisticsCompaniesFor(logisticsType).map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                  {errors.logisticsCompany && (
                    <p className="mt-1 text-sm text-red-600">{errors.logisticsCompany}</p>
                  )}
                </div>
                </div>
              </details>
              <div className="mt-4">
                <label className="block text-sm font-medium text-neutral-700 mb-1.5">
                  备注
                  {recognizedFields.includes('remark') && <RecognizedBadge fieldKey="remark" />}
                </label>
                <textarea
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder="可填写发货要求、特殊说明等（选填）"
                  rows={3}
                  className="w-full px-3 py-2 rounded border border-neutral-300 text-sm resize-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
              </div>
            </div>
          </Card>
          {/* 加急 / 要求到货日（issue #5177）：**做在订单上**（不是售后页）——
              加急单在智能派单页走「加急订单（不参与合并）」，到货日是派单排序键。
              2026-09-29：主区改全宽 ⇒ 本卡压成**一行**（开关 + 到货日并排），不再竖排占高。 */}
          <Card>
            <div className="p-6">
              <SectionTitle icon={<Zap className="w-4 h-4" />} title="加急 / 到货日" />
              <div className="mt-4 flex flex-wrap items-center gap-x-8 gap-y-3">
                <div className="flex items-start gap-3">
                  {/*
                    开关用 `role="switch"` 的按钮（**不是** `<input type="checkbox">`）：
                    下单页上已有「加工项」勾选框，多一个原生 checkbox 会让既有的
                    `getByRole('checkbox')` 变成「命中多个」（页面上不再有唯一的 checkbox）。
                  */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isUrgent}
                    aria-label="加急"
                    onClick={() => setIsUrgent((v) => !v)}
                    className={cn(
                      'mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                      isUrgent ? 'bg-primary-600' : 'bg-neutral-300'
                    )}
                  >
                    <span
                      className={cn(
                        'ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                        isUrgent && 'translate-x-4'
                      )}
                    />
                  </button>
                  <span className="text-sm text-neutral-700">
                    加急（插队）
                    <span className="block text-xs text-neutral-400 mt-0.5">
                      加急单不参与合并，在智能派单页立即单独派单
                    </span>
                  </span>
                </div>
                {/* 外发加工（V194，issue #7746 后续）：与加急同款开关（role="switch"，理由同上） */}
                <div className="flex items-start gap-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isOutsourced}
                    aria-label="外发加工"
                    onClick={() => setIsOutsourced((v) => !v)}
                    className={cn(
                      'mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                      isOutsourced ? 'bg-primary-600' : 'bg-neutral-300'
                    )}
                  >
                    <span
                      className={cn(
                        'ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                        isOutsourced && 'translate-x-4'
                      )}
                    />
                  </button>
                  <span className="text-sm text-neutral-700">
                    外发加工（交给加工厂）
                    <span className="block text-xs text-neutral-400 mt-0.5">
                      外发单不参与合并，在智能派单页选承接方后立即单独派单
                    </span>
                  </span>
                </div>
                <div className="min-w-[12rem]">
                  {/* 要求到货日：label 与日期控件**同一行**（issue #5915 —— 用户 2026-10-01：
                      「要求到货日能否和日期选择控件放一行？」）。改前 label 是 `block + mb-1.5`
                      （独占一行）、控件 `w-full`（撑满该格）⇒ 这一格是竖排，与本卡外面「开关 + 到货日」
                      的并排不一致，还多占一行高度。提示仍**另起一行、整格宽**，文案一字未改。
                      ⚠️ `htmlFor` ↔ `id` 的关联必须留着（`getByLabelText('要求到货日')` 与点 label 聚焦都靠它）。 */}
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor="requiredDeliveryDate"
                      className="shrink-0 whitespace-nowrap text-sm font-medium text-neutral-700"
                    >
                      要求到货日
                    </label>
                    <input
                      type="date"
                      id="requiredDeliveryDate"
                      value={requiredDeliveryDate}
                      onChange={(e) => setRequiredDeliveryDate(e.target.value)}
                      className="h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    />
                  </div>
                  <p className="mt-1 text-xs text-neutral-400">
                    留空 = 未指定（不填就是不填，不猜一个日期）；到货日越早，在智能派单页排得越前
                  </p>
                </div>
              </div>
            </div>
          </Card>

          {/* **费用明细 → 底部吸底汇总条**（2026-09-29 第三次裁定，用户原话「费用计算占了很大
              一块区域，导致商品列表很拥挤」）：常态只占**一行**（订单金额 + 未定价提示 + 提交/取消），
              逐行明细点「费用明细」才展开（内部自己滚，不撑高吸底条）。 */}
          <div
            data-testid="fee-summary-bar"
            className="sticky bottom-0 z-20 rounded-xl border border-neutral-200 bg-white/95 px-4 py-3 backdrop-blur shadow-[0_-2px_12px_rgba(0,0,0,0.05)]"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="text-sm text-neutral-500">合计</span>
                <span
                  data-testid="fee-summary-total"
                  className="text-xl font-semibold text-primary-600"
                >
                  {formatAmount(totals.total)}
                </span>
                {unpricedCount > 0 && (
                  <span className="text-xs text-amber-600">
                    {unpricedCount} 行加工费未定价（组合那半按 0 计）
                  </span>
                )}
                {feePreviewPending && pricedLines.length > 0 && (
                  <span className="text-xs text-neutral-400">加工费计价中…</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="fee-detail-toggle"
                  aria-expanded={feeDetailOpen}
                  onClick={() => setFeeDetailOpen((v) => !v)}
                  className="h-9 px-3 rounded border border-neutral-300 bg-white text-sm text-neutral-600 hover:border-neutral-400 transition-colors"
                >
                  {feeDetailOpen ? '收起明细' : '费用明细'}
                </button>
                <Button onClick={handleSubmit} loading={submitting} size="lg">
                  提交订单
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => router.push('/orders')}
                  size="lg"
                  disabled={submitting}
                >
                  取消
                </Button>
              </div>
            </div>
            {/* **「哪儿缺了」汇总**（issue #5840）：常显在吸底条上（不在任何折叠区里 ——
                否则又变成「只有点开才看得见」）。逐条可点 ⇒ 自动展开对应折叠区并滚过去。 */}
            {errorEntries.length > 0 && (
              <div
                data-testid="submit-error-summary"
                className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2"
              >
                <p className="text-xs font-medium text-red-700">
                  还差 {errorEntries.length} 项（点一条可直接定位）：
                </p>
                <ul className="mt-1 space-y-0.5">
                  {errorEntries.map(({ key, message }) => (
                    <li key={key}>
                      <button
                        type="button"
                        data-testid="submit-error-item"
                        data-error-key={key}
                        onClick={() => focusError(key)}
                        className="text-left text-xs text-red-700 underline underline-offset-2 hover:text-red-900"
                      >
                        {message}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {feeDetailOpen && (
              <div
                data-testid="fee-detail-panel"
                className="mt-4 max-h-[60vh] overflow-auto pr-1"
              >
              <SectionTitle icon={<Receipt className="w-4 h-4" />} title="费用明细" />

              {/* 行项费用构成（issue #4420 重设计；**issue #4488② 改为按商品组合并**）。
                  用户 2026-09-19：「费用计算也不对」⇒「**按商品合并商品金额**」。
                  商品金额按**商品组**并成一行（米数 = 各部位之和）；**加工费仍逐部位**
                  （加工费按部位归属，不合并 —— 合并会看不出是哪个部位收的）。 */}
              {productGroups.some((g) => g.product) && (
                <div className="mb-4 space-y-3">
                  {productGroups
                    .filter((g) => g.product)
                    .map((group, gi) => {
                      const groupMeters = group.lines.reduce(
                        (acc, l) => acc + (Number(l.quantity) || 0),
                        0
                      )
                      const groupUnit = Number(group.lines[0].unitPrice) || 0
                      const groupSub = group.lines.reduce(
                        (acc, l) =>
                          acc + (Number(l.quantity) || 0) * (Number(l.unitPrice) || 0),
                        0
                      )
                      const groupProc = group.lines.reduce((acc, l) => {
                        const i = feeIndexByLineId.get(l.id)
                        return acc + (i === undefined ? 0 : Number(feePreview?.items[i]?.processingFee) || 0)
                      }, 0)
                      const groupEdge = group.lines.reduce((acc, l) => {
                        const p = edgeUnitPriceOf(l)
                        return acc + (p === null ? 0 : edgeMetersOf(l) * p)
                      }, 0)
                      const groupColor = uniqueColors(group.product?.skus).find(
                        (c) => c.id === group.selectedColorId
                      )?.name
                      const isFabric = group.saleForm === SALE_FORM_FABRIC
                      return (
                        <div
                          key={group.id}
                          className="rounded-lg border border-neutral-200 overflow-hidden"
                        >
                          <div className="flex items-center justify-between gap-2 px-3 py-2 bg-neutral-50/70">
                            <span className="text-xs font-medium text-neutral-700 truncate">
                              <span className="text-neutral-400 mr-1">{gi + 1}.</span>
                              {group.product?.name}
                              {groupColor && (
                                <span className="ml-1.5 font-normal text-primary-600">
                                  {groupColor}
                                </span>
                              )}
                              {isFabric && (
                                <span className="ml-1.5 font-normal text-neutral-500">布料</span>
                              )}
                            </span>
                            <span className="text-sm font-semibold text-neutral-900 shrink-0">
                              {formatAmount(groupSub + groupProc + groupEdge)}
                            </span>
                          </div>
                          <div className="px-3 py-2 space-y-1">
                            {/* 商品金额**按商品组合并成一行**（米数 = 各部位之和，总额不变） */}
                            <CostRow
                              label="商品"
                              expr={`${groupMeters} 米 × ${formatAmount(groupUnit)}/米`}
                              amount={groupSub}
                            />
                            {/* 加工费**逐部位**（成品帘才有） */}
                            {!isFabric &&
                              group.lines.map((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const d = feeRow?.processingFeeDetail as
                                  | {
                                      unit_price?: number
                                      meters?: number
                                      fee_source?: string
                                      composition?: unknown
                                      items?: unknown
                                      special_options_total?: unknown
                                    }
                                  | undefined
                                /** 该行已定价特殊选项的合计（issue #4594：组合未定价时它**照常计入**） */
                                const rowOptionTotal = Number(d?.special_options_total) || 0
                                const unit = Number(d?.unit_price)
                                const meters = Number(d?.meters)
                                const expr =
                                  Number.isFinite(unit) && Number.isFinite(meters)
                                    ? `${meters} 米 × ${formatAmount(unit)}/米`
                                    : null
                                // 判据 5（issue #4526）：加工行只显示**组合那半** —— 整个
                                // `processingFee` 含特殊选项那半，直接显示再单列特殊选项行 = 双算。
                                const feeDisplay = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return (
                                  <CostRow
                                    key={`p_${line.id}`}
                                    label={
                                      line.curtainBody === CURTAIN_BODY_SHEER
                                        ? '加工·纱帘'
                                        : '加工'
                                    }
                                    expr={
                                      // 未定价行**点名组合**（issue #4590）：只写「未定价（按 0 计）」
                                      // 等于让商家自己回费用明细里猜是哪个组合没价。
                                      // issue #4594：未定价只指**组合那半** —— 已定价特殊选项照常计入
                                      // （它们另有逐项行），行内必须说清「哪半 0」，否则看起来像一分不收。
                                      d?.fee_source === 'unpriced'
                                        ? `组合未定价（组合那半按 0 计）· ${unpricedCombinationLabel(d)}${
                                            rowOptionTotal > 0
                                              ? `；特殊选项照计 ${formatAmount(rowOptionTotal)}`
                                              : ''
                                          }`
                                        : (expr ?? '—')
                                    }
                                    amount={feeDisplay.baseAmount}
                                    // 未定价 ⇒ **不渲染 `¥0.00`**（仓库硬纪律）：那格写「未定价」，
                                    // 组合名与「选项照计」在上面的算式里已经说清（issue #4590/#4594）
                                    amountLabel={
                                      d?.fee_source === 'unpriced' ? '未定价' : undefined
                                    }
                                  />
                                )
                              })}
                            {/* 特殊选项逐项（issue #4526 · 设计 §4.3 / 判据 5）：按**套**收费，
                                与加工费是**两半** —— 逐行 `名称 单价/套 × 套数`，合计进订单金额。
                                未定价的选项显式标「未定价（按 0 计）」，不静默。 */}
                            {!isFabric &&
                              group.lines.flatMap((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const display = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return display.specialOptionRows.map((option) => (
                                  <CostRow
                                    key={`o_${line.id}_${option.key}`}
                                    label={option.label}
                                    expr={option.expr}
                                    amount={option.amount}
                                  />
                                ))
                              })}
                            {/* 拼色加价（#4855，用户 2026-09-21 裁定）：行金额的**第三个分量** ——
                                拼色款另加 2.4 元/米 × 面料米数（报价侧同源同价）。
                                键缺席（存量单 / 旧服务端）⇒ 0 ⇒ 不渲染该行（显示口径逐字不变）。 */}
                            {!isFabric &&
                              group.lines.map((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const display = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return display.mixedColorSurcharge > 0 ? (
                                  <CostRow
                                    key={`m_${line.id}`}
                                    label="拼色加价"
                                    expr={display.mixedColorSurchargeExpr}
                                    amount={display.mixedColorSurcharge}
                                  />
                                ) : null
                              })}
                            {/* 配布边逐行（§4.8 一套窗 = 主布行 + 配布边行） */}
                            {group.lines.map((line) => {
                              const p = edgeUnitPriceOf(line)
                              if (p === null) return null
                              const m = edgeMetersOf(line)
                              return (
                                <CostRow
                                  key={`e_${line.id}`}
                                  label="配布边"
                                  expr={`${m} 米 × ${formatAmount(p)}/米`}
                                  amount={m * p}
                                />
                              )
                            })}
                            {/* ⚠️ issue #4874：原「纱帘」逐行（`布帘+纱帘` 档派生的第二条面料行）
                                已整体删除 —— 该档不再存在，需要纱帘时它是独立商品组的一行
                                （并入上面的「商品」金额，不再单列）。 */}
                          </div>
                        </div>
                      )
                    })}
                </div>
              )}

              <dl className="space-y-3 text-sm">
                <Row label="商品小计" value={formatAmount(totals.productSubtotal)} />
                {totals.edgeSubtotal > 0 && (
                  <Row label="配布边" value={formatAmount(totals.edgeSubtotal)} />
                )}
                {/* ⚠️ issue #4874：`totals.sheerSubtotal` 与「纱帘」汇总行已整体删除 */}
                <Row
                  label="加工费"
                  value={formatAmount(totals.processingFee)}
                  highlight={totals.processingFee > 0}
                />
                {/* 加工费计价状态（issue #4450）：数字来自**服务端**，状态必须显式可见 */}
                {feePreviewError && (
                  <div className="rounded bg-red-50 px-2.5 py-1.5 text-xs text-red-700">
                    {feePreviewError}（未确认金额前无法提交）
                  </div>
                )}
                {!feePreviewError && feePreviewPending && pricedLines.length > 0 && (
                  <div className="text-xs text-neutral-400">加工费计价中…</div>
                )}
                {!feePreviewError && unpricedCount > 0 && (
                  <div
                    data-testid="unpriced-fee-alert"
                    className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700"
                  >
                    <p>
                      有 {unpricedCount} 行加工费未定价 ——{' '}
                      <span className="font-medium">组合那半按 0 计</span>
                      {unpricedOptionTotal > 0
                        ? `；已定价的特殊选项照常计入（合计 ${formatAmount(unpricedOptionTotal)}）`
                        : ''}
                      。请为下列加工项组合定价后再下单：
                    </p>
                    {/* 逐条点名（issue #4590）：组合名与「加工费组合」页逐字一致；同一组合合并计数 */}
                    <ul className="mt-1 list-disc pl-4 space-y-0.5">
                      {unpricedGroups.map((g) => (
                        <li key={g.composition}>
                          {g.label}（{g.count} 行
                          {g.lineNames.length > 0 ? `：${g.lineNames.join('、')}` : ''}）
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">
                      定价入口：
                      <Link
                        href={PRICING_ENTRY}
                        className="underline underline-offset-2 hover:text-amber-900"
                      >
                        企业基础设置 → 加工费组合
                      </Link>
                    </p>
                  </div>
                )}
                {errors.feePreview && (
                  <div className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700">
                    {errors.feePreview}
                  </div>
                )}
                <div className="my-2 border-t border-dashed border-neutral-200" />
                <div className="flex items-baseline justify-between">
                  <span className="text-neutral-700">订单金额</span>
                  <span className="text-lg font-semibold text-primary-600">
                    {formatAmount(totals.total)}
                  </span>
                </div>

                {/* 优惠金额 — issue #672；双向联动 + blur 归一化（修复输入被每键重格式化吞键锁死） */}
                <div className="pt-3 mt-2 border-t border-neutral-100">
                  <label htmlFor="discountAmount" className="block text-sm font-medium text-neutral-700 mb-1.5">
                    优惠金额 (¥)
                  </label>
                  <input
                    type="text"
                    inputMode="decimal"
                    id="discountAmount"
                    value={discountAmount}
                    onChange={(e) => setDiscountAmount(e.target.value)}
                    onBlur={commitDiscount}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-neutral-400">默认 0；修改后实收款自动联动（订单金额 - 优惠）</p>
                </div>

                <div className="pt-3 mt-2 border-t border-neutral-100">
                  <label htmlFor="actualAmount" className="block text-sm font-medium text-neutral-700 mb-1.5">
                    实收款 (¥)
                  </label>
                  <input
                    type="text"
                    inputMode="decimal"
                    id="actualAmount"
                    value={actualAmount}
                    onChange={(e) => setActualAmount(e.target.value)}
                    onBlur={commitActual}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-neutral-400">默认与订单金额（扣除优惠后）一致；手动输入后自动反算优惠金额</p>
                </div>
              </dl>
              </div>
            )}
          </div>
      </div>

      {/* 识别到的明细 ⇒ 选品（issue #5345）：识别**不建行**，商家在面板上选了才建行 */}
      <OrderLinePicker
        entries={linePicker}
        onPick={handlePickEntry}
        onSkipAll={handleSkipAll}
        onClose={() => setLinePicker([])}
      />

      {/* 商品搜索弹窗 */}
      <Modal
        open={productModalOpen}
        onClose={() => setProductModalOpen(false)}
        title="选择商品"
        width={680}
        footer={
          <Button variant="secondary" onClick={() => setProductModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索商品名称 / 货号"
              value={productKeyword}
              onChange={(e) => setProductKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchProducts()}
            />
            <Button onClick={searchProducts} loading={productSearchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[420px] overflow-y-auto -mx-2 px-2">
            {productSearchLoading ? (
              <p className="text-center text-neutral-400 py-8 text-sm">加载中…</p>
            ) : productResults.length === 0 ? (
              <p className="text-center text-neutral-400 py-8 text-sm">
                {productKeyword ? '未找到相关商品' : '暂无可选商品'}
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {productResults.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handlePickProduct(p)}
                    className="flex items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-white hover:border-primary-400 hover:bg-primary-50/40 transition-colors text-left"
                  >
                    {p.images?.[0] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolveImageUrl(p.images[0])}
                        alt={p.name}
                        className="w-12 h-12 rounded object-cover bg-neutral-50 border border-neutral-200 shrink-0"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded bg-neutral-100 border border-neutral-200 flex items-center justify-center text-neutral-300 shrink-0">
                        <Package className="w-5 h-5" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-neutral-900 truncate">{p.name}</div>
                      <div className="text-xs text-neutral-400 mt-0.5 truncate">
                        {p.categoryName || '-'} · {p.skuCode || p.unit || '-'}
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-neutral-900 shrink-0">
                      ¥{Number(p.price ?? 0).toFixed(2)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* 客户选择弹窗（#3102）：选已有客户 → 回填收货信息；未命中可关闭后手动输入 */}
      <Modal
        open={customerModalOpen}
        onClose={() => setCustomerModalOpen(false)}
        title="选择客户"
        width={560}
        footer={
          <Button variant="secondary" onClick={() => setCustomerModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索客户姓名 / 手机号"
              value={customerKeyword}
              onChange={(e) => setCustomerKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchCustomers()}
            />
            <Button onClick={searchCustomers} loading={customerSearchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[380px] overflow-y-auto -mx-2 px-2">
            {customerSearchLoading ? (
              <p className="text-center text-neutral-400 py-8 text-sm">加载中…</p>
            ) : customerResults.length === 0 ? (
              <p className="text-center text-neutral-400 py-8 text-sm">
                {customerKeyword ? '未找到相关客户，可关闭后手动填写收货信息' : '暂无可选客户'}
              </p>
            ) : (
              <div className="space-y-2">
                {customerResults.map((c) => {
                  const name = c.wechatNickname || c.name || c.nickname || '未命名客户'
                  const region = [c.regionProvince, c.regionCity, c.regionDistrict].filter(Boolean).join(' ')
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => handlePickCustomer(c)}
                      className="flex w-full items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-white hover:border-primary-400 hover:bg-primary-50/40 transition-colors text-left"
                    >
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-50 text-primary-600">
                        <User className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-neutral-900 truncate">{name}</div>
                        <div className="text-xs text-neutral-400 mt-0.5 flex items-center gap-3">
                          {c.phone && (
                            <span className="inline-flex items-center gap-1">
                              <Phone className="w-3 h-3" />
                              {c.phone}
                            </span>
                          )}
                          {region && (
                            <span className="inline-flex items-center gap-1 truncate">
                              <MapPin className="w-3 h-3 shrink-0" />
                              {region}
                            </span>
                          )}
                        </div>
                      </div>
                      {c.sourceChannel && (
                        <span className={`shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 ${FONT_PX_11} text-neutral-500`}>
                          {c.sourceChannel === 'wechat_mini' ? '小程序' : c.sourceChannel === 'h5' ? 'H5' : c.sourceChannel}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}
