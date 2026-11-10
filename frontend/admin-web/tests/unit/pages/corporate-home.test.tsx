// case_ids: OB-004, OB-005
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

describe('CorporateHomePage（官网主页 v5：中小企业 AI 经营平台叙事，issue #8863）', () => {
  // ── Hero：使命 + 产品定位 ──

  it('hero：使命主标 + 企业级 AI 经营平台定位', () => {
    render(<HomePage />)
    expect(screen.getByText(/用 AI 数智化/)).toBeInTheDocument()
    expect(screen.getByText(/赋能每一家中小企业/)).toBeInTheDocument()
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/企业级 AI 经营平台/)).toBeInTheDocument()
  })

  it('hero 副标：观星台定位 + 双 AI 分工 + 数据同源', () => {
    render(<HomePage />)
    expect(
      screen.getByText(/观星台是词元通达面向布艺 \/ 窗帘企业的 AI 经营平台/)
    ).toBeInTheDocument()
    expect(screen.getByText(/米宝承接顾客咨询、算料报价、下单与售后/)).toBeInTheDocument()
    expect(screen.getByText(/黄金策承接商品、订单、生产、库存与财务/)).toBeInTheDocument()
    expect(screen.getByText(/读取同源经营数据，回答与后台记录一致/)).toBeInTheDocument()
  })

  it('hero 事实标签（可核实的四条）', () => {
    render(<HomePage />)
    expect(screen.getByText('AI 自动甄别 · 分钟级开通')).toBeInTheDocument()
    expect(screen.getAllByText('租户级数据隔离').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('四端协同 · 数据同源')).toBeInTheDocument()
    expect(screen.getByText('人机协同机制参考 GB/T 47746-2026 设计')).toBeInTheDocument()
  })

  it('CTA：免费开通 + 预约演示', () => {
    render(<HomePage />)
    expect(screen.getAllByText('免费开通')).toHaveLength(2)
    expect(screen.getByText('预约产品演示')).toBeInTheDocument()
    expect(screen.getByText('预约演示')).toBeInTheDocument()
  })

  // ── 经营课题：为什么现在 ──

  it('经营课题：四个真实经营环节', () => {
    render(<HomePage />)
    expect(screen.getByText('智能化的价值，由经营现场检验')).toBeInTheDocument()
    for (const title of [
      '询价与算料依赖经验',
      '订单与生产各自记账',
      '库存与成本缺少台账',
      '服务响应依赖人工',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  // ── 平台架构 ──

  it('平台架构：交互 / 智能 / 业务 / 数据与安全四层', () => {
    render(<HomePage />)
    expect(screen.getByText('四层架构，共用同一数据底座')).toBeInTheDocument()
    for (const layer of ['交互层', '智能层', '业务层', '数据与安全层']) {
      expect(screen.getByText(layer)).toBeInTheDocument()
    }
    expect(
      screen.getByText(/管理后台、顾客小程序、商家小程序与员工端 H5，按角色提供入口与权限/)
    ).toBeInTheDocument()
    expect(screen.getByText(/米宝与黄金策理解业务意图/)).toBeInTheDocument()
    expect(screen.getByText(/八个能力域覆盖客户服务/)).toBeInTheDocument()
    expect(
      screen.getByText(/多租户隔离、行级安全、岗位权限与操作审计/)
    ).toBeInTheDocument()
  })

  // ── 双 AI 分工 ──

  it('双 AI 区块：定位标签 + 能力清单 + 能力边界', () => {
    render(<HomePage />)
    expect(screen.getByText('顾客侧接待，经营侧决策')).toBeInTheDocument()
    expect(screen.getAllByText('黄金策').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('企业智能生产管家').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('米宝').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('企业智能客服').length).toBeGreaterThanOrEqual(1)
    // 能力规格要点（都对应真实存在的模块 / 工具）
    expect(
      screen.getByText('经营洞察：订单量、销售额、环比与待处理事项，支持每日简报')
    ).toBeInTheDocument()
    expect(screen.getByText('生产与计件：工序库、工艺路线、计件工资报表')).toBeInTheDocument()
    expect(screen.getByText('算料报价：按尺寸与工艺计算用料，输出估算报价')).toBeInTheDocument()
    expect(screen.getByText('售后受理：售后咨询与申请，工单恒为待商家审核')).toBeInTheDocument()
    // 能力边界写在明处（不把 AI 说成万能）
    expect(
      screen.getByText(/可写的动作：改价、商品改名、批量改价与批量库存调整、通知标记已读、定时提醒/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量/)
    ).toBeInTheDocument()
  })

  // ── 行业纵深 ──

  it('行业纵深：从询价到交付的六步链路 + 行业正名', () => {
    render(<HomePage />)
    expect(screen.getByText('从询价到交付，全程在同一平台内完成')).toBeInTheDocument()
    for (const title of ['询价与算料', '下单', '生产', '入库', '发货', '售后与对账']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    // 六步里的行业真值：工序三段用行业正名
    expect(
      screen.getByText(/裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）/)
    ).toBeInTheDocument()
    // 未落地的术语不得出现（「拼版」全仓无实现）
    expect(screen.queryByText(/拼版/)).not.toBeInTheDocument()
    // 「质检」已落地（观星台 /quality-inspections + 作业单质检区）⇒ 正向断言
    expect(screen.getAllByText(/质检/).length).toBeGreaterThan(0)
  })

  it('行业纵深四块（算料 / SKU / 工序计件 / 批次余料）', () => {
    render(<HomePage />)
    for (const title of ['算料与报价', '多规格 SKU', '工序与计件', '批次与余料']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  // ── 能力地图 ──

  it('能力地图：八个能力域与独立入口（菜单名与 config/menu.ts 一致）', () => {
    render(<HomePage />)
    expect(screen.getByText('八个能力域，就是后台的菜单')).toBeInTheDocument()
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
    // 真实菜单项抽样（2026-11-06 IA：入库单在仓储/物料、计件工资在财务、商品管理在订单/商品）
    for (const item of [
      '经营报表',
      '智能派单',
      '质检记录',
      '计件工资',
      '入库单',
      '余料台账',
      '省料分析',
      '采购单',
      '岗位权限',
    ]) {
      expect(screen.getAllByText(item).length).toBeGreaterThanOrEqual(1)
    }
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('通知中心')).toBeInTheDocument()
    expect(screen.getByText('查看完整能力清单')).toBeInTheDocument()
  })

  // ── 经营价值 ──

  it('经营价值：四项可核对形态', () => {
    render(<HomePage />)
    expect(screen.getByText('让经营数据可核对、可追溯')).toBeInTheDocument()
    for (const title of ['报价有依据', '交付有进度', '库存有台账', '计件有明细']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  // ── 适用企业 ──

  it('适用企业：四类布艺经营形态，不再列未验证行业', () => {
    render(<HomePage />)
    expect(screen.getByText('深耕布艺，服务四种经营形态')).toBeInTheDocument()
    for (const name of ['窗帘定制商', '布艺加工厂', '批零一体企业', '品牌与渠道商']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    // 旧版列了尚未验证的行业，重构后收窄到真实聚焦
    for (const stale of ['家居建材', '服装服饰', '电商零售']) {
      expect(screen.queryByText(stale)).not.toBeInTheDocument()
    }
  })

  // ── 关于词元通达 / 使命 ──

  it('关于词元通达：使命 + 三条产品原则', () => {
    render(<HomePage />)
    expect(screen.getByText('让 AI 成为中小企业的经营能力')).toBeInTheDocument()
    expect(screen.getByText(/AI 不应只属于大型企业/)).toBeInTheDocument()
    for (const title of ['从现场出发', '以数据为准', '把边界写明']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
  })

  // ── 平台保障 ──

  it('平台保障：准入 / 隔离 / 主体 / 审计 / 权限 / 数据同源', () => {
    render(<HomePage />)
    expect(screen.getByText('平台保障')).toBeInTheDocument()
    expect(screen.getByText('企业级底座：隔离、权限与审计')).toBeInTheDocument()
    for (const title of [
      '智能准入审核',
      '租户级数据隔离',
      '正规运营主体',
      '操作全程可追溯',
      '岗位权限可控',
      '四端数据同源',
    ]) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
    // 无证据的能力不得宣称（行级数据范围与向量检索都没有实现）
    expect(screen.queryByText(/数据范围/)).not.toBeInTheDocument()
    expect(screen.queryByText(/向量检索/)).not.toBeInTheDocument()
  })

  // ── 人机协同（口径：用户 2026-10-04 裁定保留，能力后续会回归）──

  it('人机协同流程（AI 优先应答，人工按规则接续）', () => {
    render(<HomePage />)
    expect(screen.getByText('人机协同')).toBeInTheDocument()
    expect(screen.getByText(/AI 优先应答，人工按规则接续/)).toBeInTheDocument()
    expect(screen.getByText('客户咨询')).toBeInTheDocument()
    expect(screen.getByText('米宝 AI 应答')).toBeInTheDocument()
    expect(screen.getByText('自动转人工')).toBeInTheDocument()
    expect(screen.getByText('人工接续')).toBeInTheDocument()
    expect(screen.getByText('留言受理')).toBeInTheDocument()
  })

  // ── 国标宣称（OB-005：标准号 + 4 能力点 + 免责小字）──

  it('GB/T 47746-2026 遵循国家标准区块（标准号 + 4 能力点 + 免责小字）', () => {
    render(<HomePage />)
    expect(screen.getByText('遵循国家标准')).toBeInTheDocument()
    expect(screen.getByText(/人工与智能客服协同，机制有据可依/)).toBeInTheDocument()
    expect(screen.getByText('GB/T 47746-2026')).toBeInTheDocument()
    expect(screen.getByText(/顾客联络服务 人工与智能客户服务协同要求/)).toBeInTheDocument()
    expect(screen.getByText('自动识别复杂诉求转人工')).toBeInTheDocument()
    expect(screen.getByText('转人工规则可配置')).toBeInTheDocument()
    expect(screen.getByText('转人工即同步上下文')).toBeInTheDocument()
    expect(screen.getByText('AI 承诺边界明确')).toBeInTheDocument()
    expect(screen.getByText(/沟通记录同步给人工客服，无需重复描述/)).toBeInTheDocument()
    expect(screen.getByText(/AI 只做规则解释与材料收集/)).toBeInTheDocument()
    expect(screen.getByText(/不构成任何认证、检测或备案结论/)).toBeInTheDocument()
    // 红线：不得出现「已通过认证 / 备案 / 无缝接管」等误导措辞
    expect(screen.queryByText(/已通过.*认证/)).not.toBeInTheDocument()
    expect(screen.queryByText(/无缝接管/)).not.toBeInTheDocument()
  })

  // ── 开通流程 + 底部 CTA ──

  it('三步开通 + 底部 CTA（免费开通 / 预约演示）', () => {
    render(<HomePage />)
    expect(screen.getByText('三步开通，无需自建基础设施')).toBeInTheDocument()
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('AI 智能甄别')).toBeInTheDocument()
    expect(screen.getByText('即刻开通')).toBeInTheDocument()
    expect(screen.queryByText('平台审核')).not.toBeInTheDocument()
    expect(screen.queryByText('1-3 个工作日内完成审核')).not.toBeInTheDocument()

    expect(screen.getByText('把 AI 带进经营现场')).toBeInTheDocument()
    expect(screen.getByText(/提交申请，AI 自动甄别后即可开通/)).toBeInTheDocument()
  })

  // ── 宣传真实性（issue #6291 新增判据，本单保留）──

  it('宣传真实性：不夸大能力（禁「AI 自动学习 / 越用越懂 / 精准应答」复活）', () => {
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

  // ── 文案口吻（issue #6326：去 AI 口语，改「能力陈述型」书面语）──

  it('文案口吻：首页渲染文本不含 AI 口语词表', () => {
    const { container } = render(<HomePage />)
    const hits = findColloquialMarkers(container.textContent ?? '')
    expect(hits, `首页渲染文本出现 AI 口语词：${hits.join(' / ')}`).toEqual([])
  })

  it('文案口吻判据自身的判别力自证：词表能命中已知口语样本', () => {
    // 让「空断言」进不来：样本是 2026-10-04 版本里逐字出现过的措辞。
    expect(findColloquialMarkers('黄金策打理经营，把商品管住，做不到的事 AI 会直说')).toEqual([
      '打理',
      '管住',
      '直说',
    ])
    expect(findColloquialMarkers('用 AI 数智化赋能中小企业')).toEqual([])
  })

  // ── 双 AI 定位标签的单一源（issue #6330）──

  it('定位标签单一源：口径钉在 config/ai-roles.ts，定位面不得硬编码', () => {
    // 口径本身钉在这里：改词必须同时改这条断言（用户 2026-10-05 裁定）
    expect([AI_ROLES.mibao, AI_ROLES.xiaobu]).toEqual(['企业智能生产管家', '企业智能客服'])
    const LABELS = [AI_ROLES.mibao, AI_ROLES.xiaobu]
    // 旧标签不许回流（用户 2026-10-05 之前的口径；回流 = 定位又漂了）
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

    // 判别力自证：硬编码样本与旧标签样本都必须被检出、合规样本必须零命中（否则本判据是空断言）
    expect(scan("  role: '企业智能生产管家',")).toEqual(['硬编码「企业智能生产管家」'])
    expect(scan('  米宝 · 智能助手')).toEqual(['旧标签回流「米宝 · 智能助手」'])
    expect(scan("import { AI_ROLES } from '@/config/ai-roles'\n  role: AI_ROLES.mibao,")).toEqual([])

    const files = [
      'src/app/(corporate)/page.tsx',
      'src/components/corporate/home-content.ts',
      'src/app/(corporate)/services/page.tsx',
      'src/app/register/page.tsx',
      // #6333 起纳入产品内三处（悬浮助手 / 客服工作台 / 人工会话记录）
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
    // 白名单：历史记录（改了就是篡改证据）/ 单一源的口径文档 / 本判据自己的禁用表
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
      out = '' // git grep 无命中时退 1，不是失败
    }
    const offenders = out
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .filter((rel) => !ALLOW.some((re) => re.test(rel)))

    expect(
      offenders,
      `旧定位标签残留在白名单之外（应改到 AI_ROLES 口径，或说明理由后进白名单）：${offenders.join('、')}`,
    ).toEqual([])
  })

  // ── 文案质感：量化排比与拟人量词（issue #6366）──

  it('文案质感：首页渲染文本无量化排比、无拟人量词', () => {
    const { container } = render(<HomePage />)
    const text = container.textContent ?? ''

    // 判别力自证：病症样本必须被检出、合规样本必须零命中（否则本判据是空断言）
    expect(findQuantifierRhetoric('一套经营平台，一次咨询，一张订单')).toEqual(['一套', '一次', '一张'])
    expect(findPersonifiedAi('两位 AI 助手')).toEqual(['两位 AI'])
    expect(findQuantifierRhetoric('六个能力域 · 4 个终端 · 至少10个字符')).toEqual([])
    expect(findPersonifiedAi('米宝与黄金策')).toEqual([])

    // 真实语料
    const quantifiers = findQuantifierRhetoric(text)
    expect(quantifiers, `首页渲染文本出现量化排比：${quantifiers.join(' / ')}`).toEqual([])
    const personified = findPersonifiedAi(text)
    expect(personified, `首页渲染文本出现拟人量词：${personified.join(' / ')}`).toEqual([])
  })

  it('企业级口径：官网源码不得出现零售单店视角的「门店」（issue #6379 / #6384）', () => {
    const BANNED = ['门店']
    const hit = (text: string) => BANNED.filter((phrase) => text.includes(phrase))

    // 判别力自证：病症样本必须命中、合规样本必须零命中（否则本判据是空断言）
    expect(hit('面向门店经营：以自然语言问答交付商品、订单')).toEqual(['门店'])
    expect(hit('提供门店数量、客服人数与现有流程')).toEqual(['门店'])
    expect(hit('面向企业生产与经营：读取真实经营数据')).toEqual([])
    expect(hit('提供企业规模、客服人数与现有流程')).toEqual([])

    const roots = [
      'frontend/admin-web/src/app/(corporate)',
      'frontend/admin-web/src/components/corporate',
    ]
    const offenders = execSync(
      `git grep -n -F ${BANNED.map((b) => `-e '${b}'`).join(' ')} -- ${roots.map((r) => `'${r}'`).join(' ')} || true`,
      { cwd: join(process.cwd(), '..', '..'), encoding: 'utf-8' },
    )
      .trim()
      .split('\n')
      .filter(Boolean)

    expect(
      offenders,
      `官网出现零售单店视角的「门店」（应改到企业口径，如「企业规模」/「客户接待」）：${offenders.join('；')}`,
    ).toEqual([])
  })

  it('官网源码不得出现无出处的年份（issue #6382）', () => {
    const ALLOWED_LINE = /GB\/T|gb47746|实施|©/
    const yearOffenders = (src: string) =>
      src.split('\n').filter((line) => /20\d\d/.test(line) && !ALLOWED_LINE.test(line))

    // 判别力自证：病症样本必须被检出、三类白名单样本必须零命中（否则本判据是空断言）
    expect(yearOffenders("    period: '2024 Q1',")).toEqual(["    period: '2024 Q1',"])
    expect(yearOffenders('协同机制参考推荐性国标 GB/T 47746-2026 设计')).toEqual([])
    expect(yearOffenders('《顾客联络服务…》（2026-09-01 实施）')).toEqual([])
    expect(yearOffenders('<p>© 2026 杭州词元通达科技有限公司</p>')).toEqual([])

    const roots = [
      'frontend/admin-web/src/app/(corporate)',
      'frontend/admin-web/src/components/corporate',
    ]
    const offenders = execSync(
      `git grep -n -E '20[0-9]{2}' -- ${roots.map((r) => `'${r}'`).join(' ')} || true`,
      { cwd: join(process.cwd(), '..', '..'), encoding: 'utf-8' },
    )
      .trim()
      .split('\n')
      .filter(Boolean)
      .filter((line) => yearOffenders(line).length > 0)

    expect(
      offenders,
      `官网出现无出处的年份（要么删掉时间陈述，要么进白名单并写明出处）：${offenders.join('；')}`,
    ).toEqual([])
  })
})
