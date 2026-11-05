/**
 * 下单页（`app/(dashboard)/orders/new/page.tsx`）的**共享形状** —— issue #8725 第一档切片产物。
 *
 * 单一职责：只声明类型 / 常量，**零实现**。切片前它们散在 6,913 行页面的第 139 行起，
 * 被下方每个单元同时引用（页面 / 算料层 / 展示层 / 四个表单组件）⇒ 单独收在这里才不会出现
 * 「同一个形状抄两份」。
 *
 * ⚠️ 搬运自 `orders/new/page.tsx`，**一行逻辑都没改**。改动会同时打穿
 * `tests/unit/pages/orders-new-slice-characterization.test.tsx` 的三层冻结判据。
 */
import { type AutoFeaturesResult, type CraftCalcResult, type DoorWidthPlanResult } from '@/lib/api'
import { type CraftPlanOverrides } from '@/lib/craft-calc-request'
import { type CraftSpecInput, type CurtainBody } from '@/lib/order-craft-fields'
import { type ProcessingItem, type Product } from '@/types'

export interface OrderProductSku {
  id: string
  productId?: string
  colorId: string
  colorName?: string
  doorWidth?: string
  price: number
  stock?: number
  skuCode?: string
}

export interface ProductDetail extends Omit<Product, 'skus'> {
  skus?: OrderProductSku[]
  basePrice?: number
}

