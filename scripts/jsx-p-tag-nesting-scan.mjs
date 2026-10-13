#!/usr/bin/env node
/**
 * 扫「块级元素落在 `<p>` 里」的字面 JSX 嵌套（issue #6799 判据 ① 的实例面）。
 *
 * ## 为什么需要它
 * `<p>` 在 HTML 里是**短语内容**容器：块级元素（`div` / `section` / `ul` / `table` / `h1`~`h6` …）
 * 落在里面时，**浏览器解析器会就地闭合 `<p>`**（`<p><div>x</div></p>` 解析成
 * `<p></p><div>x</div><p></p>`）⇒ 服务端 HTML 与 React 客户端树形状不一致 ⇒ React 报
 * `In HTML, <div> cannot be a descendant of <p>` + `Hydration failed`，**整页 hydration 失败**
 * （不是渲染慢，是后续交互全走未 hydrate 的 SSR DOM）。
 *
 * 本扫描器覆盖该族的**形态 ①：字面 JSX 嵌套**（`<p>…<div/>…</p>`）。
 * **形态 ②：运行期组合**（`<p>{<SomeComponent/>}</p>`，SomeComponent 自己渲染块级）**不在射程内**
 * —— 字面扫描看不到被引用组件的渲染结果，必须靠真浏览器（React 的 `validateDOMNesting` 打
 * `console.error`）。两条判据都必须在，缺一条就漏一半（见 PR body「固化声明」）：
 *   - 形态 ① 本扫描器 → `frontend/admin-web/tests/unit/p-tag-block-nesting-guard.test.ts`（vitest，常驻 CI）
 *   - 形态 ② SSR→hydrate 见证 → `frontend/admin-web/tests/unit/after-sales-detail-hydration.test.tsx`
 *
 * ## 用法
 * ```
 * node scripts/jsx-p-tag-nesting-scan.mjs <目录…>          # 人读：逐条打印命中
 * node scripts/jsx-p-tag-nesting-scan.mjs --json <目录…>   # 机器读：JSON
 * ```
 * 退出码三态：`0` = 无命中；`1` = 有命中（逐条列文件::行号::标签）；`3` = 调用方式不对（无法判定）。
 *
 * ## 判别力自证（判据自己也要会红）
 * 扫描器内含 `--self-test`：对**内存里注入**的坏形态判红、对好形态不报。
 * ```
 * node scripts/jsx-p-tag-nesting-scan.mjs --self-test
 * ```
 * 不写盘、不改语料 —— 注入只发生在内存字符串上。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { pathToFileURL } from 'node:url'

/** 落在 `<p>` 里必然非法的**块级**HTML 标签（HTML 规范的 flow/phrasing 之分）。 */
export const BLOCK_TAGS = new Set([
  'div', 'section', 'article', 'aside', 'nav', 'header', 'footer', 'main', 'figure', 'figcaption',
  'form', 'fieldset', 'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tfoot',
  'tr', 'td', 'th', 'caption', 'colgroup', 'col', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p',
  'pre', 'blockquote', 'hr', 'address', 'details', 'summary', 'dialog', 'menu', 'hgroup', 'video',
])

/** `<p>` 里**合法**的短语内容标签（白名单；不在白名单里的标签名 ⇒ 按「未知」处理，fail-closed）。 */
export const PHRASING_TAGS = new Set([
  'a', 'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'data', 'dfn', 'em', 'i', 'kbd', 'mark',
  'q', 'rp', 'rt', 'ruby', 's', 'samp', 'small', 'span', 'strong', 'sub', 'sup', 'time', 'u', 'var',
  'wbr', 'img', 'picture', 'source', 'svg', 'math', 'button', 'input', 'label', 'select', 'textarea',
  'output', 'progress', 'meter', 'canvas', 'audio', 'map', 'area', 'del', 'ins', 'bdo', 'nobr',
])

/** 跳过字符串字面量（`'` / `"` / `` ` ``，含转义）。返回结束后的下标。 */
function skipString(src, i) {
  const quote = src[i]
  i++
  while (i < src.length) {
    if (src[i] === '\\') { i += 2; continue }
    if (src[i] === quote) return i + 1
    i++
  }
  return i
}

