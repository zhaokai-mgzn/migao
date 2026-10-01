// case_ids: PR-037
/**
 * **雪花号 id 不许经过 `Number()`**（issue #5904）
 *
 * ## 为什么有它（线上事故，不是假想）
 *
 * 2026-10-01：新增入库单**保存恒失败** —— 「商品明细第 1 项的 SKU 不属于该商品（或不存在），请重新选择」。
 * 根因 = `frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx` 里
 * `skuId: Number(sku.id)`：商品/SKU 的 `id` 是**雪花号 Long**（实测 `2097126615461462018` ≈ 2.1e18），
 * 后端**有意序列化成 JSON 字符串**，而 JS 的 `Number.MAX_SAFE_INTEGER` 只有 9.007e15
 * ⇒ `Number("2097126615461462018")` → `2097126615461462000`（末位被吞）⇒ 服务端查不到该 SKU。
 *
 * ## 为什么原判据没拦住
 *
 * `frontend/admin-web/tests/unit/pages/inbound-orders-new.test.tsx` 当时用的是**玩具 id**（`id: '11'`）
 * —— 小整数转不转 Number 都一样，**洞是测不出来的**。⇒ 这类事故只能靠**源码面**守卫兜住。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **正控**：检测器对合成坏样本（`Number(sku.id)` / `parseInt(o.productId)`）**必须报出**
 *    —— 没有这条，「零命中」可能只是检测器瞎了（**空断言**）；
 * ② **负控**：`Number(item.quantity)`（不是 id）、`String(x.id)`（没转数字）、`x.skuId`（没调用）、
 *    以及**注释里的** `Number(sku.id)` **都不得**判违规；
 * ③ **未登记即红**：`frontend/admin-web/src/**` 真实语料里命中且不在登记表 ⇒ 红（打印 `文件:行`）；
 * ④ **登记陈旧即红**：登记过却已无命中 ⇒ 红（留着会让守卫悄悄放宽）；
 * ⑤ **反空跑**：语料面必须非空（没扫到文件时本判据不算通过）。
 *
 * ## 边界（如实登记）
 *
 * - 只认 `Number()/parseInt()/parseFloat()` 三种**显式**转换；`+x.id`、`x.id * 1`、`BigInt(x.id)` 不在面内
 *   （仓内无此写法；出现时由人评审补充，不由本判据背书）；
 * - 判的是**源码形态**，判不了运行期是否真丢精度（那一半由 `inbound-orders-new.test.tsx` 的
 *   「真实量级 id」实例判据承担）；
 * - 不覆盖后端：服务端 DTO 收的就是 `Long`，字符串入参由 Jackson 正常强转（本单已在真实 API 上验证）。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'

const SRC_ROOT = 'src'
const SCAN_EXT = ['.ts', '.tsx']

/** 显式数字转换（会把字符串 id 变成 double 的三兄弟） */
const ID_CONVERTERS = new Set(['Number', 'parseInt', 'parseFloat'])

/** camelCase / 全大写 的「id 结尾」成员名：`id` / `skuId` / `productID`（`valid` 这种不算） */
const ID_LIKE = /^(id|.*[a-z0-9](Id|ID))$/

/**
 * **登记表**：允许把 `.id` 交给数字转换的位置（相对 `frontend/admin-web`）。
 * 目前**空** —— 即「一处都不许」。真需要时逐条写理由（并接受评审）。
 */
const REGISTERED: { file: string; why: string }[] = []

export interface Hit {
  line: number
  text: string
}

/** 扫一段源码里的「id → 数字转换」（**AST 面**：注释不是节点，天然不算命中） */
export function scanSource(text: string, fileName = 'sample.tsx'): Hit[] {
  const sf = ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    fileName.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
  const hits: Hit[] = []
  const visit = (node: ts.Node): void => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      ID_CONVERTERS.has(node.expression.text)
    ) {
      const arg = node.arguments[0]
      if (arg && ts.isPropertyAccessExpression(arg) && ID_LIKE.test(arg.name.text)) {
        const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
        hits.push({ line: line + 1, text: node.getText(sf) })
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full, out)
    else if (SCAN_EXT.some((ext) => entry.name.endsWith(ext))) out.push(full)
  }
  return out
}

describe('#5904 雪花号 id 不许经过 Number()（源码面元守卫）', () => {
  it('① 正控：检测器认得坏形态（Number/parseInt/parseFloat + .id 结尾）', () => {
    expect(scanSource('const a = Number(sku.id)')).toHaveLength(1)
    expect(scanSource('const b = parseInt(order.productId)')).toHaveLength(1)
    expect(scanSource('const c = parseFloat(x.skuId)')).toHaveLength(1)
  })

  it('② 负控：非 id / 非转换 / 注释里的 —— 都不得判违规', () => {
    expect(scanSource('const a = Number(item.quantity)')).toHaveLength(0)
    expect(scanSource('const b = String(sku.id)')).toHaveLength(0)
    expect(scanSource('const c = sku.id')).toHaveLength(0)
    expect(scanSource('const d = Number(row.valid)')).toHaveLength(0)
    // 注释不是 AST 节点 ⇒ 源码里"讲这件事"不会被判违规
    expect(scanSource('// 反面形态：Number(sku.id) 会丢精度')).toHaveLength(0)
    expect(scanSource('/* Number(sku.id) */')).toHaveLength(0)
  })

  it('③④⑤ 真实语料：命中必须已登记、登记必须仍命中、语料面非空', () => {
    const files = walk(SRC_ROOT)
    // ⑤ 反空跑
    expect(files.length).toBeGreaterThan(50)

    const found = files
      .map((file) => ({ file: relative('.', file).replace(/\\/g, '/'), hits: scanSource(readFileSync(file, 'utf8'), file) }))
      .filter((x) => x.hits.length > 0)

    // ③ 未登记即红（具名打印 文件:行 + 那一行代码）
    const unregistered = found
      .filter((x) => !REGISTERED.some((r) => r.file === x.file))
      .flatMap((x) => x.hits.map((h) => `${x.file}:${h.line} → ${h.text}`))
    expect(unregistered, `把 .id 交给数字转换 = 雪花号丢精度（issue #5904）。要么改成原样字符串，要么登记理由：\n${unregistered.join('\n')}`).toEqual([])

    // ④ 登记陈旧即红
    const stale = REGISTERED.filter((r) => !found.some((x) => x.file === r.file))
    expect(stale.map((r) => r.file)).toEqual([])
  })
})
