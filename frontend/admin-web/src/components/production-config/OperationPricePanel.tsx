'use client'

/**
 * **工序库 / 工序与部位单价面板**（issue #6585 P1：配置指挥台 v2 的「工序与部位单价」域）。
 *
 * ## 它是什么
 *
 * 板子（`ProcessConfigBoard`）原 tab「工序管理」的第一大块（`craft-operations-panel`）：
 * 一张「一道工序一个价」的表（`operation-price-matrix`）+ 就地改价 + 行尾「管理▸」抽屉
 * （分组 / 单位 / 停用 / 删除 / 适用条件）+「新增」对话框（工序 / 特殊选项二选一）。
 *
 * ## 单一实现（issue #6585 集成口径）
 *
 * 🔴 **同一块 JSX 不留两份**：状态 / 读面 / 写面 / 派生视图全在
 * `frontend/admin-web/src/components/production-config/features.ts` 的 `useOperationFeature()`
 * 里**一份**；板子与独立挂载**都渲染本组件**：
 * - 板子挂载 ⇒ 传 `store`（它已经调过同源 hook，为就绪度取数）；
 * - 独立挂载 ⇒ 不传 `store`，本组件自己调 hook（自包含：单独 `render(<OperationPricePanel />)`
 *   即发起自己的读面）。
 *
 * `embedded=true` 只影响**区块标题**（指挥台的域标题已经回答「这是什么」），其余一字不变。
 */
import { Check, Pencil, Plus, RefreshCw, AlertCircle, X } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import {
  inputCls,
  metaInconsistentOf as metaInconsistent,
  metaTextOf as metaText,
  money,
  QtyFallbackBadge,
  QTY_RULE_MISSING_HINT,
  RulePriceCell,
  SourceBadge,
  workshopLabel,
  type MatrixRow,
} from '@/components/production-config/utils'
import { useOperationFeature, type OperationFeature } from '@/components/production-config/features'
import { cn } from '@/lib/utils'
import type { OperationPosition } from '@/types'

