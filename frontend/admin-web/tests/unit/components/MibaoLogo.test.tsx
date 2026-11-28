// case_ids: UI-082
/**
 * MibaoLogo 组件测试 —— 「黄金策」侧的机器人头像图标（issue #9306）。
 *
 * 为什么补这条：本单把该组件的注释文案改了（旧品牌名退役），而 Growth Gate 对
 * `frontend/admin-web/src/components/**\/*.tsx` 的改动要求同名单测 —— 该组件此前**没有测试文件**
 * ⇒ 改它等于「没人管」。本文件钉住三件事：尺寸可配、className 透传、禁出现可读文本
 * （图标是纯装饰，屏幕阅读器不该念出一串字）。
 *
 * 文件名沿用旧品牌名是**组件名**（技术标识，改名会引发大面积 import 变更，本单登记为未固化项）；
 * 展示面已无旧称。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'

import { MibaoLogo } from '@/components/icons/MibaoLogo'

describe('MibaoLogo（黄金策 AI 助手图标）', () => {
  it('按 size 渲染正方形 svg，viewBox 固定 0 0 80 80', () => {
    const { container } = render(<MibaoLogo size={48} />)
    const svg = container.querySelector('svg') as SVGSVGElement
    expect(svg.getAttribute('width')).toBe('48')
    expect(svg.getAttribute('height')).toBe('48')
    expect(svg.getAttribute('viewBox')).toBe('0 0 80 80')
  })

  it('默认 size=32，className 透传到 svg（供外部尺寸 / 配色类复用）', () => {
    const { container } = render(<MibaoLogo className="h-4 w-4" />)
    const svg = container.querySelector('svg') as SVGSVGElement
    expect(svg.getAttribute('width')).toBe('32')
    expect(svg.getAttribute('class')).toBe('h-4 w-4')
  })

  it('渐变定义随组件自带（不依赖外部资源），且不暴露可读文本', () => {
    const { container } = render(<MibaoLogo />)
    const gradientIds = Array.from(container.querySelectorAll('linearGradient')).map((g) => g.id)
    expect(gradientIds).toEqual(['mb-head', 'mb-face'])
    expect(container.textContent).toBe('')
  })
})
