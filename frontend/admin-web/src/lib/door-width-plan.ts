// case_ids: OR-040
/**
 * **门幅选择规则**（issue #4877）—— 在候选门幅里求「可行 / 不可行 + 哪个最省」，纯函数、无副作用。
 *
 * 用户 2026-09-21 裁定（逐字，全文见 issue #4877）：
 * - 「『**最优』= 可行集里取最小门幅（最省料），定宽买高则取分幅最少**，这个是最贴近实际的」
 * - 「**如果所有门幅都不满足，那必然走接高**」
 * - 「**顾客给的高都是成品高**」
 * - 「**默认都能倒幅**」（不需要「花型是否有方向」字段）
 * - 「**（门幅有效余量）有必要**」（判定用**有效门幅**，不是标称门幅）
 * - 「**加工类型是显式输入：定高买宽 + 高度超限 ⇒ 接高；倒幅只在显式选『定宽买高』时用
 *   （系统永不自己改判）**」
 * - 「**没有一个行业通用公式能替人拍板，能被机械化的只有「可行 / 不可行 + 哪个最省」**」
 *
 * ⚠️ **issue #5020 改判（覆盖上面第 6 条的「系统永不自己改判」）**：加工类型**缺失 ⇒ 自动推导**
 * （不再是 `undecidable`）—— 用户 2026-09-21 新口径：
 * ```
 * 定高买宽可行（成品高 + HEM_MARGIN ≤ 门幅有效值）⇒ 取**可行集里最小门幅**；加工类型 = 定高买宽
 * 否则                                            ⇒ **倒幅**（分幅最少；并列取较小门幅）；加工类型 = 定宽买高
 * 接高                                            ⇒ **不参与自动比较**（接高 = 上下拼接、横缝可见；
 *                                                    行业实践是超高窗走倒幅把竖缝藏进褶皱）
 * 人工覆盖：显式传 定高买宽 / 定宽买高 ⇒ 按所选走（显式「定高买宽」而高度超限 ⇒ needs_splice）
 * ```
 * 推导结果从 {@link SinglePanelPlan.effectiveCuttingMode} 带出；**表外取值仍 fail-closed**（不猜）。
 *
 * ## 判定（与真值源 `docs/curtain-fabric-quote-rules.md` §3 / 算料引擎同源）
 * ```
 * g_eff(g) = 标称门幅 − 有效余量（缩水/边损/对花回；缺省 0 —— 租户级配置键落地后接线）
 * 定高买宽: 可行 = { g | 成品高 + HEM_MARGIN ≤ g_eff(g) }
 *           空 ⇒ needs_splice（缺口 = 成品高 + HEM_MARGIN − max(g_eff)）；非空 ⇒ 取 min(g_eff)
 * 定宽买高: 幅数 p(g) = ceil((成品宽 + SIDE_MARGIN) × 褶倍 ÷ g_eff(g))
 *           取 p 最小者；**并列取较小门幅**（不占宽幅布）
 * 加工类型缺失 ⇒ 按上表**自动推导**（#5020）；表外 ⇒ undecidable（fail-closed，不猜）
 * ```
 *
 * ⚠️ **为什么「取最小门幅」在定高买宽下不是省米数**：定高买宽的用料 `= (宽 + 余量) × 褶倍`
 * （韩褶为 `每折吃布 × 褶数 + 余量`）—— **与门幅无关**。取最小门幅省的是**宽幅布这个稀缺资源**
 * （留给真正超高的窗）＋ 可能的单价差。而定宽买高的用料 `= 幅数 × (成品高 + 卷边)`，
 * **门幅越大米数越省** ⇒ 「取分幅最少」＝米数最省。（两条方向相反、目标同一，别读成矛盾。）
 *
 * ⚠️ **自动推导为什么以「定高买宽是否可行」为**唯一**分岔**（#5020）：倒幅（定宽买高）几何上
 * **永远可行**（幅数必定 ≥ 1）⇒ 若按「谁更省」比，倒幅会与接高一起参与竞争；而接高的用料公式
 * **不在本模块**（属算料引擎 `curtain_calc.resolve_fabric_plan`）⇒ 这里只按「单幅能不能做」分岔，
 * **不实现第二份用料公式**，也**不让接高进入自动比较**。
 *
 * ⚠️ **余量常量复用**（`SIDE_MARGIN` 宽方向 / `HEM_MARGIN` 高方向，两者今天同值 0.3 但**语义不同**，
 * 不得混用，且副本有跨语言守卫）；加工类型常量同样复用 —— 本模块**不新造**第二份字面量。
 *
 * 🔴 **照实登记的偏差（§19.1，issue #5009 登记、本单不修）**：上面这两个常量是**引擎默认值**的
 * 前端副本，而 `side_margin` / `hem_margin` 自 #4976 包 1b 起**可配** ⇒ 商家把余量改掉后，
 * 本模块算出的**门幅可行集 / 分幅 / 「需接高」告警**仍按常量 0.3 算，与**服务端判定/算料口径
 * 可能不一致**。它**不进加工费组合键**（不改钱），但会**误导商家选门幅**。
 * 修它 = 改门幅建议 = 影响钱 ⇒ **需用户裁定 + 另开单**（不在 #5009 范围）。
 * 该偏差由 `tests/unit_ci_workflows/test_hem_margin_cross_language_drift.py` 的 C6
 * **消费方白名单**在结构上钉住：想扩大消费面必须显式改白名单 = 显式复核这条偏差。
 * ⚠️ **没有**「与租户配置一致」的判据（做不到：本模块不读配置）—— 只登记，无红证。
 *
 * ## 与算料引擎的关系（**过渡实现**，不是第二份长期口径）
 * 真值源 = `backend/ai-agent-service/app/tools/curtain_calc.py`。引擎今天**既不接收门幅
 * （`internal.py` 里是硬编码常量）、也不接收加工类型（按「成品高 + 卷边 ≤ 门幅」自推）**
 * ⇒ 规则暂时落不进引擎。用户 2026-09-21：「**web 端的功能根据这个最新方案现在开工落地，
 * 替换掉现在错误的做法**」⇒ 先在 admin-web 落地；**下沉/对齐 = issue #4652**（引擎接收门幅 +
 * 加工类型）—— 届时本模块应下沉为引擎函数，或降级为**有守卫的副本**（同 `craft-calc-request.ts`
 * 与常量副本的既有范式）。⚠️ 那时**不得**留下两份会各自漂移的判定。
 *
 * ## 本模块**不做**的事（照实登记，YAGNI）
 * - **不算用料米数**（用料由算料引擎给；本模块只回答「哪个门幅 + 单幅还是接高」）；
 * - **不看库存**：候选集由调用方给（物理可行 vs 当前可下单是两层，别把缺货读成「做不了」）；
 * - **不算接高的加高条米数**（接高用料口径**未裁定**，issue #4877 已登记为独立缺口）；
 * - **不做金额最优化**：目标函数 = 用料米数（裁定 3），单价差异只做提示。
 */
