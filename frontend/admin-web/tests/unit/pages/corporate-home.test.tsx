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
    Factory: stub('factory'),
    Sofa: stub('sofa'),
    Shirt: stub('shirt'),
    ShoppingBag: stub('shopping-bag'),
    Landmark: stub('landmark'),
    BadgeCheck: stub('badge-check'),
  }
})

import HomePage from '@/app/(corporate)/page'

describe('CorporateHomePage（官网主页 v3：云厂商式事实营销，issue #2852，公司杭州词元通达科技有限公司）', () => {
  it('renders hero heading：事实型主标（7×24 客服在线 / 经营数据一问即答）', () => {
    render(<HomePage />)
    expect(screen.getByText(/7×24 客服在线/)).toBeInTheDocument()
    expect(screen.getByText(/经营数据一问即答/)).toBeInTheDocument()
  })

  it('renders company name and 企业级 AI 客服与经营平台 positioning in hero badge', () => {
    render(<HomePage />)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/企业级 AI 客服与经营平台/)).toBeInTheDocument()
  })

  it('renders hero description：米宝/小布 能力规格句', () => {
    render(<HomePage />)
    expect(screen.getByText(/米宝——企业 AI 工作助手/)).toBeInTheDocument()
    expect(screen.getByText(/小布——AI 智能客服/)).toBeInTheDocument()
  })

  it('renders CTA links', () => {
    render(<HomePage />)
    // "立即入驻" appears in both hero and bottom CTA sections
    const ctaLinks = screen.getAllByText('立即入驻')
    expect(ctaLinks).toHaveLength(2)
    expect(screen.getByText('了解更多')).toBeInTheDocument()
  })

  it('renders 产品区：米宝与小布能力清单', () => {
    render(<HomePage />)
    expect(screen.getByText(/一位打理店内经营，一位接待您的客户/)).toBeInTheDocument()
    expect(screen.getByText('米宝')).toBeInTheDocument()
    expect(screen.getByText('企业智能工作助手')).toBeInTheDocument()
    expect(screen.getByText('小布')).toBeInTheDocument()
    expect(screen.getByText('AI 智能客服')).toBeInTheDocument()
    // 能力规格要点
    expect(screen.getByText('订单跟踪与异常提醒')).toBeInTheDocument()
    expect(screen.getByText('库存盘点与智能预警')).toBeInTheDocument()
    expect(screen.getByText('订单进度与物流实时查询')).toBeInTheDocument()
    expect(screen.getByText('复杂诉求自动转人工，上下文随行')).toBeInTheDocument()
  })

  it('renders 人机协同流程图（AI 先应答，人工来兜底）', () => {
    render(<HomePage />)
    expect(screen.getByText('人机协同')).toBeInTheDocument()
    expect(screen.getByText(/AI 先应答，人工来兜底/)).toBeInTheDocument()
    expect(screen.getByText('客户咨询')).toBeInTheDocument()
    expect(screen.getByText('小布 AI 应答')).toBeInTheDocument()
    expect(screen.getByText('自动转人工')).toBeInTheDocument()
    expect(screen.getByText('人工接续')).toBeInTheDocument()
  })

  it('renders 对比表：自招客服 vs 普通机器人 vs 米高', () => {
    render(<HomePage />)
    expect(screen.getByText(/和自招客服、普通问答机器人差在哪/)).toBeInTheDocument()
    expect(screen.getByText('自招人工客服')).toBeInTheDocument()
    expect(screen.getByText('普通客服机器人')).toBeInTheDocument()
    expect(screen.getByText('7×24，大模型理解业务')).toBeInTheDocument()
    expect(screen.getByText('自动转人工 + 上下文同步')).toBeInTheDocument()
    expect(screen.getByText('AI 即问即答')).toBeInTheDocument()
    expect(screen.getByText('分钟级开通，按年订阅')).toBeInTheDocument()
  })

  it('renders 平台模块（管理后台）with feature names', () => {
    render(<HomePage />)
    expect(screen.getByText('管理后台')).toBeInTheDocument()
    expect(screen.getByText(/商品、订单、知识库，一个后台统一管理/)).toBeInTheDocument()
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('知识库')).toBeInTheDocument()
  })

  it('renders 平台保障（正规运营主体 / 租户隔离 / 多重风控）', () => {
    render(<HomePage />)
    expect(screen.getByText('平台保障')).toBeInTheDocument()
    expect(screen.getByText('AI 自动合规甄别')).toBeInTheDocument()
    expect(screen.getByText('正规运营主体')).toBeInTheDocument()
    expect(screen.getByText('多重风控防护')).toBeInTheDocument()
  })

  it('renders 适合行业 with 行业名称（不再使用虚构合作品牌）', () => {
    render(<HomePage />)
    expect(screen.getByText('适合行业')).toBeInTheDocument()
    expect(screen.getByText('布艺纺织')).toBeInTheDocument()
    expect(screen.getByText('家居建材')).toBeInTheDocument()
    expect(screen.getByText('服装服饰')).toBeInTheDocument()
    expect(screen.getByText('电商零售')).toBeInTheDocument()
    // 旧虚构合作品牌不得残留
    expect(screen.queryByText('合作品牌')).not.toBeInTheDocument()
    expect(screen.queryByText('品牌 A')).not.toBeInTheDocument()
  })

  it('renders 三步开始 with AI 智能甄别（不再出现人工 1-3 工作日审核）', () => {
    render(<HomePage />)
    expect(screen.getByText('开始使用')).toBeInTheDocument()
    expect(screen.getByText(/三步，开始使用/)).toBeInTheDocument()
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('AI 智能甄别')).toBeInTheDocument()
    expect(screen.getByText('即刻开通')).toBeInTheDocument()
    // 旧文案不得残留
    expect(screen.queryByText('平台审核')).not.toBeInTheDocument()
    expect(screen.queryByText('1-3 个工作日内完成审核')).not.toBeInTheDocument()
  })

  it('renders bottom CTA：几分钟开通，两位 AI 即刻开始工作', () => {
    render(<HomePage />)
    expect(screen.getByText(/几分钟开通，两位 AI 即刻开始工作/)).toBeInTheDocument()
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
    // 复杂诉求转人工能力仍在（小布能力清单与对比表）
    expect(screen.getByText('复杂诉求自动转人工，上下文随行')).toBeInTheDocument()
    expect(screen.getByText(/AI 应答基于实时业务数据，不编造事实/)).toBeInTheDocument()
    // 旧夸大表述不得残留
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越懂/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越精准/)).not.toBeInTheDocument()
    expect(screen.queryByText(/基于企业知识库精准应答/)).not.toBeInTheDocument()
  })
})
