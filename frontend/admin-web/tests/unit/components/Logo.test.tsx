// case_ids: UI-082
//
// 判据：**生意管家品牌标**的结构与配色（issue #9121）。
//
// 病根：旧标是「帘成 M」（米高 / 观星台时代），与产品名「生意管家」和跨行业定位都不再相符；
// 新标 = 管家铃（服务）+ 底座（经营台面）+ 星芒（词元 / AI）。金色仍只取自 brand-palette。
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Logo from '@/components/ui/Logo'
import { gold } from '@/lib/brand-palette'

describe('Logo：管家铃结构与织金口径（issue #9121）', () => {
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
    // 背景是靛蓝渐变（两段），铃身是金色渐变（两段）—— 金色必须来自 palette
    expect(stopColors).toContain(gold[300])
    expect(stopColors).toContain(gold[600])
    // 判别力自证：palette 真值变化时本断言会跟着变
    expect(gold[300]).toBe('#f6d27a')
    expect(gold[600]).toBe('#d48806')
  })

  it('管家铃：铃身 / 底座 / 顶钮 / 星芒都在，且不再是旧的「帘成 M」路径', () => {
    const { container } = render(<Logo />)
    const html = container.innerHTML
    // 旧标的 M 形波浪底摆路径特征串
    expect(html).not.toContain('C35.2 33.4 32.8 29.8 30.2 30.4')
    // 新标的四个可核对形状：铃身曲线 / 顶钮 / 底座 / 星芒
    expect(html).toContain('M13.4 33.2 C13.4 25.4')
    expect(html).toContain('<circle cx="24" cy="17.2" r="2.3"')
    expect(html).toContain('x="11" y="34" width="26"')
    expect(html).toContain('M36.2 11.4 C36.6 13.6')
  })

  it('className 透传到 svg（外层布局要能调间距，且不得丢掉 flex-shrink-0）', () => {
    const { container } = render(<Logo className="mb-4" />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('class')).toContain('mb-4')
    expect(svg?.getAttribute('class')).toContain('flex-shrink-0')
  })
})
