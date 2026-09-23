// case_ids: UI-055
/**
 * 静态扫描：禁止「falsy 兜底」形态的**数值接线**（issue #5218 判据 6；issue #5228 缺口 1 把判据语义化）。
 *
 * ## 为什么要有这条
 *
 * #5198 只机械扫了 `value={x || ''}` **一种写法**，于是同一族的另一种写法整批漏网：
 * `value={sku?.price ? sku.price : null}` —— `0` 是 falsy ⇒ 外部值由 `12.5` 变 `null`
 * ⇒ 正在输入的草稿被外部同步洗掉 ⇒ **编辑既有值时输入框当场清空**（用户原始症状复活）。
 * 「形态会变、语义不变」⇒ 用一条静态断言把「falsy 一律当空」的写法挡在门外，
 * 而不是等下一次人肉扫描（人肉扫描已经漏过一次，实测）。
 *
 * ## 判据（**语义**，不是某一种写法）
 *
 * 命中 = **这个表达式在 `x` 为假值时会产出一个「空」值**（`0` 被当空 = 病根本体）。两种形态等价：
 *
 * | 形态 | 判据 |
 * |---|---|
 * | 三元 `x ? x : <空>` | 条件与真分支**规范化后同一表达式**（`?.` 与 `.` 同一形态），且假分支是空值 |
 * | 短路或 `x \|\| <空>` | 右操作数是空值（`x \|\| E` ≡ `x ? x : E`） |
 *
 * `<空>` = `null` / `undefined` / `''` / `""`。**两个分支都纳入判定**：真分支必须与条件同一表达式
 * （`x ? x : …` 才是「拿 x 自己当 x 的真值判据」），假分支必须是空值。
 *
 * ## 判据的**作用域**（这一格是 #5228 实测数据逼出来的，不是随手选的）
 *
 * - **三元形态：全仓判红**。实测全仓 `src/**`（admin-web / mini-app / bmini-app）里
 *   `x ? x : null` / `: undefined` / `: ''` 三种写法**各 0 处** ⇒ 全仓扫描零假红，沿用既有严格度。
 * - **短路或形态：只在「数值输入接线」面判红**（`value=` / `defaultValue=` 落在带数值标记的控件上：
 *   `type="number"` / `inputMode="decimal"` / `step=` / `min=` / `NumberInput`）。
 *   理由是**实测**：裸 `||` 兜底全仓 **223 处**（`|| ''` 166 / `|| undefined` 45 / `|| null` 12），
 *   几乎全是**合法**的字符串/nullable 兜底（`data.content || ''`、`res.data.session || null`）——
 *   把它们判红就是**假红**，而假红 = 假证据（比漏报更坏：它会逼着后人去改合法代码）。
 *   ⇒ 「形态决定证据强度」：手写三元是**冗余的真值自测**（写出来本身就是信号）；
 *   `||` 是语言惯用默认值，只有落在**数值输入接线**上才是「0 被当空」那个病。
 *
 * ## 本文件自身可红（红证见「红证样本」四条；把 `findFalsyWiring` 换成 `() => []` ⇒ ①~⑤ 必红）
 *
 * - ① `x ? x : null`（既有形态）② `x ? x : undefined` ③ `x ? x : ''` ④ `x || null`（数值接线）
 *   —— **四个变体各一条红证样本**（#5228 缺口 1 的表格逐行）；
 * - ⑤ 跨行形态**已覆盖**（`\s*` 命中换行，不是「已知不覆盖」）；
 * - ⑥ `typeof` 白名单：`typeof m === 'string' && m ? m : null` 与 `typeof x === 'number' ? x : null`
 *   都是**正确**写法（前者仓库里真有：`frontend/admin-web/src/lib/production-guard-reasons.ts`）；
 * - ⑦ 负例：合法写法一律不判红（`??`、字符串兜底、文本控件上的 `|| ''`、条件≠真分支）；
 * - ⑧ 全仓（admin-web / mini-app / bmini-app 的 `src/**`）真扫零命中。
 *
 * ## 已知不覆盖（**显式登记，不许留白**）
 *
 * 1. **裸 `||` 兜底**（非接线面）**有意不管** —— 见上「判据的作用域」，全仓 223 处合法兜底；
 *    这是**判据的边界**，不是漏（⑨ 把它钉成可执行的边界断言，防后人误以为漏）。
 * 2. **间接接线**：经中间变量 / 解构 / `{...props}` 展开传递的 falsy 兜底 —— 静态文本扫描不追数据流（⑨ 同钉）。
 * 3. issue #5228 表里字面的「跨行 `x &&\n x : null`」**不是合法 JS**（`&&` 后不能直接接 `:`），
 *    无法作为判据样本；其**可判的等价形态**（跨行 `?:`）**已覆盖且有红证** —— 见 ⑤（⑨ 同钉）。
 * 4. 文本控件上的字符串兜底（`value={form.description || ''}`）**不判红**：`''` 正是字符串的正确空值。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/** 剥掉注释再扫：注释/文档里写旧形态是**说明**，不是接线（假阳性来源） */