export interface OrderLineItem {
  id: string
  /**
   * **商品组标识**（issue #4485）——同一块布（同一商品 / 颜色 / 门幅）下的多个**部位行**共用它。
   *
   * 为什么用「扁平数组 + 组标识」而不是嵌套结构：裁定 **R-a**「一行 `order_items` = 一个部位」
   * 是**落库**口径，提交与既有判据都按扁平数组走；分组**只是展示与编辑归属**
   * ⇒ 用组标识把「同一商品」标出来，渲染时分组，模型一字不改。
   */
  groupId: string
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: string | null
  selectedSku: OrderProductSku | null
  /**
   * **这个 SKU 是「规则自动选中」还是「客服手选」**（issue #4899）。
   *
   * 为什么必须有这一位：门幅规则的产品行为是「**不覆盖客服的手选**」——但**自动选中**若也算
   * 「已选」，规则就永远不再重算 ⇒ 尺寸 / 加工类型一变，页面会停在**旧门幅**上
   * （用户 2026-09-21 人工验证：「无法通过工艺&加工项选配反选最优的门幅 SKU」）。
   * ⇒ 自动选中的一律**可被规则改选**，手选的一律**不被覆盖**（只提示可换最优）。
   * ⚠️ 只活在**行状态**里，不进订单 payload。
   */
  skuAutoSelected: boolean
  /**
   * 售卖形态（issue #4493）——**商品组级**属性：同一块布按米卖还是做成帘。
   * 存在行上、由组级处理器在组内同步（与颜色 / 门幅同一机制）。
   */
  saleForm: SaleForm
  /**
   * **帘体**（issue #4521）—— 用户口径四类购买情况里的前三类：
   * `布帘` / `纱帘` —— **两者用料算法完全一致**（2026-09-21 用户裁定，见 `lib/craft-calc-request.ts`）。
   *
   * **组级**（与 `saleForm` 同一机制、组内同步）：一个商品组 = 一套帘 —— 改帘体不该只改一半
   * （主布行按公式算了料、纱帘行还留着）。
   */
  curtainBody: CurtainBody
  quantity: number
  unitPrice: number
  /**
   * **卷数**（整卷售卖，issue #5846，用户 2026-10-01 裁定 A）—— `null` = **留空**
   * ⇒ 这一对键都不进 payload，由服务端按货号卷长派生（与改造前的请求体逐字节相同）。
   *
   * ⚠️ 与 `product` 的关系：它**不是**从商品派生的显示值，是**用户录入的输入**
   * ⇒ 换商品时清回 `null`（旧商品的卷数不属于新商品），而 {@link rollLengthM} 会重新带出新商品的卷长。
   */
  rollCount: number | null
  /**
   * **每卷实际米数**（`order_items.roll_length_m` 的快照，issue #5846）——
   * 选商品时**默认带出** `products.roll_length_m`（未配 ⇒ `null`），可改成这一批的实际米数
   * （行业卷长是区间值：「一卷 60 米*左右*」）。
   */
  rollLengthM: number | null
  /**
   * 成品宽 / 高（米，**部位级**）—— issue #4420，用户 2026-09-19 裁定「宽高必填」。
   *
   * ⚠️ 归属层级：`position-instance-routing-model.md` §5.9.2 已裁定宽高是**部位级**
   * （一套「布 + 纱」的布帘与纱帘高度常不同，共用一行宽高必有一个部位的高度是错的）。
   * 本页一行 = 一个部位（裁定 R-a）⇒ 行级即部位级，语义一致。
   */
  width: number | null
  height: number | null
  /**
   * 这一行的宽 / 高是**图片识别预填**来的（issue #5349）—— 记的是**识别字段键**
   * （`curtain_width` / `curtain_height`），用来渲染 `[图片识别]` 徽标。
   *
   * ⚠️ 为什么落在**行状态**里（而不是页面级 `recognizedFields`）：那个清单是一屏多行共用的，
   * 拿它渲染宽高徽标 ⇒ **每一行**都会长出徽标，而识别只落在**一行**上（假标注比不标更糟：
   * 商家会去核对一个不是识别来的格子）。与 `openCountTouched` / `shapedItemTouched` 同族
   * ——留痕落在行状态里，收起/展开重挂不丢。
   */
  recognizedSizeKeys?: string[]
  /**
   * **识别来的工艺要求**（issue #5794）——展示用文本（如「打开方式 双开 · 款式 拼色 · 加工项 韩褶、定型」）。
   *
   * 为什么留痕：客户在图上写的要求**盖过系统默认**（默认双开 / 默认韩褶+定型都可能与客户要的相反），
   * 覆盖必须让商家看得见、对得上（用户口径「根据图中客户要求来决定……**不能选错**」）。
   */
  recognizedCraftText?: string
  /**
   * 这一行是**图片识别建出来的**（issue #5345）—— 驱动行上的 `[图片识别]` 徽标（判据 3）。
   *
   * ⚠️ 与 `recognizedSizeKeys` 分开：那是「宽高这两**格**是识别来的」，这是「这**一行**是识别人选建的」。
   * 手填的行没有这个键（`undefined`）⇒ 来源在数据上就分得开，不靠文案区分。
   */
  recognizedLine?: boolean
  /** 图上写的价（复核提示：**行价取自目录/SKU**，识别的价格不是真值 —— issue #5345 判据 6） */
  recognizedPriceHint?: string | null
  /** 建行时系统要商家注意的一句话（多规格 / 数量未逐条对应）—— **不猜**就摆到台面上 */
  recognizedNote?: string | null
  processingItems: ProcessingItem[]
  selectedProcessing: Record<string, { selected: boolean; qty: number }>
  /**
   * 商家**不采纳**的系统推算特征名（issue #4657）—— 推算结果会**进加工费组合键**
   * ⇒ 推算错 = 价格错，商家必须能纠正。缺省（`undefined`）= 全部采纳。
   */
  rejectedAutoFeatures?: string[]
  /**
   * 商家**强制加**的自动识别特征名（issue #4657）—— 系统没推、但商家知道该算
   * （例：SKU 没录门幅 ⇒ 系统按默认 2.8 米兜底 ⇒ 本该超宽却漏判）。
   */
  manualAutoFeatures?: string[]
  /** 工艺规格录入（issue #4375 §4.2/§4.5）—— 未填的键不落库；三条默认档见 createDefaultCraftSpec */
  craft: CraftSpecInput
  /**
   * **部位备注**（issue #5685）—— 商家自由文本，写「这个数字怎么来的」（算料依据的人工说明，
   * 例：`公式--48个折`）。**只活在行状态里**：落库载体是 `processingInfo.remark`（JSONB 顶层
   * 字符串，与 `craft` / `formula` 同层，见 `buildLineProcessingInfo`），**不开新列、不开新端点**。
   *
   * 缺值口径：空串 / 纯空白 ⇒ 视为未填 ⇒ **不落键**（写 `""` 会让下游多出一行空值）。
   * 上限 200 字符由录入控件 `maxLength` 挡住（服务端不截断、页面也不静默截断）。
   */
  remark?: string
  /**
   * **安装位置**（issue #7856）—— 件级（一行 = 一个部位 = 一扇窗）：这一扇窗装在那户人家的
   * 哪个空间（主卧 / 阳台 …）。**不是**部位 / 帘种（那个是 `curtainType`）。
   *
   * 落库载体 = `processingInfo.installRoom`（后端 `OrderCreateRequest.OrderItemRequest` 的
   * `processingInfo` 顶层键，与 `remark` 同一载体）—— **不是** item 一级字段（后端 DTO 没有它，
   * 放一级会被静默丢掉）。缺值 ⇒ **不落键**；上限 12 字由录入控件 `maxLength` 挡。
   * 选填：不阻塞提交。
   */
  installRoom?: string
  // ── 「套窗」输入已移除（issue #4486，用户裁定「我感觉不需要」）──
  // 代价已如实登记：商家手工路径不再能跨行绑套窗 ⇒ 布 + 纱会算成 2 套窗 ⇒ 套级工序
  // （外帘打卷/装袋/发货）各实例化 2 次（计件工资双付，约 ¥3/套）。见 issue #4486。
  // ⚠️ **底层机制保留**：`lib/order-craft-fields.ts` 的 `resolveWindowCraftLineIds` /
  // `buildWindowGroupKey` 与消费端 `ProcessingOrderService` 一字未动（API / Agent 仍可写该键）；
  // 且 **`craftLineId` 仍用于配布边配对**（§4.8 主布行 + 配布边行），见 `buildLineProcessingInfo`。
  /**
   * 配布边米数（§4.8）；`null` = 未改过 ⇒ 跟随主布米数
   */
  edgeMeters: number | null
  /** 配布边单价；`null` = 未填 ⇒ 不生成配布边明细行（后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  /**
   * **加工费就地改本单单价**（issue #4874 起「未配置」可改；🔴 issue #7642 起**已配置也可改**，
   * 用户 2026-10-24 逐字「新增订单中的加工费组合需要允许修改」）—— 元/米，`null` = 没改过。
   *
   * 只在**组合键非空**时可填；填了就：
   * ① 立刻以该价重发 `feePreview`（页面金额跟着变）② 随建单写进
   * `processingInfo.processingFeeOverride`（后端采用后 `fee_source='manual'`、金额 = 本单价 × 米数）。
   *
   * 🔴 **`0` 是一个有效值**（issue #7658，用户 2026-10-24：「在订单中改成 0 后，费用明细的展示费用
   * 未联动更改」）＝ **本单免加工费**（金额 ¥0.00，并当帧联动费用明细）。**`null`（空框）才表示
   * 「不改价、按组合价目」** —— 两者在数据上分得开：`null` ⇒ 不发该键；`0` ⇒ 发 0。
   *
   * ⚠️ **价目的命运分三种**（钱的边界，别混）：
   * - 组合**未配置** + 正价 ⇒ 建单成功后同步进「加工费组合」价目（#4872：商家自建价目的唯一通路）；
   * - 组合**已配置** ⇒ **只改本单**，价目那一份一字不动（#7642；后端在
   *   `processingFeeDetail.configured_unit_price` 里留下被覆盖的那条价目价，回写侧跳过）；
   * - **`0`** ⇒ 同样只改本单，且**永不回写**（否则一个免费单就把整条组合价清零 —— #7658）。
   *
   * ⚠️ 组合键为空（缺选配信息）⇒ **不给**改单价入口：没有 key 可落地，改了也无处可去。
   */
  processingFeeOverride: number | null
  /**
   * 商家**手改过**打开方式（issue #4493 的宽→开数联动）——落在**行状态**里，
   * 不放组件内 state（收起/展开重挂不丢）。手改过 ⇒ 改宽**不得覆盖**。
   */
  openCountTouched: boolean
  /**
   * 商家**手改过**是否定型（承接 #4489 的「手改留痕」纪律）—— 落在**行状态**里
   * （同 `openCountTouched`）。手改过 ⇒ 改帘体**不得覆盖**。
   *
   * ⚠️ issue #4566：定型已搬到**加工项** ⇒ 本标记跟踪的是「商家手动勾/取消过『定型』**加工项**」，
   * 而不是工艺规格里的某个字段（字段已随裁定退场）。
   */
  shapedItemTouched: boolean
  /**
   * 商家**手改过工艺项**（2026-09-28 下单页布局：工艺默认「韩褶」由系统**预选**）—— 落在**行状态**里
   * （同 `shapedItemTouched`，收起/展开重挂不丢）。
   *
   * 手改过（勾 / 取消 / 点「全不采纳」）⇒ 换商品 / 改帘体 / 目录到达**不得**再把推荐组合勾回来
   * （同 #4489 的「手改留痕」纪律）。**不是**第二个工艺真值：工艺的唯一派生点仍是
   * 「勾选的工艺项的 `craftHint`」（{@link craftFromItems}）。
   */
  craftItemTouched: boolean
  /**
   * 用料米数来源（真值源 §8：褶数/用料**必须带来源**，防多渠道不一致）—— issue #4434。
   * `公式计算` = 由算料引擎试算预填（宽/高/开数/拼次变化时自动重算）；
   * `人工指定` = 商家手改过 ⇒ **试算不得静默改回**（只有显式「恢复按公式计算」才切回）。
   */
  metersSource: string
  /**
   * 「人工指定」**生效时**的试算入参签名（issue #5202 · 根因 2）。
   *
   * 与**当前**签名不一致 ⇒ 说明商家手填的米数**没有跟随**这次改动（宽/高/门幅/工艺变了）。
   * 页面据此**显式告知**「已人工指定，未跟随」+ 一键恢复 —— **不得静默覆盖商家手填的数**
   * （真值源 §8：用料必须带来源），也**不得**让商家自己猜为什么数没变（用户第 8 点的病灶）。
   */
  metersManualSignature?: string
  /**
   * **人工加 / 改的推导项**（issue #5202 · 裁定 4/6）—— `undefined` = 没改过（由推导决定）。
   *
   * 一旦有值 ⇒ 随试算请求**显式下发**（契约 #5200 §四 R7：`auto=false`，**逐字采用**、不再自动改判）。
   * 与既有「手改留痕」纪律同族（`openCountTouched` / `shapedItemTouched` / `craft.cuttingMode` 的有无）。
   */
  planOverrides?: CraftPlanOverrides
  /**
   * 商家**不采纳**的「推导出的特殊选项」名（issue #5211）—— 记的是**选项名**（不是布尔位）：
   * 推导换成别的项（`拼2次` → `拼3次`）时，不对新的那一项继续生效（同 `rejectedAutoFeatures`）。
   *
   * 为什么不采纳必须有出口：这些项的下游是**工序插入 + 计件**（`拼2次` → 插 `拼2次-布`、计件
   * 0.8/1.2/1.6 元/幅；`接高` → 插 `接高-布`、计件 1.0 元/幅）⇒ 推导错 = 多插一道工序、多算工钱。
   */
  rejectedDerivedOptions?: string[]
  /**
   * 商家**手改过加工类型**（issue #5202 · 裁定 6）—— 落在**行状态**里（同 `openCountTouched` /
   * `shapedItemTouched`，收起/展开重挂不丢）。
   *
   * 为什么必须有一位：`createDefaultCraftSpec()` 也写 `craft.cuttingMode = 定高买宽`（默认档），
   * 只按「有值」判「人工覆盖」⇒ 默认档会**恒顶掉**服务端推导（三项输入收敛当场失效），
   * 而且 `data.plan.auto` 会永远显示「人工指定」（假话）。点过（含点「未指定」）⇒ 人工锁定，
   * 此后**不再被推导覆盖**。
   */
  cuttingModeTouched: boolean
  /** 最近一次算料试算结果（含**后端产出**的公式串）—— `null` = 还没算过 */
  calc: CraftCalcResult | null
  /** 试算失败原因（行内显式提示；**不退回任何估算值**） */
  calcError: string | null
  /**
   * 最近一次**自动特征判定**结果（issue #4976 包 2b）—— 判定来自**服务端**（用户裁定 B）。
   * `undefined` / `null` = **还没判**（提交闸门会拦，见 `autoFeaturesBlockReason`）。
   */
  autoFeatures?: AutoFeaturesResult | null
  /** 判定失败原因（行内显式提示；**不放行提交** —— 组合键少一项 = 钱会错） */
  autoFeaturesError?: string | null
  /**
   * 最近一次**门幅规则**结果（issue #5043 包 2b）—— 规则来自**服务端**（前端 `door-width-plan.ts` 退场）。
   * `undefined` / `null` = **还没算** ⇒ {@link cuttingModeOf} 返回 `undefined`（**不猜朝向**）。
   */
  doorWidthPlan?: DoorWidthPlanResult | null
  /** 规则失败原因（行内显式提示；**不回落任何本地规则**） */
  doorWidthPlanError?: string | null
}

