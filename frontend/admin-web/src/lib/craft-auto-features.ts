/**
 * 下单页**自动识别**（issue #4526 包 B · 设计文档 §5.1 / §5.2 / §9 判据 8）—— 纯函数，无副作用。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」。
 *
 * ⚠️ **`定型` 不在自动识别里**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项
 * 来勾选」）：它是**手选**加工项，勾选态即 `isShaped`。本模块只推导
 * 与门幅比较的超高/超宽 + 由加工类型推导的**倒幅**。
 *
 * ⚠️ **`正幅` 不是自动推导特征**（issue #4592，用户 2026-09-19 裁定「窗帘默认都是正幅，
 * **正幅不用作为加工项的加项**，但是**倒幅是需要的**」）：本模块推导出的特征会**进加工费
 * 组合键**（见 `orders/new/page.tsx::processingDetailsOf`），而 `正幅` **不在** `processing_items`
 * 目录里（V83 只种了 `超高`/`超宽`/`倒幅` 三项）⇒ 商家配不出含它的组合 ⇒ 组合键永远匹配不到价
 * ⇒ 加工费恒 ¥0.00（P0）。本清单因此与 V83 目录**逐值对齐**：`超高` / `超宽` / `倒幅`。
 *
 * ⚠️ **本文件是 admin-web 专属**，刻意**不放进** `lib/craft-display.ts`：那个文件在
 * admin-web / mini-app / bmini-app **三端逐字同源**（设计 §4.9「一份 spec，三处渲染」，
 * 当前三份 sha 全等、**尚无同步守卫** = 既有 issue #4393）。把下单页的**取价推导**塞进去
 * 会静默破坏那个不变量（将来做「三端同步」的人会被带偏）；而且自动识别是**取价逻辑**，
 * 不是**展示**逻辑，本就不属于那个文件（YAGNI：另两端今天不用它）。
 */

/**
 * **宽方向**余量（米）= 算料引擎 `curtain_calc.py` 的 `SIDE_MARGIN`
 * （`SIDE_MARGIN = 0.3  # 定高布：左右覆盖余量合计（各 15cm）`）—— 本文件是**副本**。
 *
 * ⚠️ 它**只**用于**宽**方向（`超宽`）；**高**方向必须用 {@link HEM_MARGIN}（issue #4661）：
 * 两者今天同值 0.3、**语义不同**（左右覆盖余量 ≠ 上下卷边），混用 = 与真值源口径脱钩。
 *
 * 同步守卫 = `tests/unit/lib/craft-auto-features.test.ts`（逐值读 Python 源比对，漂移即红）——
 * 本仓「副本必须有同步守卫」纪律的落点（同族 #4393 / `PLEAT_FABRIC_PER_FOLD`）。
 * （副本**漂移机制**另见 issue #4656，不在本单。）
 */
export const SIDE_MARGIN = 0.3

/**
 * **高方向**卷边（米）= 算料引擎 `curtain_calc.py` 的 `HEM_MARGIN`
 * （`HEM_MARGIN = 0.3  # 定宽布：上下卷边合计（脚位+止口）`）—— 本文件是**副本**。
 *
 * ⚠️ 它**只**用于**高**方向（`超高`）；**宽**方向必须用 {@link SIDE_MARGIN}（issue #4661）。
 */
export const HEM_MARGIN = 0.3

/** 门幅缺省值（米）—— SKU 未携带 `doorWidth` 时的行业常态 */
export const DEFAULT_DOOR_WIDTH = 2.8

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
 * ⚠️ `正幅` **不在**本清单里（issue #4592，用户 2026-09-19 裁定「窗帘默认都是正幅，
 * **正幅不用作为加工项的加项**」）：默认加工类型就是 `定高买宽`（= 正幅）⇒ 若推导它，
 * **每一张默认订单**的组合键都会被它污染。`正幅` 既不在目录里、也不进组合键。
 *
 * ⚠️ `定型` **不在**本清单里（issue #4566，用户 2026-09-19 裁定）：它是**手选**加工项
 * （ERP 91 项加工费名单里的特征词），其勾选态就是 `isShaped` 的真值来源 —— 与
 * 「按宽高 vs 门幅推导」的超高/超宽不是一类东西。
 */
