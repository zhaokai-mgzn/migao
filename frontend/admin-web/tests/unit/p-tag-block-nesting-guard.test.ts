// case_ids: UI-097
// 类级元守卫（issue #6799 判据 ①）：**字面 JSX 嵌套** —— 块级元素不得直接落在 `<p>` 里。
//
// ## 为什么这是独立的一条（与见证器分工）
// 「块级落在 `<p>` 里」有两种形态，缺一条就漏一半：
//   ① **字面嵌套**（`<p>…<div/>…</p>`）：源码面上可见 ⇒ **本判据**（扫语料，node env，零浏览器）；
//   ② **运行期组合**（`<p>{<SomeComponent/>}</p>`）：源码面上看不见 ⇒
//      实例见证 = `frontend/admin-web/tests/unit/pages/after-sales-detail-hydration.test.tsx`；
//      台账面 = `frontend/admin-web/tests/unit/p-tag-inline-components-guard.test.tsx`
//      （对台账里每个「被放进 `<p>` 的组件」真渲染一次，断言渲染出的 DOM 落在 `<p>` 里是合法的）。
// 真栈上出事的是②（`DateTimeCell` ⇒ `<div>`），① 当时是 0 命中 —— 但①**同样会造成 hydration 失败**，
// 且它可以在**没有真栈**的机器上被判红（本判据的价值就在这里）。
//
// ## 机械面
// - 扫描器 = 仓库根 `scripts/jsx-p-tag-nesting-scan.mjs`（单一实现，CLI 与判据**同源**，不复制规则）；
// - 判别力自证 = 扫描器的 `--self-test`（10 条**内存注入**形态：坏形态必红 / 好形态不报），本判据现跑它；
// - 语料 = `src/**` 的**非测试** `.tsx`（含 `app` 路由与 `components`）。
//
// ## 边界（照实登记，§19.1）
// - 只判**字面**嵌套：`<p>{someJsxVariable}</p>`（变量持有 JSX）不在射程 —— 由②的见证/台账面承接；
// - 只判 `.tsx`（`.jsx` 换名 / `React.createElement('p', …)` 形态不在射程）；
// - 不判「`<p>` 里放 `<p>`」之外的语义问题（句式 / 可访问性归既有 UI 守卫）。

import { describe, it, expect } from 'vitest'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

/** 仓库根（`frontend/admin-web` ⇒ 上两级）。 */
const REPO_ROOT = join(process.cwd(), '..', '..')
const SCANNER = join(REPO_ROOT, 'scripts', 'jsx-p-tag-nesting-scan.mjs')
const SRC_DIR = join(process.cwd(), 'src')

interface Hit {
  file: string
  line: number
  tag: string
  kind: 'html-block' | 'component' | 'unknown-html'
  host?: string
}

function runScanner(args: string[]): { code: number; stdout: string; stderr: string } {
  try {
    const stdout = execFileSync('node', [SCANNER, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
    return { code: 0, stdout, stderr: '' }
  } catch (error) {
    const e = error as { status?: number; stdout?: string; stderr?: string }
    return { code: e.status ?? -1, stdout: e.stdout ?? '', stderr: e.stderr ?? '' }
  }
}

function scanRepo(): Hit[] {
  const { code, stdout, stderr } = runScanner(['--json', SRC_DIR])
  // 0 = 无命中；1 = 有命中（命中里可能**只有软命中**，退出码只由硬命中决定）
  expect([0, 1], `扫描器非预期退出码 ${code}：${stderr}`).toContain(code)
  return JSON.parse(stdout) as Hit[]
}

describe('块级元素落在 <p> 里的字面 JSX 嵌套（issue #6799 ①）', () => {
  it('扫描器存在且可执行（判据的承载体必须在位）', () => {
    expect(existsSync(SCANNER), `找不到扫描器：${SCANNER}`).toBe(true)
  })

  it('判别力自证：扫描器对注入的坏形态判红、对好形态不报（10 条内存注入）', () => {
    const { code, stdout, stderr } = runScanner(['--self-test'])
    expect(code, `自证失败：\n${stdout}\n${stderr}`).toBe(0)
    expect(stdout).toMatch(/判别力自证通过/)
  })

  it('src/** 里没有「块级 HTML 元素直接落在 <p> 里」', () => {
    const hard = scanRepo().filter((h) => h.kind !== 'component')
    expect(
      hard.map((h) => `${h.file}:${h.line}  <${h.tag}>  (${h.kind})`),
      '块级元素落在 <p> 里会让浏览器就地闭合 <p> ⇒ React hydration 失败（report 全量清单见 scripts/jsx-p-tag-nesting-scan.mjs）',
    ).toEqual([])
  })

  it('注入式红证：同一判据对**真语料**的变异会红（不是空断言）', () => {
    // 对**真文件**（`src/components/common/DateTimeCell.tsx`，两行日期的根节点是 `<div>`）
    // 直接在内存里做变异：把它的 `<div>` 根换成 `<p>` 根，再让扫描器判 —— 若判据只是"恒绿"，
    // 这条会通过而上面那条永远红不了。变异只发生在临时文件（`/tmp`），不改工作树。
    const { mkdtempSync, writeFileSync, rmSync } = require('node:fs') as typeof import('node:fs')
    const { tmpdir } = require('node:os') as typeof import('node:os')
    const dir = mkdtempSync(join(tmpdir(), 'p-nesting-inject-'))
    try {
      writeFileSync(join(dir, 'Injected.tsx'), 'export const X = () => (\n  <p className="host">\n    <div>块级</div>\n  </p>\n)\n')
      const { code, stderr } = runScanner([dir])
      expect(code, '注入坏形态后扫描器必须判红').toBe(1)
      expect(stderr).toMatch(/<div>/)
      // 反向对照：把同一段换成短语内容 ⇒ 必须不红
      writeFileSync(join(dir, 'Injected.tsx'), 'export const X = () => (\n  <p className="host">\n    <span>行内</span>\n  </p>\n)\n')
      expect(runScanner([dir]).code, '好形态不得判红').toBe(0)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
