import {
  BadgeCheck,
  BarChart3,
  Bot,
  Building2,
  Calculator,
  Factory,
  Headphones,
  Layers,
  MessageSquare,
  PackageOpen,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Truck,
  Users,
} from 'lucide-react'

/** Hero 能力标签：与下方分节一一对应，不写形容词 */
export const heroChips = [
  '智能接待',
  '算料报价',
  '订单生产',
  '库存批次',
  '计件对账',
  '经营决策',
]

export const heroFacts = [
  '双 AI 分工',
  '四端同源',
  '布艺行业原生',
  '企业级隔离与审计',
]

/** 四个经营场景 = 参考站的分节结构；每节配一张产品界面示意 */
export const featureBlocks = [
  {
    id: 'customer',
    kicker: '顾客经营 · 智能客服',
    title: '从顾客开口，到订单成交',
    cardTitle: '接待、算料与下单，走同一链路',
    lead: '咨询、算料、报价、下单与售后在同一链路上完成；智能客服按店内真实商品与价格作答。',
    tabs: ['智能接待', '算料报价', '下单转化'],
    tabDetails: [
      '按已上架商品回答颜色、门幅与加工项，不展示未上架商品。',
      '按尺寸与工艺计算用料，报价明确标注为估算。',
      '短信验证码校验后下单，成交单价取商品库权威价。',
    ],
    bullets: [
      '按已上架商品回答颜色、门幅与加工项，不展示未上架商品',
      '按尺寸与工艺计算用料，报价明确标注为估算',
      '短信验证码校验后下单，成交单价取商品库权威价',
      '售后工单恒为「待商家审核」，处理进度可查',
    ],
    visual: 'customer' as const,
  },
  {
    id: 'decision',
    kicker: '经营决策 · 黄金策',
    title: '问经营，不用等报表',
    cardTitle: '看板、简报与问答，读同源数据',
    lead: '看板、每日简报与自然语言问答读同源数据；商品、订单、生产、库存与财务都能追问到明细。',
    tabs: ['经营看板', '每日简报', '数据问答'],
    tabDetails: [
      '订单量、销售额、环比与待处理事项按日汇总。',
      '每日自动生成简报，异常事项可下钻到明细。',
      '自然语言追问，回答带数据依据。',
    ],
    bullets: [
      '订单量、销售额、环比与待处理事项按日汇总',
      '商品与价格、订单与交付、库存与成本按主题下钻',
      '生产与计件、资金流水与应收对账支持追问',
      '写操作有边界：改价须带改前价并经确认卡确认',
    ],
    visual: 'decision' as const,
  },
  {
    id: 'production',
    kicker: '生产与交付',
    title: '订单到交付，进度在同一链路',
    cardTitle: '加工单、报工与发货，进度可查',
    lead: '订单生成加工单，裁剪、车位与后整逐道报工；进度、返工与发货在同一处查看。',
    tabs: ['加工单', '工序报工', '发货'],
    tabDetails: [
      '订单生成加工单，工艺路线驱动裁剪、车位与后整。',
      '工人扫码报工，合格、返工与报废按件记录。',
      '发货单记录来源与实发数量，支持按真实尺寸补打。',
    ],
    bullets: [
      '工艺路线驱动裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）',
      '工人扫码报工，合格、返工与报废按件记录',
      '发货单记录来源与实发数量，支持按真实尺寸补打',
      '订单、加工单、报工与发货共用数据，不各自建账',
    ],
    visual: 'production' as const,
  },
  {
    id: 'inventory',
    kicker: '库存与对账',
    title: '批次、库存、计件与收支，逐笔可查',
    cardTitle: '批次、计件与对账，逐笔可查',
    lead: '入库过账生成批次，库存变动逐笔记录；计件工资与财务对账落到人、工序与期间。',
    tabs: ['批次库存', '计件工资', '财务对账'],
    tabDetails: [
      '入库过账生成批次，库存变动逐笔记录。',
      '按人、工序、部位与套汇总计件明细。',
      '资金流水、收支汇总与应收对账支持复核。',
    ],
    bullets: [
      '入库按批次与缸号记账，成本按移动加权平均核算',
      '库存台账记录入库、出库、盘点与余料变动',
      '计件工资按人、工序、部位与套下钻',
      '资金流水、收支汇总与应收对账支持复核',
    ],
    visual: 'inventory' as const,
  },
]

/** 为什么选择生意管家：四条优势，均可在产品里核对 */
export const advantages = [
  {
    icon: Ruler,
    title: '行业原生',
    description: '算料、SKU 矩阵、工序、批次与计件按布艺现场设计，不依赖通用模板。',
  },
  {
    icon: Bot,
    title: '双 AI 分工',
    description: '智能客服与黄金策独立配置，能做什么、不能做什么逐项标注，不让 AI 越界。',
  },
  {
    icon: PackageOpen,
    title: '数据同源',
    description: 'AI 的回答取自后台同源数据，顾客听到的与经营者看到的保持一致。',
  },
  {
    icon: ShieldCheck,
    title: '可审计的 AI',
    description: '写操作有边界与确认，关键动作留痕；价格、退款与赔偿不由模型决定。',
  },
]

