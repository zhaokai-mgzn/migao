/**
 * 下单页**自动识别**的**前端半边**（issue #4526 包 B · 设计文档 §5.1 / §5.2 / §9 判据 8）。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」。
 *
 * ⚠️ **`定型` 不在自动识别里**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项
 * 来勾选」）：它是**手选**加工项，勾选态即 `isShaped`。本模块只承载与门幅比较的超高/超宽
 * + 由加工类型推导的**倒幅**。
 *
 * ⚠️ **`正幅` 不是自动推导特征**（issue #4592，用户 2026-09-19 裁定「窗帘默认都是正幅，
 * **正幅不用作为加工项的加项**，但是**倒幅是需要的**」）：推导出的特征会**进加工费
 * 组合键**（见 `orders/new/page.tsx::processingDetailsOf`），而 `正幅` **不在** `processing_items`
 * 目录里（V83 只种了 `超高`/`超宽`/`倒幅` 三项）⇒ 商家配不出含它的组合 ⇒ 组合键永远匹配不到价
 * ⇒ 加工费恒 ¥0.00（P0）。本清单因此与 V83 目录**逐值对齐**：`超高` / `超宽` / `倒幅`。
 *
 * ## 🔴 issue #5009 = #4976 包 2：**判定已移到服务端**，本文件不再判价
 *
 * 用户 2026-09-21 裁定 **B「判定移到服务端」**（前端只展示服务端结论）。本文件里原先的
 * `detectAutoFeatures` / `detectAutoFeatureNotices` **已删除** —— 判定（含「为什么没判」的提示）
 * 的唯一实现在算料引擎 `backend/ai-agent-service/app/tools/curtain_calc.py` 的
 * `detect_auto_features` / `detect_auto_feature_notices`，由只读端点
 * `POST /api/admin/orders/auto-features` 暴露给下单页
 * （`lib/api.ts` 的 `craftCalcApi.autoFeatures`）。
 *
 * **为什么必须搬**（不是形态偏好）：`hem_margin` 自 #4976 包 1b 起**可配** —— 商家把「上下卷边」
 * 改成 0.5 后，引擎按 0.5 算料，而前端这份 `HEM_MARGIN`（0.3）副本仍按 0.3 判「超高」
 * ⇒ **同一张单两套结论、组合键配错价**（#4661 / #4746 同族）。
 *
 * ⚠️ **本文件仍保留两个余量常量**，但它们**不在取价路径上**：消费方只有 `lib/door-width-plan.ts`
 * 的**门幅规则/建议**（挑哪个 SKU 门幅、要不要接高）—— 那一面是**建议**、不进组合键。
 * 判价路径（组合键）已**没有**任何前端常量参与。守卫：
 * `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py`（按新职责改判）。
 */

/**
 * **宽方向**余量（米）= 算料引擎 `curtain_calc.py` 的 `SIDE_MARGIN`
 * （`SIDE_MARGIN = 0.3  # 定高布：左右覆盖余量合计（各 15cm）`）—— 本文件是**副本**。
 *
 * ⚠️ 它**只**用于**宽**方向（`超宽`）；**高**方向必须用 {@link HEM_MARGIN}（issue #4661）：
 * 两者今天同值 0.3、**语义不同**（左右覆盖余量 ≠ 上下卷边），混用 = 与真值源口径脱钩。
 *
 * 🔴 **本副本有守卫**（issue #4656 收口，**漂移会被拦**）：
 * - `tests/unit/lib/craft-auto-features.test.ts` —— 前端腿，逐值读 Python 源比对（漂移即红）；
 * - `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py` —— Python 腿（独立 job），
 *   另钉**上面那行引文逐字一致**（注释里的值/语义也会腐烂，§19.2 ③）。
 *
 * ⚠️ **issue #5009 起消费方只剩门幅规则**（`lib/door-width-plan.ts`）：**取价路径不再读它**
 * （判定已移到服务端）。守卫 C6 的**消费方白名单**钉住这一点 —— 出现白名单外的消费方
 * （尤其 `orders/new/page.tsx` 的取价路径）⇒ 红。
 *
 * 🔴 **照实登记的边界（§19.1，本单不修）**：`door-width-plan.ts` 用这两个常量算
 * **门幅可行集 / 分幅 / 需接高**，而 `hem_margin` / `side_margin` 自 #4976 包 1b 起**可配**
 * ⇒ 商家把余量改掉后，**门幅建议与「需接高」告警**仍按常量 0.3 算，与引擎口径**可能不一致**。
 * 它不进组合键（不改钱），但会误导商家选门幅 ⇒ **需另开单**（修它 = 改门幅建议 = 影响钱）。
 * 该偏差由 C6 的**白名单**在结构上钉住（想扩大消费面必须显式改白名单 = 显式复核该偏差）。
 */
