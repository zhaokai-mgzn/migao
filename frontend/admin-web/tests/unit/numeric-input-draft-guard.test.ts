// case_ids: UI-141
/**
 * 类级元守卫（issue #8003）：**数值输入框不许在 `onChange` 里 `Number(target.value)` 往返**。
 *
 * ## 病灶（用户 2026-10-28 逐字，附截图）
 *
 * > 「这里的输入框不允许输入小数点，这里应该要支持 3 位小数，后续要注意，**已经发现几次新增的输入框
 * > 都不支持输入小数点，这个默认开发规则是不符合实际业务需要的**」
 *
 * 机制不是「某个写法不好看」，而是**受控组件把草稿当数字写回**：
 *
 * ```tsx
 * value={formatDraft(item.value)}
 * onChange={(e) => onChange({ value: Number(e.target.value) })}   // Number('0.') === 0
 * ```
 *
 * `Number('0.')` / `parseFloat('.')` 都会把**输入中的中间态**（`0.` / `.` / `-`）归一成数字，
 * React 再把归一后的值写回 DOM ⇒ **小数点当场消失**，`0.145` 这类三位小数永远打不出来。
 * 仓库里的唯一正确口径是 `frontend/admin-web/src/components/ui/NumberInput.tsx`
 * （`type="text"` + `inputMode="decimal"` + 内部字符串草稿，issue #5198 / #5210 已把坑趟平）。
 *
 * ## 判据（会红）
 *
 * 扫描三个前端包的 `src/**` 里每个 `<input …>` **开标签**：若其（内联）`onChange` 里出现
 * `Number(...target.value)` / `parseFloat(...target.value)` / `parseInt(...target.value)`
 * （含 `e.currentTarget.value` / 跨行）⇒ red。零容忍、**不开台账**：
 * 落地时全仓只有 1 处（本单修的那一处），`<select onChange={…Number(e.target.value)}>`（分页条数）
 * 不是输入框、不受影响。
 *
 * 红证：把 `CuttingHeightConfigPanel` 的取值框改回手写 `Number(e.target.value)` ⇒ 真语料扫描当场红。
 * 负例（必须**不**命中）：`<select>` 上的同一写法 · `NumberInput` 的 `onChange={(v) => …}` ·
 * `<input type="number">` 但**不做** `Number` 往返（本判据不判它，见边界）。
 *
 * ## 边界（如实登记，§19.1）
 *
 * 1. **不判 `type="number"` 本身**：它是否有小数录入问题取决于**有没有受控回写**，静态文本判不出来
 *    （存量 14 处真实使用，含涉钱面 ⇒ 另开审计单逐处真机复验，见 issue #8003 的「已登记的边界」）。
 * 2. **不追数据流**：经中间变量 / `{...props}` 展开传入的数值接线不在射程内。
 * 3. **不判「该不该用 NumberInput」**：只判「输入框的 onChange 有没有数字往返」这一条**机制**；
 *    其它形态（`value={String(x)}` 配 `Number` 之外的手写解析）由 review 兜。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, sep } from 'node:path'

/** 三个前端包的 `src/**`（相对 `frontend/admin-web` 的 cwd）；不存在的包跳过。 */
const ROOTS = ['src', '../mini-app/src', '../bmini-app/src']

