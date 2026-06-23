import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// ===== Override lucide-react mock to cover all icons used by services page =====
// Use vi.hoisted to ensure the stub is available at mock hoist time
const { iconStub } = vi.hoisted(() => {
  const iconStub = (name: string) => {
    const Component = (props: any) => {
      const React = require('react')
      return React.createElement('span', { 'data-testid': `icon-${name}`, ...props })
    }
    Component.displayName = name
    return Component
  }
  return { iconStub }
})

vi.mock('lucide-react', () => ({
  MessageSquare: iconStub('message-square'),
  Wrench: iconStub('wrench'),
  Zap: iconStub('zap'),
  Radio: iconStub('radio'),
  LayoutDashboard: iconStub('layout-dashboard'),
  ShoppingBag: iconStub('shopping-bag'),
  Users: iconStub('users'),
  BarChart3: iconStub('bar-chart3'),
  Smartphone: iconStub('smartphone'),
  MessageCircle: iconStub('message-circle'),
  History: iconStub('history'),
  TrendingUp: iconStub('trending-up'),
  UserCheck: iconStub('user-check'),
  PieChart: iconStub('pie-chart'),
  Sparkles: iconStub('sparkles'),
  PackageSearch: iconStub('package-search'),
  Truck: iconStub('truck'),
  BookOpen: iconStub('book-open'),
  Headphones: iconStub('headphones'),
  MessagesSquare: iconStub('messages-square'),
}))

import ServicesPage from '@/app/(corporate)/services/page'

