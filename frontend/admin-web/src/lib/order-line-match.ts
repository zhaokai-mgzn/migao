/**
 * 订单侧「**明细条目 → 匹配候选 → 用户选品 → 建订单行**」（issue #5345）—— 纯函数，不碰 React、不发请求。
 *
 * ## 它补的是哪一段
 * 包 1（#5321）交付时登记的未实装项：识别到的**商品明细只进备注、不建订单行** ⇒ 商家仍要照着手打一遍。
 * 缺的链路是「识别 + 给候选 + **人选** + 建行」，**不是**「识别即建行」（那是猜商品）。
 *
 * ## 四条铁律（都有机械判据，见 `tests/unit/lib/order-line-match.test.ts`）
 * 1. 🔴 **不猜商品**：匹配不到 ⇒ 只剩「都不是」；未选 / 选「都不是」/ 选了**没给过该条目**的商品
 *    ⇒ **一行都不建**（`buildableChoices` 是唯一放行口，判据 1）。
 * 2. 🔴 **不落库**：本模块零写端点调用 —— 它只产出**订单行的补丁**，「提交」永远是人的动作（判据 4）。
 * 3. 🔴 **门幅（`fabric_width`）不在这里**：唯一来源是**所选 SKU** 的 `doorWidth`
 *    （页面经 `parseDoorWidth` 取后随试算下发，issue #4877/#5349）—— 本面出现门幅标识符即红（判据 5）。
 * 4. 🔴 **单价只来自目录 / SKU**：图上写的价（`priceHint`）只作**复核提示**展示，
 *    绝不进 `unitPrice`（判据 6）。
 *
 * ⚠️ **候选理由必须用户读得到**（判据 2）：相似度用「重合 N/M 字」这种可核对的说法，
 * 不写「AI 推荐」这类黑箱文案；规格 / 分类命中逐条列出。
 */
import type { RecognizedField } from './api'

/**
 * 建行面**消费**的识别字段键 —— 与识别内核 `backend/ai-agent-service/app/vision/targets.py`
 * 的 order 字段表逐字对齐（元守卫见测试文件的「类级元守卫」组：改名漂移 / 多读一个键 / 私吞
 * 价格·门幅类键 ⇒ 红）。
 */
export const LINE_PATH_FIELD_KEYS = {
  items: 'items',
  quantity: 'quantity',
} as const

/** 「都不是」的**选项 id**（与真商品 id 不可能撞：商品 id 是数字串 / uuid） */
export const NO_MATCH_CHOICE = '__none__'

/** 「都不是」的**用户可见文案**（判据 1：人永远有"都不对"这个出口） */
export const NO_MATCH_LABEL = '都不是'

/** 明细分隔符：识别内核把 `items` 定义成「商品名称清单，多个用顿号分隔」 */
const ENTRY_SPLIT = /[、，,;；\n]/
/** 图上写的价（`120元` / `120 块` / `120元/米`）—— **只作提示**，不进单价（判据 6） */
const PRICE_HINT = /(\d+(?:\.\d+)?)\s*(?:元|块)(?:\s*\/\s*(?:米|m|件|套|个|幅))?/
/** 带单位的量（`8米` / `2件`）—— 只用于**从匹配文本里剔除**，不用于逐条认数量 */
const QUANTITY_TOKEN = /(\d+(?:\.\d+)?)\s*(?:米|m|件|套|个|幅)/g
/** 候选条数上限（给用户挑的清单要短；排序见 `matchLineCandidates`） */
const CANDIDATE_LIMIT = 3

/** 取「有值」字段的值（空值 / 缺字段 ⇒ `''`；口径同 `image-recognize.ts`） */
function valueOf(fields: RecognizedField[], key: string): string {
  const hit = (fields || []).find((f) => f.key === key)
  return hit && typeof hit.value === 'string' ? hit.value.trim() : ''
}

/** 正数才收（`8米` / `8` ⇒ 8；`若干` / `0` ⇒ `null`：**不猜**） */
function positiveNumber(raw: string): number | null {
  const m = raw.match(/\d+(?:\.\d+)?/)
  if (!m) return null
  const value = Number(m[0])
  return Number.isFinite(value) && value > 0 ? value : null
}

/** 明细条目（**图上抄来的原文**）：名称 + 数量 + 图上写的价（提示用） */
export interface DetailEntry {
  /** 条目原文（一字不差，展示给商家核对） */
  name: string
  /** 数量：**只有整张图只有一条明细时**才敢认（多条明细 + 一个数量 = 无从对应 ⇒ `null`，不猜） */
  quantity: number | null
  /** 图上写的价（如 `120元`）—— **复核提示**，绝不进单价（判据 6） */
  priceHint: string | null
}

