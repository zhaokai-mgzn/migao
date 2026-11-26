// case_ids: OB-004, OB-005, OB-008
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

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

describe('CorporateHomePage（官网首页：产品页版式 + 场景分节，issue #9121）', () => {
  // ── Hero：浅色产品页头 ──

  it('hero：产品名 + 主标 + 企业级 AI 经营平台定位', () => {
    render(<HomePage />)
    expect(screen.getAllByText(/生意管家/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/让经营有据可依/)).toBeInTheDocument()
    expect(screen.getByText('让生意每天向前')).toBeInTheDocument()
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/企业级 AI 经营平台/)).toBeInTheDocument()
  })

  it('hero 副标：生意管家定位 + 双 AI 分工 + 数据同源', () => {
    render(<HomePage />)
    expect(screen.getByText(/生意管家是词元通达面向布艺 \/ 窗帘企业的 AI 经营平台/)).toBeInTheDocument()
    expect(screen.getByText(/米宝接待顾客、算料报价、下单与售后/)).toBeInTheDocument()
    expect(screen.getByText(/黄金策看经营、跟进度、处理商品与财务/)).toBeInTheDocument()
    expect(screen.getByText(/两侧读取同源经营数据/)).toBeInTheDocument()
  })

  it('hero 能力标签（六个经营动作）与四条事实', () => {
    render(<HomePage />)
    for (const chip of ['智能接待', '算料报价', '订单生产', '库存批次', '计件对账', '经营决策']) {
      expect(screen.getAllByText(chip).length).toBeGreaterThanOrEqual(1)
    }
    for (const fact of ['双 AI 分工', '四端同源', '布艺行业原生', '企业级隔离与审计']) {
      expect(screen.getAllByText(fact).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('hero 右侧：工作台示意（订单 / 生产 / 库存 + 黄金策问答）', () => {
    render(<HomePage />)
    expect(screen.getByText('生意管家 · 工作台')).toBeInTheDocument()
    expect(screen.getAllByText('界面示意').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('黄金策').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('订单趋势')).toBeInTheDocument()
  })

  it('CTA：内测期只留预约演示，不露出免费开通入口（OB-008）', () => {
    render(<HomePage />)
    expect(screen.queryByText('免费开通')).not.toBeInTheDocument()
    expect(screen.getAllByText('预约产品演示').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('查看产品能力').length).toBeGreaterThanOrEqual(1)
  })

  // ── 八个能力域 ──

  it('能力域：八个域只列名称与解决的问题，不展开内部菜单', () => {
    render(<HomePage />)
    expect(screen.getByText('八个能力域，覆盖一家布艺企业的日常')).toBeInTheDocument()
    for (const domain of ['客户服务', '订单/商品', '生产管理', '质量管理', '仓储/物料', '财务', '供应链', '组织管理']) {
      expect(screen.getAllByText(domain).length).toBeGreaterThanOrEqual(1)
    }
    for (const internalItem of ['在线接待', '价格本', '智能派单', '余料台账']) {
      expect(screen.queryByText(internalItem)).not.toBeInTheDocument()
    }
  })

  // ── 四个场景分节（参考站的核心版式）──

  it('场景标签可切换说明（参考站的可切换 pills）', () => {
    render(<HomePage />)
    const tab = screen.getByRole('tab', { name: '算料报价' })
    fireEvent.click(tab)
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('按尺寸与工艺计算用料，报价明确标注为估算。')).toBeInTheDocument()
  })

  it('四个场景分节：顾客经营 / 经营决策 / 生产与交付 / 库存与对账', () => {
    render(<HomePage />)
    for (const title of [
      '从顾客开口，到订单成交',
      '问经营，不用等报表',
      '订单到交付，进度在同一链路',
      '批次、库存、计件与收支，逐笔可查',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
    // 每节的标签与产品示意（4 节 + hero = 至少 5 处「界面示意」）
    expect(screen.getAllByText('界面示意').length).toBeGreaterThanOrEqual(5)
    expect(screen.getByText('微信客服 · 米宝')).toBeInTheDocument()
    expect(screen.getByText('管理后台 · 经营报表')).toBeInTheDocument()
    expect(screen.getByText('加工单 · 生产进度')).toBeInTheDocument()
    expect(screen.getByText('库存台账 · 批次')).toBeInTheDocument()
  })

  // ── 为什么选择 ──

  it('优势：行业原生 / 双 AI 分工 / 数据同源 / 可审计的 AI', () => {
    render(<HomePage />)
    expect(screen.getByText('行业原生，数据同源，边界清楚')).toBeInTheDocument()
    for (const title of ['行业原生', '双 AI 分工', '数据同源', '可审计的 AI']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  // ── 平台保障 / 适用企业 / 交付 ──

  it('平台保障：六格支持（主体 / 隔离 / 权限 / 四端 / 模板 / 审计）', () => {
    render(<HomePage />)
    expect(screen.getByText('企业级底座，交付前就把边界写清')).toBeInTheDocument()
    for (const title of [
      '正规运营主体',
      '租户级数据隔离',
      '岗位权限可控',
      '四端数据同源',
      '行业模板预置',
      '操作全程可追溯',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('适用企业：三类布艺经营形态', () => {
    render(<HomePage />)
    expect(screen.getByText('深耕布艺，服务三类经营形态')).toBeInTheDocument()
    for (const name of ['窗帘定制商', '布艺加工厂', '批零一体企业']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    for (const stale of ['家居建材', '服装服饰', '电商零售']) {
      expect(screen.queryByText(stale)).not.toBeInTheDocument()
    }
  })

  it('三步开通 + 底部 CTA（内测期只留预约演示，OB-008）', () => {
    render(<HomePage />)
    expect(screen.getByText('三步开通，按您的流程落地')).toBeInTheDocument()
    for (const title of ['预约演示', '对齐流程', '开通上线']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText('把 AI 带进经营现场')).toBeInTheDocument()
    expect(screen.getByText(/预约演示，按您的业务流程逐项确认/)).toBeInTheDocument()
  })

  // ── 能力边界 + 国标 ──

  it('能力边界：AI 不编造 / 定价权归属商品库 / 敏感事项不由 AI 决定', () => {
    render(<HomePage />)
    expect(screen.getByText('把 AI 能做什么、不能做什么写在明处')).toBeInTheDocument()
    for (const title of ['数据之外不作答', '定价权归属商品库', '敏感事项不由 AI 决定']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    expect(screen.getByText(/不编造订单、物流与金额/)).toBeInTheDocument()
  })

  it('GB/T 47746-2026 遵循国家标准区块（标准号 + 4 能力点 + 免责小字）', () => {
    render(<HomePage />)
    expect(screen.getByText('遵循国家标准')).toBeInTheDocument()
    expect(screen.getByText(/人机协同机制有据可依/)).toBeInTheDocument()
    expect(screen.getAllByText(/GB\/T 47746-2026/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/顾客联络服务 人工与智能客户服务协同要求/)).toBeInTheDocument()
    for (const point of ['自动识别复杂诉求转人工', '转人工规则可配置', '转人工即同步上下文', 'AI 承诺边界明确']) {
      expect(screen.getByText(point)).toBeInTheDocument()
    }
    expect(screen.getByText(/不构成任何认证、检测或备案结论/)).toBeInTheDocument()
    expect(screen.queryByText(/已通过.*认证/)).not.toBeInTheDocument()
    expect(screen.queryByText(/无缝接管/)).not.toBeInTheDocument()
  })

  // ── 宣传真实性 / 视觉 / 口吻 ──

  it('宣传真实性：不夸大能力（禁「自动学习 / 越用越懂 / 精准应答」复活）', () => {
    render(<HomePage />)
    expect(screen.queryByText(/自动学习/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越懂/)).not.toBeInTheDocument()
    expect(screen.queryByText(/越用越精准/)).not.toBeInTheDocument()
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
    const BANNED_OLD = ['企业智能工作助手', '企业智能助手', '米宝 · 智能助手', '米宝 · B端工作助手', '小布 · AI']
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
    expect(offenders, `定位标签必须来自单一源；命中：${offenders.join('；')}`).toEqual([])
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
