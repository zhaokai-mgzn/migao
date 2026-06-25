import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock lucide-react — icons used by corporate home page
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Bot: stub('bot'),
    MessageSquare: stub('message-square'),
    Package: stub('package'),
    ClipboardList: stub('clipboard-list'),
    BookOpen: stub('book-open'),
    Sparkles: stub('sparkles'),
    Brain: stub('brain'),
    Smartphone: stub('smartphone'),
    ShieldCheck: stub('shield-check'),
    FileText: stub('file-text'),
    Search: stub('search'),
    Rocket: stub('rocket'),
    ArrowRight: stub('arrow-right'),
    Check: stub('check'),
  }
})

import HomePage from '@/app/(corporate)/page'

describe('CorporateHomePage', () => {
  it('renders hero heading', () => {
    render(<HomePage />)
    expect(screen.getByText(/AI 驱动的新一代/)).toBeInTheDocument()
    expect(screen.getByText(/企业智能管理平台/)).toBeInTheDocument()
  })

  it('renders hero description', () => {
    render(<HomePage />)
    expect(screen.getByText(/米高 SaaS 平台/)).toBeInTheDocument()
  })

  it('renders CTA links', () => {
    render(<HomePage />)
    // "立即入驻" appears in both hero and bottom CTA sections
    const ctaLinks = screen.getAllByText('立即入驻')
    expect(ctaLinks).toHaveLength(2)
    expect(screen.getByText('了解更多')).toBeInTheDocument()
  })

  it('renders features section title', () => {
    render(<HomePage />)
    expect(screen.getByText('功能亮点')).toBeInTheDocument()
  })

  it('renders feature names', () => {
    render(<HomePage />)
    expect(screen.getByText('米宝 · 企业智能助手')).toBeInTheDocument()
    expect(screen.getByText('小布 · AI 智能客服')).toBeInTheDocument()
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('知识库')).toBeInTheDocument()
  })

  it('renders advantages section title', () => {
    render(<HomePage />)
    expect(screen.getByText('为什么选择米高')).toBeInTheDocument()
  })

  it('renders advantage names', () => {
    render(<HomePage />)
    expect(screen.getByText('双AI助手赋能')).toBeInTheDocument()
    expect(screen.getByText('大模型深度理解')).toBeInTheDocument()
    expect(screen.getByText('多渠道统一管理')).toBeInTheDocument()
    expect(screen.getByText('数据安全可靠')).toBeInTheDocument()
  })

  it('renders steps section title', () => {
    render(<HomePage />)
    expect(screen.getByText('入驻流程')).toBeInTheDocument()
  })

  it('renders step names', () => {
    render(<HomePage />)
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('平台审核')).toBeInTheDocument()
    expect(screen.getByText('开通使用')).toBeInTheDocument()
  })

  it('renders bottom CTA', () => {
    render(<HomePage />)
    expect(screen.getByText(/准备好让AI助手驱动您的业务增长了吗/)).toBeInTheDocument()
    expect(screen.getByText(/立即入驻米高平台/)).toBeInTheDocument()
  })
})
