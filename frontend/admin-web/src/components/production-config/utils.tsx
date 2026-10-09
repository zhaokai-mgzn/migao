/**
 * 工艺配置（工序 / 路线 / 算料 / 裁高）的**共享工具与展示常量**（issue #6585 P1）。
 *
 * ## 为什么有这个模块
 *
 * v2 把 `ProcessConfigBoard` 的内部 tab 拆成可独立挂载的面板
 * （`OperationPricePanel` / `RoutingsPanel` / `CuttingHeightPanel` / `CalcFormulaPanel`）。
 * 拆分要求「同一个公式不得被复制两份」⇒ 被多处用到的纯函数、展示常量与行视图类型收在这里**一份**，
 * 板子与四个面板都从这里 import（板子行为一字不变，只是定义处从文件内挪到模块外）。
 *
 * ## 纪律
 *
 * - 这里**只有**纯函数与展示常量：无状态、无请求、无副作用（`money` 的 `null ⇒ ¥0.00`
 *   陷阱、`pickConvergedCell` 与后端同尺的选行规则等，说明逐条随函数保留）。
 * - **不在这里判任何口径**：就绪度判据在 `@/lib/config-readiness`，护栏理由在
 *   `@/lib/production-guard-reasons`（本模块只搬运展示层共用的那几件东西）。
 */
import { Check, Pencil, X } from 'lucide-react'
import type { CatalogOperation, OperationPosition, ProductionSource, RouteRule } from '@/types'
import { cn } from '@/lib/utils'

/**
 * 金额展示（`¥` + 两位小数）。
 * ⚠️ `null` 会渲染成 `¥0.00` —— 即「未定价」被显示成「0 元」。**未定价的字段不得直接喂进来**：
 * 先判 `null`（如规则行的「未定价」分支），再调本函数。
 */
export const money = (v?: number | string | null) => `¥${Number(v ?? 0).toFixed(2)}`

/**
 * 逻辑工序名 —— **行键的唯一口径**（issue #4886）。
 *
 * ⚠️ 该值在接口里的字段名历史上叫 `operation`（后端 `ProductionRoutingReadService.positionView`
 * 逐字写的就是 `logical_name`）；配套后端可能改叫 `logical_name` ⇒ 这里做
 * `logical_name ?? operation` **兜底读取**，**两种命名都能渲染**（前端不猜、不发明第三份名字）。
 */
export const logicalNameOf = (cell: OperationPosition): string =>
  (cell as OperationPosition & { logical_name?: string | null }).logical_name ?? cell.operation

/**
 * 同一逻辑名多行时的**收敛选择**（规则逐字见 {@link convergeByLogicalName}）：
 * 按 `position` 字典序 → `id` 升序取首个 —— 与后端
 * `ProductionOperationQueryService#collapseToLogical` 的**同一把尺**，保证两边选出**同一行**
 * （选错行 = `PUT /operation-positions/{id}` 改的是另一个价）。
 *
 * 🔴 **两条旧平局规则已退场**（issue #4937 / #4951 去部位化彻底版，如实登记为**判据面缩小**）：
 * ① 「优先 `applicable === true`」—— 存活行的 `applicable` **恒 `TRUE`**、该字段已从
 *    `OperationPosition` 退场（写面收到它即 422）⇒ 判据的输入不复存在；
 * ② 「其中优先 `布帘`」—— `position` 现在**恒 `通用`**（部位维物理退场）⇒ 没有可优先的列。
 * 留下这一条**不是放宽**：它仍是**完全确定**的（字典序 + `id`，不依赖 DB 返回序），且 #4951 之后
 * 同一逻辑名本就只有一行（收敛是过渡期兜底，选行结果唯一）。
 */
export const pickConvergedCell = (group: OperationPosition[]): OperationPosition => {
  if (group.length === 1) return group[0]
  return [...group].sort(
    (a, b) =>
      (a.position ?? '').localeCompare(b.position ?? '') ||
      String(a.id ?? '').localeCompare(String(b.id ?? '')),
  )[0]
}

/**
 * **按逻辑工序名去重收敛为一行**（issue #4886 的**健壮性**要求）——
 * 这是「前后端可各自独立上线」的那道桥。
 *
 * 配套后端上线后 `GET /operation-positions` 每个逻辑工序名**只返回一行**；在它上线前
 * （或读面回退）接口**仍可能返回同一逻辑名的多行**。前端不得因此渲染出重复行
 * ⇒ 一律收敛成一行（规则见 {@link pickConvergedCell}）。
 * ⚠️ 收敛后**保留那一行的 `id`** —— 它就是 `PUT /operation-positions/{id}` 的寻址键。
 * 行序**保持服务端首次出现的顺序**（`Map` 插入序 = 服务端序，前端不重排）。
 */
