// case_ids: UI-082
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import ServicesPage from '@/app/(corporate)/services/page'
import { findColloquialMarkers } from './copy-voice-banlist'

describe('ServicesPage（官网产品与服务 v4：双 AI + 四终端 + 六能力域，issue #6291 / #6326）', () => {
  // ── 页头 ──

  it('renders page title 与定位副标', () => {
    render(<ServicesPage />)
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: '两位 AI 助手与全链路经营平台',
      })
    ).toBeInTheDocument()
    expect(screen.getByText(/四个终端共用同一套数据/)).toBeInTheDocument()
  })

  it('renders 页头事实标签（AI 数 / 能力域数 / 终端数 / 行业纵深）', () => {
    render(<ServicesPage />)
    expect(screen.getByText('2 位 AI 助手')).toBeInTheDocument()
    expect(screen.getByText(/6 个能力域 · \d+ 项功能/)).toBeInTheDocument()
    expect(screen.getByText('4 个终端')).toBeInTheDocument()
    expect(screen.getByText('算料 · 工序 · 批次 · 计件')).toBeInTheDocument()
  })

  // ── 两位 AI ──

  it('renders 两位 AI 的产品卡', () => {
    render(<ServicesPage />)
    expect(screen.getByText('小布 · AI 智能客服')).toBeInTheDocument()
    expect(screen.getByText('米宝 · 企业智能工作助手')).toBeInTheDocument()
    expect(screen.getByText('顾客侧：从规格咨询到下单、物流查询与售后受理')).toBeInTheDocument()
    expect(screen.getByText('经营侧：以自然语言查询账目、订单与进度')).toBeInTheDocument()
  })

  it('renders 小布的能力点（含算料报价与售后受理）', () => {
    render(<ServicesPage />)
    expect(
      screen.getByText('按尺寸与工艺计算用料并给出估算报价，明确说明为估算而非成交价')
    ).toBeInTheDocument()
    expect(
      screen.getByText('售后咨询与申请受理，工单恒为「待商家审核」')
    ).toBeInTheDocument()
    expect(screen.getByText('订单进度、物流轨迹、收货地址查询')).toBeInTheDocument()
  })

  it('renders 米宝的能力点（含生产计件与财务对账）', () => {
    render(<ServicesPage />)
    expect(
      screen.getByText('生产与计件：工序库、工艺路线、计件工资与报工明细')
    ).toBeInTheDocument()
    expect(
      screen.getByText('财务与客户：资金流水 / 收支汇总 / 应收对账问答，客户档案与售后工单')
    ).toBeInTheDocument()
    expect(screen.getByText('库存与入库：批次库存、库存台账、入库单与批次成本')).toBeInTheDocument()
  })

  it('renders 能力边界（旧版「批量操作库存 / 退换货处理」等已过期表述不得残留）', () => {
    render(<ServicesPage />)
    expect(screen.getByText(/写操作只有三类：改价、批量上下架、批量库存调整/)).toBeInTheDocument()
    expect(screen.getByText(/不做：改价、取消订单、退款、承诺优惠折扣、报库存数量/)).toBeInTheDocument()
    expect(screen.queryByText(/批量操作库存/)).not.toBeInTheDocument()
    expect(screen.queryByText(/智能工单流转/)).not.toBeInTheDocument()
  })

  // ── 四个终端 ──

  it('renders 四个终端（管理后台 / 顾客小程序 / 商家小程序 / 员工端 H5）', () => {
    render(<ServicesPage />)
    for (const name of ['管理后台', '顾客小程序', '商家小程序', '员工端 H5']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    expect(screen.getByText('扫码报工（合格 / 返工 / 报废）')).toBeInTheDocument()
    expect(screen.getByText('工人登录、拍照入库、补打标签')).toBeInTheDocument()
  })

  // ── 六个能力域 ──

  it('renders 六个能力域与独立入口的全部菜单名', () => {
    render(<ServicesPage />)
    for (const domain of ['工作台', '客户服务', '交易管理', '生产管理', '仓储与物料', '组织管理']) {
      expect(screen.getByText(domain)).toBeInTheDocument()
    }
    for (const item of [
      '经营看板',
      '每日简报',
      '在线接待',
      '客户列表',
      '知识库',
      '售后工单',
      '订单列表',
      '财务对账',
      '生产看板',
      '智能派单',
      '加工项管理',
      '工艺配置',
      '计件工资',
      '入库单',
      '发货单',
      '余料台账',
      '省料看板',
      '员工管理',
      '岗位权限',
      '企业基础信息',
      '商品管理',
      '通知中心',
    ]) {
      expect(screen.getByText(item)).toBeInTheDocument()
    }
  })

  it('renders 能力域明细（抽样断言细节文本）', () => {
    render(<ServicesPage />)
    expect(
      screen.getByText(/只有已发布的卡片会被 AI 检索到/)
    ).toBeInTheDocument()
    expect(screen.getByText(/过账自动生成批次号、增加库存并按移动加权平均记成本/)).toBeInTheDocument()
    expect(screen.getByText(/返工与报废不计件，由服务端排除/)).toBeInTheDocument()
  })

  // ── 行业纵深 ──

  it('renders 行业纵深四块', () => {
    render(<ServicesPage />)
    expect(screen.getByText('布艺经营的四项核心能力')).toBeInTheDocument()
    for (const title of ['算料与报价', '多规格 SKU', '工序与计件', '批次与余料']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  // ── 交付与开通 ──

  it('renders 交付与开通（AI 秒级开通 / 模板 / 权限 / 价格口径）', () => {
    render(<ServicesPage />)
    expect(screen.getByText('AI 自动甄别，秒级开通')).toBeInTheDocument()
    expect(screen.getByText('行业模板预置')).toBeInTheDocument()
    expect(screen.getByText('价格与合同另行沟通')).toBeInTheDocument()
    expect(screen.getByText(/本页面不公示价格/)).toBeInTheDocument()
  })

  it('renders 底部 CTA', () => {
    render(<ServicesPage />)
    expect(screen.getByText('立即入驻')).toBeInTheDocument()
    expect(screen.getByText('留言咨询')).toBeInTheDocument()
  })

  // ── 视觉与真实性 ──

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

  // ── 文案口吻（issue #6326：去 AI 口语，改「能力陈述型」书面语）──

  it('文案口吻：产品与服务页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<ServicesPage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `产品与服务页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })
})