/**
 * 识别字段 ⇒ 明细条目（N 条 ⇒ N 个候选待选，判据 1）。
 *
 * ⚠️ 数量**不逐条猜**：多条明细时 `quantity` 一律为 `null`（⇒ 建行按 1，由商家在行上核对）。
 * 逐条从名称里抠数字看似聪明，但 `2.8米` 可能是宽、`8米` 可能是量、`120元` 是价 —— 认错就是钱错。
 */
export function parseDetailEntries(fields: RecognizedField[]): DetailEntry[] {
  const raw = valueOf(fields, 'items')
  if (raw === '') return []
  const names = raw
    .split(ENTRY_SPLIT)
    .map((s) => s.trim())
    .filter((s) => s !== '')
  if (names.length === 0) return []
  const quantity = names.length === 1 ? positiveNumber(valueOf(fields, 'quantity')) : null
  return names.map((name) => ({ name, quantity, priceHint: priceHintOf(name) }))
}

/** 条目原文里写的价（没有 ⇒ `null`，不编） */
export function priceHintOf(name: string): string | null {
  const m = name.match(PRICE_HINT)
  return m ? m[0] : null
}

/** 匹配用的文本：**剔除图上写的价与带单位的量**，只留名称本体（否则「120元米」也参与相似度） */
function matchText(name: string): string {
  return name
    .replace(PRICE_HINT, ' ')
    .replace(QUANTITY_TOKEN, ' ')
    .toLowerCase()
    .replace(/[^\u4e00-\u9fa5a-z0-9]/g, '')
}

/** 候选商品（结构最小面 —— 目录列表 / 商品详情都满足它，不绑死某个 DTO） */
export interface LineCatalogProduct {
  id: string
  name: string
  specifications?: Record<string, string>
  categoryName?: string
}

export interface LineCandidate {
  productId: string
  productName: string
  /** 排序分（越大越靠前）；「都不是」恒为 0 且排在末位 */
  score: number
  /** **用户读得到**的理由（判据 2）：名称相似度 + 规格 / 分类命中 */
  reason: string
}

/** 名称相似度：字符重合（Jaccard）—— 中文商品名没有空格可切词，重合率是商家能核对的说法 */
function nameSimilarity(a: string, b: string): { score: number; common: number; union: number } {
  const setA = new Set(a)
  const setB = new Set(b)
  let common = 0
  for (const ch of setA) if (setB.has(ch)) common += 1
  const union = setA.size + setB.size - common
  return { score: union === 0 ? 0 : common / union, common, union }
}

/** 规格 / 分类命中（条目名里出现了目录里登记的那个值 ⇒ 说明商家写的就是它） */
function specHits(entryName: string, product: LineCatalogProduct): string[] {
  const hits: string[] = []
  for (const [key, value] of Object.entries(product.specifications ?? {})) {
    const v = String(value ?? '').trim()
    if (v.length >= 2 && entryName.includes(v)) hits.push(`规格命中：${key}「${v}」`)
  }
  const category = String(product.categoryName ?? '').trim()
  if (category.length >= 2 && entryName.includes(category)) hits.push(`分类命中：${category}`)
  return hits
}

/**
 * 明细条目 ⇒ **匹配候选**（按分排序、附理由、最多 {@link CANDIDATE_LIMIT} 条）。
 *
 * 分 = 名称重合率 + 包含加成 + 规格/分类命中加成；**零重合 ⇒ 不给候选**（宁可少给，也不编）。
 * ⚠️ 这里**只排序 + 解释**，不替用户拍板 —— 选品是人的动作（判据 1/7）。
 */
export function matchLineCandidates(
  entry: DetailEntry,
  catalog: ReadonlyArray<LineCatalogProduct>,
): LineCandidate[] {
  const entryText = matchText(entry.name)
  const scored: LineCandidate[] = []
  for (const product of catalog || []) {
    const productText = matchText(product.name)
    if (entryText === '' || productText === '') continue
    const { score: similarity, common, union } = nameSimilarity(entryText, productText)
    const contained = entryText.includes(productText) || productText.includes(entryText)
    const hits = specHits(entry.name, product)
    const score = similarity + (contained ? 0.35 : 0) + hits.length * 0.2
    if (score <= 0) continue // 一个字都不重合 ⇒ **不给候选**（不硬凑）
    const similarityText = contained
      ? `名称包含「${product.name}」`
      : `名称相似：与「${product.name}」重合 ${common}/${union} 字`
    scored.push({
      productId: product.id,
      productName: product.name,
      score,
      reason: [`${similarityText}（重合 ${common}/${union} 字）`, ...hits].join('；'),
    })
  }
  return scored
    .sort(
      (a, b) =>
        b.score - a.score ||
        a.productName.localeCompare(b.productName) ||
        a.productId.localeCompare(b.productId),
    )
    .slice(0, CANDIDATE_LIMIT)
}