export const convergeByLogicalName = (cells: OperationPosition[]): OperationPosition[] => {
  const byName = new Map<string, OperationPosition[]>()
  cells.forEach((cell) => {
    const name = logicalNameOf(cell)
    byName.set(name, [...(byName.get(name) ?? []), cell])
  })
  return [...byName.values()].map(pickConvergedCell)
}

/** 主线一步的展示视图（只读与草稿共用 —— {@link StepView}） */
export interface StepView {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  /** 工序库里有这条（有库口径元数据） */
  resolved: boolean
  /** 矩阵里没有它（停用/被删/名字是变体名）⇒ 保存必被后端拒，但页面要先让人看见 */
  missing: boolean
}

/** 抽屉里的**一道变体**（工艺项行的工序设置维护面） */
export interface VariantView {
  id: string
  group: string | null
  unit: string | null
  /** 工序库里的 provenance；查不到 ⇒ `null` ⇒ **不渲染徽标**（静默 = 未知） */
  source: ProductionSource | null
  /**
   * 本条目是**按逻辑名回退**认出来的（issue #4674 C）：它的价目行 `variant_operation_id`
   * **未指向**该工序（NULL）⇒ 读面给不出变体 id，而**后端判据**（`variantNameOf` 按逻辑名反查）
   * 认得出它 ⇒ 两把尺不一致。
   * ⇒ 前端**照样认**（与后端同一份口径、不静默空）但**显式提示**「这些价目行未关联到本工序」。
   */
  unlinked: boolean
  /**
   * **指向别处**的价目行（issue #4674 C 的形态②）：行自带的 `variant_operation_id` 与
   * 「按逻辑名认出来的那道工序」**不是同一个** ⇒ 这一行属于**别的**工序。
   * 这种行**只如实报出、不给写面**（对它 PUT/DELETE 就是改另一道工序）。
   */
  foreign?: boolean
}

/** 价目表里的**一行**（`cell=null` = 工序库里有、价目行没有 —— 与板子逐字同形） */
export interface MatrixRow {
  operation: string
  /**
   * 该行的价目行；`null` = **工序库里有、价目行没有**（issue #5875 的「无价目行」行）——
   * 这类行没有可写的 `id` ⇒ **不可定价**。
   * ⚠️ 别把它当「未定价」：`cellState(null)` 虽然也回 `unpriced`，但两者语义不同
   * （「未定价」= 有行、`unit_price` 为空；「无价目行」= 连行都没有 —— 同仓纪律「未定价 ≠ ¥0.00」）。
   */
  cell: OperationPosition | null
  cells: Map<string, OperationPosition>
  /** 无价目行时，元数据（分组 / 单位）只能从**工序库那一行**取（读面已把 `name` 归一为逻辑名） */
  library?: CatalogOperation | null
}

/**
 * 第一层「工序」的**车间分组**（issue #4677 = 设计 §4.1 元素②；**行业术语**，不是我们发明的词）。
 *
 * 取值来源 = 行尾元数据里的 `group`（已存在，`production_operations.group_name`），**不新造字段**；
 * 本表只做两件事：① 给出**行业正名**（设计 §1.2：《成品窗帘生产流程及工作规范》）——
 * `裁剪` ⇒ 裁剪（裁床）/ `车位` ⇒ 车位（缝制）/ `后道` ⇒ 后整（烫工及后整）；② 固定**折叠组的顺序**。
 *
 * ⚠️ 用**前缀匹配**认领（`裁剪*` 覆盖 `裁剪（裁床）` 这类已带括号的历史值，也覆盖将来
 * `裁剪组` 这类写法）；认不出的分组**照原样追加在后**（不丢组、不改名）—— 同 `metaText`
 * 「不许静默取第一个」的纪律。
 */
export const WORKSHOP_LABEL: Array<{ prefix: string; label: string }> = [
  { prefix: '裁剪', label: '裁剪（裁床）' },
  { prefix: '车位', label: '车位（缝制）' },
  { prefix: '后整', label: '后整（烫工及后整）' },
  { prefix: '后道', label: '后整（烫工及后整）' },
  { prefix: '质检', label: '质检' },
  { prefix: '其他', label: '其他' },
]