/**
 * **售卖形态**（issue #4493，用户裁定）：同一块布既能**按米卖（布料）**、也能**做成帘（成品帘）**。
 *
 * - `布料` ⇒ **无加工**：不出现宽高 / 工艺规格 / 部位行 / 加工项 / 加工费，也不生成加工单；
 * - `成品帘` ⇒ 上述全有（宽高**必填**）。
 *
 * 默认 `成品帘`：与今天的行为一致（所有字段照旧出现）⇒ 不静默改变任何现有商家的下单形态。
 */
// 🔴 布料这个**字面量**的唯一真值源是 `@/lib/sale-form.ts`（issue #7320 立的展示侧唯一读点）
// ⇒ 这里只**转出**，不另写一份（同一取值两份定义 = 两份会漂的口径，
//   `tests/unit/lib/sale-form.test.ts` 的类级字面量守卫也会当场红）。
import { SALE_FORM_FABRIC } from '@/lib/sale-form'

export { SALE_FORM_FABRIC }

/** 另一个取值本就在下单页表单态：`成品帘`（没有第二处定义） */
export const SALE_FORM_FINISHED = '成品帘'

export type SaleForm = typeof SALE_FORM_FABRIC | typeof SALE_FORM_FINISHED

/**
 * **系统识别**块里的一行（issue #4657）：系统推算的（含被**不采纳**的，留痕要看得见）
 * 或商家**强制加**的。
 *
 * ⚠️ 不复用 lib 的 `AutoFeature`：那里 `source` 只可能是 `推算`（推导产生）；
 * 本行多了 `手动加`（商家强制加、系统没推）这一档 —— 它只在**页面侧**有意义。
 */
