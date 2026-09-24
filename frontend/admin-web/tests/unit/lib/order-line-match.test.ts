// case_ids: OR-008, OR-036
/**
 * 订单侧「**明细条目 → 匹配候选 → 用户选品 → 建订单行**」（issue #5345）。
 *
 * ## 它治什么
 * #5321（包 1）交付时登记的未实装项：订单侧识别到的**商品明细只进备注、不建订单行**
 * ⇒ 商家仍要照着手打一遍 ⇒ 图片建单在订单侧省得不多。本文件钉住那条链路的**纯函数半边**
 * （页面接线见 `tests/unit/pages/orders-new-image-lines.test.tsx`）。
 *
 * ## 七条判据（冻结判据逐条落成**可执行断言**，不是散文）
 * | 判据 | 断言 |
 * |---|---|
 * | 1 不猜商品 | 匹配不到 ⇒ 候选表只剩「都不是」；未选 / 选「都不是」/ 选了**不在该条目候选里**的商品 ⇒ **0 行**（+ 注入式红证） |
 * | 2 候选可解释 | 每个候选都带**用户读得到**的理由（名称相似度 + 规格 / 分类命中），非黑箱 |
 * | 3 来源可区分 | 识别建的行带 `recognizedLine` 标记（徽标口径 = `[图片识别]`），与手填行不同 |
 * | 4 🔴 不落库 | 建行面（纯函数 + 选品组件）**零写端点调用**（静态扫描 + 注入式红证） |
 * | 5 🔴 门幅来自所选 SKU | 建行补丁**不含**任何门幅字段；推导入参随 SKU 门幅变化（2.8→1.4）|
 * | 6 🔴 单价来自目录/SKU | 图上写了 `120元` ⇒ 行价仍是 SKU 价（+ 注入式红证） |
 * | 7 用户复核 | 没有任何路径能**不经用户选择**产出多行（选择集为空 ⇒ 0 行） |
 * | 类级（铁律 8） | 识别字段 ⇒ 建行面消费 的**接线登记表** + 钱/门幅类键的类级守卫（+ 注入式红证） |
 *
 * ⚠️ 判据 4/5 读的是**调用点 / 键集 / 字段**（结构化证据），**不读"文本里提到过"**
 * —— 注释里为了解释纪律写下端点名不算违规（`migao-dev-flow` §17.3「判据被自己的文案喂绿」）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  LINE_PATH_FIELD_KEYS,
  NO_MATCH_CHOICE,
  NO_MATCH_LABEL,
  buildableChoices,
  parseDetailEntries,
  pickerOptionsFor,
  recognizedLinePatchOf,
  type RecognizedLineSku,
} from '@/lib/order-line-match'
import { RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'
import { parseDoorWidth } from '@/lib/craft-auto-features'
import { craftCalcParamsOf, type CalcLineInput } from '@/lib/craft-calc-request'
import { createDefaultCraftSpec } from '@/lib/order-craft-fields'
import type { RecognizedField } from '@/lib/api'
import type { Product } from '@/types'

// ── 真值源（只读；取不到就**直接失败**，不静默跳过 —— 同 `craft-calc-defaults.test.ts`）──
/** 识别内核字段表（后端真值源）：字段键与「订单侧有哪些识别字段」的唯一权威 */
const TARGETS_PY = resolve(__dirname, '../../../../../backend/ai-agent-service/app/vision/targets.py')
/** 建行面（前端）：**glob 面** —— 新增识别/选品文件自动进扫描集，不需要登记 */
const LINE_MATCH_LIB = resolve(__dirname, '../../../src/lib/order-line-match.ts')
const RECOGNIZE_COMPONENTS = resolve(__dirname, '../../../src/components/image-recognize')
const ORDER_PAGE = resolve(__dirname, '../../../src/app/(dashboard)/orders/new/page.tsx')

const PY_SRC = readFileSync(TARGETS_PY, 'utf8')
const LIB_SRC = readFileSync(LINE_MATCH_LIB, 'utf8')
const PAGE_SRC = readFileSync(ORDER_PAGE, 'utf8')

