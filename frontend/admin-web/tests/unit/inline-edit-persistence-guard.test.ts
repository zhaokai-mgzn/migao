// case_ids: PR-010, PR-042, UI-055, UI-057
//
// ========== 类级元守卫：行内编辑**必须有显式落库路径，失败不得静默退出** ==========
//
// 病根（issue #6662，两处实例）：
//   ① `SkuPriceCell` 的 `onBlur={() => setEditing(false)}` —— 改完价点别处，**改动无声消失**；
//   ② `handleSaveDraftAndLeave` 的 `finally { setShowLeaveModal(false) }` —— 校验失败时
//      `handleSubmit` 是**早退 return、不抛异常** ⇒ 弹窗关了、草稿没存、人也没离开。
// 两者是**同一类**：**退出路径（失焦 / 关闭弹窗）与「真的落库了没有」脱钩**。
// 只修这两处 = 没修 —— 本文件把这一类做成**可机械检查**的形态。
//
// 判据（两条，都**不依赖金额/文案**，只看结构）：
//   判据 A：行内编辑器（有 `<name>Editing` 编辑态 + `onBlur`）的 `onBlur` 必须指向
//           **同一文件里做落库调用的那个函数**；只关编辑态 ⇒ 未登记即红。
//   判据 B：弹窗的关闭没有一个发生在**非条件**路径上（尤其 `try/catch` 的 `finally`）——
//           `finally { setShowLeaveModal(false) }` 即红，`if (!ok) return` 之后的关闭才合规。
//
// 台账 `tests/unit/inline-edit-persistence-ledger.json`：**只许缩短**（新增条目要走评审并在
// PR body 登记）；本单的现状是**零条目、零豁免**（唯一一处行内编辑器已按判据 A 收敛）。
//
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, it, expect } from 'vitest'

const SRC_ROOT = join(process.cwd(), 'src')
const LEDGER_PATH = join(process.cwd(), 'tests/unit/inline-edit-persistence-ledger.json')