import {
  CUTTING_MODE_FIXED_HEIGHT,
  CUTTING_MODE_FIXED_WIDTH,
  HEM_MARGIN,
  SIDE_MARGIN,
  parseDoorWidth,
} from '@/lib/craft-auto-features'

/**
 * 候选门幅（米）—— 数字或 SKU 原值（`2.8米` 这类字符串走同一份解析）。
 * 允许 `null` / `undefined`（SKU 的 `doorWidth` 在商品模型里是**可选**字段）：
 * **解析不到即剔除**（不默认成任何值 —— 见 `normalizeCandidates`）。
 */
export type DoorWidthCandidate = number | string | null | undefined

/** 判不了的原因（**每一类都对应一个「本系统缺什么」**，不许静默挑一个默认值顶上） */
export type CutPlanUndecidableCode =
  | 'missing-cutting-mode'
  | 'no-door-width'
  | 'missing-size'
  | 'missing-fullness'

export interface CutPlanInput {
  /** 成品宽（米）—— 缺失 ⇒ 定宽买高判不了（定高买宽不需要宽） */
  width?: number | null
  /** 成品高（米）—— **顾客给的尺寸直接就是成品高**（裁定：不做离地/轨道/挂钩换算） */
  height?: number | null
  /**
   * 加工类型（`定高买宽` / `定宽买高`）—— **可选**（issue #5020）。
   *
   * 缺失 ⇒ **自动推导**（定高买宽可行 ⇒ 定高买宽；否则 ⇒ 定宽买高/倒幅），推导结果从
   * {@link EffectiveCuttingMode} 带出；**显式传入 ⇒ 按所选走**（人工覆盖，含「显式定高买宽
   * 而高度超限 ⇒ `needs_splice`」）；**表外取值 ⇒ 仍 fail-closed**（`undecidable`，不猜）。
   */
  cuttingMode?: string | null
  /** 候选门幅集（同商品同颜色、同售卖方式；是否按库存过滤由调用方决定） */
  candidates: readonly DoorWidthCandidate[]
  /** 褶倍（定宽买高的分幅数需要；缺失 ⇒ undecidable，**不拿假褶倍判价**） */
  fullness?: number | null
  /** 开数（需接片数 = 开数；缺省 1 = 单开） */
  openCount?: number
  /** 门幅有效余量（米）：缩水 / 边损 / 对花回；缺省 `0`（不配 ⇒ 与标称同值） */
  allowance?: number
}

