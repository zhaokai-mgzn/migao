import {
  BadgeCheck,
  BarChart3,
  Bot,
  Building2,
  Calculator,
  Factory,
  Heart,
  Layers,
  Lightbulb,
  Lock,
  MessageSquare,
  PackageOpen,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from 'lucide-react'
import { AI_ROLES } from '@/config/ai-roles'

/** Hero 事实标签：每一条都能在代码或文档里找到出处，不写形容词 */
export const heroFacts = [
  '双 AI 分工 · 各守边界',
  '四端同源 · 数据一致',
  '布艺行业原生',
  '企业级隔离与审计',
]

export const agents = [
  {
    icon: Bot,
    name: '黄金策',
    role: AI_ROLES.mibao,
    brief: '面向经营侧：用自然语言查询经营数据，处理商品、订单、生产、库存与财务事项。',
    highlights: [
      '经营看板与每日简报：订单量、销售额、环比与待处理事项',
      '商品与价格：资料维护、批量改价、批量库存调整（可撤销）',
      '订单与交付：订单、物流、加工单进度与报工明细',
      '库存与成本：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资与报工明细',
      '财务与客户：资金流水、收支汇总、应收对账、客户档案与售后工单',
    ],
    boundary:
      '可写：改价、商品改名、批量改价与批量库存调整、通知标记已读、定时提醒；上下架与删除不做。改价须带改前价并经确认卡确认；AI 不创建订单与商品。',
  },
  {
    icon: MessageSquare,
    name: '米宝',
    role: AI_ROLES.xiaobu,
    brief: '面向顾客侧：7×24 小时接待咨询，覆盖算料报价、下单、物流查询与售后受理。',
    highlights: [
      '商品咨询：颜色、门幅与加工项，按店内已上架商品作答',
      '算料报价：按尺寸与工艺计算用料，输出估算报价',
      '下单：短信验证码校验，成交单价取商品库权威价',
      '订单与物流：订单进度、物流轨迹与收货地址',
      '售后受理：咨询与申请，工单恒为待商家审核',
      '知识卡片与图片识别：按已发布知识作答，支持图片解读',
    ],
    boundary:
      '不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；报价一律说明为估算。',
  },
]

/** 经营价值：四件最耗人的日常，交付后用户能看到的形态（不写百分比） */
export const valuePoints = [
  {
    icon: MessageSquare,
    title: '咨询有回应',
    description: '常规咨询由米宝即时接待；复杂诉求按规则交人工，沟通记录同步，无需重复描述。',
  },
  {
    icon: Calculator,
    title: '报价有依据',
    description: '算料公式、工艺参数与加工费组合可配置；未定价项明确提示，成交价取商品库权威价。',
  },
  {
    icon: Truck,
    title: '交付有进度',
    description: '订单生成加工单，裁剪、车位与后整逐道报工；进度、返工与报废在同一链路可查。',
  },
  {
    icon: BarChart3,
    title: '账目有明细',
    description: '入库批次、库存台账、计件工资、收支与应收逐笔记录，差异可追溯、可复核。',
  },
]

/** 三条产品能力线：顾客经营 / 经营决策 / 业务全链路 */
export const capabilityLines = [
  {
    icon: MessageSquare,
    title: '顾客经营',
    subtitle: '米宝 · 顾客侧 AI',
    description: '从规格咨询到下单、物流查询与售后受理，覆盖顾客会问到的完整链路。',
    points: ['商品与加工项咨询', '算料与估算报价', '下单、物流与售后'],
  },
  {
    icon: Bot,
    title: '经营决策',
    subtitle: '黄金策 · 经营侧 AI',
    description: '用自然语言查经营数据、跟订单与生产进度，处理商品、库存与财务事项。',
    points: ['看板与每日简报', '订单、生产与库存查询', '受控写入与确认卡'],
  },
  {
    icon: Layers,
    title: '业务全链路',
    subtitle: '共用业务底座',
    description: '商品、订单、生产、仓储与财务在同一数据上流转，四个终端不各自建账。',
    points: ['商品与价格本', '订单与加工单', '批次、计件与对账'],
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
    description: '顾客侧与经营侧独立配置，能做什么、不能做什么逐条标注，不让 AI 越界。',
  },
  {
    icon: PackageOpen,
    title: '数据同源',
    description: 'AI 的回答取自后台同一经营数据，顾客听到的与经营者看到的保持一致。',
  },
  {
    icon: ShieldCheck,
    title: '可审计的 AI',
    description: '写操作有边界与确认，关键动作留痕；价格、退款与赔偿不由模型决定。',
  },
]

/** 适用企业：收窄到真实现阶段的布艺 / 窗帘经营形态 */
export const enterpriseTypes = [
  { icon: Ruler, name: '窗帘定制商' },
  { icon: Factory, name: '布艺加工厂' },
  { icon: ShoppingBag, name: '批零一体企业' },
  { icon: Building2, name: '品牌与渠道商' },
]

/** 能力边界：首页「把 AI 能做什么、不能做什么写在明处」三条 */
export const principles = [
  {
    icon: Lightbulb,
    title: '数据之外不作答',
    description:
      'AI 只依据店内真实数据与已发布知识作答：不编造订单、物流与金额，不报库存数量，不展示未上架商品。',
  },
  {
    icon: Lock,
    title: '定价权归属商品库',
    description:
      '顾客侧成交单价取商品库权威价；经营侧改价须带出改前价并经确认卡确认。',
  },
  {
    icon: Heart,
    title: '敏感事项不由 AI 决定',
    description: '价格、折扣、退款金额、赔偿与法律诉求，AI 只解释规则与收集材料，不作决定。',
  },
]

/** 平台保障：四条可核实的企业级事实 */
export const guarantees = [
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
    icon: Layers,
    title: '岗位权限可控',
    description: '员工菜单与操作权限逐人可配，权限树与后台菜单同源。',
  },
  {
    icon: BarChart3,
    title: '操作全程可追溯',
    description: '关键写操作留有记录，AI 的受控写入同样进入审计链。',
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
