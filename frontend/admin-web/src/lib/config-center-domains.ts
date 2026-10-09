/**
 * 「企业基础设置 = 配置指挥台」的**域目录单一真值模块**（issue #6580；设计真值源 =
 * `docs/design/enterprise-settings-redesign.md`）。
 *
 * ## 它是什么
 *
 * 页面左栏那**四个区 · 八个域**的**唯一**定义处：域的 key / 人话名 / 一句话简介 / 所属区 /
 * 打开本域所需的读码。页面**只渲染它**，不写死任何字面量（否则「区里少了哪个域」「徽标少了一个」
 * 这类缺陷没有任何东西会变红）。
 *
 * ## 分区的唯一依据（设计 §2）
 *
 * 按「**一笔单的钱与活怎么走**」排，不是按旧页面排：
 *
 * | 区 | 这一区回答的问题 | 域（按依赖顺序） |
 * |---|---|---|
 * | 一 · 报价与计费 | 这一单**收多少钱**？ | ① 算料口径 → ② 加工项与加工费 |
 * | 二 · 生产执行 | 这一单**在车间怎么走**？ | ③ 工艺与路线 |
 * | 三 · 余料与省料 | 裁下来的料**怎么不浪费**？ | ④ 余料尺寸 |
 * | 四 · 企业与账号 | 这家店**长什么样、谁能进来**？ | ⑤ 企业信息 / ⑥ AI 客服 / ⑦ 工人端页面 / ⑧ 通知设置 |
 *
 * ⚠️ **归属的裁定依据（两处真值源的取舍，具名登记）**：设计 §2 的分区表把「工艺与路线」的内容
 * （工序库 / 工序与部位单价 / 工艺路线 / 路线规则）写在「报价与计费」那一行的合并格里，**同时又**
 * 在「生产执行」区里回答「这一单在车间怎么走」—— 两处冲突。**取「生产执行」**，理由三条：
 * ① 域序列里的 `③ 工艺与路线` **恰好落在「生产执行」区的下方**（`③` 在一/二区交界处，图与序列都指向二区）；
 * ② 该域内容（工序库 / 路线）就是「车间怎么走」那件事 —— 域只回答一个问题，放二区才自洽；
 * ③ 放一区会让「二 · 生产执行」**成为空区**（页面与判据都要求四区各有域）。
 * ⇒ 四区**都不为空**：2 + 1 + 1 + 4 = 8，有测试钉住这一条。
 *
 * ## 🔴 本模块不判任何口径（同 `config-readiness.ts` 的纪律）
 *
 * 这里只有「有哪些域、它们叫什么、归哪一区、打开它要哪个码」。
 * **「还缺什么 / 下一步」的判据一律不在这里** —— 那是
 * `@/lib/config-readiness` 的 `judge*` 系列（有类级守卫钉住它是唯一真值源）。
 * {@link mainlineStepOfDomain} 只做**域 → 主线步骤键**的映射（让人知道本域该显示哪个徽标），
 * 它不产出任何三态。
 */

/**
 * 一区（页面左栏的第一层）。
 *
 * ⚠️ `label` **不含数字**：编号（一 / 二 / 三 / 四）由页面按 {@link CONFIG_ZONES} 的顺序渲染 ——
 * 把编号写进文案 = 造第二份会漂的口径（插一个区就得手改所有文案）。
 */
export interface ConfigZone {
  /** 稳定键（`data-testid="config-zone-<key>"`） */
  key: string
  /** 区名（人话） */
  label: string
  /** 这一区回答的问题（一句话） */
  question: string
}

/** 一个配置域（页面左栏的第二层 = 右栏面板的选取单位）。 */
export interface ConfigDomain {
  /** 稳定键（**逐字**用于 `?domain=` / `#domain-<key>` / `config-domain-<key>`） */
  key: string
  /** 域的人话名 */
  label: string
  /** 所属区（必须命中 {@link CONFIG_ZONES} 的某个 key；守卫钉住「不漏挂、不幽灵」） */
  zone: string
  /** 这个域管什么（一句话 —— 右栏标题下的「这是什么」） */
  summary: string
  /**
   * 打开本域所需的读码 —— 域级「看得见 ⇒ 打得开」（issue #6573 的既定口径）。
   *
   * 不持该码 ⇒ **不渲染、不进入左栏、也不发它的请求**（不是渲染出来再让人撞 403）。
   * 🔴 取值必须是**该域第一屏读端点的既有码**（不新造码 —— 新造码今天无人持有 = 域恒不可见，
   * #4203 同族坑）。
   */
  requiredCode: string
  /**
   * 本域对应**配置主线**里的哪些步（空数组 = 主线今天没有覆盖本域）。
   *
   * 用途只有一个：右栏标题旁的状态徽标**与主线同源**（设计 G4）—— 徽标文字直接取自
   * `ConfigReadinessBar` 的三态文案，判据取 `@/lib/config-readiness` 的 `worstState`
   *（**不在页面里另写一份判断**）。
   * · 一个域可能覆盖**多步**（「工艺与路线」一个域 = 工序库 + 工序与部位单价 + 工艺路线 + 默认路线
   *   四步中的三步）⇒ 徽标取**最差**的那一步（`worstState`），理由是域徽标回答的是
   *   「这一域还有没有事要做」；
   * · 空数组 ⇒ 本域**不显示**徽标（宁缺勿滥：编一个读数出来就是第二份会漂的口径）。
   */
  mainlineSteps: readonly string[]
}

