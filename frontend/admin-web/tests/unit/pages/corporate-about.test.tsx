// case_ids: UI-082, OB-008
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import AboutPage from '@/app/(corporate)/about/page'
import {
  findColloquialMarkers,
  findPersonifiedAi,
  findQuantifierRhetoric,
} from './copy-voice-banlist'

describe('CorporateAboutPage（官网关于页：主体事实 + 产品原则，issue #9121）', () => {
  it('renders page header', () => {
    render(<AboutPage />)
    expect(screen.getByRole('heading', { level: 1, name: '关于生意管家' })).toBeInTheDocument()
    expect(screen.getByText(/生意管家是杭州词元通达科技有限公司旗下的 AI 经营平台/)).toBeInTheDocument()
  })

  it('renders company intro（布艺行业真实流程 + 双 AI 分工 + 公司名含义）', () => {
    render(<AboutPage />)
    expect(screen.getByText(/布艺经营的多数知识，至今仍存放在人身上/)).toBeInTheDocument()
    expect(screen.getByText(/系统里留下的，往往只有开单与记账/)).toBeInTheDocument()
    expect(screen.getByText(/米宝在顾客侧、黄金策在经营侧/)).toBeInTheDocument()
    expect(screen.getByText(/都要能落回系统里的真实记录/)).toBeInTheDocument()
    expect(screen.getByText(/词元是 AI 的底座，通达是把能力送到经营现场/)).toBeInTheDocument()
  })

  it('renders mission and vision', () => {
    render(<AboutPage />)
    expect(screen.getByText('我们的使命')).toBeInTheDocument()
    expect(screen.getByText(/以可负担的成本，让 AI 数智化成为布艺企业经营的基本能力/)).toBeInTheDocument()
    expect(screen.getByText('我们的愿景')).toBeInTheDocument()
    expect(screen.getByText(/都拥有与大企业同等的经营能力/)).toBeInTheDocument()
    expect(screen.getByText(/让规模不再是经营能力的边界/)).toBeInTheDocument()
  })

  it('renders 产品原则（不编造 / 价格不由模型定 / 敏感事项不做决定 / 边界写明）', () => {
    render(<AboutPage />)
    expect(screen.getByText('AI 的边界与授权')).toBeInTheDocument()
    for (const title of ['数据之外不作答', '定价权归属商品库', '敏感事项不由 AI 决定', '能力边界公开标注']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  it('renders 我们的选择（行业先行 / 数据同源 / 边界公开），不再展开技术底座', () => {
    render(<AboutPage />)
    expect(screen.getByText('行业先行，数据同源，边界公开')).toBeInTheDocument()
    for (const title of ['行业先行', '数据同源', '边界公开']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    // 用户 2026-11-24 裁定：官网不再泄露底层架构
    expect(screen.queryByText('技术底座')).not.toBeInTheDocument()
    expect(screen.queryByText(/业务工具层/)).not.toBeInTheDocument()
    expect(screen.queryByText(/多租户底座/)).not.toBeInTheDocument()
    // 查无出处的年份不得回流（issue #6382）
    expect(screen.queryByText(/20\d\d/)).not.toBeInTheDocument()
  })

  it('renders 底部 CTA（内测期不露出立即入驻，OB-008）', () => {
    render(<AboutPage />)
    expect(screen.queryByText('立即入驻')).not.toBeInTheDocument()
    expect(screen.getByText('联系我们')).toBeInTheDocument()
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

  it('文案口吻：关于我们页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<AboutPage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `关于我们页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })

  it('文案质感：关于我们页渲染文本无量化排比、无拟人量词', () => {
    const { container } = render(<AboutPage />)
    const text = container.textContent ?? ''

    expect(findQuantifierRhetoric('一套经营平台，一次咨询，一张订单')).toEqual(['一套', '一次', '一张'])
    expect(findPersonifiedAi('两位 AI 助手')).toEqual(['两位 AI'])
    expect(findQuantifierRhetoric('六个能力域 · 4 个终端 · 至少10个字符')).toEqual([])
    expect(findPersonifiedAi('米宝与黄金策')).toEqual([])

    expect(findQuantifierRhetoric(text)).toEqual([])
    expect(findPersonifiedAi(text)).toEqual([])
  })
})