/** 单价格（就地可改）：`noPriceRow` = 工序库里有、价目行没有（**不可定价**，与「未定价」不同态） */
function OperationPriceCell({
  operation,
  cell,
  noPriceRow,
  editing,
  draft,
  busy,
  reasons,
  onStartEdit,
  onDraftChange,
  onSave,
  onCancel,
}: {
  operation: string
  cell: OperationPosition | null
  noPriceRow: boolean
  editing: boolean
  draft: string
  busy: boolean
  reasons: string[]
  onStartEdit: () => void
  onDraftChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  if (noPriceRow) {
    return (
      <span
        data-testid={`operation-price-${operation}`}
        data-state="no_row"
        title={`「${operation}」在工序库里有，但没有任何价目行（也就没法定价）。点行尾「管理▸」可停用或删除它；需要它干活请删除后用右上「新增工序」重建（新建工序会自动带上价目行）。`}
        className="text-neutral-500"
      >
        无价目行
      </span>
    )
  }
  const state = cell?.unit_price == null ? 'unpriced' : 'priced'
  const hasPrice = state === 'priced'
  return (
    <div
      data-testid={`operation-price-${operation}`}
      data-state={state}
      title={
        state === 'unpriced'
          ? `「${operation}」还没定价（≠ ¥0.00）`
          : `「${operation}」计件单价（给工人） ${money(cell?.unit_price)}`
      }
      className={cn(state === 'unpriced' ? 'text-amber-700' : 'text-neutral-900')}
    >
      {editing ? (
        <span className="flex items-center gap-1.5">
          <input
            value={draft}
            inputMode="decimal"
            aria-label={`${operation} 计件单价（给工人）`}
            data-testid={`operation-price-input-${operation}`}
            disabled={busy}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSave()}
            className={cn(
              'h-8 w-24 rounded border bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/15',
              reasons.length > 0 ? 'border-red-300 focus:border-red-400' : 'border-neutral-300 focus:border-primary-500',
            )}
          />
          <button
            type="button"
            aria-label="保存计件单价"
            data-testid={`operation-price-save-${operation}`}
            disabled={busy}
            onClick={onSave}
            className="rounded p-1 text-primary-600 hover:bg-neutral-100 disabled:opacity-50"
          >
            <Check className="w-4 h-4" />
          </button>
          <button
            type="button"
            aria-label="取消"
            data-testid={`operation-price-cancel-${operation}`}
            disabled={busy}
            onClick={onCancel}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </span>
      ) : (
        <span className="flex items-center gap-1.5">
          <span>{state === 'unpriced' ? '未定价' : money(cell?.unit_price)}</span>
          <button
            type="button"
            aria-label={`编辑「${operation}」计件单价（给工人）`}
            data-testid={`operation-price-edit-${operation}`}
            onClick={onStartEdit}
            className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
      {editing && reasons.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-red-600" data-testid={`operation-price-reasons-${operation}`}>
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

export function OperationPricePanel({
  store,
  embedded = false,
  hideActions = false,
}: {
  /** 共享同一份功能体状态（板子传入）；不传 ⇒ 本组件自包含地调同源 hook */
  store?: OperationFeature
  /** `true` ⇒ 不渲染本层区块标题（域标题由指挥台给） */
  embedded?: boolean
  /**
   * `true` ⇒ **不渲染本层的动作按钮组**（刷新 / 新增工序）。
   *
   * 🔴 板子（`ProcessConfigBoard`）用它 —— 那一屏的动作按钮在**页头**（`routings-new-operation`），
   * 面板再渲染一份 = 同一个 `data-testid` 出现两次（`getByTestId` 直接红）。独立挂载（指挥台 /
   * 单测）默认 `false`：这一域的功能面必须自带入口。
   */
  hideActions?: boolean
} = {}) {
  // ⚠️ hook 必须无条件调用（React 规则）；未传 `store` 时它就是本面板的自取数来源
  const own = useOperationFeature({ enabled: !store })
  const op = store ?? own

  const {
    catalogError, matrixError, rulesError, loading, error, load,
    search, setSearch,
    cellEditing, setCellEditing, cellDraft, setCellDraft, cellBusy, cellReasons, setCellReasons,
    manageOp, openWorkshops, setOpenWorkshops, editingVariantId, setEditingVariantId,
    variantDraft, setVariantDraft, variantBusy, variantReasons, opLevelReasons, setOpLevelReasons,
    confirmDeleteOpByName, setConfirmDeleteOpByName,
    confirmDeleteRuleId, setConfirmDeleteRuleId, ruleDeleteReasons, setRuleDeleteReasons, ruleBusy,
    ruleOptions, conditionFormOpen, setConditionFormOpen, conditionDraft, setConditionDraft,
    conditionReasons, editingRulePriceId, setEditingRulePriceId, rulePriceDraft, setRulePriceDraft,
    rulePriceReasons, setRulePriceReasons, rulePriceBusy,
    newOpOpen, setNewOpOpen, newOp, setNewOp, newOpReasons, setNewOpReasons, qtyRuleNotice, setQtyRuleNotice,
    newKind, setNewKind, newOption, setNewOption, newOptionReasons, setNewOptionReasons, busy,
    logicalOps, optionNames, operationsRows, visibleMatrixRows, visibleWorkshopGroups, unpricedCount,
    qtyRuleMissingOf, manageOpEntry, manageOpCells, manageVariants, manageUnlinked, manageTargetOp,
    manageConditions, deleteRuleTarget, opDeleteBlockerCells, deleteOpByNameTarget, deleteOpByNameCells,
    openCreateOperation, createOperation, createOptionRule, createCondition, openConditionForm,
    switchConditionKind, closeManage, openManageFor, cellKeyOf, saveCellPrice, cancelCellEdit,
    submitVariant, openDeleteOpByName, removeOpByName, disableOpByName, removeRule, saveRulePrice,
    cancelRulePrice, metaValues,
  } = op

  const workshopTitle = (group: string, count: number) =>
    `${group === '' ? '未分组' : workshopLabel(group)} · ${count} 道`

  return (
    <section className="space-y-4" data-testid="craft-operations-panel">
      {/* 本层面板标题（`embedded` 时不渲染 —— 域标题由指挥台给）；
          ⚠️ **动作按钮不随 `embedded` 消失**（它们是这一域的功能面，不是标题的一部分）；
          板子用 `hideActions` 单独去掉它（那一屏的按钮在页头，见该 prop 注释）。 */}
      {!embedded && (
        <div>
          <h2 className="text-base font-medium text-neutral-900">工序库 · 计件单价</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            一道工序一个价：报工工资 = 数量 × 计件单价。
          </p>
        </div>
      )}
      {!hideActions && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button variant="secondary" size="sm" data-testid="routings-new-operation" onClick={openCreateOperation}>
            <Plus className="w-4 h-4 mr-1.5" />
            新增工序
          </Button>
        </div>
      )}

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
        <div className="space-y-4">
          {/* 写面提示：刚建的工序不在算料目录内 ⇒ 数量按 1 计（提示条不是失败，可关闭） */}
          {qtyRuleNotice && (
            <p
              role="status"
              data-testid="qty-rule-hint"
              className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
            >
              {qtyRuleNotice}
              <button
                type="button"
                data-testid="qty-rule-hint-dismiss"
                aria-label="关闭提示"
                onClick={() => setQtyRuleNotice(null)}
                className="ml-2 text-xs text-amber-700 underline decoration-dotted hover:text-amber-900"
              >
                知道了
              </button>
            </p>
          )}
          <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="operation-price-matrix">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-base font-medium text-neutral-900">工艺项 · 计件单价（给工人）</h2>
                <span className="text-sm text-neutral-500">
                  <span data-testid="operation-price-matrix-total">{operationsRows.length}</span> 道工序 ·
                  一道工序一个价
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={cn(
                    'rounded px-2 py-0.5 text-xs',
                    unpricedCount > 0 ? 'bg-amber-50 text-amber-700' : 'bg-neutral-100 text-neutral-500',
                  )}
                  data-testid="matrix-unpriced-count"
                  title="这些工序还没定价 —— 报工按未定价处理，请补价"
                >
                  未定价 {unpricedCount} 项
                </span>
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索工序名…"
                  aria-label="搜索工序"
                  data-testid="operations-search"
                  className="h-8 w-40 rounded border border-neutral-300 bg-white px-2 text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
            </div>
            <p className="mb-3 text-xs text-neutral-500">
              这一屏的价是<strong>计件单价（给工人）</strong>：报工工资 = 数量 × 计件单价。
              <strong>一道工序一个价</strong>；
              <span className="text-amber-700">未定价</span> = 还没定价（≠ ¥0.00；真 0 元照显示 ¥0.00）。
              收顾客的那笔钱不在这里 —— 基础工序在「加工项组合费用」，特殊选项在每道工序的
              <strong>「适用条件」</strong>里（按套计价）。
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
                {operationsRows.length === 0
                  ? '暂无可定价的工序 —— 点右上「新增工序」建一道，再回这里定价'
                  : '没有匹配的工序，换个关键词试试'}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="operation-workshop-table">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="py-2 pr-4 font-medium whitespace-nowrap">工序</th>
                      <th className="py-2 pr-4 font-medium whitespace-nowrap">单价</th>
                      <th className="py-2 pr-4 font-medium whitespace-nowrap">分组 · 单位 · 操作</th>
                    </tr>
                  </thead>
                  {visibleWorkshopGroups.map((g) => (
                    <tbody key={g.group || '__ungrouped__'} data-testid={`matrix-workshop-${g.group || '未分组'}`}>
                      <tr className="border-b border-neutral-100 bg-neutral-50/60">
                        <td colSpan={3} className="py-1.5 pr-4">
                          <button
                            type="button"
                            aria-expanded={openWorkshops[g.group || '__ungrouped__'] !== false}
                            data-testid={`matrix-workshop-toggle-${g.group || '未分组'}`}
                            onClick={() =>
                              setOpenWorkshops((prev) => ({
                                ...prev,
                                [g.group || '__ungrouped__']: prev[g.group || '__ungrouped__'] === false,
                              }))
                            }
                            className="flex items-center gap-1.5 text-xs font-medium text-neutral-700"
                          >
                            <span aria-hidden>
                              {openWorkshops[g.group || '__ungrouped__'] === false ? '▸' : '▾'}
                            </span>
                            {workshopTitle(g.group, g.rows.length)}
                          </button>
                        </td>
                      </tr>
                      {openWorkshops[g.group || '__ungrouped__'] !== false &&
                        g.rows.map((row: MatrixRow) => {
                          const groups = metaValues(row, (c) => c.group, (o) => o.group)
                          const units = metaValues(row, (c) => c.unit, (o) => o.unit)
                          const inconsistent = metaInconsistent(groups) || metaInconsistent(units)
                          const key = cellKeyOf(row.operation)
                          return (
                            <tr
                              key={row.operation}
                              className="border-b border-neutral-100 last:border-0"
                              data-testid={`matrix-row-${row.operation}`}
                              data-operation={row.operation}
                            >
                              <td className="py-2.5 pr-4 align-top">
                                <div className="text-neutral-900">{row.operation}</div>
                                {qtyRuleMissingOf(row.operation) && (
                                  <QtyFallbackBadge testId={`matrix-qty-fallback-${row.operation}`} />
                                )}
                              </td>
                              <td className="py-2.5 pr-4 align-top">
                                <OperationPriceCell
                                  operation={row.operation}
                                  cell={row.cell}
                                  noPriceRow={!row.cell}
                                  editing={cellEditing === key}
                                  draft={cellDraft}
                                  busy={cellBusy}
                                  reasons={cellEditing === key && cellReasons?.key === key ? cellReasons.items : []}
                                  onStartEdit={() => {
                                    setCellEditing(key)
                                    setCellDraft(row.cell && row.cell.unit_price != null ? String(row.cell.unit_price) : '')
                                    setCellReasons(null)
                                  }}
                                  onDraftChange={setCellDraft}
                                  onSave={() => row.cell && saveCellPrice(row.cell)}
                                  onCancel={cancelCellEdit}
                                />
                              </td>
                              <td
                                className="py-2.5 pr-4 align-top"
                                data-testid={`matrix-meta-${row.operation}`}
                                data-inconsistent={inconsistent ? 'true' : undefined}
                                title={inconsistent ? '分组 / 单位不一致，已逐个列出' : undefined}
                              >
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-xs text-neutral-500">
                                    {groups.length === 0 && units.length === 0
                                      ? '—'
                                      : `${metaText(groups)} · ${metaText(units)}`}
                                  </span>
                                  <button
                                    type="button"
                                    data-testid={`matrix-manage-${row.operation}`}
                                    onClick={() => openManageFor(row.operation)}
                                    title="管理这道工序的设置：分组 / 单位 / 停用 / 删除"
                                    className="rounded px-1.5 py-0.5 text-xs text-primary-700 hover:bg-neutral-100"
                                  >
                                    管理▸
                                  </button>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                    </tbody>
                  ))}
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {/* 「管理▸」抽屉：该逻辑工序的设置维护面（分组 / 单位 / 停用 / 删除 / 适用条件） */}
      <Modal
        open={manageOp !== null}
        onClose={closeManage}
        title={manageOp ? `「${manageOp}」的设置` : ''}
        width={760}
        footer={
          <div className="flex w-full flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              data-testid="operations-manage-disable"
              disabled={variantBusy || !manageTargetOp}
              onClick={() => manageTargetOp && void disableOpByName(manageTargetOp)}
            >
              停用
            </Button>
            <Button
              size="sm"
              variant="secondary"
              data-testid="operations-manage-delete"
              disabled={variantBusy || !manageTargetOp}
              onClick={openDeleteOpByName}
            >
              删除
            </Button>
            <span className="text-xs text-neutral-400">删除后历史报工不受影响</span>
            <Button variant="secondary" className="ml-auto" data-testid="operations-manage-close" onClick={closeManage}>
              关闭
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm" data-testid="operations-manage-drawer">
          <p className="text-neutral-600">
            这道工序的设置。<strong>分组</strong>与<strong>单位</strong>决定报工口径；
            下方「适用条件」决定它<strong>什么情况下做</strong>。
          </p>
          {manageOp && qtyRuleMissingOf(manageOp) && (
            <p
              className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
              data-testid="operations-manage-qty-fallback"
            >
              {QTY_RULE_MISSING_HINT}
            </p>
          )}
          {opLevelReasons && (
            <ul className="space-y-0.5 text-xs text-red-600" data-testid="operations-manage-op-reasons">
              {opLevelReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {variantReasons && (
            <ul className="space-y-0.5 text-xs text-red-600" data-testid="variant-reasons">
              {variantReasons.items.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {manageVariants.length === 0 ? (
            <div className="py-4 text-center" data-testid="operations-manage-empty">
              <p className="text-sm text-neutral-500">
                「{manageOp}」在<strong>工序库</strong>里有这一行，但它在价目表里
                {manageOpCells.length > 0 ? (
                  <>有 {manageOpCells.length} 行，而这些行<strong>都没有关联到它</strong></>
                ) : (
                  <><strong>还没有任何价目行</strong></>
                )}
                ⇒ 它现在不出现在加工单里，也没法定价。
              </p>
              <p className="mt-1 text-xs text-neutral-400">
                点下面的「删除这道工序」把它删掉；如果只是列表没加载全，点右上「刷新」重试。
              </p>
              <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  data-testid="operations-manage-delete-empty"
                  disabled={variantBusy || !manageOpEntry}
                  onClick={openDeleteOpByName}
                >
                  删除这道工序
                </Button>
              </div>
            </div>
          ) : (
            <div className="divide-y divide-neutral-100">
              {manageUnlinked.length > 0 && (
                <p
                  className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800"
                  data-testid="operations-manage-unlinked-hint"
                >
                  ⚠️ 这道工序有
                  <strong className="mx-1">{manageUnlinked.length}</strong>
                  条设置<strong>没有关联到它</strong>（价目行指向的不是这道工序）——
                  下面带「这些行指向的不是这道工序」标记的行<strong>不提供设置</strong>（改它们就是改另一道工序）；
                  点底部<strong className="mx-1">删除</strong>可直接删掉这道工序。
                </p>
              )}
              {manageVariants.map((v) => (
                <div key={v.id} className="py-3" data-testid={`variant-row-${v.id}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-neutral-900">{manageOp}</span>
                    {v.source && <SourceBadge source={v.source} testId={`variant-source-${v.id}`} />}
                    {v.foreign && (
                      <span
                        className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700"
                        data-testid={`variant-foreign-${v.id}`}
                      >
                        这些行指向的不是这道工序
                      </span>
                    )}
                  </div>

                  {v.foreign ? (
                    <p className="mt-2 text-xs text-neutral-500" data-testid={`variant-foreign-note-${v.id}`}>
                      价目表里这几行关联到的是另一道工序 ⇒ 这里不提供设置；请到那道工序的抽屉里改，
                      或点底部「删除」把本工序删掉。
                    </p>
                  ) : (
                    <>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {editingVariantId === v.id ? (
                          <>
                            <input
                              aria-label="分组"
                              data-testid={`variant-group-input-${v.id}`}
                              className={cn(inputCls, 'h-8 w-28')}
                              value={variantDraft.group_name}
                              onChange={(e) => setVariantDraft({ ...variantDraft, group_name: e.target.value })}
                            />
                            <input
                              aria-label="单位"
                              data-testid={`variant-unit-input-${v.id}`}
                              className={cn(inputCls, 'h-8 w-24')}
                              value={variantDraft.unit}
                              onChange={(e) => setVariantDraft({ ...variantDraft, unit: e.target.value })}
                            />
                            <Button
                              size="sm"
                              data-testid={`variant-meta-save-${v.id}`}
                              disabled={variantBusy}
                              onClick={() =>
                                void submitVariant(v.id, {
                                  group_name: variantDraft.group_name,
                                  unit: variantDraft.unit,
                                })
                              }
                            >
                              保存
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              data-testid={`variant-meta-cancel-${v.id}`}
                              onClick={() => setEditingVariantId(null)}
                            >
                              取消
                            </Button>
                          </>
                        ) : (
                          <>
                            <span className="text-neutral-600">
                              分组「{v.group ?? '—'}」 · 单位「{v.unit ?? '—'}」
                            </span>
                            <button
                              type="button"
                              aria-label={`编辑「${manageOp}」的分组与单位`}
                              data-testid={`variant-meta-edit-${v.id}`}
                              onClick={() => {
                                setEditingVariantId(v.id)
                                setVariantDraft({ group_name: v.group ?? '', unit: v.unit ?? '' })
                              }}
                              className="inline-flex items-center gap-1 rounded border border-neutral-200 px-1.5 py-0.5 text-xs text-neutral-600 hover:bg-neutral-50 hover:text-neutral-800"
                            >
                              <Pencil className="w-3 h-3" />
                              改分组 / 单位
                            </button>
                          </>
                        )}
                      </div>

                      <p className="mt-1 text-xs text-neutral-500" data-testid={`variant-meta-note-${v.id}`}>
                        {v.group && v.unit ? (
                          <>工人在「{v.group}」报工、按「{v.unit}」计数（报工工资 = 数量 × 计件单价）。</>
                        ) : (
                          <>分组与单位决定报工口径（工人在哪个组报工、按什么计数）—— 这条还没配全，点「改分组 / 单位」补上。</>
                        )}
                        {v.source === '占位待确认' && (
                          <> 单价还是套模板时的<strong>初始价</strong>：确认后改成实际工价（改价只影响新报工，历史报工按当时价）。</>
                        )}
                      </p>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 适用条件（挂在工序身上；写面复用 POST/DELETE /route-rules） */}
          <div className="rounded border border-neutral-200 bg-neutral-50 p-3" data-testid="operation-conditions">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-neutral-900">适用条件</span>
              <span className="text-xs text-neutral-500">这道工序在什么情况下做</span>
              <Button size="sm" className="ml-auto" data-testid="operation-condition-add" onClick={openConditionForm}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                添加条件
              </Button>
            </div>

            <p className="mt-1 text-xs text-neutral-400">
              条件里的名字<strong>逐字取自</strong>订单里的特殊选项 / 加工项 / 部位（错一个字就不会命中）。
              特殊选项按<strong>套</strong>收费（元/套）；加工项与部位不按套计价。
            </p>

            {rulesError ? (
              <p
                className="mt-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600"
                data-testid="operation-conditions-error"
              >
                {rulesError}
              </p>
            ) : manageConditions.length === 0 ? (
              <p className="mt-2 text-xs text-neutral-400" data-testid="operation-conditions-empty">
                没有额外条件 —— 无论订单选什么工艺、什么特殊选项，这道工序都按主线做。
              </p>
            ) : (
              <ul className="mt-2 divide-y divide-neutral-100">
                {manageConditions.map((rule) => (
                  <li
                    key={rule.id}
                    className="flex flex-wrap items-center gap-2 py-2"
                    data-testid={`operation-condition-${rule.id}`}
                  >
                    <span className="text-neutral-800" data-testid={`operation-condition-text-${rule.id}`}>
                      {op.conditionTextOf(rule)}
                    </span>
                    {rule.trigger_kind === 'option' && (
                      <RulePriceCell
                        rule={rule}
                        editing={editingRulePriceId === rule.id}
                        draft={rulePriceDraft}
                        busy={rulePriceBusy}
                        reasons={editingRulePriceId === rule.id ? rulePriceReasons : []}
                        onStartEdit={() => {
                          setEditingRulePriceId(rule.id)
                          setRulePriceDraft(rule.customer_unit_price == null ? '' : String(rule.customer_unit_price))
                          setRulePriceReasons([])
                        }}
                        onDraftChange={setRulePriceDraft}
                        onSave={() => void saveRulePrice(rule)}
                        onCancel={cancelRulePrice}
                      />
                    )}
                    <button
                      type="button"
                      data-testid={`operation-condition-delete-${rule.id}`}
                      onClick={() => {
                        setConfirmDeleteRuleId(rule.id)
                        setRuleDeleteReasons(null)
                      }}
                      className="ml-auto rounded px-1.5 py-1 text-xs text-neutral-500 hover:bg-neutral-100 hover:text-red-600"
                    >
                      删除
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {conditionFormOpen && (
              <div className="mt-3 space-y-2 rounded border border-neutral-200 bg-white p-3" data-testid="operation-condition-form">
                <div>
                  <span className="mb-1 block text-xs text-neutral-600">什么时候</span>
                  <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="什么时候">
                    {([
                      { key: 'option', label: '特殊选项' },
                      { key: 'processing_item', label: '加工项' },
                      { key: 'position', label: '部位' },
                    ] as const).map((k) => (
                      <button
                        key={k.key}
                        type="button"
                        role="radio"
                        aria-checked={conditionDraft.trigger_kind === k.key}
                        data-testid={`condition-kind-${k.key}`}
                        onClick={() => switchConditionKind(k.key)}
                        className={cn(
                          'rounded-full border px-3 py-1 text-sm transition-colors',
                          conditionDraft.trigger_kind === k.key
                            ? 'border-primary-600 bg-neutral-50 font-medium text-primary-700'
                            : 'border-neutral-300 text-neutral-600 hover:bg-neutral-50',
                        )}
                      >
                        {k.label}
                      </button>
                    ))}
                  </div>
                  <select
                    id="condition-value"
                    aria-label="什么时候生效"
                    data-testid="condition-value"
                    className={cn(inputCls, 'mt-2')}
                    value={conditionDraft.trigger_value}
                    onChange={(e) => setConditionDraft((d) => ({ ...d, trigger_value: e.target.value }))}
                  >
                    <option value="">
                      {conditionDraft.trigger_kind === 'processing_item'
                        ? '从加工项列表里选…'
                        : conditionDraft.trigger_kind === 'position'
                          ? '从部位列表里选…'
                          : '从特殊选项列表里选…'}
                    </option>
                    {(conditionDraft.trigger_kind === 'processing_item'
                      ? ruleOptions.processing_items
                      : conditionDraft.trigger_kind === 'position'
                        ? ruleOptions.positions
                        : optionNames
                    ).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-neutral-600" htmlFor="condition-action">
                    做还是不做
                  </label>
                  <select
                    id="condition-action"
                    data-testid="condition-action"
                    className={inputCls}
                    value={conditionDraft.action}
                    onChange={(e) => {
                      const action = e.target.value as 'insert' | 'remove'
                      setConditionDraft((d) => ({ ...d, action, after_operation: '' }))
                    }}
                  >
                    <option value="insert">做（订单命中时加上这道工序）</option>
                    <option value="remove">不做（订单命中时去掉这道工序）</option>
                  </select>
                </div>

                {conditionDraft.action === 'insert' && (
                  <div>
                    <label className="mb-1 block text-xs text-neutral-600" htmlFor="condition-anchor">
                      插在哪道工序之后
                    </label>
                    <select
                      id="condition-anchor"
                      data-testid="condition-anchor"
                      className={inputCls}
                      value={conditionDraft.after_operation}
                      onChange={(e) => setConditionDraft((d) => ({ ...d, after_operation: e.target.value }))}
                    >
                      <option value="">放到最后（末尾）</option>
                      {logicalOps.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {conditionReasons.length > 0 && (
                  <ul className="space-y-0.5 text-xs text-red-600" data-testid="condition-add-reasons">
                    {conditionReasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}

                <div className="flex justify-end gap-2">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    data-testid="condition-add-cancel"
                    onClick={() => setConditionFormOpen(false)}
                  >
                    取消
                  </Button>
                  <Button loading={busy} data-testid="condition-add-submit" onClick={createCondition}>
                    保存
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* 新增（类型二选一：工序 / 特殊选项） */}
      <Modal
        open={newOpOpen}
        onClose={() => !busy && setNewOpOpen(false)}
        title="新增"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setNewOpOpen(false)}>
              取消
            </Button>
            <Button
              loading={busy}
              data-testid="routings-create-operation-submit"
              onClick={newKind === 'option' ? createOptionRule : createOperation}
            >
              保存
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <div className="flex gap-2" role="radiogroup" aria-label="新增类型">
            {([
              { key: 'operation', label: '工序' },
              { key: 'option', label: '特殊选项' },
            ] as const).map((k) => (
              <button
                key={k.key}
                type="button"
                role="radio"
                aria-checked={newKind === k.key}
                data-testid={`create-kind-${k.key}`}
                onClick={() => {
                  setNewKind(k.key)
                  setNewOptionReasons([])
                }}
                className={cn(
                  'rounded-full border px-3 py-1 text-sm transition-colors',
                  newKind === k.key
                    ? 'border-primary-600 bg-neutral-50 font-medium text-primary-700'
                    : 'border-neutral-300 text-neutral-600 hover:bg-neutral-50',
                )}
              >
                {k.label}
              </button>
            ))}
          </div>
          <p className="text-neutral-600" data-testid="create-kind-two-ledgers">
            工序的价是<strong>给工人的计件</strong>（元/件·米·折）；特殊选项的价是
            <strong>对顾客的按套</strong>（元/套）。两者是两本账，互不换算。
          </p>

          {newKind === 'operation' ? (
            <>
              <p className="text-neutral-600">
                单价直接决定工人计件工资，请与车间核对后再填（调价只影响新报工，历史报工按当时价）。
              </p>
              {([
                { key: 'name', label: '工序名称', ph: '如 罗马帘穿杆', hint: '工序名只写这道活本身（如「精裁」「三边」），不要带任何前缀或后缀' },
                { key: 'group_name', label: '分组', ph: '裁剪 / 车位 / 后道 / 其他' },
                { key: 'unit', label: '单位', ph: '米 / 套 / 件 / 个 / 折' },
              ] as { key: string; label: string; ph: string; hint?: string }[]).map((f) => (
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
                  {f.hint && (
                    <p className="mt-1 text-xs text-neutral-400" data-testid={`routings-create-op-${f.key}-hint`}>
                      {f.hint}
                    </p>
                  )}
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

              {newOpReasons.length > 0 && (
                <ul className="space-y-0.5 text-xs text-red-600" data-testid="routings-create-op-reasons">
                  {newOpReasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-trigger_value">
                  选项名称
                </label>
                <input
                  id="new-option-trigger_value"
                  data-testid="routings-create-option-trigger_value"
                  className={inputCls}
                  placeholder="如 拼3次 / 免熨 / 防翘扣"
                  value={newOption.trigger_value}
                  onChange={(e) => setNewOption({ ...newOption, trigger_value: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-customer_unit_price">
                  单价（元/套）
                </label>
                <input
                  id="new-option-customer_unit_price"
                  inputMode="decimal"
                  data-testid="routings-create-option-customer_unit_price"
                  className={inputCls}
                  placeholder="如 12.5"
                  value={newOption.customer_unit_price}
                  onChange={(e) => setNewOption({ ...newOption, customer_unit_price: e.target.value })}
                />
                <p className="mt-1 text-xs text-neutral-400">
                  这是对顾客的按套价（元/套），不进工人的计件工资。
                </p>
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-operation">
                  这道选项落在哪道工序上
                </label>
                <select
                  id="new-option-operation"
                  data-testid="routings-create-option-operation"
                  className={inputCls}
                  value={newOption.operation}
                  onChange={(e) =>
                    setNewOption({
                      ...newOption,
                      operation: e.target.value,
                      after_operation: e.target.value ? op.anchorDefaultFor(e.target.value) : '',
                    })
                  }
                >
                  <option value="">选择这条选项落在哪道工序上…</option>
                  {logicalOps.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-neutral-600" htmlFor="new-option-after_operation">
                  插在哪道工序之后（可选）
                </label>
                <select
                  id="new-option-after_operation"
                  data-testid="routings-create-option-after_operation"
                  className={inputCls}
                  value={newOption.after_operation}
                  onChange={(e) => setNewOption({ ...newOption, after_operation: e.target.value })}
                >
                  <option value="">放到最后（末尾）</option>
                  {logicalOps.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-neutral-400">
                  已按这道工序现有的位置填好默认值，通常不用改。
                </p>
              </div>
              {newOptionReasons.length > 0 && (
                <ul className="space-y-0.5 text-xs text-red-600" data-testid="routings-create-option-reasons">
                  {newOptionReasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </Modal>

      {/* 删除一条适用条件的二次确认（内容用人话说清删的是哪一条） */}
      <Modal
        open={deleteRuleTarget !== null}
        onClose={() => !ruleBusy && setConfirmDeleteRuleId(null)}
        title="删除这条适用条件"
        footer={null}
      >
        {deleteRuleTarget && (
          <div data-testid="route-rule-delete-modal" data-rule={deleteRuleTarget.id} className="space-y-3 text-sm">
            <p className="text-neutral-600">
              将删除这条条件：<strong className="ml-1">{op.conditionTextOf(deleteRuleTarget)}</strong>
            </p>
            <p className="text-neutral-500">
              删除后，订单命中这个条件时<strong>不再</strong>增删「{deleteRuleTarget.operation ?? '—'}」这道工序
              （加工单按当前主线生成）。历史加工单一字不变。
            </p>
            {ruleDeleteReasons && (
              <ul className="space-y-0.5 text-xs text-red-600" data-testid="route-rule-delete-reasons">
                {ruleDeleteReasons.items.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={ruleBusy}
                data-testid={`route-rule-delete-cancel-${deleteRuleTarget.id}`}
                onClick={() => setConfirmDeleteRuleId(null)}
              >
                取消
              </Button>
              <Button
                variant="danger"
                loading={ruleBusy}
                data-testid={`route-rule-delete-confirm-${deleteRuleTarget.id}`}
                onClick={() => void removeRule(deleteRuleTarget)}
              >
                确认删除
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* 删除工序的二次确认（目标 = 抽屉当前展示的那一行；与价目行是否关联得上无关） */}
      <Modal
        open={deleteOpByNameTarget !== null}
        onClose={() => !variantBusy && setConfirmDeleteOpByName(null)}
        title="删除工序"
        footer={null}
      >
        {deleteOpByNameTarget && (
          <div
            data-testid="operations-manage-delete-modal"
            data-operation={deleteOpByNameTarget.op.name}
            className="space-y-3 text-sm"
          >
            <p className="text-neutral-600">
              将删除工序<strong className="mx-1">「{deleteOpByNameTarget.op.name}」</strong>
              （{deleteOpByNameTarget.candidates > 1
                ? `工序库里有 ${deleteOpByNameTarget.candidates} 行同名，删除的是其中一行`
                : '工序库里的这一行'}）。
            </p>
            <p className="text-neutral-500">
              删除后它不再出现在工序库与工序单价表里，新加工单不会再生成这道工序；
              <strong>历史报工不受影响</strong>（以前报过的工按当时的工序算）。
            </p>
            {deleteOpByNameCells.length === 0 ? (
              <p
                className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-neutral-600"
                data-testid="operations-manage-delete-nocells"
              >
                这道工序<strong>没有挂任何价目行</strong> ⇒ 删除不会有行需要摘。
              </p>
            ) : opDeleteBlockerCells.length > 0 ? (
              <p
                className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800"
                data-testid="operations-manage-delete-cells"
              >
                它在价目表里共 {deleteOpByNameCells.length} 行，其中
                <strong className="mx-1">{opDeleteBlockerCells.length}</strong>
                行还是「做」。点「确认删除」：系统会把这几行<strong>设为不做</strong>，
                然后删除这道工序（一次完成，不留半成品）；
                <strong>历史报工不受影响</strong>（以前报过的工按当时的工序算）。
              </p>
            ) : (
              <p
                className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800"
                data-testid="operations-manage-delete-cells"
              >
                它在价目表里共 {deleteOpByNameCells.length} 行，且都已经是「不做」⇒ 删除时这些行会一起清掉；
                <strong>历史报工不受影响</strong>。
              </p>
            )}
            {opLevelReasons && (
              <ul className="space-y-0.5 text-xs text-red-600" data-testid="operations-manage-delete-reasons">
                {opLevelReasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
                disabled={variantBusy}
                data-testid="operations-manage-delete-cancel"
                onClick={() => {
                  setConfirmDeleteOpByName(null)
                  setOpLevelReasons(null)
                }}
              >
                取消
              </Button>
              <Button
                variant="danger"
                loading={variantBusy}
                data-testid="operations-manage-delete-confirm"
                onClick={() => void removeOpByName(deleteOpByNameTarget.op)}
              >
                确认删除
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </section>
  )
}

export default OperationPricePanel
