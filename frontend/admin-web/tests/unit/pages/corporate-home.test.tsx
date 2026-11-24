// case_ids: OB-004, OB-005, OB-008
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import HomePage from '@/app/(corporate)/page'
import {
  findColloquialMarkers,
  findPersonifiedAi,
  findQuantifierRhetoric,
} from './copy-voice-banlist'
import { AI_ROLES } from '@/config/ai-roles'
import { readFileSync } from 'fs'
import { join } from 'path'
import { execSync } from 'child_process'

describe('CorporateHomePage（官网首页：产品 / 能力 / 价值 / 优势，issue #9121）', () => {
  // ── Hero：产品定位 ──

  it('hero：产品名 + 使命主标 + 企业级 AI 经营平台定位', () => {
    render(<HomePage />)
    expect(screen.getAllByText(/生意管家/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/让 AI 成为/)).toBeInTheDocument()
    expect(screen.getAllByText(/每一家企业的经营能力/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/企业级 AI 经营平台/)).toBeInTheDocument()
  })

  it('hero 副标：生意管家定位 + 双 AI 分工 + 数据同源', () => {
    render(<HomePage />)
    expect(
      screen.getByText(/生意管家是词元通达面向布艺 \/ 窗帘企业的 AI 经营平台/)
    ).toBeInTheDocument()
    expect(screen.getByText(/米宝承接咨询、算料报价、/)).toBeInTheDocument()
    expect(screen.getByText(/黄金策承接商品、订单、生产、库存与财务/)).toBeInTheDocument()
    expect(screen.getByText(/两侧读取同源经营数据/)).toBeInTheDocument()
  })

  it('hero 事实标签（可核实的四条）', () => {
    render(<HomePage />)
    for (const fact of [
      '双 AI 分工 · 各守边界',
      '四端同源 · 数据一致',
      '布艺行业原生',
      '企业级隔离与审计',
    ]) {
      expect(screen.getByText(fact)).toBeInTheDocument()
    }
  })

  it('hero 右侧：管家每天处理的三件事', () => {
    render(<HomePage />)
    expect(screen.getByText('管家每天处理的三件事')).toBeInTheDocument()
    for (const title of ['接客', '管货', '看账']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  it('CTA：内测期只留预约演示，不露出免费开通入口（OB-008）', () => {
    render(<HomePage />)
    expect(screen.queryByText('免费开通')).not.toBeInTheDocument()
    expect(screen.getAllByText('预约产品演示').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('查看产品能力').length).toBeGreaterThanOrEqual(1)
  })

  // ── 经营价值：重点突出 ──

  it('经营价值：四件耗人的日常，交给管家', () => {
    render(<HomePage />)
    expect(screen.getByText('四件耗人的事，交给管家')).toBeInTheDocument()
    for (const title of ['咨询有回应', '报价有依据', '交付有进度', '账目有明细']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  // ── 产品能力：三条能力线 ──

  it('产品能力：顾客经营 / 经营决策 / 业务全链路', () => {
    render(<HomePage />)
    expect(screen.getByText('两条 AI，共用业务底座')).toBeInTheDocument()
    for (const title of ['顾客经营', '经营决策', '业务全链路']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText('米宝 · 顾客侧 AI')).toBeInTheDocument()
    expect(screen.getByText('黄金策 · 经营侧 AI')).toBeInTheDocument()
  })

  // ── 为什么选择我们 ──

  it('优势：行业原生 / 双 AI 分工 / 数据同源 / 可审计的 AI', () => {
    render(<HomePage />)
    expect(screen.getByText('行业原生，数据同源，边界清楚')).toBeInTheDocument()
    for (const title of ['行业原生', '双 AI 分工', '数据同源', '可审计的 AI']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  // ── 能力域 ──

  it('能力域：八个域只列名称与解决的问题，不展开内部菜单', () => {
    render(<HomePage />)
    expect(screen.getByText('八个能力域，覆盖日常经营')).toBeInTheDocument()
    for (const domain of [
      '客户服务',
      '订单/商品',
      '生产管理',
      '质量管理',
      '仓储/物料',
      '财务',
      '供应链',
      '组织管理',
    ]) {
      expect(screen.getAllByText(domain).length).toBeGreaterThanOrEqual(1)
    }
    for (const internalItem of ['在线接待', '价格本', '智能派单', '余料台账', '计件工资']) {
      expect(screen.queryByText(internalItem)).not.toBeInTheDocument()
    }
  })

  // ── 行业纵深 + 适用企业 ──

  it('行业纵深：四道关口 + 适用企业四类', () => {
    render(<HomePage />)
    expect(screen.getByText('布艺生意的四道关口，系统原生处理')).toBeInTheDocument()
    for (const title of ['算料与报价', '多规格 SKU', '工序与计件', '批次与余料']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
    expect(screen.getByText('适用企业')).toBeInTheDocument()
    for (const name of ['窗帘定制商', '布艺加工厂', '批零一体企业', '品牌与渠道商']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    // 未验证行业的旧口径不得回流
    for (const stale of ['家居建材', '服装服饰', '电商零售']) {
      expect(screen.queryByText(stale)).not.toBeInTheDocument()
    }
  })

  // ── 能力边界 + 平台保障 ──

  it('能力边界：AI 不编造 / 定价权归属商品库 / 敏感事项不由 AI 决定', () => {
    render(<HomePage />)
    expect(screen.getByText('把 AI 能做什么、不能做什么写在明处')).toBeInTheDocument()
    for (const title of ['数据之外不作答', '定价权归属商品库', '敏感事项不由 AI 决定']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText(/不编造订单、物流与金额/)).toBeInTheDocument()
  })

  it('平台保障：正规主体 / 隔离 / 权限 / 审计', () => {
    render(<HomePage />)
    expect(screen.getByText('企业级底座：隔离、权限与审计')).toBeInTheDocument()
    for (const title of ['正规运营主体', '租户级数据隔离', '岗位权限可控', '操作全程可追溯']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
    // 无证据的能力不得宣称（行级数据范围与向量检索都没有实现）
    expect(screen.queryByText(/数据范围/)).not.toBeInTheDocument()
    expect(screen.queryByText(/向量检索/)).not.toBeInTheDocument()
  })

  // ── 国标宣称（OB-005：标准号 + 4 能力点 + 免责小字）──

  it('GB/T 47746-2026 遵循国家标准区块（标准号 + 4 能力点 + 免责小字）', () => {
    render(<HomePage />)
    expect(screen.getByText('遵循国家标准')).toBeInTheDocument()
    expect(screen.getByText(/人机协同机制有据可依/)).toBeInTheDocument()
    expect(screen.getAllByText(/GB\/T 47746-2026/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/顾客联络服务 人工与智能客户服务协同要求/)).toBeInTheDocument()
    for (const point of [
      '自动识别复杂诉求转人工',
      '转人工规则可配置',
      '转人工即同步上下文',
      'AI 承诺边界明确',
    ]) {
      expect(screen.getByText(point)).toBeInTheDocument()
    }
    expect(screen.getByText(/不构成任何认证、检测或备案结论/)).toBeInTheDocument()
    // 红线：不得出现「已通过认证 / 备案 / 无缝接管」等误导措辞
    expect(screen.queryByText(/已通过.*认证/)).not.toBeInTheDocument()
    expect(screen.queryByText(/无缝接管/)).not.toBeInTheDocument()
  })

  // ── 开通流程 + 底部 CTA ──

  it('三步开通 + 底部 CTA（内测期只留预约演示，OB-008）', () => {
    render(<HomePage />)
    expect(screen.getByText('三步开通，按您的流程落地')).toBeInTheDocument()
    for (const title of ['预约演示', '对齐流程', '开通上线']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText('把 AI 带进经营现场')).toBeInTheDocument()
    expect(screen.getByText(/预约演示，按您的业务流程逐项确认/)).toBeInTheDocument()
  })

  // ── 宣传真实性 ──

  it('宣传真实性：不夸大能力（禁「自动学习 / 越用越懂 / 精准应答」复活）', () => {
    render(<HomePage />)
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越懂/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越精准/)).not.toBeInTheDocument()
    expect(screen.queryByText(/基于企业知识库精准应答/)).not.toBeInTheDocument()
  })

  it('宣传真实性：官网不得出现占位联系方式（电话 / 邮箱 / 地址）', () => {
    render(<HomePage />)
    expect(screen.queryByText(/400-888-8888/)).not.toBeInTheDocument()
    expect(screen.queryByText(/contact@migao-ai\.com/)).not.toBeInTheDocument()
    expect(screen.queryByText(/文一西路000号/)).not.toBeInTheDocument()
  })

  it('视觉口径：不再使用通用蓝色渐变模板（改用织物质感 token）', () => {
    const { container } = render(<HomePage />)
    expect(container.innerHTML).not.toContain('from-blue-600')
    expect(container.innerHTML).not.toContain('to-indigo-800')
  })

  // ── 文案口吻与质感 ──

  it('文案口吻：首页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<HomePage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `首页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })

  it('文案口吻判据自身的判别力自证：词表能命中已知口语样本', () => {
    expect(findColloquialMarkers('黄金策打理经营，把商品管住，做不到的事 AI 会直说')).toEqual([
      '打理',
      '管住',
      '直说',
    ])
    expect(findColloquialMarkers('用 AI 数智化赋能中小企业')).toEqual([])
  })

  it('文案质感：首页渲染文本无量化排比、无拟人量词', () => {
    const { container } = render(<HomePage />)
    const text = container.textContent ?? ''
    expect(findQuantifierRhetoric('一套经营平台，一次咨询，一张订单')).toEqual(['一套', '一次', '一张'])
    expect(findPersonifiedAi('两位 AI 助手')).toEqual(['两位 AI'])
    expect(findQuantifierRhetoric(text)).toEqual([])
    expect(findPersonifiedAi(text)).toEqual([])
  })

  // ── 双 AI 定位标签的单一源（issue #6330）──

  it('定位标签单一源：口径钉在 config/ai-roles.ts，定位面不得硬编码', () => {
    expect([AI_ROLES.mibao, AI_ROLES.xiaobu]).toEqual(['企业智能生产管家', '企业智能客服'])
    const LABELS = [AI_ROLES.mibao, AI_ROLES.xiaobu]
    const BANNED_OLD = [
      '企业智能工作助手',
      '企业智能助手',
      '米宝 · 智能助手',
      '米宝 · B端工作助手',
      '小布 · AI',
    ]
    const scan = (src: string) => [
      ...LABELS.filter((label) => src.includes(label)).map((label) => `硬编码「${label}」`),
      ...BANNED_OLD.filter((old) => src.includes(old)).map((old) => `旧标签回流「${old}」`),
    ]

    expect(scan("  role: '企业智能生产管家',")).toEqual(['硬编码「企业智能生产管家」'])
    expect(scan('  米宝 · 智能助手')).toEqual(['旧标签回流「米宝 · 智能助手」'])
    expect(scan("import { AI_ROLES } from '@/config/ai-roles'\n  role: AI_ROLES.mibao,")).toEqual([])

    const files = [
      'src/app/(corporate)/page.tsx',
      'src/components/corporate/home-content.ts',
      'src/app/(corporate)/services/page.tsx',
      'src/app/register/page.tsx',
      'src/components/ai-assistant/FloatingAssistant.tsx',
      'src/components/chat/SessionInsight.tsx',
      'src/app/(dashboard)/agent-workspace/human-sessions/page.tsx',
    ]
    const offenders = files.flatMap((rel) =>
      scan(readFileSync(join(process.cwd(), rel), 'utf-8')).map((finding) => `${rel} ${finding}`),
    )
    expect(
      offenders,
      `定位标签必须来自单一源 src/config/ai-roles.ts（改词只改那里）；命中：${offenders.join('；')}`,
    ).toEqual([])
  })

  it('定位标签全仓残留：旧标签不得出现在白名单之外的任何文件（issue #6335）', () => {
    const OLD = [
      '企业智能工作助手',
      '企业智能助手',
      '米宝 · 智能助手',
      '米宝 · B端工作助手',
      '小布 · AI',
      '米宝 · 商家助手',
      '小布 · 智能购物助手',
    ]
    const ALLOW = [
      /^CHANGELOG\.md$/,
      /^frontend\/admin-web\/src\/config\/ai-roles\.ts$/,
      /^frontend\/admin-web\/tests\/unit\/pages\/corporate-home\.test\.tsx$/,
      /^acceptance\//,
    ]
    const patterns = OLD.map((o) => `-e '${o}'`).join(' ')
    let out = ''
    try {
      out = execSync(`git grep -l -F ${patterns}`, {
        cwd: join(process.cwd(), '..', '..'),
        encoding: 'utf-8',
      })
    } catch {
      out = ''
    }
    const offenders = out
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .filter((rel) => !ALLOW.some((re) => re.test(rel)))
    expect(offenders, `旧定位标签残留在白名单之外：${offenders.join('、')}`).toEqual([])
  })
})
