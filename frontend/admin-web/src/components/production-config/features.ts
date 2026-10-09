'use client'

/**
 * 「工序库 / 工序与部位单价」与「工艺路线（含路线规则）」两块功能体的**共享状态与写面**（issue #6585 P1）。
 *
 * ## 为什么有这个模块（而不是把逻辑留在板子里）
 *
 * v2 把 `ProcessConfigBoard` 的内部 tab 拆成可独立挂载的面板；面板必须**自包含**（自己发自己的读面、
 * 自己持有写面），而板子**仍要**渲染同一块功能体（旧路由 `/production/routings` 行为一字不变，
 * `tests/unit/pages/production-routings.test.tsx` 的 163 条逐条钉住它）——
 * 🔴 **同一块 JSX 不许留两份**（否则就是「同一个概念两个载体」）。
 * ⇒ 办法：**状态 / 读面 / 写面 / 派生视图全在这里一份**，板子与面板各自
 * `useOperationFeature()` / `useRoutingsFeature()` 取同一份；两侧都只**渲染**面板组件。
 *
 * 取值来源与判据逐条随代码保留（未定价 ≠ ¥0.00 / 一条工序一个价 / 与后端护栏③同一把尺的删除路径 …），
 * 本模块只做**搬运**，不改任何口径。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { cuttingHeightApi, productionApi } from '@/lib/api'
// 就绪度判据的**单一真值**（issue #6573）：板子的五步体检卡与跨页主线**都调这里** ——
// 同一个概念两个载体 = 同一屏两个互相矛盾的数（#5858 的实测形态）。本模块只借用「缺哪条基础路线」
// 这一条判据，板子仍持有卡的文案（那属于呈现，不属于功能体）。
import { missingBaseRoutesOf } from '@/lib/config-readiness'
import { isErrorToastShown, toastRequestError } from '@/lib/api-error'
import {
  optionPriceGuardReasons,
  routingAdminGuardReasons,
  routingGuardReasons,
} from '@/lib/production-guard-reasons'
import {
  conditionText,
  convergeByLogicalName,
  logicalNameOf,
  type MatrixRow,
  type VariantView,
} from '@/components/production-config/utils'
import type {
  CatalogOperation,
  OperationPosition,
  OperationPositionUpdateParams,
  OperationsCatalog,
  ProductionOperationUpdateParams,
  RouteRule,
  RouteRuleCreateParams,
  RouteRuleTriggerKind,
  RouteRuleTriggerOptions,
  Routing,
  RoutingsResponse,
} from '@/types'

/** 一格价目的两态（`unit_price=null` ⇒ `unpriced`；**绝不**回落 `¥0.00`） */
export const cellState = (cell?: OperationPosition | null): 'unpriced' | 'priced' => {
  if (!cell) return 'unpriced'
  return cell.unit_price == null ? 'unpriced' : 'priced'
}

// ════════════════════════ 工序库 / 工序与部位单价 ════════════════════════

