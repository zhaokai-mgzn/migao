/**
 * 「企业基础设置 = 配置指挥台」的**域目录单一真值模块**（issue #6580；设计真值源 =
 * `docs/design/enterprise-settings-redesign.md`）。
 *
 * ## 它是什么
 *
 * 页面左栏那**四个区 · 十一个域**的**唯一**定义处：域的 key / 人话名 / 一句话简介 / 所属区 /
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
/**
 * 十一个域（**顺序即左栏顺序、也是依赖顺序**：先算钱 → 再干活 → 再省料 → 最后是这家店）。
 *
 * ⚠️ **v2（issue #6585）**：由 8 个域拆到 **11 个** —— 原来的 `processing-fee`（「加工项与加工费」，
 * 一个域里塞两件事）拆成 `processing-items` + `fee-combinations`；原来的 `craft-route`
 * （「工艺与路线」，一个域里塞四件事）拆成 `operation-prices` + `craft-route` + `cutting-height`。
 * 拆的依据 = **一件配置一件事**：域内不许再套一层导航（设计 §2 判死线第 3 条），
 * 而 v1 这几域里挂的功能体**各自自带 tab**（工序管理 / 算料配置 / 裁高配置、加工项 / 加工费组合）——
 * 左栏一套导航 + 域内又一套，正是用户说的「分不清该点哪个」。
 *
 * 🔴 旧的 `?domain=processing-fee` 仍可用（见 {@link LEGACY_DOMAIN_ALIASES}，落到
 * `processing-items`）—— 域 key 是**可分享的 URL 契约**，改域不许让旧链接落到空白。
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
    key: 'processing-items',
    label: '加工项与分类',
    zone: 'quote',
    summary: '这家提供哪些加工、它们怎么分类 —— 顾客下单时能选到的就是这里启用的',
    // 加工项 / 加工分类读面（`processingItemApi` / `processingCategoryApi`）
    requiredCode: 'production:view',
    // 主线今天没有「加工项」那一步（`config-readiness.ts` 头部「未实装」已具名登记）⇒ 不编读数、不显示徽标
    mainlineSteps: [],
  },
  {
    key: 'fee-combinations',
    label: '加工费组合',
    zone: 'quote',
    summary: '什么特征组合收什么价 —— 组合命中不到，那一行就收不到价',
    // 加工费组合 / 缺口读面（`productionApi.getFeeCombinations` / `getFeeGaps`）
    requiredCode: 'production:view',
    mainlineSteps: ['fee-combinations'],
  },
  {
    key: 'operation-prices',
    label: '工序与部位单价',
    zone: 'production',
    summary: '车间要做哪些活、每道活多少钱（给工人的计件单价）',
    // 工序库 / 工序-部位价目读面（`getOperationsCatalog` / `getOperationPositions`）
    requiredCode: 'production:view',
    mainlineSteps: ['operations'],
  },
  {
    key: 'craft-route',
    label: '工艺路线',
    zone: 'production',
    summary: '订单按哪条路线走 —— 没匹配到任何路线的订单走「默认路线」那条',
    // 工艺路线读面（`productionApi.getRoutings`）
    requiredCode: 'production:view',
    // 「工艺路线」与「默认路线」是**同一个列表**的两步判据（领先条 = 默认路线）⇒ 一个域承载两步
    mainlineSteps: ['routings', 'default-route'],
  },
  {
    key: 'cutting-height',
    label: '裁高配置',
    zone: 'production',
    summary: '裁剪高度怎么算 —— 成品高加上命中的增量项（定型 / 打孔这类）',
    // 裁高读面（`cuttingHeightApi`）
    requiredCode: 'production:view',
    mainlineSteps: [],
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

/**
 * 旧域 key → 现域 key（**URL 契约的兼容层**）。
 *
 * 为什么必须有：`?domain=` 是可分享 / 可收藏 / 可被通知与文档引用的地址 —— 拆域（#6585）把
 * `processing-fee` 拆成两个域之后，旧链接**不许落到空白**（那等于「点了一个链接看到空页」，
 * 比 404 更难排查）。这里只做**语义等价**的映射，不猜。
 */
export const LEGACY_DOMAIN_ALIASES: Readonly<Record<string, string>> = {
  // v1 的「加工项与加工费」（一个域两件事）⇒ 落到「加工项与分类」（另一半在「加工费组合」域）
  'processing-fee': 'processing-items',
}

/** 把 URL 里的 `?domain=` 解析成**现役**域（先查现役 key，再查兼容别名）；找不到 ⇒ `undefined`。 */
export function resolveDomainKey(key: string | null | undefined): string | undefined {
  if (!key) return undefined
  if (CONFIG_DOMAINS.some((d) => d.key === key)) return key
  return LEGACY_DOMAIN_ALIASES[key]
}

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