/**
 * 四个区（**顺序即页面顺序**，也是「一笔单的钱与活」的因果链顺序）。
 */
export const CONFIG_ZONES: readonly ConfigZone[] = [
  { key: 'quote', label: '报价与计费', question: '这一单收多少钱' },
  { key: 'production', label: '生产执行', question: '这一单在车间怎么走' },
  { key: 'material', label: '余料与省料', question: '裁下来的料怎么不浪费' },
  { key: 'tenant', label: '企业与账号', question: '这家店长什么样、谁能进来' },
]

/** 域的稳定键（**逐字**；页面 URL 与测试都取它，不写字面量）。 */
export type ConfigDomainKey =
  | 'calc'
  | 'processing-fee'
  | 'craft-route'
  | 'remnant-sizes'
  | 'enterprise'
  | 'ai'
  | 'worker-pages'
  | 'notifications'

/**
 * 八个域（**顺序即左栏顺序、也是依赖顺序**：先算钱 → 再干活 → 再省料 → 最后是这家店）。
 */
export const CONFIG_DOMAINS: readonly ConfigDomain[] = [
  {
    key: 'calc',
    label: '算料口径',
    zone: 'quote',
    summary: '每片帘子用多少布、留多少余地 —— 每一项都直接改米数，也就是改钱',
    // 读面 `GET /api/admin/production/craft-calc-config` 的**方法级**码（与 `tenant-params.ts` 同源）
    requiredCode: 'production:view',
    mainlineSteps: ['calc'],
  },
  {
    key: 'processing-fee',
    label: '加工项与加工费',
    zone: 'quote',
    summary: '这家做哪些加工、什么特征组合收什么价 —— 组合命中不到，那一行就收不到价',
    // 加工项 / 加工分类 / 加工费组合读面（`/production/processing` 的节点码）
    requiredCode: 'production:view',
    // 🔴 主线把「加工费组合」算作**一步**，而本域还管「加工项与分类」——
    //    主线今天没有「加工项」那一步（`config-readiness.ts` 头部「未实装」已具名登记）⇒
    //    不编一个读数出来，本域**不显示**徽标。
    mainlineSteps: ['fee-combinations'],
  },
  {
    key: 'craft-route',
    label: '工艺与路线',
    zone: 'production',
    summary: '车间要做哪些活、每道活多少钱、订单按哪条路线走',
    // 工序库 / 价目 / 工艺路线读面（`/production/routings` 的节点码）
    requiredCode: 'production:view',
    mainlineSteps: ['operations', 'routings', 'default-route'],
  },
  {
    key: 'remnant-sizes',
    label: '余料尺寸',
    zone: 'material',
    summary: '做一个小件需要多大一块布 —— 填了才启用该小件的余料匹配',
    // 小件用料尺寸表读面（`RemnantController` 类级码）
    requiredCode: 'processing:manage',
    mainlineSteps: [],
  },
  {
    key: 'enterprise',
    label: '企业信息',
    zone: 'tenant',
    summary: '企业名称、Logo 与手机端入口',
    // `GET/PUT /api/admin/settings`（本页自身的既有码）
    requiredCode: 'system:manage',
    mainlineSteps: [],
  },
  {
    key: 'ai',
    label: 'AI 客服',
    zone: 'tenant',
    summary: '顾客在对话里看到的客服名称与开场文案',
    // `GET /api/admin/tenant/ai-config`
    requiredCode: 'system:manage',
    mainlineSteps: [],
  },
  {
    key: 'worker-pages',
    label: '工人端页面',
    zone: 'tenant',
    summary: '工人端有哪些页面与菜单对他们可见',
    requiredCode: 'system:manage',
    mainlineSteps: [],
  },
  {
    key: 'notifications',
    label: '通知设置',
    zone: 'tenant',
    summary: '订单、客服等重要事件的站内通知总开关',
    requiredCode: 'system:manage',
    mainlineSteps: [],
  },
]

/** 按 key 取域（找不到 ⇒ `undefined`；调用方负责兜底，**不在这里编一个默认域**）。 */
export function findDomain(key: string | null | undefined): ConfigDomain | undefined {
  return CONFIG_DOMAINS.find((d) => d.key === key)
}

/** 本域覆盖的主线步骤 key（空数组 = 主线没覆盖它 ⇒ 页面不显示徽标）。 */
export function mainlineStepsOfDomain(domain: ConfigDomain): readonly string[] {
  return domain.mainlineSteps
}

/** 某区里的域（顺序即 {@link CONFIG_DOMAINS} 的顺序）。 */
export function domainsOfZone(zoneKey: string): ConfigDomain[] {
  return CONFIG_DOMAINS.filter((d) => d.zone === zoneKey)
}

/**
 * 主线步骤 key → **承载它的域**（{@link ConfigDomain.mainlineSteps} 的反查）。
 *
 * 用途：主线「去配置」要做**页内跳转**（设计 G3）时，得知道该跳到哪个域。
 * 找不到 ⇒ `undefined`（主线有一步没被任何域承载 ⇒ 调用方按「跨页链接」兜底，**不编一个域**）。
 */
export function domainOfMainlineStep(stepKey: string): ConfigDomain | undefined {
  return CONFIG_DOMAINS.find((d) => d.mainlineSteps.includes(stepKey))
}
