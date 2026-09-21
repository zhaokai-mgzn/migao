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
 * 🔴 **本副本有守卫**（issue #4656 收口，**漂移会被拦**）：
 * - `tests/unit/lib/craft-auto-features.test.ts` —— 前端腿，逐值读 Python 源比对（漂移即红）；
 * - `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py` —— Python 腿（独立 job），
 *   另钉**上面那行引文逐字一致**（注释里的值/语义也会腐烂，§19.2 ③）。
 *
 * 本仓「副本必须有同步守卫」纪律的落点（同族 #4393 / `PLEAT_FABRIC_PER_FOLD`）。
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
 */
export const HEM_MARGIN = 0.3

/**
 * ## 门幅口径（issue #4877 **改判：前端不再持有「缺省门幅」**）
 *
 * | 口径 | 值 | 来源 | 谁在读 |
 * |---|---|---|---|
 * | 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 本页判定（{@link parseDoorWidth}）、规则（`door-width-plan.ts`）、SKU 定位 / 加工费组合键 |
 * | 引擎**端点**门幅 | **硬编码**（`backend/ai-agent-service/app/api/internal.py` 的 `_FABRIC_WIDTH`） | 算料试算通路 | **尚未按 SKU 门幅接线** = 分叉 #4652 |
 *
 * 🔴 **「缺省门幅」已删除**（issue #4877；用户 2026-09-21 裁定「如果所有门幅都不满足，
 * 那必然走接高」+「加工类型是显式输入」）：SKU 未携带门幅 ⇒ {@link parseDoorWidth} 返回 `null`
 * ⇒ 判定面**不判**并显式告知（`missing-door-width`）、规则面（`door-width-plan.ts` 的
 * `resolveCutPlan`）返回 `undecidable` —— **不得**回退任何默认门幅继续推算。
 * 旧行为「静默按缺省门幅判超高/超宽」正是本单要替换掉的错误做法（真单实测：同一张 3.0×2.75 的
 * 单子，门幅按 2.8 / 3.2 之差会得到「需接高」与「单幅可做」两种相反结论，用料 9.15 / 6.3 米）。
 *
 * ⚠️ **口径分裂照实登记**：引擎端点按它自己的硬编码值算分幅，本页按 **SKU 门幅** 判
 * ⇒ 两者可能不一致（组合键与实际算料对不上）。**权威 = SKU/商品门幅**；引擎侧改为**接收**该值
 * = **分叉 #4652**（本单不动 ai-agent）。⇒ 本文件**刻意不抄**那个值
 * （抄一份 = 第二份会漂移的口径，同族 #4656）：守卫
 * `tests/unit_ci_workflows/test_fabric_width_truth_source.py`（前端出现该值字面量即红）。
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
 * 门幅解析 —— 解析 SKU 的 `doorWidth`（可带单位，如 `2.8米`）。
 * 缺席 / 不可解析 / 非正数 ⇒ `null`（**不默认成任何值**）。
 *
 * ⚠️ **门幅选择规则必须用本函数**（`door-width-plan.ts`）：缺失 = **不可判定** ——
 * 「静默按缺省 2.8 推算」正是 issue #4877 要替换掉的错误做法。
 */
export function parseDoorWidth(doorWidth: unknown): number | null {
  if (doorWidth === null || doorWidth === undefined) return null
  const match = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!match) return null
  return positiveNumber(match[1])
}



