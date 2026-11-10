import {
  BadgeCheck,
  BarChart3,
  Bot,
  Building2,
  Calculator,
  ClipboardList,
  Coins,
  Database,
  Factory,
  FileText,
  Headphones,
  Landmark,
  Layers,
  MessageSquare,
  PackageOpen,
  Rocket,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Target,
  Truck,
  Users,
  Zap,
} from 'lucide-react'
import { AI_ROLES } from '@/config/ai-roles'

/** Hero 事实标签：每一条都能在代码或文档里找到出处，不写形容词 */
const heroFacts = [
  'AI 自动甄别 · 分钟级开通',
  '租户级数据隔离',
  '四端协同 · 数据同源',
  '人机协同机制参考 GB/T 47746-2026 设计',
]

const agents = [
  {
    icon: Bot,
    name: '黄金策',
    role: AI_ROLES.mibao,
    brief: '面向经营侧：以自然语言问答交付商品、订单、生产、库存与财务信息，辅助日常经营决策。',
    highlights: [
      '经营洞察：订单量、销售额、环比与待处理事项，支持每日简报',
      '商品与价格：批量改价、批量库存调整（可撤销）、商品资料维护',
      '订单与交付：订单、物流、加工单进度与报工明细',
      '库存与成本：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资报表',
      '财务与客户：资金流水、收支汇总、应收对账、客户档案与售后工单',
    ],
    boundary:
      '可写的动作：改价、商品改名、批量改价与批量库存调整、通知标记已读、定时提醒；上下架与删除不做。改价须携带改前价并经确认卡二次确认；AI 不创建订单与商品。',
  },
  {
    icon: MessageSquare,
    name: '米宝',
    role: AI_ROLES.xiaobu,
    brief: '面向顾客侧：7×24 小时接待咨询，覆盖算料报价、下单、物流查询与售后受理。',
    highlights: [
      '商品咨询：颜色、门幅、加工项，按店内已上架商品作答',
      '算料报价：按尺寸与工艺计算用料，输出估算报价',
      '下单：短信验证码校验，成交单价取商品库权威价',
      '订单与物流：订单进度、物流轨迹、收货地址',
      '售后受理：售后咨询与申请，工单恒为待商家审核',
      '知识卡片与图片识别：按已发布知识作答，支持图片解读',
    ],
    boundary:
      '不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；报价一律说明为估算。',
  },
]

/** 中小企业的经营课题 → 平台应对（每一项都对应真实模块） */
const businessChallenges = [
  {
    icon: Ruler,
    title: '询价与算料依赖经验',
    description: '算料规则、工艺参数与加工费组合可配置；报价依据可追溯，未定价项明确提示。',
  },
  {
    icon: ClipboardList,
    title: '订单与生产各自记账',
    description: '订单生成加工单，工序进度、报工明细与交付状态在同一链路查看。',
  },
  {
    icon: PackageOpen,
    title: '库存与成本缺少台账',
    description: '入库过账生成批次，库存变动逐笔记录，成本按移动加权平均核算。',
  },
  {
    icon: Headphones,
    title: '服务响应依赖人工',
    description: '米宝 7×24 接待常规咨询；复杂诉求按规则转人工，上下文同步至坐席。',
  },
]

/** 平台四层：交互 / 智能 / 业务 / 数据与安全 */
const platformLayers = [
  {
    icon: Layers,
    name: '交互层',
    description: '管理后台、顾客小程序、商家小程序与员工端 H5，按角色提供入口与权限。',
  },
  {
    icon: Bot,
    name: '智能层',
    description: '米宝与黄金策理解业务意图，调用工具完成查询、分析与受控写入。',
  },
  {
    icon: Database,
    name: '业务层',
    description: '八个能力域覆盖客户服务、交易、生产、质量、仓储、财务、供应链与组织管理。',
  },
  {
    icon: ShieldCheck,
    name: '数据与安全层',
    description: '多租户隔离、行级安全、岗位权限与操作审计构成统一底座。',
  },
]

/** 订单全流程 —— 布艺行业纵深（每一步都有对应模块或接口） */
const orderJourney = [
  {
    step: '01',
    icon: Ruler,
    title: '询价与算料',
    description:
      '按尺寸、褶皱与工艺计算用料，输出估算报价；加工项与加工费组合单独定价，未定价项明确提示。',
  },
  {
    step: '02',
    icon: ShoppingBag,
    title: '下单',
    description:
      '规格覆盖颜色、售卖方式与门幅；短信验证码校验后下单，成交单价取商品库权威价，AI 不自行定价。',
  },
  {
    step: '03',
    icon: Factory,
    title: '生产',
    description:
      '订单生成加工单，工艺路线驱动裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）；工人扫码报工，进度实时可见。',
  },
  {
    step: '04',
    icon: PackageOpen,
    title: '入库',
    description:
      '入库单先建草稿，不动库存；过账后生成批次、增加库存，并按移动加权平均记录成本。',
  },
  {
    step: '05',
    icon: Truck,
    title: '发货',
    description:
      '发货单记录来源与实发数量，支持按真实尺寸 A4 补打；区分物流发货与无需物流。',
  },
  {
    step: '06',
    icon: Calculator,
    title: '售后与对账',
    description:
      '售后工单覆盖退货、换货、维修、退款、投诉与其他六类；财务提供资金流水、收支汇总与应收对账。',
  },
]

