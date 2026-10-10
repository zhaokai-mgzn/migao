// case_ids: BM-040
/**
 * 类级守卫：**把数/钱印成字符串的函数，必须自己挡住「坏值」**（issue #6685，涉钱面）
 *
 * ## 治的形态（本单实例 + 它的类）
 *
 * `frontend/bmini-app/src/services/dashboardService.ts` 的 `formatYuan` / `formatPercent`
 * 签名是 `(cents: number)`，但 TS 的 `number` **不挡住运行时传进来的 `undefined`**
 * —— 服务端 `200 + 空 data`（`{}` / 缺键）时 `stats.todaySales` 就是 `undefined`
 * ⇒ 商家屏印出 **`NaN元`**（`undefined/100` ⇒ `NaN`）。同类 `formatPercent` 更狠：直接抛。
 *
 * 单修一处 = 没修：**下一个把数印成字符串的函数照抄这个签名，同一个坑还会再来**。
 * ⇒ 判据落在**函数体**上，而不是某一个调用点：
 * 凡「形参含 number 且返回 string」的格式化函数，函数体里必须出现**有限性守卫**
 * （`Number.isFinite` / `!Number.isNaN`）—— 否则未登记即红。
 *
 * ## 库存台账（本仓实测，2026-10-10）
 *
 * | 函数 | 文件 | 守卫 |
 * |---|---|---|
 * | `formatYuan` | `src/services/dashboardService.ts` | `Number.isFinite` |
 * | `formatPercent` | `src/services/dashboardService.ts` | `Number.isFinite` |
 * | `formatYuanAmount` | `src/services/adminOpsService.ts` | `Number.isFinite` |
 * | `formatMeters` | `src/services/adminOpsService.ts` | `Number.isFinite` |
 * | `formatWaitHours` | `src/services/adminOpsService.ts` | `Number.isFinite` |
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 库存里每个函数都**存在**且函数体含有限性守卫 | 摘掉守卫 / 改名 / 删函数 ⇒ 具名红 |
 * | 2 | 全仓 numeric 格式化函数库存 == 台账（**只许缩短**） | 新增一个无守卫的数格式化函数 ⇒ 红；删除却不删台账 ⇒ 红 |
 * | 3 | 判别力自证：坏形态（无守卫）被抓、好形态不误报、豁免清理判据真会红 | 守卫退化成恒绿 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const LEDGER_PATH = path.join(__dirname, 'numeric-format-guard-ledger.json')

/** 有限性守卫的可判形态（两条并列：任一出现即算挡住坏值） */
const GUARD_PATTERNS: RegExp[] = [/Number\.isFinite\s*\(/, /!\s*Number\.isNaN\s*\(/]

/** 扫描面：只扫服务/工具层（页面 JSX 里的临时格式化不在本判据射程，见文件头边界） */
const SCAN_DIRS = ['src/services', 'src/utils']

type Ledger = {
  /** 每个 numeric 格式化函数一条（**只许缩短**：台账只记活着且真有守卫的） */
  inventory: Array<{ file: string; fn: string; guard: string }>
  /** 有意豁免：只许为空/缩短，且必须写明理由（当前无） */
  exempt: Array<{ file: string; fn: string; reason: string }>
}

export function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/** 去掉块注释与行注释：**被注释掉的守卫不算守卫**，被注释掉的函数不算函数 */
export function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '')
}

/**
 * 找「形参列表里含 `number` 且返回类型是 `string` 的导出格式化函数」。
 *
 * 判据形态（不是语义判据）：`export function format<大写字母>…( … )` + 参数含 `number` + 返回 `string`。
 * 名字必须 `format` 后接大写 —— 避免把 `formatter` 一类无关标识卷进来。
 */
