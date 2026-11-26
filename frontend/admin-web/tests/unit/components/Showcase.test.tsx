// case_ids: UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import { SectionIntro, ShowcaseBlock, SupportGrid } from '@/components/corporate/Showcase'
import { Bot, ShieldCheck } from 'lucide-react'

describe('Showcase（官网分节版式）', () => {
  it('SectionIntro 渲染眉标 / 标题 / 导语', () => {
    render(<SectionIntro kicker="能力域" title="八个能力域" lead="只到域级。" />)
    expect(screen.getByText('能力域')).toBeInTheDocument()
    expect(screen.getByText('八个能力域')).toBeInTheDocument()
    expect(screen.getByText('只到域级。')).toBeInTheDocument()
  })

  it('ShowcaseBlock 渲染分节标题 / 卡片标题 / 标签 / 要点 / 示意 / CTA', () => {
    render(
      <ShowcaseBlock
        kicker="顾客经营"
        title="分节标题"
        cardTitle="卡片标题"
        lead="导语"
        tabs={['接待', '算料']}
        tabDetails={['接待说明', '算料说明']}
        bullets={['要点甲', '要点乙']}
        visual={<div data-testid="visual">示意</div>}
      />
    )
    expect(screen.getByText('分节标题')).toBeInTheDocument()
    expect(screen.getByText('卡片标题')).toBeInTheDocument()
    for (const tab of ['接待', '算料']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
    }
    expect(screen.getByText('要点甲')).toBeInTheDocument()
    expect(screen.getByTestId('visual')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /了解产品能力/ })).toHaveAttribute('href', '/services')
  })

  it('SupportGrid 渲染六格支持的标题与说明', () => {
    render(
      <SupportGrid
        items={[
          { icon: Bot, title: '双 AI', description: '分工' },
          { icon: ShieldCheck, title: '隔离', description: '按租户' },
        ]}
      />
    )
    expect(screen.getByText('双 AI')).toBeInTheDocument()
    expect(screen.getByText('分工')).toBeInTheDocument()
    expect(screen.getByText('隔离')).toBeInTheDocument()
  })
})
