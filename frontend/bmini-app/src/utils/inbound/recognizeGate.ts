/**
 * 识别结果的**门禁与前填口径**（issue #5052 P3；设计 §6.3 / §6.4）
 *
 * 服务端已经守住了两条红线（`WorkerInboundService.recognize`：零命中不建品、降级不预填）。
 * 前端这一层的职责是**不许在后面把它拆掉**：
 *
 * | 判据 | 端侧的坏形态（本模块要防的） |
 * |---|---|
 * | §6.3 零命中 ⇒ 拒绝入库、不自动建品 | 页面拿不到 `skuId` 却仍允许提交 ⇒ 或者更坏：**自己造一个产品** |
 * | §6.3 多命中 ⇒ 工人消歧 | 页面**替工人挑第一个**（"猜"就是这里发生的） |
 * | §6.4 不确定 ⇒ 不预填 | 页面把降级文案里的品名/色号塞进输入框，工人直接点确认 ⇒ 账上多一个假 SKU |
 *
 * ⚠️ 「不自动建品」在端侧是**结构事实**：本文件与 `services/workerInboundService.ts` 里
 * **不存在**任何建商品 / 建 SKU 的端点调用（守卫扫源码面；新增一个 ⇒ 红）。
 *
 * ⚠️ 数量口径**不在端侧重写**（照实登记）：真值 = 服务端 `InboundOrderService.requireItemNumbers`
 * （`> 0` 且最多 1 位小数，超 1 位**显式拒绝、不静默取整**）⇒ 端侧只做「填没填」这一层，
 * 数值判定与服务端 400 的文案**原样上屏**（理由见 `./truth` 文件头的 TS6059 实测）。
 */

/** 命中的既有 SKU（读面 = `WorkerInboundSkuMatch`） */
export interface SkuMatch {
  skuId: number
  productId?: string | null
  productName?: string | null
  skuCode?: string | null
  colorName?: string | null
  doorWidth?: string | null
  stock?: number | string | null
}

/** 零命中时给工人看的话（**可行动**：说清「系统不会自动建品」+ 三条出路） */
export const NO_SKU_MATCH_MESSAGE =
  '这个识别结果在系统里没有对应的货号/色号，不能入库（系统不会自动建品）。请核对标签是否拍清楚，或从已有商品里选一个，或让文员先建档。'

/** 多命中时给工人看的话（**不许替他猜**） */
export const AMBIGUOUS_SKU_MESSAGE = '识别到多个可能的货号/色号，请自己核对实物后选一个（系统不替你挑）。'

export type SkuGateOutcome =
  | { kind: 'matched'; match: SkuMatch }
  | { kind: 'ambiguous'; matches: SkuMatch[]; message: string }
  | { kind: 'none'; message: string }

/**
 * SKU 匹配门禁（§6.3）。
 *
 * - **1 条** ⇒ `matched`（可预选，但页面仍要让工人核对 —— 裁定 4「AI 识别 + 人工确认」）；
 * - **多条** ⇒ `ambiguous`（工人消歧；**服务端与前端都不许猜**）；
 * - **0 条** ⇒ `none`（拒绝入库；**不建品、不建 SKU、不落台账**）。
 */
export function evaluateSkuGate(matches: SkuMatch[] | null | undefined): SkuGateOutcome {
  const list = Array.isArray(matches) ? matches.filter((m) => m && m.skuId !== undefined && m.skuId !== null) : []
  if (list.length === 0) return { kind: 'none', message: NO_SKU_MATCH_MESSAGE }
  if (list.length === 1) return { kind: 'matched', match: list[0] }
  return { kind: 'ambiguous', matches: list, message: AMBIGUOUS_SKU_MESSAGE }
}

/** 服务端识别回执里本页用到的字段（其余原样透传，不在端侧重算） */
export interface RecognizeLike {
  path?: string | null
  degraded?: boolean | null
  requiresManualEntry?: boolean | null
  barcode?: string | null
  productName?: string | null
  colorName?: string | null
  quantityMeters?: string | null
  skuMatches?: SkuMatch[] | null
  message?: string | null
}

export interface PrefillResult {
  /** 是否**预填**了候选（false ⇒ 输入框留空，工人手输） */
  prefillUsed: boolean
  productName: string
  colorName: string
  quantity: string
  /** 给工人看的说明（永远非空：说清本次是「已预填，请核对」还是「不确定，请手输」） */
  notice: string
  gate: SkuGateOutcome
}

/**
 * 识别回执 ⇒ 表单初值（§6.4「不确定 = 不预填」）。
 *
 * 🔴 三条不预填的触发条件（任一命中 ⇒ **三个字段全部留空**，只保留条码原文给工人对照）：
 * ① `degraded`（vision 降级 / 一格都没认出来）；② `requiresManualEntry`；③ **SKU 零命中**。
 * 红证：让降级分支也预填 ⇒ 判据必红。
 */
export function prefillFromRecognize(response: RecognizeLike | null | undefined): PrefillResult {
  const res = response || {}
  const gate = evaluateSkuGate(res.skuMatches)
  const blank = (): PrefillResult => ({
    prefillUsed: false,
    productName: '',
    colorName: '',
    quantity: '',
    notice: String(res.message || '').trim() || '识别不确定，请手工录入品名、色号与米数（系统不猜、不编造）。',
    gate,
  })

  if (!res || res.degraded || res.requiresManualEntry || gate.kind === 'none') {
    return blank()
  }

  const match = gate.kind === 'matched' ? gate.match : null
  const productName = String(res.productName || match?.productName || '').trim()
  const colorName = String(res.colorName || match?.colorName || '').trim()
  const quantity = String(res.quantityMeters ?? '').trim()

  // 三格全空 = 没有可预填的内容 ⇒ 视作「不预填」（避免"预填了一个空表单"的假动作）
  if (!productName && !colorName && !quantity) return blank()

  return {
    prefillUsed: true,
    productName,
    colorName,
    quantity,
    notice:
      gate.kind === 'ambiguous'
        ? AMBIGUOUS_SKU_MESSAGE
        : String(res.message || '').trim() || '已按识别结果预填，请核对实物后确认。',
    gate,
  }
}

/** 建草稿前的端侧闸（服务端仍会独立校验一遍 —— 端侧只是别让用户白填） */
export interface DraftInput {
  productId?: string | null
  skuId?: number | null
  quantity?: string | number | null
  /** 工人是否已点过「我确认」（§6.5「不做免确认」） */
  confirmed?: boolean
}

export interface DraftCheck {
  ok: boolean
  message: string
}

/**
 * 建草稿的准入（**端侧只拦"结构上不可能成功"的那几种**）：
 * ① 必须已选**既有** SKU（零命中 ⇒ `evaluateSkuGate` 已拦；这里再兜一次结构性判断）；
 * ② 米数必须**填了**（数值口径由服务端判定，400 的文案原样上屏 —— 端侧不重写第二份口径）；
 * ③ 必须已人工确认（未确认 ⇒ 不提交；服务端另有 409）。
 */
export function checkDraftInput(input: DraftInput): DraftCheck {
  if (!input.productId || input.skuId === undefined || input.skuId === null) {
    return { ok: false, message: NO_SKU_MATCH_MESSAGE }
  }
  if (String(input.quantity ?? '').trim() === '') {
    return { ok: false, message: '请填写入库米数（数量按米记，服务端会校验「大于 0 且最多 1 位小数」）' }
  }
  if (!input.confirmed) {
    return { ok: false, message: '请先核对实物并勾选「我确认」后再提交（过账不可撤销）' }
  }
  return { ok: true, message: '' }
}
