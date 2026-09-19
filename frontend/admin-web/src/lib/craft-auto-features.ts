/**
 * 下单页**自动识别**（issue #4526 包 B · 设计文档 §5.1 / §5.2 / §9 判据 8）—— 纯函数，无副作用。
 *
 * 用户 2026-09-19：「**超高 / 超宽是和门幅标准比较的**，客户报的数据和门幅对比后能
 * **自动区分**出来是超高还是超宽，**这个要求做到自动识别**」。
 *
 * ⚠️ **`定型` 不在自动识别里**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项
 * 来勾选」）：它是**手选**加工项，勾选态即 `isShaped`。本模块只推导
 * 与门幅比较的超高/超宽 + 由加工类型推导的倒幅/正幅。
 *
 * ⚠️ **本文件是 admin-web 专属**，刻意**不放进** `lib/craft-display.ts`：那个文件在
 * admin-web / mini-app / bmini-app **三端逐字同源**（设计 §4.9「一份 spec，三处渲染」，
 * 当前三份 sha 全等、**尚无同步守卫** = 既有 issue #4393）。把下单页的**取价推导**塞进去
 * 会静默破坏那个不变量（将来做「三端同步」的人会被带偏）；而且自动识别是**取价逻辑**，
 * 不是**展示**逻辑，本就不属于那个文件（YAGNI：另两端今天不用它）。
 */

/**
 * 卷边常量（米）= 算料引擎 `curtain_calc.py` 的 `HEM_MARGIN`（**副本**）。
 *
 * 同步守卫 = `tests/unit/lib/craft-auto-features.test.ts`（逐值读 Python 源比对，漂移即红）——
 * 本仓「副本必须有同步守卫」纪律的落点（同族 #4393 / `PLEAT_FABRIC_PER_FOLD`）。
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
 * ⚠️ `定型` **不在**本清单里（issue #4566，用户 2026-09-19 裁定）：它是**手选**加工项
 * （ERP 91 项加工费名单里的特征词），其勾选态就是 `isShaped` 的真值来源 —— 与
 * 「按宽高 vs 门幅推导」的超高/超宽不是一类东西。
 */
export const AUTO_FEATURE_NAMES = ['超高', '超宽', '倒幅', '正幅'] as const

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
  /** 加工类型（定高买宽 / 定宽买高）；未指定 / 表外取值 ⇒ 不推导朝向 */
  cuttingMode?: string
}

/**
 * 自动识别（设计 §5.2 冻结规则）—— 纯函数，**不读任何全局状态**。
 *
 * 顺序 = `超宽 → 超高 → 倒幅/正幅`（与 ERP 组合名 `韩折+超宽+超高+定型` 同族；
 * 组合键归一化另有唯一实现，此处顺序只为展示稳定）。
 *
 * ⚠️ **`定型` 已移出**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项来勾选」）：
 * 它现在是**手选**加工项（勾选态 = `isShaped`），不再由本函数推导 —— 自动推导的只有
 * 与门幅比较出来的超高/超宽，以及由 `cuttingMode` 推导的倒幅/正幅。
 */
export function detectAutoFeatures(input: AutoFeatureInput): AutoFeature[] {
  const features: AutoFeature[] = []
  const doorWidth = resolveDoorWidth(input.doorWidth)

  const width = positiveNumber(input.width)
  if (width !== null && roundMeters(width + HEM_MARGIN) > doorWidth) {
    features.push({
      name: '超宽',
      source: '推算',
      reason: `成品宽 ${width} + 卷边 ${HEM_MARGIN} = ${roundMeters(width + HEM_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  const height = positiveNumber(input.height)
  if (height !== null && roundMeters(height + HEM_MARGIN) > doorWidth) {
    features.push({
      name: '超高',
      source: '推算',
      reason: `成品高 ${height} + 卷边 ${HEM_MARGIN} = ${roundMeters(height + HEM_MARGIN)} 米 > 门幅 ${doorWidth} 米`,
    })
  }

  // 倒幅 / 正幅由 `cuttingMode` **唯一推导**（设计 §5.1）—— 设手选项 = 制造第二份冲突口径
  if (input.cuttingMode === '定宽买高') {
    features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
  } else if (input.cuttingMode === '定高买宽') {
    features.push({ name: '正幅', source: '推算', reason: '加工类型 = 定高买宽' })
  }

  return features
}