/** 数字往返：`Number(` / `parseFloat(` / `parseInt(` 作用在 `…target.value` 上（含 `currentTarget`） */
const ROUNDTRIP_RE = /\b(?:Number|parseFloat|parseInt)\s*\(\s*[\w.[\]'"]*\.(?:currentTarget|target)\.value\b/

/** 收集 `<input …>` **开标签**（花括号 / 圆括号配平；`onChange={(e) => …}` 里的 `>` 不算结束）。 */
export function inputTags(text: string): string[] {
  const out: string[] = []
  let i = 0
  while (i < text.length) {
    const start = text.indexOf('<input', i)
    if (start === -1) break
    const after = text[start + '<input'.length]
    // `<inputs>` / `<inputXxx` 不是 input 标签
    if (after !== undefined && /[A-Za-z0-9_-]/.test(after)) {
      i = start + '<input'.length
      continue
    }
    let depth = 0
    let quote: string | null = null
    let j = start
    for (; j < text.length; j++) {
      const c = text[j]
      if (quote) {
        if (c === '\\') j++
        else if (c === quote) quote = null
        continue
      }
      if (c === '"' || c === "'" || c === '`') {
        quote = c
        continue
      }
      if (c === '{') depth++
      else if (c === '}') depth--
      else if (c === '>' && depth === 0) {
        j++
        break
      }
    }
    out.push(text.slice(start, j))
    i = j
  }
  return out
}

/** 规则本体（纯函数，可内存注入取证）：返回「在 `<input>` 的 onChange 里做数字往返」的位置。 */
export function roundtripViolations(files: { rel: string; text: string }[]): string[] {
  const bad: string[] = []
  for (const file of files) {
    for (const tag of inputTags(file.text)) {
      if (ROUNDTRIP_RE.test(tag)) {
        bad.push(`${file.rel}::${tag.slice(0, 90).replace(/\s+/g, ' ')}…`)
      }
    }
  }
  return bad
}

function walk(root: string, abs: string, out: { rel: string; text: string }[]): void {
  for (const name of readdirSync(abs)) {
    const full = join(abs, name)
    if (statSync(full).isDirectory()) walk(root, full, out)
    else if (/\.tsx$/.test(name)) out.push({ rel: `${root}/${name}`, text: readFileSync(full, 'utf8') })
  }
}

function realFiles(): { rel: string; text: string }[] {
  const out: { rel: string; text: string }[] = []
  for (const root of ROOTS) {
    const abs = join(process.cwd(), root.split('/').join(sep))
    try {
      if (statSync(abs).isDirectory()) walk(root, abs, out)
    } catch {
      // 该包不在本工作区（例如只检出 admin-web）⇒ 跳过，不判红
    }
  }
  return out
}

describe('数值输入框的草稿口径（issue #8003 / UI-138）', () => {
  it('① 真语料零命中：`<input>` 的 onChange 里没有 Number/parseFloat(target.value) 往返', () => {
    const files = realFiles()
    // 扫描面非空自证（看不见 ⇒ 判据在扫空气）
    expect(files.length).toBeGreaterThan(200)
    expect(roundtripViolations(files)).toEqual([])
  })

  it('② 红证：三种往返形态都必须被判出', () => {
    const samples = [
      { rel: 'a.tsx', text: '<input value={v} onChange={(e) => setV(Number(e.target.value))} />' },
      { rel: 'b.tsx', text: '<input value={v} onChange={(e) => setV(parseFloat(e.currentTarget.value))} />' },
      {
        rel: 'c.tsx',
        text: '<input\n  value={v}\n  onChange={(e) =>\n    setV(e.target.value === "" ? null : Number(e.target.value))\n  }\n/>',
      },
    ]
    expect(roundtripViolations(samples)).toHaveLength(3)
  })

  it('③ 负例：`<select>` / `NumberInput` / 不做数字往返的 `<input>` 一律不判红', () => {
    const ok = [
      { rel: 'a.tsx', text: '<select value={n} onChange={(e) => setN(Number(e.target.value))} />' },
      { rel: 'b.tsx', text: '<NumberInput value={v} onChange={(n) => setV(n)} />' },
      { rel: 'c.tsx', text: '<input type="text" value={v} onChange={(e) => setV(e.target.value)} />' },
      { rel: 'd.tsx', text: '<input type="number" value={v} onChange={(e) => setV(e.target.value)} />' },
      { rel: 'e.tsx', text: '<input value={v} onChange={() => setV(Number(0.145))} />' },
    ]
    expect(roundtripViolations(ok)).toEqual([])
  })

  it('④ 本判据的靶心用例：裁高配置面板的取值框走 NumberInput（不受手写往返影响）', () => {
    const panel = readFileSync(
      join(process.cwd(), 'src', 'components', 'production', 'CuttingHeightConfigPanel.tsx'),
      'utf8',
    )
    expect(panel).toContain("import NumberInput from '@/components/ui/NumberInput'")
    expect(panel).toContain('decimals={3}')
    expect(roundtripViolations([{ rel: 'panel.tsx', text: panel }])).toEqual([])
  })
})