export const SIDE_MARGIN = 0.3

/**
 * **高方向**卷边（米）= 算料引擎 `curtain_calc.py` 的 `HEM_MARGIN`
 * （`HEM_MARGIN = 0.3  # 定宽布：上下卷边合计（脚位+止口）`）—— 本文件是**副本**。
 *
 * ⚠️ 它**只**用于**高**方向（`超高`）；**宽**方向必须用 {@link SIDE_MARGIN}（issue #4661）。
 *
 * 🔴 **本副本有守卫**（issue #4656 收口，**漂移会被拦**）：常量值与上面那行引文（值 + 语义注释）
 * 都由守卫逐值读 Python 源比对 ——
 * `tests/unit/lib/craft-auto-features.test.ts`（前端腿，漂移即红）+
 * `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py`（Python 腿，独立 job）。
 *
 * ⚠️ **issue #4976 包 1b 起引擎侧已可配**（`hem_margin` 进配置键）⇒ 本常量只代表**引擎默认值**，
 * 消费方（门幅规则）因此可能滞后于租户配置 —— **照实登记**（#4976 包 2 的边界），
 * 但**取价路径已与服务端同源**（判定走服务端、用租户配置）。
 */
export const HEM_MARGIN = 0.3

/**
 * ## 门幅口径（issue #4877 **改判：前端不再持有「缺省门幅」**）
 *
 * | 口径 | 值 | 来源 | 谁在读 |
 * |---|---|---|---|
 * | 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 本文件 {@link parseDoorWidth}、规则（`door-width-plan.ts`）、**判定（发给服务端）** |
 * | 引擎**试算**门幅 | **硬编码**（`backend/ai-agent-service/app/api/internal.py` 的 `_FABRIC_WIDTH`） | 算料试算通路 | **尚未按 SKU 门幅接线** = 分叉 #4652（判定通路已于 #5009 按 SKU 门幅接线） |
 *
 * 🔴 **「缺省门幅」已删除**（issue #4877；用户 2026-09-21 裁定「如果所有门幅都不满足，
 * 那必然走接高」+「加工类型是显式输入」）：SKU 未携带门幅 ⇒ {@link parseDoorWidth} 返回 `null`
 * ⇒ 页面把 `null` 发给服务端 ⇒ 服务端**不判**超宽/超高并回 `missing-door-width` 提示，
 * 页面**显式告知**商家 —— **不得**回退任何默认门幅继续推算。
 * 旧行为「静默按缺省门幅判超高/超宽」正是 #4877 要替换掉的错误做法（真单实测：同一张 3.0×2.75 的
 * 单子，门幅按 2.8 / 3.2 之差会得到「需接高」与「单幅可做」两种相反结论，用料 9.15 / 6.3 米）。
 *
 * ⇒ 本文件**刻意不抄**引擎的硬编码门幅值（抄一份 = 第二份会漂移的口径，同族 #4656）：
 * 守卫 `tests/unit_ci_workflows/test_fabric_width_truth_source.py`（前端出现该值字面量即红）。
 */

/**
 * **自动推导**特征名清单（**推导产生**，不是商家勾选项 —— 判据 8：出现手选项 ⇒ 红）。
 *
 * ⚠️ 单一真值：下单页用**本清单**把加工项目录里这几项**滤出**手选列表
 * （它们在目录里**必须存在** —— 商家配「加工费组合」时要能选到 `韩折+超高+定型` 这种名字，
 * 但下单页的手选控件必须没有它们）。**别在下单页再抄一份名字数组**。
 *
 * 🔴 **本清单必须与 `processing_items` 目录（V83）逐值对齐**（issue #4592，P0）：
 * 推导出的特征会**进加工费组合键**（`processingDetailsOf` 把它并进
 * `processingInfo.processingItems[]`，服务端 `ProcessingFeeQueryService.featureNames()` 只读这个数组），
 * 而商家只能在**目录已种**的项里配组合 ⇒ 清单里多出一个目录没有的名字
 * （`正幅`）⇒ **组合键永远匹配不到价** ⇒ 加工费恒 ¥0.00。
 * V83 已种的自动推导特征 = `超高` / `超宽` / `倒幅` **三项**，本清单与它**一一对应**。
 *
 * ⚠️ issue #5009 起本清单**还兼一个职责**：服务端返回的 `auto_features[].name` 必须落在本清单里
 * 才允许进组合键（服务端越界给一个目录里没有的名字 = 组合键恒匹配不到价 ⇒ 必须拦住）。
 */
