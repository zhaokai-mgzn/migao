// case_ids: BM-017
/**
 * **SKU 匹配门禁 / 不确定不预填 / 数量口径**（issue #5052 P3；设计 §6.3 / §6.4，验收判据 2 / 3）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | C1 | **零命中 ⇒ 不落库、不建品、不建 SKU**：门禁返回 `none`，且提交闸拒绝 | 允许无 sku 提交 ⇒ 红 |
 * | C2 | **不确定不预填**：`degraded` / `requiresManualEntry` / 零命中 ⇒ 三格全空 + 可行动提示 | 降级也预填 ⇒ 红 |
 * | C3 | **多命中由工人消歧**：不替工人挑（不返回 matched） | 自动取第一条 ⇒ 红 |
 * | C4 | 端侧**只拦结构上不可能成功**的（缺 SKU / 缺米数 / 未确认）；数值口径唯一真值在服务端，端侧不重写 | 端侧另写一套数值规则 ⇒ 红（源码面） |
 * | C5 | 「不自动建品」在端侧是**结构事实**：入库模块里不存在任何建品 / 建 SKU 的调用 | 加一个 `POST /api/admin/products` ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import {
  AMBIGUOUS_SKU_MESSAGE,
  NO_SKU_MATCH_MESSAGE,
  checkDraftInput,
  evaluateSkuGate,
  prefillFromRecognize,
  type PrefillResult,
  type RecognizeLike,
} from '../src/utils/inbound/recognizeGate'
import { INBOUND_PAGE_SCOPE_FILES } from '../src/utils/inbound/gaps'
import { BMINI_ROOT } from './helpers/h5PlatformLists'

// skuId 的出参形态是**字符串**（雪花号 > 2^53，issue #6340）⇒ 端侧类型与语料都是 string
const SINGLE = { skuId: '9', productId: 'p1', productName: '遮光布', skuCode: 'MG-1001', colorName: '米白' }
const OTHER = { skuId: '10', productId: 'p2', productName: '遮光布', skuCode: 'MG-1002', colorName: '米白' }

/** 与 C2 同口径的纯判定（注入式红证用） */
function prefillProblems(response: RecognizeLike, out: PrefillResult): string[] {
  const mustBeBlank =
    !!response.degraded || !!response.requiresManualEntry || (response.skuMatches || []).length === 0
  const problems: string[] = []
  if (mustBeBlank && (out.productName || out.colorName || out.quantity)) {
    problems.push('不确定 / 零命中却预填了候选')
  }
  if (mustBeBlank && out.prefillUsed) problems.push('不确定 / 零命中却标了 prefillUsed')
  if (!out.notice.trim()) problems.push('没有给工人任何说明（静默）')
  return problems
}

