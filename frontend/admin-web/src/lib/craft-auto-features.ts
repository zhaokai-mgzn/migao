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

/**
 * **门幅缺省值**（米）—— SKU 未携带 `doorWidth` 时本页按它推算。
 *
 * 🔴 **它不是前端自己编的数**（issue #4746）：缺省口径 = **算料引擎的默认门幅**
 * （`curtain_calc.build_quote(fabric_width: float = 2.8)`，米宝下单通路不传门幅时的值）
 * —— 逐值锚定见守卫 `tests/unit/lib/craft-auto-features.test.ts`（改一处必红）。
 *
 * ## 门幅三处口径（issue #4746，**核清后的结论**）
 *
 * | 口径 | 值 | 来源 | 谁在读 |
 * |---|---|---|---|
 * | 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 本页判定（{@link resolveDoorWidth}）、SKU 定位 / 加工费组合键 |
 * | 前端**缺省**门幅 | {@link DEFAULT_DOOR_WIDTH} = 2.8 | 算料引擎默认门幅（`build_quote` 的 `fabric_width` 默认值） | SKU 未携带门幅时的判定 |
 * | 引擎**端点**门幅 | 3.2 | `backend/ai-agent-service/app/api/internal.py::_FABRIC_WIDTH`（**硬编码**） | 商家手工下单页**试算通路** |
 *
 * ⚠️ **口径分裂（照实登记）**：引擎端点那个 3.2 的注释写着「商家手工下单页当前没有门幅字段」
 * —— **已过期**（商家侧有门幅：商品 `doorWidths` ⇒ `product_skus.door_width` ⇒ 下单页
 * `SKU.doorWidth`）。⇒ 同一张单：本页按 SKU 门幅（缺省 2.8）判「超宽/超高」并**进加工费组合键**，
 * 引擎按 3.2 算分幅 ⇒ **可能不一致**（组合键与实际算料对不上 ⇒ 报价/加工费对不上）。
 *
 * **权威 = SKU/商品门幅**（设计 §3.2「门幅 G = SKU.doorWidth（缺省 2.8 米）」+ 商家可配）；
 * 引擎侧改为**接收**该值是**分叉 #4652**（本单**不动 ai-agent**）。⇒ 本文件**刻意不抄** 3.2
 * （抄一份 = 第二份会漂移的口径，同族 #4656）：守卫
 * `tests/unit_ci_workflows/test_fabric_width_truth_source.py`（前端出现该值字面量即红）。
 */
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
 * 判定文案里的米数：取整到毫米；**只有「取整把严格大于抹平了」这一种情况**才照实给全精度
 * （如 `(1.1 + 0.3) × 2 = 2.8000000000000003`）—— 否则商家看到的是
 * 「2.8 米 > 门幅 2.8 米」这种**自相矛盾的依据**（判据要能自证）。
 *
 * ⚠️ 判据本身**不做取整**（与算料引擎一致，见 {@link detectAutoFeatures}）：引擎的分幅条件是
 * `ceil((宽 + side_margin) × 褶倍 ÷ 门幅) ≥ 2`，即**原始浮点**的 `乘积 > 门幅`
 * —— 实测 `宽 1.1 × 褶倍 2.0 ÷ 门幅 2.8`：引擎 `panels = 2`（米数翻倍），
 * 而「先取整到毫米再比」会判「不超宽」⇒ **漏报**（正是本单要消灭的那种脱钩）。
 */
