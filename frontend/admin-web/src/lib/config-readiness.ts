/**
 * 配置主线（configuration mainline）—— **单一真值模块**（issue #6573）。
 *
 * ## 它是什么
 *
 * 「配置还缺什么、下一步去哪」的**唯一**定义处：跨页的**主线步骤目录**（{@link MAINLINE_STEPS}）
 * + 每步的**纯判据**（`judge*` 系列）。
 *
 * ## 为什么必须是**一个**模块，而不是各页各写一套
 *
 * 本仓有前车之鉴，且逐字记在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx`
 * 的就绪度注释里：**同一个概念两个载体** ⇒ 同一屏出现两个互相矛盾的数（「工序库 40 道 · 已完成」与
 * 「29 道工序 · 11 道没定价」并存，用户截图实证，issue #5858）。
 * ⇒ 判据只在这里写一次：`production/routings/page.tsx` 的**页内五步**与
 * `frontend/admin-web/src/components/settings/ConfigReadinessBar.tsx` 的**跨页主线**都调这里。
 *
 * ## 判据的纪律（三条，都可被判据检查）
 *
 * 1. 🔴 **本模块不读状态、不算钱**：输入是**已经从服务端读到的**事实（计数 / 状态串），
 *    输出是一个三态。任何取数、任何金额口径都不在这里。
 * 2. 🔴 **三态不可互画**：`todo` = **确定的没配**；`unknown` = **读不到**。
 *    读失败 ⇒ `unknown` —— **绝不**降级成 `todo`（把「没读到」画成「没配」）或
 *    `done`（谎报已配）。
 * 3. 🔴 **「取不到」不等于 0**：可选的第三方输入一律用 `null`（= 本次没取到、**不参与判定**）
 *    而不是 `0`（= 真的是零）—— 同族口径「未定价 ≠ ¥0.00」。
 *
 * ## 未实装（如实登记，不是「已覆盖」）
 *
 * **2026-11-04（issue #6579）两件旧账已销**（改前逐条登记为「未实装」，现在都实装了）：
 *
 * - **「加工项」进主线了**（{@link judgeProcessingItemsStep}）：启用 / 停用口径已定
 *   「有加工项 ∧ 至少一项启用」，事实由服务端聚合端点给（`total` / `active`）。
 * - **「孤儿工序」主线也能拿到数了**（{@link judgeOperationsStep} 的 `orphans` 不再是 `null`）：
 *   这份事实本来就住在服务端，改由 `GET /api/admin/config-readiness` 按**工艺配置页同一口径**
 *   算出后给数 ⇒ 前端不再需要复刻逻辑名去重（第二份会漂的实现）。
 *
 * 仍未实装（如实登记，不是「已覆盖」）：
 *
 * - 主线**只覆盖服务端这七步**；「企业信息 / AI 客服 / 通知设置」三个经营域没有主线步骤
 *   ⇒ 它们的域徽标不显示（宁缺勿滥，不编读数）。
 */

// 端点响应的**形状**只有一份定义（`types/config-readiness.ts`）—— 本模块只借用它的
// 「一步」类型来标定 `statesFromFacts` 的入参（`import type` ⇒ 运行时零依赖，不构成环）。
import type { ConfigReadinessStep } from '@/types/config-readiness'

/** 一步的三态（**只有三种**，没有第四种「不确定但画成 todo」的余地）。 */
export type ReadinessState = 'done' | 'todo' | 'unknown'

/** 主线的一步。 */
export interface MainlineStep {
  /** 稳定键（测试与 `data-testid` 用；**不随文案变**） */
  key: string
  /** 步名（人话） */
  label: string
  /** 这一步在配什么（一句） */
  why: string
  /** 不配会怎样 —— **阻断性**的必须写清后果，不要写「建议配置」 */
  impact: string
  /** 可点的去处（深链，能带 tab / 锚点就带） */
  href: string
  /** 没配会不会**挡住业务**（阻断 = 订单 / 派单 / 收款走不通） */
  blocking: boolean
}

