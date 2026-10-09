'use client'

/**
 * **工艺路线 + 路线规则面板**（issue #6585 P1：配置指挥台 v2 的「工艺路线」域）。
 *
 * ## 它是什么
 *
 * 板子（`ProcessConfigBoard`）原 tab「工序管理」的第二大块（`routings-list`）：
 * 具名路线列表（默认徽标 + 主线道数 + 空壳标记 + 编辑主线 / 改名 / 设为默认 / 删除）
 * 与「适用条件」（路线规则 `GET/POST/DELETE /route-rules`）的读写。
 *
 * ## 单一实现（issue #6585 集成口径）
 *
 * 🔴 状态 / 读面 / 写面 / 派生视图全在 `features.ts` 的 `useRoutingsFeature()` 里**一份**；
 * 板子与独立挂载**都渲染本组件**：板子传 `store`（它已调过同源 hook），独立挂载不传 ⇒
 * 本组件自己调 hook（自包含：单独 `render(<RoutingsPanel />)` 即发起自己的读面）。
 * `embedded=true` 只影响**区块标题**，其余一字不变。
 */
import { AlertCircle, ArrowDown, ArrowUp, Check, Pencil, Plus, RefreshCw, Star, Trash2, X } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import { conditionText, inputCls, money, RulePriceCell } from '@/components/production-config/utils'
import { useRoutingsFeature, type RoutingsFeature } from '@/components/production-config/features'
import { cn } from '@/lib/utils'
import type { RouteRule } from '@/types'


