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
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import { productionApi } from '@/lib/api'
import { routingGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type {
  CatalogOperation,
  OperationsCatalog,
  ProductionScope,
  ProductionSeedTemplate,
  ProductionSource,
  RouteSignal,
  Routing,
  RoutingGaps,
  RoutingsResponse,
} from '@/types'

/**
 * 工艺配置 /production/routings（issue #4416：**工序库 + 工艺路线合并为单页**）
 *
 * 为什么合并：工序是**原子词汇**，路线是**用工序名拼出的有序序列** —— 后端护栏把这条先后关系钉死
 * （`ProductionRoutingCommandService.validateSequence`：「工序「X」在工序库中不存在或已停用：
 * **请先在「工序库」新增该工序」」；且「至少一道必完工序」是完工判定的唯一依据）。
 * 拆成两个菜单时，建路线发现缺工序要跳到另一个菜单去建（「新增工序」按钮此前在路线页、
 * 工序目录却在工序库页），且两页都在拉 `GET /routings` ⇒ 同一份数据两处渲染。
 *
 * 页面形态（**不做强制向导** —— 商家是回头改配置的，不是一次过）：
 * - **顶部就绪度检查器**：① 工序库就绪 → ② 路线就绪（至少一条且**序列非空**）→ ③ 缺口可见。
 *   把隐性依赖变成看得见的步骤；每步给「下一步」提示。
 * - **左栏 = 工序库**（搜索 + 分组 + 行内改单价/必完/作用域），**右栏 = 工艺路线**（缺口 + 列表 + 序列编辑）。
 *   编辑序列时点左栏「加入」即可把工序排进去 —— 同一页，不再跨菜单。
 * - **空壳路线显性化**：`POST /routings` 允许 `operations` 缺省（「空序列拒」护栏只拦 PUT），
 *   而 `ProductionOperationQueryService.findRouting` 对空序列路线**会正常命中**并返回
 *   `operation_count=0`、`missing_operations=[]` ⇒ `resolveRoute` 既不 fail-closed 也不报错
 *   ⇒ **该部位静默拿到 0 道工序**。本页把它标成「空壳 · 不可用」，并让新建路线**自动进入序列编辑**。
 * - **护栏就地预检**（缺必完工序 / 引用库中不存在的工序）：后端仍是唯一权威，前端只把
 *   「保存失败」提前成「看得见」。
 * - **信号映射收进折叠的「存量单兜底」**（#4385 裁定 R-f：路线键已改直读订单行 V63 列，
 *   信号表降级为存量单兜底）⇒ 文案按此改写，不再写成「命中优先于默认路线」的主配置入口。
 * - **行业模板仅在工序库为空时出现**：开租审批通过时 `RegistrationService.applyProductionSeedTemplate`
 *   已按 `tenant.industry` **自动套用**（收口 #4316）⇒ 常驻卡片会让商家误以为必须手点；
 *   保留它只为两条补救路径（开租套用失败被显式降级 / #4316 之前的存量租户库为空）。
 *
 * 契约（冻结，**不得自行发明端点/字段名**）：
 *   GET    /api/admin/production/routings            PUT  /routings/{id}  body {operations:[…]}
 *   POST   /api/admin/production/routings            body {curtain_type, craft, operations?}
 *   GET    /api/admin/production/operations-catalog  POST /production/operations
 *   PUT    /api/admin/production/operations/{id}     （改单价 / 必完 / 作用域）
 *   GET    /api/admin/production/routing-gaps
 *   GET|POST /api/admin/production/route-signals     PUT|DELETE /route-signals/{id}
 *   GET|POST /api/admin/production/seed-templates[/{id}/apply]
 *   —— 写端点权限 processing:manage（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线；
 * 领域模型与裁定：docs/design/position-instance-routing-model.md（R-c 作用域 / R-f 解绑加工项）。
 */

const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

/** 路线的唯一键（服务端唯一键 `(tenant_id, curtain_type, craft)`）—— 展示 key 与编辑标识共用一处 */
const routingKey = (r: Pick<Routing, 'curtain_type' | 'craft'>) => `${r.curtain_type}×${r.craft}`

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

/** 就绪度一步（把「工序 → 路线 → 缺口」的先后关系变成看得见的步骤） */
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

/** 序列里一道工序的展示口径：库中查得到就用库字段，否则用路线既有行，最后才留空 */
interface DraftStep {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  unit_price?: number | null
  is_must_finish?: boolean
  /** 库中查不到该工序（停用/被删）⇒ 该行标红并指名（保存必被后端拒，但页面要先让人看见） */
  missing: boolean
}

export default function ProcessConfigPage() {
  // ── 只读面 ──
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [gaps, setGaps] = useState<RoutingGaps | null>(null)
  const [signals, setSignals] = useState<RouteSignal[]>([])
  const [signalsError, setSignalsError] = useState('')
  const [templates, setTemplates] = useState<ProductionSeedTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  /** 工序库搜索（左栏是调色板：工序多起来必须能筛） */
  const [search, setSearch] = useState('')

  // ── 工序库行内编辑（单价；作用域/必完为即时写） ──
  const [editingOpId, setEditingOpId] = useState<string | number | null>(null)
  const [opDraft, setOpDraft] = useState('')
  const [opBusy, setOpBusy] = useState(false)

  // ── 序列编辑 ──
  const [editing, setEditing] = useState<Routing | null>(null)
  const [editingKey, setEditingKey] = useState('')
  const [draft, setDraft] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState<string[]>([])
  /** 本地即时错误（如空序列），与后端理由同区展示，形态一致 */
  const [localReason, setLocalReason] = useState('')

  // ── 弹窗 / 折叠区 ──
  const [newRouteOpen, setNewRouteOpen] = useState(false)
  const [newRoute, setNewRoute] = useState({ curtain_type: '', craft: '' })
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  const [signalForm, setSignalForm] = useState<{ id: number | null; signal: string; curtain_type: string; craft: string } | null>(
    null,
  )
  /** 信号映射区默认**收起**：它是存量单兜底层，不是主配置步骤（#4385 R-f） */
  const [signalsOpen, setSignalsOpen] = useState(false)
  const [confirmTemplate, setConfirmTemplate] = useState<ProductionSeedTemplate | null>(null)
  const [applying, setApplying] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    // 五条只读端点互不依赖：任一条失败不得把整页吞掉（页面不白屏，失败处给可读提示）
    const [routingsRes, catalogRes, gapsRes, signalsRes, templateRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getRoutingGaps(),
      productionApi.getRouteSignals(),
      productionApi.getSeedTemplates(),
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
    setGaps(gapsRes.status === 'fulfilled' ? gapsRes.value.data?.data ?? null : null)
    if (signalsRes.status === 'fulfilled') {
      setSignals(signalsRes.value.data?.data?.signals ?? [])
      setSignalsError('')
    } else {
      setSignals([])
      setSignalsError('信号映射加载失败，请稍后重试')
    }
    setTemplates(templateRes.status === 'fulfilled' ? templateRes.value.data?.data ?? [] : [])
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

  /** 左栏按搜索词过滤（分组内过滤；整组被滤空则不渲染该组） */
  const visibleGroups = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (catalog?.groups ?? [])
      .map((g) => ({ ...g, operations: g.operations.filter((op) => !q || op.name.toLowerCase().includes(q)) }))
      .filter((g) => g.operations.length > 0)
  }, [catalog, search])

  // ────────────────────────── 就绪度（先后依赖显性化） ──────────────────────────

  const operationsReady = (catalog?.total ?? 0) > 0
  const routeList = useMemo(() => routings?.routings ?? [], [routings])
  const emptyShells = useMemo(() => routeList.filter((r) => (r.operation_count ?? 0) === 0), [routeList])
  const routingsReady = routeList.length > 0 && emptyShells.length === 0
  const pendingOps = useMemo(() => (gaps?.unrouted_operations ?? []).filter((o) => o.pending_confirmation), [gaps])
  const realUnrouted = useMemo(() => (gaps?.unrouted_operations ?? []).filter((o) => !o.pending_confirmation), [gaps])
  const signalGaps = gaps?.signal_keys_without_route ?? []
  const gapsState: 'done' | 'todo' | 'unknown' = gaps == null ? 'unknown' : realUnrouted.length === 0 && signalGaps.length === 0 ? 'done' : 'todo'

  const routingsHint =
    routeList.length === 0
      ? '下一步：点右上「新建路线」建一条（部位 × 工艺 → 工序序列）。'
      : emptyShells.length > 0
        ? `有 ${emptyShells.length} 条「空壳」路线（序列为空）：该部位会静默拿到 0 道工序，请点「编辑序列」把工序排进去。`
        : ''
  const gapsHint =
    `有 ${realUnrouted.length} 道工序未进任何路线、${signalGaps.length} 个信号组合没有对应路线。` +
    (pendingOps.length > 0 ? `（另有 ${pendingOps.length} 道「有意挂起」等客户确认，不计入待处理）` : '')

  // ────────────────────────── 序列编辑 ──────────────────────────

  const openEditor = (routing: Routing) => {
    setEditing(routing)
    setEditingKey(routingKey(routing))
    setDraft((routing.operations ?? []).map((s) => s.operation))
    setReasons([])
    setLocalReason('')
  }

  const closeEditor = () => {
    setEditing(null)
    setEditingKey('')
    setDraft([])
    setReasons([])
    setLocalReason('')
  }

  /** draft 的有序行（seq 归一为 1..N；字段优先取工序库口径，库中缺失则回落路线既有行并**标记 missing**） */
  const draftSteps: DraftStep[] = useMemo(() => {
    const fromRouting = new Map((editing?.operations ?? []).map((s) => [s.operation, s]))
    return draft.map((name, i) => {
      const lib = libraryByName.get(name)
      const prev = fromRouting.get(name)
      return {
        seq: i + 1,
        operation: name,
        group: lib?.group ?? prev?.group ?? null,
        unit: lib?.unit ?? prev?.unit ?? null,
        unit_price: lib?.unit_price ?? prev?.unit_price ?? null,
        is_must_finish: lib?.is_must_finish ?? prev?.is_must_finish,
        missing: !lib,
      }
    })
  }, [draft, editing, libraryByName])

  const missingSteps = draftSteps.filter((s) => s.missing)
  /** 就地预检：一道必完工序都没有 ⇒ 这张单**永远完不了工**（必完全绿是完工判定的唯一依据） */
  const lacksMustFinish = draftSteps.length > 0 && !draftSteps.some((s) => s.is_must_finish)

  /** 从左栏调色板把工序加进**正在编辑**的路线（未进入编辑态时按钮禁用，避免误加进别的路线） */
  const addFromPalette = (name: string) => {
    if (!editingKey) return
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

  /** 保存序列：空序列本地拦（不发无效请求）；其余护栏理由由后端逐条返回 */
  const saveSequence = async () => {
    if (!editing) return
    if (draft.length === 0) {
      setLocalReason('序列不能为空：至少保留一道工序')
      setReasons([])
      return
    }
    if (!editing.id) {
      setReasons(['该路线缺少 id，无法保存（请联系管理员核对路线数据）'])
      return
    }
    setSaving(true)
    setReasons([])
    setLocalReason('')
    try {
      await productionApi.updateRoutingSequence(editing.id, { operations: draft })
      toast.success('路线序列已保存')
      closeEditor()
      await load()
    } catch (e) {
      console.error(e)
      setReasons(routingGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('路线序列保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 新建路线：部位 + 工艺 → 建壳后**立刻进入序列编辑**（消灭「建壳了但没排序」的静默态） */
  const createRoute = async () => {
    const curtain_type = newRoute.curtain_type.trim()
    const craft = newRoute.craft.trim()
    if (!curtain_type || !craft) {
      toast.error('请填写部位与工艺')
      return
    }
    setBusy(true)
    try {
      const res = await productionApi.createRouting({ curtain_type, craft, operations: [] })
      const created = res.data?.data as Routing | undefined
      toast.success(`已新建路线 ${curtain_type} × ${craft}，请把工序排进去`)
      setNewRouteOpen(false)
      setNewRoute({ curtain_type: '', craft: '' })
      await load()
      // 服务端回显的路线对象（含 id / operations）—— 没有它就退化成「建了个空壳但没人知道」
      if (created?.curtain_type && created?.craft) {
        openEditor({ ...created, operations: created.operations ?? [] })
      }
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('新建路线失败')
    } finally {
      setBusy(false)
    }
  }

  /** 新增工序：建新路线时必须有工序可选，否则商家无处可建（本页左栏顶部入口） */
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

  /** 信号映射保存：id 为空 = 新增（POST），有 id = 改（PUT） */
  const saveSignal = async () => {
    if (!signalForm) return
    const signal = signalForm.signal.trim()
    const curtain_type = signalForm.curtain_type.trim()
    const craft = signalForm.craft.trim()
    if (!signal || !curtain_type || !craft) {
      toast.error('信号、部位、工艺都要填')
      return
    }
    setBusy(true)
    try {
      const body = { signal, curtain_type, craft }
      if (signalForm.id == null) await productionApi.createRouteSignal(body)
      else await productionApi.updateRouteSignal(signalForm.id, body)
      toast.success(signalForm.id == null ? '信号映射已新增' : '信号映射已更新')
      setSignalForm(null)
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('信号映射保存失败')
    } finally {
      setBusy(false)
    }
  }

  /** 删除信号映射（先确认，再删；成功后重新拉取，避免本地猜测） */
  const deleteSignal = async (s: RouteSignal) => {
    if (!window.confirm(`确认删除信号「${s.signal}」的映射吗？删除后该信号将回落到默认路线。`)) return
    setBusy(true)
    try {
      await productionApi.deleteRouteSignal(s.id)
      toast.success('信号映射已删除')
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('删除信号映射失败')
    } finally {
      setBusy(false)
    }
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
            工序库（词汇表）→ 工艺路线（用工序拼出的序列）。路线是计件工资与完工判定的唯一输入，改前请核对单位与单价
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
          {/* ── 就绪度：① 工序库 → ② 工艺路线 → ③ 缺口（先后依赖显性化） ── */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="process-readiness">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">配置就绪度</h2>
              <span className="text-sm text-neutral-500">
                按顺序配：先有工序，才能排路线；路线是加工单能不能生成的唯一输入
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
                testId="readiness-step-gaps"
                index={3}
                label="缺口"
                state={gapsState}
                hint={gapsState === 'unknown' ? '缺口数据加载失败，请刷新重试。' : gapsHint}
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

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
            {/* ══════════════ 左栏：工序库（词汇表 / 调色板） ══════════════ */}
            <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="operations-catalog">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-baseline gap-2">
                  <h2 className="text-base font-medium text-neutral-900">工序库</h2>
                  <span className="text-sm text-neutral-500">
                    共 <span data-testid="operations-catalog-total">{total}</span> 道工序
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
                工序分组 · 作用域（部位级/套级） · 计件单价 · 必完开关；调价只影响新报工（历史报工按当时价）。
                {editingKey ? (
                  <span className="text-primary-700"> 正在编辑「{editingKey}」—— 点行末「加入」把工序排进去。</span>
                ) : (
                  <span> 先在右侧点「编辑序列」，再从这里把工序加进去。</span>
                )}
              </p>

              {catalogError ? (
                <p
                  className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                  data-testid="operations-catalog-error"
                >
                  {catalogError}
                </p>
              ) : visibleGroups.length === 0 ? (
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
                              <th className="py-2 font-medium">加入路线</th>
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
                                    onChange={(e) => submitOperation(op.id, { scope: e.target.value as ProductionScope })}
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
                                <td className="py-2.5">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`operation-add-${op.id}`}
                                    disabled={!editingKey}
                                    onClick={() => addFromPalette(op.name)}
                                    title={
                                      editingKey ? `加入「${editingKey}」的序列` : '先在右侧点「编辑序列」，再从这里加入'
                                    }
                                  >
                                    <Plus className="w-3.5 h-3.5" />
                                  </Button>
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
            </section>

            {/* ══════════════ 右栏：工艺路线（缺口 + 列表 + 序列编辑） ══════════════ */}
            <div className="space-y-4">
              {/* ── 缺口区：**有意挂起**（等客户确认）与**真缺口**分开渲染 ── */}
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-5" data-testid="routings-gaps">
                <div className="mb-3 flex flex-wrap items-baseline gap-2">
                  <h2 className="text-base font-medium text-neutral-900">缺口</h2>
                  <span className="text-sm text-neutral-600">
                    有 <span data-testid="routings-gap-unrouted-count">{realUnrouted.length}</span> 道工序还没有进任何路线
                  </span>
                </div>

                {gaps == null ? (
                  <p className="text-sm text-neutral-500" data-testid="routings-gaps-unavailable">
                    缺口数据加载失败，请刷新重试（有工序没进路线时，该工序不会出现在任何加工单里）
                  </p>
                ) : (
                  <div className="space-y-3">
                    {realUnrouted.length === 0 ? (
                      <p className="text-sm text-neutral-500" data-testid="routings-gaps-empty">
                        所有活跃工序都已进入路线
                      </p>
                    ) : (
                      <ul className="space-y-1" data-testid="routings-gap-unrouted-list">
                        {realUnrouted.map((op) => (
                          <li
                            key={op.name}
                            className="flex flex-wrap items-baseline gap-2 text-sm text-neutral-700"
                            data-testid={`routings-gap-unrouted-${op.name}`}
                          >
                            <span className="font-medium text-neutral-900">{op.name}</span>
                            <span className="text-neutral-500">
                              {op.group_name ?? '—'} · {op.unit ?? '—'} · {money(op.unit_price)}
                            </span>
                            <span className="text-xs text-amber-700">未进任何路线，加工单不会出现该工序</span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {/* 有意挂起：后端明写「不要让商家/前端把它们读成「系统漏了」」⇒ 单列一块 */}
                    {pendingOps.length > 0 && (
                      <div className="border-t border-amber-200 pt-3" data-testid="routings-gap-pending">
                        <p className="text-sm text-neutral-600">
                          有意挂起 · 等客户确认（
                          <span data-testid="routings-gap-pending-count">{pendingOps.length}</span>
                          道）：不是系统漏了 —— 猜出来的工序与单价会直接算成工人工资，故不猜
                        </p>
                        <ul className="mt-1 space-y-0.5">
                          {pendingOps.map((op) => (
                            <li
                              key={op.name}
                              className="flex flex-wrap items-baseline gap-2 text-sm text-neutral-600"
                              data-testid={`routings-gap-pending-${op.name}`}
                            >
                              <span className="font-medium text-neutral-800">{op.name}</span>
                              <span className="text-neutral-500">
                                {op.group_name ?? '—'} · {op.unit ?? '—'} · {money(op.unit_price)}
                              </span>
                              <span className="text-xs text-neutral-500">等客户确认（#4261 提问清单）</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="border-t border-amber-200 pt-3" data-testid="routings-gap-signals">
                      <p className="text-sm text-neutral-600">没有路线的信号组合（这些信号目前会回落到默认路线）：</p>
                      {signalGaps.length === 0 ? (
                        <p className="mt-1 text-sm text-neutral-500" data-testid="routings-gap-signals-empty">
                          无
                        </p>
                      ) : (
                        <ul className="mt-1 flex flex-wrap gap-1.5">
                          {signalGaps.map((k) => (
                            <li
                              key={`${k.curtain_type}|${k.craft}`}
                              data-testid={`routings-gap-signal-${k.curtain_type}-${k.craft}`}
                              className="rounded border border-amber-300 bg-white px-2 py-0.5 text-xs text-amber-800"
                            >
                              {k.curtain_type} × {k.craft}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* ── 路线列表 ── */}
              <div className="rounded-lg border border-neutral-200 bg-white p-5">
                <div className="mb-3 flex items-baseline gap-2">
                  <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
                  <span className="text-sm text-neutral-500">
                    共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条
                  </span>
                </div>

                {routeList.length === 0 ? (
                  <p className="py-8 text-center text-sm text-neutral-400" data-testid="routings-empty">
                    暂无工艺路线，点右上「新建路线」开始
                  </p>
                ) : (
                  <div className="space-y-4">
                    {routeList.map((routing) => {
                      const key = routingKey(routing)
                      const isEditing = !!editingKey && editingKey === key
                      const isEmptyShell = (routing.operation_count ?? 0) === 0
                      return (
                        <div key={key} className="rounded-lg border border-neutral-200 p-4" data-testid={`routing-${key}`}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-baseline gap-2">
                              <span className="text-sm font-medium text-neutral-900" data-testid={`routing-title-${key}`}>
                                {routing.curtain_type} × {routing.craft}
                              </span>
                              <span className="text-xs text-neutral-400">{routing.operation_count} 道工序</span>
                              {isEmptyShell && (
                                <span
                                  data-testid={`routing-empty-shell-${key}`}
                                  title="空壳路线会被正常命中并返回 0 道工序 —— 既不报错也不 fail-closed，该部位会静默拿到 0 道工序"
                                  className="rounded bg-red-50 px-1.5 py-0.5 text-[11px] text-red-600"
                                >
                                  空壳 · 不可用
                                </span>
                              )}
                              <SourceBadge source={routing.source} testId={`routing-source-${key}`} />
                            </div>
                            {isEditing ? (
                              <div className="flex items-center gap-2">
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  data-testid={`routing-cancel-${key}`}
                                  disabled={saving}
                                  onClick={closeEditor}
                                >
                                  取消
                                </Button>
                                <Button size="sm" data-testid={`routing-save-${key}`} loading={saving} onClick={saveSequence}>
                                  保存
                                </Button>
                              </div>
                            ) : (
                              <Button
                                variant="secondary"
                                size="sm"
                                data-testid={`routing-edit-${key}`}
                                onClick={() => openEditor(routing)}
                              >
                                <Pencil className="w-3.5 h-3.5 mr-1.5" />
                                编辑序列
                              </Button>
                            )}
                          </div>

                          {/* 保存被拒：逐条展示理由（空序列 / 工序不存在 / 重复 / 缺必完工序） */}
                          {isEditing && (localReason || reasons.length > 0) && (
                            <div
                              className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                              data-testid={`routing-error-${key}`}
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
                                  data-testid={`routing-precheck-${key}`}
                                >
                                  这条路线一道「必完」工序都没有 —— 必完工序全绿是完工判定的唯一依据，
                                  缺了这张单永远完不了工。请至少把一道关键工序标为「必完」。
                                </p>
                              )}
                              {missingSteps.length > 0 && (
                                <p
                                  className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                                  data-testid={`routing-precheck-missing-${key}`}
                                >
                                  有 {missingSteps.length} 道工序在工序库中不存在或已停用（
                                  {missingSteps.map((s) => s.operation).join('、')}
                                  ）—— 保存会被拒，请先到左栏「新增工序」补上，或把它从序列里移除。
                                </p>
                              )}

                              {draftSteps.length === 0 ? (
                                <p className="text-sm text-neutral-400" data-testid={`routing-draft-empty-${key}`}>
                                  序列为空：从左侧工序库点「加入」把工序排进来（必完工序是完工门槛，缺了会阻止打包）
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
                                      data-testid={`routing-draft-step-${key}-${step.seq}`}
                                    >
                                      <span className="w-6 text-neutral-400">{step.seq}.</span>
                                      <span
                                        className="font-medium text-neutral-900"
                                        data-testid={`routing-draft-name-${key}-${step.seq}`}
                                      >
                                        {step.operation}
                                      </span>
                                      <span className="text-xs text-neutral-500">
                                        {step.group ?? '—'} · {step.unit ?? '—'} · {money(step.unit_price)}
                                      </span>
                                      {step.is_must_finish && <span className="text-xs text-amber-600">必完</span>}
                                      {step.missing && (
                                        <span
                                          className="text-xs text-red-600"
                                          data-testid={`routing-draft-missing-${key}-${step.seq}`}
                                        >
                                          工序库中不存在或已停用
                                        </span>
                                      )}
                                      <span className="ml-auto flex items-center gap-1">
                                        <button
                                          type="button"
                                          aria-label={`上移 ${step.operation}`}
                                          data-testid={`routing-draft-up-${key}-${step.seq}`}
                                          disabled={i === 0}
                                          onClick={() => move(i, -1)}
                                          className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                        >
                                          <ArrowUp className="w-3.5 h-3.5" />
                                        </button>
                                        <button
                                          type="button"
                                          aria-label={`下移 ${step.operation}`}
                                          data-testid={`routing-draft-down-${key}-${step.seq}`}
                                          disabled={i === draftSteps.length - 1}
                                          onClick={() => move(i, 1)}
                                          className="rounded p-1 text-neutral-500 hover:bg-neutral-200 disabled:opacity-30"
                                        >
                                          <ArrowDown className="w-3.5 h-3.5" />
                                        </button>
                                        <button
                                          type="button"
                                          aria-label={`删除 ${step.operation}`}
                                          data-testid={`routing-draft-remove-${key}-${step.seq}`}
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
                                从左栏工序库点「加入」添加工序（v1 不做拖拽编排，用上移/下移调顺序）。
                              </p>
                            </div>
                          ) : (
                            <ol className="mt-3 flex flex-wrap gap-1.5">
                              {(routing.operations ?? []).map((step) => (
                                <li
                                  key={step.seq}
                                  data-testid={`routing-step-${key}-${step.seq}`}
                                  className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-700"
                                >
                                  <span className="mr-1 text-neutral-400">{step.seq}.</span>
                                  {step.operation}
                                  <span className="ml-1.5 text-neutral-400">
                                    {step.unit ?? '—'} · {money(step.unit_price)}
                                  </span>
                                  {step.is_must_finish && <span className="ml-1.5 text-amber-600">必完</span>}
                                </li>
                              ))}
                            </ol>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* ── 存量单兜底：信号映射（#4385 裁定 R-f 已降级，默认收起） ── */}
              <div className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="route-signals-section">
                <button
                  type="button"
                  data-testid="route-signals-toggle"
                  aria-expanded={signalsOpen}
                  onClick={() => setSignalsOpen((v) => !v)}
                  className="flex w-full items-center gap-2 text-left"
                >
                  {signalsOpen ? (
                    <ChevronDown className="w-4 h-4 text-neutral-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-neutral-500" />
                  )}
                  <span className="text-base font-medium text-neutral-900">存量单兜底 · 信号映射</span>
                  <span className="text-sm text-neutral-500">{signals.length} 条 —— 仅在订单没有填部位/工艺时才用</span>
                </button>

                {signalsOpen && (
                  <div className="mt-3" data-testid="route-signals-body">
                    <p className="mb-3 text-xs text-neutral-500">
                      新订单的部位/工艺由订单行直接给出（V63 列），路线按它直读，不查这里的表。
                      只有存量单或没填部位/工艺的单才会落到这一层：按「加工项名 → 加工项选项 → 商品名 → 销售方式」
                      的顺序做关键词匹配，命中即取这里的部位/工艺；都不命中才回落默认路线。
                      商家自定义的加工项名会参与匹配 —— 加自定义加工项后请回来核对这里。
                    </p>
                    <div className="mb-3 flex justify-end">
                      <Button
                        size="sm"
                        data-testid="route-signal-new"
                        onClick={() => setSignalForm({ id: null, signal: '', curtain_type: '', craft: '' })}
                      >
                        <Plus className="w-4 h-4 mr-1.5" />
                        新增映射
                      </Button>
                    </div>

                    {signalsError && (
                      <p
                        className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                        data-testid="route-signals-error"
                      >
                        {signalsError}
                      </p>
                    )}

                    {signals.length === 0 ? (
                      <p className="py-6 text-center text-sm text-neutral-400" data-testid="route-signals-empty">
                        暂无信号映射（没填部位/工艺的订单将回落到默认路线）
                      </p>
                    ) : (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                            <th className="py-2 pr-4 font-medium">信号</th>
                            <th className="py-2 pr-4 font-medium">部位</th>
                            <th className="py-2 pr-4 font-medium">工艺</th>
                            <th className="py-2 font-medium">操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {signals.map((s) => (
                            <tr key={s.id} className="border-b border-neutral-100 last:border-0" data-testid={`route-signal-${s.id}`}>
                              <td className="py-2.5 pr-4 text-neutral-900">{s.signal}</td>
                              <td className="py-2.5 pr-4 text-neutral-600">{s.curtain_type}</td>
                              <td className="py-2.5 pr-4 text-neutral-600">{s.craft}</td>
                              <td className="py-2.5">
                                <div className="flex items-center gap-2">
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    data-testid={`route-signal-edit-${s.id}`}
                                    onClick={() =>
                                      setSignalForm({
                                        id: s.id,
                                        signal: s.signal,
                                        curtain_type: s.curtain_type,
                                        craft: s.craft,
                                      })
                                    }
                                  >
                                    编辑
                                  </Button>
                                  <Button
                                    variant="danger"
                                    size="sm"
                                    data-testid={`route-signal-delete-${s.id}`}
                                    onClick={() => deleteSignal(s)}
                                  >
                                    删除
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* 新建路线 */}
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
            创建后直接进入序列编辑，请把工序从左栏排进来 —— 序列为空的路线会被加工单正常命中并返回 0 道工序。
          </p>
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="new-route-curtain">
              部位（帘种，如 布帘 / 纱帘 / 罗马帘）
            </label>
            <input
              id="new-route-curtain"
              data-testid="routings-create-curtain-type"
              className={inputCls}
              value={newRoute.curtain_type}
              onChange={(e) => setNewRoute({ ...newRoute, curtain_type: e.target.value })}
            />
          </div>
          <div>
            <label className="mb-1 block text-neutral-600" htmlFor="new-route-craft">
              工艺（如 韩褶 / 打孔 / 四爪钩）
            </label>
            <input
              id="new-route-craft"
              data-testid="routings-create-craft"
              className={inputCls}
              value={newRoute.craft}
              onChange={(e) => setNewRoute({ ...newRoute, craft: e.target.value })}
            />
          </div>
        </div>
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

      {/* 信号映射 新增/编辑 */}
      <Modal
        open={!!signalForm}
        onClose={() => !busy && setSignalForm(null)}
        title={signalForm?.id == null ? '新增信号映射' : '编辑信号映射'}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setSignalForm(null)}>
              取消
            </Button>
            <Button loading={busy} data-testid="route-signal-submit" onClick={saveSignal}>
              保存
            </Button>
          </div>
        }
      >
        {signalForm && (
          <div className="space-y-3 text-sm">
            <p className="text-neutral-600">
              只在订单没有填部位/工艺时兜底：按「加工项名 → 加工项选项 → 商品名 → 销售方式」的顺序匹配关键词，
              命中即取这里的部位/工艺。
            </p>
            {[
              { key: 'signal', label: '信号（关键词）', ph: '如 罗马帘' },
              { key: 'curtain_type', label: '部位', ph: '如 罗马帘' },
              { key: 'craft', label: '工艺', ph: '如 韩褶' },
            ].map((f) => (
              <div key={f.key}>
                <label className="mb-1 block text-neutral-600" htmlFor={`signal-${f.key}`}>
                  {f.label}
                </label>
                <input
                  id={`signal-${f.key}`}
                  data-testid={`route-signal-${f.key}`}
                  className={inputCls}
                  placeholder={f.ph}
                  value={(signalForm as unknown as Record<string, string>)[f.key]}
                  onChange={(e) => setSignalForm({ ...signalForm, [f.key]: e.target.value })}
                />
              </div>
            ))}
          </div>
        )}
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