/** 分组名 → 行业正名（认不出 ⇒ 原样返回，**不发明**名字） */
export const workshopLabel = (group: string): string =>
  WORKSHOP_LABEL.find((w) => group.startsWith(w.prefix))?.label ?? group

/** 分组排序权重（认不出 ⇒ 排在最后，保持各自相对顺序） */
export const workshopRank = (group: string): number => {
  const i = WORKSHOP_LABEL.findIndex((w) => group.startsWith(w.prefix))
  return i < 0 ? WORKSHOP_LABEL.length : i
}

/**
 * 行尾元数据 = 该行各格变体元数据的**公共值**；各格不一致时**逐个列出**（用 ` / ` 分隔）——
 * **不许静默取第一个**（取第一个会让「这道工序在两个分组里」这种事静默消失）。
 * 全 `null`（查不到变体）⇒ 空数组 ⇒ 渲染 `—`（不发明元数据）。
 */
export const metaTextOf = (values: string[]) => (values.length > 0 ? values.join(' / ') : '—')

/** 该行元数据是否**各格不一致**（不一致时界面要如实标出，不许静默取第一个） */
export const metaInconsistentOf = (values: string[]) => values.length > 1

/** 输入框统一样式（板子与四个面板共用；改一处即多处一致） */
export const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/**
 * provenance 三态 → 徽标（#4361 冻结取值）。未知/缺省（老实例未升级）**不渲染任何徽标** ——
 * 静默 = 未知，**不得**显示成「实证」（同 route-source 口径）。
 * 「占位待确认」文案要让商家看懂：它说的是**单价是初始占位值，需确认**，而不是工序本身有问题。
 */
export const SOURCE_META: Record<ProductionSource, { label: string; className: string }> = {
  实证: { label: '实证', className: 'bg-emerald-50 text-emerald-700' },
  推算: { label: '推算', className: 'bg-neutral-100 text-neutral-500' },
  /* issue #5860：徽标**挂在工序名后面**，而它说的是**单价**的来源 ⇒ 必须带主语
     （改前 `初始价·待确认` 被商家读成「这道工序待确认」，用户原话「这里的文案让人看不明白」）。
     真值来源 = `production_operations.source`；`实证` / `推算` 两档对商家没有动作可做，保持原词。 */
  占位待确认: { label: '单价：初始价（待确认）', className: 'bg-amber-50 text-amber-700' },
}

/**
 * 触发维（V71 列注释的闭词表；`shaped` / `processing_item` 是表结构预留，无种子行）。
 *
 * `position`（**部位**，issue #4962 加回的第 4 档）—— 用户裁定「如果有一些工序只能布帘有或者
 * 纱帘有，可以在适用条件上设置」⇒ 规则级部位限定**重新参与渲染**（人话里显示 `部位 = <值>`）。
 */
export const TRIGGER_KIND_LABEL: Record<string, string> = {
  craft: '工艺',
  option: '特殊选项',
  shaped: '是否定型',
  processing_item: '加工项',
  position: '部位',
}

/**
 * 一条条件的**人话**（issue #4650 阶段 1）。
 *
 * 商家看到的不是「触发类型 / 动作 / 目标工序 / 插入锚点」，而是**这道工序在什么情况下做**；
 * 目标工序由**所在抽屉 / 所在规则行**表达 ⇒ 话里不重复工序名。
 * 🔴 **部位限定要说出来（issue #4962）**：任何带 `position` 的规则都要把这一维说进人话
 * （`trigger_kind === 'position'` 时 `trigger_value` 与 `position` 是同一把值 ⇒ 只说一遍）。
 */
export const conditionText = (rule: import('@/types').RouteRule) => {
  const kind = TRIGGER_KIND_LABEL[rule.trigger_kind ?? ''] ?? rule.trigger_kind ?? '—'
  const value = rule.trigger_value ?? '—'
  const positionClause = rule.position ? `${TRIGGER_KIND_LABEL.position} = ${rule.position}` : ''
  const triggerClause = rule.trigger_kind === 'position' ? '' : `${kind} = ${value}`
  const when = [positionClause, triggerClause].filter(Boolean).join('、') || `${kind} = ${value}`
  if (rule.action === 'remove') return `${when} 时不做`
  return rule.after_operation
    ? `${when} 时插入（在「${rule.after_operation}」之后）`
    : `${when} 时插入（追加到末尾）`
}