/**
 * 扫描一段 TSX/JSX 源码，返回落在 `<p>` 里的非短语内容。
 * @param {string} src
 * @param {string} file 用于报错的文件名（仓库相对路径）
 * @returns {{file: string, line: number, tag: string, kind: 'html-block'|'unknown'|'component'}[]}
 */
export function scanSource(src, file = '<inline>') {
  const hits = []
  // 栈：{ kind: 'el'|'expr'|'attr', name?: string, line?: number }
  const stack = [{ kind: 'el', name: '', line: 1 }]   // 根
  let inTag = false
  let i = 0
  const lineOf = (pos) => src.slice(0, pos).split('\n').length
  const openTag = () => {
    for (let k = stack.length - 1; k >= 0; k--) if (stack[k].kind === 'el') return stack[k]
    return null
  }
  /** 当前最近的**组件**宿主（用于把软命中归到一处登记；`<p>` 自身也算一个宿主）。 */
  const hostComponent = () => {
    for (let k = stack.length - 1; k >= 0; k--) {
      const t = stack[k]
      if (t.kind === 'el' && t.name && /^[A-Z]/.test(t.name)) return t.name
    }
    return '(模块顶层)'
  }
  const popToContainer = () => {
    while (stack.length > 1) {
      const t = stack.pop()
      if (t.kind === 'expr' || t.kind === 'attr') return
    }
  }

  while (i < src.length) {
    const c = src[i]
    if (c === '"' || c === "'" || c === '`') { i = skipString(src, i); continue }
    // 注释
    if (c === '/' && src[i + 1] === '/') { while (i < src.length && src[i] !== '\n') i++; continue }
    if (c === '/' && src[i + 1] === '*') { const e = src.indexOf('*/', i + 2); i = e === -1 ? src.length : e + 2; continue }
    // 闭合标签
    if (c === '<' && src[i + 1] === '/') {
      const m = /^<\/\s*([A-Za-z_$][\w.$:-]*)?\s*>/.exec(src.slice(i))
      if (m) {
        i += m[0].length
        while (stack.length > 1) { const t = stack.pop(); if (t.kind === 'el') break }
        inTag = false
        continue
      }
      i++; continue
    }
    // 开启标签 / 片段
    if (c === '<' && /[A-Za-z_$>]/.test(src[i + 1] || '')) {
      const m = /^<([A-Za-z_$][\w.$:-]*)?/.exec(src.slice(i))
      const name = m[1] || ''                       // '' = 片段 `<>`
      let j = i + m[0].length
      let depth = 0
      let selfClose = false
      while (j < src.length) {
        const ch = src[j]
        if (ch === '"' || ch === "'" || ch === '`') { j = skipString(src, j); continue }
        if (ch === '{') { depth++; j++; continue }
        if (ch === '}') { depth--; j++; continue }
        if (depth === 0 && ch === '/' && src[j + 1] === '>') { selfClose = true; j += 2; break }
        if (depth === 0 && ch === '>') { j++; break }
        j++
      }
      const parent = openTag()
      // JSX 自闭合 `<div />` 在浏览器里同样产出 `<div></div>` ⇒ 同样会就地闭合 <p>，不豁免
      if (parent && parent.name === 'p') {
        const lower = name.toLowerCase()
        const isBlock = BLOCK_TAGS.has(lower)
        const isComponent = /^[A-Z]/.test(name)
        const isKnownPhrasing = !name || PHRASING_TAGS.has(lower)
        if (isBlock) hits.push({ file, line: lineOf(i), tag: name, kind: 'html-block' })
        else if (isComponent) hits.push({ file, line: lineOf(i), tag: name, kind: 'component', host: hostComponent() })
        else if (name && !isKnownPhrasing) hits.push({ file, line: lineOf(i), tag: name, kind: 'unknown-html' })
      }
      if (!selfClose) stack.push({ kind: 'el', name, line: lineOf(i) })
      inTag = false
      i = j
      continue
    }
    // 表达式容器 / 属性表达式
    if (c === '{') { stack.push({ kind: inTag ? 'attr' : 'expr' }); i++; continue }
    if (c === '}') { popToContainer(); i++; continue }
    if (c === '<') { inTag = true; i++; continue }
    inTag = false
    i++
  }
  return hits
}

