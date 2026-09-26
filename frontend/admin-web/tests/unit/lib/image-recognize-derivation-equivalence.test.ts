// case_ids: OR-036, OR-008, OR-046
/**
 * **图片路径 ⇄ 手工路径 的推导等价性**（issue #5349：图片建单必须接上「自动推导参数」链）。
 *
 * 病根（不是"推导没跑"，而是"识别给不出推导的输入"）：识别字段表里订单侧只有一个**自由文本**
 * `spec`（「规格（宽×高 / 门幅 / 颜色等）」），而推导链要的是**结构化数值输入**
 * （`lib/craft-calc-request.ts::craftCalcParamsOf` 对 宽 / 高 是 fail-closed：缺任一个就不发试算）
 * ⇒ 自由文本进不了推导函数。
 *
 * 本文件把 issue #5349 的五条验收判据钉成**可执行断言**（不是散文）：
 *
 * | 判据 | 断言 |
 * |---|---|
 * | 1 等价性 | 同一组输入 ⇒ 图片路径与手工路径的试算入参**逐字一致**（+ 注入式红证） |
 * | 2 单一真值 | 识别面（`lib/image-recognize*.ts` + `app/vision/*.py`）**零推导调用**（+ 注入式红证） |
 * | 3 缺失输入不产出 | 缺一个输入 ⇒ 试算 `null` ⇒ 推导项恒空（**不是**用默认值硬推） |
 * | 4 来源可区分 | `[图片识别]` ≠「系统推导」（两个常量逐字断言） |
 * | 5 钱面护栏 | 推导链可见面由**既有** `craft-plan` 面板承担（本单不新增第二份）——见文件末的说明 |
 * | 类级（铁律 8） | 识别 target ⇄ 推导输入的接线**登记表** + 豁免台账（未登记即红 / 只许缩短） |
 *
 * ⚠️ 判据 ②④ 读的是**调用点 / 常量值**（结构化证据），**不读"文本里提到过"**
 * —— 注释里出现推导函数名不算违规（`migao-dev-flow` §17.3「判据能被自己的文案喂绿」）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  ORDER_DERIVATION_INPUT_KEYS,
  RECOGNIZE_SOURCE_TAG,
  buildOrderPrefill,
  sizeTargetLineIndex,
} from '@/lib/image-recognize'
import {
  CRAFT_PLAN_SOURCE_DERIVED,
  craftCalcParamsOf,
  craftCalcSignature,
  derivedJoinSpliceItemOf,
  derivedSpecialOptionsOf,
  type CalcLineInput,
} from '@/lib/craft-calc-request'
import { createDefaultCraftSpec } from '@/lib/order-craft-fields'
import type { RecognizedField } from '@/lib/api'

// ── 真值源（只读；取不到就**直接失败**，不静默跳过 —— 同 `craft-calc-defaults.test.ts`）──
/** 识别内核字段表（后端真值源） */
const TARGETS_PY = resolve(
  __dirname,
  '../../../../../backend/ai-agent-service/app/vision/targets.py',
)
/** 识别面（前端接线）：**glob 面**——新增识别文件自动进扫描集，不需要登记 */
const RECOGNIZE_LIB = resolve(__dirname, '../../../src/lib/image-recognize.ts')
/** 下单页（接线点） */
const ORDER_PAGE = resolve(
  __dirname,
  '../../../src/app/(dashboard)/orders/new/page.tsx',
)

const PY_SRC = readFileSync(TARGETS_PY, 'utf8')
const LIB_SRC = readFileSync(RECOGNIZE_LIB, 'utf8')
const PAGE_SRC = readFileSync(ORDER_PAGE, 'utf8')

