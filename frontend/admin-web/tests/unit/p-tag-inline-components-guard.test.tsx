// case_ids: UI-097
// 类级元守卫（issue #6799 判据 ② 的运行期面）：凡**被放进 `<p>` 里**的组件，必须逐条认证
// （真渲染一次 ⇒ 断言它在 `<p>` 里产生的 DOM 不含块级后代），且台账与语料**双向对齐**。
//
// ## 这一条堵的是什么
// 源码扫描（`p-tag-block-nesting-guard.test.ts`）只能看到字面嵌套。真栈缺陷的形态是
// `<p>{<DateTimeCell/>}</p>` —— 源码面 0 命中，而 `DateTimeCell` 的根节点是 `<div>`
// ⇒ 浏览器就地闭合 `<p>` ⇒ React 报 `In HTML, <div> cannot be a descendant of <p>`。
// 本判据把「谁被放进 `<p>` 里」变成**现取清单**，再要求清单里每一个名字都在台账里
// 有认证 + 真渲染读数：**新组件未登记即红**（这正是"同类进不来"的机械面）。
//
// ## 判据为什么可信（红/绿都实测过）
// - 坏形态（`<p><div/></p>`）：React 在客户端渲染时同样打那两条 `console.error`
//   （实测：`asDiv=true ⇒ console.error 2 条`；`asDiv=false ⇒ 0 条`）—— 所以「渲染后断言 DOM 无块级后代」
//   与真栈读数同条件；本文件底部还有一条**判别力自证**把这条读数钉住。
// - 好形态（`<p><span/></p>`）：0 条。
//
// ## 边界（照实登记，§19.1）
// - 台账 `runtime: declared` 的条目**不真渲染**（Next 运行时组件在 vitest 里只能走 mock，
//   断言 mock 自己等于空断言）—— 该条的渲染面由真栈冒烟与 `hydration-witness` 承接，台账里逐条写明理由；
// - 组件可以带必填 props 而不被本判据渲染（`runtime: declared` 是唯一出口，且必须给 `evidence`）；
// - 判不了"文案/版式好不好看"（那是 §15.7 截图读图）。

import { describe, it, expect } from 'vitest'
import React from 'react'
import { render, cleanup } from '@testing-library/react'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AlertCircle, Check, RefreshCw, ShieldOff } from 'lucide-react'
import { InlineMarkdown } from '@/lib/inline-markdown'

const REPO_ROOT = join(process.cwd(), '..', '..')
const SCANNER = join(REPO_ROOT, 'scripts', 'jsx-p-tag-nesting-scan.mjs')
const SRC_DIR = join(process.cwd(), 'src')
const LEDGER = join(process.cwd(), 'tests', 'unit', 'p-tag-inline-components-ledger.json')

/** `<p>` 里**非法**的块级后代（判据用；与扫描器的 `BLOCK_TAGS` 同口径的 DOM 面实现）。 */
const BLOCK_IN_P = /^(DIV|SECTION|ARTICLE|ASIDE|NAV|HEADER|FOOTER|MAIN|FORM|FIELDSET|UL|OL|LI|DL|DT|DD|TABLE|THEAD|TBODY|TFOOT|TR|TD|TH|H[1-6]|P|PRE|BLOCKQUOTE|HR|FIGURE|ADDRESS|DETAILS|SUMMARY|DIALOG|MENU|HGROUP|VIDEO)$/

interface LedgerEntry {
  component: string
  source: string
  fn: string
  runtime: 'instantiated' | 'declared'
  renders: string
  evidence: string
}

