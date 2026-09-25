// case_ids: UI-057, UI-058
//
// 类级元守卫：**内部词汇不得写进用户可见文案**。两个形态，同一条纪律：
//
// ① 度量分层代号（issue #5565）：省料看板把 `L2` / `L3` 抄进了页头副标题与区块标题
//    ⇒ 用户逐字反馈「L2和L3是什么概念，用户不懂，我也不懂」。
// ② 机制隐喻（issue #5576）：「池」是 pooling 的实现隐喻（池看板/池化开关/进池/池内/成批区）
//    ⇒ 用户逐字反馈「池看板这个命名用户不太懂」，菜单改名**智能派单**并与页内文案一起去隐喻。
//
// 形态相同：写码时对着 issue/设计写，把**内部编号或机制隐喻**当名词带上了屏。单个页面改一次
// 不解决复发 ⇒ 本守卫是那条类级收口。
//
// ## 发现规则（机械、窄口径：只认**会上屏**的行）
//
//   · 代号①：`（L2）`（括号包裹）或 `L2 中文`（标题式）
//   · 隐喻②：出现 CJK「池」（ASCII 的 `pool` / `pooled` / `poolingEnabled` 是**契约与实现**，
//     不在射程内 —— 本判据只扫**给商家看的中文**）
//
// **不算**的：注释（`//` / `/* … */` / JSX `{/* … */}`，含**跨行块注释**）与 SVG `d="…"`。
// 这两条不是"宽容"，是判据口径：判的是**会不会被用户看到**，不是"源码里有没有这个词"
//（实测 `orders/page.tsx` 的图标路径含 `…6.7L3 8`；`pool-board.ts` 的 JSDoc 里满是"池化"机制说明）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

const ROOT = process.cwd()
/** 用户可见面：页面 / 组件 / **文案助手**（`src/lib/saving-board.ts`、`src/lib/craft-calc-glossary.ts` 这类也产文案） */
const SCAN_DIRS = ['src/app', 'src/components', 'src/lib']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/** 豁免台账（**只许缩短**）：登记「命中规则但确有必要」的 `相对路径:行`。当前为空。 */
const EXEMPT: string[] = []

const LAYER_IN_PARENS = /[（(]\s*L[123]\s*[）)]/
const LAYER_BEFORE_CJK = /L[123][ 　](?=[\u4e00-\u9fff])/
/** 机制隐喻：CJK「池」（`pool` 这类 ASCII 标识符不算） */
const POOL_METAPHOR = /池/

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/**
 * 取「会上屏的行」：逐字符剥掉 `//` 行注释与 `/* … *\/` 块注释（**含跨行**，JSX `{/* … *\/}` 也是块注释），
 * 再去掉 SVG path 行。返回 `{行号, 可见文本}`。
 *
 * ⚠️ 边界（如实登记）：字符串字面量里的 `//`（如 URL）会被当行注释截断 ⇒ 只会**少扫**、不会假红。
 */
function visibleLines(src: string): { line: number; text: string }[] {
  const out: { line: number; text: string }[] = []
  let inBlock = false
  src.split('\n').forEach((raw, index) => {
    let visible = ''
    let cursor = 0
    while (cursor < raw.length) {
      if (inBlock) {
        const end = raw.indexOf('*/', cursor)
        if (end === -1) break
        inBlock = false
        cursor = end + 2
        continue
      }
      const block = raw.indexOf('/*', cursor)
      const lineComment = raw.indexOf('//', cursor)
      if (lineComment !== -1 && (block === -1 || lineComment < block)) {
        visible += raw.slice(cursor, lineComment)
        break
      }
      if (block === -1) {
        visible += raw.slice(cursor)
        break
      }
      visible += raw.slice(cursor, block)
      inBlock = true
      cursor = block + 2
    }
    if (raw.includes('d="')) return // SVG path（图标路径里有 L3 这类字样，但它不上屏）
    if (!visible.trim()) return
    out.push({ line: index + 1, text: visible.trim() })
  })
  return out
}

describe('用户可见文案不得含内部词汇（issue #5565 / #5576）', () => {
  const files = SCAN_DIRS.flatMap((d) => sourceFiles(join(ROOT, d)))

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, '三个扫描目录下应有一批源文件').toBeGreaterThanOrEqual(50)
    expect(files.some((f) => f.includes('production/pool/page'))).toBe(true)
    expect(files.some((f) => f.includes('saving-board'))).toBe(true)
  })

  it('`（L2）` / `L2 中文` 这类内部代号没有出现在用户可见文案里（未登记即红）', () => {
    const offenders: string[] = []
    for (const file of files) {
      for (const { line, text } of visibleLines(readFileSync(file, 'utf-8'))) {
        if (!LAYER_IN_PARENS.test(text) && !LAYER_BEFORE_CJK.test(text)) continue
        const where = `${relative(ROOT, file)}:${line}`
        if (!EXEMPT.includes(where)) offenders.push(`${where}  ${text.slice(0, 100)}`)
      }
    }
    expect(
      offenders,
      '内部代号（L1/L2/L3 这类分层编号）写进了用户可见文案 —— 商家读不懂（issue #5565）。\n'
        + '出口：换成"这个数是什么"的人话（如「每批布用剩多少」「每平方米成品用掉多少米布」），'
        + '代号留在注释/文档里；确有必要请登记 EXEMPT（只许缩短）。\n'
        + offenders.join('\n'),
    ).toEqual([])
  })

  it('🔴 机制隐喻「池」（池看板/池化/进池/池内/成批区）没有出现在用户可见文案里（issue #5576）', () => {
    const offenders: string[] = []
    for (const file of files) {
      for (const { line, text } of visibleLines(readFileSync(file, 'utf-8'))) {
        if (!POOL_METAPHOR.test(text)) continue
        const where = `${relative(ROOT, file)}:${line}`
        if (!EXEMPT.includes(where)) offenders.push(`${where}  ${text.slice(0, 100)}`)
      }
    }
    expect(
      offenders,
      '内部机制隐喻「池」（pooling 的实现说法）写进了用户可见文案 —— 商家读不懂（issue #5576）。\n'
        + '出口：改成商家的话（待派订单 / 合并派单 / 可合并的待派订单 / 加急订单（不参与合并）…）；'
        + '机制名留在注释、字段名（`pooled` / `poolingEnabled`）与内部文档里。\n'
        + offenders.join('\n'),
    ).toEqual([])
  })
})