export function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 「空」字面量：falsy 时产出它 = 把 `0` 与「空」混为一谈 */
const EMPTY = String.raw`(?:null\b|undefined\b|''|"")`
/** 标识符或属性访问链（`?.` 与 `.` 视为同一形态） */
const EXPR = String.raw`[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*`
/** 三元：`x ? x : <空>`（`\s` 含换行 ⇒ 跨行形态一并覆盖） */
const TERNARY_RE = new RegExp(`(${EXPR})\\s*\\?\\s*(${EXPR})\\s*:\\s*(${EMPTY})`, 'g')
/** 短路或：`x || <空>` */
const OR_RE = new RegExp(`(${EXPR})\\s*\\|\\|\\s*(${EMPTY})`, 'g')
/** 数值输入标记：`||` 形态只在这个面上判红（见文件头「判据的作用域」） */
const NUMERIC_MARKER =
  /(?:\btype\s*=\s*["']number["']|\binputMode\s*=\s*["']decimal["']|(?:^|[\s<])NumberInput\b|\bstep\s*=|\bmin\s*=)/

/** `?.` 与 `.` 是同一形态（`sku?.price ? sku.price : null` 也是同一个表达式的自测） */
const norm = (s: string) => s.replace(/\?\./g, '.')

/**
 * 该命中所在语句的前半段是否已有 `typeof` 收窄 —— `typeof m === 'string' && m ? m : null`
 * 是**正确**写法（`typeof` 已把类型收窄到字符串，`''` 与 `0` 不是一回事）⇒ 放行。
 */
function typeofGuarded(src: string, at: number): boolean {
  const stmtStart = Math.max(src.lastIndexOf('\n', at), src.lastIndexOf(';', at), src.lastIndexOf('{', at))
  return /\btypeof\b/.test(src.slice(stmtStart + 1, at))
}

/** 找 `at` 所在的 JSX 开标签文本（大括号 / 引号配平地找收尾 `>`；不是开标签则 null） */
function enclosingTag(src: string, at: number): string | null {
  const lt = src.lastIndexOf('<', at)
  if (lt < 0) return null
  if (!/^[A-Za-z][\w.]*/.test(src.slice(lt + 1, lt + 60))) return null
  let depth = 0
  let quote = ''
  for (let i = lt + 1; i < src.length; i++) {
    const c = src[i]
    if (quote) {
      if (c === quote) quote = ''
      continue
    }
    if (c === '"' || c === "'") quote = c
    else if (c === '{') depth++
    else if (c === '}') depth--
    else if (c === '>' && depth === 0) return src.slice(lt, i + 1)
  }
  return null
}

/** `at` 所在的大括号是哪个属性的值（`value` / `defaultValue` / …）；不在属性值里则 null */
function attrNameAt(src: string, at: number): string | null {
  const open = src.lastIndexOf('{', at)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < at; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}') depth--
  }
  if (depth <= 0) return null
  const m = /([\w$]+)\s*=\s*$/.exec(src.slice(Math.max(0, open - 24), open))
  return m ? m[1] : null
}