export const AUTO_FEATURE_NAMES = ['超高', '超宽', '倒幅'] as const

/** 自动推导特征名（类型 = 上面清单的成员，**不另写一份联合类型**） */
export type AutoFeatureName = (typeof AUTO_FEATURE_NAMES)[number]

/** 一条自动识别特征（`source` 一律「推算」：推理非实证，照实标注） */
export interface AutoFeature {
  name: AutoFeatureName
  source: '推算'
  /** 可读依据（哪两个数比出来的）—— 商家要能核对判定 */
  reason: string
}

/** 取有限正数（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/** 米数取整到毫米（判定文案用）—— 浮点加法会给出 `6.8999999999999995` 这类值，不能进判定文案 */
function roundMeters(value: number): number {
  return Number(value.toFixed(3))
}

/**
 * 门幅（米）—— 解析 SKU 的 `doorWidth`（可带单位，如 `2.8米`）。
 * 缺席 / 不可解析 / 非正数 ⇒ {@link DEFAULT_DOOR_WIDTH}（不判成 0，也不「不判定」）。
 */
export function resolveDoorWidth(doorWidth: unknown): number {
  if (doorWidth === null || doorWidth === undefined) return DEFAULT_DOOR_WIDTH
  const match = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!match) return DEFAULT_DOOR_WIDTH
  return positiveNumber(match[1]) ?? DEFAULT_DOOR_WIDTH
}

/** 一条自动识别特征入参（尺寸一律米；`doorWidth` 给原始值，本函数负责解析） */
export interface AutoFeatureInput {
  /** 成品宽（米）；缺失 / 非正数 ⇒ 不判超宽 */
  width?: number | null
  /** 成品高（米）；缺失 / 非正数 ⇒ 不判超高 */
  height?: number | null
  /** SKU 门幅（原样传入，本函数用 {@link resolveDoorWidth} 解析） */
  doorWidth?: unknown
  /**
   * 加工类型（`定高买宽` / `定宽买高`）—— **决定哪个方向受门幅约束**（issue #4661）：
   * `定高买宽` ⇒ 只判超高；`定宽买高` ⇒ 只判超宽（+ 倒幅）。
   * ⚠️ 缺失 / 表外取值 ⇒ **超宽与超高都不判**（保守，不猜朝向；`倒幅` 亦不推导）。
   */
  cuttingMode?: string
  // ⚠️ 待引入（**不在本单**，另单）：`fullness`（褶倍）—— 用户已裁定「超宽」应与算料引擎
  // 算分幅的口径一致（`(窗宽 + SIDE_MARGIN) × 褶倍 > 门幅`）。本对象是**可选字段集合** ⇒
  // 加 `fullness?: number | null` 属**加字段、不改现有字段语义**，调用方只需多传一个键。
  // 本单**刻意不实现**（签名与判据同时冻结，避免与在跑的页面包撞车）。
}

/** 加工类型 `定高买宽` —— **高**方向受门幅约束（**宽**按米买、无上限）⇒ 只判 `超高` */
const CUTTING_MODE_FIXED_HEIGHT = '定高买宽'
/** 加工类型 `定宽买高` —— **宽**方向受门幅约束（分幅数 = `(宽+余量)×褶倍 ÷ 门幅`）⇒ 只判 `超宽` */
const CUTTING_MODE_FIXED_WIDTH = '定宽买高'