/** 递归收集 src 下的 .ts/.tsx（排除测试与声明文件） */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      out.push(...collectSourceFiles(full))
    } else if (/\.tsx?$/.test(entry) && !/\.d\.ts$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

/**
 * 判据 A 的扫描器（**纯函数**，便于判别力自证）：
 * 返回「行内编辑器的 onBlur 与落库路径脱钩」的违规清单。
 *
 * 语义（有意收窄，边界见文件末）：
 *   - 只认**同一文件里**的落库调用（`patch/put/post` 或导出到 `request/api` 的调用）；
 *   - `onBlur={fn}` / `onBlur={() => fn()}` / `onBlur={() => { ... fn() ... }}` 里出现
 *     **任何一个「调用了落库函数的函数名」** ⇒ 合规；
 *   - `onBlur` 体里**只**出现编辑态 setter（`setXxxEditing(false)` / `closeEditor()` 之类
 *     不落库的本地函数）⇒ 违规；
 *   - 没有任何 `onBlur` 属性 / 文件里没有行内编辑态 ⇒ 不参与判定（不是这一族）。
 */
export function scanInlineEditorOnBlur(rawSource: string): string[] {
  const source = stripComments(rawSource)
  const stateMatch = source.match(/const\s+\[(\w*[Ee]diting)\w*\s*,\s*(set\w+)\s*\]\s*=\s*useState/)
  if (!stateMatch) return []
  const [, editingVar, setEditingVar] = stateMatch

  // 本文件里做过落库调用的函数名（`const save = async () => { ... request.patch(...) }`）
  const persists = /(request|api|\w+Api)\s*\.\s*(patch|put|post)\s*\(/
  const persistFns = new Set<string>()
  const fnRegex = /(?:const|function)\s+(\w+)\s*(?:=\s*(?:async\s*)?\([^)]*\)\s*=>|\([^)]*\)\s*\{)/g
  let fn: RegExpExecArray | null
  while ((fn = fnRegex.exec(source))) {
    const name = fn[1]
    // 取该函数体（到下一个顶层 `const|function` 或文件末）—— 足够粗，但只用于「有没有落库调用」
    const rest = source.slice(fn.index)
    const nextIdx = rest.slice(fn[0].length).search(/\n(?:const|function)\s+\w+\s*(?:=|\()/)
    const body = nextIdx === -1 ? rest : rest.slice(0, fn[0].length + nextIdx)
    if (persists.test(body)) persistFns.add(name)
  }

  const violations: string[] = []
  const onBlurRegex = /onBlur=\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g
  let m: RegExpExecArray | null
  while ((m = onBlurRegex.exec(source))) {
    const handler = m[1]
    const callsPersistFn = [...persistFns].some((name) => new RegExp(`\\b${name}\\s*\\(`).test(handler))
    if (callsPersistFn) continue
    // 只关编辑态（或什么都不做）⇒ 改动没有任何落库出口
    const closesOnly = new RegExp(`\\b${setEditingVar}\\s*\\(`).test(handler)
    if (closesOnly) {
      violations.push(
        `onBlur={${handler.trim()}} 只关闭编辑态（${setEditingVar}）而没有落库调用` +
          ` —— 同类缺陷形态：退出路径与「真的存了没有」脱钩（编辑态变量 ${editingVar}）`,
      )
    }
  }
  return violations
}

/**
 * 判据 B 的扫描器（**纯函数**）：
 * 返回「弹窗关闭发生在非条件路径（`finally`）上」的违规清单。
 */
/**
 * 剥掉注释再扫（**必须**）：本仓的注释里大量**逐字引用**缺陷形态（例如
 * `handleSaveDraftAndLeave` 的 JSDoc 写着「改前是 `finally { ... setShowLeaveModal(false) }`」）——
 * 不剥注释 ⇒ 判据被自己的说明文案喂红（实测：ProductForm.tsx 当场判红，报的却是注释里的字）。
 */
export function stripComments(source: string): string {
  // ⚠️ 必须是**字符级状态机**（不是两条正则）：正则版会把字符串里的 `//`（如
  // `'https://example.com'`）当成行注释起点，从那里把**后面的代码整段删掉** ⇒
  // 花括号配对失衡、判据恒绿。状态机认 `'` / `"` / `` ` `` / `//` / `/*`。
  let out = ''
  let i = 0
  let quote: string | null = null
  while (i < source.length) {
    const c = source[i]
    const next = source[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += next ?? ''; i += 2; continue }
      if (c === quote) quote = null
      i++
      continue
    }
    if (c === "'" || c === '"' || c === '`') { quote = c; out += c; i++; continue }
    if (c === '/' && next === '/') {
      while (i < source.length && source[i] !== '\n') i++
      continue
    }
    if (c === '/' && next === '*') {
      i += 2
      while (i < source.length && !(source[i] === '*' && source[i + 1] === '/')) i++
      i += 2
      continue
    }
    out += c
    i++
  }
  return out
}

export function scanUnconditionalModalClose(rawSource: string): string[] {
  const source = stripComments(rawSource)
  const violations: string[] = []
  // 只认「弹窗**可见性**关闭」两类 setter：`setShowXxxModal(false)` / `setXxxModalOpen(false)`。
  // ⚠️ 不要把 `set\w*Modal\w*(false)` 写成通配 —— 它会把 `setCatModalLoading(false)`
  // 这类**加载态**复位也判红（实测假红：ProductForm 的 openCatModal）。
  const closeCall = /set(?:Show)?\w*Modal(?:Open)?\(\s*false\s*\)/g
  const marker = /finally\s*\{/g
  let m: RegExpExecArray | null
  while ((m = marker.exec(source))) {
    // ⚠️ 必须做**花括号配对**：`/finally\s*\{[^}]*\}/` 会被内层 `}` 提前截断 ——
    // 实测会把本文件的 `finally {` 截成空块 ⇒ 扫不到关闭调用 ⇒ 判据 B **恒绿**
    // （守卫退化成装饰，正是本单要防的形态）。
    const braceStart = m.index + m[0].length - 1
    let depth = 0
    let end = braceStart
    for (let i = braceStart; i < source.length; i++) {
      if (source[i] === '{') depth++
      else if (source[i] === '}') {
        depth--
        if (depth === 0) { end = i; break }
      }
    }
    const block = source.slice(braceStart, end + 1)
    const calls = block.match(closeCall) || []
    for (const call of calls) {
      violations.push(
        `\`finally\` 里出现弹窗关闭调用 \`${call}\` —— 退出路径无条件执行 ⇒ ` +
          `「没提交成功」也会关弹窗（谎报已存的形态）`,
      )
    }
  }
  return violations
}

type Ledger = { claims: string[]; notes?: string }
function readLedger(): Ledger {
  if (!existsSync(LEDGER_PATH)) return { claims: [] }
  return JSON.parse(readFileSync(LEDGER_PATH, 'utf-8')) as Ledger
}

const sourceFiles = collectSourceFiles(SRC_ROOT)

describe('#6662 判据 A｜行内编辑器的 onBlur 必须指向落库路径（类级元守卫）', () => {
  it('判别力自证：坏形态判红、好形态一条不红（防止守卫退化成恒绿）', () => {
    const bad = `
      function Cell() {
        const [editing, setEditing] = useState(false)
        const save = async () => { await request.patch('/x', {}) }
        return <input onBlur={() => setEditing(false)} />
      }`
    const good = `
      function Cell() {
        const [editing, setEditing] = useState(false)
        const save = async () => { await request.patch('/x', {}) }
        return <input onBlur={save} />
      }`
    // 坏形态：只关编辑态 ⇒ 必须红
    expect(scanInlineEditorOnBlur(bad).length).toBeGreaterThanOrEqual(1)
    // 好形态：直接指向落库函数 ⇒ 必须绿
    expect(scanInlineEditorOnBlur(good)).toEqual([])
    // 对照：根本不带 onBlur 的文件**不参与判定**（不是这一族，不该被扫成红）
    expect(scanInlineEditorOnBlur('const a = 1')).toEqual([])
  })

  it('全仓零违规：任何「行内编辑态 + onBlur 只关编辑态」都必须在台账里登记（未登记即红）', () => {
    const ledger = readLedger()
    const offenders: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(process.cwd(), file)
      const violations = scanInlineEditorOnBlur(readFileSync(file, 'utf-8'))
      for (const v of violations) {
        if (ledger.claims.includes(`${rel}::${v}`)) continue
        offenders.push(`${rel}: ${v}`)
      }
    }
    expect(
      offenders,
      `未登记的「行内编辑静默退出」形态（登记进 tests/unit/inline-edit-persistence-ledger.json，` +
        `该台账只许缩短）：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('台账只许缩短：现状 = 零条目零豁免（新增条目必须在 PR body 登记）', () => {
    const ledger = readLedger()
    expect(ledger.claims).toEqual([])
  })
})

describe('#6662 判据 B｜弹窗关闭不得发生在非条件路径上（类级元守卫）', () => {
  it('判别力自证：`finally { setShowLeaveModal(false) }` 判红、条件关闭判绿', () => {
    const bad = `
      const handleSaveDraftAndLeave = async () => {
        try { await handleSubmit('draft') }
        catch { /* stay */ }
        finally { setDraftSaving(false); setShowLeaveModal(false) }
      }`
    const good = `
      const handleSaveDraftAndLeave = async () => {
        setDraftSaving(true)
        try {
          const ok = await handleSubmit('draft')
          if (!ok) return
          setShowLeaveModal(false)
        } finally { setDraftSaving(false) }
      }`
    expect(scanUnconditionalModalClose(bad).length).toBeGreaterThanOrEqual(1)
    expect(scanUnconditionalModalClose(good)).toEqual([])
  })

  it('全仓零违规：ProductForm 的弹窗关闭在条件路径上（提交成功才关）', () => {
    const file = join(SRC_ROOT, 'components/products/ProductForm.tsx')
    const violations = scanUnconditionalModalClose(readFileSync(file, 'utf-8'))
    expect(violations, `ProductForm.tsx 出现无条件关弹窗：\n${violations.join('\n')}`).toEqual([])
  })
})

// ========== 未固化 / 边界（照实登记，不粉饰）==========
//
// 1. **判据 A 只认「同一文件内的落库函数名被调用」**：`onBlur` 经由中间变量
//    （`const h = save; onBlur={h}`）或组件 props 传入的落库回调**扫不出来** ——
//    这类形态由实例判据（product-detail.test.tsx 的 #6662 两条）承担，不是留白。
// 2. **判据 A 只扫 `src/**`**：测试文件、`scripts/`、两个 Taro app（bmini / worker-h5）不在射程内；
//    小程序侧若出现同族形态，需另开单（本包文件族不含那两个 app）。
// 3. **判据 B 只认 `finally` 字面块**：其他「无条件关」的写法（如 `await f(); setShow(false)`）
//    是**语义**问题 —— 扫不出来，靠评审 + 实例判据。
// 4. 两条判据都**不跑被引用的组件**（不渲染、不连网）⇒ 结构面绿 ≠ 行为面绿；
//    行为面由 `product-detail.test.tsx` / `ProductForm.test.tsx` 的 #6662 用例承担。
