// case_ids: PR-037
/**
 * **雪花号 id 不许经过 `Number()`**（issue #5904；射程于 issue #6340 扩到 `frontend/bmini-app/src`）
 *
 * ## 为什么有它（线上事故，不是假想）
 *
 * 2026-10-01：新增入库单**保存恒失败** —— 「商品明细第 1 项的 SKU 不属于该商品（或不存在），请重新选择」。
 * 根因 = `frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx` 里
 * `skuId: Number(sku.id)`：商品/SKU 的 `id` 是**雪花号 Long**（实测 `2097126615461462018` ≈ 2.1e18），
 * 后端**有意序列化成 JSON 字符串**，而 JS 的 `Number.MAX_SAFE_INTEGER` 只有 9.007e15
 * ⇒ `Number("2097126615461462018")` → `2097126615461462000`（末位被吞）⇒ 服务端查不到该 SKU。
 *
 * 2026-10-05（issue #6340）：**同族缺陷在工人端（bmini-app）复发** —— 拍照入库页写的是
 * `skuId: Number(chosenSku?.skuId)`，而当时本判据的语料根只有 `frontend/admin-web/src`
 * ⇒ 工人端**不在射程内**，一处分都不扣。⇒ 本次把语料根**参数化**（一份规则、两个根，
 * 不复制第二份实现），命中即红、且必须登记。
 *
 * ## 为什么原判据没拦住
 *
 * `frontend/admin-web/tests/unit/pages/inbound-orders-new.test.tsx` 当时用的是**玩具 id**（`id: '11'`）
 * —— 小整数转不转 Number 都一样，**洞是测不出来的**。⇒ 这类事故只能靠**源码面**守卫兜住。
 * （#6340 的实例判据因此改用**真实量级** id：`frontend/bmini-app/tests/worker-inbound-page.test.tsx`
 * 的「#6340 靶心」用例，SKU 选项用 `2106900122848247810`。）
 *
 * ## 判据（各自能单独变红）
 *
 * ① **正控**：检测器对合成坏样本（`Number(sku.id)` / `parseInt(o.productId)`）**必须报出**
 *    —— 没有这条，「零命中」可能只是检测器瞎了（**空断言**）；
 * ② **负控**：`Number(item.quantity)`（不是 id）、`String(x.id)`（没转数字）、`x.skuId`（没调用）、
 *    以及**注释里的** `Number(sku.id)` **都不得**判违规；
 * ③ **未登记即红**：**两个语料根**（`frontend/admin-web/src/**` + `frontend/bmini-app/src/**`）
 *    真实语料里命中且不在登记表 ⇒ 红（打印 文件:行 + 那一行代码）；
 * ④ **登记陈旧即红**：登记过却已无命中 ⇒ 红（留着会让守卫悄悄放宽）；
 * ⑤ **反空跑**：语料面必须非空（没扫到文件时本判据不算通过）+ **每个根各自非空**
 *    （根写错 / 目录改名 ⇒ 红，而不是「那个根 0 命中」的假绿）。
 *
 * ## 边界（如实登记）
 *
 * - 只认 `Number()/parseInt()/parseFloat()` 三种**显式**转换；`+x.id`、`x.id * 1`、`BigInt(x.id)` 不在面内
 *   （仓内无此写法；出现时由人评审补充，不由本判据背书）；
 * - `String(x.skuId)` / 原样透传**不算命中**（那正是修好后的形态）—— 判据只拦「转成 double」；
 * - 判的是**源码形态**，判不了运行期是否真丢精度（那一半由页面级实例判据承担：admin-web 的
 *   `inbound-orders-new.test.tsx`、bmini 的 `worker-inbound-page.test.tsx`，都用真实量级 id）；
 * - 不覆盖后端：服务端 DTO 收的就是 `Long`，字符串入参由 Jackson 正常强转（issue #6340 已在真实 API 上验证）；
 * - 射程外的同族写法（`frontend/mini-app` / `frontend/worker-h5`）**未纳入**（本轮未清点，不为其背书）。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import ts from 'typescript'

/** 语料根的**参数化**声明：一份规则、N 个根（新增根 = 这里加一行，不是复制一份判据） */
const SRC_ROOTS = [
  { label: 'admin-web', dir: resolve(process.cwd(), 'src') },
  { label: 'bmini-app', dir: resolve(process.cwd(), '..', 'bmini-app', 'src') },
]
const SCAN_EXT = ['.ts', '.tsx']