/** 后端 `TARGET_FIELDS` 里 order 的字段键（正则只认 `TargetField("key", …)` 的**位置**证据） */
function orderTargetKeys(src: string): string[] {
  const block = src.match(/"order":\s*\(([\s\S]*?)\n    \),/)
  if (!block) throw new Error('targets.py 里读不到 target「order」的字段表（元守卫必须能读到真值）')
  return [...block[1].matchAll(/TargetField\(\s*"([^"]+)"/g)].map((m) => m[1])
}

/** 去掉 `/* … *​/` 与 `// …` —— 判据只认**代码**（注释里引用纪律不算违规） */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

// ── 夹具 ───────────────────────────────────────────────────────────────────
const TAG = RECOGNIZE_SOURCE_TAG

function field(key: string, value: string | null, label = key): RecognizedField {
  return { key, label, value, source: value ? TAG : null, reason: null }
}

/** 识别内核在订单侧的**真实产出形态**：`items` 是「商品名称清单，多个用顿号分隔」 */
function recognized(items: string, quantity: string | null = null): RecognizedField[] {
  return [field('items', items, '商品明细'), field('quantity', quantity, '数量')]
}

const CATALOG: Product[] = [
  {
    id: 'p1',
    name: '雪尼尔遮光窗帘',
    categoryId: 'c1',
    categoryName: '成品帘',
    price: 88,
    unit: '米',
    status: 'on_sale',
    images: [],
    specifications: { 材质: '雪尼尔' },
  },
  {
    id: 'p2',
    name: '棉麻窗帘',
    categoryId: 'c1',
    categoryName: '成品帘',
    price: 55,
    unit: '米',
    status: 'on_sale',
    images: [],
    specifications: { 材质: '棉麻' },
  },
]

function sku(id: string, doorWidth: string, price: number): RecognizedLineSku {
  return { id, colorId: `c-${id}`, doorWidth, price, stock: 10 }
}

const SPLIT_ENTRY = parseDetailEntries(recognized('雪尼尔遮光窗帘、棉麻窗帘'))[0]

/** 页面侧一行的**试算入参**装配（与 `orders/new/page.tsx::calcInputOf` 同一形状）——
 *  门幅**只**从 `selectedSku.doorWidth` 经唯一解析点 `parseDoorWidth` 取（issue #4877）。 */
function calcLineOf(patch: ReturnType<typeof recognizedLinePatchOf>): CalcLineInput {
  return {
    width: 2.8,
    height: 2.4,
    craft: createDefaultCraftSpec(),
    fabricWidth: parseDoorWidth(patch.selectedSku?.doorWidth),
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 判据 1 · 不猜商品：匹配不到 ⇒ 候选（含「都不是」）+ **不建行**
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 1 · 不猜商品：候选由人挑，「都不是」恒在，未选/不是就不建行 (#5345)', () => {
  it('明细条目按顿号拆开（不是把整串当一个商品名）', () => {
    const entries = parseDetailEntries(recognized('雪尼尔遮光窗帘、棉麻窗帘'))
    expect(entries.map((e) => e.name)).toEqual(['雪尼尔遮光窗帘', '棉麻窗帘'])
  })

  it('匹配不到 ⇒ 候选表**只剩「都不是」**（不是"没候选就不给选"）', () => {
    const entry = parseDetailEntries(recognized('完全不相干的型号 ZZ-9000'))[0]
    const options = pickerOptionsFor(entry, CATALOG)
    expect(options.map((o) => o.productId)).toEqual([NO_MATCH_CHOICE])
    expect(options[0].productName).toBe(NO_MATCH_LABEL)
    // 理由必须说清「为什么没给候选」与「接下来会怎样」
    expect(options[0].reason).toMatch(/不建行|留在备注/)
  })

  it('匹配得到 ⇒ 候选在前、「都不是」**恒在末位**（人永远有"都不对"这个出口）', () => {
    const options = pickerOptionsFor(SPLIT_ENTRY, CATALOG)
    expect(options.length).toBeGreaterThan(1)
    expect(options.at(-1)!.productId).toBe(NO_MATCH_CHOICE)
    expect(options.at(-1)!.productName).toBe(NO_MATCH_LABEL)
  })

  it('未选 / 选「都不是」/ 选了**不在该条目候选里**的商品 ⇒ 一行都不建', () => {
    const entry = parseDetailEntries(recognized('完全不相干的型号 ZZ-9000'))[0]
    // 未选（用户没动）
    expect(buildableChoices([], CATALOG)).toEqual([])
    // 选「都不是」
    expect(buildableChoices([{ entry, productId: NO_MATCH_CHOICE }], CATALOG)).toEqual([])
    // 选了一个**没给过该条目**的商品（比如从别处塞进来）⇒ 仍然不建（不猜、不放行）
    expect(buildableChoices([{ entry, productId: 'p1' }], CATALOG)).toEqual([])
  })

  it('注入式红证：去掉「候选里出现过」这一层 ⇒ 上面那条会当场红', () => {
    const entry = parseDetailEntries(recognized('完全不相干的型号 ZZ-9000'))[0]
    // 注入形态 = 只按"目录里有这个商品"放行（少了「它是不是该条目的候选」这一问）
    const naive = (choices: { entry: typeof entry; productId: string }[]) =>
      choices
        .filter((c) => c.productId !== NO_MATCH_CHOICE)
        .map((c) => CATALOG.find((p) => p.id === c.productId))
        .filter((p): p is Product => Boolean(p))
    expect(naive([{ entry, productId: 'p1' }])).toHaveLength(1) // 注入形态**真的**会建行
    expect(buildableChoices([{ entry, productId: 'p1' }], CATALOG)).toEqual([]) // 真实实现不会
  })

  it('被选中的商品 ⇒ 建行；选品是**人的动作**（空选择集 ⇒ 0 行，判据 7）', () => {
    const built = buildableChoices([{ entry: SPLIT_ENTRY, productId: 'p1' }], CATALOG)
    expect(built.map((b) => b.product.id)).toEqual(['p1'])
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 2 · 候选可解释（为什么给这几个，用户读得到）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 2 · 候选可解释：相似度 / 规格命中都摆在界面上 (#5345)', () => {
  it('每个候选都带非空理由，且理由里能读到「相似」与命中的规格', () => {
    const options = pickerOptionsFor(SPLIT_ENTRY, CATALOG).filter(
      (o) => o.productId !== NO_MATCH_CHOICE
    )
    expect(options.length).toBeGreaterThan(0)
    for (const option of options) {
      expect(option.reason.trim()).not.toBe('')
    }
    const top = options[0]
    expect(top.productId).toBe('p1') // 「雪尼尔遮光窗帘」逐字命中
    expect(top.reason).toMatch(/相似|重合|包含/)
    expect(top.reason).toMatch(/雪尼尔/) // 规格命中：材质
  })

  it('按分数从高到低（不是把目录原样倒给用户）', () => {
    const scores = pickerOptionsFor(SPLIT_ENTRY, CATALOG)
      .filter((o) => o.productId !== NO_MATCH_CHOICE)
      .map((o) => o.score)
    expect([...scores].sort((a, b) => b - a)).toEqual(scores)
  })

  it('注入式红证：理由若被清成空串 / 只回目录顺序 ⇒ 上面两条会红', () => {
    const withBlankReason = pickerOptionsFor(SPLIT_ENTRY, CATALOG).map((o) => ({ ...o, reason: '' }))
    expect(withBlankReason.some((o) => o.reason.trim() === '')).toBe(true)
    const unsorted = [...CATALOG].reverse().map((p) => ({ productId: p.id, score: 0 }))
    expect(unsorted[0].productId).toBe('p2') // 目录反序 ≠ 相似度序 ⇒ 判据有判别力
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 3 · 来源可区分（识别建的行 ≠ 手填的行）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 3 · 来源可区分：识别建的行带来源标记 (#5345)', () => {
  it('建行补丁带 `recognizedLine: true`，徽标口径沿用 `[图片识别]`', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s1', '2.8', 88)])
    expect(patch.recognizedLine).toBe(true)
    expect(TAG).toBe('[图片识别]')
  })

  it('识别建的行与手填的行**在数据上就不同**（不是靠文案区分）', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s1', '2.8', 88)])
    // 手填行（`createEmptyLineItem()` 的形态）没有这个键 ⇒ `undefined`
    const handFilled: { recognizedLine?: boolean } = {}
    expect(patch.recognizedLine).toBe(true)
    expect(handFilled.recognizedLine).toBeUndefined()
    expect(patch.recognizedLine).not.toBe(handFilled.recognizedLine)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 4 · 🔴 不落库（建行面零写端点）
// ══════════════════════════════════════════════════════════════════════════════
/** 建行面的所有文件（**glob 面**：新增识别/选品文件自动进扫描集） */
function lineFaceFiles(): string[] {
  const files = [LINE_MATCH_LIB]
  for (const name of readdirSync(RECOGNIZE_COMPONENTS)) {
    if (name.endsWith('.ts') || name.endsWith('.tsx')) files.push(resolve(RECOGNIZE_COMPONENTS, name))
  }
  return files
}

/**
 * 写端点痕迹 —— **结构化证据**（调用形态，不是"提到过"）：
 * 建行/建单/提交类端点的**语法绑定位置**。注释里为了解释「本面不落库」写下端点名 ⇒ 不算。
 */
function writeEvidence(src: string): string[] {
  const code = stripComments(src)
  const hits: string[] = []
  for (const m of code.matchAll(
    /(?:orderApi|productApi|customerApi|processingItemApi|request)\s*\.\s*(?:create\w*|update\w*|delete\w*|post|put|patch|delete)\s*\(/g
  )) {
    hits.push(m[0].replace(/\s+/g, ''))
  }
  if (/\.submit\s*\(/.test(code)) hits.push('.submit(')
  return hits
}

describe('判据 4 · 🔴 不落库：建行面只填订单行，提交永远是人的动作 (#5345)', () => {
  it('建行面（纯函数 + 识别/选品组件）零写端点调用', () => {
    const offenders = lineFaceFiles()
      .map((path) => ({ path: path.replace(resolve(__dirname, '../../..') + '/', ''), hits: writeEvidence(readFileSync(path, 'utf8')) }))
      .filter((r) => r.hits.length > 0)
    expect(offenders, `复制命令复现：grep -nE 'orderApi\\.(create|update)|request\\.(post|put)' <面内文件>`).toEqual([])
  })

  it('注入式红证：真写了端点调用 / 真提交了 ⇒ 扫描必须认出来', () => {
    expect(writeEvidence(`${LIB_SRC}\nconst r = await orderApi.createOrder(payload)\n`)).toEqual([
      'orderApi.createOrder(',
    ])
    expect(writeEvidence(`${LIB_SRC}\nawait form.submit()\n`)).toEqual(['.submit('])
    // 反向：注释里的端点名不得被当成违规（否则判据会被自己的文案喂红）
    expect(writeEvidence(`${LIB_SRC}\n// 本面不调用 orderApi.createOrder()，只回传补丁\n`)).toEqual([])
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 5 · 🔴 门幅（fabric_width）只来自**所选 SKU**
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 5 · 🔴 门幅来自所选 SKU：选品 ⇒ 推导链才拿到 fabric_width (#5345)', () => {
  it('建行补丁**不含**任何门幅字段（它不持有第二份门幅口径）', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s1', '2.8', 88)])
    const keys = Object.keys(patch)
    expect(keys).not.toContain('fabricWidth')
    expect(keys).not.toContain('fabric_width')
    expect(keys).not.toContain('doorWidth')
  })

  it('选品 ⇒ 推导入参拿到 fabric_width（= 所选 SKU 的门幅）', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s1', '2.8', 88)])
    expect(craftCalcParamsOf(calcLineOf(patch))?.fabric_width).toBe(2.8)
  })

  it('换一个门幅的 SKU ⇒ 推导值**跟着变**（证明它来自 SKU，不是写死的数）', () => {
    const wide = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s-wide', '2.8', 88)])
    const narrow = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s-narrow', '1.4', 55)])
    expect(craftCalcParamsOf(calcLineOf(wide))?.fabric_width).toBe(2.8)
    expect(craftCalcParamsOf(calcLineOf(narrow))?.fabric_width).toBe(1.4)
  })

  it('未选到唯一规格（多个规格 ⇒ 系统不猜）⇒ 推导链 fail-closed：**不发** fabric_width', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s1', '2.8', 88), sku('s2', '1.4', 55)])
    expect(patch.selectedSku).toBeNull()
    expect(craftCalcParamsOf(calcLineOf(patch))?.fabric_width).toBeUndefined()
  })

  it('注入式红证：把门幅塞成识别值 / 写死 ⇒ 上面「跟着 SKU 变」那条当场红', () => {
    const narrow = recognizedLinePatchOf(SPLIT_ENTRY, [sku('s-narrow', '1.4', 55)])
    // 注入形态 = 建行时就带一个门幅（识别来的 `door_width` 或写死 2.8）
    const injected: CalcLineInput = { ...calcLineOf(narrow), fabricWidth: 2.8 }
    expect(craftCalcParamsOf(injected)?.fabric_width).toBe(2.8)
    expect(craftCalcParamsOf(calcLineOf(narrow))?.fabric_width).toBe(1.4)
    expect(craftCalcParamsOf(injected)?.fabric_width).not.toBe(
      craftCalcParamsOf(calcLineOf(narrow))?.fabric_width
    )
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 6 · 🔴 单价只来自目录 / SKU（识别的价格不是真值）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 6 · 🔴 单价来自目录/SKU，不来自识别 (#5345)', () => {
  it('图上写了价 ⇒ 只作为**复核提示**留存，不进单价', () => {
    const entry = parseDetailEntries(recognized('雪尼尔遮光窗帘（120元/米）'))[0]
    expect(entry.priceHint).toContain('120')
    const patch = recognizedLinePatchOf(entry, [sku('s1', '2.8', 88)])
    expect(patch.unitPrice).toBe(88) // SKU 价
    expect(patch.priceHint).toContain('120') // 提示仍在（让商家能核对）
    expect(patch.unitPrice).not.toBe(120)
  })

  it('图上没写价 ⇒ `priceHint` 为 `null`（不编一个价出来）', () => {
    expect(parseDetailEntries(recognized('雪尼尔遮光窗帘'))[0].priceHint).toBeNull()
  })

  it('没有可用规格 ⇒ 单价为 0（**不猜价**），等商家选规格', () => {
    const patch = recognizedLinePatchOf(SPLIT_ENTRY, [])
    expect(patch.selectedSku).toBeNull()
    expect(patch.unitPrice).toBe(0)
  })

  it('注入式红证：改成用识别价 ⇒ 上面那条断言当场红（两个数不同 ⇒ 判据有判别力）', () => {
    const entry = parseDetailEntries(recognized('雪尼尔遮光窗帘（120元/米）'))[0]
    const recognizedPrice = Number(entry.priceHint!.match(/\d+(?:\.\d+)?/)![0])
    expect(recognizedPrice).toBe(120)
    expect(recognizedLinePatchOf(entry, [sku('s1', '2.8', 88)]).unitPrice).toBe(88)
    // 注入形态 = 优先用识别价
    const injected = { ...recognizedLinePatchOf(entry, [sku('s1', '2.8', 88)]), unitPrice: recognizedPrice }
    expect(injected.unitPrice).not.toBe(88)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 7 · 用户复核（不是"识别完直接落行"）
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 7 · 用户复核：建行必须经过「人选」这一动作 (#5345)', () => {
  it('选择集为空（用户什么都没点）⇒ 0 行（识别本身不产出行）', () => {
    const entries = parseDetailEntries(recognized('雪尼尔遮光窗帘、棉麻窗帘、纱帘'))
    expect(entries).toHaveLength(3)
    expect(buildableChoices([], CATALOG)).toEqual([])
  })

  it('页面把选择权交给用户：候选 + 「都不是」由页面渲染，建行只在选择回调里发生', () => {
    // 读的是**调用点**（位置证据），不是"文档里说会调用"
    expect(/pickerOptionsFor\s*\(/.test(PAGE_SRC)).toBe(true)
    expect(/buildableChoices\s*\(/.test(PAGE_SRC)).toBe(true)
    expect(/onPickEntry|handlePickEntry/.test(PAGE_SRC)).toBe(true)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 类级固化（`AGENTS.md` 铁律 8 / `migao-dev-flow` §23 G1~G2）
// ══════════════════════════════════════════════════════════════════════════════
/** 建行面**实际消费**的识别字段键 —— 从源码里**现取**（`valueOf(fields, 'key')` 的位置证据） */
function consumedKeysFromSource(src: string): string[] {
  return [...src.matchAll(/valueOf\(\s*fields\s*,\s*'([^']+)'/g)].map((m) => m[1])
}

/** 订单侧识别字段里**价格 / 门幅类**的键（钱面与门幅面的类级守卫口径） */
function priceLikeOrderKeys(src: string): string[] {
  return orderTargetKeys(src).filter((k) => /price|amount|money|fee|door_width|fabric_width/.test(k))
}

describe('类级元守卫：识别字段 ⇄ 建行面 的接线登记 (#5345 · 铁律 8)', () => {
  it('声明的建行面字段键必须都在后端 order 字段表里（两端改名漂移 ⇒ 红）', () => {
    const declared = new Set(Object.values(LINE_PATH_FIELD_KEYS))
    const keys = new Set(orderTargetKeys(PY_SRC))
    const phantom = [...declared].filter((k) => !keys.has(k))
    expect(phantom).toEqual([])
  })

  it('源码里**实际读取**的字段键 ⊆ 声明（偷偷多读一个键 ⇒ 红）', () => {
    const consumed = consumedKeysFromSource(stripComments(LIB_SRC))
    const declared = Object.values(LINE_PATH_FIELD_KEYS) as readonly string[]
    expect(consumed.filter((k) => !declared.includes(k))).toEqual([])
  })

  it('注入式红证：源码里多读一个未声明的键（如尺寸 / 价）⇒ 上面那条当场红', () => {
    const injected = `${LIB_SRC}\nconst w = valueOf(fields, 'curtain_width')\n`
    const consumed = consumedKeysFromSource(stripComments(injected))
    const declared = Object.values(LINE_PATH_FIELD_KEYS) as readonly string[]
    expect(consumed.filter((k) => !declared.includes(k))).toEqual(['curtain_width'])
  })

  it('🔴 钱面类级：订单侧识别字段表里**不得**有价格 / 门幅类的键', () => {
    expect(
      priceLikeOrderKeys(PY_SRC),
      '订单侧识别字段里出现价格/门幅类键 ⇒ 必须显式回答「它进不进建行面」：' +
        '单价只能来自目录 / SKU、门幅只能来自所选 SKU（issue #5345 判据 5/6）'
    ).toEqual([])
  })

  it('注入式红证：给订单侧字段表塞一个 `price` / `door_width` ⇒ 上面那条当场红', () => {
    const injected = PY_SRC.replace(
      '"order": (',
      '"order": (\n        TargetField("price", "售价", "售价（元）"),\n        TargetField("door_width", "门幅", "门幅（米）"),'
    )
    expect(priceLikeOrderKeys(injected)).toEqual(['price', 'door_width'])
  })
})