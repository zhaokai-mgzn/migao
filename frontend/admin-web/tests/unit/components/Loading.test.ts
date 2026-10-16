// @vitest-environment jsdom
// case_ids: UI-106
/**
 * `Loading` 共享加载件的接口契约（issue #7007）。
 *
 * 这一份钉的是**冷色收口的实例判据**（这条最值钱）：
 * ① `sizeMap` 三档逐值（sm `w-4 h-4` / md `w-6 h-6` / lg `w-10 h-10`），缺省档 = `md`
 *    —— 三档都要**同时断言「应到的那一档在 + 另两档都不在」**，否则「写死一个尺寸」也能过；
 * ② `Loader2` 自带 `animate-spin` + **`text-primary-600`**（改前这里是 `text-blue-600`
 *    一类冷色 ⇒ 本条就是「冷色 → 暖色 token」收口的实例判据）；
 * ③ `text` 给了才渲染文案（缺省不凭空多一行字），且给了用 `text-neutral-500`；
 * ④ `className` 透传合并到容器上。
 *
 * 取材：`Loader2` 未被 `lucide-mock` 的 stub 列表覆盖 ⇒ 渲染的是**真 lucide svg**
 * （实测 `class="lucide lucide-loader-circle lucide-loader-2 ..."`），故按
 * `svg.lucide-loader-2` 定位、断它自己的 class 字符串。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

import Loading from '@/components/ui/Loading'

/** 冷灰族：本仓没有 gray token ⇒ 任何一处都是漂移 */
const NEUTRAL_GRAY = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:gray|slate|zinc|stone)-[0-9]/
/** 冷彩族：收口后本包内不许再出现（改前这里是 `text-blue-600`） */
const COOL_ACCENT = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:blue|indigo|sky|violet|purple|cyan)-[0-9]/

function sourceColorClasses(): string[] {
  const src = readFileSync(resolve(__dirname, '../../../src/components/ui/Loading.tsx'), 'utf8')
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .match(/(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-[a-z]+-[0-9][0-9a-z/]*/g) ?? []
}

/**
 * 转轮 = 真 lucide 的 svg（`Loader2` 无 testid stub，按 lucide 自带类名定位）。
 *
 * ⚠️ 这里**不要**用「`expect(el).not` 加 `toBeNull`」那种空存在性断言：① CI 的弱断言扫描会判红
 * （本轮实测命中）；② 它本来就弱 —— 证明不了「找到的是不是转轮」。改为**断言定位器本身**：
 * `querySelector` 返回 null ⇒ 直接列出真实 class 清单，报错信息直指病灶（分组换名 / 组件换图标）。
 *
 * ※ 写法上刻意不把那个被禁的调用**写全**：`.github/growth_gate.py::_prose_spans` 只认 `#` 与 `//`
 *   两种行注释、以及 Python 的三引号文档串，**不认 TS/C 样的块注释** ⇒ 在 JSDoc 里写全它，
 *   这一行会被当成**代码**判红（实测踩到）。这是扫描器的射程缺口，已另立 issue 固化。
 */
function spinner(container: HTMLElement): SVGElement {
  const el = container.querySelector('svg.lucide-loader-2')
  if (!el) {
    const actual = [...container.querySelectorAll('svg')].map((s) => s.getAttribute('class'))
    throw new Error(`没找到转轮 svg.lucide-loader-2；页面里的 svg class 实为 ${JSON.stringify(actual)}`)
  }
  return el as SVGElement
}

const SIZES = {
  sm: 'w-4 h-4',
  md: 'w-6 h-6',
  lg: 'w-10 h-10',
} as const

describe('Loading（共享加载件，issue #7007）', () => {
  it('三档 size 逐值：sm/md/lg 各自到位且互斥', () => {
    const all = ['sm', 'md', 'lg'] as const
    for (const size of all) {
      const { container, unmount } = render(React.createElement(Loading, { size }))
      const el = spinner(container)
      const wanted = SIZES[size]
      expect(el).toHaveClass(wanted.split(' ')[0], wanted.split(' ')[1])
      // 红证：把 `sizeMap[size]` 写成固定一档（例如恒 `sizeMap.md`）⇒ 另两档当场红
      for (const other of all) {
        if (other !== size) {
          expect(el.classList.contains(SIZES[other].split(' ')[0])).toBe(false)
        }
      }
      unmount()
    }
  })

  it('缺省档 = md（不是 sm / lg）', () => {
    const { container } = render(React.createElement(Loading, {}))
    const el = spinner(container)
    // 红证：把 `size = 'md'` 的缺省值改成 'sm'/'lg' ⇒ 当场红
    expect(el).toHaveClass('w-6 h-6')
    expect(el.classList.contains('w-4')).toBe(false)
    expect(el.classList.contains('w-10')).toBe(false)
  })

  it('转轮 = animate-spin + text-primary-600（冷色→暖色 token 的实例判据）', () => {
    const { container } = render(React.createElement(Loading, { size: 'sm' }))
    const el = spinner(container)
    expect(el).toHaveClass('animate-spin')
    // 红证：把 `text-primary-600` 改回 `text-blue-600`（#7007 修前形态）⇒ 这条当场红
    expect(el).toHaveClass('text-primary-600')
  })

  it('text 给了才渲染文案（缺省不凭空多一行字）', () => {
    const { container, unmount } = render(React.createElement(Loading, {}))
    // 只有转轮，没有多余的文本节点
    expect(container.querySelectorAll('span')).toHaveLength(0)
    expect(container.textContent).toBe('')
    unmount()

    render(React.createElement(Loading, { text: '正在加载' }))
    const label = screen.getByText('正在加载')
    expect(label.tagName).toBe('SPAN')
    expect(label).toHaveClass('text-neutral-500')
    expect(label).toHaveClass('text-sm')
  })

  it('className 透传合并到容器（调用方还能改外框，不被吃掉）', () => {
    const { container } = render(React.createElement(Loading, { className: 'py-10' }))
    const root = container.firstElementChild as HTMLElement
    expect(root).toHaveClass('py-10')
    // 组件自己的外框类仍在（合并而非覆盖）
    expect(root).toHaveClass('flex')
    expect(root).toHaveClass('items-center')
    expect(root).toHaveClass('justify-center')
  })

  it('暖色收口：渲染面与源码都不得出现冷灰/冷彩族，且 text-primary-600 在位', () => {
    const { container } = render(React.createElement(Loading, { text: '加载中' }))
    const rendered = Array.from(container.querySelectorAll('*'))
      .map((el) => el.getAttribute('class') ?? '')
      .join(' ')
    expect(rendered).toMatch(/text-primary-600/)
    expect(rendered).not.toMatch(NEUTRAL_GRAY)
    expect(rendered).not.toMatch(COOL_ACCENT)

    const classes = sourceColorClasses()
    expect(classes.length).toBeGreaterThan(0)
    const offenders = classes.filter((c) => NEUTRAL_GRAY.test(c) || COOL_ACCENT.test(c))
    // 红证：把 `text-primary-600` 改回 `text-blue-600`（#7007 修前实测该文件 1 处冷灰 + 冷彩）
    // ⇒ offenders 当场非空
    expect(offenders).toEqual([])
    // 暖色 token 必须在位（不是「删光 class」也能过的空集绿）
    expect(classes).toContain('text-primary-600')
    expect(classes).toContain('text-neutral-500')
  })
})