/** 一条自动识别特征入参（尺寸一律米；`doorWidth` 给原始值，本函数负责解析） */
export interface AutoFeatureInput {
  /** 成品宽（米）；缺失 / 非正数 ⇒ 不判超宽 */
  width?: number | null
  /** 成品高（米）；缺失 / 非正数 ⇒ 不判超高 */
  height?: number | null
  /** SKU 门幅（原样传入，本函数用 {@link parseDoorWidth} 解析；解析不到 ⇒ **不判**，见 #4877） */
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
export const CUTTING_MODE_FIXED_HEIGHT = '定高买宽'
/** 加工类型 `定宽买高` —— **宽**方向受门幅约束（分幅数 = `(宽+余量)×褶倍 ÷ 门幅`）⇒ 只判 `超宽` */
export const CUTTING_MODE_FIXED_WIDTH = '定宽买高'

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
 *
 * 🔴🔴 **issue #4976 包 2b 起：本函数已不在「取价路径」上**（用户 2026-09-21 裁定 B
 * 「**判定移到服务端**」）—— 下单页的自动特征判定改由服务端
 * （`POST /api/admin/orders/auto-features` → 引擎 `curtain_calc.detect_auto_features`）给出，
 * 前端只**展示**服务端结论。⇒ **本函数不再被 `orders/new` 调用**（静态判据
 * `orders-new-auto-features.test.ts` 的「本页不得本地判特征」钉住），其单测保留只为
 * **钉住判据语义**（服务端实现与之同式，措辞逐字对齐）。
 *
 * 为什么必须搬：判定进**加工费组合键** ⇒ 判定即钱；而服务端判定用的是**该租户的配置**
 * （`side_margin` / `hem_margin` / 档位褶倍）与**该 SKU 的门幅**，前端只持常量副本
 * ⇒ 商家改过配置后两边会算出不同的键。
 *
 * ⚠️ **待收口（已登记在母单 #4976）**：本函数与它的单测可在后续小单里**整体删除**
 * （它已是「无人调用的第二份判据」）—— 本包不删是为了把「钱路径切换」与「删实现+改 46 条单测」
 * 分成两步，降低一次性改动面。
 */
export function detectAutoFeatures(input: AutoFeatureInput): AutoFeature[] {
  const features: AutoFeature[] = []
  const mode = input.cuttingMode

  // 加工类型缺失 / 表外取值 ⇒ 两个方向**都不判**（保守，不猜）；`倒幅` 亦不推导。
  if (mode !== CUTTING_MODE_FIXED_HEIGHT && mode !== CUTTING_MODE_FIXED_WIDTH) return features

  // 🔴 门幅缺失 / 不可解析 ⇒ **超高 / 超宽都不判**（issue #4877：**已无缺省门幅**）。
  // 「判不了」必须长得像「判不了」（由 {@link detectAutoFeatureNotices} 显式告知），
  // 不许拿一个默认门幅顶上 —— 真单实测：同一张 3.0×2.75 的单子，门幅按 2.8 / 3.2 之差
  // 会得到「需接高」与「单幅可做」两种相反结论。
  // ⚠️ **`倒幅` 照常推导**（见下）：它由**加工类型**唯一决定、与门幅无关 ——
  // 因为门幅缺数据就连它一起吞掉 = 静默少一个加工费组合键项（改钱），那不是「不猜」，是「漏判」。
  const doorWidth = parseDoorWidth(input.doorWidth)

  // 宽方向（只属 `定宽买高`）：判据 = 算料引擎的**分幅**条件
  // `ceil((宽 + side_margin) × 褶倍 ÷ 门幅) ≥ 2` ⟺ `(宽 + side_margin) × 褶倍 > 门幅`（#4662）。
  // 余量 = 左右覆盖余量 `SIDE_MARGIN`（与真值源分幅数公式同常量）；褶倍缺失 ⇒ 不判（不猜）。
  const width = positiveNumber(input.width)
  const fullness = positiveNumber(input.fullness)
  if (
    doorWidth !== null &&
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
  if (
    doorWidth !== null &&
    mode === CUTTING_MODE_FIXED_HEIGHT &&
    height !== null &&
    height + HEM_MARGIN > doorWidth
  ) {
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
  kind: 'missing-fullness' | 'cutting-mode-conflict' | 'missing-door-width'
  /** 可读依据（哪两个数比出来的 + 前提）。口径一律来自算料引擎的同款判据，**前端不编** */
  reason: string
}

/**
 * 该行需要**显式告知商家**的两件事（issue #4662）—— 纯函数。
 *
 * 🔴 **issue #4976 包 2b 起：本函数与「取价路径上的判定」已不是同一个来源** ——
 * 判定（进加工费组合键的那个）由**服务端**给（`POST /api/admin/orders/auto-features`
 * → 引擎 `curtain_calc.detect_auto_features`），而本函数仍在前端**本地**算，
 * **只为提示**（不进组合键、不改推算）。
 * ⇒ 两者**可能不同源**（服务端用**该租户配置**的余量/卷边与档位褶倍，本函数用模块常量副本）
 * —— 这是**已登记**的边界（母单 #4976：提示面未随判定一起搬）。
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
 *    本页的**服务端判定**同源），并**显式登记**「引擎试算门幅尚未接线」（分叉 #4652）；
 *    真正把两边合一要在 ai-agent 侧接线（本单不动）。
 *
 * ⚠️ 两条提示都**不改变推算**：特征仍按商家选的 `cuttingMode` 分流（裁定 C 的前半句）。
 * ⚠️ 依据缺失（高未知 / 加工类型缺失或表外）⇒ **不提示**（没有依据就不下结论，不猜）。
 */
export function detectAutoFeatureNotices(input: AutoFeatureInput): AutoFeatureNotice[] {
  const notices: AutoFeatureNotice[] = []
  const mode = input.cuttingMode
  if (mode !== CUTTING_MODE_FIXED_HEIGHT && mode !== CUTTING_MODE_FIXED_WIDTH) return notices

  // 🔴 门幅缺失 / 不可解析 ⇒ 判定面**什么都没判**（issue #4877）⇒ 显式告知并直接返回：
  // 再做「缺褶倍」「几何矛盾」两条提示会误导（它们的前提都依赖门幅）。
  const doorWidth = parseDoorWidth(input.doorWidth)
  if (doorWidth === null) {
    notices.push({
      kind: 'missing-door-width',
      reason: '该 SKU 未维护门幅 ⇒ 超高/超宽都判不了（系统不按缺省门幅推算，请先补商品门幅）',
    })
    return notices
  }
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