/** 「组件被放进 `<p>` 里」的现取清单 + 落点（跑仓库脚本，与实例判据同源）。 */
function componentsInsideP(): { component: string; sites: string[] }[] {
  const stdout = execFileSync('node', [SCANNER, '--json', SRC_DIR], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  const hits = JSON.parse(stdout) as { file: string; line: number; tag: string; kind: string }[]
  const byComponent = new Map<string, string[]>()
  for (const h of hits) {
    if (h.kind !== 'component') continue
    byComponent.set(h.tag, [...(byComponent.get(h.tag) ?? []), `${h.file}:${h.line}`])
  }
  return [...byComponent.entries()].map(([component, sites]) => ({ component, sites })).sort((a, b) => a.component.localeCompare(b.component))
}

const ledger = (JSON.parse(readFileSync(LEDGER, 'utf8')) as { entries: LedgerEntry[] }).entries
const found = componentsInsideP()
const foundNames = found.map((f) => f.component)

/** 把被 `<p>` 包裹的组件渲染进 DOM，返回 `<p>` 里出现的块级后代标签名（空数组 = 合法）。 */
function renderInsideParagraph(element: React.ReactElement): string[] {
  const { container } = render(<p data-testid="host">{element}</p>)
  const host = container.querySelector('p[data-testid="host"]')!
  const illegal: string[] = []
  for (const el of Array.from(host.querySelectorAll('*'))) {
    if (BLOCK_IN_P.test(el.tagName)) illegal.push(el.tagName.toLowerCase())
  }
  cleanup()
  return illegal
}

describe('被放进 <p> 的组件必须认证为「渲染短语内容」（issue #6799 ②）', () => {
  it('台账非空且每条字段完整（空台账/缺字段 = 判据失效，fail-closed）', () => {
    expect(ledger.length, '台账为空 ⇒ 判据空转').toBeGreaterThan(0)
    for (const e of ledger) {
      expect(e.component, '缺 component').toBeTruthy()
      expect(e.source, `${e.component} 缺 source`).toBeTruthy()
      expect(e.fn, `${e.component} 缺 fn`).toBeTruthy()
      expect(e.evidence, `${e.component} 缺 evidence`).toBeTruthy()
      expect(['instantiated', 'declared']).toContain(e.runtime)
    }
  })

  it('语料里**新**出现在 <p> 里的组件必须在台账里（未登记即红）', () => {
    const missing = foundNames.filter((n) => !ledger.some((e) => e.component === n))
    expect(
      missing.map((n) => {
        const sites = found.find((f) => f.component === n)!.sites
        return `${n}  落点=${sites.join(', ')}`
      }),
      '这些组件被渲染在 <p> 里但未认证 ⇒ 若它渲染块级元素，就是一次整页 hydration 失败（issue #6799）',
    ).toEqual([])
  })

  it('台账不得空转：每条登记都必须在语料里现取到（台账只许缩短）', () => {
    const stale = ledger.filter((e) => !foundNames.includes(e.component)).map((e) => e.component)
    expect(stale, '台账里有、语料里已无 ⇒ 删掉该条（只许缩短，不许留冗余）').toEqual([])
  })

  it('逐条真渲染：组件在 <p> 里产生的 DOM 不得含块级后代', () => {
    const instantiated = ledger.filter((e) => e.runtime === 'instantiated')
    expect(instantiated.length, '没有任何 instantiated 条目 ⇒ 真渲染面未覆盖').toBeGreaterThan(0)
    const failures: string[] = []
    for (const entry of instantiated) {
      const element = instantiate(entry)
      const illegal = renderInsideParagraph(element)
      if (illegal.length) failures.push(`${entry.component} 在 <p> 里渲染出 ${[...new Set(illegal)].join('/')}`)
    }
    expect(failures).toEqual([])
  })

  it('判别力自证：真渲染读数对注入的坏形态会红、对好形态不报（同一条判据的对照）', () => {
    const bad = renderInsideParagraph(<div data-probe>块级</div>)
    expect(bad, '坏形态必须报出 div —— 否则真渲染判据是空断言').toContain('div')
    expect(renderInsideParagraph(<span data-probe>行内</span>)).toEqual([])
  })
})

/**
 * 依台账把条目实例化（`runtime: instantiated` 才调用）。
 * 用**静态** import（vitest 的 `@/` 别名对 CJS `require` 不生效，实测 `Cannot find module '@/lib/inline-markdown'`）。
 */
const INSTANTIABLE: Record<string, React.ComponentType<Record<string, unknown>>> = {
  AlertCircle: AlertCircle as unknown as React.ComponentType<Record<string, unknown>>,
  Check: Check as unknown as React.ComponentType<Record<string, unknown>>,
  RefreshCw: RefreshCw as unknown as React.ComponentType<Record<string, unknown>>,
  ShieldOff: ShieldOff as unknown as React.ComponentType<Record<string, unknown>>,
  InlineMarkdown: InlineMarkdown as unknown as React.ComponentType<Record<string, unknown>>,
}

function instantiate(entry: LedgerEntry): React.ReactElement {
  const Comp = INSTANTIABLE[entry.fn]
  expect(Comp, `台账登记的 ${entry.component}（fn=${entry.fn}）没有实例化分支 —— 补一条静态 import，或改成 runtime=declared 并写明 evidence`).toBeTruthy()
  const props = entry.fn === 'InlineMarkdown' ? { text: '**强调**与 `键名`' } : {}
  return React.createElement(Comp, props)
}
