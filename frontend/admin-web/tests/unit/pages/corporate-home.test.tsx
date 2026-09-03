// case_ids: OB-004, OB-005
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
    Zap: stub('zap'),
    Rocket: stub('rocket'),
    ArrowRight: stub('arrow-right'),
    Check: stub('check'),
    Factory: stub('factory'),
    Sofa: stub('sofa'),
    Shirt: stub('shirt'),
    ShoppingBag: stub('shopping-bag'),
    Landmark: stub('landmark'),
    BadgeCheck: stub('badge-check'),
  }
})

import HomePage from '@/app/(corporate)/page'

describe('CorporateHomePage（主页文案重设计：米高+小布双 Agent，公司杭州词元通达科技有限公司）', () => {
  it('renders hero heading with 双 Agent 品牌', () => {
    render(<HomePage />)
    expect(screen.getByText(/米高 × 小布/)).toBeInTheDocument()
    expect(screen.getByText(/AI 驱动的新一代/)).toBeInTheDocument()
    expect(screen.getByText(/企业智能管理平台/)).toBeInTheDocument()
  })

  it('renders company name in hero badge', () => {
    render(<HomePage />)
    // 公司名出现在 Hero badge 与合规保障区
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders hero description mentioning AI 秒级甄别', () => {
    render(<HomePage />)
    expect(screen.getByText(/米高企业智能工作助手 \+ 小布智能客服/)).toBeInTheDocument()
    // 「AI 自动甄别」出现在 Hero 与步骤区等多处
    expect(screen.getAllByText(/AI 自动甄别/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders CTA links', () => {
    render(<HomePage />)
    // "立即入驻" appears in both hero and bottom CTA sections
    const ctaLinks = screen.getAllByText('立即入驻')
    expect(ctaLinks).toHaveLength(2)
    expect(screen.getByText('了解更多')).toBeInTheDocument()
  })

  it('renders 双 Agent 区（米高 + 小布）', () => {
    render(<HomePage />)
    expect(screen.getByText('双 AI 助手')).toBeInTheDocument()
    expect(screen.getByText('米高')).toBeInTheDocument()
    expect(screen.getByText('企业智能工作助手')).toBeInTheDocument()
    expect(screen.getByText('小布')).toBeInTheDocument()
    expect(screen.getByText('AI 智能客服')).toBeInTheDocument()
  })

  it('renders features section title', () => {
    render(<HomePage />)
    expect(screen.getByText('核心能力')).toBeInTheDocument()
  })

  it('renders feature names', () => {
    render(<HomePage />)
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

  it('renders steps with AI 智能甄别（不再出现人工 1-3 工作日审核）', () => {
    render(<HomePage />)
    expect(screen.getByText('入驻流程')).toBeInTheDocument()
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('AI 智能甄别')).toBeInTheDocument()
    expect(screen.getByText('即刻开通')).toBeInTheDocument()
    // 旧文案不得残留
    expect(screen.queryByText('平台审核')).not.toBeInTheDocument()
    expect(screen.queryByText('1-3 个工作日内完成审核')).not.toBeInTheDocument()
  })

  it('renders 适用行业与合规保障（不再使用虚构合作品牌）', () => {
    render(<HomePage />)
    expect(screen.getByText('适用行业与合规保障')).toBeInTheDocument()
    expect(screen.getByText('布艺纺织')).toBeInTheDocument()
    expect(screen.getByText('AI 自动合规甄别')).toBeInTheDocument()
    expect(screen.getByText('正规运营主体')).toBeInTheDocument()
    expect(screen.getByText('多重风控防护')).toBeInTheDocument()
    // 旧虚构合作品牌不得残留
    expect(screen.queryByText('合作品牌')).not.toBeInTheDocument()
    expect(screen.queryByText('品牌 A')).not.toBeInTheDocument()
  })

  it('renders bottom CTA', () => {
    render(<HomePage />)
    expect(screen.getByText(/准备好让AI助手驱动您的业务增长了吗/)).toBeInTheDocument()
    expect(screen.getByText(/AI 自动甄别秒级通过/)).toBeInTheDocument()
  })

  it('renders GB/T 47746-2026 遵循国家标准区块（标准号 + 4 能力点 + 免责小字，issue #2787）', () => {
    render(<HomePage />)
    // 区块标题与标准号
    expect(screen.getByText('遵循国家标准')).toBeInTheDocument()
    expect(screen.getByText(/让人工与智能客服协同更可靠/)).toBeInTheDocument()
    expect(screen.getByText('GB/T 47746-2026')).toBeInTheDocument()
    expect(screen.getByText(/顾客联络服务 人工与智能客户服务协同要求/)).toBeInTheDocument()
    // 4 能力点
    expect(screen.getByText('自动识别复杂诉求转人工')).toBeInTheDocument()
    expect(screen.getByText('转人工规则可配置')).toBeInTheDocument()
    expect(screen.getByText('转人工即同步上下文')).toBeInTheDocument()
    expect(screen.getByText('AI 严格承诺边界')).toBeInTheDocument()
    // 关键证据句（能力点描述）
    expect(screen.getByText(/沟通记录同步给人工客服，无需重复描述/)).toBeInTheDocument()
    expect(screen.getByText(/AI 只做规则解释与材料收集/)).toBeInTheDocument()
    // 免责小字（无认证/备案结论）
    expect(screen.getByText(/不构成任何认证、检测或备案结论/)).toBeInTheDocument()
    // 红线：不得出现「已通过认证/备案」等误导措辞
    expect(screen.queryByText(/已通过.*认证/)).not.toBeInTheDocument()
  })
})