/**
 * **实际据以求解的加工类型**（issue #5020）—— `single_panel` / `needs_splice` 上**恒非空**：
 * 显式传入 ⇒ 逐字回带；缺失 ⇒ **自动推导出的那一档**（定高买宽可行 ⇒ 定高买宽；否则 ⇒ 定宽买高）。
 *
 * ⚠️ 调用方读它、**不要**读 `input.cuttingMode`：后者在「未指定」时是 `undefined`，拿它做判断
 * 会把自动解当成「没判」。
 */
export type EffectiveCuttingMode =
  | typeof CUTTING_MODE_FIXED_HEIGHT
  | typeof CUTTING_MODE_FIXED_WIDTH

export interface SinglePanelPlan {
  state: 'single_panel'
  /** **实际据以求解的**加工类型（issue #5020：显式传入 ⇒ 逐字回带；缺失 ⇒ 自动推导值） */
  effectiveCuttingMode: EffectiveCuttingMode
  /** 选中的**标称**门幅（米） */
  doorWidth: number
  /** 选中门幅的**有效**门幅（标称 − 有效余量） */
  effectiveDoorWidth: number
  /** 定高买宽恒 1（单幅）；定宽买高为分幅数 */
  panels: number
  reason: string
}

export interface NeedsSplicePlan {
  state: 'needs_splice'
  /** **实际据以求解的**加工类型（接高只在**显式** `定高买宽` 下出现 ⇒ 恒为 `定高买宽`） */
  effectiveCuttingMode: EffectiveCuttingMode
  /** 候选里最宽的**标称**门幅（缺口以它为基准算） */
  widestDoorWidth: number
  widestEffectiveDoorWidth: number
  /** 缺口高度（米）= 成品高 + 卷边 − 最宽有效门幅（接高加高条的自然输入） */
  gapMeters: number
  /** 需接片数 = 开数（每片都要接一条） */
  panelCount: number
  reason: string
}

export interface UndecidablePlan {
  state: 'undecidable'
  code: CutPlanUndecidableCode
  reason: string
}

export type CutPlan = SinglePanelPlan | NeedsSplicePlan | UndecidablePlan

/** 米数取整到毫米（只用于**文案与比较**；判定方向不取整） */
function round3(value: number): number {
  return Number(value.toFixed(3))
}