/** 递归列出目录下的**测试** `.tsx`（判据自己也要扫：`<p>` 判据的夹具同样是语料）。 */
export function listTestTsx(root) {
  const out = []
  ;(function walk(dir) {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry === '.next' || entry.startsWith('.')) continue
      const p = join(dir, entry)
      const st = statSync(p)
      if (st.isDirectory()) walk(p)
      else if (/\.test\.tsx$/.test(p)) out.push(p)
    }
  })(root)
  return out
}

/** 递归列出目录下的非测试 `.tsx`（跳过 node_modules / .next / 隐藏目录）。 */
export function listTsx(root) {
  const out = []
  ;(function walk(dir) {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry === '.next' || entry.startsWith('.')) continue
      const p = join(dir, entry)
      const st = statSync(p)
      if (st.isDirectory()) walk(p)
      else if (/\.tsx$/.test(p) && !/\.test\.tsx$/.test(p)) out.push(p)
    }
  })(root)
  return out
}

/** 对一组文件跑扫描，返回全部命中（file 为相对 `root` 的路径）。 */
export function scanFiles(root, files = listTsx(root)) {
  return files.flatMap((f) => scanSource(readFileSync(f, 'utf8'), relative(root, f)))
}

// ── 判别力自证：注入式（内存字符串，不落盘）──────────────────────────────
const SELF_TEST_CASES = [
  // 每条：[名字, 源码, 期望命中数]
  ['字面块级嵌套（坏）', '<p className="a">\n  <div>x</div>\n</p>', 1],
  ['字面块级自闭合（坏）', '<p><section /></p>', 1],
  ['表达式里的块级（坏）', '<p>{cond ? <ul><li>a</li></ul> : null}</p>', 1],
  ['组件落在 p 里（软命中：需 SSR 见证复核）', '<p><Foo /></p>', 1],
  ['片段在 p 里（不算命中）', '<p><>text</></p>', 0],
  ['短语内容（好）', '<p>text <span>s</span> <a href="#">l</a> <code>c</code></p>', 0],
  ['块级在 p 外（好）', '<div>\n  <p>text</p>\n  <div>x</div>\n</div>', 0],
  ['嵌套在字符串里（好-不误报）', 'const a = "<p><div>x</div></p>"', 0],
  ['注释里（好-不误报）', '// <p><div>x</div></p>\nconst a = 1', 0],
  ['组件在 p 外（好）', '<div>\n  <p>t</p>\n  <DateTimeCell value={a} />\n</div>', 0],
]

export function selfTest() {
  const failures = []
  for (const [name, src, want] of SELF_TEST_CASES) {
    const got = scanSource(src, name).length
    if (got !== want) failures.push(`${name}: 期望命中 ${want}，实测 ${got}`)
  }
  return failures
}

// ── CLI（仅在作为入口执行时跑；被 import 时不自执行）────────────────────
const IS_ENTRY = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
const argv = process.argv.slice(2)
if (IS_ENTRY && argv.includes('--self-test')) {
  const failures = selfTest()
  if (failures.length) {
    console.error('✗ 判别力自证失败（扫描器自身退化）：')
    for (const f of failures) console.error('  - ' + f)
    process.exit(1)
  }
  console.log(`✓ 判别力自证通过（${SELF_TEST_CASES.length} 条注入形态：坏形态必红、好形态不报）`)
  process.exit(0)
}
const dirs = argv.filter((a) => !a.startsWith('--'))
if (!IS_ENTRY) {
  // 被 import：不跑 CLI
} else if (!dirs.length) {
  console.error('用法: node scripts/jsx-p-tag-nesting-scan.mjs [--json] <目录…>')
  process.exit(3)
} else {
const all = dirs.flatMap((d) => scanFiles(d))
const hard = all.filter((h) => h.kind !== 'component')
if (argv.includes('--json')) {
  console.log(JSON.stringify(all, null, 2))
} else {
  for (const h of all) console.error(`${h.kind === 'component' ? '·' : '✗'} ${h.file}:${h.line}  <${h.tag}>  (${h.kind})`)
  console.log(`硬命中（块级 / 未知 HTML 落在 <p> 里）=${hard.length}，软命中（组件落在 <p> 里，需 SSR 见证复核）=${all.length - hard.length}`)
}
process.exit(hard.length ? 1 : 0)
}