/** 经营价值：只写可核对、可追溯的形态，不写百分比 */
const valuePoints = [
  {
    icon: Calculator,
    title: '报价有依据',
    description: '算料公式、工艺参数与未定价项均有记录，报价过程可复核。',
  },
  {
    icon: Truck,
    title: '交付有进度',
    description: '订单、加工单与报工进度在同源链路可查，异常可定位。',
  },
  {
    icon: BarChart3,
    title: '库存有台账',
    description: '批次、缸号、成本与余料变动逐笔记录，差异可追溯。',
  },
  {
    icon: Coins,
    title: '计件有明细',
    description: '报工、返工与报废记录可核对；返工与报废不计件。',
  },
]

/** 适用企业：收窄到真实现阶段的布艺 / 窗帘经营形态 */
const enterpriseTypes = [
  {
    icon: Ruler,
    name: '窗帘定制商',
    description: '定制规格多，询价与算料频繁，需要统一的报价口径。',
  },
  {
    icon: Factory,
    name: '布艺加工厂',
    description: '订单、工序与计件管理复杂，需要透明的生产进度。',
  },
  {
    icon: ShoppingBag,
    name: '批零一体企业',
    description: '销售、库存与财务需要同源，减少跨系统对账。',
  },
  {
    icon: Building2,
    name: '品牌与渠道商',
    description: '多终端服务与统一数据，支撑渠道协同。',
  },
]

/** 产品原则（关于词元通达） */
const principles = [
  {
    icon: Target,
    title: '从现场出发',
    description: '先解决算料、工序、批次与计件等具体问题，再谈平台化。',
  },
  {
    icon: BarChart3,
    title: '以数据为准',
    description: 'AI 的回答与后台记录一致，经营数据同源。',
  },
  {
    icon: ShieldCheck,
    title: '把边界写明',
    description: 'AI 能做什么、不能做什么，在页面与产品中明确标注。',
  },
]

const platformGuarantees = [
  {
    icon: BadgeCheck,
    title: '智能准入审核',
    description:
      '入驻申请由 AI 自动审查：敏感信息与非法内容先经规则层过滤，再给出结论；通过后自动开通租户与管理员账号。',
  },
  {
    icon: ShieldCheck,
    title: '租户级数据隔离',
    description: '租户身份仅取自登录凭证，查询自动按租户过滤；跨租户访问一律返回 404。',
  },
  {
    icon: Landmark,
    title: '正规运营主体',
    description: '由杭州词元通达科技有限公司提供，保障产品与服务的长期稳定。',
  },
  {
    icon: ClipboardList,
    title: '操作全程可追溯',
    description:
      'AI 的工具调用与关键业务操作全程留有记录可查，身份取自登录账号，敏感信息脱敏保存。',
  },
  {
    icon: Users,
    title: '岗位权限可控',
    description:
      '管理员、客服、运营、销售、财务、商品管理员、知识编辑等岗位，菜单权限逐人可配。',
  },
  {
    icon: Layers,
    title: '四端数据同源',
    description: '管理后台、顾客小程序、商家小程序、员工端 H5 共用数据底座，不各自建账。',
  },
]

const steps = [
  {
    icon: FileText,
    step: '01',
    title: '提交申请',
    description: '填写企业信息并完成手机验证，全程约几分钟。',
  },
  {
    icon: Zap,
    step: '02',
    title: 'AI 智能甄别',
    description: 'AI 自动核验企业信息与合规性，秒级返回结果，无需等待人工审核。',
  },
  {
    icon: Rocket,
    step: '03',
    title: '即刻开通',
    description: '开通后即获得管理后台，米宝与黄金策同步上线。',
  },
]

const handoffSteps: Array<[string, string]> = [
  ['客户咨询', '顾客通过微信小程序或网页发起咨询'],
  ['米宝 AI 应答', '商品、订单、物流、售后实时应答'],
  ['自动转人工', '识别复杂诉求，或顾客主动要求转人工'],
  ['人工接续', '自动创建会话与工单，上下文同步，无需重复描述'],
  ['留言受理', '非营业时间留言，人工上线后接续处理'],
]

const gbPoints = [
  {
    icon: Sparkles,
    title: '自动识别复杂诉求转人工',
    description:
      '情绪化表达、多轮未解决、涉及赔偿或法律等超范围诉求，AI 自动建议或直接转接人工客服，由人工承接。',
  },
  {
    icon: Zap,
    title: '转人工规则可配置',
    description: '顾客可直接提出转人工，商家亦可自定义触发关键词，转接规则可随业务调整。',
  },
  {
    icon: MessageSquare,
    title: '转人工即同步上下文',
    description:
      '转人工后自动创建人工会话与工单并通知坐席，顾客与 AI 的沟通记录同步给人工客服，无需重复描述；原对话可直接继续沟通，非营业时间自动转为留言。',
  },
  {
    icon: ShieldCheck,
    title: 'AI 承诺边界明确',
    description:
      '涉及价格、折扣、退款金额等敏感事项，AI 只做规则解释与材料收集；申请类动作一律待人工客服或规范流程审核确认。',
  },
]

export {
  agents,
  businessChallenges,
  enterpriseTypes,
  gbPoints,
  handoffSteps,
  heroFacts,
  orderJourney,
  platformGuarantees,
  platformLayers,
  principles,
  steps,
  valuePoints,
}