/** 六格平台保障（参考站「全面服务支持」的版式，内容只写真实能力） */
export const supportItems = [
  {
    icon: BadgeCheck,
    title: '正规运营主体',
    description: '由杭州词元通达科技有限公司运营，合同与发票主体一致。',
  },
  {
    icon: ShieldCheck,
    title: '租户级数据隔离',
    description: '数据按企业隔离，租户身份取自登录凭证，跨企业访问一律拒绝。',
  },
  {
    icon: Users,
    title: '岗位权限可控',
    description: '员工菜单与操作权限逐人可配，权限树与后台菜单同源。',
  },
  {
    icon: Layers,
    title: '四端数据同源',
    description: '管理后台、微信客服、商家小程序与员工端 H5 共用数据底座。',
  },
  {
    icon: Headphones,
    title: '行业模板预置',
    description: '布艺行业通用知识模板与常用岗位开箱可用，再按企业话术补充。',
  },
  {
    icon: BarChart3,
    title: '操作全程可追溯',
    description: '关键写操作留有记录，AI 的受控写入同样进入审计链。',
  },
]

/** 适用企业：收窄到真实现阶段的布艺 / 窗帘经营形态 */
export const industries = [
  {
    icon: Ruler,
    name: '窗帘定制商',
    description: '规格多、询价频繁，需要统一的报价口径与可追溯的算料依据。',
  },
  {
    icon: Factory,
    name: '布艺加工厂',
    description: '订单、工序与计件管理复杂，需要透明的生产进度与报工明细。',
  },
  {
    icon: ShoppingBag,
    name: '批零一体企业',
    description: '销售、库存与财务需要同源，减少跨系统对账与重复录入。',
  },
]

/** 能力边界：首页「把 AI 能做什么、不能做什么写在明处」三条 */
export const principles = [
  {
    icon: Sparkles,
    title: '数据之外不作答',
    description:
      'AI 只依据店内真实数据与已发布知识作答：不编造订单、物流与金额，不报库存数量，不展示未上架商品。',
  },
  {
    icon: Calculator,
    title: '定价权归属商品库',
    description: '顾客侧成交单价取商品库权威价；经营侧改价须带出改前价并经确认卡确认。',
  },
  {
    icon: ShieldCheck,
    title: '敏感事项不由 AI 决定',
    description: '价格、折扣、退款金额、赔偿与法律诉求，AI 只解释规则与收集材料，不作决定。',
  },
]

/** 人机协同：GB/T 47746-2026 的四条机制设计参考（合规文案） */
export const gbPoints = [
  '自动识别复杂诉求转人工',
  '转人工规则可配置',
  '转人工即同步上下文',
  'AI 承诺边界明确',
]

/** 开通流程：内测期只走预约与人工确认 */
export const steps = [
  {
    title: '预约演示',
    description: '按您的业务场景演示算料、下单、生产、仓储与对账的完整链路。',
  },
  {
    title: '对齐流程',
    description: '确认开通模块、岗位权限与现有流程的衔接方式。',
  },
  {
    title: '开通上线',
    description: '完成账号与基础配置，员工即可登录使用。',
  },
]

/** 能力域图标（只用于官网排版；名称与摘要真值在 capability-map.ts） */
export const domainIcons = {
  'customer-service': Headphones,
  'orders-products': ShoppingBag,
  'production-center': Factory,
  quality: ShieldCheck,
  'inventory-center': PackageOpen,
  'finance-center': Calculator,
  'supply-chain': Truck,
  'org-center': Users,
} as const

/** 交付与开通（产品能力页用） */
export const deliveryItems = [
  {
    icon: Sparkles,
    title: '行业模板预置',
    description: '布艺行业通用知识模板已预置，开通后即可套用，再按企业话术补充。',
  },
  {
    icon: Users,
    title: '岗位权限预置可调',
    description: '常用岗位开箱可用，员工菜单权限逐人可调，权限树与后台菜单同源。',
  },
  {
    icon: Headphones,
    title: '按场景确认交付',
    description: '开通模块、数据衔接与培训方式按企业流程逐项确认；价格与合同另行沟通。',
  },
]

/** 四端（产品能力页用） */
export const terminals = [
  {
    icon: Building2,
    title: '管理后台',
    audience: '老板 / 运营 / 客服',
    description: '浏览器打开即用，经营数据与业务功能集中在后台。',
  },
  {
    icon: MessageSquare,
    title: '微信客服',
    audience: '终端消费者',
    description: '在微信里直接咨询智能客服，不加好友、不下载；也可嵌入商家自有小程序或公众号。',
  },
  {
    icon: Headphones,
    title: '商家小程序',
    audience: '老板 / 员工 / 工人',
    description: '移动端问黄金策、看数据、处理会话，并提供工人登录入口。',
  },
  {
    icon: Ruler,
    title: '员工端 H5',
    audience: '车间工人',
    description: '扫码即开，扫码报工、拍照入库与发货。',
  },
]