/**
 * 配置主线（**依赖顺序 = 渲染顺序**，见 `frontend/admin-web/src/lib/config-readiness.ts` 的用户裁定）。
 *
 * 顺序不是审美：`加工项` 是 `加工费组合` 的输入（组合的 `items[]` 取自加工项目录），
 * 而组合命中不到 ⇒ **该行加工费收不到价**。把「用结果的人」排在「准备输入的人」前面，
 * 就是「没有一条清晰的路径」的成因。
 */
export const MAINLINE_STEPS: readonly MainlineStep[] = [
  {
    key: 'operations',
    label: '工序与单价',
    why: '车间要做哪些活、每道活给工人多少钱',
    impact: '缺工序或没定价 ⇒ 报工算不出工资（未定价按未定价处理 = 工人白干），进度也推不动',
    href: '/production/routings',
    blocking: true,
  },
  {
    key: 'routings',
    label: '工艺路线',
    why: '订单按哪条主线走（两条基础路线必须齐）',
    impact: '缺基础路线 ⇒ 那一类帘型的订单一单都生成不了加工单',
    href: '/production/routings',
    blocking: true,
  },
  {
    key: 'default-route',
    label: '默认路线',
    why: '没有专属路线的订单，按哪条路线生产',
    impact: '没有默认路线 ⇒ 没有专属路线的订单**一单都派不出去**',
    href: '/production/routings',
    blocking: true,
  },
  // 🔴 issue #6579：接上「加工项」这一步 —— 它是「加工费组合」的**输入**（组合的 items[] 取自
  // 加工项目录），故排在组合**之前**（本模块头的依赖顺序纪律）。
  {
    key: 'processing-items',
    label: '加工项',
    why: '顾客能选的那些加工（打孔 / 拼接 / 花边 …），以及每一项怎么收费',
    impact: '加工项全停用 ⇒ 订单里选不中它们，加工费组合也就命中不到（该行收不到价）',
    href: '/settings?domain=processing-items',
    blocking: false,
  },
  {
    key: 'fee-combinations',
    label: '加工费组合',
    why: '一组选配特征 → 一个单价（元/米）',
    impact: '组合命中不到 ⇒ 该行**收不到价**（不是 ¥0.00，是根本没价可收）',
    href: '/production/processing-fees',
    blocking: true,
  },
  // 🔴 issue #6579：接上「余料尺寸」这一步（**跨码步骤**）—— 读面码是 `processing:manage`
  // （余料尺寸表读端点所属的码）。不持该码的调用方拿到的服务端载荷里**整个没有这一步**
  // ⇒ 这里也就不会给它画一行（「不持码的域不渲染也不请求」的同口径，issue #6573）。
  {
    key: 'remnant-sizes',
    label: '余料尺寸',
    why: '做一个小件（抱枕 / 搭巾 …）需要多大一块布',
    impact: '不填 ⇒ 这些小的余料不会产生匹配建议（余料照常登记，只是不会被推荐着用）',
    href: '/settings?domain=remnant-sizes',
    blocking: false,
  },
  {
    key: 'calc',
    label: '算料配置',
    why: '用布量公式与余量口径 —— 每一项都直接改米数 = 改钱',
    impact: '没保存过 ⇒ 全程用引擎默认值（不算错，但你以为配过）',
    href: '/settings/params',
    blocking: false,
  },
]

/**
 * 第 ① 步「工序与单价」的判据。
 *
 * @param input.readFailed 两个读面（工序库 / 价目表）是否**任一读失败** ⇒ `unknown`（不谎报）
 * @param input.total 表里（价目行 ∪ 无价目行的库行）的**逻辑工序数**
 * @param input.unpriced 未定价数（`unit_price = null`）
 * @param input.orphans 孤儿工序数（库里有、没有任何价目行）；**`null` = 本次未取到 ⇒ 不参与判定**
 */
