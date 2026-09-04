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
    Smartphone: stub('smartphone'),
    ShieldCheck: stub('shield-check'),
    FileText: stub('file-text'),
    Zap: stub('zap'),
    Rocket: stub('rocket'),
    ArrowRight: stub('arrow-right'),
    Check: stub('check'),
    Clock: stub('clock'),
    Factory: stub('factory'),
    Sofa: stub('sofa'),
    Shirt: stub('shirt'),
    ShoppingBag: stub('shopping-bag'),
    Landmark: stub('landmark'),
    BadgeCheck: stub('badge-check'),
  }
})

import HomePage from '@/app/(corporate)/page'

describe('CorporateHomePage（整页品牌化：企业 AI 智能化叙事，米宝×小布双 AI 员工，公司杭州词元通达科技有限公司，issue #2848）', () => {
  it('renders hero heading: 米宝×小布 品牌 + 人设身份（AI 员工 × AI 客服）', () => {
    render(<HomePage />)
    expect(screen.getByText(/米宝 × 小布/)).toBeInTheDocument()
    // 人设镜像行：按位置对应 米宝=AI 员工（内部运营）、小布=AI 客服
    expect(screen.getByText(/AI 员工 × AI 客服/)).toBeInTheDocument()
  })

  it('renders company name and 企业 AI 智能化平台 positioning in hero badge', () => {
    render(<HomePage />)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/企业 AI 智能化平台/)).toBeInTheDocument()
  })

  it('renders hero description 双角色分工 + AI 自动甄别秒级开通', () => {
    render(<HomePage />)
    expect(screen.getByText(/米宝替您打理内部——订单、库存、售后件件有着落/)).toBeInTheDocument()
    expect(screen.getByText(/小布替您接待客户——咨询、物流、退换样样有回应/)).toBeInTheDocument()
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

  it('renders 开场叙事（企业 AI 智能化 + slogan + 三段式故事点）', () => {
    render(<HomePage />)
    expect(screen.getByText('企业 AI 智能化')).toBeInTheDocument()
    expect(screen.getByText(/AI 正在改写生意的方式/)).toBeInTheDocument()
    // slogan 出现在开场副文案
    expect(screen.getByText(/让每家企业，都配得起一支 AI 团队/)).toBeInTheDocument()
    // 三个故事点
    expect(screen.getByText(/从咨询工具，到在岗员工/)).toBeInTheDocument()
    expect(screen.getByText(/从人工值守，到 7×24 在岗/)).toBeInTheDocument()
    expect(screen.getByText(/从大厂专属，到开箱即用/)).toBeInTheDocument()
  })

  it('renders 双 AI 员工区（米宝 + 小布，一支 AI 团队）', () => {
    render(<HomePage />)
    expect(screen.getByText('两位 AI 员工')).toBeInTheDocument()
    expect(screen.getByText(/两位 AI 员工，就是一支 AI 团队/)).toBeInTheDocument()
    expect(screen.getByText(/老板管店，客服管客，AI 干活/)).toBeInTheDocument()
    expect(screen.getByText('米宝')).toBeInTheDocument()
    expect(screen.getByText('企业智能工作助手')).toBeInTheDocument()
    expect(screen.getByText('小布')).toBeInTheDocument()
    expect(screen.getByText('AI 智能客服')).toBeInTheDocument()
  })

  it('renders 平台底座 section with feature names', () => {
    render(<HomePage />)
    expect(screen.getByText('平台底座')).toBeInTheDocument()
    expect(screen.getByText(/生意先数字化，AI 才好干活/)).toBeInTheDocument()
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('知识库')).toBeInTheDocument()
  })

  it('renders 为什么是米高 with 差异化 advantage names', () => {
    render(<HomePage />)
    expect(screen.getByText('为什么是米高')).toBeInTheDocument()
    expect(screen.getByText(/客服机器人常见，在岗干活的 AI 员工少有/)).toBeInTheDocument()
    expect(screen.getByText('一支 AI 团队，双岗协同')).toBeInTheDocument()
    expect(screen.getByText('懂行业的商品建模')).toBeInTheDocument()
    expect(screen.getByText('能办事，不是只会聊天')).toBeInTheDocument()
    expect(screen.getByText('微信私域原生渠道')).toBeInTheDocument()
    expect(screen.getByText('租户级数据隔离')).toBeInTheDocument()
    expect(screen.getByText('按国标设计的人机协同')).toBeInTheDocument()
  })

  it('renders steps with AI 智能甄别（不再出现人工 1-3 工作日审核）', () => {
    render(<HomePage />)
    expect(screen.getByText('三步上岗')).toBeInTheDocument()
    expect(screen.getByText(/三步，给您的企业添上 AI 员工/)).toBeInTheDocument()
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('AI 智能甄别')).toBeInTheDocument()
    expect(screen.getByText('即刻开通')).toBeInTheDocument()
    // 旧文案不得残留
    expect(screen.queryByText('平台审核')).not.toBeInTheDocument()
    expect(screen.queryByText('1-3 个工作日内完成审核')).not.toBeInTheDocument()
  })

  it('renders 适用行业场景与合规保障（不再使用虚构合作品牌）', () => {
    render(<HomePage />)
    expect(screen.getByText('适合谁')).toBeInTheDocument()
    expect(screen.getByText(/从布艺出发，面向每一家想 AI 化的企业/)).toBeInTheDocument()
    expect(screen.getByText('布艺纺织')).toBeInTheDocument()
    expect(screen.getByText('家居建材')).toBeInTheDocument()
    expect(screen.getByText('服装服饰')).toBeInTheDocument()
    expect(screen.getByText('电商零售')).toBeInTheDocument()
    expect(screen.getByText('AI 自动合规甄别')).toBeInTheDocument()
    expect(screen.getByText('正规运营主体')).toBeInTheDocument()
    expect(screen.getByText('多重风控防护')).toBeInTheDocument()
    // 旧虚构合作品牌不得残留
    expect(screen.queryByText('合作品牌')).not.toBeInTheDocument()
    expect(screen.queryByText('品牌 A')).not.toBeInTheDocument()
  })

  it('renders bottom CTA with 企业 AI 智能化收尾', () => {
    render(<HomePage />)
    expect(screen.getByText(/企业 AI 智能化，从为您的店添两位 AI 员工开始/)).toBeInTheDocument()
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

  it('宣传真实性：不夸大 AI 自学习/知识库检索能力（RAG POC 未开放，issue #2807）', () => {
    render(<HomePage />)
    expect(screen.getByText(/商品·订单·物流实时查询应答/)).toBeInTheDocument()
    expect(screen.getByText(/自动判断复杂诉求，转人工客服兜底/)).toBeInTheDocument()
    expect(screen.getByText(/AI 应答基于实时业务数据，不编造事实/)).toBeInTheDocument()
    // 旧夸大表述不得残留
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越懂/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越精准/)).not.toBeInTheDocument()
    expect(screen.queryByText(/基于企业知识库精准应答/)).not.toBeInTheDocument()
  })
})
