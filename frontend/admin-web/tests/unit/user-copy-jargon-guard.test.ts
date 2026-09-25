// case_ids: UI-057
//
// 类级元守卫（issue #5565）：**内部代号不得写进用户可见文案**。
//
// 病根形态（实测）：省料看板把 issue #5159 的度量分层代号 `L2` / `L3` 抄进了页头副标题与两个区块标题
// ⇒ 用户逐字反馈「L2和L3是什么概念，用户不懂，我也不懂」。这类泄漏的成因不是"文案风格"，
// 而是**写码时对着 issue 写**、把内部编号当成名词带上了屏 —— 单个页面改一次不解决复发。
//
// 发现规则（机械、窄口径，只认**会上屏**的两种形态）：
//   ① 括号包裹的代号：`（L2）` / `(L3)`（副标题那一种）
//   ② 代号后紧跟中文：`L2 批次余量分档`（区块标题那一种）
// **不算**的：注释行（`//` / `*` / `{/*`）与 SVG `d="…"`（路径数据里有 `L3`，但它不上屏 ——
// 实测 `orders/page.tsx` 的图标路径就是 `…6.7L3 8`，不加这条会假红）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

const ROOT = process.cwd()
/** 用户可见面：页面 / 组件 / **文案助手**（`src/lib/saving-board.ts` 这类就产 label 与 hint） */
const SCAN_DIRS = ['src/app', 'src/components', 'src/lib']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/** 豁免台账（**只许缩短**）：登记「命中规则但确有必要」的 `相对路径:行`。当前为空。 */
const EXEMPT: string[] = []

const LAYER_IN_PARENS = /[（(]\s*L[123]\s*[）)]/
const LAYER_BEFORE_CJK = /L[123][ 　](?=[\u4e00-\u9fff])/

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/** 注释行 / SVG path：不上屏 ⇒ 不参与判定（判定的是"会不会被用户看到"，不是"源码里有没有这个词"） */
function isOffScreen(line: string): boolean {
  const trimmed = line.trim()
  return (
    trimmed.startsWith('//')
    || trimmed.startsWith('*')
    || trimmed.startsWith('/*')
    || trimmed.includes('{/*')
    || line.includes('d="')
  )
}

describe('用户可见文案不得含内部代号（issue #5565）', () => {
  const files = SCAN_DIRS.flatMap((d) => sourceFiles(join(ROOT, d)))

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, '三个扫描目录下应有一批源文件').toBeGreaterThanOrEqual(50)
    expect(files.some((f) => f.includes('saving-board'))).toBe(true)
  })

  it('`（L2）` / `L2 中文` 这类内部代号没有出现在用户可见文案里（未登记即红）', () => {
    const offenders: string[] = []
    for (const file of files) {
      readFileSync(file, 'utf-8').split('\n').forEach((line, index) => {
        if (isOffScreen(line)) return
        if (!LAYER_IN_PARENS.test(line) && !LAYER_BEFORE_CJK.test(line)) return
        const where = `${relative(ROOT, file)}:${index + 1}`
        if (EXEMPT.includes(where)) return
        offenders.push(`${where}  ${line.trim().slice(0, 100)}`)
      })
    }
    expect(
      offenders,
      '内部代号（L1/L2/L3 这类分层编号）写进了用户可见文案 —— 商家读不懂（issue #5565）。\n'
        + '出口：把代号换成"这个数是什么"的人话（如「每批布用剩多少」「每平方米成品用掉多少米布」），'
        + '代号留在注释/文档里；确有必要的写法请登记到本文件 EXEMPT（只许缩短）。\n'
        + offenders.join('\n'),
    ).toEqual([])
  })
})