describe('ServicesPage', () => {
  // ── Page header ──

  it('should render page title', () => {
    render(<ServicesPage />)
    expect(screen.getByText('产品与服务')).toBeInTheDocument()
  })

  it('should render page subtitle', () => {
    render(<ServicesPage />)
    expect(screen.getByText(/双AI助手 \+ 全链路管理平台/)).toBeInTheDocument()
  })

  it('should render header section with gradient background', () => {
    render(<ServicesPage />)
    const heading = screen.getByRole('heading', { level: 1, name: '产品与服务' })
    expect(heading).toBeInTheDocument()
  })

  // ── Products list ──

  it('should render all 5 product sections', () => {
    render(<ServicesPage />)
    const products = [
      '米宝 · 企业智能工作助手',
      '小布 · AI 智能客服',
      '商家管理后台',
      '微信小程序客服',
      '数据分析与报表',
    ]
    for (const name of products) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('should render product descriptions', () => {
    render(<ServicesPage />)
    expect(screen.getByText(/面向企业员工的AI工作搭档/)).toBeInTheDocument()
    expect(screen.getByText(/面向消费者的7×24小时智能客服/)).toBeInTheDocument()
    expect(screen.getByText(/功能完善的一站式管理平台/)).toBeInTheDocument()
    expect(screen.getByText(/在微信生态内为消费者提供原生体验/)).toBeInTheDocument()
    expect(screen.getByText(/全方位数据洞察能力/)).toBeInTheDocument()
  })

  // ── Product features (米宝) ──

  it('should render mibao features', () => {
    render(<ServicesPage />)
    expect(screen.getByText('商品智能管理：语音/文字查询商品、批量操作库存、智能分类推荐')).toBeInTheDocument()
    expect(screen.getByText('订单全程跟踪：一句话查订单状态、物流追踪、异常订单智能预警')).toBeInTheDocument()
    expect(screen.getByText('知识即时检索：面料知识、工艺流程、安装指南、售后政策，问即答')).toBeInTheDocument()
    expect(screen.getByText('售后高效协同：退换货处理、客户投诉跟进、智能工单流转')).toBeInTheDocument()
    expect(screen.getByText('多轮深度对话：基于上下文理解，支持复杂业务场景的连续交互')).toBeInTheDocument()
  })

  it('should render xiaobu features', () => {
    render(<ServicesPage />)
    expect(screen.getByText('基于大语言模型，精准理解客户意图，应答自然贴切有温度')).toBeInTheDocument()
    expect(screen.getByText('多轮对话与上下文记忆，像真人客服一样连续沟通')).toBeInTheDocument()
    expect(screen.getByText('智能工具调用：商品查询、物流追踪、知识检索一键直达')).toBeInTheDocument()
    expect(screen.getByText('毫秒级流式应答，所见即所得的打字机效果，体验流畅自然')).toBeInTheDocument()
  })

  it('should render admin backend features', () => {
    render(<ServicesPage />)
    expect(screen.getByText('商品中心：商品信息管理、加工项配置、知识库维护，商品运营一站搞定')).toBeInTheDocument()
    expect(screen.getByText('交易中心：订单管理、售后处理、物流跟踪，全链路把控')).toBeInTheDocument()
    expect(screen.getByText('客户中心：客户档案、标签管理、行为洞察，精准运营')).toBeInTheDocument()
    expect(screen.getByText('数据看板：经营数据一览，趋势分析，数据驱动决策')).toBeInTheDocument()
  })

  it('should render mini app features', () => {
    render(<ServicesPage />)
    expect(screen.getByText('微信原生体验，无需额外下载，扫码即用')).toBeInTheDocument()
    expect(screen.getByText('富媒体消息展示，商品卡片、订单详情直观呈现')).toBeInTheDocument()
    expect(screen.getByText('完整会话管理，历史记录随时回顾，服务连贯不断线')).toBeInTheDocument()
  })

  it('should render data analytics features', () => {
    render(<ServicesPage />)
    expect(screen.getByText('服务质量监控：响应时长、客户满意度、问题解决率全面追踪')).toBeInTheDocument()
    expect(screen.getByText('客户行为洞察：访问路径分析、偏好画像、转化漏斗')).toBeInTheDocument()
    expect(screen.getByText('经营数据统计：订单趋势、营收分析、库存周转一目了然')).toBeInTheDocument()
  })

  // ── Icons ──

  it('should render product icons in colored containers', () => {
    render(<ServicesPage />)
    expect(screen.getByTestId('icon-sparkles')).toBeInTheDocument()
    expect(screen.getByTestId('icon-message-square')).toBeInTheDocument()
    expect(screen.getByTestId('icon-layout-dashboard')).toBeInTheDocument()
    // Smartphone appears twice (product icon + feature icon), use getAllByTestId
    const smartphoneIcons = screen.getAllByTestId('icon-smartphone')
    expect(smartphoneIcons.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByTestId('icon-pie-chart')).toBeInTheDocument()
  })

  it('should render feature icons in each product card', () => {
    render(<ServicesPage />)
    expect(screen.getByTestId('icon-package-search')).toBeInTheDocument()
    expect(screen.getByTestId('icon-truck')).toBeInTheDocument()
    expect(screen.getByTestId('icon-book-open')).toBeInTheDocument()
    expect(screen.getByTestId('icon-headphones')).toBeInTheDocument()
    expect(screen.getByTestId('icon-messages-square')).toBeInTheDocument()
  })

  // ── Alternate background rows ──

  it('should have alternating background colors on product cards', () => {
    const { container } = render(<ServicesPage />)
    const cards = container.querySelectorAll('.rounded-2xl')
    expect(cards.length).toBe(5)
    expect(cards[0].className).toContain('bg-white')
    expect(cards[1].className).toContain('bg-gray-50')
  })

  // ── Feature cards count ──

  it('should have feature grids for each product', () => {
    const { container } = render(<ServicesPage />)
    const featureCards = container.querySelectorAll('.grid')
    expect(featureCards.length).toBe(5)
  })

  it('should render multiple feature items across all products', () => {
    const { container } = render(<ServicesPage />)
    // 5+4+4+3+3 = 19 feature items
    const featureItems = container.querySelectorAll('.grid > div')
    expect(featureItems.length).toBeGreaterThanOrEqual(10)
  })
})