describe('SKU 匹配门禁与预填口径', () => {
  it('C1 零命中 ⇒ none（拒绝入库，文案说清"不会自动建品"）', () => {
    const gate = evaluateSkuGate([])
    expect(gate.kind).toBe('none')
    if (gate.kind === 'none') {
      expect(gate.message).toBe(NO_SKU_MATCH_MESSAGE)
      expect(gate.message).toContain('不会自动建品')
    }
    // null / undefined 同样按零命中处置（服务端也可能不下发该键）
    expect(evaluateSkuGate(null).kind).toBe('none')
    expect(evaluateSkuGate(undefined).kind).toBe('none')
  })

  it('C1 零命中时提交闸拒绝（没有 skuId 就没有入库）', () => {
    const check = checkDraftInput({ productId: null, skuId: null, quantity: '60.5', confirmed: true })
    expect(check.ok).toBe(false)
    expect(check.message).toContain('不会自动建品')
    // 只有 productId 没有 skuId（库存权威在 SKU 级）也不放行
    const half = checkDraftInput({ productId: 'p1', skuId: null, quantity: '60.5', confirmed: true })
    expect(half.ok).toBe(false)
  })

  it('C3 多命中 ⇒ ambiguous（工人消歧，端侧不挑第一条）', () => {
    const gate = evaluateSkuGate([SINGLE, OTHER])
    expect(gate.kind).toBe('ambiguous')
    if (gate.kind === 'ambiguous') {
      expect(gate.matches).toHaveLength(2)
      expect(gate.message).toBe(AMBIGUOUS_SKU_MESSAGE)
      expect(gate.message).toContain('不替你挑')
    }
  })

  it('C2 degraded ⇒ 三格全空 + 提示人工录入（不编造）', () => {
    const response: RecognizeLike = {
      path: 'vision',
      degraded: true,
      requiresManualEntry: true,
      productName: '遮光布',
      colorName: '米白',
      quantityMeters: '60.5',
      skuMatches: [SINGLE],
      message: '识别不确定，请手工录入',
    }
    const out = prefillFromRecognize(response)
    expect(out.prefillUsed).toBe(false)
    expect([out.productName, out.colorName, out.quantity]).toEqual(['', '', ''])
    expect(out.notice).toContain('手工录入')
  })

  it('C2 requiresManualEntry（即使没标 degraded）⇒ 同样不预填', () => {
    const out = prefillFromRecognize({
      requiresManualEntry: true,
      productName: '遮光布',
      colorName: '米白',
      skuMatches: [SINGLE],
    })
    expect(out.prefillUsed).toBe(false)
    expect(out.productName).toBe('')
  })

  it('C2 零命中（未标降级）⇒ 不预填（否则工人一点确认就落一个假 SKU）', () => {
    const out = prefillFromRecognize({
      productName: '遮光布',
      colorName: '米白',
      quantityMeters: '60.5',
      skuMatches: [],
    })
    expect(out.prefillUsed).toBe(false)
    expect(out.productName).toBe('')
    expect(out.gate.kind).toBe('none')
  })

  it('C2 🔴 红证：让降级分支也预填 ⇒ 同一个判定函数必判红', () => {
    const degraded: RecognizeLike = { degraded: true, productName: '遮光布', skuMatches: [SINGLE] }
    const correct = prefillFromRecognize(degraded)
    expect(prefillProblems(degraded, correct)).toEqual([])
    // 注入：降级却预填
    expect(prefillProblems(degraded, { ...correct, prefillUsed: true, productName: '遮光布' })).not.toEqual([])
  })

  it('唯一命中 ⇒ 预填（供工人核对），且提示「请核对」而非「已入库」', () => {
    const out = prefillFromRecognize({
      path: 'barcode_decode',
      barcode: 'MG-1001',
      skuMatches: [SINGLE],
      productName: '遮光布',
      colorName: '米白',
      quantityMeters: '60.5',
      message: '条码命中已有货号，请核对后填写米数。',
    })
    expect(out.prefillUsed).toBe(true)
    expect(out.productName).toBe('遮光布')
    expect(out.quantity).toBe('60.5')
    expect(out.gate.kind).toBe('matched')
    expect(out.notice).toContain('核对')
  })

  it('C4 端侧只拦"结构上不可能成功"的：缺 SKU / 缺米数 / 未确认', () => {
    const base = { productId: 'p1', skuId: '9', confirmed: true }
    expect(checkDraftInput({ ...base, quantity: '60.5' }).ok).toBe(true)
    for (const empty of ['', '   ']) {
      const check = checkDraftInput({ ...base, quantity: empty })
      expect(check.ok).toBe(false)
      expect(check.message).toContain('请填写入库米数')
    }
    expect(checkDraftInput({ productId: null, skuId: null, quantity: '60.5', confirmed: true }).ok).toBe(false)
    expect(checkDraftInput({ ...base, quantity: '60.5', confirmed: false }).ok).toBe(false)
  })

  it('C4 数量口径**不在端侧重写**（服务端是唯一真值：> 0 且最多 1 位小数，超 1 位显式拒绝）', () => {
    const code = fs
      .readFileSync(path.join(BMINI_ROOT, 'src/utils/inbound/recognizeGate.ts'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    // 端侧不许出现数值判定（小数位、正负、下限）—— 那就是第二份口径，迟早与服务端漂移
    for (const pattern of [/Number\(/, /parseFloat/, /\\\\d\+\\\\.\\\\d/, /toFixed/, /\*\s*10\b/]) {
      expect({ pattern: String(pattern), hit: pattern.test(code) }).toEqual({ pattern: String(pattern), hit: false })
    }
    // 也不许把服务端的规则文案抄一份（文案唯一生成处 = 服务端 400 的 message）
    expect(code).not.toContain('最多 1 位小数（库存按')
  })

  it('C4 未勾选「我确认」⇒ 不提交（§6.5 不做免确认）', () => {
    const check = checkDraftInput({ productId: 'p1', skuId: '9', quantity: '60.5', confirmed: false })
    expect(check.ok).toBe(false)
    expect(check.message).toContain('我确认')
  })

  it('C5 「不自动建品」是结构事实：入库射程内没有任何建品 / 建 SKU / 改库存的调用', () => {
    const forbidden = [
      /\/api\/admin\/products/,
      /\/api\/admin\/skus/,
      /createProduct\s*\(/,
      /createSku\s*\(/,
      /stock\/adjust/,
    ]
    const offenders: string[] = []
    for (const rel of INBOUND_PAGE_SCOPE_FILES) {
      const code = fs
        .readFileSync(path.join(BMINI_ROOT, rel), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
      for (const pattern of forbidden) {
        if (pattern.test(code)) offenders.push(`${rel} → ${pattern}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('C5 建草稿的请求体里没有"任意调整"字段（结构上不可表达）', () => {
    const service = fs.readFileSync(path.join(BMINI_ROOT, 'src/services/workerInboundService.ts'), 'utf8')
    const requestBlock = service.slice(
      service.indexOf('export interface InboundDraftRequest'),
      service.indexOf('function toResponse'),
    )
    for (const key of ['adjustment', 'delta', 'setStock', 'operator', 'tenantId']) {
      expect({ key, present: new RegExp(`\\b${key}\\b`).test(requestBlock) }).toEqual({ key, present: false })
    }
  })
})
