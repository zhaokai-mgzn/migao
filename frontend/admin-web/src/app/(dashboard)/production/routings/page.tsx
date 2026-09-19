'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  RefreshCw,
  Star,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import { productionApi } from '@/lib/api'
import { routingAdminGuardReasons, routingGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type {
  CatalogOperation,
  OperationPosition,
  OperationsCatalog,
  ProductionScope,
  ProductionSeedTemplate,
  ProductionSource,
  RouteRule,
  Routing,
  RoutingsResponse,
} from '@/types'

/**
 * 工艺配置 /production/routings（issue #4416 合并单页；issue #4433 = 母单 #4423 的 **P3** 适配新模型）
 *
 * ## 新模型下这一页回答两个问题（**一屏一件事**，不做功能平铺）
 *
 * | tab | 它回答的问题 | 主区 | 次区（折叠） |
 * |---|---|---|---|
 * | **工艺项** | 「每道工序在**哪个部位**做、各自**多少钱**？」 | 部位价目矩阵（28 逻辑工序 × 3 部位 = 84 格） | 工序库明细（分组/单位/作用域/必完/改单价） |
 * | **工艺路线** | 「订单按哪条主线走、什么时候插/删工序？」 | 具名路线（默认徽标 + 适用帘种 + 主线 + 改名/设默认/删除） | 条件工序规则（26 条） |
 *
 * 为什么两个 tab 各自再分「主区 / 折叠次区」：tab 只是第一层拆分；把 84 格矩阵与 35 行工序库
 * 依次堆进一屏仍然是**功能平铺**（用户 2026-09-19 总要求：「别把功能直接平铺到一个页面上」）。
 * 主区回答本 tab 的问题，次区是同一件事的**明细/维护面** ⇒ 折叠（用户原话：若某 tab 内部仍显拥挤
 * ⇒ 继续拆（抽屉 / 子页 / **折叠区**），而不是平铺）。
 *
 * ## 与旧形态的三处关键差异（P2b #4459 / P2c #4500 之后）
 *
 * 1. **路线 = 一条具名主线**（`{id, name, is_default, positions, mainline}`），不再是
 *    「部位 × 工艺」展开快照 ⇒ 列表显示**总名**+默认徽标+适用帘种，**不再**出现 `部位 × 工艺` 标题；
 *    改名**只改 `name`**（不给 `mainline` 就不动序列 —— 改一个名字不该顺带重写计件工资的输入）。
 * 2. **部位价目矩阵的行键是逻辑工序名**（`精裁` / `三边`），**不是** `production_operations.name`
 *    （那边仍是旧名 `精裁-布` / `布三边`）。两者之间**没有**暴露给前端的映射 ⇒ 前端**不猜**：
 *    矩阵按矩阵自己的键渲染，主线的「工序是否存在」按「工序库 ∪ 矩阵」两侧并集判定
 *    （只按工序库判会让每条种子路线都误报「工序库中不存在」）。
 * 3. **顺序口径**：`operation-positions` 按 `(operation, position)`、`route-rules` 按 `(priority, id)`
 *    —— **服务端已排好**，前端**不重排**（重排会与服务端口径分叉，同一张单两次生成会得到不同序列）。
 *
 * ## 护栏（后端仍是唯一权威；前端只把「保存失败」提前成「看得见」）
 *
 * - **删默认 ⇒ 拦**（默认路线是兜底终点，删了没有专属路线的订单一张加工单也生成不了）；
 * - **删最后一条 ⇒ 拦**（同因）；两条同时成立时**两条理由都给**（后端也一次报全）；
 * - **设为默认**只对非默认行开放（`is_default:false` 后端 422 ⇒ 前端**永不**提交 false）；
 * - 危险操作（删除 / 设为默认）**二次确认**；护栏理由**就地逐条**展示（复用 `lib/production-guard-reasons.ts`）；
 * - 商家面**不得**出现内部机制名（issue #4453：「信号映射」是研发内部机制）⇒ 后端理由过
 *   `merchantWording` 只换词、不删理由。
 *
 * ## 契约（冻结，**不得自行发明端点/字段名**）
 *   GET    /api/admin/production/routings                 POST /routings   body {name, mainline?, positions?, is_default?}
 *   PUT    /api/admin/production/routings/{id}            DELETE /routings/{id}      （部分更新 {name?, is_default?, mainline?, positions?, status?}）
 *   GET    /api/admin/production/operation-positions      GET  /route-rules          （#4500 两个只读面；写面留 v1b）
 *   GET    /api/admin/production/operations-catalog       POST /production/operations
 *   PUT    /api/admin/production/operations/{id}          （改单价 / 必完 / 作用域）
 *   GET|POST /api/admin/production/seed-templates[/{id}/apply]
 *   —— 写端点权限 processing:manage（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线；
 * 领域模型与裁定：docs/design/position-instance-routing-model.md（R-c 作用域 / R-f 解绑加工项）。
 */

const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

/**
 * 部位（帘种）**闭词表** —— 与 V71 列注释的取值域同口径（`production_operation_positions.position`）。
 * 用途 = 矩阵列序 + 新建路线的适用帘种勾选（矩阵为空时仍要有列/选项）；矩阵里出现的**未知部位**
 * 追加在后面（不丢数据、不改服务端口径）。
 */
const POSITION_DOMAIN = ['布帘', '纱帘', '帘头']

const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/**
 * provenance 三态 → 徽标（#4361 冻结取值）。未知/缺省（老实例未升级）**不渲染任何徽标** ——
 * 静默 = 未知，**不得**显示成「实证」（同 route-source 口径）。
 * 「占位待确认」文案要让商家看懂：它说的是**单价是初始占位值，需确认**，而不是工序本身有问题。
 */
const SOURCE_META: Record<ProductionSource, { label: string; className: string }> = {
  实证: { label: '实证', className: 'bg-emerald-50 text-emerald-700' },
  推算: { label: '推算', className: 'bg-neutral-100 text-neutral-500' },
  占位待确认: { label: '初始价·待确认', className: 'bg-amber-50 text-amber-700' },
}

/**
 * 工序作用域两档（V67，issue #4384 A1）——**闭词表**，与后端 `ProductionOperationCommandService`
 * 的校验、迁移 V67 的列注释同口径（前端不发明第三值）。
 */
const SCOPE_META: Record<ProductionScope, { label: string; title: string }> = {
  position: { label: '部位级', title: '每部位一次（如布帘一道、纱帘一道）' },
  set: { label: '套级', title: '每樘窗一次（一樘「布 + 纱」只做一次）' },
}
const SCOPE_ORDER: ProductionScope[] = ['position', 'set']

/**
 * 库口径 → 受控两档。**缺省按 `position`**（安全方向）：列是 `NOT NULL DEFAULT 'position'`，
 * 老实例未升级时键缺失 —— 默认成 `set` 会把每道工序都静默去重，默认成 `position` 最坏只是保持今天的行为。
 */
const scopeOf = (op: CatalogOperation): ProductionScope => (op.scope === 'set' ? 'set' : 'position')

/** 触发维（V71 列注释的闭词表；`shaped` / `processing_item` 是表结构预留，无种子行） */
const TRIGGER_KIND_LABEL: Record<string, string> = {
  craft: '工艺',
  option: '特殊选项',
  shaped: '是否定型',
  processing_item: '加工项',
}

/** 规则动作的可读文案：`insert` 带锚点（无锚点 = 追加末尾）/ `remove` 移除 */
const ruleActionText = (rule: RouteRule) =>
  rule.action === 'remove'
    ? `移除「${rule.operation ?? '—'}」`
    : `在「${rule.after_operation ?? '末尾'}」之后插入「${rule.operation ?? '—'}」`

/** provenance 徽标；「占位待确认」是**可行动**引导：点它即进入该工序的改价入口（既有版本化写面） */
function SourceBadge({
  source,
  testId,
  onConfirmPrice,
}: {
  source?: ProductionSource | null
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
  return <span data-testid={testId} className={className}>{meta.label}</span>
}

/** 就绪度一步（把「工序 → 路线 → 默认路线」的先后关系变成看得见的步骤） */
function ReadinessStep({
  testId,
  index,
  label,
  state,
  hint,
}: {
  testId: string
  index: number
  label: string
  state: 'done' | 'todo' | 'unknown'
  hint?: string
}) {
  const done = state === 'done'
  return (
    <div
      data-testid={testId}
      data-state={state}
      className={cn(
        'rounded border px-3 py-2',
        done ? 'border-emerald-200 bg-emerald-50/60' : 'border-amber-200 bg-amber-50/60',
      )}
    >
      <div className="flex items-center gap-2 text-sm">
        <span className={cn('font-medium', done ? 'text-emerald-800' : 'text-amber-900')}>
          {index}. {label}
        </span>
        <span className={cn('text-xs', done ? 'text-emerald-700' : 'text-amber-800')}>
          {done ? '已完成' : state === 'unknown' ? '未知' : '待完成'}
        </span>
      </div>
      {!done && hint && <p className="mt-1 text-xs text-amber-800">{hint}</p>}
    </div>
  )
}

/** 折叠次区（同一件事的明细面）—— 折叠 ≠ 删能力：入口常驻可见并带计数 */
function CollapsibleSection({
  testId,
  title,
  hint,
  count,
  open,
  onToggle,
  children,
}: {
  testId: string
  title: string
  hint: string
  count?: string
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white" data-testid={testId}>
      <button
        type="button"
        aria-expanded={open}
        data-testid={`${testId}-toggle`}
        data-state={open ? 'open' : 'closed'}
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-5 py-3 text-left hover:bg-neutral-50"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 text-neutral-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-neutral-400" />
        )}
        <span className="text-sm font-medium text-neutral-900">{title}</span>
        {count && (
          <span className="text-xs text-neutral-400" data-testid={`${testId}-total`}>
            {count}
          </span>
        )}
        <span className="ml-auto hidden text-xs text-neutral-400 sm:inline">{hint}</span>
      </button>
      {open && (
        <div className="border-t border-neutral-100 p-5 pt-4" data-testid={`${testId}-body`}>
          {children}
        </div>
      )}
    </section>
  )
}

