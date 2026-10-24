// case_ids: OR-006, UI-040
// 类级元守卫（issue #7590）：**订单链路上的「商品表」只允许一种对齐口径 = 整表居中**。
//
// 病灶：订单详情页与发货页各有一份 `ProductTable`（同一形态被复制粘贴两次），改前两份都逐列传
// `align`（商品 / 货号 / 颜色 / 规格 左、数量 中、单价 / 金额 / 商品合计 右）⇒ 同一张表三种对齐
// 并存，列与列之间没有稳定参照边（用户 2026-10-24 截图）。修一份**不算**修：下一次复制粘贴会
// 原样把旧形态带出来。
//
// 两条规则（判据本体 = 下面的 `findProductTables` / `scanProductTable`，纯函数、可内存注入）：
//   ① **未登记即红**：源码里只要出现「订单商品表」（表头同时有 `商品货号` 与 `商品合计`），
//      该文件就必须在 `REGISTERED` 里 —— 新增复制体先在这里红，逼人确认对齐口径；
//   ② **登记了也要守口径**：表内 `<Th>` / `<Td>` 调用点不得再传 `align`，也不得出现
//      `text-left` / `text-right` —— 「逐列旋钮」就是漂移的入口（对齐只允许在 `Th` / `Td`
//      的定义处、且为 `text-center`）。
//
// 判别力自证：最后一个用例用内存注入造「带 align 的复制体 / 未登记的新文件 / 已收敛的文件」，
// 三种形态各自判定正确（不落盘）。
//
// 边界（照实登记，§19.1）：
//   · 本判据判**源码形态**，不判渲染结果 —— 「类名对了、渲染仍不居中」（包裹层 / 内联样式 /
//     继承）由实例层守：`tests/unit/pages/order-detail.test.tsx` 与
//     `tests/unit/pages/ship-order.test.tsx`（逐格 `text-center`）；
//   · 效果层（真浏览器计算样式）由 `tests/e2e/specs/orders/order-detail.spec.ts` 的同名用例守；
//   · 识别口径是**表头文本**（`商品货号` + `商品合计`）—— 表头改名会让扫描面漂移，
//     故下面的普查自证要求两份已登记文件**必须仍被扫到**。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative, sep } from 'path'

const SRC_DIR = join(process.cwd(), 'src')

/** 已登记的订单商品表（**双向**：登记的必须仍存在 ⇒ 死条目即红）。 */
const REGISTERED = [
  'src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
  'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
]

/** 订单商品表的识别口径：表头里同时出现这两段文本。 */
const PRODUCT_HEADERS = ['商品货号', '商品合计']

const stripTags = (s: string): string => s.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim()

/**
 * 定位源码里的「订单商品表」块（`<table>` 起止字符区间）。
 *
 * 纯函数：不看文件系统，便于内存注入取证。
 */
export function findProductTables(source: string): Array<{ body: string }> {
  const out: Array<{ body: string }> = []
  const open = /<table\b[^>]*>/g
  let m: RegExpExecArray | null
  while ((m = open.exec(source)) !== null) {
    const close = source.indexOf('</table>', m.index)
    if (close === -1) continue
    const body = source.slice(m.index, close + '</table>'.length)
    // 表头区（`<thead>`…`</thead>`；无 thead 时退化为整块）同时含两段表头文本才算商品表
    const theadEnd = body.indexOf('</thead>')
    const headArea = stripTags(theadEnd === -1 ? body : body.slice(0, theadEnd))
    if (PRODUCT_HEADERS.every((h) => headArea.includes(h))) out.push({ body })
  }
  return out
}

/**
 * 规则 ②：一份源码里的订单商品表**对齐缺陷**（对齐只允许在 `Th` / `Td` 的定义处）。
 *
 * 返回人类可读的缺陷条目（空数组 = 合规）。
 */
export function scanProductTable(source: string): string[] {
  const defects: string[] = []
  for (const { body } of findProductTables(source)) {
    for (const tag of body.match(/<T[hd]\b[^>]*>/g) ?? []) {
      if (/\balign=/.test(tag)) defects.push(`逐列 align：${tag}`)
    }
    for (const cls of body.match(/text-(?:left|right)\b/g) ?? []) {
      defects.push(`表内写死 ${cls}`)
    }
  }
  return defects
}

