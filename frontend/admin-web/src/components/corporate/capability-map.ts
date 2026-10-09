import {
  BarChart3,
  Bell,
  BookOpen,
  Boxes,
  Calculator,
  ClipboardCheck,
  ClipboardList,
  Coins,
  Factory,
  Headphones,
  Layers,
  LifeBuoy,
  Newspaper,
  Package,
  PackageOpen,
  Recycle,
  Ruler,
  ScrollText,
  Settings,
  ShieldCheck,
  TrendingDown,
  Truck,
  UserCircle,
  Users,
  type LucideIcon,
} from 'lucide-react'

/**
 * 官网「能力地图」单一源（issue #6291）。
 *
 * 为什么单独成模块：首页与「产品与服务」页都要展示这套能力域，
 * 两处各写一份必然漂移（官网文案与现实脱节的病根）。
 *
 * 真值源 = `frontend/admin-web/src/config/menu.ts`（侧边栏单一源，6 组 18 项 + 2 个一级项 + 1 个尾部独立项）
 * ⇒ **本文件只做「分组展示」的排版，不新增、不改写任何菜单名**。
 * 改菜单请改 `config/menu.ts`，再回来同步这里的分组顺序。
 */

export interface CapabilityItem {
  /** 与 `config/menu.ts` 逐字一致的菜单名 */
  name: string
  /** 一句话说清它解决什么 —— 只写代码里能看到的形态，不写能力之外的承诺 */
  detail: string
  icon: LucideIcon
}

export interface CapabilityDomain {
  key: string
  /** 分组名，与 `config/menu.ts` 的 `menuGroups[].name` 逐字一致 */
  name: string
  summary: string
  items: CapabilityItem[]
}

export const capabilityDomains: CapabilityDomain[] = [
  {
    key: 'workspace',
    name: '工作台',
    summary: '经营全景入口：当日经营状况与待处理事项一屏可见。',
    items: [
      {
        name: '经营看板',
        detail:
          '订单量、销售额、环比与待处理事项一屏可见；无上期可比数据时显示「—」，不以 0 代替。',
        icon: BarChart3,
      },
      {
        name: '每日简报',
        detail: 'AI 每天生成经营要点，数字都经过系统核对；简报不含客户手机号等个人信息。',
        icon: Newspaper,
      },
    ],
  },
  {
    key: 'customer-service',
    name: '客户服务',
    summary: '顾客从咨询到售后的全流程管理。',
    items: [
      {
        name: '在线接待',
        detail: '人工坐席工作台：会话列表（待接待 / 接待中 / 已结束 / 已转接）+ 对话区 + 回复。',
        icon: Headphones,
      },
      {
        name: '客户列表',
        detail: '客户档案、来源渠道、VIP 等级与标签；手机号默认脱敏展示。',
        icon: UserCircle,
      },
      {
        name: '知识库',
        detail: '知识卡片有草稿 / 待审核 / 已发布 / 已归档四态，只有已发布的卡片会被 AI 检索到。',
        icon: BookOpen,
      },
      {
        name: '售后工单',
        detail: '退货 / 换货 / 维修 / 退款 / 投诉 / 其他六类，含优先级与超时工单下钻。',
        icon: LifeBuoy,
      },
    ],
  },
  {
    key: 'trade-center',
    name: '交易管理',
    summary: '订单与账目从下单记录到对账。',
    items: [
      {
        name: '订单列表',
        detail: '按订单号 / 收货人 / 下单时间 / 商品编码 / 是否含加工多维检索，支持备注、关闭与发货。',
        icon: ClipboardList,
      },
      {
        name: '财务对账',
        detail: '资金流水、收支汇总、应收对账三张账；默认本期为自然月。',
        icon: Calculator,
      },
    ],
  },
  {
    key: 'production-center',
    name: '生产管理',
    summary: '布艺行业纵深环节：加工单、工序、报工与计件。',
    items: [
      {
        name: '生产看板',
        detail: '加工单列表 + 每单工序进度 + 计件合计；加工单的唯一入口。',
        icon: ClipboardCheck,
      },
      {
        name: '智能派单',
        detail: '加急插队区 + 按物料分组成批派单（勾选 → 预览 → 一键派），超时未派告警。',
        icon: Factory,
      },
      {
        name: '计件工资',
        detail: '按人 / 工序 / 部位 / 套四档下钻；返工与报废不计件，系统会自动排除。',
        icon: Coins,
      },
    ],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    summary: '按布料的真实形态记账：批次、缸号与余料。',
    items: [
      {
        name: '入库单',
        detail:
          '草稿不动库存；过账自动生成批次号、增加库存并按移动加权平均记成本；期初建账支持 Excel 批量导入并逐行给出校验报告。',
        icon: PackageOpen,
      },
      {
        name: '发货单',
        detail: '全量发货单（单号 / 订单 / 客户 / 来源 / 发货人 / 实发），支持按真实尺寸 A4 补打。',
        icon: Truck,
      },
      {
        name: '余料台账',
        detail:
          '余料尺寸 / 面积 / 来源订单 / 批次 / 缸号 / 状态，含回收记账、报废留痕与小件优先匹配。',
        icon: Recycle,
      },
      {
        name: '省料看板',
        detail: '逐单比对公式米数与排料米数、按批次看余量分档、按单位产出看面料消耗。',
        icon: TrendingDown,
      },
      {
        name: '库存明细',
        detail:
          '逐笔列出 SKU 级库存变更（变动前 → 变动后），按时间 / 货号 / 原因 / 单据号 / 操作人成行，想查库存为什么变，顺着它往下看。',
        icon: ScrollText,
      },
    ],
  },
  {
    key: 'org-center',
    name: '组织管理',
    summary: '菜单权限与岗位配置。',
    items: [
      {
        name: '员工管理',
        detail: '岗位分配、菜单权限逐人勾选、员工登录账号与初始密码、工人档案。',
        icon: Users,
      },
      {
        name: '岗位权限',
        detail: '岗位（角色）与权限树维护；权限分组的树就是侧边栏菜单本身，两处不会漂移。',
        icon: ShieldCheck,
      },
    ],
  },
]

