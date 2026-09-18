'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowDown, ArrowUp, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { isErrorToastShown } from '@/lib/api-error'
import { productionApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  CatalogOperation,
  OperationsCatalog,
  RouteSignal,
  Routing,
  RoutingGaps,
  RoutingsResponse,
} from '@/types'

/**
 * 工艺路线 /production/routings（issue #4307，前端半边；契约所有者 = 后端 4308）
 *
 * 用户面（本页是「企业设置工艺路线自定义」的唯一可操作入口）：
 * - 路线列表：部位 × 工艺 → 有序工序序列（含分组/单位/单价/必完标记），只读总览；
 * - 序列编辑：从**工序库**选工序 → 上移/下移/删除 → 保存（PUT /production/routings/{id}）；
 *   v1 不做拖拽编排（冻结：有序列表增删 + 上下移）。
 * - **护栏理由逐条展示**：保存被拒时不得只弹「保存失败」——后端返回的每一条理由都要露面
 *   （空序列 / 工序不存在 / 重复 / 缺必完工序 / seq 归一 / 权限）；客户端可自行判定的
 *   （空序列）本地先拦，不发无效请求。
 * - 缺口区（GET /production/routing-gaps）：①有工序但未进任何路线 ②没有路线的信号组合 ——
 *   此前只活在代码注释里（真值源 §3 的 4 道「待客户确认」工序 + 罗马帘缺口）。
 * - 新建路线（部位 + 工艺 + 初始序列）/ 新增工序（POST /production/operations）/ 信号映射增删改。
 *
 * 契约（冻结，见 issue #4308；**不得自行发明端点/字段名**）：
 *   GET    /api/admin/production/routings
 *   PUT    /api/admin/production/routings/{id}          body {operations: ["精裁-布", ...]}
 *   GET    /api/admin/production/operations-catalog
 *   POST   /api/admin/production/operations             body {name, group_name, unit, unit_price, position}
 *   GET    /api/admin/production/routing-gaps
 *   POST   /api/admin/production/route-signals          body {signal, curtain_type, craft, priority}
 *   PUT    /api/admin/production/route-signals/{id}
 *   DELETE /api/admin/production/route-signals/{id}
 *   —— 写端点权限 processing:manage（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §3 工艺路线。
 */

const money = (v?: number | null) => `¥${Number(v ?? 0).toFixed(2)}`

const inputCls =
  'h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400'

/**
 * 护栏理由 → 逐条可读文案（issue #4308 的护栏清单：空序列 / 工序不存在 / 重复 / 缺必完工序 /
 * 权限）。识别不了的原样透出 —— **绝不吞掉后端理由**（吞掉就等于回到「只弹保存失败」）。
 */
export function describeRoutingGuard(raw: string): string {
  const s = (raw || '').trim()
  if (!s) return '保存失败'
  const dup = s.match(/重复|duplicate/i)
  if (dup) return `工序重复：${s}`
  if (/不存在/.test(s) || /不在/.test(s) || /not[_ ]?found/i.test(s)) return `工序不存在：${s}`
  if (/必完/.test(s)) return `缺少必完工序：${s}`
  if (/空|empty/i.test(s)) return `序列不能为空：${s}`
  if (/权限|forbidden|denied/i.test(s)) return `没有工艺路线管理权限：${s}`
  return s
}

/**
 * 从失败的请求里取**逐条**护栏理由：优先用后端新增的结构化清单 `error_messages`，
 * 退化到单条 `error` / Error.message。字段名口径见 issue #4308（本单不发明字段）。
 */
export function routingGuardReasons(error: unknown): string[] {
  const e = error as
    | { response?: { data?: { error_messages?: unknown; error?: unknown } }; message?: string }
    | null
    | undefined
  const body = e?.response?.data
  if (Array.isArray(body?.error_messages) && body.error_messages.length > 0) {
    return body.error_messages.map((r) => describeRoutingGuard(String(r)))
  }
  if (typeof body?.error_messages === 'string' && body.error_messages) {
    return [describeRoutingGuard(body.error_messages)]
  }
  if (typeof body?.error === 'string' && body.error) return [describeRoutingGuard(body.error)]
  if (typeof e?.message === 'string' && e.message) return [describeRoutingGuard(e.message)]
  return ['保存失败，请稍后重试']
}

/** 序列里一道工序的展示口径：库中查得到就用库字段，否则用路线既有行，最后才留空 */
interface DraftStep {
  seq: number
  operation: string
  group?: string | null
  unit?: string | null
  unit_price?: number | null
  is_must_finish?: boolean
}

