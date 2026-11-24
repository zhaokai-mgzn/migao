// case_ids: UI-082
//
// 判据：**生意管家品牌标**的结构与配色（issue #9121）。
//
// 病根：旧标是「帘成 M」；第一版重做是「管家铃」，第二版试过五笔「生」。
// 用户 2026-11-24 反馈「重新设计 logo 要求简洁 有设计感又立意深远」⇒ 收敛到「旦」字方印：
// 日（金圆）出地平线（金线）= 天明 / 日复一日 / 生意如日初升；两笔，缩到 28px 仍能读。
// 金色仍只取自 brand-palette。
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Logo from '@/components/ui/Logo'
import { gold } from '@/lib/brand-palette'

describe('Logo：旦字方印结构与织金口径（issue #9121）', () => {
  it('三档尺寸逐值确定（small/medium/large = 28/36/56），默认 medium', () => {
    const { container: small } = render(<Logo size="small" />)
    const { container: medium } = render(<Logo />)
    const { container: large } = render(<Logo size="large" />)
    expect(small.querySelector('svg')?.getAttribute('width')).toBe('28')
    expect(medium.querySelector('svg')?.getAttribute('width')).toBe('36')
    expect(large.querySelector('svg')?.getAttribute('width')).toBe('56')
  })

  it('金色渐变 = brand-palette 的 gold[300] → gold[600]（不是本文件里的第二份字面量）', () => {
    const { container } = render(<Logo />)
    const stopColors = [...container.innerHTML.matchAll(/stop-color="([^"]+)"/g)].map((m) => m[1])
    expect(stopColors).toContain(gold[300])
    expect(stopColors).toContain(gold[600])
    expect(gold[300]).toBe('#f6d27a')
    expect(gold[600]).toBe('#d48806')
  })

  it('旦字方印：金圆 + 金线都在，且旧「帘成 M」/ 管家铃 / 五笔「生」都不得回流', () => {
    const { container } = render(<Logo />)
    const html = container.innerHTML
    // 旧「帘成 M」的波浪底摆路径特征串
    expect(html).not.toContain('C35.2 33.4 32.8 29.8 30.2 30.4')
    // 第一版管家铃的铃身 / 底座特征串
    expect(html).not.toContain('M13.4 33.2 C13.4 25.4')
    expect(html).not.toContain('x="11" y="34" width="26"')
    // 第二版五笔「生」的笔画特征串
    expect(html).not.toContain('M18.6 17.2 L23.2 14.8')
    expect(html).not.toContain('M24 15 V32.9')
    // 新标两笔：日（圆） + 一（地平线）
    expect(html).toContain('<circle cx="24" cy="20.5" r="7.6"')
    expect(html).toContain('M10 34.5 H38')
  })

  it('className 透传到 svg（外层布局要能调间距，且不得丢掉 flex-shrink-0）', () => {
    const { container } = render(<Logo className="mb-4" />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('class')).toContain('mb-4')
    expect(svg?.getAttribute('class')).toContain('flex-shrink-0')
  })
})