export function judgeOperationsStep(input: {
  readFailed: boolean
  total: number
  unpriced: number
  orphans: number | null
}): ReadinessState {
  if (input.readFailed) return 'unknown'
  if (input.total === 0) return 'todo'
  if (input.unpriced > 0) return 'todo'
  if (input.orphans !== null && input.orphans > 0) return 'todo'
  return 'done'
}

/**
 * 两条**基础路线**（issue #4677 的口径）—— 判据是「**缺哪条**」，不是数条数
 * （数条数会把「窗帘路线 + 一条商家自建路线」判成齐，是用户实测踩到的形态）。
 * 🔴 定义只在**这里**：`production/routings/page.tsx` 与跨页主线都取它。
 */
export const BASE_ROUTE_NAMES = ['窗帘工序路线（默认）', '布料工序路线'] as const

/** 从**已有的**路线名清单里算出缺哪几条基础路线（找不到 ⇒ 原样保留该名字）。 */
export function missingBaseRoutesOf(routeNames: readonly string[]): string[] {
  return BASE_ROUTE_NAMES.filter((n) => !routeNames.includes(n))
}

/** 第 ② 步「工艺路线」：两条基础路线齐 ∧ 没有空壳路线。`missing` 传**缺的那几条的名字**。 */
export function judgeBaseRoutesStep(missing: readonly string[], emptyShells = 0): ReadinessState {
  return missing.length === 0 && emptyShells === 0 ? 'done' : 'todo'
}

/** 第 ③ 步「默认路线」：**恰好一条**才算完成（0 条 = 派不出去；多条 = 兜底终点不确定）。 */
export function judgeDefaultRouteStep(defaultCount: number): ReadinessState {
  return defaultCount === 1 ? 'done' : 'todo'
}

/**
 * 第 ④ 步「加工费组合」：**有组合** ∧ **没有未定价组合**（订单里出现过、库里没价）。
 * `null` = 对应读面没取到 ⇒ `unknown`。
 *
 * ⚠️ **未定价组合的判定在服务端**（`GET /api/admin/production/processing-fee-gaps` 的
 * `unpriced_combination_total`）—— 前端**不重算**组合命中口径（那会变成第二份会漂的口径）。
 */
export function judgeFeeCombinationsStep(
  comboCount: number | null,
  gapCount: number | null,
): ReadinessState {
  if (comboCount === null || gapCount === null) return 'unknown'
  if (comboCount === 0) return 'todo'
  return gapCount > 0 ? 'todo' : 'done'
}

/**
 * 第 ⑤ 步「算料配置」：`source === 'stored'` ⇒ done；`'default'` ⇒ todo；
 * **其余一切（含 `undefined` / `'unavailable'`）⇒ unknown**（读不到就说读不到）。
 */
export function judgeConfigSourceStep(source: string | null | undefined): ReadinessState {
  if (source === 'stored') return 'done'
  if (source === 'default') return 'todo'
  return 'unknown'
}

/**
 * 「加工项」这一步的判据（issue #6579 接上主线）。
 *
 * **有加工项 ∧ 至少一项启用** 才算完成：全停用 ⇒ 订单里选不中任何加工项，
 * 下游「加工费组合」也就命中不到（组合的 `items[]` 取自加工项目录）。
 *
 * @param input.total 加工项目录总数
 * @param input.active 其中**启用**的条数
 */
export function judgeProcessingItemsStep(input: { total: number; active: number }): ReadinessState {
  if (input.total === 0) return 'todo'
  return input.active === 0 ? 'todo' : 'done'
}

/**
 * 「余料尺寸」这一步的判据（issue #6579 接上主线；**跨码**：读面码 `processing:manage`）。
 *
 * 配了任意一条小件用料尺寸 ⇒ 该小件的余料匹配才启用；**一条都没配** ⇒ 不产生匹配建议
 * （余料照常登记，只是不会被推荐着用）⇒ `todo`。
 *
 * @param input.configured 服务端读面的 `configured`（= 本租户配过没有）
 * @param input.items 配了几条
 */