export default function RoutingsPage() {
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [gaps, setGaps] = useState<RoutingGaps | null>(null)
  const [signals, setSignals] = useState<RouteSignal[]>([])
  const [signalsError, setSignalsError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  /** 序列编辑：当前编辑的路线（null = 未进入编辑）；draft = 待保存的有序工序名 */
  const [editing, setEditing] = useState<Routing | null>(null)
  const [draft, setDraft] = useState<string[]>([])
  const [picked, setPicked] = useState('')
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState<string[]>([])
  /** 本地即时错误（如空序列），与后端理由同区展示，形态一致 */
  const [localReason, setLocalReason] = useState('')

  /** 新建路线 / 新增工序 / 信号映射 弹窗 */
  const [newRouteOpen, setNewRouteOpen] = useState(false)
  const [newRoute, setNewRoute] = useState({ curtain_type: '', craft: '' })
  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  const [signalForm, setSignalForm] = useState<{ id: number | null; signal: string; curtain_type: string; craft: string } | null>(
    null,
  )
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const [routingsRes, catalogRes, gapsRes, signalsRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getRoutingGaps(),
      productionApi.getRouteSignals(),
    ])
    if (routingsRes.status === 'fulfilled') {
      setRoutings(routingsRes.value.data?.data ?? null)
    } else {
      setRoutings(null)
      setError('工艺路线加载失败，请稍后重试')
    }
    // 工序库 / 缺口 / 信号互不依赖：任一条失败不得把整页吞掉（页面不白屏，失败处给可读提示）
    setCatalog(catalogRes.status === 'fulfilled' ? catalogRes.value.data?.data ?? null : null)
    setGaps(gapsRes.status === 'fulfilled' ? gapsRes.value.data?.data ?? null : null)
    if (signalsRes.status === 'fulfilled') {
      setSignals(signalsRes.value.data?.data?.signals ?? [])
      setSignalsError('')
    } else {
      setSignals([])
      setSignalsError('信号映射加载失败，请稍后重试')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const libraryOps = useMemo(
    () => (catalog?.groups ?? []).flatMap((g) => g.operations),
    [catalog],
  )
  const libraryByName = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(op.name, op))
    return m
  }, [libraryOps])

  const openEditor = (routing: Routing) => {
    setEditing(routing)
    setDraft((routing.operations ?? []).map((s) => s.operation))
    setPicked('')
    setReasons([])
    setLocalReason('')
  }

  const closeEditor = () => {
    setEditing(null)
    setDraft([])
    setReasons([])
    setLocalReason('')
  }

  /** draft 的有序行（seq 归一为 1..N；字段优先取工序库口径） */
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
      }
    })
  }, [draft, editing, libraryByName])

  const addToDraft = () => {
    if (!picked) return
    setDraft((d) => (d.includes(picked) ? d : [...d, picked]))
    setPicked('')
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

  /** 新建路线：部位 + 工艺 → 建壳后立刻进入序列编辑（初版序列由商家自行排） */
  const createRoute = async () => {
    const curtain_type = newRoute.curtain_type.trim()
    const craft = newRoute.craft.trim()
    if (!curtain_type || !craft) {
      toast.error('请填写部位与工艺')
      return
    }
    setBusy(true)
    try {
      await productionApi.createRouting({ curtain_type, craft, operations: [] })
      toast.success(`已新建路线 ${curtain_type} × ${craft}`)
      setNewRouteOpen(false)
      setNewRoute({ curtain_type: '', craft: '' })
      await load()
    } catch (e) {
      console.error(e)
      if (!isErrorToastShown(e)) toast.error('新建路线失败')
    } finally {
      setBusy(false)
    }
  }

  /** 新增工序：建新路线时必须有工序可选，否则商家无处可建 */
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

  const unrouted = gaps?.unrouted_operations ?? []
  const catalogGroups = catalog?.groups ?? []

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">工艺路线</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            部位 × 工艺 → 工序序列。路线是计件工资与完工判定的唯一输入，改前请核对单位与单价
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
          {/* ── 缺口区：有工序但未进任何路线 + 没有路线的信号组合 ── */}
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-5" data-testid="routings-gaps">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">缺口</h2>
              <span className="text-sm text-neutral-600">
                有 <span data-testid="routings-gap-unrouted-count">{unrouted.length}</span> 道工序还没有进任何路线
              </span>
            </div>

            {gaps == null ? (
              <p className="text-sm text-neutral-500" data-testid="routings-gaps-unavailable">
                缺口数据加载失败，请刷新重试（有工序没进路线时，该工序不会出现在任何加工单里）
              </p>
            ) : (
              <div className="space-y-3">
                {unrouted.length === 0 ? (
                  <p className="text-sm text-neutral-500" data-testid="routings-gaps-empty">
                    所有活跃工序都已进入路线
                  </p>
                ) : (
                  <ul className="space-y-1" data-testid="routings-gap-unrouted-list">
                    {unrouted.map((op) => (
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

                <div className="border-t border-amber-200 pt-3" data-testid="routings-gap-signals">
                  <p className="text-sm text-neutral-600">
                    没有路线的信号组合（这些信号目前会回落到默认路线）：
                  </p>
                  {(gaps.signal_keys_without_route ?? []).length === 0 ? (
                    <p className="mt-1 text-sm text-neutral-500" data-testid="routings-gap-signals-empty">
                      无
                    </p>
                  ) : (
                    <ul className="mt-1 flex flex-wrap gap-1.5">
                      {(gaps.signal_keys_without_route ?? []).map((k) => (
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

            {(routings?.routings ?? []).length === 0 ? (
              <p className="py-8 text-center text-sm text-neutral-400" data-testid="routings-empty">
                暂无工艺路线，点右上「新建路线」开始
              </p>
            ) : (
              <div className="space-y-4">
                {(routings?.routings ?? []).map((routing) => {
                  const key = `${routing.curtain_type}×${routing.craft}`
                  const isEditing = editing === routing
                  return (
                    <div key={key} className="rounded-lg border border-neutral-200 p-4" data-testid={`routing-${key}`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-baseline gap-2">
                          <span className="text-sm font-medium text-neutral-900" data-testid={`routing-title-${key}`}>
                            {routing.curtain_type} × {routing.craft}
                          </span>
                          <span className="text-xs text-neutral-400">{routing.operation_count} 道工序</span>
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
                          {draftSteps.length === 0 ? (
                            <p className="text-sm text-neutral-400" data-testid={`routing-draft-empty-${key}`}>
                              序列为空：从下面工序库添加至少一道（必完工序是完工门槛，缺了会阻止打包）
                            </p>
                          ) : (
                            <ol className="space-y-1.5">
                              {draftSteps.map((step, i) => (
                                <li
                                  key={`${step.operation}-${i}`}
                                  className="flex flex-wrap items-center gap-2 rounded border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-sm"
                                  data-testid={`routing-draft-step-${key}-${step.seq}`}
                                >
                                  <span className="w-6 text-neutral-400">{step.seq}.</span>
                                  <span className="font-medium text-neutral-900" data-testid={`routing-draft-name-${key}-${step.seq}`}>
                                    {step.operation}
                                  </span>
                                  <span className="text-xs text-neutral-500">
                                    {step.group ?? '—'} · {step.unit ?? '—'} · {money(step.unit_price)}
                                  </span>
                                  {step.is_must_finish && <span className="text-xs text-amber-600">必完</span>}
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

                          {/* 从工序库添加工序（v1 不做拖拽编排） */}
                          <div className="flex flex-wrap items-center gap-2">
                            <label className="text-sm text-neutral-600" htmlFor={`routing-add-select-${key}`}>
                              从工序库添加
                            </label>
                            <select
                              id={`routing-add-select-${key}`}
                              value={picked}
                              data-testid={`routing-add-select-${key}`}
                              onChange={(e) => setPicked(e.target.value)}
                              className="h-9 min-w-[240px] rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500"
                            >
                              <option value="">请选择工序</option>
                              {catalogGroups.map((g) => (
                                <optgroup key={g.group} label={g.group}>
                                  {g.operations.map((op) => (
                                    <option key={op.id} value={op.name}>
                                      {op.name}（{op.group ?? '—'} · {op.unit ?? '—'} · {money(op.unit_price)}）
                                    </option>
                                  ))}
                                </optgroup>
                              ))}
                            </select>
                            <Button
                              variant="secondary"
                              size="sm"
                              data-testid={`routing-add-${key}`}
                              disabled={!picked}
                              onClick={addToDraft}
                            >
                              <Plus className="w-3.5 h-3.5 mr-1" />
                              添加
                            </Button>
                            {libraryOps.length === 0 && (
                              <span className="text-xs text-amber-700" data-testid="routing-catalog-empty">
                                工序库为空 —— 先点右上「新增工序」，否则没有工序可加
                              </span>
                            )}
                          </div>
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

          {/* ── 信号映射配置区（issue #4308 P2：派生不再读硬编码常量表）── */}
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-baseline gap-2">
                <h2 className="text-base font-medium text-neutral-900">信号映射</h2>
                <span className="text-sm text-neutral-500">
                  加工项名/商品名里的信号 → 部位/工艺；命中优先于默认路线
                </span>
              </div>
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
              <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600" data-testid="route-signals-error">
                {signalsError}
              </p>
            )}

            {signals.length === 0 ? (
              <p className="py-6 text-center text-sm text-neutral-400" data-testid="route-signals-empty">
                暂无信号映射（全部订单将回落到默认路线）
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
                          <Button variant="danger" size="sm" data-testid={`route-signal-delete-${s.id}`} onClick={() => deleteSignal(s)}>
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
        <div className="space-y-3 px-6 py-4 text-sm">
          <p className="text-neutral-600">创建后到列表里点「编辑序列」把工序排好（v1 不做拖拽编排）。</p>
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
        <div className="space-y-3 px-6 py-4 text-sm">
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
          <div className="space-y-3 px-6 py-4 text-sm">
            <p className="text-neutral-600">
              信号按「加工项名 → 加工项选项 → 商品名 → 销售方式」的顺序匹配，命中即用这里的部位/工艺。
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
    </div>
  )
}