/**
 * 数量口径缺口的**读面文案**（issue #6117 / #6128）—— 逐字取自后端
 * `ProductionOperationQueryService.QTY_RULE_MISSING_HINT`（读面只给布尔 `qty_rule_missing`）。
 */
export const QTY_RULE_MISSING_HINT = '该工序不在算料目录内，派工应做数量将按 1 计'

/**
 * **读面标记**：这道工序不在算料目录内（`qty_rule_missing === true`）⇒ 派工应做数量走**兜底 1**。
 * 缺省（键缺失 / 非 `true`）⇒ **不渲染**：静默 = 未知，不得冒充已知。
 */
export function QtyFallbackBadge({ testId }: { testId: string }) {
  return (
    <span
      data-testid={testId}
      title={QTY_RULE_MISSING_HINT}
      className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700"
    >
      数量按 1 计
    </span>
  )
}

/** provenance 徽标；「占位待确认」是**可行动**引导：点它即进入该工序的改价入口 */
export function SourceBadge({
  source,
  testId,
  onConfirmPrice,
}: {
  source?: import('@/types').ProductionSource | null
  testId: string
  onConfirmPrice?: () => void
}) {
  const meta = source ? SOURCE_META[source] : undefined
  if (!meta) return null
  const className = cn('ml-2 rounded px-1.5 py-0.5 text-[11px]', meta.className)
  if (source === '占位待确认' && onConfirmPrice) {
    return (
      <button
        type="button"
        data-testid={testId}
        onClick={onConfirmPrice}
        title="初始价（占位值），点此改成实际单价 —— 调价只影响新报工，历史报工按当时价"
        className={cn(className, 'underline decoration-dotted hover:brightness-95')}
      >
        {meta.label}
      </button>
    )
  }
  return (
    <span data-testid={testId} className={className}>
      {meta.label}
    </span>
  )
}

/** 条件工序规则的「单价（元/套）」格（三态互斥；`option` + `null` ⇒「未定价」≠ `¥0.00`） */
export function RulePriceCell({
  rule,
  editing,
  draft,
  busy,
  reasons,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
}: {
  rule: RouteRule
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const isOption = rule.trigger_kind === 'option'
  const raw = rule.customer_unit_price
  const unpriced = raw === null || raw === undefined || raw === ''
  const state = !isOption ? 'na' : unpriced ? 'unpriced' : 'priced'
  const hasPrice = state === 'priced'
  return (
    <div
      className={cn('flex flex-col gap-0.5', state === 'unpriced' ? 'text-amber-600' : 'text-neutral-600')}
      data-testid={`route-rule-price-${rule.id}`}
      data-state={state}
      title={isOption ? '特殊选项按套收费（元/套）' : '只有特殊选项按套计价'}
    >
      {state === 'na' ? (
        '—'
      ) : editing ? (
        <span className="flex items-center gap-1.5">
          <input
            type="text"
            inputMode="decimal"
            aria-label={`${rule.trigger_value ?? ''} 单价（元/套）`}
            data-testid={`route-rule-price-input-${rule.id}`}
            value={draft}
            disabled={busy}
            onChange={(e) => onDraftChange(e.target.value)}
            className={cn(
              'h-8 w-24 rounded border bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/15',
              reasons.length > 0
                ? 'border-red-300 focus:border-red-400'
                : 'border-neutral-300 focus:border-primary-500',
            )}
          />
          <button
            type="button"
            aria-label="保存单价"
            data-testid={`route-rule-price-save-${rule.id}`}
            disabled={busy}
            onClick={onSave}
            className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            type="button"
            aria-label="取消"
            data-testid={`route-rule-price-cancel-${rule.id}`}
            disabled={busy}
            onClick={onCancel}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </span>
      ) : (
        <span className="flex items-center gap-1.5">
          <span>{unpriced ? '未定价' : money(raw)}</span>
          <button
            type="button"
            aria-label={`编辑 ${rule.trigger_value ?? ''} 单价（元/套）`}
            data-testid={`route-rule-price-edit-${rule.id}`}
            onClick={onStartEdit}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
      {editing && reasons.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-red-600" data-testid={`route-rule-price-reasons-${rule.id}`}>
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {editing && (
        <span className="mt-1 block text-[11px] text-neutral-400">
          {hasPrice ? '清空 = 改回未定价（≠ 0 元）' : '填 0 表示真 0 元；清空 = 未定价'}
        </span>
      )}
    </div>
  )
}