export function judgeRemnantSizesStep(input: { configured: boolean; items: number }): ReadinessState {
  if (!input.configured) return 'todo'
  return input.items > 0 ? 'done' : 'todo'
}

/**
 * 把**服务端事实**翻译成逐步骤三态（issue #6579）—— 主线只发**一个**请求的依据。
 *
 * ## 三条纪律（都可被判据检查）
 *
 * 1. 🔴 **只做翻译，不做取数**：输入是 `GET /api/admin/config-readiness` 的
 *    `data.steps`（事实），输出是三态；判定一律调本模块的 `judge*`，**不在这里另写口径**。
 * 2. 🔴 **`facts` 缺键 ⇒ `unknown`**（读不到），**不是** `todo`（没配）。服务端取数失败时
 *    给的就是空 `facts` —— 把它读成「没配置」就是谎报（同族口径：「未定价 ≠ ¥0.00」）。
 * 3. 🔴 **载荷里整个缺席的步骤 ⇒ 不产出键**：跨码步骤（`remnant-sizes`）在不持该码时
 *    服务端**不发**这一步 ⇒ 它连「读不到」都不是（是「与你无关」），渲染面据此整行不画。
 *
 * @param steps 端点返回的 `steps`（`null` / `undefined` = 整个请求没拿到 ⇒ 返回空对象，
 *              渲染面会按「全部读不到」处理）
 */
export function statesFromFacts(
  steps: Record<string, ConfigReadinessStep> | null | undefined,
): Record<string, ReadinessState> {
  const out: Record<string, ReadinessState> = {}
  // 整份载荷都没拿到（请求失败）⇒ **一条结论都不产出**（渲染面按「全部读不到」处理）。
  // 这是有意的：产出六个 `unknown` 会让「没有事实」与「事实缺键」在调用方看起来一样。
  if (!steps) return out
  const factsOf = (key: string): Record<string, unknown> | null => {
    const step = steps?.[key]
    const facts = step?.facts
    return facts && typeof facts === 'object' ? facts : null
  }
  const numOf = (facts: Record<string, unknown> | null, key: string): number | null => {
    const value = facts?.[key]
    return typeof value === 'number' && Number.isFinite(value) ? value : null
  }

  const operations = factsOf('operations')
  const opsTotal = numOf(operations, 'total')
  const opsUnpriced = numOf(operations, 'unpriced')
  const opsOrphans = numOf(operations, 'orphans')
  out.operations = judgeOperationsStep({
    readFailed: opsTotal === null || opsUnpriced === null || opsOrphans === null,
    total: opsTotal === null ? 0 : opsTotal,
    unpriced: opsUnpriced === null ? 0 : opsUnpriced,
    orphans: opsOrphans,
  })

  const routings = factsOf('routings')
  const missing = routings?.['missing_base_routes']
  out.routings = Array.isArray(missing)
    ? judgeBaseRoutesStep(missing.map((name) => String(name)))
    : 'unknown'

  const defaultRoute = factsOf('default-route')
  const defaultCount = numOf(defaultRoute, 'count')
  out['default-route'] = defaultCount === null ? 'unknown' : judgeDefaultRouteStep(defaultCount)

  const processingItems = factsOf('processing-items')
  const itemsTotal = numOf(processingItems, 'total')
  const itemsActive = numOf(processingItems, 'active')
  out['processing-items'] =
    itemsTotal === null || itemsActive === null
      ? 'unknown'
      : judgeProcessingItemsStep({ total: itemsTotal, active: itemsActive })

  const fees = factsOf('fee-combinations')
  out['fee-combinations'] = judgeFeeCombinationsStep(
    numOf(fees, 'combinations'),
    numOf(fees, 'gaps'),
  )

  const calc = factsOf('calc')
  const source = calc?.['source']
  out.calc = judgeConfigSourceStep(typeof source === 'string' ? source : null)

  // 跨码步骤：**载荷里有这一步**才产出键（不持码时它整个缺席 —— 不是「读不到」）
  if (Object.prototype.hasOwnProperty.call(steps, 'remnant-sizes')) {
    const remnant = factsOf('remnant-sizes')
    const configured = remnant?.['configured']
    const items = numOf(remnant, 'items')
    out['remnant-sizes'] =
      typeof configured === 'boolean' && items !== null
        ? judgeRemnantSizesStep({ configured, items })
        : 'unknown'
  }

  return out
}

