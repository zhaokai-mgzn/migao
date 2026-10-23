// case_ids: PR-037, SP-006, PRC-005
//
// 类级元守卫：**SKU 只能选，不能打**（issue #7567）。
//
// ## 它治的类
//
// 用户 2026-10-23 逐字：「这种选择SKU的组件应该作为sku的公共组件，你新增的采购单和作业单中的
// sku 输入框是不能作为生产系统使用的，需要优化」（复核确认第二处 = 价格本）。
// 三处病灶同源：把**内部标识**（≈19 位雪花号 `2097126615461462018`）当成人能填的东西交给商家；
// 价格本还多一层 `Number(skuId)` —— 转换即吞末位（#5904 实测：`2097126615461462000`），查不到该 SKU。
//
// 单点修完不算修（铁律 8），因为「下一个新页面再手拼一格 SKU 输入框」没有任何东西会红：
//   · 页面用例只守各自的页面，谁也不会问「你这个输入框合理吗」；
//   · 设计基线守卫管的是**控件铬**，不管「该不该让人填这个字段」。
//
// ## 判据（会红，未登记即红；登记台账**只许缩短**且条数现取）
//
// 扫 `frontend/admin-web/src/**` 的 `.ts/.tsx`（先剥注释，避免注释里的反例文本误报）：
//   规则 1·**裸 SKU 文本输入**：`placeholder` 字面量里含 `SKU`；
//   规则 2·**文本输入绑 skuId**：`value={…skuId…}`（把雪花号绑到输入框 = 让人打它）；
//   规则 3·**SKU id 数字化**：`Number|parseInt|parseFloat(…skuId)`（雪花号 > 2^53，必截断）；
//   规则 4·**消费面必须走共用件**：入库单 / 采购单 / 价格本三个页面必须 `import … from '@/components/products/SkuPicker'`
//          —— 谁把页面改回手拼，规则 4 当场红（规则 1~3 只能证明「现在没手拼」，证明不了「以后仍用共用件」）。
//
// ## 边界（照实登记，§19.1）
//
// - 判的是**源码形态**，不解析 AST：跨行拼字符串 / 运行时拼出来的 placeholder 抓不到；
// - 只管 `src/`（测试夹具与脚本不在射程）；`components/products/SkuPicker.tsx` 自己也**不许**出现这三类形态
//   （共用件只回传 `{product, sku}` 对象，不落输入框）；
// - 价格本的「客户 id」手填框**不在本守卫射程**（那是客户选择器的活，PRC-005 边界 ② 已登记）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, sep } from 'node:path'

const SRC_DIR = join(process.cwd(), 'src')

/** 台账：存量违规（**只许缩短**；今天为空 = 一处都不许有） */
const RAW_SKU_INPUT_LEDGER: string[] = []
const SKU_ID_NUMBER_LEDGER: string[] = []
const RAW_SKU_INPUT_BASELINE = 0
const SKU_ID_NUMBER_BASELINE = 0

/** 规则 4 的消费面：三个页面都必须继续用共用件（去掉任一个 ⇒ 红） */
const PICKER_CONSUMERS = [
  'src/app/(dashboard)/inbound-orders/new/page.tsx',
  'src/app/(dashboard)/purchase-orders/page.tsx',
  'src/app/(dashboard)/price-books/page.tsx',
]

/** 剥注释：块注释（含 JSX 注释）与整行行注释 —— 注释里会写反例文本，不能当违规 */
function stripComments(source: string): string {
  return source
    .replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

function walk(dir: string, base = SRC_DIR, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const abs = join(dir, name)
    if (statSync(abs).isDirectory()) {
      walk(abs, base, out)
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(`src/${abs.slice(base.length + 1).split(sep).join('/')}`)
    }
  }
  return out
}

function read(rel: string): string {
  return readFileSync(join(process.cwd(), rel), 'utf8')
}

/** 规则 1：`placeholder="…SKU…"`（单双引号字面量；模板串另算，见边界） */
const RAW_SKU_PLACEHOLDER = /placeholder=(?:"[^"\n]*SKU[^"\n]*"|'[^'\n]*SKU[^'\n]*')/i
/** 规则 2：把 skuId 绑到输入框 / 值位 */
const SKU_ID_INPUT_VALUE = /value=\{[^}\n]*\.skuId\b[^}\n]*\}/
/** 规则 3：SKU id 数字化 */
const SKU_ID_TO_NUMBER = /\b(?:Number|parseInt|parseFloat)\s*\(\s*(?:[A-Za-z_$][\w$]*\.)?skuId\b/

describe('类级守卫：SKU 只能选、不能打（issue #7567）', () => {
  it('规则 1：`src/` 里没有 placeholder 含 SKU 的文本输入（台账为空 = 一处都不许有）', () => {
    const hits = walk(SRC_DIR)
      .filter((rel) => RAW_SKU_PLACEHOLDER.test(stripComments(read(rel))))
      .filter((rel) => !RAW_SKU_INPUT_LEDGER.includes(rel))
    expect(hits).toEqual([])
    expect(RAW_SKU_INPUT_LEDGER.length).toBeLessThanOrEqual(RAW_SKU_INPUT_BASELINE)
  })

  it('规则 2：没有任何输入框（或值位）绑定 `skuId` —— 雪花号不该出现在可编辑控件里', () => {
    const hits = walk(SRC_DIR)
      .filter((rel) => SKU_ID_INPUT_VALUE.test(stripComments(read(rel))))
      .filter((rel) => !RAW_SKU_INPUT_LEDGER.includes(rel))
    expect(hits).toEqual([])
  })

  it('规则 3：没有 `Number(…skuId)` / `parseInt(…skuId)` —— 雪花号一转换就吞末位', () => {
    const hits = walk(SRC_DIR)
      .filter((rel) => SKU_ID_TO_NUMBER.test(stripComments(read(rel))))
      .filter((rel) => !SKU_ID_NUMBER_LEDGER.includes(rel))
    expect(hits).toEqual([])
    expect(SKU_ID_NUMBER_LEDGER.length).toBeLessThanOrEqual(SKU_ID_NUMBER_BASELINE)
  })

  it('规则 4：入库单 / 采购单 / 价格本三个消费面都从共用件取 SKU（谁改回手拼谁红）', () => {
    const missing = PICKER_CONSUMERS.filter((rel) => {
      const source = stripComments(read(rel))
      return !source.includes("from '@/components/products/SkuPicker'")
    })
    expect(missing).toEqual([])
    // 共用件本体必须存在（引用得到 ≠ 文件在；少一个就是三个页面一起红）
    expect(() => statSync(join(process.cwd(), 'src/components/products/SkuPicker.tsx'))).not.toThrow()
  })

  it('判别力自证：三条规则各自能命中一个"坏形态"（判据不是空转）', () => {
    // 用内存里的样本自证，不往源码里注入 —— 判据红了才算「会红」，不是「恰好没命中」
    expect(RAW_SKU_PLACEHOLDER.test('<input placeholder="SKU" />')).toBe(true)
    expect(SKU_ID_INPUT_VALUE.test('<input value={line.skuId} />')).toBe(true)
    expect(SKU_ID_TO_NUMBER.test('const id = Number(skuId)')).toBe(true)
    // 反面：注释里的反例文本不算违规（否则这份守卫会被自己的说明文字判红）
    expect(RAW_SKU_PLACEHOLDER.test(stripComments('/** 反例：<input placeholder="SKU"> */'))).toBe(false)
  })
})