export function useOperationFeature({ enabled = true }: { enabled?: boolean } = {}) {
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [matrix, setMatrix] = useState<OperationPosition[]>([])
  const [matrixError, setMatrixError] = useState('')
  const [rules, setRules] = useState<RouteRule[]>([])
  const [rulesError, setRulesError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const [cellEditing, setCellEditing] = useState<string | null>(null)
  const [cellDraft, setCellDraft] = useState('')
  const [cellBusy, setCellBusy] = useState(false)
  const [cellReasons, setCellReasons] = useState<{ key: string; items: string[] } | null>(null)

  const [manageOp, setManageOp] = useState<string | null>(null)
  const [openWorkshops, setOpenWorkshops] = useState<Record<string, boolean>>({})
  const [editingVariantId, setEditingVariantId] = useState<string | null>(null)
  const [variantDraft, setVariantDraft] = useState({ group_name: '', unit: '' })
  const [variantBusy, setVariantBusy] = useState(false)
  const [variantReasons, setVariantReasons] = useState<{ id: string; items: string[] } | null>(null)
  const [confirmDeleteOpByName, setConfirmDeleteOpByName] = useState<string | null>(null)
  const [opLevelReasons, setOpLevelReasons] = useState<string[] | null>(null)

  const [confirmDeleteRuleId, setConfirmDeleteRuleId] = useState<number | null>(null)
  const [ruleDeleteReasons, setRuleDeleteReasons] = useState<{ id: number; items: string[] } | null>(null)
  const [ruleBusy, setRuleBusy] = useState(false)

  const [ruleOptions, setRuleOptions] = useState<RouteRuleTriggerOptions>({ crafts: [], processing_items: [], positions: [] })
  const [conditionFormOpen, setConditionFormOpen] = useState(false)
  const [conditionDraft, setConditionDraft] = useState<{
    trigger_kind: RouteRuleTriggerKind
    trigger_value: string
    action: 'insert' | 'remove'
    after_operation: string
  }>({ trigger_kind: 'option', trigger_value: '', action: 'insert', after_operation: '' })
  const [conditionReasons, setConditionReasons] = useState<string[]>([])

  const [editingRulePriceId, setEditingRulePriceId] = useState<string | number | null>(null)
  const [rulePriceDraft, setRulePriceDraft] = useState('')
  const [rulePriceReasons, setRulePriceReasons] = useState<string[]>([])
  const [rulePriceBusy, setRulePriceBusy] = useState(false)

  const [newOpOpen, setNewOpOpen] = useState(false)
  const [newOp, setNewOp] = useState({ name: '', group_name: '', unit: '', unit_price: '' })
  const [newOpReasons, setNewOpReasons] = useState<string[]>([])
  const [qtyRuleNotice, setQtyRuleNotice] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<'operation' | 'option'>('operation')
  const [newOption, setNewOption] = useState({
    trigger_value: '',
    customer_unit_price: '',
    operation: '',
    after_operation: '',
  })
  const [newOptionReasons, setNewOptionReasons] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const [routingsRes, catalogRes, positionsRes, rulesRes, ruleOptionsRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getOperationPositions(),
      productionApi.getRouteRules(),
      productionApi.getRouteRuleOptions(),
    ])
    if (routingsRes.status === 'fulfilled') setRoutings(routingsRes.value.data?.data ?? null)
    else {
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
    if (positionsRes.status === 'fulfilled') {
      setMatrix((positionsRes.value.data?.data ?? []).map((c) => ({ ...c, operation: logicalNameOf(c) })))
      setMatrixError('')
    } else {
      setMatrix([])
      setMatrixError('工序单价加载失败，请稍后重试')
    }
    if (rulesRes.status === 'fulfilled') {
      setRules(rulesRes.value.data?.data ?? [])
      setRulesError('')
    } else {
      setRules([])
      setRulesError('适用条件加载失败，请稍后重试')
    }
    if (ruleOptionsRes.status === 'fulfilled') {
      const opts = ruleOptionsRes.value.data?.data
      setRuleOptions({
        crafts: opts?.crafts ?? [],
        processing_items: opts?.processing_items ?? [],
        positions: opts?.positions ?? [],
      })
    } else {
      setRuleOptions({ crafts: [], processing_items: [], positions: [] })
    }
    setLoading(false)
  }, [])

  /**
   * 自读：`enabled=false` 时**不发请求**（板子已用同源 hook 取过同一份数据 ⇒ 不重复发；
   * 面板独立挂载时走默认 `true`，自己发）。
   */
  useEffect(() => {
    if (!enabled) return
    void load()
  }, [enabled, load])

  const libraryOps = useMemo(() => (catalog?.groups ?? []).flatMap((g) => g.operations), [catalog])
  const libraryByName = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(op.name, op))
    return m
  }, [libraryOps])
  const libraryById = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    libraryOps.forEach((op) => m.set(String(op.id), op))
    return m
  }, [libraryOps])

  const orphanOps = useMemo(() => {
    const referenced = new Set(
      matrix.map((c) => c.variant_operation_id).filter((v): v is string => v != null).map(String),
    )
    return libraryOps.filter((op) => !referenced.has(String(op.id)))
  }, [matrix, libraryOps])

  const matrixRows = useMemo<MatrixRow[]>(
    () =>
      convergeByLogicalName(matrix).map((cell) => ({
        operation: cell.operation,
        cell,
        cells: new Map([[cell.position, cell]]),
      })),
    [matrix],
  )

  const logicalOps = useMemo(() => matrixRows.map((r) => r.operation), [matrixRows])

  const optionNames = useMemo(
    () => [...new Set(rules.filter((r) => r.trigger_kind === 'option').map((r) => r.trigger_value ?? ''))]
      .filter((n) => n !== ''),
    [rules],
  )

  const orphanRows = useMemo<MatrixRow[]>(() => {
    const priced = new Set(matrixRows.map((r) => r.operation))
    const seen = new Set<string>()
    const rows: MatrixRow[] = []
    orphanOps.forEach((op) => {
      const name = op.name
      if (!name || seen.has(name) || priced.has(name)) return
      seen.add(name)
      rows.push({ operation: name, cell: null, cells: new Map(), library: op })
    })
    return rows
  }, [orphanOps, matrixRows])

  const operationsRows = useMemo(() => [...matrixRows, ...orphanRows], [matrixRows, orphanRows])

  const distinctMeta = (
    row: { cells: Map<string, OperationPosition> },
    pick: (c: OperationPosition) => string | null | undefined,
  ) => {
    const out: string[] = []
    row.cells.forEach((c) => {
      const v = pick(c)
      if (v && !out.includes(v)) out.push(v)
    })
    return out
  }

  const metaValues = (
    row: MatrixRow,
    pick: (c: OperationPosition) => string | null | undefined,
    libPick: (o: CatalogOperation) => string | null | undefined,
  ): string[] => {
    const vals = distinctMeta(row, pick)
    if (vals.length > 0 || !row.library) return vals
    const v = libPick(row.library)
    return v ? [v] : []
  }

  const q = search.trim().toLowerCase()

  const workshopGroups = useMemo(() => {
    const byGroup = new Map<string, MatrixRow[]>()
    operationsRows.forEach((row) => {
      const groups = metaValues(row, (c) => c.group, (o) => o.group)
      const key = groups.length > 0 ? groups.join(' / ') : ''
      byGroup.set(key, [...(byGroup.get(key) ?? []), row])
    })
    return [...byGroup.entries()].map(([group, rows]) => ({ group, rows }))
  }, [operationsRows])

  const visibleMatrixRows = useMemo(
    () => operationsRows.filter((r) => !q || r.operation.toLowerCase().includes(q)),
    [operationsRows, q],
  )

  const visibleWorkshopGroups = useMemo(
    () =>
      workshopGroups
        .map((g) => ({ group: g.group, rows: g.rows.filter((r) => !q || r.operation.toLowerCase().includes(q)) }))
        .filter((g) => g.rows.length > 0),
    [workshopGroups, q],
  )

  const unpricedCount = useMemo(
    () => matrixRows.filter((r) => cellState(r.cell) === 'unpriced').length,
    [matrixRows],
  )

  const qtyRuleMissingOf = useCallback(
    (operation: string): boolean => libraryByName.get(operation)?.qty_rule_missing === true,
    [libraryByName],
  )

  const fallbackOpByName = useMemo(() => {
    const m = new Map<string, { op: CatalogOperation; candidates: number }>()
    libraryOps.forEach((op) => {
      const cur = m.get(op.name)
      if (cur) {
        cur.candidates += 1
        return
      }
      m.set(op.name, { op, candidates: 1 })
    })
    return m
  }, [libraryOps])

  const idsByName = useMemo(() => {
    const m = new Map<string, Set<string>>()
    libraryOps.forEach((op) => {
      const set = m.get(op.name) ?? new Set<string>()
      set.add(String(op.id))
      m.set(op.name, set)
    })
    return m
  }, [libraryOps])

  const manageOpEntry = useMemo(
    () => (manageOp ? fallbackOpByName.get(manageOp) ?? null : null),
    [fallbackOpByName, manageOp],
  )
  const manageRow = useMemo(() => matrixRows.find((r) => r.operation === manageOp) ?? null, [matrixRows, manageOp])
  const manageOpCells = useMemo(() => (manageRow ? [...manageRow.cells.values()] : []), [manageRow])

  const variantsOf = useCallback(
    (row: MatrixRow): VariantView[] => {
      const byId = new Map<string, VariantView>()
      const byName = fallbackOpByName.get(row.operation)?.op ?? null
      const ownIds = idsByName.get(row.operation) ?? null
      row.cells.forEach((c) => {
        const explicit = c.variant_operation_id
        const fallback = explicit ? null : byName
        const id = explicit ?? (fallback ? String(fallback.id) : null)
        if (!id) return
        const entry = libraryById.get(id)
        const foreign = !!explicit && entry != null && ownIds != null && !ownIds.has(String(explicit))
        const unlinked = !explicit || foreign
        if (byId.has(id)) return
        byId.set(id, {
          id,
          group: (fallback?.group ?? c.group) ?? null,
          unit: (fallback?.unit ?? c.unit) ?? null,
          source: entry?.source ?? fallback?.source ?? null,
          unlinked,
          foreign,
        })
      })
      return [...byId.values()]
    },
    [fallbackOpByName, idsByName, libraryById],
  )

  const manageVariants = useMemo(() => (manageRow ? variantsOf(manageRow) : []), [manageRow, variantsOf])
  const manageUnlinked = useMemo(() => manageVariants.filter((v) => v.unlinked), [manageVariants])

  const manageTargetOp = useMemo(() => {
    const v = manageVariants.find((x) => !x.foreign)
    return (v ? libraryById.get(v.id) ?? null : null) ?? manageOpEntry?.op ?? null
  }, [manageVariants, libraryById, manageOpEntry])

  const manageConditions = useMemo(
    () => (manageOp ? rules.filter((r) => r.operation === manageOp) : []),
    [rules, manageOp],
  )

  const routeList = useMemo(() => routings?.routings ?? [], [routings])
  const anchorDefaultFor = (operation: string) => {
    const seeded = rules.find(
      (r) => r.operation === operation && r.action !== 'remove' && (r.after_operation ?? '') !== '',
    )
    if (seeded) return seeded.after_operation as string
    const mainline = routeList.find((r) => r.is_default)?.mainline ?? []
    const idx = mainline.indexOf(operation)
    return idx > 0 ? mainline[idx - 1] : ''
  }

  const deleteRuleTarget = useMemo(
    () => rules.find((r) => r.id === confirmDeleteRuleId) ?? null,
    [rules, confirmDeleteRuleId],
  )
  const opDeleteBlockerCells = useMemo(() => manageOpCells, [manageOpCells])
  const deleteOpByNameTarget = useMemo(
    () =>
      confirmDeleteOpByName && manageTargetOp
        ? { op: manageTargetOp, candidates: manageOpEntry?.candidates ?? 1 }
        : null,
    [confirmDeleteOpByName, manageTargetOp, manageOpEntry],
  )
  const deleteOpByNameCells = useMemo(
    () => (deleteOpByNameTarget ? manageOpCells : []),
    [deleteOpByNameTarget, manageOpCells],
  )

  /** 就绪度卡第 ① 步的输入（issue #6585）：工序库读面非空（`catalog.total > 0`） */
  const operationsReady = (catalog?.total ?? 0) > 0

  // ── 写面 ──

  const openCreateOperation = () => {
    setNewKind('operation')
    setNewOptionReasons([])
    setNewOpReasons([])
    setNewOpOpen(true)
  }

  const createOperation = async () => {
    const name = newOp.name.trim()
    const price = Number(newOp.unit_price)
    const reasons: string[] = []
    if (!name) reasons.push('请填写工序名称')
    if (newOp.unit_price.trim() === '' || Number.isNaN(price)) {
      reasons.push('请输入有效单价（元/件·米·折）')
    }
    if (reasons.length > 0) {
      setNewOpReasons(reasons)
      return
    }
    setNewOpReasons([])
    setBusy(true)
    try {
      const res = await productionApi.createOperation({
        name,
        group_name: newOp.group_name.trim() || undefined,
        unit: newOp.unit.trim() || undefined,
        unit_price: price,
      })
      const hint = res?.data?.data?.qty_rule_hint
      setQtyRuleNotice(typeof hint === 'string' && hint.trim() !== '' ? hint : null)
      toast.success(`已新增工序「${name}」`)
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

  const createOptionRule = async () => {
    const reasons: string[] = []
    const trigger = newOption.trigger_value.trim()
    if (!trigger) reasons.push('请填写选项名称')
    if (!newOption.operation) reasons.push('请选择目标工序：这条选项要在哪道工序上生效')
    const rawPrice = newOption.customer_unit_price.trim()
    if (rawPrice === '') {
      reasons.push('请填写单价（元/套）：对客按套计价，空着等于没有报价')
    } else if (!/^\d+(\.\d{1,2})?$/.test(rawPrice)) {
      reasons.push('单价必须是 ≥ 0 且最多两位小数的数字（元/套）')
    }
    if (reasons.length > 0) {
      setNewOptionReasons(reasons)
      return
    }
    const payload: RouteRuleCreateParams = {
      trigger_value: trigger,
      operation: newOption.operation,
      customer_unit_price: Number(rawPrice),
    }
    if (newOption.after_operation) payload.after_operation = newOption.after_operation
    setBusy(true)
    setNewOptionReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('特殊选项已新增')
      setNewOpOpen(false)
      setNewOption({ trigger_value: '', customer_unit_price: '', operation: '', after_operation: '' })
      await load()
    } catch (e) {
      console.error(e)
      setNewOptionReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('新增特殊选项失败')
    } finally {
      setBusy(false)
    }
  }

  const createCondition = async () => {
    if (!manageOp) return
    const reasons: string[] = []
    const trigger = conditionDraft.trigger_value.trim()
    if (!trigger) {
      const reasonByKind: Record<RouteRuleTriggerKind, string> = {
        craft: '请选择什么时候生效：工艺必须从列表里选（手输一个不在列表里的名字 = 这条条件永远不命中）',
        processing_item: '请选择什么时候生效：加工项必须从列表里选（触发键 = 订单里的加工项名，精确相等）',
        position: '请选择什么时候生效：部位必须从列表里选（部位 = 布帘/纱帘/帘头/布料，空 = 不限部位）',
        option: '请选择什么时候生效：特殊选项必须从列表里选（选项名是订单里的键，错一个字就查不到）',
      }
      reasons.push(reasonByKind[conditionDraft.trigger_kind] ?? reasonByKind.option)
    }
    if (reasons.length > 0) {
      setConditionReasons(reasons)
      return
    }
    const payload: RouteRuleCreateParams = {
      trigger_kind: conditionDraft.trigger_kind,
      trigger_value: trigger,
      action: conditionDraft.action,
      operation: manageOp,
    }
    if (conditionDraft.action === 'insert' && conditionDraft.after_operation) {
      payload.after_operation = conditionDraft.after_operation
    }
    if (conditionDraft.trigger_kind === 'position') {
      payload.position = trigger
    }
    setBusy(true)
    setConditionReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('条件已添加')
      setConditionFormOpen(false)
      await load()
    } catch (e) {
      console.error(e)
      setConditionReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('添加条件失败')
    } finally {
      setBusy(false)
    }
  }

  const openConditionForm = () => {
    setConditionDraft({
      trigger_kind: 'option',
      trigger_value: '',
      action: 'insert',
      after_operation: manageOp ? anchorDefaultFor(manageOp) : '',
    })
    setConditionReasons([])
    setConditionFormOpen(true)
  }

  const switchConditionKind = (kind: RouteRuleTriggerKind) => {
    setConditionDraft((d) => ({ ...d, trigger_kind: kind, trigger_value: '' }))
    setConditionReasons([])
  }

  const closeManage = () => {
    if (variantBusy) return
    setManageOp(null)
    setConditionFormOpen(false)
    setConditionReasons([])
    setConfirmDeleteOpByName(null)
    setOpLevelReasons(null)
  }

  const openManageFor = (operation: string) => {
    setManageOp(operation)
    setEditingVariantId(null)
    setConfirmDeleteOpByName(null)
    setVariantReasons(null)
    setOpLevelReasons(null)
  }

  const cellKeyOf = (operation: string) => operation

  const submitCell = async (
    key: string,
    id: string | null | undefined,
    payload: OperationPositionUpdateParams,
  ) => {
    if (!id) {
      setCellReasons({ key, items: ['这一行缺少行标识，无法保存 —— 请点右上「刷新」重试'] })
      return
    }
    setCellBusy(true)
    setCellReasons(null)
    try {
      await productionApi.updateOperationPosition(id, payload)
      toast.success(payload.unit_price == null ? '已改回未定价' : '计件单价已更新')
      setCellEditing(null)
      await load()
    } catch (e) {
      setCellReasons({ key, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('保存失败')
    } finally {
      setCellBusy(false)
    }
  }

  const saveCellPrice = (cell: OperationPosition) => {
    const key = cellKeyOf(cell.operation)
    const raw = cellDraft.trim()
    if (raw !== '' && !/^\d+(\.\d{1,2})?$/.test(raw)) {
      setCellReasons({ key, items: ['计件单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'] })
      return
    }
    void submitCell(key, cell.id, { unit_price: raw === '' ? null : Number(raw) })
  }

  const cancelCellEdit = () => {
    setCellEditing(null)
    setCellDraft('')
    setCellReasons(null)
  }

  const submitVariant = async (id: string, payload: ProductionOperationUpdateParams) => {
    setVariantBusy(true)
    setVariantReasons(null)
    try {
      await productionApi.updateOperation(id, payload)
      toast.success('工序已更新')
      setEditingVariantId(null)
      await load()
    } catch (e) {
      setVariantReasons({ id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('工序更新失败')
    } finally {
      setVariantBusy(false)
    }
  }

  const openDeleteOpByName = () => {
    if (!manageOp) return
    if (!manageTargetOp) {
      setOpLevelReasons([
        `「${manageOp}」在工序库里查不到对应的工序行，无法删除 —— 请点右上「刷新」重试；` +
          '若仍查不到，它可能已被别的会话删除',
      ])
      return
    }
    setConfirmDeleteOpByName(manageOp)
    setOpLevelReasons(null)
  }

  const removeOpByName = async (op: CatalogOperation) => {
    setVariantBusy(true)
    setOpLevelReasons(null)
    try {
      if (opDeleteBlockerCells.length > 0) {
        await productionApi.deleteOperation(String(op.id), { detachPositions: true })
        toast.success(`已设为不做并删除工序「${op.name}」`)
      } else {
        await productionApi.deleteOperation(String(op.id))
        toast.success(`已删除工序「${op.name}」`)
      }
      setConfirmDeleteOpByName(null)
      await load()
    } catch (e) {
      setOpLevelReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setVariantBusy(false)
    }
  }

  const disableOpByName = async (op: CatalogOperation) => {
    setVariantBusy(true)
    setOpLevelReasons(null)
    try {
      await productionApi.updateOperation(op.id, { status: 'disabled' })
      toast.success(`已停用工序「${op.name}」`)
      await load()
    } catch (e) {
      setOpLevelReasons(routingAdminGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('停用失败')
    } finally {
      setVariantBusy(false)
    }
  }

  const removeRule = async (rule: RouteRule) => {
    setRuleBusy(true)
    setRuleDeleteReasons(null)
    try {
      await productionApi.deleteRouteRule(rule.id)
      toast.success('规则已删除')
      setConfirmDeleteRuleId(null)
      await load()
    } catch (e) {
      setRuleDeleteReasons({ id: rule.id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setRuleBusy(false)
    }
  }

  const saveRulePrice = async (rule: RouteRule) => {
    const raw = rulePriceDraft.trim()
    const value = raw === '' ? null : Number(raw)
    if (value !== null && (Number.isNaN(value) || value < 0 || !/^\d+(\.\d{1,2})?$/.test(raw))) {
      setRulePriceReasons(['单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'])
      return
    }
    setRulePriceBusy(true)
    setRulePriceReasons([])
    try {
      await productionApi.updateRuleCustomerUnitPrice(rule.id, { customer_unit_price: value })
      toast.success(value === null ? '已改回未定价' : '单价已更新')
      setEditingRulePriceId(null)
      await load()
    } catch (e) {
      setRulePriceReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('单价保存失败')
    } finally {
      setRulePriceBusy(false)
    }
  }

  const cancelRulePrice = () => {
    setEditingRulePriceId(null)
    setRulePriceDraft('')
    setRulePriceReasons([])
  }

  return {
    // 只读面
    catalog, catalogError, routings, matrix, matrixError, rules, rulesError, loading, error, load,
    search, setSearch,
    // 矩阵格写面
    cellEditing, setCellEditing, cellDraft, setCellDraft, cellBusy, cellReasons, setCellReasons,
    // 抽屉
    manageOp, setManageOp, openWorkshops, setOpenWorkshops, editingVariantId, setEditingVariantId,
    variantDraft, setVariantDraft, variantBusy, variantReasons, confirmDeleteOpByName,
    setConfirmDeleteOpByName, opLevelReasons, setOpLevelReasons,
    // 条件删除
    confirmDeleteRuleId, setConfirmDeleteRuleId, ruleDeleteReasons, setRuleDeleteReasons, ruleBusy,
    // 适用条件表单
    ruleOptions, conditionFormOpen, setConditionFormOpen, conditionDraft, setConditionDraft,
    conditionReasons, editingRulePriceId, setEditingRulePriceId, rulePriceDraft, setRulePriceDraft,
    rulePriceReasons, setRulePriceReasons, rulePriceBusy,
    // 新增弹窗
    newOpOpen, setNewOpOpen, newOp, setNewOp, newOpReasons, setNewOpReasons, qtyRuleNotice, setQtyRuleNotice,
    newKind, setNewKind, newOption, setNewOption, newOptionReasons, setNewOptionReasons, busy,
    // 派生
    libraryOps, libraryByName, libraryById, orphanOps, matrixRows, logicalOps, optionNames, orphanRows,
    operationsRows, workshopGroups, visibleMatrixRows, visibleWorkshopGroups, unpricedCount,
    qtyRuleMissingOf, fallbackOpByName, idsByName, manageOpEntry, manageRow, manageOpCells, variantsOf,
    manageVariants, manageUnlinked, manageTargetOp, manageConditions, routeList, anchorDefaultFor,
    deleteRuleTarget, opDeleteBlockerCells, deleteOpByNameTarget, deleteOpByNameCells,
    // 就绪度卡第 ① 步的输入
    operationsReady,
    /** 行尾元数据取值（价目行优先，无价目行时回落工序库那一行） */
    metaValues,
    /** 一条条件的**人话**（与板子同源；`utils.ts` 一份） */
    conditionTextOf: conditionText,
    // 写面
    openCreateOperation, createOperation, createOptionRule, createCondition, openConditionForm,
    switchConditionKind, closeManage, openManageFor, cellKeyOf, submitCell, saveCellPrice,
    cancelCellEdit, submitVariant, openDeleteOpByName, removeOpByName, disableOpByName, removeRule,
    saveRulePrice, cancelRulePrice,
  }
}

export type OperationFeature = ReturnType<typeof useOperationFeature>

// ════════════════════════ 工艺路线（含路线规则） ════════════════════════

/**
 * 工艺路线（含路线规则）功能体。
 *
 * `enabled=false` ⇒ **不发读面**（板子已用同源 hook 取过同一份数据 ⇒ 不重复发；
 * `RoutingsPanel` 被板子传入 `store` 时同样不重复发）。默认 `true` = 独立挂载时自包含取数。
 */
export function useRoutingsFeature({ enabled = true }: { enabled?: boolean } = {}) {
  const [routings, setRoutings] = useState<RoutingsResponse | null>(null)
  const [catalog, setCatalog] = useState<OperationsCatalog | null>(null)
  const [matrix, setMatrix] = useState<OperationPosition[]>([])
  const [rules, setRules] = useState<RouteRule[]>([])
  const [rulesError, setRulesError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState('')

  const [editing, setEditing] = useState<Routing | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState<string[]>([])
  const [localReason, setLocalReason] = useState('')

  const [renameTarget, setRenameTarget] = useState<Routing | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [confirmAction, setConfirmAction] = useState<{ kind: 'delete' | 'default'; routing: Routing } | null>(null)
  const [opReasons, setOpReasons] = useState<string[]>([])

  const [ruleOptions, setRuleOptions] = useState<RouteRuleTriggerOptions>({ crafts: [], processing_items: [], positions: [] })
  const [confirmDeleteRuleId, setConfirmDeleteRuleId] = useState<number | null>(null)
  const [ruleDeleteReasons, setRuleDeleteReasons] = useState<{ id: number; items: string[] } | null>(null)
  const [ruleBusy, setRuleBusy] = useState(false)
  const [editingRulePriceId, setEditingRulePriceId] = useState<string | number | null>(null)
  const [rulePriceDraft, setRulePriceDraft] = useState('')
  const [rulePriceReasons, setRulePriceReasons] = useState<string[]>([])
  const [rulePriceBusy, setRulePriceBusy] = useState(false)

  const [newRouteOpen, setNewRouteOpen] = useState(false)
  const [newRoute, setNewRoute] = useState<{ name: string }>({ name: '' })
  /** 「添加条件」弹窗的目标工序（`null` = 关闭）—— 取值域 = 价目表逻辑工序名 */
  const [addConditionOp, setAddConditionOp] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const [routingsRes, catalogRes, positionsRes, rulesRes, ruleOptionsRes] = await Promise.allSettled([
      productionApi.getRoutings(),
      productionApi.getOperationsCatalog(),
      productionApi.getOperationPositions(),
      productionApi.getRouteRules(),
      productionApi.getRouteRuleOptions(),
    ])
    if (routingsRes.status === 'fulfilled') {
      setRoutings(routingsRes.value.data?.data ?? null)
    } else {
      setRoutings(null)
      setError('工艺路线加载失败，请稍后重试')
    }
    if (catalogRes.status === 'fulfilled') setCatalog(catalogRes.value.data?.data ?? null)
    else setCatalog(null)
    if (positionsRes.status === 'fulfilled') {
      setMatrix((positionsRes.value.data?.data ?? []).map((c) => ({ ...c, operation: logicalNameOf(c) })))
    } else setMatrix([])
    if (rulesRes.status === 'fulfilled') {
      setRules(rulesRes.value.data?.data ?? [])
      setRulesError('')
    } else {
      setRules([])
      setRulesError('适用条件加载失败，请稍后重试')
    }
    if (ruleOptionsRes.status === 'fulfilled') {
      const opts = ruleOptionsRes.value.data?.data
      setRuleOptions({
        crafts: opts?.crafts ?? [],
        processing_items: opts?.processing_items ?? [],
        positions: opts?.positions ?? [],
      })
    } else {
      setRuleOptions({ crafts: [], processing_items: [], positions: [] })
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    if (!enabled) return
    void load()
  }, [enabled, load])

  const routeList = useMemo(() => routings?.routings ?? [], [routings])

  /**
   * 就绪度卡（路线侧）的三条派生（issue #6585）：与板子**逐值同源** ——
   * `emptyShells` = 主线为空的路线、`missingBaseRoutes` = 缺哪条基础路线（判据收敛在
   * `@/lib/config-readiness`，不在这里另写一份）、`defaults` = 默认路线（第 ③ 步的计数）。
   */
  const emptyShells = useMemo(
    () => routeList.filter((r) => (r.mainline ?? []).length === 0),
    [routeList],
  )
  const missingBaseRoutes = useMemo(
    () => missingBaseRoutesOf(routeList.map((r) => r.name)),
    [routeList],
  )
  const defaults = useMemo(() => routeList.filter((r) => r.is_default), [routeList])

  /** 工序库按名索引（主线 chips 的「分组 · 单位」与「工序是否存在」判据） */
  const libraryByName = useMemo(() => {
    const m = new Map<string, CatalogOperation>()
    ;(catalog?.groups ?? []).flatMap((g) => g.operations).forEach((op) => m.set(op.name, op))
    return m
  }, [catalog])
  /** 价目表里出现过的逻辑工序名（「工序是否存在」的**唯一权威**，与板子同源） */
  const matrixOps = useMemo(() => new Set(matrix.map((c) => c.operation)), [matrix])

  const distinctMeta = (
    row: { cells: Map<string, OperationPosition> },
    pick: (c: OperationPosition) => string | null | undefined,
  ) => {
    const out: string[] = []
    row.cells.forEach((c) => {
      const v = pick(c)
      if (v && !out.includes(v)) out.push(v)
    })
    return out
  }

  const paletteOps = useMemo(
    () =>
      convergeByLogicalName(matrix).map((cell) => ({
        name: cell.operation,
        groups: distinctMeta({ cells: new Map([[cell.position, cell]]) }, (c) => c.group),
      })),
    [matrix],
  )

  const stepView = useCallback(
    (name: string, i: number) => {
      const lib = libraryByName.get(name)
      return {
        seq: i + 1,
        operation: name,
        group: lib?.group ?? null,
        unit: lib?.unit ?? null,
        resolved: !!lib,
        missing: !matrixOps.has(name),
      }
    },
    [libraryByName, matrixOps],
  )

  const draftSteps = useMemo(() => draft.map(stepView), [draft, stepView])
  const missingSteps = draftSteps.filter((s) => s.missing)

  const defaultRoute = useMemo(() => routeList.find((r) => r.is_default) ?? null, [routeList])
  const anchorDefaultFor = (operation: string) => {
    const seeded = rules.find(
      (r) => r.operation === operation && r.action !== 'remove' && (r.after_operation ?? '') !== '',
    )
    if (seeded) return seeded.after_operation as string
    const mainline = defaultRoute?.mainline ?? []
    const idx = mainline.indexOf(operation)
    return idx > 0 ? mainline[idx - 1] : ''
  }

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

  const createRoute = async () => {
    const name = newRoute.name.trim()
    if (!name) {
      toast.error('请填写路线名称')
      return
    }
    setBusy(true)
    try {
      const res = await productionApi.createRouting({ name })
      const created = res.data?.data as Routing | undefined
      toast.success(`已新建路线「${name}」，请把工序排进主线`)
      setNewRouteOpen(false)
      setNewRoute({ name: '' })
      await load()
      if (created?.id) openEditor({ ...created, mainline: created.mainline ?? [] })
    } catch (e) {
      console.error(e)
      toastRequestError(e, '新建路线失败')
    } finally {
      setBusy(false)
    }
  }

  const openRename = (routing: Routing) => {
    setRenameTarget(routing)
    setRenameDraft(routing.name)
    setOpReasons([])
  }

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

  const deleteBlockReasons = (routing: Routing): string[] => {
    const out: string[] = []
    if (routeList.length <= 1) {
      out.push('这是最后一条工艺路线：删了就一条都不剩，任何订单都生成不了加工单。请先新建一条路线，再删这条。')
    }
    if (routing.is_default) {
      out.push(
        '默认路线是订单的最后去处：删了之后，没匹配到专属路线的订单一张加工单也生成不了。请先把另一条设为默认，再删这条。',
      )
    }
    return out
  }

  const removeRule = async (rule: RouteRule) => {
    setRuleBusy(true)
    setRuleDeleteReasons(null)
    try {
      await productionApi.deleteRouteRule(rule.id)
      toast.success('规则已删除')
      setConfirmDeleteRuleId(null)
      await load()
    } catch (e) {
      setRuleDeleteReasons({ id: rule.id, items: routingAdminGuardReasons(e) })
      if (!isErrorToastShown(e)) toast.error('删除失败')
    } finally {
      setRuleBusy(false)
    }
  }

  const saveRulePrice = async (rule: RouteRule) => {
    const raw = rulePriceDraft.trim()
    const value = raw === '' ? null : Number(raw)
    if (value !== null && (Number.isNaN(value) || value < 0 || !/^\d+(\.\d{1,2})?$/.test(raw))) {
      setRulePriceReasons(['单价必须是 ≥ 0 且最多两位小数的数字（要表示「还没定价」请清空）'])
      return
    }
    setRulePriceBusy(true)
    setRulePriceReasons([])
    try {
      await productionApi.updateRuleCustomerUnitPrice(rule.id, { customer_unit_price: value })
      toast.success(value === null ? '已改回未定价' : '单价已更新')
      setEditingRulePriceId(null)
      await load()
    } catch (e) {
      setRulePriceReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('单价保存失败')
    } finally {
      setRulePriceBusy(false)
    }
  }

  const cancelRulePrice = () => {
    setEditingRulePriceId(null)
    setRulePriceDraft('')
    setRulePriceReasons([])
  }

  const deleteRuleTarget = useMemo(
    () => rules.find((r) => r.id === confirmDeleteRuleId) ?? null,
    [rules, confirmDeleteRuleId],
  )

  /** 规则行的**取值域**（目标工序 / 锚点）—— 与价目表逻辑名同源，不新造第二份工序名清单 */
  const logicalOps = useMemo(() => convergeByLogicalName(matrix).map((c) => c.operation), [matrix])
  const optionNames = useMemo(
    () => [...new Set(rules.filter((r) => r.trigger_kind === 'option').map((r) => r.trigger_value ?? ''))]
      .filter((n) => n !== ''),
    [rules],
  )

  /** 给某道工序加一条适用条件（写面复用 `POST /route-rules`，不新造第二套） */
  const createCondition = async (
    operation: string,
    kind: RouteRuleTriggerKind,
    trigger: string,
    action: 'insert' | 'remove',
  ) => {
    const reasons: string[] = []
    if (!trigger) {
      const reasonByKind: Record<RouteRuleTriggerKind, string> = {
        craft: '请选择什么时候生效：工艺必须从列表里选（手输一个不在列表里的名字 = 这条条件永远不命中）',
        processing_item: '请选择什么时候生效：加工项必须从列表里选（触发键 = 订单里的加工项名，精确相等）',
        position: '请选择什么时候生效：部位必须从列表里选（部位 = 布帘/纱帘/帘头/布料，空 = 不限部位）',
        option: '请选择什么时候生效：特殊选项必须从列表里选（选项名是订单里的键，错一个字就查不到）',
      }
      reasons.push(reasonByKind[kind] ?? reasonByKind.option)
      setOpReasons(reasons)
      return
    }
    const payload: RouteRuleCreateParams = { trigger_kind: kind, trigger_value: trigger, action, operation }
    if (action === 'insert') {
      const anchor = anchorDefaultFor(operation)
      if (anchor) payload.after_operation = anchor
    }
    if (kind === 'position') payload.position = trigger
    setBusy(true)
    setOpReasons([])
    try {
      await productionApi.createOptionRule(payload)
      toast.success('条件已添加')
      setAddConditionOp(null)
      await load()
    } catch (e) {
      console.error(e)
      setOpReasons(optionPriceGuardReasons(e))
      if (!isErrorToastShown(e)) toast.error('添加条件失败')
    } finally {
      setBusy(false)
    }
  }

  return {
    routings, catalog, matrix, rules, rulesError, loading, error, load, picked, setPicked,
    editing, editingId, draft, saving, reasons, localReason,
    renameTarget, setRenameTarget, renameDraft, setRenameDraft, confirmAction, setConfirmAction, opReasons,
    ruleOptions, confirmDeleteRuleId, setConfirmDeleteRuleId, ruleDeleteReasons, setRuleDeleteReasons,
    ruleBusy, editingRulePriceId, setEditingRulePriceId, rulePriceDraft, setRulePriceDraft,
    rulePriceReasons, setRulePriceReasons, rulePriceBusy,
    newRouteOpen, setNewRouteOpen, newRoute, setNewRoute, busy,
    routeList, emptyShells, missingBaseRoutes, defaults,
    defaultRoute, paletteOps, stepView, draftSteps, missingSteps, anchorDefaultFor,
    openEditor, closeEditor, addFromPalette, move, removeAt, saveSequence, createRoute, openRename,
    submitRename, runConfirm, deleteBlockReasons, removeRule, saveRulePrice, cancelRulePrice,
    deleteRuleTarget,
    // 适用条件（新增表单）
    addConditionOp, setAddConditionOp, createCondition, logicalOps, optionNames,
  }
}

export type RoutingsFeature = ReturnType<typeof useRoutingsFeature>

// ════════════════════════ 裁高配置（就绪信号） ════════════════════════

/**
 * 裁高配置的**就绪信号**（issue #5161 / #5858 的就绪度第 ⑤ 步）。
 *
 * 只需要一个 `source`（「配没配」）—— 写面与展示仍由 `CuttingHeightConfigPanel` 自己管。
 * 板子与 `CuttingHeightPanel` **共用这一份**（issue #6585 选 (b)）：板子调它算第 ⑤ 步、
 * 面板把它当 `store` 传下去 ⇒ 首屏**只发一次** `cuttingHeightApi.get()`（选 (a) 会发两次）。
 */
export function useCutFeature({ enabled = true }: { enabled?: boolean } = {}) {
  /** `null` = 还没读回来；`stored` = 本租户存过；`default` = 缺行用系统默认 */
  const [source, setSource] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await cuttingHeightApi.get()
      setSource(res.data?.data?.source ?? '')
      setError('')
    } catch {
      setSource(null)
      setError('裁高配置加载失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void load()
  }, [enabled, load])

  return { source, error, load }
}

export type CutFeature = ReturnType<typeof useCutFeature>
