// case_ids: UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import AboutPage from '@/app/(corporate)/about/page'
import { findColloquialMarkers } from './copy-voice-banlist'

describe('CorporateAboutPage（官网关于页 v4：产品原则 + 主体事实，issue #6291 / #6326）', () => {
  it('renders page header', () => {
    render(<AboutPage />)
    expect(screen.getByRole('heading', { level: 1, name: '关于米高' })).toBeInTheDocument()
    expect(screen.getByText(/米高是杭州词元通达科技有限公司旗下的 AI 经营平台/)).toBeInTheDocument()
  })

  it('renders company intro（布艺行业真实流程 + 双 AI 分工）', () => {
    render(<AboutPage />)
    expect(screen.getByText(/一款窗帘要按颜色 × 售卖方式 × 门幅组合出几十个规格/)).toBeInTheDocument()
    expect(screen.getByText(/顾客侧是小布/)).toBeInTheDocument()
    expect(screen.getByText(/经营侧是米宝/)).toBeInTheDocument()
  })

  it('renders mission and vision', () => {
    render(<AboutPage />)
    expect(screen.getByText('我们的使命')).toBeInTheDocument()
    expect(screen.getByText('我们的愿景')).toBeInTheDocument()
  })

  it('renders 产品原则（不编造 / 价格不由模型定 / 敏感事项不做决定 / 边界写明）', () => {
    render(<AboutPage />)
    expect(screen.getByText('米高的产品原则')).toBeInTheDocument()
    expect(screen.getByText('数据之外不作答')).toBeInTheDocument()
    expect(screen.getByText('定价权归属商品库')).toBeInTheDocument()
    expect(screen.getByText('敏感事项不由 AI 决定')).toBeInTheDocument()
    expect(screen.getByText('能力边界公开标注')).toBeInTheDocument()
  })

  it('renders core values section 与四条价值观', () => {
    render(<AboutPage />)
    expect(screen.getByText('核心价值观')).toBeInTheDocument()
    for (const name of ['技术驱动', '客户至上', '行业深耕', '数据安全']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('renders timeline section 与五个里程碑', () => {
    render(<AboutPage />)
    expect(screen.getByText('发展历程')).toBeInTheDocument()
    for (const title of ['项目启动', '核心引擎开发', '平台上线', '多渠道接入', '能力扩展']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText(/生产工序、仓储批次、财务对账与计件工资陆续上线/)).toBeInTheDocument()
  })

  it('renders 底部 CTA', () => {
    render(<AboutPage />)
    expect(screen.getByText('立即入驻')).toBeInTheDocument()
    expect(screen.getByText('留言咨询')).toBeInTheDocument()
  })

  it('宣传真实性：不出现占位联系方式与浮夸表述', () => {
    render(<AboutPage />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/文一西路000号/)).not.toBeInTheDocument()
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越懂/)).not.toBeInTheDocument()
  })

  it('视觉口径：不再使用通用蓝色渐变模板', () => {
    const { container } = render(<AboutPage />)
    expect(container.innerHTML).not.toContain('from-blue-600')
    expect(container.innerHTML).not.toContain('to-indigo-800')
  })

  // ── 文案口吻（issue #6326：去 AI 口语，改「能力陈述型」书面语）──

  it('文案口吻：关于我们页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<AboutPage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `关于我们页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })
})