/** 该命中是否落在「数值输入接线」面（见文件头「判据的作用域」） */
function inNumericValueWiring(src: string, at: number): boolean {
  const tag = enclosingTag(src, at)
  if (!tag || !NUMERIC_MARKER.test(tag)) return false
  const attr = attrNameAt(src, at)
  return attr === 'value' || attr === 'defaultValue'
}

/** 扫出一段代码里所有「falsy 兜底」的数值接线（`typeof` 收窄保护的字符串守卫放行） */
export function findFalsyWiring(code: string): string[] {
  const src = stripComments(code)
  const hits: string[] = []
  // 三元形态：全仓（实测三种空值各 0 处 ⇒ 无假红）
  for (const m of src.matchAll(TERNARY_RE)) {
    if (norm(m[1]) !== norm(m[2])) continue
    const at = m.index ?? 0
    if (typeofGuarded(src, at)) continue
    hits.push(m[0].trim())
  }
  // 短路或形态：只在数值接线面（裸表达式是语言惯用默认值，全仓 223 处合法）
  for (const m of src.matchAll(OR_RE)) {
    const at = m.index ?? 0
    if (!inNumericValueWiring(src, at)) continue
    if (typeofGuarded(src, at)) continue
    hits.push(m[0].trim())
  }
  return hits
}

/** 递归收集 .ts/.tsx（跳过测试与声明文件——本判据管的是**产品代码**的接线） */
function sourceFiles(dir: string, acc: string[] = []): string[] {
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return acc // 某些端在本地没检出（CI 上是完整仓）⇒ 不因此判红
  }
  for (const name of entries) {
    const p = join(dir, name)
    if (name === 'node_modules' || name === '.next') continue
    if (statSync(p).isDirectory()) sourceFiles(p, acc)
    else if (/\.tsx?$/.test(name) && !/\.d\.ts$/.test(name)) acc.push(p)
  }
  return acc
}