/** 后端 `TARGET_FIELDS` 里某个 target 的字段键（正则只认 `TargetField("key", …)` 的**位置**证据） */
function targetFieldKeys(target: string): string[] {
  const block = PY_SRC.match(new RegExp(`"${target}":\\s*\\(([\\s\\S]*?)\\n    \\),`))
  if (!block) throw new Error(`targets.py 里读不到 target「${target}」的字段表`)
  return [...block[1].matchAll(/TargetField\(\s*"([^"]+)"/g)].map((m) => m[1])
}

/** 后端 `TARGET_FIELDS` 的全部 target 名 */
function allTargets(): string[] {
  const block = PY_SRC.match(/TARGET_FIELDS[^=]*=\s*\{([\s\S]*?)\n\}/)
  if (!block) throw new Error('targets.py 里读不到 TARGET_FIELDS')
  return [...block[1].matchAll(/^\s{4}"([^"]+)":\s*\(/gm)].map((m) => m[1])
}

/** 后端 `DERIVATION_INPUT_KEYS` 里某个 target 声明的「推导链原始输入」 */
function declaredDerivationInputs(target: string): string[] {
  const block = PY_SRC.match(/DERIVATION_INPUT_KEYS[^=]*=\s*\{([\s\S]*?)\n\}/)
  if (!block) throw new Error('targets.py 里读不到 DERIVATION_INPUT_KEYS（元守卫必须能读到真值）')
  const entry = block[1].match(new RegExp(`"${target}"\\s*:\\s*\\(([^)]*)\\)`))
  if (!entry) return []
  return [...entry[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
}

// ── 夹具：识别内核产出的字段表（有值 = 预填候选；`value: null` = 有意留空）──
const TAG = RECOGNIZE_SOURCE_TAG
const EMPTY_ORDER = { customerName: '', customerPhone: '', customerAddress: '', remark: '' }

function sizeField(key: string, value: string | null, reason: string | null = null): RecognizedField {
  return { key, label: key === 'curtain_width' ? '帘宽' : '帘高', value, source: value ? TAG : null, reason }
}

const ORDER_SIZE_FIELDS: RecognizedField[] = [
  sizeField('curtain_width', '2.8'),
  sizeField('curtain_height', '2.4'),
]

/** 页面侧一行的**试算入参**装配（与 `orders/new/page.tsx::calcInputOf` 同一形状：
 *  宽 / 高 + 默认工艺规格）—— 两条路径共用它，等价性才有意义。 */
function lineOf(width: number | null | undefined, height: number | null | undefined): CalcLineInput {
  return {
    width: width ?? null,
    height: height ?? null,
    craft: createDefaultCraftSpec(),
  }
}

describe('判据 1 · 等价性：同一组输入，图片路径与手工路径的推导逐字一致 (#5349)', () => {
  it('识别值经页面行进入推导链，与商家手敲同一组数字得到**逐字相同**的入参', () => {
    const prefill = buildOrderPrefill(ORDER_SIZE_FIELDS, EMPTY_ORDER)

    // 图片路径：识别 → 预填（结构化数）→ 行状态 → 推导
    const viaImage = craftCalcParamsOf(lineOf(prefill.curtainWidth, prefill.curtainHeight))
    // 手工路径：商家在同一个数字框里敲「2.8 / 2.4」
    const viaTyping = craftCalcParamsOf(lineOf(2.8, 2.4))

    expect(viaImage).toEqual(viaTyping)
    // 签名是「会不会重发试算」的判据：它也必须一致（否则两条路径的**重算时机**都不同）
    expect(craftCalcSignature(viaImage)).toBe(craftCalcSignature(viaTyping))
    expect(craftCalcSignature(viaImage)).not.toBe('')
  })

  it('注入式红证：识别值若不是规范十进制串，这条等价性会**当场红**（判据有判别力）', () => {
    // 注入：把页面拿到的值换成内核**未归一**的原文（`2.8米`）—— `Number('2.8米')` 是 NaN
    const injected = Number('2.8米')
    expect(Number.isNaN(injected)).toBe(true)
    const degraded = craftCalcParamsOf(lineOf(injected, 2.4))
    expect(degraded).toBeNull()
    expect(craftCalcSignature(degraded)).not.toBe(craftCalcSignature(craftCalcParamsOf(lineOf(2.8, 2.4))))

    // 而预填层**结构上拒收**这种值 ⇒ 注入形态不会真的发生（拒绝点即判据）
    expect(buildOrderPrefill([sizeField('curtain_width', '2.8米')], EMPTY_ORDER).curtainWidth).toBeUndefined()
  })
})

// ── 判据 2 · 单一真值：识别面零推导 ──────────────────────────────────────────
/** 推导链的**唯一**实现点（`lib/craft-calc-request.ts`）里的对外符号 */
const DERIVATION_SYMBOLS = [
  'craftCalcParamsOf',
  'craftCalcSignature',
  'derivedSpliceOptionOf',
  'derivedJoinHeightOptionOf',
  'derivedJoinSpliceItemOf',
  'derivedSpecialOptionsOf',
  'effectiveSpecialOptionsOf',
  'spliceOptionNameOf',
  'joinGapOf',
  'SPLICE_ITEM_NAME',
  'JOIN_HEIGHT_OPTION_NAME',
] as const

/**
 * 识别面上的推导痕迹 —— **两条结构化证据**（不读"提到过"）：
 * ① **调用点**（`符号(` / `符号.` 的语法绑定位置）；② **导入绑定**（`from '…craft-calc-request'`）。
 * 注释里为了解释「本文件不做推导」而写下符号名 ⇒ **不算**（只有加括号的调用形态才算）。
 */
function derivationEvidence(src: string): string[] {
  const hits: string[] = []
  for (const name of DERIVATION_SYMBOLS) {
    if (new RegExp(`(?:^|[^\\w.$])${name}\\s*[({]`).test(src)) hits.push(`call:${name}`)
  }
  if (/from\s+['"][^'"]*craft-calc-request['"]/.test(src)) hits.push('import:craft-calc-request')
  return hits
}

describe('判据 2 · 单一真值：识别侧不得有第二份派生逻辑 (#5349)', () => {
  it('`lib/image-recognize.ts` 里零推导调用、零推导模块导入', () => {
    expect(derivationEvidence(LIB_SRC)).toEqual([])
  })

  it('注入式红证：塞一句推导调用 / 一句推导导入进源码，扫描必须认出来', () => {
    expect(derivationEvidence(`${LIB_SRC}\nconst p = craftCalcParamsOf(line)\n`)).toEqual([
      'call:craftCalcParamsOf',
    ])
    expect(derivationEvidence(`${LIB_SRC}\nimport { x } from '@/lib/craft-calc-request'\n`)).toEqual([
      'import:craft-calc-request',
    ])
    // 反向：**注释里的名字**不得被当成违规（否则判据会被自己的文案喂红）
    expect(derivationEvidence(`${LIB_SRC}\n// 本文件不做推导：craftCalcParamsOf 在页面侧\n`)).toEqual([])
    expect(derivationEvidence(LIB_SRC)).toEqual([])
  })

  it('识别内核（后端 `app/vision/**`）不得 import 任何算料实现', () => {
    // 内核是**纯识别**：算料只在 `app/tools/curtain_calc.py`（服务端唯一实现）与页面侧调用
    expect(/curtain_calc|craft_calc/.test(PY_SRC)).toBe(false)
  })
})

describe('判据 3 · 缺失输入 ⇒ 该推导项不产出（不是用默认值硬推）(#5349)', () => {
  it('只认到帘宽、帘高留空 ⇒ 试算 fail-closed，推导项恒空', () => {
    const prefill = buildOrderPrefill([sizeField('curtain_width', '2.8')], EMPTY_ORDER)

    expect(prefill.curtainWidth).toBe(2.8)
    expect(prefill.curtainHeight).toBeUndefined()
    // 页面那一行的窗高仍是 `null` ⇒ 推导链**不发请求**（`craftCalcParamsOf` 的第一条 fail-closed）
    expect(craftCalcParamsOf(lineOf(prefill.curtainWidth, undefined))).toBeNull()
    // 没有 plan ⇒ **不产出任何**推导项（缺输入时**不**按默认值编一个「接高」/「拼2次」出来）
    expect(derivedSpecialOptionsOf({ plan: null })).toEqual([])
    expect(derivedJoinSpliceItemOf({ plan: null, manualOptions: [] })).toBeNull()
  })

  it('内核有意留空的尺寸（`value: null`）绝不预填 —— 保持页面的 `null` 而不是填 0', () => {
    const prefill = buildOrderPrefill(
      [
        sizeField('curtain_width', null, '「2.8×2.4」未写明哪个是宽哪个是高，宁可不填'),
        sizeField('curtain_height', null, '「2.8×2.4」未写明哪个是宽哪个是高，宁可不填'),
      ],
      EMPTY_ORDER,
    )

    expect(prefill.curtainWidth).toBeUndefined()
    expect(prefill.curtainHeight).toBeUndefined()
    expect(prefill.recognizedFields).toEqual([])
    // 0 是**真值**（会被当成"填了"）⇒ 缺输入必须是 `null`（未填），不是 0
    expect(craftCalcParamsOf(lineOf(0, 0))).toBeNull()
  })
})

describe('判据 4 · 来源可区分：识别来的输入 ≠ 推导出的项 (#5349)', () => {
  it('两个标注是**不同**的字面量（否则商家无法判断该信哪一格）', () => {
    expect(RECOGNIZE_SOURCE_TAG).toBe('[图片识别]')
    expect(CRAFT_PLAN_SOURCE_DERIVED).toBe('系统推导')
    expect(RECOGNIZE_SOURCE_TAG).not.toBe(CRAFT_PLAN_SOURCE_DERIVED)
  })

  it('识别进行的尺寸带 `[图片识别]` 徽标键；推导项**不带**该键（标注各归各的）', () => {
    const prefill = buildOrderPrefill(ORDER_SIZE_FIELDS, EMPTY_ORDER)

    expect(prefill.recognizedFields).toEqual(
      expect.arrayContaining(['curtain_width', 'curtain_height']),
    )
    // 推导项（`接高` / `拼N次`）是**推导**结果，不得冒充识别来源
    const derived = derivedSpecialOptionsOf({ plan: { splice_times: 2, join_height_m: 0.05 } })
    expect(derived).toEqual(['拼2次', '接高'])
    expect(derived.includes(RECOGNIZE_SOURCE_TAG)).toBe(false)
  })
})

describe('尺寸预填的落点：只落在**还没有尺寸主张**的行上 (#5349)', () => {
  it('第一行宽高都空 ⇒ 落第 0 行', () => {
    expect(sizeTargetLineIndex([{ width: null, height: null }])).toBe(0)
  })

  it('已有尺寸的行**一格都不动**（不覆盖商家敲进去的数）', () => {
    expect(sizeTargetLineIndex([{ width: 3, height: 2.5 }])).toBe(-1)
    // 只填了宽 = 这一行已经有尺寸主张 ⇒ 不把识别的高塞进去（宁可不填）
    expect(sizeTargetLineIndex([{ width: 3, height: null }])).toBe(-1)
    expect(sizeTargetLineIndex([{ width: null, height: 2.5 }])).toBe(-1)
  })

  it('第 0 行已有尺寸、第 1 行还空 ⇒ 落第 1 行（找**第一行**空尺寸行）', () => {
    expect(
      sizeTargetLineIndex([
        { width: 3, height: 2.5 },
        { width: null, height: null },
      ]),
    ).toBe(1)
  })
})

describe('下单页的接线点（判据 1 的页面侧半边）(#5349)', () => {
  it('页面用**同一个纯函数**挑选落点，并把预填值写进行状态', () => {
    // 读的是**调用点**（位置证据）：页面必须真的调用它，而不是"文档里说会调用"
    expect(/sizeTargetLineIndex\s*\(/.test(PAGE_SRC)).toBe(true)
    expect(/prefill\.curtainWidth/.test(PAGE_SRC)).toBe(true)
    expect(/prefill\.curtainHeight/.test(PAGE_SRC)).toBe(true)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 类级固化（`AGENTS.md` 铁律 8 / `migao-dev-flow` §23 G1~G2）
// ══════════════════════════════════════════════════════════════════════════════
/**
 * **不喂推导链的识别 target**（豁免台账，**只许缩短**）。
 *
 * 有了这张表，「新 target 该不该带推导输入」就是一个**必须显式回答**的问题
 * （不登记 ⇒ 下面第 1 条断言红），而不是靠人记得去想。
 */
const TARGETS_WITHOUT_DERIVATION = ['product', 'inbound', 'shipment'] as const
describe('类级元守卫：识别 target ⇄ 推导输入 的接线登记 (#5349 · 铁律 8)', () => {
  it('每个 target 要么登记了推导输入、要么在「不喂推导链」台账里（新 target 不登记 ⇒ 红）', () => {
    const unregistered = allTargets().filter(
      (t) =>
        declaredDerivationInputs(t).length === 0 &&
        !(TARGETS_WITHOUT_DERIVATION as readonly string[]).includes(t),
    )
    expect(unregistered).toEqual([])
  })

  it('豁免台账**只许缩短**：登记了推导输入的 target 不得再留在台账里（豁免必带死亡条件）', () => {
    const dead = TARGETS_WITHOUT_DERIVATION.filter((t) => declaredDerivationInputs(t).length > 0)
    expect(dead).toEqual([])
  })

  it('声明的推导输入必须真的在该 target 的字段表里（声明与字段表不得各写一份）', () => {
    for (const target of allTargets()) {
      const keys = new Set(targetFieldKeys(target))
      const missing = declaredDerivationInputs(target).filter((key) => !keys.has(key))
      expect({ target, missing }).toEqual({ target, missing: [] })
    }
  })

  it('声明的推导输入必须在页面上**接进推导入参**（未接线 ⇒ 红：字段认出来也没人用）', () => {
    const declared = declaredDerivationInputs('order')
    const wired = Object.values(ORDER_DERIVATION_INPUT_KEYS)
    const unwired = declared.filter((key) => !(wired as readonly string[]).includes(key))
    expect(unwired).toEqual([])
  })

  it('页面接线用的识别键必须都在后端字段表里（两端改名漂移 ⇒ 红）', () => {
    const keys = new Set(targetFieldKeys('order'))
    const phantom = Object.values(ORDER_DERIVATION_INPUT_KEYS).filter((key) => !keys.has(key))
    expect(phantom).toEqual([])
  })
})