/** 不在 6 组内的独立入口（`config/menu.ts` 的 `standaloneTopItems` / `standaloneItems`） */
export const standaloneEntries: CapabilityItem[] = [
  {
    name: '商品管理',
    detail:
      '状态四态（出售中 / 已下架 / 审核中 / 草稿）、多规格 SKU、Excel 批量导入导出与商品分类树。',
    icon: Package,
  },
  {
    // 🔴 issue #6580：本席位原为「参数总览」—— 该一级项已撤掉（内容回到 `/settings`
    // 页内的配置域），改由**由组织管理组升为一级项**的「企业基础设置」占位（原名「企业基础信息」）。
    // ⚠️ 本文件属「官网源码」⇒ 不得写无出处的年份/时间陈述（`corporate-home.test.tsx` 会判红），
    // 故此处只引 issue 号、不写日期。
    // 官网必须与后台菜单同源：名称、数量、归属三处都随 `config/menu.ts` 走（漏讲/多讲 ⇒ 判据红）。
    name: '企业基础设置',
    detail:
      '把商家可配的东西集中到一处：企业名称与 Logo、AI 客服名称与欢迎语、工人端页面开关、通知设置，以及生产配置（加工项与分类、加工费组合定价、工序库与工艺路线）与算料口径；顶部按依赖顺序排出配置主线，直接说清还缺哪项、该去哪页配。',
    icon: Settings,
  },
  {
    name: '通知中心',
    detail: '站内信 / 短信 / 微信 / 邮件四渠道标签，未读已读与详情代办。',
    icon: Bell,
  },
]

/** 行业纵深：通用客服做不了、而布艺生意天天要面对的四件事（首页与产品页共用） */
export const industryDepth = [
  {
    icon: Ruler,
    title: '算料与报价',
    description:
      '按尺寸与工艺计算用料并给出估算价；成交单价严格取商品库权威价，不采用模型输出的价格。',
  },
  {
    icon: Layers,
    title: '多规格 SKU',
    description: '颜色 × 售卖方式 × 门幅的 SKU 矩阵，配加工项与加工费组合，规格复杂度由系统承载，无需客服记忆。',
  },
  {
    icon: Coins,
    title: '工序与计件',
    description:
      '裁床 / 车位 / 后整的工序库与工艺路线；报工记录合格、返工、报废，计件工资按人 / 工序 / 部位 / 套四档下钻。',
  },
  {
    icon: Recycle,
    title: '批次与余料',
    description:
      '入库按批次与缸号记账，余料台账记尺寸、来源订单与状态；省料看板比对公式米数与排料米数。',
  },
]

/** 菜单项总数（6 组 + 2 个独立入口），由上面的数据算出来，不写死 */
export const menuItemCount =
  capabilityDomains.reduce((sum, d) => sum + d.items.length, 0) + standaloneEntries.length