export interface SystemAutoFeatureRow {
  /**
   * 特征 / 加工项名 —— **不再是** `AutoFeatureName`（issue #5230）：这一块除了服务端推算的
   * 超高 / 超宽 / 倒幅与商家强制加的项，还要承载**派生加工项**「拼接」
   * （它不在 `AUTO_FEATURE_NAMES` 里 —— 那一份清单是**手选控件要滤掉**的名字，
   * 而拼接**必须留在手选列表**里：裁定 4「接高、拼接也允许人工加」）。
   */
  name: string
  source: '推算' | '手动加'
  reason: string
  /** 系统推算过、但被商家**不采纳** ⇒ **不在**生效值里（只作留痕展示） */
  rejected: boolean
}

/** 商家对系统推算的**裁决**（issue #4657）：`adopt` 恢复系统推算 · `reject` 不采纳 · `add` 强制加 */
export type AutoFeatureDecision = 'adopt' | 'reject' | 'add'

/** 一个**商品组**：同商品 / 同色 / 同门幅下的多个部位行（issue #4485） */
export interface ProductGroup {
  id: string
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: string | null
  selectedSku: OrderProductSku | null
  /** 售卖形态（issue #4493）：组级 —— 决定这一组下面出什么（布料 = 没有加工） */
  saleForm: SaleForm
  /** 帘体（issue #4521；**issue #4874 收窄为两档**：`布帘` / `纱帘`，`布帘+纱帘` 已删除） */
  curtainBody: CurtainBody
  lines: OrderLineItem[]
}
