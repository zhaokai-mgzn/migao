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
 * - **「加工项」不是本主线的一步**：它的「活跃数」口径今天没有在别处落成判据
 *   （`GET /api/admin/processing-items` 是分页读面，启用 / 停用口径未定）⇒ 宁缺勿滥，
 *   等那个口径先在别处成立再进主线。主线今天到「加工费组合」为止（组合价从**订单侧缺口**反查，
 *   口径在服务端、`unpriced_combination_total`）。
 * - **孤儿工序**（库里有工序、没有任何价目行）：本模块的 {@link judgeOperationsStep} **支持**这一维，
 *   但跨页主线**取不到**它（要复刻 `routings` 页的逻辑名去重口径 = 第二份会漂的实现）⇒
 *   主线传 `null`（不参与判定），`routings` 页传真实数。**已知差异，具名登记**。
 */

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
    why: '没匹配到专属路线的订单走哪条（兜底终点）',
    impact: '没有默认路线 ⇒ 没有专属路线的订单**一单都派不出去**',
    href: '/production/routings',
    blocking: true,
  },
  {
    key: 'fee-combinations',
    label: '加工费组合',
    why: '一组选配特征 → 一个单价（元/米）',
    impact: '组合命中不到 ⇒ 该行**收不到价**（不是 ¥0.00，是根本没价可收）',
    href: '/production/processing-fees',
    blocking: true,
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