/**
 * 主线上一步的展示口径（只读与草稿**共用一份** —— 两处各拼一份必然漂移）。
 *
 * ⚠️ `resolved` = 该工序能在**工序库**里查到（才有 分组/单位/单价/必完 这些库口径元数据）。
 * 主线存的是**逻辑工序名**（`精裁`），而 `production_operations.name` 仍是旧名（`精裁-布`），
 * 两者之间**没有**暴露给前端的映射 ⇒ 前端**不猜**：查不到就只显示名字，不发明单位/单价。
 */
interface StepView {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  unit_price?: number | null
  is_must_finish?: boolean
  /** 工序库里有这条（有库口径元数据） */
  resolved: boolean
  /** 工序库与部位价目表**都**没有它（停用/被删）⇒ 保存必被后端拒，但页面要先让人看见 */
  missing: boolean
}

export default function ProcessConfigPage() {
  // ── 只读面 ──
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [templates, setTemplates] = useState<ProductionSeedTemplate[]>([])
  const [matrix, setMatrix] = useState<OperationPosition[]>([])
  const [matrixError, setMatrixError] = useState('')
  const [rules, setRules] = useState<RouteRule[]>([])
  const [rulesError, setRulesError] = useState('')
  const [loading, setLoading] = useState(true)
  /** 两个 tab：`operations` 工艺项 / `routes` 工艺路线。默认落在「工艺项」—— 依赖顺序上它在前。 */
  const [tab, setTab] = useState<'operations' | 'routes'>('operations')
  /** 「添加工序」选择器（路线 tab 内）—— 工序库在另一个 tab，编辑器必须自带入口 */
  const [picked, setPicked] = useState('')
  const [error, setError] = useState('')
  /** 工序名搜索（**一个控件管整个「工艺项」tab**：矩阵行 + 工序库明细） */
  const [search, setSearch] = useState('')
  /** 次区折叠（默认收起：主区是矩阵，明细面按需展开） */
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [rulesOpen, setRulesOpen] = useState(false)

  // ── 工序库行内编辑（单价；作用域/必完为即时写） ──
  const [editingOpId, setEditingOpId] = useState<string | number | null>(null)
  const [opDraft, setOpDraft] = useState('')
  const [opBusy, setOpBusy] = useState(false)

  // ── 主线编辑 ──
  const [editing, setEditing] = useState<Routing | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState<string[]>([])
  /** 本地即时错误（如空主线），与后端理由同区展示，形态一致 */
  const [localReason, setLocalReason] = useState('')

  // ── 路线管理面（改名 / 删除 / 设为默认）──
  const [renameTarget, setRenameTarget] = useState<Routing | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [confirmAction, setConfirmAction] = useState<{ kind: 'delete' | 'default'; routing: Routing } | null>(null)
  /** 管理面被拒的逐条理由（就地展示，不吞成一句「操作失败」） */
  const [opReasons, setOpReasons] = useState<string[]>([])

  // ── 弹窗 ──
  const [newRouteOpen, setNewRouteOpen] = useState(false)
  /** 新建路线：默认三种帘种全适用（收窄适用范围就取消勾选；至少留一个） */
  const [newRoute, setNewRoute] = useState<{ name: string; positions: string[] }>({
    name: '',
    positions: POSITION_DOMAIN,
  })
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  const [confirmTemplate, setConfirmTemplate] = useState<ProductionSeedTemplate | null>(null)
  const [applying, setApplying] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    // 五条只读端点互不依赖：任一条失败不得把整页吞掉（页面不白屏，失败处给可读提示）
    const [routingsRes, catalogRes, templateRes, matrixRes, rulesRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getSeedTemplates(),
      productionApi.getOperationPositions(),
      productionApi.getRouteRules(),
    ])
    if (routingsRes.status === 'fulfilled') {
      setRoutings(routingsRes.value.data?.data ?? null)
    } else {
      setRoutings(null)
      setError('工艺路线加载失败，请稍后重试')
    }
    if (catalogRes.status === 'fulfilled') {
      setCatalog(catalogRes.value.data?.data ?? null)
      setCatalogError('')
    } else {
      setCatalog(null)
      setCatalogError('工序库加载失败，请稍后重试')
    }
    setTemplates(templateRes.status === 'fulfilled' ? templateRes.value.data?.data ?? [] : [])
    if (matrixRes.status === 'fulfilled') {
      setMatrix(matrixRes.value.data?.data ?? [])
      setMatrixError('')
    } else {
      setMatrix([])
      setMatrixError('部位价目加载失败，请稍后重试')
    }
    if (rulesRes.status === 'fulfilled') {
      setRules(rulesRes.value.data?.data ?? [])
      setRulesError('')
    } else {
      setRules([])
      setRulesError('条件工序规则加载失败，请稍后重试')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const libraryOps = useMemo(() => (catalog?.groups ?? []).flatMap((g) => g.operations), [catalog])
  const libraryByName = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(op.name, op))
    return m
  }, [libraryOps])
  /** 部位价目表里出现过的逻辑工序名（主线可能用它书写 ⇒ 判「工序是否存在」必须并上这一侧） */
  const matrixOps = useMemo(() => new Set(matrix.map((c) => c.operation)), [matrix])
  const knownOps = useMemo(
    () => new Set<string>([...libraryByName.keys(), ...matrixOps]),
    [libraryByName, matrixOps],
  )

  const q = search.trim().toLowerCase()

  /** 工序库明细按搜索词过滤（分组内过滤；整组被滤空则不渲染该组） */
  const visibleGroups = useMemo(
    () =>
      (catalog?.groups ?? [])
        .map((g) => ({ ...g, operations: g.operations.filter((op) => !q || op.name.toLowerCase().includes(q)) }))
        .filter((g) => g.operations.length > 0),
    [catalog, q],
  )

  // ────────────────────────── 部位价目矩阵（tab「工艺项」主区） ──────────────────────────

  /** 列 = 闭词表里**数据里真有**的部位 + 未知部位（追加在后；不丢数据） */
  const positionColumns = useMemo(() => {
    const present = new Set(matrix.map((c) => c.position))
    return [
      ...POSITION_DOMAIN.filter((p) => present.has(p)),
      ...[...present].filter((p) => !POSITION_DOMAIN.includes(p)),
    ]
  }, [matrix])

  /**
   * 行 = 逻辑工序（**保持服务端顺序**：`Map` 的插入顺序即首次出现顺序）。
   * ⚠️ **不过滤** `applicable=false` 的格 —— 「明确不做」与「没定价」必须在界面上可区分。
   */
  const matrixRows = useMemo(() => {
    const byOp = new Map<string, Map<string, OperationPosition>>()
    matrix.forEach((cell) => {
      if (!byOp.has(cell.operation)) byOp.set(cell.operation, new Map())
      byOp.get(cell.operation)!.set(cell.position, cell)
    })
    return [...byOp.entries()].map(([operation, cells]) => ({ operation, cells }))
  }, [matrix])

  const visibleMatrixRows = useMemo(
    () => matrixRows.filter((r) => !q || r.operation.toLowerCase().includes(q)),
    [matrixRows, q],
  )

  /** 一格三态：明确不做（applicable=false）/ 没定价 / 有价 —— 三态**不同形** */
  const cellState = (cell?: OperationPosition): 'na' | 'unpriced' | 'priced' => {
    if (!cell) return 'unpriced'
    if (cell.applicable === false) return 'na'
    return cell.unit_price == null ? 'unpriced' : 'priced'
  }

  // ────────────────────────── 就绪度（先后依赖显性化） ──────────────────────────

  const operationsReady = (catalog?.total ?? 0) > 0
  const routeList = useMemo(() => routings?.routings ?? [], [routings])
  const emptyShells = useMemo(
    () => routeList.filter((r) => (r.mainline ?? []).length === 0),
    [routeList],
  )
  const routingsReady = routeList.length > 0 && emptyShells.length === 0
  const defaults = useMemo(() => routeList.filter((r) => r.is_default), [routeList])

  const routingsHint =
    routeList.length === 0
      ? '下一步：点右上「新建路线」建一条（一条路线 = 一条有序主线 + 适用帘种）。'
      : emptyShells.length > 0
        ? `有 ${emptyShells.length} 条「空壳」路线（主线为空）：该路线命中后一道工序都没有，请点「编辑主线」把工序排进去。`
        : ''
  const defaultRouteHint =
    defaults.length === 0
      ? '没有默认路线：匹配不到专属路线的订单，一张加工单也生成不了。请在下方路线列表点「设为默认」选一条。'
      : ''

  // ────────────────────────── 主线编辑 ──────────────────────────

  /** 主线一步的展示口径（只读与草稿共用 —— 见 {@link StepView}） */
  const stepView = useCallback(
    (name: string, i: number): StepView => {
      const lib = libraryByName.get(name)
      return {
        seq: i + 1,
        operation: name,
        group: lib?.group ?? null,
        unit: lib?.unit ?? null,
        unit_price: lib?.unit_price ?? null,
        is_must_finish: lib?.is_must_finish,
        resolved: !!lib,
        missing: !knownOps.has(name),
      }
    },
    [libraryByName, knownOps],
  )

  const openEditor = (routing: Routing) => {
    setEditing(routing)
    setEditingId(routing.id)
    setDraft(routing.mainline ?? [])
    setReasons([])
    setLocalReason('')
  }

  const closeEditor = () => {
    setEditing(null)
    setEditingId(null)
    setDraft([])
    setReasons([])
    setLocalReason('')
  }

  const draftSteps: StepView[] = useMemo(() => draft.map(stepView), [draft, stepView])

  const missingSteps = draftSteps.filter((s) => s.missing)
  /**
   * 就地预检：一道必完工序都没有 ⇒ 这张单**永远完不了工**。
   * ⚠️ 只在**每一步都能在工序库里查到**时判 —— 逻辑工序名（`精裁`）拿不到 `is_must_finish`
   * ⇒ 判不了就不判（**静默 = 未知**，不得当成违规，同 route_source 纪律）。
   */
  const lacksMustFinish =
    draftSteps.length > 0 &&
    draftSteps.every((s) => s.resolved) &&
    !draftSteps.some((s) => s.is_must_finish)

  const addFromPalette = (name: string) => {
    if (!editingId) return
    setDraft((d) => (d.includes(name) ? d : [...d, name]))
    setLocalReason('')
  }

  const move = (index: number, delta: -1 | 1) => {
    setDraft((d) => {
      const next = [...d]
      const target = index + delta
      if (target < 0 || target >= next.length) return d
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const removeAt = (index: number) => setDraft((d) => d.filter((_, i) => i !== index))

  /** 保存主线：空主线本地拦（不发无效请求）；其余护栏理由由后端逐条返回 */
  const saveSequence = async () => {
    if (!editing) return
    if (draft.length === 0) {
      setLocalReason('主线不能为空：一条路线至少要有 1 道工序')
      setReasons([])
      return
    }
    setSaving(true)
    setReasons([])
    setLocalReason('')
    try {
      await productionApi.updateRouting(editing.id, { mainline: draft })
      toast.success('路线主线已保存')
      closeEditor()
      await load()
    } catch (e) {
      console.error(e)
      setReasons(routingGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('路线主线保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 新建路线：名字 + 适用帘种 → 建壳后**立刻进入主线编辑**（消灭「建壳了但没排」的静默态） */
  const createRoute = async () => {
    const name = newRoute.name.trim()
    if (!name) {
      toast.error('请填写路线名称')
      return
    }
    if (newRoute.positions.length === 0) {
      toast.error('请至少勾选一个适用帘种')
      return
    }
    setBusy(true)
    try {
      const res = await productionApi.createRouting({ name, positions: newRoute.positions })
      const created = res.data?.data as Routing | undefined
      toast.success(`已新建路线「${name}」，请把工序排进主线`)
      setNewRouteOpen(false)
      setNewRoute({ name: '', positions: POSITION_DOMAIN })
      await load()
      if (created?.id) {
        openEditor({ ...created, mainline: created.mainline ?? [] })
      }
    } catch (e) {
      console.error(e)
      toastRequestError(e, '新建路线失败')
    } finally {
      setBusy(false)
    }
  }

  // ────────────────────────── 路线管理面（改名 / 删除 / 设为默认） ──────────────────────────

  const openRename = (routing: Routing) => {
    setRenameTarget(routing)
    setRenameDraft(routing.name)
    setOpReasons([])
  }

  /** 改名：**只提交 `name`**（不给 mainline ⇒ 服务端不动序列） */
  const submitRename = async () => {
    const target = renameTarget
    if (!target) return
    const name = renameDraft.trim()
    if (!name) {
      setOpReasons(['路线名称不能为空'])
      return
    }
    setBusy(true)
    setOpReasons([])
    try {
      await productionApi.updateRouting(target.id, { name })
      toast.success('路线名称已更新')
      setRenameTarget(null)
      await load()
    } catch (e) {
      console.error(e)
      setOpReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('改名失败')
    } finally {
      setBusy(false)
    }
  }

  /**
   * 删除 / 设为默认（二次确认后执行）。
   * ⚠️ `is_default` **只发 true** —— 发 false 会让该租户零默认（后端 422）。
   */
  const runConfirm = async () => {
    const action = confirmAction
    if (!action) return
    setBusy(true)
    setOpReasons([])
    try {
      if (action.kind === 'delete') {
        await productionApi.deleteRouting(action.routing.id)
        toast.success(`已删除路线「${action.routing.name}」`)
      } else {
        await productionApi.updateRouting(action.routing.id, { is_default: true })
        toast.success(`已把「${action.routing.name}」设为默认路线`)
      }
      setConfirmAction(null)
      await load()
    } catch (e) {
      console.error(e)
      setOpReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error(action.kind === 'delete' ? '删除失败' : '设为默认失败')
    } finally {
      setBusy(false)
    }
  }

  /** 删除护栏（**就地**给理由，不等后端 422）；两条同时成立时两条都给（后端也一次报全） */
  const deleteBlockReasons = (routing: Routing): string[] => {
    const out: string[] = []
    if (routeList.length <= 1) {
      out.push('这是最后一条工艺路线：删了就一条都不剩，任何订单都生成不了加工单。请先新建一条路线，再删这条。')
    }
    if (routing.is_default) {
      out.push(
        '默认路线是路线兜底的终点：删了之后匹配不到专属路线的订单，一张加工单也生成不了。请先把另一条设为默认，再删这条。',
      )
    }
    return out
  }

  // ────────────────────────── 工序库写面 ──────────────────────────

  const createOperation = async () => {
    const name = newOp.name.trim()
    const price = Number(newOp.unit_price)
    if (!name) {
      toast.error('请填写工序名称')
      return
    }
    if (newOp.unit_price.trim() === '' || Number.isNaN(price)) {
      toast.error('请输入有效单价')
      return
    }
    setBusy(true)
    try {
      await productionApi.createOperation({
        name,
        group_name: newOp.group_name.trim() || undefined,
        unit: newOp.unit.trim() || undefined,
        unit_price: price,
      })
      toast.success('工序已新增')
      setNewOpOpen(false)
      setNewOp({ name: '', group_name: '', unit: '', unit_price: '' })
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('新增工序失败')
    } finally {
      setBusy(false)
    }
  }

  /** 工序库写路径统一出口：成功 toast + 重新拉取（结果可见），失败可读提示且不假装成功 */
  const submitOperation = async (id: string | number, payload: Parameters<typeof productionApi.updateOperation>[1]) => {
    setOpBusy(true)
    try {
      await productionApi.updateOperation(id, payload)
      toast.success('工序已更新')
      setEditingOpId(null)
      await load()
    } catch (e) {
      toastRequestError(e, '工序更新失败')
    } finally {
      setOpBusy(false)
    }
  }

  const savePrice = (op: CatalogOperation) => {
    const value = Number(opDraft)
    if (opDraft.trim() === '' || Number.isNaN(value)) {
      toast.error('请输入有效单价')
      return
    }
    submitOperation(op.id, { unit_price: value })
  }

  /**
   * 一键补套行业模板（**空态补救**，不是主路径）。
   * 结果 toast 必须报**服务端返回的真实数字**（新增/跳过）—— 缺结果体时显式报错，不假装成功。
   */
  const applyTemplate = async () => {
    const template = confirmTemplate
    if (!template) return
    setApplying(template.templateId)
    try {
      const res = await productionApi.applySeedTemplate(template.templateId)
      const result = res.data?.data
      if (!result) {
        toast.error('套用结果缺失，请刷新页面核对工序库')
      } else {
        toast.success(
          `已套用「${template.name}」：新增 ${result.created_operations} 道工序、` +
            `${result.created_routings} 条工艺路线、跳过 ${result.skipped} 条（初始价请在列表中确认后修改）`,
        )
      }
      setConfirmTemplate(null)
      await load()
    } catch (e) {
      toastRequestError(e, '套用行业模板失败')
    } finally {
      setApplying('')
    }
  }

  const total = catalog?.total ?? 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">工艺配置</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            工序（在哪些部位做、各自多少钱）→ 工艺路线（订单按哪条主线走）。路线是计件工资与完工判定的唯一输入
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button variant="secondary" size="sm" data-testid="routings-new-operation" onClick={() => setNewOpOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            新增工序
          </Button>
          <Button size="sm" data-testid="routings-new-route" onClick={() => setNewRouteOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建路线
          </Button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="routings-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="routings-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <Button size="sm" data-testid="routings-retry" onClick={load}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* ── 就绪度（三步）：① 工序库 → ② 工艺路线 → ③ 默认路线 ── */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="process-readiness">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">配置就绪度</h2>
              <span className="text-sm text-neutral-500">
                按顺序配：先有工序，才能排路线；路线里要有一条默认的兜底
              </span>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <ReadinessStep
                testId="readiness-step-operations"
                index={1}
                label={`工序库 ${total} 道`}
                state={operationsReady ? 'done' : 'todo'}
                hint="下一步：用下方「行业模板」补套，或点右上「新增工序」逐道建。"
              />
              <ReadinessStep
                testId="readiness-step-routings"
                index={2}
                label={`工艺路线 ${routeList.length} 条`}
                state={routingsReady ? 'done' : 'todo'}
                hint={routingsHint}
              />
              <ReadinessStep
                testId="readiness-step-default-route"
                index={3}
                label={`默认路线 ${defaults.length} 条`}
                state={defaults.length === 1 ? 'done' : 'todo'}
                hint={defaultRouteHint}
              />
            </div>
          </div>

          {/* ── 行业模板：**仅工序库为空时**出现（开租已自动套用；这里只是补套路径） ── */}
          {!operationsReady && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-5" data-testid="seed-templates">
              <div className="mb-3 flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-medium text-neutral-900">工序库为空 · 补套行业模板</h2>
                <span className="text-sm text-neutral-600">
                  开租时系统会按行业自动套用；这里是套用失败或老租户的补救入口（已存在的条目自动跳过）
                </span>
              </div>
              {templates.length === 0 ? (
                <p className="py-4 text-sm text-neutral-500" data-testid="seed-templates-empty">
                  暂无可用模板
                </p>
              ) : (
                <div className="divide-y divide-amber-200">
                  {templates.map((t) => (
                    <div
                      key={t.templateId}
                      className="flex items-start justify-between gap-3 py-3"
                      data-testid={`seed-template-${t.templateId}`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-neutral-900">{t.name}</span>
                          <span className="rounded bg-white px-1.5 py-0.5 text-[11px] text-neutral-500">
                            v{t.version}
                          </span>
                        </div>
                        {t.description && <p className="mt-1 text-sm text-neutral-600">{t.description}</p>}
                      </div>
                      <Button
                        size="sm"
                        data-testid={`seed-template-apply-${t.templateId}`}
                        disabled={applying === t.templateId}
                        onClick={() => setConfirmTemplate(t)}
                        title="把该行业的预置工序与工艺路线复制到您的工序库（已存在条目自动跳过）"
                      >
                        {applying === t.templateId ? '套用中…' : '一键套用'}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 两个 tab：工艺项 / 工艺路线 ──
              合并仍是**一个菜单入口、一个页面**；tab 切换**不丢状态**（编辑中的 draft 保留在 state 里）。 */}
          <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="process-config-tabs">
            {([
              { key: 'operations', label: '工艺项' },
              { key: 'routes', label: '工艺路线' },
            ] as const).map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                data-testid={`process-config-tab-${t.key}`}
                data-state={tab === t.key ? 'active' : 'inactive'}
                onClick={() => setTab(t.key)}
                className={cn(
                  '-mb-px border-b-2 px-4 py-2 text-sm transition-colors',
                  tab === t.key
                    ? 'border-primary-600 font-medium text-primary-700'
                    : 'border-transparent text-neutral-500 hover:text-neutral-800',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div>
            {/* ══════════════ tab「工艺项」：主区 = 部位价目矩阵，次区 = 工序库明细 ══════════════ */}
            {tab === 'operations' && (
              <div className="space-y-4">
                {/* 主区：部位价目矩阵（这一屏回答「每道工序在哪个部位做、多少钱」） */}
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="operation-price-matrix">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <h2 className="text-base font-medium text-neutral-900">部位价目</h2>
                      <span className="text-sm text-neutral-500">
                        <span data-testid="operation-price-matrix-total">{matrixRows.length}</span> 道工序 ×{' '}
                        {positionColumns.length} 个部位 ={' '}
                        <span data-testid="operation-price-matrix-cells">
                          {matrixRows.length * positionColumns.length}
                        </span>{' '}
                        格
                      </span>
                    </div>
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="搜索工序名…"
                      aria-label="搜索工序"
                      data-testid="operations-search"
                      className="h-8 w-40 rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                  <p className="mb-3 text-xs text-neutral-500">
                    同一道工序在布帘 / 纱帘 / 帘头<strong>各自定价</strong>：<span className="text-neutral-400">不做</span> =
                    该部位明确不做这道工序（不是漏配）；<span className="text-amber-700">未定价</span> =
                    做但还没定价。改价写面随 v1b 开放，当前为只读呈现。
                  </p>

                  {matrixError ? (
                    <p
                      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="operation-price-matrix-error"
                    >
                      {matrixError}
                    </p>
                  ) : visibleMatrixRows.length === 0 ? (
                    <p className="py-8 text-center text-sm text-neutral-400" data-testid="operation-price-matrix-empty">
                      {matrixRows.length === 0
                        ? '暂无部位价目数据 —— 工序的单价在下方「工序库明细」里维护'
                        : '没有匹配的工序，换个关键词试试'}
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">工序</th>
                            {positionColumns.map((p) => (
                              <th key={p} className="py-2 pr-4 font-medium">
                                {p}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {visibleMatrixRows.map((row) => (
                            <tr
                              key={row.operation}
                              className="border-b border-neutral-100 last:border-0"
                              data-testid={`matrix-row-${row.operation}`}
                              data-operation={row.operation}
                            >
                              <td className="py-2.5 pr-4 text-neutral-900">{row.operation}</td>
                              {positionColumns.map((p) => {
                                const cell = row.cells.get(p)
                                const state = cellState(cell)
                                return (
                                  <td
                                    key={p}
                                    data-testid={`matrix-cell-${row.operation}-${p}`}
                                    data-state={state}
                                    title={
                                      state === 'na'
                                        ? `${p}不做「${row.operation}」这道工序`
                                        : state === 'unpriced'
                                          ? `${p}做「${row.operation}」，但还没定价`
                                          : `${p}「${row.operation}」单价 ${money(cell?.unit_price)}`
                                    }
                                    className={cn(
                                      'py-2.5 pr-4',
                                      state === 'na'
                                        ? 'text-neutral-400'
                                        : state === 'unpriced'
                                          ? 'text-amber-700'
                                          : 'text-neutral-900',
                                    )}
                                  >
                                    {state === 'na' ? '不做' : state === 'unpriced' ? '未定价' : money(cell?.unit_price)}
                                  </td>
                                )
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>

                {/* 次区（折叠）：工序库明细 —— 分组 / 单位 / 作用域 / 必完 / 改单价 */}
                <CollapsibleSection
                  testId="operations-catalog"
                  title="工序库明细"
                  hint="分组 · 单位 · 作用域 · 必完 · 改单价"
                  count={`共 ${total} 道`}
                  open={catalogOpen}
                  onToggle={() => setCatalogOpen((v) => !v)}
                >
                  <p className="mb-3 text-xs text-neutral-500">
                    工序分组 · 作用域（部位级/套级） · 计件单价 · 必完开关；调价只影响新报工（历史报工按当时价）。
                  </p>
                  {catalogError ? (
                    <p
                      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="operations-catalog-error"
                    >
                      {catalogError}
                    </p>
                  ) : (
                    <>
                      {visibleGroups.length === 0 ? (
                        <p className="py-8 text-center text-sm text-neutral-400" data-testid="operations-catalog-empty">
                          {total === 0
                            ? '暂无工序数据 —— 用上方「补套行业模板」载入行业预置工序与工艺路线'
                            : '没有匹配的工序，换个关键词试试'}
                        </p>
                      ) : (
                        <div className="space-y-5">
                          {visibleGroups.map((g) => (
                            <div key={g.group} data-testid={`operation-group-${g.group}`}>
                              <div className="mb-2 flex items-center gap-2">
                                <span className="text-sm font-medium text-neutral-900">{g.group}</span>
                                <span className="text-xs text-neutral-400">{g.operations.length} 道</span>
                              </div>
                              <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                  <thead>
                                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                                      <th className="py-2 pr-4 font-medium">工序名称</th>
                                      <th className="py-2 pr-4 font-medium">部位</th>
                                      <th className="py-2 pr-4 font-medium">作用域</th>
                                      <th className="py-2 pr-4 font-medium">单位</th>
                                      <th className="py-2 pr-4 font-medium">计件单价</th>
                                      <th className="py-2 pr-4 font-medium">必完</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {g.operations.map((op) => (
                                      <tr
                                        key={op.id}
                                        className="border-b border-neutral-100 last:border-0"
                                        data-testid={`operation-row-${op.id}`}
                                      >
                                        <td className="py-2.5 pr-4 text-neutral-900">
                                          {op.name}
                                          {op.is_start_marker && (
                                            <span className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
                                              首工序
                                            </span>
                                          )}
                                          <SourceBadge
                                            source={op.source}
                                            testId={`operation-source-${op.id}`}
                                            onConfirmPrice={() => {
                                              setEditingOpId(op.id)
                                              setOpDraft(String(op.unit_price ?? 0))
                                            }}
                                          />
                                        </td>
                                        <td className="py-2.5 pr-4 text-neutral-600">{op.position ?? '—'}</td>
                                        {/* 作用域（#4384 A1）：可见 + 可改。就地改档走既有写面（PUT body 带 scope）。 */}
                                        <td className="py-2.5 pr-4">
                                          <select
                                            aria-label={`${op.name} 作用域`}
                                            data-testid={`operation-scope-${op.id}`}
                                            value={scopeOf(op)}
                                            disabled={opBusy}
                                            title={SCOPE_META[scopeOf(op)].title}
                                            onChange={(e) =>
                                              submitOperation(op.id, { scope: e.target.value as ProductionScope })
                                            }
                                            className="h-8 rounded border border-neutral-300 bg-white px-1.5 text-sm text-neutral-700 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 disabled:opacity-50"
                                          >
                                            {SCOPE_ORDER.map((s) => (
                                              <option key={s} value={s} title={SCOPE_META[s].title}>
                                                {SCOPE_META[s].label}
                                              </option>
                                            ))}
                                          </select>
                                        </td>
                                        <td className="py-2.5 pr-4 text-neutral-600">{op.unit ?? '—'}</td>
                                        <td className="py-2.5 pr-4 text-neutral-900">
                                          {editingOpId === op.id ? (
                                            <span className="flex items-center gap-1.5">
                                              <input
                                                value={opDraft}
                                                inputMode="decimal"
                                                aria-label={`${op.name} 计件单价`}
                                                data-testid={`operation-price-input-${op.id}`}
                                                onChange={(e) => setOpDraft(e.target.value)}
                                                onKeyDown={(e) => e.key === 'Enter' && savePrice(op)}
                                                className="h-8 w-24 rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                                              />
                                              <button
                                                type="button"
                                                aria-label="保存单价"
                                                data-testid={`operation-price-save-${op.id}`}
                                                disabled={opBusy}
                                                onClick={() => savePrice(op)}
                                                className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
                                              >
                                                <Check className="w-4 h-4" />
                                              </button>
                                            </span>
                                          ) : (
                                            <span className="flex items-center gap-1.5">
                                              <span>{money(op.unit_price)}</span>
                                              <button
                                                type="button"
                                                aria-label={`编辑 ${op.name} 单价`}
                                                data-testid={`operation-price-edit-${op.id}`}
                                                onClick={() => {
                                                  setEditingOpId(op.id)
                                                  setOpDraft(String(op.unit_price ?? 0))
                                                }}
                                                className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
                                              >
                                                <Pencil className="w-3.5 h-3.5" />
                                              </button>
                                            </span>
                                          )}
                                        </td>
                                        <td className="py-2.5 pr-4">
                                          <input
                                            type="checkbox"
                                            aria-label={`${op.name} 必须完成才可打包`}
                                            data-testid={`operation-must-finish-${op.id}`}
                                            checked={!!op.is_must_finish}
                                            disabled={opBusy}
                                            onChange={(e) => submitOperation(op.id, { is_must_finish: e.target.checked })}
                                            className="h-4 w-4 accent-primary-600"
                                          />
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </CollapsibleSection>
              </div>
            )}

            {/* ══════════════ tab「工艺路线」：主区 = 具名路线，次区 = 条件工序规则 ══════════════ */}
            {tab === 'routes' && (
              <div className="space-y-4">
                {/* 主区：具名路线（name + 默认徽标 + 适用帘种 + 主线 + 改名/设默认/删除） */}
                <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="routings-list">
                  <div className="mb-3 flex items-baseline gap-2">
                    <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
                    <span className="text-sm text-neutral-500">
                      共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条 · 每条 = 一条有序主线 +
                      适用帘种
                    </span>
                  </div>

                  {/* 管理面被拒：逐条理由就地展示（不吞成一句「操作失败」） */}
                  {opReasons.length > 0 && (
                    <div
                      className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="routing-op-error"
                    >
                      <p className="flex items-center gap-2 font-medium">
                        <AlertCircle className="w-4 h-4" />
                        操作被拒绝，请逐条处理：
                      </p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-6">
                        {opReasons.map((r, i) => (
                          <li key={i} data-testid={`routing-op-error-item-${i}`}>
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {routeList.length === 0 ? (
                    <p className="py-8 text-center text-sm text-neutral-400" data-testid="routings-empty">
                      暂无工艺路线 —— 点右上「新建路线」建一条（一条路线 = 一条有序主线 + 适用帘种）
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {routeList.map((routing) => {
                        const id = routing.id
                        const isEditing = editingId === id
                        const mainline = routing.mainline ?? []
                        const isEmptyShell = mainline.length === 0
                        const blockReasons = deleteBlockReasons(routing)
                        return (
                          <div key={id} className="rounded-lg border border-neutral-200 p-4" data-testid={`routing-${id}`}>
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-baseline gap-2">
                                <span className="text-sm font-medium text-neutral-900" data-testid={`routing-name-${id}`}>
                                  {routing.name}
                                </span>
                                {routing.is_default && (
                                  <span
                                    data-testid={`routing-default-${id}`}
                                    title="默认路线：匹配不到专属路线的订单走它（每租户恰一条）"
                                    className="rounded bg-primary-50 px-1.5 py-0.5 text-[11px] text-primary-700"
                                  >
                                    默认
                                  </span>
                                )}
                                <span className="text-xs text-neutral-400" data-testid={`routing-positions-${id}`}>
                                  适用：{(routing.positions ?? []).join(' / ') || '—'}
                                </span>
                                <span
                                  className="text-xs text-neutral-400"
                                  data-testid={`routing-mainline-count-${id}`}
                                >
                                  主线 {mainline.length} 道
                                </span>
                                {isEmptyShell && (
                                  <span
                                    data-testid={`routing-empty-shell-${id}`}
                                    title="主线为空：这条路线被命中后一道工序都没有 —— 既不报错也不拦，该订单会静默拿到 0 道工序"
                                    className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
                                  >
                                    空壳 · 不可用
                                  </span>
                                )}
                              </div>
                              {isEditing ? (
                                <div className="flex items-center gap-2">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-cancel-${id}`}
                                    disabled={saving}
                                    onClick={closeEditor}
                                  >
                                    取消
                                  </Button>
                                  <Button size="sm" data-testid={`routing-save-${id}`} loading={saving} onClick={saveSequence}>
                                    保存
                                  </Button>
                                </div>
                              ) : (
                                <div className="flex flex-wrap items-center gap-2">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-edit-${id}`}
                                    onClick={() => openEditor(routing)}
                                  >
                                    <Pencil className="w-3.5 h-3.5 mr-1.5" />
                                    编辑主线
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-rename-${id}`}
                                    onClick={() => openRename(routing)}
                                    title="只改路线总名，不动主线工序"
                                  >
                                    改名
                                  </Button>
                                  {/* 设为默认：默认行**不显示**（后端 is_default:false ⇒ 422，前端不得发 false） */}
                                  {!routing.is_default && (
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      data-testid={`routing-set-default-${id}`}
                                      onClick={() => {
                                        setOpReasons([])
                                        setConfirmAction({ kind: 'default', routing })
                                      }}
                                    >
                                      <Star className="w-3.5 h-3.5 mr-1.5" />
                                      设为默认
                                    </Button>
                                  )}
                                  <Button
                                    variant="danger"
                                    size="sm"
                                    data-testid={`routing-delete-${id}`}
                                    disabled={blockReasons.length > 0 || busy}
                                    onClick={() => {
                                      setOpReasons([])
                                      setConfirmAction({ kind: 'delete', routing })
                                    }}
                                  >
                                    <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                                    删除
                                  </Button>
                                </div>
                              )}
                            </div>

                            {/* 护栏理由**就地**展示（不等后端 422 才知道为什么点不动） */}
                            {blockReasons.length > 0 && (
                              <ul
                                className="mt-2 list-disc space-y-0.5 rounded border border-amber-200 bg-amber-50 px-3 py-2 pl-7 text-xs text-amber-800"
                                data-testid={`routing-delete-blocked-${id}`}
                              >
                                {blockReasons.map((r, i) => (
                                  <li key={i}>{r}</li>
                                ))}
                              </ul>
                            )}

                            {/* 主线保存被拒：逐条展示理由（空主线 / 工序不存在 / 重复 / 缺必完工序） */}
                            {isEditing && (localReason || reasons.length > 0) && (
                              <div
                                className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                                data-testid={`routing-error-${id}`}
                              >
                                <p className="flex items-center gap-2 font-medium">
                                  <AlertCircle className="w-4 h-4" />
                                  保存被拒绝，请逐条修正：
                                </p>
                                <ul className="mt-1 list-disc space-y-0.5 pl-6">
                                  {(localReason ? [localReason] : reasons).map((r, i) => (
                                    <li key={i} data-testid={`routing-error-item-${i}`}>
                                      {r}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {isEditing ? (
                              <div className="mt-3 space-y-3">
                                {/* 就地预检（后端仍是唯一权威，这里只把「保存失败」提前成「看得见」） */}
                                {lacksMustFinish && (
                                  <p
                                    className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
                                    data-testid={`routing-precheck-${id}`}
                                  >
                                    这条路线一道「必完」工序都没有 —— 必完工序全绿是完工判定的唯一依据，
                                    缺了这张单永远完不了工。请至少把一道关键工序标为「必完」。
                                  </p>
                                )}
                                {missingSteps.length > 0 && (
                                  <p
                                    className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                                    data-testid={`routing-precheck-missing-${id}`}
                                  >
                                    有 {missingSteps.length} 道工序在工序库中不存在或已停用（
                                    {missingSteps.map((s) => s.operation).join('、')}
                                    ）—— 保存会被拒，请先到「工艺项 · 工序库明细」补上，或把它从主线里移除。
                                  </p>
                                )}

                                {/* 添加工序：工序库在**另一个 tab** ⇒ 编辑器自带入口 */}
                                <div className="flex flex-wrap items-center gap-2">
                                  <select
                                    aria-label="从工序库添加工序"
                                    data-testid={`routing-add-select-${id}`}
                                    value={picked}
                                    onChange={(e) => setPicked(e.target.value)}
                                    className="h-9 min-w-56 flex-1 rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500"
                                  >
                                    <option value="">从工序库选择要添加的工序…</option>
                                    {libraryOps.map((op) => (
                                      <option key={op.id} value={op.name}>
                                        {op.name}
                                        {op.group ? `（${op.group}）` : ''}
                                      </option>
                                    ))}
                                  </select>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`routing-add-${id}`}
                                    disabled={!picked}
                                    onClick={() => {
                                      if (picked) addFromPalette(picked)
                                      setPicked('')
                                    }}
                                  >
                                    <Plus className="w-3.5 h-3.5 mr-1.5" />
                                    加入
                                  </Button>
                                </div>

                                {draftSteps.length === 0 ? (
                                  <p className="text-sm text-neutral-400" data-testid={`routing-draft-empty-${id}`}>
                                    主线为空：从上方「从工序库选择要添加的工序…」选一道点「加入」（必完工序是完工门槛，缺了会阻止打包）
                                  </p>
                                ) : (
                                  <ol className="space-y-1.5">
                                    {draftSteps.map((step, i) => (
                                      <li
                                        key={`${step.operation}-${i}`}
                                        className={cn(
                                          'flex flex-wrap items-center gap-2 rounded border px-2 py-1.5 text-sm',
                                          step.missing ? 'border-red-200 bg-red-50' : 'border-neutral-200 bg-neutral-50',
                                        )}
                                        data-testid={`routing-draft-step-${id}-${step.seq}`}
                                      >
                                        <span className="w-6 text-neutral-400">{step.seq}.</span>
                                        <span
                                          className="font-medium text-neutral-900"
                                          data-testid={`routing-draft-name-${id}-${step.seq}`}
                                        >
                                          {step.operation}
                                        </span>
                                        {step.resolved && (
                                          <span className="text-xs text-neutral-500">
                                            {step.group ?? '—'} · {step.unit ?? '—'} · {money(step.unit_price)}
                                          </span>
                                        )}
                                        {step.is_must_finish && <span className="text-xs text-amber-600">必完</span>}
                                        {step.missing && (
                                          <span
                                            className="text-xs text-red-600"
                                            data-testid={`routing-draft-missing-${id}-${step.seq}`}
                                          >
                                            工序库中不存在或已停用
                                          </span>
                                        )}
                                        <span className="ml-auto flex items-center gap-1">
                                          <button
                                            type="button"
                                            aria-label={`上移 ${step.operation}`}
                                            data-testid={`routing-draft-up-${id}-${step.seq}`}
                                            disabled={i === 0}
                                            onClick={() => move(i, -1)}
                                            className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                          >
                                            <ArrowUp className="w-3.5 h-3.5" />
                                          </button>
                                          <button
                                            type="button"
                                            aria-label={`下移 ${step.operation}`}
                                            data-testid={`routing-draft-down-${id}-${step.seq}`}
                                            disabled={i === draftSteps.length - 1}
                                            onClick={() => move(i, 1)}
                                            className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                          >
                                            <ArrowDown className="w-3.5 h-3.5" />
                                          </button>
                                          <button
                                            type="button"
                                            aria-label={`删除 ${step.operation}`}
                                            data-testid={`routing-draft-remove-${id}-${step.seq}`}
                                            onClick={() => removeAt(i)}
                                            className="rounded p-1 text-neutral-500 hover:bg-red-50 hover:text-red-600"
                                          >
                                            <Trash2 className="w-3.5 h-3.5" />
                                          </button>
                                        </span>
                                      </li>
                                    ))}
                                  </ol>
                                )}

                                <p className="text-xs text-neutral-500">
                                  从上方「添加工序」选择器里选（v1 不做拖拽编排，用上移/下移调顺序）。
                                </p>
                              </div>
                            ) : (
                              <ol className="mt-3 flex flex-wrap gap-1.5">
                                {mainline.map((name, i) => {
                                  const step = stepView(name, i)
                                  return (
                                    <li
                                      key={step.seq}
                                      data-testid={`routing-step-${id}-${step.seq}`}
                                      className={cn(
                                        'rounded border px-2 py-1 text-xs',
                                        step.missing
                                          ? 'border-red-200 bg-red-50 text-red-700'
                                          : 'border-neutral-200 bg-neutral-50 text-neutral-700',
                                      )}
                                    >
                                      <span className="mr-1 text-neutral-400">{step.seq}.</span>
                                      {step.operation}
                                      {step.resolved && (
                                        <span className="ml-1.5 text-neutral-400">
                                          {step.unit ?? '—'} · {money(step.unit_price)}
                                        </span>
                                      )}
                                      {step.is_must_finish && <span className="ml-1.5 text-amber-600">必完</span>}
                                      {step.missing && <span className="ml-1.5">工序库中不存在或已停用</span>}
                                    </li>
                                  )
                                })}
                              </ol>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </section>

                {/* 次区（折叠）：统一规则区 —— 工艺变体 ∪ 特殊选项（26 条） */}
                <CollapsibleSection
                  testId="route-rules"
                  title="条件工序规则"
                  hint="工艺 / 特殊选项触发时，往主线里插一道或删一道"
                  count={`共 ${rules.length} 条`}
                  open={rulesOpen}
                  onToggle={() => setRulesOpen((v) => !v)}
                >
                  <p className="mb-3 text-xs text-neutral-500">
                    触发键<strong>逐字取自后端</strong>（与订单里的工艺 / 选项名是同一个键）：错一个字就会查不到 ⇒
                    条件工序不加、计件系数退回 1.0。规则按优先级<strong>升序</strong>生效，顺序决定工序序列。
                  </p>
                  {rulesError ? (
                    <p
                      className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                      data-testid="route-rules-error"
                    >
                      {rulesError}
                    </p>
                  ) : rules.length === 0 ? (
                    <p className="py-6 text-center text-sm text-neutral-400" data-testid="route-rules-empty">
                      暂无条件工序规则 —— 订单的工艺与特殊选项都不需要额外增删工序
                    </p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">触发</th>
                            <th className="py-2 pr-4 font-medium">部位限定</th>
                            <th className="py-2 pr-4 font-medium">动作</th>
                            <th className="py-2 pr-4 font-medium">目标工序</th>
                            <th className="py-2 pr-4 font-medium">优先级</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rules.map((rule) => (
                            <tr
                              key={rule.id}
                              className="border-b border-neutral-100 last:border-0"
                              data-testid={`route-rule-${rule.id}`}
                            >
                              <td className="py-2.5 pr-4 text-neutral-900" data-testid={`route-rule-trigger-${rule.id}`}>
                                <span className="mr-1.5 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
                                  {TRIGGER_KIND_LABEL[rule.trigger_kind ?? ''] ?? rule.trigger_kind ?? '—'}
                                </span>
                                {rule.trigger_value ?? '—'}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-600" data-testid={`route-rule-position-${rule.id}`}>
                                {rule.position ?? '不限'}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-700" data-testid={`route-rule-action-${rule.id}`}>
                                {ruleActionText(rule)}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-900" data-testid={`route-rule-target-${rule.id}`}>
                                {rule.operation ?? '—'}
                              </td>
                              <td className="py-2.5 pr-4 text-neutral-500" data-testid={`route-rule-priority-${rule.id}`}>
                                {rule.priority ?? '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CollapsibleSection>
              </div>
            )}
          </div>
        </>
      )}

      {/* 新建路线：名字 + 适用帘种（默认三种帘种全适用；收窄适用范围就取消勾选） */}
      <Modal
        open={newRouteOpen}
        onClose={() => !busy && setNewRouteOpen(false)}
        title="新建路线"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setNewRouteOpen(false)}>
              取消
            </Button>
            <Button loading={busy} data-testid="routings-create-route-submit" onClick={createRoute}>
              创建
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            创建后直接进入主线编辑，请把工序排进去 —— 主线为空的路线被命中后一道工序都没有。
          </p>
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="new-route-name">
              路线名称（如 窗帘工序路线 / 纱帘专线）
            </label>
            <input
              id="new-route-name"
              data-testid="routings-create-name"
              className={inputCls}
              value={newRoute.name}
              onChange={(e) => setNewRoute({ ...newRoute, name: e.target.value })}
            />
          </div>
          <div>
            <span className="mb-1 block text-neutral-600">适用帘种（至少勾一个）</span>
            <div className="flex flex-wrap gap-3">
              {POSITION_DOMAIN.map((p) => (
                <label key={p} className="flex items-center gap-1.5 text-neutral-700">
                  <input
                    type="checkbox"
                    data-testid={`routings-create-position-${p}`}
                    checked={newRoute.positions.includes(p)}
                    onChange={(e) =>
                      setNewRoute((prev) => ({
                        ...prev,
                        positions: e.target.checked
                          ? POSITION_DOMAIN.filter((x) => x === p || prev.positions.includes(x))
                          : prev.positions.filter((x) => x !== p),
                      }))
                    }
                    className="h-4 w-4 accent-primary-600"
                  />
                  {p}
                </label>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      {/* 改名：**只改路线总名**（不给 mainline ⇒ 服务端不动序列） */}
      <Modal
        open={!!renameTarget}
        onClose={() => !busy && setRenameTarget(null)}
        title="更改路线名称"
        footer={null}
      >
        <div data-testid="routing-rename-modal" className="space-y-3 text-sm">
          <p className="text-neutral-600">
            只改这条路线的<strong>总名</strong>，主线工序与单价都不动（主线是计件工资与完工判定的输入）。
          </p>
          <input
            aria-label="路线名称"
            data-testid="routing-rename-input"
            className={inputCls}
            value={renameDraft}
            onChange={(e) => setRenameDraft(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              disabled={busy}
              data-testid="routing-rename-cancel"
              onClick={() => setRenameTarget(null)}
            >
              取消
            </Button>
            <Button loading={busy} data-testid="routing-rename-submit" onClick={submitRename}>
              保存
            </Button>
          </div>
        </div>
      </Modal>

      {/* 危险操作二次确认（删除 / 设为默认） */}
      <Modal
        open={!!confirmAction}
        onClose={() => !busy && setConfirmAction(null)}
        title={confirmAction?.kind === 'delete' ? '删除工艺路线' : '设为默认路线'}
        footer={null}
      >
        {confirmAction && (
          <div
            data-testid="routing-confirm-modal"
            data-kind={confirmAction.kind}
            data-routing={confirmAction.routing.id}
            className="space-y-3 text-sm"
          >
            {confirmAction.kind === 'delete' ? (
              <p className="text-neutral-600">
                将删除路线「{confirmAction.routing.name}」。删除后它立刻不再参与选路，
                匹配不到专属路线的订单会回落到默认路线。
              </p>
            ) : (
              <p className="text-neutral-600">
                将把「{confirmAction.routing.name}」设为默认路线（每租户恰一条，原默认路线会自动降级）。
                匹配不到专属路线的订单都会走它。
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" disabled={busy} data-testid="routing-confirm-cancel" onClick={() => setConfirmAction(null)}>
                取消
              </Button>
              <Button
                variant={confirmAction.kind === 'delete' ? 'danger' : 'primary'}
                loading={busy}
                data-testid={`routing-confirm-${confirmAction.kind}-${confirmAction.routing.id}`}
                onClick={runConfirm}
              >
                {confirmAction.kind === 'delete' ? '确认删除' : '设为默认'}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 新增工序 */}
      <Modal
        open={newOpOpen}
        onClose={() => !busy && setNewOpOpen(false)}
        title="新增工序"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setNewOpOpen(false)}>
              取消
            </Button>
            <Button loading={busy} data-testid="routings-create-operation-submit" onClick={createOperation}>
              保存
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            单价直接决定工人计件工资，请与车间核对后再填（调价只影响新报工，历史报工按当时价）。
          </p>
          {[
            { key: 'name', label: '工序名称', ph: '如 罗马帘-穿杆' },
            { key: 'group_name', label: '分组', ph: '裁剪 / 车位 / 后道 / 其他' },
            { key: 'unit', label: '单位', ph: '米 / 套 / 件 / 个 / 折' },
          ].map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-neutral-600" htmlFor={`new-op-${f.key}`}>
                {f.label}
              </label>
              <input
                id={`new-op-${f.key}`}
                data-testid={`routings-create-op-${f.key}`}
                className={inputCls}
                placeholder={f.ph}
                value={(newOp as Record<string, string>)[f.key]}
                onChange={(e) => setNewOp({ ...newOp, [f.key]: e.target.value })}
              />
            </div>
          ))}
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="new-op-unit_price">
              计件单价（元）
            </label>
            <input
              id="new-op-unit_price"
              inputMode="decimal"
              data-testid="routings-create-op-unit_price"
              className={inputCls}
              value={newOp.unit_price}
              onChange={(e) => setNewOp({ ...newOp, unit_price: e.target.value })}
            />
          </div>
        </div>
      </Modal>

      {/* 一键套用确认（批量写入工序/路线，防误触；照知识库页范式） */}
      <Modal open={!!confirmTemplate} onClose={() => setConfirmTemplate(null)} title="套用行业模板" footer={null}>
        <p className="text-sm">
          将把「{confirmTemplate?.name}」的预置工序与工艺路线复制到您的工序库；已存在的条目将自动跳过。
          套用出的单价是<strong>初始价（占位值）</strong>，请逐条确认后按实际工价修改 —— 改价只影响新报工，历史报工按当时价。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmTemplate(null)}>取消</Button>
          <Button data-testid="seed-template-apply-confirm" onClick={applyTemplate} disabled={!!applying}>
            {applying ? '套用中…' : '确定套用'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