function walkTsx(dir: string): string[] {
  const files: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) files.push(...walkTsx(full))
    else if (name.endsWith('.tsx')) files.push(full)
  }
  return files
}

const rel = (full: string) => relative(process.cwd(), full).split(sep).join('/')
const CORPUS = walkTsx(SRC_DIR).map((full) => ({ path: rel(full), source: readFileSync(full, 'utf-8') }))
const FOUND = CORPUS.filter((f) => findProductTables(f.source).length > 0).map((f) => f.path).sort()

describe('订单商品表对齐口径守卫（issue #7590）', () => {
  it('普查面自证：两份已登记的商品表都真的被扫到（改名/搬走 ⇒ 先红，而不是静默空跑）', () => {
    expect(CORPUS.length, '扫不到页面源码 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(100)
    for (const path of REGISTERED) {
      expect(FOUND, `已登记的商品表扫不到：${path}（识别口径 = 表头含 ${PRODUCT_HEADERS.join(' + ')}）`).toContain(path)
    }
  })

  it('① 订单商品表未登记即红（复制粘贴出来的新表必须先确认对齐口径）', () => {
    const unexpected = FOUND.filter((p) => !REGISTERED.includes(p))
    expect(
      unexpected,
      '这些文件里有「订单商品表」但没登记 ⇒ 先在这里登记，并确认它满足整表居中：\n'
        + unexpected.join('\n')
        + '\n\n出口：表头与数据格一律 `text-center`（复用共享原语或照 '
        + 'OrderDetail.tsx 的 `Th` / `Td` 定义写）；确属另一套版式（如打印单据）⇒ 不要用这两段表头文本。',
    ).toEqual([])
  })

  it('② 已登记的商品表里没有逐列对齐旋钮（无 align= / text-left / text-right）', () => {
    const offenders = CORPUS.filter((f) => REGISTERED.includes(f.path))
      .flatMap((f) => scanProductTable(f.source).map((d) => `${f.path}::${d}`))
    expect(
      offenders,
      '这些调用点把对齐写回了逐列参数（漂移入口；用户裁定整表居中）：\n'
        + offenders.join('\n')
        + '\n\n出口：删掉 `align` 与 `text-left` / `text-right`，对齐只留在 `Th` / `Td` 的定义处。',
    ).toEqual([])
  })

  it('台账不得腐坏：登记的条目必须仍是商品表（双向相等，只许缩短）', () => {
    const dead = REGISTERED.filter((p) => !FOUND.includes(p))
    expect(dead, `这些登记条目已不是订单商品表 ⇒ 死条目，请从 REGISTERED 删除：${dead.join('、')}`).toEqual([])
  })

  it('判别力自证：内存注入的三种形态各自判定正确（不落盘）', () => {
    const table = (cells: string, headers = '商品货号</Th><Th>颜色</Th><Th>商品合计') =>
      `<div className="overflow-x-auto"><table className="w-full"><thead><tr>`
      + `<Th>商品</Th><Th>${headers}</Th></tr></thead><tbody><tr>${cells}</tr></tbody></table></div>`

    // ① 合规形态（对齐只在 Th/Td 定义处）⇒ 不是缺陷、能被识别成商品表
    const good = table('<Td>SKU-1</Td><Td>-</Td><td className="px-3 py-3 text-center">¥1.00</td>')
    expect(findProductTables(good)).toHaveLength(1)
    expect(scanProductTable(good)).toEqual([])

    // ② 逐列 align 旋钮 ⇒ 缺陷
    const bad = table('<Td align="right">¥1.00</Td><Td>-</Td>').replace('<Th>商品', '<Th align="left">商品')
    expect(scanProductTable(bad)).toContain('逐列 align：<Th align="left">')
    expect(scanProductTable(bad).some((d) => d.includes('<Td align="right">'))).toBe(true)

    // ③ 数据格写死 text-right ⇒ 缺陷（即使没有 align 属性）
    expect(scanProductTable(table('<td className="px-3 text-right">¥1.00</td>'))).toContain('表内写死 text-right')

    // ④ 识别口径：表头不含「商品合计」⇒ 不是本类（如打印单据 / 其它列表）⇒ 不参与
    const other = '<table><thead><tr><th>单号</th><th>金额</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>'
    expect(findProductTables(other)).toEqual([])
  })
})