/** 「都不是」选项（**恒在末位**：匹不匹配得上都要给这个出口） */
export const NO_MATCH_OPTION: LineCandidate = {
  productId: NO_MATCH_CHOICE,
  productName: NO_MATCH_LABEL,
  score: 0,
  reason: '都不是 / 匹配不到 ⇒ 不建行（明细留在备注，可照旧手工选商品）',
}

/** 面板上真正渲染的选项 = 候选 + 「都不是」（顺序即显示顺序，判据 1） */
export function pickerOptionsFor(
  entry: DetailEntry,
  catalog: ReadonlyArray<LineCatalogProduct>,
): LineCandidate[] {
  return [...matchLineCandidates(entry, catalog), NO_MATCH_OPTION]
}

/** 用户在面板上做出的选择（`productId === NO_MATCH_CHOICE` ⇒ 明确放弃这条） */
export interface EntryChoice {
  entry: DetailEntry
  productId: string
}

/**
 * 选择集 ⇒ **可建的（条目, 商品）对** —— 建行的**唯一放行口**（判据 1/7）。
 *
 * 放行条件两条，缺一不可：
 * ① 不是「都不是」（用户没放弃）；
 * ② 该商品**在这一条目的候选里出现过**（页面不能替用户挑一个没给过他的商品 —— 那就是"猜商品"）。
 * ⚠️ 空选择集 ⇒ 空结果：**识别本身一行都不建**，建行必须经过「人选」这一步（判据 7）。
 */
export function buildableChoices(
  choices: ReadonlyArray<EntryChoice>,
  catalog: ReadonlyArray<LineCatalogProduct>,
): { entry: DetailEntry; product: LineCatalogProduct }[] {
  const built: { entry: DetailEntry; product: LineCatalogProduct }[] = []
  for (const choice of choices || []) {
    if (choice.productId === NO_MATCH_CHOICE) continue
    const product = (catalog || []).find((p) => p.id === choice.productId)
    if (!product) continue
    const offered = matchLineCandidates(choice.entry, catalog).some(
      (c) => c.productId === product.id,
    )
    if (!offered) continue
    built.push({ entry: choice.entry, product })
  }
  return built
}

/** 订单行上的 SKU（结构最小面：页面本地的 `OrderProductSku` 与 `types.ProductSku` 都满足它） */
export interface RecognizedLineSku {
  id: string
  colorId: string
  doorWidth?: string
  price: number
  stock?: number
}

/**
 * 建行**补丁**（喂给 `{...createEmptyLineItem(), product: 详情, ...patch}`）。
 *
 * 🔴 两个"不在这里"是**有意**的（判据 5/6）：
 * - **门幅**不在这里 —— 唯一来源是 `selectedSku.doorWidth`（页面经 `parseDoorWidth` 取）；
 * - **单价**只来自 `selectedSku.price`；图上写的价只出现在 `priceHint`（提示用）。
 * ⚠️ **不猜规格**：只有**唯一**规格时才定下颜色 / 门幅（⇒ 单价才有真值）；
 * 多规格 ⇒ `selectedSku: null` + `unitPrice: 0` + `note` 让商家去选（与 #4877「没有缺省门幅」同口径）。
 */
export interface RecognizedLinePatch {
  quantity: number
  unitPrice: number
  selectedColorId: string | null
  selectedSku: RecognizedLineSku | null
  /** 来源标记（判据 3）：识别建的行 ≠ 手填的行 —— 徽标口径 = `[图片识别]` */
  recognizedLine: true
  /** 图上写的价（**复核提示**，不进 `unitPrice`） */
  priceHint: string | null
  /** 需要商家注意的一句话（多规格 / 数量未能逐条对应） */
  note: string | null
}

export function recognizedLinePatchOf(
  entry: DetailEntry,
  skus: ReadonlyArray<RecognizedLineSku> | null | undefined,
): RecognizedLinePatch {
  const available = skus ?? []
  const sku = available.length === 1 ? available[0] : null
  const notes: string[] = []
  if (available.length > 1) {
    notes.push(`该商品有 ${available.length} 个规格（颜色 × 门幅）⇒ 系统不猜，请在行上选规格`)
  } else if (available.length === 0) {
    notes.push('该商品没有可用规格（颜色 × 门幅）⇒ 请在行上先补规格')
  }
  if (entry.quantity === null) notes.push('数量按 1 建行（图上数量未能逐条对应）—— 请核对')
  return {
    // 数量：识别只提供输入，**不猜**（多条明细时 `entry.quantity` 为 null ⇒ 1）
    quantity: entry.quantity ?? 1,
    // 单价：**只来自所选 SKU**（判据 6）
    unitPrice: sku ? Number(sku.price) || 0 : 0,
    selectedColorId: sku ? sku.colorId : null,
    selectedSku: sku,
    recognizedLine: true,
    priceHint: entry.priceHint,
    note: notes.length > 0 ? notes.join('；') : null,
  }
}