export function findNumericFormatters(source: string): Array<{ fn: string; body: string }> {
  const src = stripComments(source)
  const re =
    /export\s+(?:async\s+)?function\s+(format[A-Z]\w*)\s*\(([^)]*)\)\s*(?::\s*([^={]+))?\s*\{/g
  const out: Array<{ fn: string; body: string }> = []
  let m: RegExpExecArray | null
  while ((m = re.exec(src))) {
    const [, fn, params, ret] = m
    if (!/\bnumber\b/.test(params)) continue
    if (!/\bstring\b/.test(ret ?? '')) continue
    // 函数体：从 `{` 起做花括号配对（够用且对嵌套对象字面量安全）
    let depth = 1
    let i = re.lastIndex
    for (; i < src.length && depth > 0; i++) {
      if (src[i] === '{') depth++
      else if (src[i] === '}') depth--
    }
    out.push({ fn, body: src.slice(re.lastIndex, i - 1) })
  }
  return out
}

/** 台账声明的守卫是否真在函数体里逐字出现 */
export function guardPresent(body: string, guard: string): boolean {
  return body.includes(guard)
}

/** 函数体里有没有**任一**可判的有限性守卫 */
export function hasFiniteGuard(body: string): boolean {
  return GUARD_PATTERNS.some((p) => p.test(body))
}

// 现取库存（**不写死数字**：数量由扫描自证）
const ledger: Ledger = JSON.parse(fs.readFileSync(LEDGER_PATH, 'utf-8'))
const files = SCAN_DIRS.flatMap((d) => walk(path.join(ROOT, d))).filter((f) => /\.(ts|tsx)$/.test(f))
const inventory = files
  .flatMap((f) =>
    findNumericFormatters(fs.readFileSync(f, 'utf-8')).map((x) => ({
      file: path.relative(ROOT, f).split(path.sep).join('/'),
      fn: x.fn,
      body: x.body,
    })),
  )
  .sort((a, b) => `${a.file}::${a.fn}`.localeCompare(`${b.file}::${b.fn}`))

describe('类级守卫：numeric 格式化函数必须挡住坏值（issue #6685）', () => {
  it('台账每个函数都活着、且函数体里真有它声明的守卫', () => {
    const alive = new Map(inventory.map((x) => [`${x.file}::${x.fn}`, x]))
    const problems: string[] = []
    for (const entry of ledger.inventory) {
      const key = `${entry.file}::${entry.fn}`
      const found = alive.get(key)
      if (!found) {
        problems.push(`台账里的 ${key} 已不存在（函数被删/改名/挪文件）⇒ 要么补回守卫，要么删台账条目`)
      } else if (!guardPresent(found.body, entry.guard)) {
        problems.push(`${key} 的函数体里找不到声明的守卫「${entry.guard}」`)
      }
    }
    expect(problems).toEqual([])
  })

  it('🔴 全仓 numeric 格式化函数 == 台账（只许缩短）', () => {
    const scanned = inventory.map((x) => `${x.file}::${x.fn}`).sort()
    const recorded = ledger.inventory.map((e) => `${e.file}::${e.fn}`).sort()
    // 新增无守卫的函数 ⇒ 出现在 scanned、不在 recorded ⇒ 两条断言都不空
    expect(scanned).toEqual(recorded)
  })

  it('🔴 未登记的 numeric 格式化函数**未登记即红**（具名报出）', () => {
    const recorded = new Set(ledger.inventory.map((e) => `${e.file}::${e.fn}`))
    const unregistered = inventory
      .filter((x) => !recorded.has(`${x.file}::${x.fn}`) && !hasFiniteGuard(x.body))
      .map((x) => `${x.file}::${x.fn}`)
    expect(unregistered).toEqual([])
  })

  it('豁免台账只许为空或缩短，且每条必须写明理由', () => {
    expect(ledger.exempt).toEqual([])
  })
})

describe('判别力自证（issue #6685 判据 3）', () => {
  it('坏形态（逐字照修前的 formatYuan）被判为无守卫', () => {
    const bad = `
/** 金额展示：元（后端分 → 元） */
export function formatYuan(cents: number): string {
  return (cents / 100).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}`
    const found = findNumericFormatters(bad)
    expect(found.map((x) => x.fn)).toEqual(['formatYuan'])
    expect(hasFiniteGuard(found[0].body)).toBe(false)
  })

  it('好形态（修后实现）不误报', () => {
    const good = `
export function formatYuan(cents: number | null | undefined): string {
  const n = Number(cents)
  if (cents === null || cents === undefined || !Number.isFinite(n)) return '--'
  return (n / 100).toLocaleString('zh-CN')
}`
    const found = findNumericFormatters(good)
    expect(found.map((x) => x.fn)).toEqual(['formatYuan'])
    expect(hasFiniteGuard(found[0].body)).toBe(true)
  })

  it('被注释掉的守卫不算守卫（**判据不许被注释骗过**）', () => {
    const sneaky = `
export function formatYuan(cents: number): string {
  // if (!Number.isFinite(cents)) return '--'
  return (cents / 100).toLocaleString('zh-CN')
}`
    expect(hasFiniteGuard(findNumericFormatters(sneaky)[0].body)).toBe(false)
  })

  it('非 number 入参的格式化函数不在射程（`formatMessageTime` 不误报）', () => {
    const time = `export function formatMessageTime(value: string | null | undefined): string {
  return value ?? ''
}`
    expect(findNumericFormatters(time)).toEqual([])
  })

  it('🔴 反向对照：台账若留一个已不存在的条目，判据 1 真会红', () => {
    const alive = new Map(inventory.map((x) => [`${x.file}::${x.fn}`, x]))
    expect(alive.has('src/services/ghost.ts::formatGhost')).toBe(false)
    const problems = [{ file: 'src/services/ghost.ts', fn: 'formatGhost' }]
      .map((entry) => `${entry.file}::${entry.fn}`)
      .filter((key) => !alive.has(key))
    expect(problems).toEqual(['src/services/ghost.ts::formatGhost'])
  })
})