/** 有限正数 ⇒ 该数；其余（含 undefined / null / NaN / ≤0）⇒ null */
function positive(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number(String(value ?? '').trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/** 候选门幅：解析 + 去重 + 升序（解析不了的**直接丢弃**，不默认成任何值） */
function normalizeCandidates(candidates: readonly DoorWidthCandidate[]): number[] {
  const parsed = candidates.map((c) => (typeof c === 'number' ? positive(c) : parseDoorWidth(c)))
  return Array.from(new Set(parsed.filter((g): g is number => g !== null))).sort((a, b) => a - b)
}

/**
 * 求解：给定成品宽高、**显式**加工类型与候选门幅集 ⇒ 选中门幅 / 需接高 / 判不了。
 *
 * 返回的三态里**只有 `single_panel` 与 `needs_splice` 可以驱动界面**；`undecidable` 必须
 * 显式告知（缺门幅 ⇒ 提示补商品资料；缺加工类型/尺寸 ⇒ 让调用方去问），
 * **不得**回退任何缺省门幅继续推算（issue #4877 要替换掉的正是这个做法）。
 */
export function resolveCutPlan(input: CutPlanInput): CutPlan {
  const requested = input.cuttingMode
  // 表外取值（非空但不是两档之一）⇒ **仍 fail-closed**（#5020 只放宽「缺失」，不放宽「不认识」）。
  if (requested != null && requested !== '' && !isCuttingMode(requested)) {
    return {
      state: 'undecidable',
      code: 'missing-cutting-mode',
      reason: `加工类型「${requested}」不在表内（${CUTTING_MODE_FIXED_HEIGHT} / ${CUTTING_MODE_FIXED_WIDTH}）—— 不猜朝向`,
    }
  }

  const candidates = normalizeCandidates(input.candidates)
  if (candidates.length === 0) {
    return {
      state: 'undecidable',
      code: 'no-door-width',
      reason: '该规格没有可用门幅（SKU 未维护门幅）—— 不按缺省门幅推算',
    }
  }

  const allowance = Math.max(positive(input.allowance) ?? 0, 0)
  const effective = candidates.map((doorWidth) => ({
    doorWidth,
    effectiveDoorWidth: round3(doorWidth - allowance),
  }))

  const height = positive(input.height)
  const fixedHeightFeasible = (): boolean =>
    height !== null && effective.some((c) => round3(height + HEM_MARGIN) <= c.effectiveDoorWidth)

  /**
   * **加工类型缺失 ⇒ 自动推导**（issue #5020）：定高买宽可行 ⇒ 定高买宽；否则 ⇒ 定宽买高（倒幅）。
   * ⚠️ 接高**不参与**这个比较（口径见文件头）；缺成品高 ⇒ 两档都判不了 ⇒ `missing-size`。
   */
  const mode: EffectiveCuttingMode | null =
    requested != null && requested !== ''
      ? (requested as EffectiveCuttingMode)
      : height === null
        ? null
        : fixedHeightFeasible()
          ? CUTTING_MODE_FIXED_HEIGHT
          : CUTTING_MODE_FIXED_WIDTH
  if (mode === null) {
    return {
      state: 'undecidable',
      code: 'missing-size',
      reason: '缺成品高 —— 判不了「定高买宽是否可行」⇒ 也推导不出加工类型（不凭空挑一个朝向）',
    }
  }

  if (mode === CUTTING_MODE_FIXED_HEIGHT) {
    // ⚠️ 显式档也要在这里挡住缺高：**不能**让 `height!` 落到下面的算式（`null` 会算成 0）。
    if (height === null) {
      return { state: 'undecidable', code: 'missing-size', reason: '缺成品高 —— 判不了高度方向是否受门幅约束' }
    }
    const need = round3(height + HEM_MARGIN)
    const feasible = effective
      .filter((c) => need <= c.effectiveDoorWidth)
      .sort((a, b) => a.effectiveDoorWidth - b.effectiveDoorWidth)

    if (feasible.length > 0) {
      const chosen = feasible[0]
      return {
        state: 'single_panel',
        effectiveCuttingMode: CUTTING_MODE_FIXED_HEIGHT,
        doorWidth: chosen.doorWidth,
        effectiveDoorWidth: chosen.effectiveDoorWidth,
        panels: 1,
        reason:
          `成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ${need} 米 ≤ 门幅 ${chosen.doorWidth} 米` +
          `（有效 ${chosen.effectiveDoorWidth} 米）⇒ 单幅可做，取可行集里最小门幅`,
      }
    }

    const widest = effective.reduce((a, b) => (b.effectiveDoorWidth > a.effectiveDoorWidth ? b : a))
    const panelCount = Math.max(1, Math.trunc(positive(input.openCount) ?? 1))
    const gap = round3(need - widest.effectiveDoorWidth)
    return {
      state: 'needs_splice',
      effectiveCuttingMode: CUTTING_MODE_FIXED_HEIGHT,
      widestDoorWidth: widest.doorWidth,
      widestEffectiveDoorWidth: widest.effectiveDoorWidth,
      gapMeters: gap,
      panelCount,
      reason:
        `成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ${need} 米 > 最大门幅 ${widest.doorWidth} 米` +
        `（有效 ${widest.effectiveDoorWidth} 米）⇒ 没有任何门幅能单幅做成，走接高` +
        `（缺口 ${gap} 米 × ${panelCount} 片）；**不改成倒幅**（加工类型由人工显式选定，系统不改判）`,
    }
  }

  // 定宽买高（倒幅）：分幅数最少 ⇒ 米数最省；并列取较小门幅（不占宽幅布）。
  const width = positive(input.width)
  if (width === null) {
    return { state: 'undecidable', code: 'missing-size', reason: '缺成品宽 —— 算不出定宽买高的分幅数' }
  }
  const fullness = positive(input.fullness)
  if (fullness === null) {
    return {
      state: 'undecidable',
      code: 'missing-fullness',
      reason: '缺褶倍 —— 算不出分幅数（不拿一个假褶倍去判）',
    }
  }

  const need = (width + SIDE_MARGIN) * fullness
  const ranked = effective
    .map((c) => ({ ...c, panels: Math.max(1, Math.ceil(need / c.effectiveDoorWidth)) }))
    .sort((a, b) => a.panels - b.panels || a.effectiveDoorWidth - b.effectiveDoorWidth)
  const chosen = ranked[0]
  return {
    state: 'single_panel',
    effectiveCuttingMode: CUTTING_MODE_FIXED_WIDTH,
    doorWidth: chosen.doorWidth,
    effectiveDoorWidth: chosen.effectiveDoorWidth,
    panels: chosen.panels,
    reason:
      `成品宽 ${width} + 左右余量 ${SIDE_MARGIN} = ${round3(width + SIDE_MARGIN)} 米 × 褶倍 ${fullness}` +
      ` = ${round3(need)} 米 ÷ 门幅 ${chosen.doorWidth} 米（有效 ${chosen.effectiveDoorWidth} 米）` +
      ` ⇒ ${chosen.panels} 幅（取分幅最少；并列取较小门幅）`,
  }
}

/** 取值是否是表内两档之一（**只认这两档** —— 表外一律 fail-closed） */
function isCuttingMode(value: string): value is EffectiveCuttingMode {
  return value === CUTTING_MODE_FIXED_HEIGHT || value === CUTTING_MODE_FIXED_WIDTH
}

/** 客服所选门幅相对**规则解**的判定（用户 2026-09-21：「客服选了不是最省的门幅 ⇒ 提示可选最优」） */
export type DoorWidthChoiceVerdict =
  /** 就是规则解（或并列最优）⇒ **不提示**（不 nag） */
  | 'optimal'
  /** 可行但不是规则解 ⇒ 提示可换更省的门幅 */
  | 'suboptimal'
  /** **选的这个门幅单幅做不出**（定高买宽下高度超限）⇒ 比「非最优」更强的告警：需接高 */
  | 'infeasible'
  /** 判不了（未选门幅 / 门幅未维护 / 规则自身不可判定）⇒ 不提示最优 */
  | 'unknown'

export interface DoorWidthChoice {
  plan: CutPlan
  /** 客服所选门幅（解析不到 ⇒ `null` = 未选 / 未维护） */
  selectedDoorWidth: number | null
  verdict: DoorWidthChoiceVerdict
  /** 可执行建议（`suboptimal` / `infeasible` 时非空；其余 ⇒ `null`，界面不提示） */
  suggestion: string | null
}

/**
 * 客服所选门幅 ⇒ 相对规则解的判定与建议（issue #4877）。
 *
 * 三条边界（都有判据）：
 * ① **未选 / 未维护 / 规则不可判定 ⇒ `unknown`**（不提示「最优」—— 没有可比的对象）；
 * ② **所选门幅不可行 ⇒ `infeasible`**（比「非最优」更强：先告警「需接高」，再给规则解）；
 * ③ **并列最优不提示**：定宽买高下分幅数相同 = 米数相同 ⇒ 判 `optimal`（挑哪个门幅是库存/单价的事，
 *    系统不 nag）。
 */
export function judgeDoorWidthChoice(
  input: CutPlanInput,
  selectedDoorWidth?: DoorWidthCandidate | null,
): DoorWidthChoice {
  const plan = resolveCutPlan(input)
  const selected =
    typeof selectedDoorWidth === 'number' ? positive(selectedDoorWidth) : parseDoorWidth(selectedDoorWidth)
  if (plan.state === 'undecidable' || selected === null) {
    return { plan, selectedDoorWidth: selected, verdict: 'unknown', suggestion: null }
  }

  const allowance = Math.max(positive(input.allowance) ?? 0, 0)
  const selectedEffective = round3(selected - allowance)

  // 没有任何门幅能单幅做成 ⇒ 无论客服选了哪一个，结论都是「需接高」。
  if (plan.state === 'needs_splice') {
    return {
      plan,
      selectedDoorWidth: selected,
      verdict: 'infeasible',
      suggestion:
        `所选 ${selected} 米门幅单幅做不出成品高（需接高：缺口 ${plan.gapMeters} 米 × ${plan.panelCount} 片）` +
        ` —— 本单**没有任何门幅**能单幅做成（规则解同此结论）`,
    }
  }

  if (plan.doorWidth === selected) {
    return { plan, selectedDoorWidth: selected, verdict: 'optimal', suggestion: null }
  }

  const height = positive(input.height)
  const needHeight = height === null ? null : round3(height + HEM_MARGIN)

  // 定高买宽：规则解 = **可行集里最小门幅**（用料与门幅无关 ⇒ 取小 = 不占宽幅布 + 可能的单价差）
  // ⚠️ issue #5020：判据读**规则实际用的**加工类型（`plan.effectiveCuttingMode`），
  // **不是** `input.cuttingMode` —— 后者在「未指定」时是 `undefined`，会把自动解读成「不是定高买宽」。
  if (plan.effectiveCuttingMode === CUTTING_MODE_FIXED_HEIGHT) {
    if (needHeight !== null && needHeight > selectedEffective) {
      return {
        plan,
        selectedDoorWidth: selected,
        verdict: 'infeasible',
        suggestion:
          `所选 ${selected} 米门幅单幅做不出（成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ${needHeight} 米，` +
          `缺口 ${round3(needHeight - selectedEffective)} 米 ⇒ **需接高**）；规则解 = ${plan.doorWidth} 米门幅`,
      }
    }
    return {
      plan,
      selectedDoorWidth: selected,
      verdict: 'suboptimal',
      suggestion:
        `规则解是 ${plan.doorWidth} 米门幅（可行集里最小：成品高 ${height} + 上下卷边 ${HEM_MARGIN} = ` +
        `${needHeight} 米 ≤ ${plan.doorWidth} 米）—— 换它可少占宽幅布（宽幅布留给真正超高的窗）`,
    }
  }

  // 定宽买高：规则解 = **分幅最少**（门幅越大 ⇒ 幅数越少 ⇒ 米数越省）⇒ 多出的每幅都是真金白银
  const width = positive(input.width)
  const fullness = positive(input.fullness)
  if (width === null || fullness === null) {
    return { plan, selectedDoorWidth: selected, verdict: 'unknown', suggestion: null }
  }
  const need = (width + SIDE_MARGIN) * fullness
  const selectedPanels = Math.max(1, Math.ceil(need / selectedEffective))
  if (selectedPanels <= plan.panels) {
    // 并列（分幅数相同 ⇒ 米数相同）：挑哪个门幅是库存/单价的事，不 nag。
    return { plan, selectedDoorWidth: selected, verdict: 'optimal', suggestion: null }
  }
  const perPanel = round3((height ?? 0) + HEM_MARGIN)
  return {
    plan,
    selectedDoorWidth: selected,
    verdict: 'suboptimal',
    suggestion:
      `所选 ${selected} 米门幅要 ${selectedPanels} 幅；规则解 ${plan.doorWidth} 米只要 ${plan.panels} 幅` +
      `（少 ${selectedPanels - plan.panels} 幅 × 每幅 ${perPanel} 米用料）`,
  }
}
