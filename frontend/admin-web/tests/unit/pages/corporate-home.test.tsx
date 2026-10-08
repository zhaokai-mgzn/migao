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

describe('CorporateHomePage（官网主页 v4：织物质感重设计 + 真实能力文案 + 能力陈述型口吻，issue #6291 / #6326）', () => {
  // ── Hero ──

  it('renders hero：布艺行业经营平台定位 + 双 AI 主标', () => {
    render(<HomePage />)
    expect(screen.getByText(/AI 客服与经营系统/)).toBeInTheDocument()
    expect(screen.getByText(/覆盖布艺经营全流程/)).toBeInTheDocument()
  })

  it('renders company name and 布艺行业 AI 经营平台 positioning in hero badge', () => {
    render(<HomePage />)
    expect(screen.getAllByText(/杭州词元通达科技有限公司/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/布艺行业 AI 经营平台/)).toBeInTheDocument()
  })

  it('renders hero description：元元与黄金策的分工规格句', () => {
    render(<HomePage />)
    expect(
      screen.getByText(/顾客侧由元元承接：咨询应答、算料报价、下单、物流查询与售后受理/)
    ).toBeInTheDocument()
    expect(screen.getByText(/经营侧由黄金策承接：商品、订单、生产、库存与财务/)).toBeInTheDocument()
  })

  it('renders hero 事实标签（可核实的四条）', () => {
    render(<HomePage />)
    expect(screen.getByText('AI 自动甄别 · 秒级开通')).toBeInTheDocument()
    expect(screen.getAllByText('租户级数据隔离').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('微信小程序 + 商家小程序 + 员工端 H5')).toBeInTheDocument()
    expect(screen.getByText('人机协同机制参考 GB/T 47746-2026 设计')).toBeInTheDocument()
  })

  it('renders CTA links', () => {
    render(<HomePage />)
    expect(screen.getAllByText('立即入驻')).toHaveLength(2)
    expect(screen.getByText('查看产品能力')).toBeInTheDocument()
    expect(screen.getByText('留言咨询')).toBeInTheDocument()
  })

  // ── 双 AI 分工 ──

  it('renders 双 AI 区块：能力清单 + 能力边界', () => {
    render(<HomePage />)
    expect(screen.getByText(/顾客侧服务，经营侧管理/)).toBeInTheDocument()
    expect(screen.getAllByText('黄金策').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('企业智能生产管家').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('元元').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('企业智能客服').length).toBeGreaterThanOrEqual(1)
    // 能力规格要点（都对应真实存在的模块 / 工具）
    expect(
      screen.getByText('经营看板与每日简报：订单量、销售额、环比、待处理事项')
    ).toBeInTheDocument()
    expect(screen.getByText('生产与计件：工序库、工艺路线、计件工资报表')).toBeInTheDocument()
    expect(screen.getByText('窗帘算料报价：按尺寸与工艺算用料，给出估算报价')).toBeInTheDocument()
    expect(screen.getByText('售后受理：售后咨询与申请，工单恒为待商家审核')).toBeInTheDocument()
    // 能力边界写在明处（不把 AI 说成万能）
    expect(screen.getByText(/写操作只有三类：改价、批量上下架、批量库存调整/)).toBeInTheDocument()
    expect(
      screen.getByText(/不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量/)
    ).toBeInTheDocument()
  })

  // ── 行业纵深 ──

  it('renders 「销售与生产的闭环」的行业纵深链路', () => {
    render(<HomePage />)
    expect(screen.getByText('销售与生产的闭环')).toBeInTheDocument()
    for (const title of ['询价与算料', '下单', '生产', '入库', '发货', '售后与对账']) {
      expect(screen.getByText(title)).toBeInTheDocument()
    }
    // 六步里的行业真值：工序三段用行业正名
    expect(screen.getByText(/裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）/)).toBeInTheDocument()
    // 未落地的术语不得出现（「拼版」全仓无实现；「质检」未进任何工艺路线）
    expect(screen.queryByText(/拼版/)).not.toBeInTheDocument()
    expect(screen.queryByText(/质检/)).not.toBeInTheDocument()
  })

  it('renders 行业纵深四块（算料 / SKU / 工序计件 / 批次余料）', () => {
    render(<HomePage />)
    for (const title of ['算料与报价', '多规格 SKU', '工序与计件', '批次与余料']) {
      expect(screen.getAllByText(title).length).toBeGreaterThanOrEqual(1)
    }
  })

  // ── 能力地图 ──

  it('renders 能力地图：六个能力域与独立入口（菜单名与 config/menu.ts 一致）', () => {
    render(<HomePage />)
    expect(screen.getByText('覆盖经营全链路的能力域')).toBeInTheDocument()
    for (const domain of ['工作台', '客户服务', '交易管理', '生产管理', '仓储与物料', '组织管理']) {
      expect(screen.getAllByText(domain).length).toBeGreaterThanOrEqual(1)
    }
    // 真实菜单项抽样（旧版官网只讲「商品 / 订单 / 知识库」三件事）
    for (const item of [
      '经营看板',
      '每日简报',
      '智能派单',
      '计件工资',
      '余料台账',
      '省料看板',
      '岗位权限',
    ]) {
      expect(screen.getAllByText(item).length).toBeGreaterThanOrEqual(1)
    }
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('通知中心')).toBeInTheDocument()
  })

  // ── 人机协同（口径：用户 2026-10-04 裁定保留，能力后续会回归）──

  it('renders 人机协同流程（AI 先应答，人工来兜底）', () => {
    render(<HomePage />)
    expect(screen.getByText('人机协同')).toBeInTheDocument()
    expect(screen.getByText(/AI 优先应答，人工按规则接续/)).toBeInTheDocument()
    expect(screen.getByText('客户咨询')).toBeInTheDocument()
    expect(screen.getByText('元元 AI 应答')).toBeInTheDocument()
    expect(screen.getByText('自动转人工')).toBeInTheDocument()
    expect(screen.getByText('人工接续')).toBeInTheDocument()
    expect(screen.getByText('留言受理')).toBeInTheDocument()
  })

  // ── 国标宣称（OB-005：标准号 + 4 能力点 + 免责小字）──

  it('renders GB/T 47746-2026 遵循国家标准区块（标准号 + 4 能力点 + 免责小字）', () => {
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

  // ── 平台保障 ──

  it('renders 平台保障（运营主体 / 数据隔离 / 权限 / 可追溯）', () => {
    render(<HomePage />)
    expect(screen.getByText('平台保障')).toBeInTheDocument()
    expect(screen.getByText('AI 自动合规甄别')).toBeInTheDocument()
    expect(screen.getByText('正规运营主体')).toBeInTheDocument()
    expect(screen.getByText('操作可追溯')).toBeInTheDocument()
    expect(screen.getByText('岗位权限可控')).toBeInTheDocument()
    // 无证据的能力不得宣称（行级数据范围与向量检索都没有实现）
    expect(screen.queryByText(/数据范围/)).not.toBeInTheDocument()
    expect(screen.queryByText(/向量检索/)).not.toBeInTheDocument()
  })

  // ── 适合行业 / 开通 ──

  it('renders 适合行业 with 行业名称（不使用虚构合作品牌）', () => {
    render(<HomePage />)
    expect(screen.getByText('适合行业')).toBeInTheDocument()
    expect(screen.getByText('布艺纺织')).toBeInTheDocument()
    expect(screen.getByText('家居建材')).toBeInTheDocument()
    expect(screen.getByText('服装服饰')).toBeInTheDocument()
    expect(screen.getByText('电商零售')).toBeInTheDocument()
    expect(screen.queryByText('合作品牌')).not.toBeInTheDocument()
    expect(screen.queryByText('品牌 A')).not.toBeInTheDocument()
  })

  it('renders 三步开始 with AI 智能甄别（不出现人工审核口径）', () => {
    render(<HomePage />)
    expect(screen.getByText('开始使用')).toBeInTheDocument()
    expect(screen.getByText(/三步开通/)).toBeInTheDocument()
    expect(screen.getByText('提交申请')).toBeInTheDocument()
    expect(screen.getByText('AI 智能甄别')).toBeInTheDocument()
    expect(screen.getByText('即刻开通')).toBeInTheDocument()
    expect(screen.queryByText('平台审核')).not.toBeInTheDocument()
    expect(screen.queryByText('1-3 个工作日内完成审核')).not.toBeInTheDocument()
  })

  it('renders bottom CTA：数分钟内完成开通，元元与黄金策同步上线', () => {
    render(<HomePage />)
    expect(screen.getByText(/数分钟内完成开通，元元与黄金策同步上线/)).toBeInTheDocument()
    expect(screen.getByText(/经 AI 自动甄别后秒级返回结果/)).toBeInTheDocument()
  })

  // ── 宣传真实性（issue #6291 新增判据）──

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
    expect(findColloquialMarkers('AI 客服与经营系统')).toEqual([])
  })

  // ── 双 AI 定位标签的单一源（issue #6330）──

  it('定位标签单一源：口径钉在 config/ai-roles.ts，三个定位面不得硬编码', () => {
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
    // 上面那条只扫「声明的 6 个定位面」⇒ e2e 断言 / 注释里的旧标签扫不到
    //（#6335 实测漏了 3 处，其中 2 条 e2e 跑到必红）。这条按**全仓**再兜一遍。
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
    expect(findPersonifiedAi('元元与黄金策')).toEqual([])

    // 真实语料
    const quantifiers = findQuantifierRhetoric(text)
    expect(
      quantifiers,
      `首页渲染文本出现量化排比：${quantifiers.join(' / ')}`,
    ).toEqual([])
    const personified = findPersonifiedAi(text)
    expect(personified, `首页渲染文本出现拟人量词：${personified.join(' / ')}`).toEqual([])
  })
  it('企业级口径：官网源码不得出现零售单店视角的「门店」（issue #6379 / #6384）', () => {
    // 口径（用户 2026-10-05 两次裁定）：
    //   ① 「黄金策不是面向门店经营……是企业级的生产管家」（issue #6379）
    //   ② 「要去掉，不要出现门店，我们是解决企业的问题」（issue #6384）
    // 「门店」是**零售单店**视角，而观星台是**企业级**平台（企业智能生产管家 + 六个能力域）
    // ⇒ 用它描述客户的经营形态或 AI 的朝向，都把客户框小了。
    // 禁用表收窄到**单字**「门店」：前两条（门店经营 / 门店真实数据）被它天然覆盖。
    // 这里扫**源码**而不是渲染文本：layout.tsx 的 OG / Twitter 描述不上屏，渲染文本判据扫不到它。
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
    // 由来：关于页原「发展历程」写 2024 Q1~2025 五个时间段，而**仓史首个提交是 2026-05-06**
    // ⇒ 全部早于代码起点约两年、仓里找不到任何出处。官网立的是「每条事实都能找到出处」的人设，
    // 这类年份正是反例。
    //
    // 白名单 = **行级**，每条都写明"为什么这一行的时间不是我们的时间陈述"：
    //   ① 国标号与其文档路径（`GB/T 47746-2026` / `gb47746-2026-compliance.md`）
    //   ② 国标实施日期（讲的是标准本身何时生效，不是我们的里程碑）
    //   ③ 版权年份（`© 2026`，随当前年份走）
    // 🔴 未固化项（照实登记）：行级白名单是**粗放**口径 —— 同一行里若既有「实施」又藏一个编造年份，
    //    会漏判。要更严就得逐条给年份配「出处锚」，那是另一个量级的改动，本单不做。
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