describe('静态扫描：数值接线的 falsy 兜底（issue #5218 判据 6 / issue #5228 缺口 1）', () => {
  // ── 红证样本：#5228 表格里的四个变体各一条（删判据 ⇒ 逐条必红）────────────────

  it('① 红证样本：`x ? x : null`（既有形态）必须被扫出', () => {
    expect(findFalsyWiring('const p = sku?.price ? sku.price : null')).toEqual([
      'sku?.price ? sku.price : null',
    ])
  })

  it('② 红证样本（#5228 变体）：`x ? x : undefined` 必须被扫出', () => {
    expect(findFalsyWiring('const p = sku?.price ? sku.price : undefined')).toEqual([
      'sku?.price ? sku.price : undefined',
    ])
  })

  it("③ 红证样本（#5228 变体）：`x ? x : ''` 必须被扫出", () => {
    expect(findFalsyWiring("const p = sku?.price ? sku.price : ''")).toEqual([
      "sku?.price ? sku.price : ''",
    ])
  })

  it('④ 红证样本（#5228 变体）：`x || null` 在数值接线上必须被扫出', () => {
    expect(
      findFalsyWiring('<input type="number" value={sku?.price || null} onChange={f} />')
    ).toEqual(['sku?.price || null'])
  })

  it('⑤ 跨行形态**已覆盖**（不是「已知不覆盖」）：条件/问号/分支分行都照样扫出', () => {
    expect(findFalsyWiring('const p = sku?.price\n  ? sku.price\n  : null')).toEqual([
      'sku?.price\n  ? sku.price\n  : null',
    ])
    expect(findFalsyWiring('const p = sku?.price ?\n  sku.price :\n  undefined')).toEqual([
      'sku?.price ?\n  sku.price :\n  undefined',
    ])
    expect(
      findFalsyWiring('<input\n  type="number"\n  value={sku?.price ||\n    null}\n/>')
    ).toEqual(['sku?.price ||\n    null'])
  })

  // ── 负例样本：**合法写法不得判红**（假红 = 假证据）──────────────────────────

  it('⑥ `typeof` 白名单：字符串守卫与类型收窄不算违规', () => {
    // 仓库里真有这一处：frontend/admin-web/src/lib/production-guard-reasons.ts
    expect(
      findFalsyWiring("const m = e?.message\nreturn typeof m === 'string' && m ? m : null")
    ).toEqual([])
    expect(findFalsyWiring("const p = typeof x === 'number' ? x : null")).toEqual([])
    expect(
      findFalsyWiring('<input type="number" value={typeof x === \'number\' ? x : null} />')
    ).toEqual([])
  })

  it('⑦ 负例：`??`（只对 null/undefined 兜底，**0 原样保留**）不判红', () => {
    expect(findFalsyWiring('const p = sku?.price ?? null')).toEqual([])
    expect(findFalsyWiring('const p = sku?.price ?? undefined')).toEqual([])
    expect(
      findFalsyWiring('<NumberInput value={sku?.price ?? null} onChange={f} />')
    ).toEqual([])
  })

  it('⑦ 负例：字符串兜底（裸 / 文本控件）不判红 —— 全仓 223 处合法写法', () => {
    expect(findFalsyWiring("const s = data.content || ''")).toEqual([])
    expect(findFalsyWiring('const s = res.data.session || null')).toEqual([])
    expect(
      findFalsyWiring('<input type="text" value={color.remark || \'\'} onChange={f} />')
    ).toEqual([])
  })

  it('⑦ 负例：条件与真分支**不是同一表达式**（`a.b ? a.c : null`）不判红', () => {
    expect(findFalsyWiring('const p = a.b ? a.c : null')).toEqual([])
    expect(findFalsyWiring('<input type="number" value={a.b ? a.c : null} onChange={f} />')).toEqual([])
  })

  it('⑦ 负例：注释里写了旧形态不算违规（假阳性实测踩过）', () => {
    expect(findFalsyWiring('// 旧形态 `sku?.price ? sku.price : null` 已拆掉\nconst x = 1')).toEqual([])
    expect(findFalsyWiring('/* 说明：value={sku?.stock ? sku.stock : null} */\nconst y = 1')).toEqual([])
    expect(findFalsyWiring('/* 说明：value={sku?.price || null} */\nconst y = 1')).toEqual([])
  })

  // ── 已知不覆盖 / 判据边界：**显式登记**（钉成可执行断言，防后人误以为漏）──────

  it('⑨ 已知不覆盖 1：裸 `||` 兜底有意不判红（判据边界，不是漏）', () => {
    // 全仓实测：`|| ''` 166 / `|| undefined` 45 / `|| null` 12 —— 几乎全是合法兜底。
    expect(findFalsyWiring('const s = res.data.session || null')).toEqual([])
    expect(findFalsyWiring("const s = data.content || ''")).toEqual([])
  })

  it('⑨ 已知不覆盖 2：经中间变量 / props 展开的间接接线（静态扫描不追数据流）', () => {
    expect(
      findFalsyWiring('<input type="number" value={v} onChange={f} />\n// v 来自别处')
    ).toEqual([])
    expect(
      findFalsyWiring('<input type="number" {...props} />')
    ).toEqual([])
  })

  it('⑨ 已知不覆盖 3：#5228 字面的「跨行 `x &&\\n x : null`」不是合法 JS（等价的可判形态已覆盖，见 ⑤）', () => {
    expect(findFalsyWiring('const p = sku?.price &&\n  sku.price : null')).toEqual([])
  })

  // ── 真仓扫描 ────────────────────────────────────────────────────────────

  it('⑧ 全仓（admin-web / mini-app / bmini-app 的 src）零命中', () => {
    const roots = ['src', '../mini-app/src', '../bmini-app/src'].map((d) => join(process.cwd(), d))
    const bad = roots.flatMap((root) =>
      sourceFiles(root).flatMap((f) =>
        findFalsyWiring(readFileSync(f, 'utf8')).map((hit) => `${f}: ${hit}`)
      )
    )
    expect(bad).toEqual([])
  })
})
