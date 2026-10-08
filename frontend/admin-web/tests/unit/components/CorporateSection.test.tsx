// case_ids: UI-082
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  CallToAction,
  PageHero,
  SectionHeading,
} from '@/components/corporate/CorporateSection'

/**
 * 官网共用版式组件（issue #6291）。
 *
 * 为什么单独测：`SectionHeading` / `PageHero` / `CallToAction` 被四个官网页面共用，
 * 它们的分支（居中 vs 左对齐、有没有导语、有没有 chips、有没有行动按钮）一旦改坏，
 * 四个页面会**同时**坏 —— 这里把每条分支钉住。
 */
describe('CorporateSection（官网共用版式）', () => {
  // ── SectionHeading ──

  it('SectionHeading 渲染小标签 / 标题 / 导语', () => {
    render(<SectionHeading kicker="行业纵深" title="一条窗帘订单" lead="通用客服只答有没有货" />)
    expect(screen.getByText('行业纵深')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '一条窗帘订单' })).toBeInTheDocument()
    expect(screen.getByText('通用客服只答有没有货')).toBeInTheDocument()
  })

  it('SectionHeading 默认居中；align=left 时左对齐（类名可判）', () => {
    const { container: centered } = render(<SectionHeading kicker="A" title="居中" />)
    expect(centered.firstElementChild?.className).toContain('mx-auto')
    expect(centered.firstElementChild?.className).toContain('text-center')

    const { container: left } = render(<SectionHeading kicker="B" title="左对齐" align="left" />)
    expect(left.firstElementChild?.className).toContain('text-left')
    expect(left.firstElementChild?.className).not.toContain('mx-auto')
  })

  it('SectionHeading 无导语时不渲染导语段落', () => {
    render(<SectionHeading kicker="无导语" title="标题" />)
    expect(screen.queryByText(/通用客服/)).not.toBeInTheDocument()
    expect(screen.getByText('无导语').nextElementSibling?.tagName).toBe('H2')
  })

  // ── PageHero ──

  it('PageHero 渲染 kicker / h1 / 导语', () => {
    render(<PageHero kicker="产品与服务" title="能干活的两个 AI" lead="观星台不是接一个客服机器人" />)
    expect(screen.getByText('产品与服务')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '能干活的两个 AI' })).toBeInTheDocument()
    expect(screen.getByText('观星台不是接一个客服机器人')).toBeInTheDocument()
  })

  it('PageHero 渲染事实标签；未给 chips 时不渲染标签容器', () => {
    const { container } = render(
      <PageHero kicker="K" title="T" lead="L" chips={['2 位 AI 助手', '4 个终端']} />
    )
    expect(screen.getByText('2 位 AI 助手')).toBeInTheDocument()
    expect(screen.getByText('4 个终端')).toBeInTheDocument()
    expect(container.querySelectorAll('.rounded-lg.border').length).toBe(2)

    const { container: noChips } = render(<PageHero kicker="K" title="T" lead="L" />)
    expect(noChips.querySelectorAll('.rounded-lg.border').length).toBe(0)
  })

  it('PageHero 用织物质感深色底（neutral-900），不用通用蓝色渐变', () => {
    const { container } = render(<PageHero kicker="K" title="T" lead="L" />)
    const section = container.querySelector('section')
    expect(section?.className).toContain('bg-neutral-900')
    expect(section?.className).not.toContain('from-blue-600')
  })

  // ── CallToAction ──

  it('CallToAction 渲染标题 / 导语 / 双按钮', () => {
    render(
      <CallToAction
        title="想看清楚它能不能接住你的生意？"
        lead="提交入驻申请"
        primary={<a href="/register">立即入驻</a>}
        secondary={<a href="/contact">留言咨询</a>}
      />
    )
    expect(
      screen.getByRole('heading', { level: 2, name: '想看清楚它能不能接住你的生意？' })
    ).toBeInTheDocument()
    expect(screen.getByText('提交入驻申请')).toBeInTheDocument()
    expect(screen.getByText('立即入驻')).toBeInTheDocument()
    expect(screen.getByText('留言咨询')).toBeInTheDocument()
  })

  it('CallToAction 无行动按钮时不渲染按钮容器', () => {
    const { container } = render(<CallToAction title="仅标题" lead="仅导语" />)
    expect(container.querySelector('.sm\\:flex-row')).toBeNull()
  })
})