/** 主线的汇总读数（**全部现取**，不缓存、不留痕）。 */
export interface ReadinessSummary {
  done: number
  todo: number
  unknown: number
  total: number
  /** 第一个**没完成**的步骤键（`todo` 优先于 `unknown`）；全完成 ⇒ `null` */
  nextKey: string | null
  /** 阻断性且没完成的有几步（摘要在有阻断项时用更强的措辞） */
  blockingLeft: number
}

/**
 * 汇总（纯函数）。
 *
 * `nextKey` 的选法：**先 `todo` 再 `unknown`** —— 确定的缺口比「没读到」更该先处理；
 * 两者都没有才算全完成。
 */
export function summarizeReadiness(
  entries: readonly { key: string; state: ReadinessState; blocking: boolean }[],
): ReadinessSummary {
  const done = entries.filter((e) => e.state === 'done').length
  const todo = entries.filter((e) => e.state === 'todo').length
  const unknown = entries.filter((e) => e.state === 'unknown').length
  const next =
    entries.find((e) => e.state === 'todo') ?? entries.find((e) => e.state === 'unknown') ?? null
  return {
    done,
    todo,
    unknown,
    total: entries.length,
    nextKey: next ? next.key : null,
    blockingLeft: entries.filter((e) => e.blocking && e.state !== 'done').length,
  }
}

/**
 * 常驻面摘要的**一句话**（`migao-dev-flow` §31 P1：常驻面**一行**，不随缺项条数增长）。
 *
 * 语调按 §31 P4：只陈述**事实 + 该做什么**，不责备、不堆惊叹号。
 */
export function readinessHeadline(
  summary: ReadinessSummary,
  nextLabel: string | null,
): string {
  if (summary.nextKey === null) return `配置已完成 ${summary.done}/${summary.total}`
  const gap =
    summary.todo > 0
      ? `${summary.todo} 项未配置`
      : `${summary.unknown} 项读不到（刷新可重试）`
  return `配置完成 ${summary.done}/${summary.total} · ${gap} · 下一步「${nextLabel ?? ''}」`
}

/**
 * 一批步骤状态的**最差**取值（`todo` > `unknown` > `done`）—— 用于「**一个配置域覆盖多步**」时
 * 那个域的徽标（设计真值源 `docs/design/enterprise-settings-redesign.md` 的 G4：徽标与主线**同源**）。
 *
 * 为什么放这里而不是页面里：三态的任何取舍都属于「口径」，本模块是它的**唯一**家
 *（类级守卫 `tests/unit_ci_workflows/test_config_readiness_single_source.py` 钉住）。
 * 为什么「最差」而不是「最好」：域徽标要回答的是「**这个域还有没有事要做**」——
 * 三步里只要一步没配好，这一域就不算配好；报「已配置」会让商家漏掉那一步。
 *
 * 空数组（或全是 `undefined`）⇒ `null`（**不编读数**：主线没覆盖它，那就不显示徽标）。
 */
export function worstState(of: ReadonlyArray<ReadinessState | undefined>): ReadinessState | null {
  const present = of.filter((s): s is ReadinessState => Boolean(s))
  if (!present.length) return null
  const rank: Record<ReadinessState, number> = { todo: 0, unknown: 1, done: 2 }
  return present.reduce((worst, cur) => (rank[cur] < rank[worst] ? cur : worst))
}