/**
 * 自动识别（设计 §5.2 冻结规则；issue #4661 按加工类型分流）—— 纯函数，**不读任何全局状态**。
 *
 * 顺序 = `超宽 → 超高 → 倒幅`（与 ERP 组合名 `韩折+超宽+超高+定型` 同族；
 * 组合键归一化另有唯一实现，此处顺序只为展示稳定）。
 *
 * 🔴 **两个方向各自被门幅约束，取决于加工类型**（issue #4661，用户 2026-09-20 裁定
 * 「**定高买宽的话就不用算超宽，定宽买高就不用算超高**」）。真值源
 * `curtain_calc.py`：`定高买宽` ⇒ `M = (W + SIDE_MARGIN) × 褶倍`，**宽按米买无上限**、
 * 只有**高**受 `门幅` 约束（`高 + HEM_MARGIN ≤ 门幅` 才是可用条件）；`定宽买高` ⇒
 * `幅数 = ceil((W + SIDE_MARGIN) × 褶倍 / 门幅)`，**宽**受门幅约束。⇒ 判据表：
 *
 * | `cuttingMode` | 判超宽 | 判超高 | 判倒幅 |
 * |---|---|---|---|
 * | `定高买宽` | ❌ | ✅（`高 + HEM_MARGIN > 门幅`）| ❌ |
 * | `定宽买高` | ✅（`宽 + SIDE_MARGIN > 门幅`）| ❌ | ✅ |
 * | 缺失 / 表外取值 | ❌ | ❌ | ❌（保守：**不猜**朝向）|
 *
 * ⚠️ **常量按方向分开**：宽方向用 {@link SIDE_MARGIN}（左右覆盖余量）、高方向用
 * {@link HEM_MARGIN}（上下卷边）—— 今天同值 0.3、**语义不同**，不得混用。
 *
 * ⚠️ **`定型` 已移出**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项来勾选」）：
 * 它现在是**手选**加工项（勾选态 = `isShaped`），不再由本函数推导。
 *
 * 🔴 **`定高买宽` 不推导朝向特征**（issue #4592，P0）：它等于**正幅**（窗帘常态），
 * 而 `正幅` 不在 `processing_items` 目录（V83）里 ⇒ 推它就会让**默认订单**的组合键
 * 永远匹配不到价。用户裁定「正幅不用作为加工项的加项，但是倒幅是需要的」。
 */
export function detectAutoFeatures(input: AutoFeatureInput): AutoFeature[] {
  const features: AutoFeature[] = []
  const doorWidth = resolveDoorWidth(input.doorWidth)
  const mode = input.cuttingMode

  // 加工类型缺失 / 表外取值 ⇒ 两个方向**都不判**（保守，不猜）；`倒幅` 亦不推导。
  if (mode !== CUTTING_MODE_FIXED_HEIGHT && mode !== CUTTING_MODE_FIXED_WIDTH) return features

  // 宽方向（只属 `定宽买高`）：余量 = 左右覆盖余量 `SIDE_MARGIN`（与真值源分幅数公式同常量）
  const width = positiveNumber(input.width)
  if (mode === CUTTING_MODE_FIXED_WIDTH && width !== null && roundMeters(width + SIDE_MARGIN) > doorWidth) {
    features.push({
      name: '超宽',
      source: '推算',
      reason: `成品宽 ${width} + 左右余量 ${SIDE_MARGIN} = ${roundMeters(width + SIDE_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  // 高方向（只属 `定高买宽`）：余量 = 上下卷边 `HEM_MARGIN`（与真值源可用条件同常量）
  const height = positiveNumber(input.height)
  if (mode === CUTTING_MODE_FIXED_HEIGHT && height !== null && roundMeters(height + HEM_MARGIN) > doorWidth) {
    features.push({
      name: '超高',
      source: '推算',
      reason: `成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ${roundMeters(height + HEM_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  // **倒幅**由 `cuttingMode` 唯一推导（设计 §5.1）—— 设手选项 = 制造第二份冲突口径。
  // `定高买宽`（= **正幅**，也是缺省加工类型）**刻意不推导**（issue #4592，P0）：
  // `正幅` 不在 `processing_items` 目录（V83 只有 超高/超宽/倒幅）⇒ 推它 = 每张默认订单的
  // 组合键都带一个商家配不出的名字 ⇒ 组合价永远匹配不到 ⇒ 加工费恒 ¥0.00。
  if (mode === CUTTING_MODE_FIXED_WIDTH) {
    features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
  }

  return features
}

