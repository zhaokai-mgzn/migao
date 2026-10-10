// case_ids: UI-082
//
// 判据：**Logo 的织金渐变取自单一真值源**（issue #6665 第 6 条）。
//
// 病根：Logo 此前在 SVG 里写死 `#FFC53D` → `#D48806`，而三份官网页面又各写一份金色任意值
// ⇒ 四个金各写各的；改一处必然漂移。
// 现口径：色值只在 `src/lib/brand-palette.ts`（`tailwind.config.ts` 也读它，页面用 token 类）。
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Logo from '@/components/ui/Logo'
import { gold } from '@/lib/brand-palette'

describe('Logo：尺寸与织金渐变口径（issue #6665）', () => {
  it('三档尺寸逐值确定（small/medium/large = 28/36/56），默认 medium', () => {
    const { container: small } = render(<Logo size="small" />)
    const { container: medium } = render(<Logo />)
    const { container: large } = render(<Logo size="large" />)
    expect(small.querySelector('svg')?.getAttribute('width')).toBe('28')
    expect(medium.querySelector('svg')?.getAttribute('width')).toBe('36')
    expect(large.querySelector('svg')?.getAttribute('width')).toBe('56')
  })

  it('渐变色 = brand-palette 的 gold[400] → gold[600]（不是本文件里的第二份字面量）', () => {
    const { container } = render(<Logo />)
    // 读 HTML 字面量：React 会把 SVG 属性序列化成 kebab-case（`stop-color`），
    // 且 jsdom 对 SVG stop 的 DOM 查询在不同版本下行为不一（实测 querySelectorAll 返回空）。
    const stopColors = [...container.innerHTML.matchAll(/stop-color="([^"]+)"/g)].map((m) => m[1])
    expect(stopColors).toEqual([gold[400], gold[600]])
    // 判别力自证：这两个值不等于「随手写一个金色」也能过 —— 它们就是 palette 里的键
    expect(gold[400]).toBe('#ffc53d')
    expect(gold[600]).toBe('#d48806')
  })

  it('className 透传到 svg（外层布局要能调间距，且不得丢掉 flex-shrink-0）', () => {
    const { container } = render(<Logo className="mb-4" />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('class')).toContain('mb-4')
    expect(svg?.getAttribute('class')).toContain('flex-shrink-0')
  })
})
