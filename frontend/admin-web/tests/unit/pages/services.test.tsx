// case_ids: UI-082, OB-008
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import ServicesPage from '@/app/(corporate)/services/page'
import {
  findColloquialMarkers,
  findPersonifiedAi,
  findQuantifierRhetoric,
} from './copy-voice-banlist'

describe('ServicesPage（官网产品能力：浅色页头 + 场景分节 + 能力域，issue #9121）', () => {
  it('renders page title 与定位副标', () => {
    render(<ServicesPage />)
    expect(screen.getByText(/两条 AI/)).toBeInTheDocument()
    expect(screen.getByText('共用业务底座')).toBeInTheDocument()
    expect(screen.getByText(/管理后台、微信客服、商家小程序与员工端 H5 共用数据/)).toBeInTheDocument()
  })

  it('renders 页头能力标签（六个经营动作）', () => {
    render(<ServicesPage />)
    for (const chip of ['智能接待', '算料报价', '订单生产', '库存批次', '计件对账', '经营决策']) {
      expect(screen.getAllByText(chip).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('hero 右侧：工作台示意', () => {
    render(<ServicesPage />)
    expect(screen.getByText('生意管家 · 工作台')).toBeInTheDocument()
    expect(screen.getAllByText('界面示意').length).toBeGreaterThanOrEqual(1)
  })

  it('四个场景分节：标题 / 标签 / 产品示意', () => {
    render(<ServicesPage />)
    for (const title of [
      '从顾客开口，到订单成交',
      '问经营，不用等报表',
      '订单到交付，进度在同一链路',
      '批次、库存、计件与收支，逐笔可查',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
    expect(screen.getAllByText('界面示意').length).toBeGreaterThanOrEqual(5)
    expect(screen.getByText('微信客服 · 米宝')).toBeInTheDocument()
    expect(screen.getByText('管理后台 · 经营报表')).toBeInTheDocument()
    expect(screen.getByText('加工单 · 生产进度')).toBeInTheDocument()
    expect(screen.getByText('库存台账 · 批次')).toBeInTheDocument()
  })

  it('八个能力域：只列域与解决的问题，不展开内部菜单', () => {
    render(<ServicesPage />)
    for (const domain of ['客户服务', '订单/商品', '生产管理', '质量管理', '仓储/物料', '财务', '供应链', '组织管理']) {
      expect(screen.getAllByText(domain).length).toBeGreaterThanOrEqual(1)
    }
    for (const internalItem of ['在线接待', '售后工单', '价格本', '智能派单', '余料台账']) {
      expect(screen.queryByText(internalItem)).not.toBeInTheDocument()
    }
  })

  it('行业纵深四块', () => {
    render(<ServicesPage />)
    expect(screen.getByText('布艺经营的四项核心能力')).toBeInTheDocument()
    for (const title of ['算料与报价', '多规格 SKU', '工序与计件', '批次与余料']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('四个终端', () => {
    render(<ServicesPage />)
    for (const name of ['管理后台', '微信客服', '商家小程序', '员工端 H5']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    expect(screen.getByText('老板 / 员工 / 工人')).toBeInTheDocument()
  })

  it('交付与开通（模板 / 权限 / 交付口径）', () => {
    render(<ServicesPage />)
    expect(screen.getByText('行业模板预置')).toBeInTheDocument()
    expect(screen.getByText('岗位权限预置可调')).toBeInTheDocument()
    expect(screen.getByText('按场景确认交付')).toBeInTheDocument()
    expect(screen.getByText(/价格与合同另行沟通/)).toBeInTheDocument()
  })

  it('底部 CTA（内测期不露出立即入驻，OB-008）', () => {
    render(<ServicesPage />)
    expect(screen.queryByText('立即入驻')).not.toBeInTheDocument()
    expect(screen.getByText('联系我们')).toBeInTheDocument()
  })

  it('视觉口径：不再使用通用蓝色渐变模板', () => {
    const { container } = render(<ServicesPage />)
    expect(container.innerHTML).not.toContain('from-blue-600')
    expect(container.innerHTML).not.toContain('to-indigo-800')
  })

  it('宣传真实性：不出现占位联系方式与浮夸表述', () => {
    render(<ServicesPage />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/文一西路000号/)).not.toBeInTheDocument()
    expect(screen.queryByText(/拼版/)).not.toBeInTheDocument()
    expect(screen.queryByText(/毫秒级/)).not.toBeInTheDocument()
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
  })

  it('文案口吻：产品能力页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<ServicesPage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `产品能力页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })

  it('文案质感：产品能力页渲染文本无量化排比、无拟人量词', () => {
    const { container } = render(<ServicesPage />)
    const text = container.textContent ?? ''
    expect(findQuantifierRhetoric('一套经营平台，一次咨询，一张订单')).toEqual(['一套', '一次', '一张'])
    expect(findPersonifiedAi('两位 AI 助手')).toEqual(['两位 AI'])
    expect(findQuantifierRhetoric('六个能力域 · 4 个终端 · 至少10个字符')).toEqual([])
    expect(findPersonifiedAi('米宝与黄金策')).toEqual([])
    expect(findQuantifierRhetoric(text)).toEqual([])
    expect(findPersonifiedAi(text)).toEqual([])
  })
})