export function RoutingsPanel({
  store,
  embedded = false,
  hideActions = false,
}: {
  /** 共享同一份功能体状态（板子传入）；不传 ⇒ 本组件自包含地调同源 hook */
  store?: RoutingsFeature
  /** `true` ⇒ 不渲染本层区块标题（域标题由指挥台给） */
  embedded?: boolean
  /**
   * `true` ⇒ **不渲染本层的动作按钮组**（刷新 / 新建路线）。
   *
   * 🔴 板子（`ProcessConfigBoard`）用它 —— 那一屏的动作按钮在**页头**（`routings-new-route`），
   * 面板再渲染一份 = 同一个 `data-testid` 出现两次（`getByTestId` 直接红）。独立挂载默认 `false`。
   */
  hideActions?: boolean
} = {}) {
  // hook 必须无条件调用；未传 `store` 时它就是本面板的自取数来源。
  // ⚠️ 独立挂载时 `libraryByName` / `matrixOps` 由 `useRoutingsFeature` 内部的价目行自建
  //（它自己也读一次 `operation-positions` 用于主线 chips 的「工序是否存在」判据）。
  // 传了 `store` ⇒ `enabled=false`：板子已用同源 hook 取过同一份（不重复发请求）。
  const own = useRoutingsFeature({ enabled: !store })
  const rt = store ?? own

  const {
    rules, rulesError, loading, error, load,
    picked, setPicked, editingId, draft, saving, reasons, localReason,
    renameTarget, setRenameTarget, renameDraft, setRenameDraft, confirmAction, setConfirmAction, opReasons,
    ruleOptions, confirmDeleteRuleId, setConfirmDeleteRuleId, ruleDeleteReasons, setRuleDeleteReasons,
    ruleBusy, editingRulePriceId, setEditingRulePriceId, rulePriceDraft, setRulePriceDraft,
    rulePriceReasons, setRulePriceReasons, rulePriceBusy,
    newRouteOpen, setNewRouteOpen, newRoute, setNewRoute, busy,
    routeList, paletteOps, stepView, draftSteps, missingSteps, anchorDefaultFor,
    openEditor, closeEditor, addFromPalette, move, removeAt, saveSequence, createRoute, openRename,
    submitRename, runConfirm, deleteBlockReasons, removeRule, saveRulePrice, cancelRulePrice,
    deleteRuleTarget, routings,
    addConditionOp, setAddConditionOp, createCondition, logicalOps, optionNames,
  } = rt

  return (
    <section className="space-y-4" data-testid="routings-panel">
      {/* 本层面板标题（`embedded` 时不渲染 —— 域标题由指挥台给）；
          ⚠️ **动作按钮不随 `embedded` 消失**（它们是这一域的功能面，不是标题的一部分）；
          板子用 `hideActions` 单独去掉它（那一屏的按钮在页头，见该 prop 注释）。 */}
      {!embedded && (
        <div>
          <h2 className="text-base font-medium text-neutral-900">工艺路线（路线与规则）</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            一条路线 = 一条有序主线；订单按命中的主线走。
          </p>
        </div>
      )}
      {!hideActions && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button size="sm" data-testid="routings-new-route" onClick={() => setNewRouteOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建路线
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
          <section className="rounded-lg border border-neutral-200 bg-white p-5" data-testid="routings-list">
            <div className="mb-3 flex items-baseline gap-2">
              <h2 className="text-base font-medium text-neutral-900">工艺路线</h2>
              <span className="text-sm text-neutral-500">
                共 <span data-testid="routings-total">{routings?.total ?? 0}</span> 条 · 每条 = 一条有序主线
              </span>
            </div>

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
                暂无工艺路线 —— 点右上「新建路线」建一条（一条路线 = 一条有序主线）
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

                          <span className="text-xs text-neutral-400" data-testid={`routing-mainline-count-${id}`}>
                            主线 {mainline.length} 道
                          </span>
                          {isEmptyShell && (
                            <span
                              data-testid={`routing-empty-shell-${id}`}
                              title="主线为空：这条路线被命中后一道工序都没有 —— 既不报错也不拦，该订单会拿到 0 道工序"
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
                            {!routing.is_default && (
                              <Button
                                variant="secondary"
                                size="sm"
                                data-testid={`routing-set-default-${id}`}
                                onClick={() => {
                                  setOpReasonsReset(setConfirmAction, routing)
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
                                setOpReasonsReset(setConfirmAction, routing, 'delete')
                              }}
                            >
                              <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                              删除
                            </Button>
                          </div>
                        )}
                      </div>

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
                          {missingSteps.length > 0 && (
                            <p
                              className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600"
                              data-testid={`routing-precheck-missing-${id}`}
                            >
                              有 {missingSteps.length} 道工序在工序库中不存在或已停用（
                              {missingSteps.map((s) => s.operation).join('、')}
                              ）—— 保存会被拒，请先到「工序库」点「新增工序」把它建出来，
                              或把它从主线里移除。
                            </p>
                          )}

                          <div className="flex flex-wrap items-center gap-2">
                            <select
                              aria-label="从工序库添加工序"
                              data-testid={`routing-add-select-${id}`}
                              value={picked}
                              onChange={(e) => setPicked(e.target.value)}
                              className="h-9 min-w-56 flex-1 rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500"
                            >
                              <option value="">从工序库选择要添加的工序…</option>
                              {paletteOps.map((o) => (
                                <option key={o.name} value={o.name}>
                                  {o.name}
                                  {o.groups.length > 0 ? `（${o.groups.join(' / ')}）` : ''}
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
                              主线为空：从上方「从工序库选择要添加的工序…」选一道点「加入」
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
                                      {step.group ?? '—'} · {step.unit ?? '—'}
                                    </span>
                                  )}
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

        </div>
      )}

      {/* 新建路线：只问名字（`POST /routings` 不再传 `positions`） */}
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
              路线名称（如 窗帘工序路线 / 加急专线）
            </label>
            <input
              id="new-route-name"
              data-testid="routings-create-name"
              className={inputCls}
              value={newRoute.name}
              onChange={(e) => setNewRoute({ ...newRoute, name: e.target.value })}
            />
          </div>
        </div>
      </Modal>

      {/* 改名：只改路线总名（不给 mainline ⇒ 服务端不动序列） */}
      <Modal open={!!renameTarget} onClose={() => !busy && setRenameTarget(null)} title="更改路线名称" footer={null}>
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

      {/* 删除一条适用条件的二次确认（内容用**人话**说清删的是哪一条） */}
      <Modal
        open={deleteRuleTarget !== null}
        onClose={() => !ruleBusy && setConfirmDeleteRuleId(null)}
        title="删除这条适用条件"
        footer={null}
      >
        {deleteRuleTarget && (
          <div data-testid="route-rule-delete-modal" data-rule={deleteRuleTarget.id} className="space-y-3 text-sm">
            <p className="text-neutral-600">
              将删除这条条件：<strong className="ml-1">{conditionText(deleteRuleTarget)}</strong>
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

    </section>
  )
}

/** 打开二次确认前清掉上一轮的操作理由（与板子同一形态，不把上一轮理由带进新弹框） */
function setOpReasonsReset(
  setConfirmAction: (v: { kind: 'delete' | 'default'; routing: import('@/types').Routing } | null) => void,
  routing: import('@/types').Routing,
  kind: 'delete' | 'default' = 'default',
) {
  setConfirmAction({ kind, routing })
}

export default RoutingsPanel