export const AUTO_FEATURE_NAMES = ['超高', '超宽', '倒幅'] as const

/** 自动推导特征名（类型 = 上面清单的成员，**不另写一份联合类型**） */
export type AutoFeatureName = (typeof AUTO_FEATURE_NAMES)[number]

/** 一条自动识别特征（服务端产出；`source` 一律「推算」：推理非实证，照实标注） */
export interface AutoFeature {
  name: AutoFeatureName
  source: '推算'
  /** 可读依据（哪两个数比出来的）—— 商家要能核对判定。**由服务端产出，前端不编** */
  reason: string
}

/** 取有限正数（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/**
 * 门幅解析 —— 解析 SKU 的 `doorWidth`（可带单位，如 `2.8米`）。
 * 缺席 / 不可解析 / 非正数 ⇒ `null`（**不默认成任何值**）。
 *
 * ⚠️ **门幅选择规则必须用本函数**（`door-width-plan.ts`）；下单页也用它把该 SKU 的门幅
 * **发给服务端**做判定（`null` ⇒ 不传 ⇒ 服务端**不判**，见 #4877）。
 */
export function parseDoorWidth(doorWidth: unknown): number | null {
  if (doorWidth === null || doorWidth === undefined) return null
  const match = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!match) return null
  return positiveNumber(match[1])
}

/** 加工类型 `定高买宽` —— **高**方向受门幅约束（**宽**按米买、无上限）⇒ 只判 `超高` */
export const CUTTING_MODE_FIXED_HEIGHT = '定高买宽'
/** 加工类型 `定宽买高` —— **宽**方向受门幅约束（分幅数 = `(宽+余量)×褶倍 ÷ 门幅`）⇒ 只判 `超宽` */
export const CUTTING_MODE_FIXED_WIDTH = '定宽买高'

/**
 * 系统识别的**提示**（issue #4662；issue #5009 起**由服务端产出**）—— 只说明
 * 「**为什么没判**」或「**系统实际会按哪种算**」。
 *
 * **不是特征**：不进 `AUTO_FEATURE_NAMES`、不进加工费组合键、不影响判定结果
 * （组合键只能含 `processing_items` 目录里有的名字 —— #4592 的 P0）。
 *
 * ⚠️ **搬到服务端的理由**（issue #5009）：用户裁定 B 是「前端**只展示**服务端结论」，
 * 「为什么没判」属于判定面；且 `cutting-mode-conflict` 的依据里嵌着**上下卷边** ——
 * 留在前端的副本会在商家改 `hem_margin` 后**给商家看一个错的数**（0.3）。
 */
export interface AutoFeatureNotice {
  kind: AutoFeatureNoticeKind
  /** 可读依据（哪两个数比出来的 + 前提）。口径一律来自算料引擎的同款判据，**前端不编** */
  reason: string
}

/**
 * 提示类别清单（**单一真值**）—— 与引擎 `curtain_calc.AUTO_FEATURE_NOTICE_KINDS` 逐值一致
 * （由 `backend/ai-agent-service/tests/test_production/test_auto_features.py` 的
 * `TestMigrationEquivalenceNotices::test_notice_kinds_are_the_frozen_contract` 与前端腿共同钉住）。
 *
 * ⚠️ 下单页按 `kind` 分流渲染与过滤 ⇒ 服务端给一个表外的 `kind` 必须**被挡住**
 * （挡不住 = 静默渲染不出，商家看不见「这里本该判」）。
 */
export const AUTO_FEATURE_NOTICE_KINDS = [
  'missing-door-width',
  'missing-fullness',
  'cutting-mode-conflict',
] as const

/** 提示类别（类型 = 上面清单的成员，**不另写一份联合类型**） */
export type AutoFeatureNoticeKind = (typeof AUTO_FEATURE_NOTICE_KINDS)[number]