/** 显式数字转换（会把字符串 id 变成 double 的三兄弟） */
const ID_CONVERTERS = new Set(['Number', 'parseInt', 'parseFloat'])

/** camelCase / 全大写 的「id 结尾」成员名：`id` / `skuId` / `productID`（`valid` 这种不算） */
const ID_LIKE = /^(id|.*[a-z0-9](Id|ID))$/

/**
 * **登记表**：允许把 `.id` 交给数字转换的位置（`frontend/` 起算的仓库相对路径）。
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

/** `frontend/` 起算的仓库相对路径（`frontend/admin-web` 的上一级就是 `frontend`） */
function repoRelative(absPath: string): string {
  return relative(join(process.cwd(), '..'), absPath).replace(/\\/g, '/')
}

/** 现取全部语料文件（按根分组，便于 ⑤ 逐根反空跑） */
function corpusByRoot(): { label: string; dir: string; files: string[] }[] {
  return SRC_ROOTS.map((root) => ({ ...root, files: walk(root.dir) }))
}

describe('#5904/#6340 雪花号 id 不许经过 Number()（源码面元守卫，射程 = admin-web + bmini-app）', () => {
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
    // 修好后的形态（#6340 的修法）：原样字符串透传，不是命中
    expect(scanSource('const e = { skuId: String(chosenSku?.skuId) }')).toHaveLength(0)
    expect(scanSource('const f = { skuId: chosenSku?.skuId }')).toHaveLength(0)
    // 注释不是 AST 节点 ⇒ 源码里"讲这件事"不会被判违规
    expect(scanSource('// 反面形态：Number(sku.id) 会丢精度')).toHaveLength(0)
    expect(scanSource('/* Number(sku.id) */')).toHaveLength(0)
  })

  it('③④⑤ 真实语料：命中必须已登记、登记必须仍命中、每个语料根都非空', () => {
    const roots = corpusByRoot()
    // ⑤ 反空跑（逐根）：根写错 / 目录改名 ⇒ 红，而不是「那个根 0 命中」的假绿
    for (const root of roots) {
      expect(root.files.length, `语料根 ${root.label}（${root.dir}）一个文件都没扫到 ⇒ 判红而不是判绿`)
        .toBeGreaterThan(50)
    }
    const files = roots.flatMap((root) => root.files)
    expect(files.length).toBeGreaterThan(100)

    const found = files
      .map((file) => ({ file: repoRelative(file), hits: scanSource(readFileSync(file, 'utf8'), file) }))
      .filter((x) => x.hits.length > 0)

    // ③ 未登记即红（具名打印 文件:行 + 那一行代码）
    const unregistered = found
      .filter((x) => !REGISTERED.some((r) => r.file === x.file))
      .flatMap((x) => x.hits.map((h) => `${x.file}:${h.line} → ${h.text}`))
    expect(unregistered, `把 .id 交给数字转换 = 雪花号丢精度（issue #5904 / #6340）。要么改成原样字符串，要么登记理由：\n${unregistered.join('\n')}`).toEqual([])

    // ④ 登记陈旧即红
    const stale = REGISTERED.filter((r) => !found.some((x) => x.file === r.file))
    expect(stale.map((r) => r.file)).toEqual([])
  })

  it('⑥ 射程自证：两个根都在面内，且 bmini 的入库页确实被扫到', () => {
    const roots = corpusByRoot()
    expect(roots.map((r) => r.label)).toEqual(['admin-web', 'bmini-app'])
    const bminiFiles = roots.find((r) => r.label === 'bmini-app')!.files.map(repoRelative)
    expect(bminiFiles).toContain('bmini-app/src/pages/worker/inbound/index.tsx')
  })
})
