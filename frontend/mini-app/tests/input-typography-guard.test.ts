// case_ids: MC-184
/**
 * 「C 端 H5 输入面字体族继承 + 占位符收口」守卫（issue #8575，承 #6480 的同一根因）
 *
 * ## 治的形态
 *
 * Taro H5 把 `<Input>` / `<Textarea>` 的 `className` 挂在**外层包裹元素**上
 * （`taro-input-core` / `taro-textarea-core`），真正绘字的是**内层原生控件**
 * （`input.weui-input` / `textarea.taro-textarea`）。浏览器给它们**自己的 UA 默认样式**
 * （`Arial` / `monospace` 13.33px）且**不继承**父级 ⇒ 样式只写外层 class 时，
 * 输入面的字体 / 字号 / 占位符色全部落在浏览器默认上。
 *
 * ## 唯一落点
 *
 * `frontend/mini-app/src/styles/input-center.scss`（由 `src/app.scss` 引入）：
 * ① `.weui-input` / `.taro-textarea` `font-family: inherit`；
 * ② `.taro-textarea` 另加 `font-size: inherit`；
 * ③ `::placeholder` 的**唯一**来源（`$text-secondary`，字号不写）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判什么 | 红证 |
 * |---|---|---|
 * | 1 | 共享层在位、被 `src/app.scss` 真的 `@use`，且**两个**内层控件都有 `font-family: inherit` | 删一条 ⇒ 红并具名 |
 * | 2 | 共享层**不许**写具体字体族（会改变现有视觉） | 改 `Arial` ⇒ 红 |
 * | 3 | `.taro-textarea` 必须有 `font-size: inherit`（UA 默认 13.33px 到不了内层） | 删掉 ⇒ 红 |
 * | 4 | `::placeholder` 只在共享层，且同时覆盖两个内层选择器、**不写** `font-size` | 加 `font-size` ⇒ 红 |
 * | 5 | 共享层之外**任何** scss 出现 `.taro-textarea` / `.weui-input` ⇒ 红（防逐页各写一份） | 往页面 scss 加一处 ⇒ 红并具名 |
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = process.cwd()
const SRC = join(ROOT, 'src')
const SHARED = join(SRC, 'styles', 'input-center.scss')
const APP_SCSS = join(SRC, 'app.scss')

const read = (p: string) => readFileSync(p, 'utf8')

/** 剥掉 scss 注释（引号感知：字符串里的 `//` 不是注释起点）。 */
function stripComments(source: string): string {
  let out = ''
  let quote: string | null = null
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (quote) {
      out += ch
      if (ch === '\\') { out += source[++i] ?? ''; continue }
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; out += ch; continue }
    if (ch === '/' && source[i + 1] === '*') {
      const end = source.indexOf('*/', i + 2)
      i = end < 0 ? source.length : end + 1
      continue
    }
    if (ch === '/' && source[i + 1] === '/') {
      const end = source.indexOf('\n', i)
      i = end < 0 ? source.length : end - 1
      continue
    }
    out += ch
  }
  return out
}

function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, acc)
    else if (p.endsWith('.scss')) acc.push(p)
  }
  return acc
}

const sharedCode = () => stripComments(read(SHARED))

/** 从 `选择器 { … }` 里取一段规则体（够用即可：本判据只看单层块）。 */
function block(code: string, selector: string): string | null {
  const idx = code.indexOf(selector)
  if (idx < 0) return null
  const open = code.indexOf('{', idx)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < code.length; i++) {
    if (code[i] === '{') depth++
    else if (code[i] === '}') {
      depth--
      if (depth === 0) return code.slice(idx, i + 1)
    }
  }
  return null
}

describe('C 端 H5 输入面字体族 / 占位符收口（issue #8575）', () => {
  it('① 共享层在位、被 app.scss 真的引入，且 `.weui-input, .taro-textarea` 都 `font-family: inherit`', () => {
    const app = stripComments(read(APP_SCSS))
    expect(app).toContain("styles/input-center.scss")

    const code = sharedCode()
    const inner = block(code, '.weui-input,')
    // 缺了就以「null」失败，报错里能看到是哪一个断言（jest 的 expect 不收第二参数）
    expect(inner).toContain('font-family: inherit')
    expect(inner).toContain('.taro-textarea')
  })

  it('② 共享层不许写具体字体族（会改变现有视觉）', () => {
    const code = sharedCode()
    const concrete = [...code.matchAll(/font-family:\s*([^;}]+)/g)]
      .map((m) => m[1].trim())
      .filter((v) => v !== 'inherit')
    expect(concrete).toEqual([])
  })

  it('③ textarea 必须有 font-size: inherit（UA 默认 13.33px monospace 到不了内层）', () => {
    const code = sharedCode()
    // `.taro-textarea` 出现在两个块里（字体族那条是 `.weui-input, .taro-textarea {`），
    // 这里要的是**带 font-size: inherit 的**那一条 ⇒ 逐块找，不能只看第一次出现。
    const blocks = [...code.matchAll(/\.taro-textarea\s*\{([^}]*)\}/g)].map((m) => m[1])
    expect(blocks.some((b) => /font-size:\s*inherit/.test(b))).toBe(true)
  })

  it('④ `::placeholder` 覆盖两个内层选择器、取 `$text-secondary`、不写 font-size', () => {
    const code = sharedCode()
    const ph = block(code, '.weui-input::placeholder')
    expect(ph).toContain('.taro-textarea::placeholder')
    expect(ph).toContain('$text-secondary')
    expect(ph).not.toMatch(/font-size:/)
  })

  it('⑤ 共享层之外任何 scss 出现 `.taro-textarea` / `.weui-input` ⇒ 红（防逐页各写一份）', () => {
    const leaks = walk(SRC)
      .filter((p) => p !== SHARED)
      .flatMap((p) => {
        const code = stripComments(read(p))
        return /\.taro-textarea|\.weui-input/.test(code)
          ? [`${relative(ROOT, p)}`]
          : []
      })
    expect(leaks).toEqual([])
  })
})