function metersForReason(value: number, doorWidth: number): number | string {
  const rounded = roundMeters(value)
  return rounded > doorWidth || value <= doorWidth ? rounded : String(value)
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
  /**
   * **褶倍（倍数）**—— 宽方向**分幅**的乘数（issue #4662，用户 2026-09-20 裁定 A）。
   *
   * 与算料引擎 `curtain_calc.py` 的定宽买高分支
   * `panels = math.ceil((window_width + cfg["side_margin"]) * fullness / fabric_width)`
   * 里的 `fullness` **同一个数**：判据 = `(宽 + SIDE_MARGIN) × 褶倍 > 门幅`
   * （**这才是真正多花钱的地方** —— 分幅）。
   *
   * ⚠️ 缺失 / 非正数 ⇒ **不判超宽**（不猜：宁可漏判并在界面说明，也不拿一个假褶倍去判价）；
   * 「为什么没判」由 {@link detectAutoFeatureNotices} 给出（界面可见，不静默）。
   */
  fullness?: number | null
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
 * | `定宽买高` | ✅（`(宽 + SIDE_MARGIN) × 褶倍 > 门幅`；**褶倍缺失 ⇒ 不判**）| ❌ | ✅ |
 * | 缺失 / 表外取值 | ❌ | ❌ | ❌（保守：**不猜**朝向）|
 *
 * ⚠️ **「超宽」判据含褶倍**（issue #4662，用户 2026-09-20 裁定 A「含褶倍，与算料引擎一致」）：
 * 只比 `宽 + SIDE_MARGIN > 门幅` 会**漏报韩褶大窗**（1.5 宽 × 2.0 倍 = 3.6 米要分 2 幅，
 * 而 1.8 ≤ 2.8 判「不超宽」）—— 分幅才是多花钱的地方。褶倍缺失 / 非正 ⇒ **不判超宽**
 * （不猜），并由 {@link detectAutoFeatureNotices} 显式说明。
 *
 * ⚠️ **几何矛盾**（商家选的档位 vs 引擎按几何实际算的档位）不在本函数里 —— 见
 * {@link detectAutoFeatureNotices}：推算**以商家选的为准**（用户 2026-09-20 裁定 C），
 * 矛盾只**提示**、不改变推算结果。
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

  // 宽方向（只属 `定宽买高`）：判据 = 算料引擎的**分幅**条件
  // `ceil((宽 + side_margin) × 褶倍 ÷ 门幅) ≥ 2` ⟺ `(宽 + side_margin) × 褶倍 > 门幅`（#4662）。
  // 余量 = 左右覆盖余量 `SIDE_MARGIN`（与真值源分幅数公式同常量）；褶倍缺失 ⇒ 不判（不猜）。
  const width = positiveNumber(input.width)
  const fullness = positiveNumber(input.fullness)
  if (
    mode === CUTTING_MODE_FIXED_WIDTH &&
    width !== null &&
    fullness !== null &&
    // ⚠️ **不取整**：与引擎逐字同源（`ceil(乘积 ÷ 门幅) ≥ 2` ⟺ 原始浮点的 `乘积 > 门幅`）
    (width + SIDE_MARGIN) * fullness > doorWidth
  ) {
    features.push({
      name: '超宽',
      source: '推算',
      reason:
        `成品宽 ${width} + 左右余量 ${SIDE_MARGIN} = ${roundMeters(width + SIDE_MARGIN)} 米` +
        ` × 褶倍 ${fullness} = ${metersForReason((width + SIDE_MARGIN) * fullness, doorWidth)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  // 高方向（只属 `定高买宽`）：余量 = 上下卷边 `HEM_MARGIN`（与真值源可用条件同常量）
  // ⚠️ **不取整**：引擎的定高可用条件是 `window_height + HEM_MARGIN <= fabric_width`（原始浮点）——
  // 取整会让「成品高 2.5001」这类输入在前端判「不超高」而引擎实际回落定宽（静默不一致）。
  const height = positiveNumber(input.height)
  if (mode === CUTTING_MODE_FIXED_HEIGHT && height !== null && height + HEM_MARGIN > doorWidth) {
    features.push({
      name: '超高',
      source: '推算',
      reason: `成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ${metersForReason(height + HEM_MARGIN, doorWidth)} 米 > 门幅 ${doorWidth} 米`,
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

/**
 * 系统识别的**提示**（issue #4662）—— 只说明「**为什么没判**」或「**系统实际会按哪种算**」，
 * **不是特征**：不进 `AUTO_FEATURE_NAMES`、不进加工费组合键、不影响
 * {@link detectAutoFeatures} 的推算结果（组合键只能含 `processing_items` 目录里有的名字 —— #4592 的 P0）。
 */
export interface AutoFeatureNotice {
  kind: 'missing-fullness' | 'cutting-mode-conflict'
  /** 可读依据（哪两个数比出来的 + 前提）。口径一律来自算料引擎的同款判据，**前端不编** */
  reason: string
}

/**
 * 该行需要**显式告知商家**的两件事（issue #4662）—— 纯函数，与 {@link detectAutoFeatures} 同源同入参。
 *
 * ① `missing-fullness`：**褶倍缺失 ⇒ 未判超宽**（用户裁定 A 的口径）。不猜一个褶倍去判价，
 *    但也**不静默** —— 商家看得见「这里本该判、因为缺褶倍没判」。
 * ② `cutting-mode-conflict`：**几何矛盾**（用户 2026-09-20 裁定 C「以商家选的为准，
 *    几何矛盾时显式提示」）。真值源 = 算料引擎 `curtain_calc.py` 的**几何分支**：
 *    `if window_height + HEM_MARGIN <= fabric_width:` ⇒ 定高买宽，否则 ⇒ 定宽买高 + 告警
 *    （「成品高 … 超过门幅 … 的定高上限，已按定宽布（买高）计算」）。
 *    ⚠️ 引擎**不接收**商家的 `cuttingMode`（`calculate_fabric_meters` 按几何分支，`internal.py`
 *    的算料入参里没有该键）⇒ 两者**可能不一致** ⇒ 不一致时必须说出来，否则「前端推算」与
 *    「引擎实际计算」**静默不一致**（商家以为按定高买宽做，实际按定宽买高分幅）。
 *    🔴 **但「引擎实际会按哪种算」这句话在 issue #4746 下说过头了**：引擎的 `fabric_width` 是
 *    `internal.py::_FABRIC_WIDTH` **硬编码 3.2**（不是本 SKU 门幅）⇒ 拿本 SKU 门幅算出来的
 *    「系统实际会按 X 算」**可能说错**。⇒ 前提句只声明「**本页按本 SKU 门幅判**」（与
 *    {@link detectAutoFeatures} 同源），并**显式登记**「引擎试算门幅尚未接线」（分叉 #4652）；
 *    真正把两边合一要在 ai-agent 侧接线（本单不动）。
 *
 * ⚠️ 两条提示都**不改变推算**：特征仍按商家选的 `cuttingMode` 分流（裁定 C 的前半句）。
 * ⚠️ 依据缺失（高未知 / 加工类型缺失或表外）⇒ **不提示**（没有依据就不下结论，不猜）。
 */
export function detectAutoFeatureNotices(input: AutoFeatureInput): AutoFeatureNotice[] {
  const notices: AutoFeatureNotice[] = []
  const mode = input.cuttingMode
  if (mode !== CUTTING_MODE_FIXED_HEIGHT && mode !== CUTTING_MODE_FIXED_WIDTH) return notices

  const doorWidth = resolveDoorWidth(input.doorWidth)
  const width = positiveNumber(input.width)
  const height = positiveNumber(input.height)

  // ① 缺褶倍 ⇒ 未判超宽（只在「该方向真的受门幅约束」且宽已知时才说得通）
  if (mode === CUTTING_MODE_FIXED_WIDTH && width !== null && positiveNumber(input.fullness) === null) {
    notices.push({
      kind: 'missing-fullness',
      reason: `缺褶倍 ⇒ 未判超宽（成品宽 ${width} + 左右余量 ${SIDE_MARGIN} 是否要分幅取决于褶倍，不猜）`,
    })
  }

  // ② 几何矛盾：引擎按「高 + 上下卷边 vs 门幅」**唯一**决定实际档位（与上面 `超高` 同一条判据）
  if (height !== null) {
    const overHeight = height + HEM_MARGIN > doorWidth
    const actualMode = overHeight ? CUTTING_MODE_FIXED_WIDTH : CUTTING_MODE_FIXED_HEIGHT
    if (actualMode !== mode) {
      notices.push({
        kind: 'cutting-mode-conflict',
        reason:
          `加工类型选了「${mode}」，但成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ` +
          `${metersForReason(height + HEM_MARGIN, doorWidth)} 米 ${overHeight ? '超过' : '未超过'}本 SKU 门幅 ${doorWidth} 米` +
          // 🔴 issue #4746：**不再**声称「算料引擎按此判几何」—— 引擎按 `internal.py::_FABRIC_WIDTH`
          // 硬编码 3.2 试算，那句是对**引擎行为**的无据断言（前提句会说错 ⇒ 商家按提示做的决定是错的）。
          // 改后只声明**本页**按本 SKU 门幅判（判据仍是引擎的同一条几何分支），并把「引擎试算门幅
          // 尚未接线」显式登记出来（分叉 #4652）—— 前提句由本函数入参的**同一个门幅**导出，不自编。
          `（判据 = 算料引擎的几何分支「高 + 卷边 vs 门幅」，不读商家选的加工类型；本页按本 SKU 门幅判）` +
          `⇒ 按本 SKU 门幅口径，系统实际会按${actualMode}算` +
          `（⚠️ 引擎试算门幅尚未按本 SKU 门幅接线 —— #4746 / 待 #4652 ⇒ 引擎实际结果可能不同）`,
      })
    }
  }

  return notices
}

