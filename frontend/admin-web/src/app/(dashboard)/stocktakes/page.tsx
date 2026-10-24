'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button, EmptyState, Input, Modal, PageCard, PageHeader } from '@/components/ui'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { displayEnum } from '@/lib/enum-display'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { stocktakeApi, warehouseApi } from '@/lib/api'
import { formatStockQuantity } from '@/lib/stock-quantity'
import { usePermission } from '@/lib/permission'
import RequestApprovalModal from '@/components/approvals/RequestApprovalModal'
import { stocktakeDiffDraft, type ApprovalDraft } from '@/lib/approval-request'
import type { Stocktake, StocktakeLine, StocktakeStatus, Warehouse } from '@/types/stocktake'

/**
 * 盘点单 `/stocktakes`（issue #7373，P1-1 段 2 后端 / 本页 = 商家面）。
 *
 * ## 它是什么
 *
 * 一张盘点单 = **某个仓**的账面快照（出任务当刻逐批次抄 `bookQty` = **这一卷还剩多少米**，
 * 派生 = 入库米数 − 已派工消耗；issue #7618 改前抄的是原始入库量，裁剪过的批次账面偏高）
 * + 逐批次录实盘。
 * 完成时服务端按差异调整 `stock_batches.quantity`；**有差异必须有已通过的「盘点差异」审批**，
 * 否则**写面直接拒**（不是前端提示）—— 本页把那句服务端原文原样显示，不吞成「操作失败」。
 *
 * ## 🔴 三个「不许画成 0」的地方（与 P3 口径同源：未采集 ≠ 0）
 *
 * 1. 没数的行：实盘量显示「未数」（不是 `0`）——「还没数」和「数出来是 0」是两件事；
 * 2. 差异：只显示**服务端**算出的 `diffQty`（不前端现算，避免与写面口径分叉）；
 * 3. 差异合计：只有**全部批次都数过**才给数；否则写「待录入（还有 N 个批次没数）」。
 *
 * ## 权限
 *
 * 读 `inbound:view`（菜单/路由守卫同码）、写 `inbound:create` —— 与仓/库存**同域复用既有码**，
 * 零授权 delta（新造 `stocktake:*` 会让页面与菜单对所有人不可见，#4203 同族坑）。
 *
 * ## 边界（照实登记）
 *
 * - 不在本页建仓 / 改仓（仓库主数据归仓储域；本页只**选**仓）；
 * - 不做「周期盘点计划」（到点自动出任务属后续段）；
 * - 完成/作废都只有一步确认：不可逆的是**库存数量调整**，而它被审批闸门挡在服务端。
 */

const STATUS_LABEL: Record<StocktakeStatus, string> = {
  counting: '盘点中',
  completed: '已完成',
  cancelled: '已作废',
}

const STATUS_BADGE: Record<StocktakeStatus, string> = {
  counting: 'bg-amber-50 text-amber-700',
  completed: 'bg-emerald-50 text-emerald-700',
  cancelled: 'bg-neutral-100 text-neutral-500',
}

/** 数量上屏：`null` = 还没数 ⇒ 「未数」（**不是** `-`、更不是 `0`）。 */
function qtyText(value: number | null | undefined): string {
  return value === null || value === undefined ? '未数' : formatStockQuantity(value)
}

/**
 * 差异合计：**全部数完才有数**。
 *
 * 部分未数时返回 `null`（调用方写「待录入」）—— 把没数的批次当 0 相加会得到一个
 * **看起来已对账**的合计，正是「未采集画成 0」的同类事故。
 */
export function diffTotal(items: StocktakeLine[]): number | null {
  if (items.length === 0) return null
  if (items.some((i) => i.countedQty === null || i.countedQty === undefined)) return null
  return items.reduce((sum, i) => sum + (i.diffQty ?? 0), 0)
}

/**
 * 实盘量输入校验：**允许 0**（盘亏到 0 是真实结果）、最多 1 位小数、不许负数/非数。
 *
 * ⚠️ 不能复用 `checkStockQuantity`：那条口径是**入库**数量「必须 > 0」（#5153），
 * 而盘点恰恰要能数出 0 —— 复用它会把「这个批次盘空了」挡在门外。
 */
export function checkCountedQty(raw: string): string | null {
  const text = raw.trim()
  if (!/^\d+(\.\d)?$/.test(text)) return '实盘量必须是 0 或正数，最多 1 位小数'
  return null
}

export default function StocktakesPage() {
  const { has } = usePermission()
  const canWrite = has('inbound:create')

  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [rows, setRows] = useState<Stocktake[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Stocktake | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [counts, setCounts] = useState<Record<number, string>>({})
  const [actionBusy, setActionBusy] = useState(false)
  const [formError, setFormError] = useState('')
  // 有差异但缺「盘点差异」审批时，就地开申请（issue #7374 段 3）：ref = 盘点单号，金额 = 差异合计
  const [approvalDraft, setApprovalDraft] = useState<ApprovalDraft | null>(null)

  const [openForm, setOpenForm] = useState(false)
  const [formWarehouseId, setFormWarehouseId] = useState('')
  const [formNote, setFormNote] = useState('')

  const [confirm, setConfirm] = useState<null | 'complete' | 'cancel'>(null)

  const warehouseLabel = useCallback(
    (id: number) => {
      const w = warehouses.find((x) => x.id === id)
      // 只显示**仓名**（issue #7616，用户 2026-10-24：「直接叫主仓即可，不要带括号和 main」）：
      // 编码是内部键，拼在商家面前既重复又像内部标识；同名消歧是将来有多仓时的事，
      // 届时用业务字段（仓名 + 位置），不拿编码顶上。
      // 查不到就照实写「未知仓库」——不猜、不拿 id 当名字冒充
      return w ? w.name : `未知仓库 #${id}`
    },
    [warehouses],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [w, s] = await Promise.all([warehouseApi.list(), stocktakeApi.list()])
      setWarehouses((w.data?.data ?? []) as Warehouse[])
      setRows((s.data?.data ?? []) as Stocktake[])
    } catch (e) {
      setLoadError(loadErrorMessage(e, '盘点单'))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true)
    setDetailError('')
    setFormError('')
    try {
      const res = await stocktakeApi.detail(id)
      const d = (res.data?.data ?? null) as Stocktake | null
      setDetail(d)
      // 只回填**已数**的行：未数的行留空 ⇒ 提交时不会被读成 0
      const draft: Record<number, string> = {}
      for (const line of d?.items ?? []) {
        if (line.countedQty !== null && line.countedQty !== undefined) {
          draft[line.batchId] = formatStockQuantity(line.countedQty)
        }
      }
      setCounts(draft)
    } catch (e) {
      setDetail(null)
      setDetailError(loadErrorMessage(e, '盘点明细'))
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId)
  }, [selectedId, loadDetail])

  const selectedRow = useMemo(() => rows.find((r) => r.id === selectedId) ?? null, [rows, selectedId])
  const isCounting = detail?.status === 'counting'
  const total = diffTotal(detail?.items ?? [])
  const uncounted = (detail?.items ?? []).filter(
    (i) => i.countedQty === null || i.countedQty === undefined,
  ).length

  async function submitOpen() {
    setFormError('')
    if (!formWarehouseId) {
      setFormError('先选一个仓 —— 盘点必须落在具体某个仓上')
      return
    }
    setActionBusy(true)
    try {
      await stocktakeApi.open(Number(formWarehouseId), formNote.trim() || undefined)
      toast.success('盘点任务已出')
      setOpenForm(false)
      setFormNote('')
      setFormWarehouseId('')
      await load()
    } catch (e) {
      setFormError(loadErrorMessage(e, '出盘点任务'))
    } finally {
      setActionBusy(false)
    }
  }

  async function saveCounts() {
    if (!detail) return
    setFormError('')
    const payload: Record<string, number> = {}
    for (const [batchId, raw] of Object.entries(counts)) {
      const text = (raw ?? '').trim()
      if (text === '') continue
      const problem = checkCountedQty(text)
      if (problem) {
        setFormError(`批次 ${batchId}：${problem}`)
        return
      }
      payload[batchId] = Number(text)
    }
    if (Object.keys(payload).length === 0) {
      setFormError('还没有录任何实盘量')
      return
    }
    setActionBusy(true)
    try {
      const res = await stocktakeApi.count(detail.id, payload)
      const d = (res.data?.data ?? null) as Stocktake | null
      if (d) setDetail(d)
      toast.success('实盘量已保存')
      await load()
    } catch (e) {
      setFormError(loadErrorMessage(e, '保存实盘量'))
    } finally {
      setActionBusy(false)
    }
  }

  async function runConfirm() {
    if (!detail || !confirm) return
    setFormError('')
    setActionBusy(true)
    try {
      if (confirm === 'complete') {
        const res = await stocktakeApi.complete(detail.id)
        const d = (res.data?.data ?? null) as Stocktake | null
        if (d) setDetail(d)
        toast.success('盘点已完成，差异已按数量调整')
      } else {
        const res = await stocktakeApi.cancel(detail.id)
        const d = (res.data?.data ?? null) as Stocktake | null
        if (d) setDetail(d)
        toast.success('盘点单已作废')
      }
      setConfirm(null)
      await load()
    } catch (e) {
      // 🔴 「有差异但没有已通过的盘点差异审批」是**服务端**拒绝 —— 原样显示它给的下一步
      const message = loadErrorMessage(e, confirm === 'complete' ? '完成盘点' : '作废盘点')
      setFormError(message)
      // 顺手把申请入口摆出来（差异合计页面本来就有，直接预填 —— 金额低于差异合计等于白批）
      if (confirm === 'complete' && detail && /盘点差异/.test(message)) {
        setApprovalDraft(
          stocktakeDiffDraft({ stocktakeNo: detail.stocktakeNo, diffTotal: diffTotal(detail.items) }),
        )
      }
      setConfirm(null)
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="盘点单"
        subtitle="按仓出一张盘点任务，逐批次录实盘；有差异要先走「盘点差异」审批才能完成。"
        actions={
          canWrite ? (
            <Button
              icon={<Plus className="w-4 h-4" />}
              onClick={() => setOpenForm(true)}
              data-testid="stocktake-open"
            >
              出盘点任务
            </Button>
          ) : null
        }
      />

      <PageCard className="mt-4">
        {loadError && (
          <ListLoadError
            testId="stocktakes-load-error"
            message={loadError}
            onRetry={() => void load()}
            retrying={loading}
          />
        )}

        {loading ? (
          <div className="py-10 text-center text-sm text-neutral-500">加载中...</div>
        ) : loadError ? null : rows.length === 0 ? (
          <EmptyState
            testId="stocktakes-empty"
            icon="file"
            title="还没有盘点单"
            description={
              canWrite
                ? '点右上角「出盘点任务」选一个仓，系统会按那一刻的账面数开出这张盘点单。'
                : '有盘点任务时会出现在这里。'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="stocktakes-table">
              <thead>
                <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                  <th className="py-2 whitespace-nowrap">盘点单号</th>
                  <th className="py-2 whitespace-nowrap">仓库</th>
                  <th className="py-2 whitespace-nowrap">状态</th>
                  <th className="py-2 whitespace-nowrap">备注</th>
                  <th className="py-2 whitespace-nowrap">完成时间</th>
                  <th className="py-2 text-right whitespace-nowrap sticky right-0 bg-white">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    data-testid={`stocktake-row-${row.id}`}
                    className={row.id === selectedId ? 'border-b border-neutral-100 bg-neutral-50' : 'border-b border-neutral-100'}
                  >
                    <td className="py-2 font-medium text-neutral-900">{row.stocktakeNo}</td>
                    <td className="py-2 text-neutral-600">{warehouseLabel(row.warehouseId)}</td>
                    <td className="py-2">
                      <span
                        data-testid={`stocktake-status-${row.id}`}
                        className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[row.status] ?? 'bg-neutral-100 text-neutral-500'}`}
                      >
                        {displayEnum(STATUS_LABEL, row.status)}
                      </span>
                    </td>
                    <td className="py-2 text-neutral-600">{row.note || '—'}</td>
                    <td className="py-2 text-neutral-600">{row.completedAt ? row.completedAt.slice(0, 16).replace('T', ' ') : '—'}</td>
                    <td className="py-2 text-right sticky right-0 bg-white">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => setSelectedId(row.id)}
                        data-testid={`stocktake-open-detail-${row.id}`}
                      >
                        查看明细
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageCard>

      {selectedId && (
        <PageCard className="mt-4">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-neutral-900" data-testid="stocktake-detail-title">
                {selectedRow?.stocktakeNo ?? detail?.stocktakeNo ?? '盘点明细'}
              </h2>
              <p className="mt-0.5 text-xs text-neutral-500">
                {selectedRow ? warehouseLabel(selectedRow.warehouseId) : ''}
                {detail ? ` · ${displayEnum(STATUS_LABEL, detail.status)}` : ''}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {canWrite && isCounting && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={actionBusy}
                    onClick={() => void saveCounts()}
                    data-testid="stocktake-save-counts"
                  >
                    保存实盘量
                  </Button>
                  <Button size="sm" disabled={actionBusy} onClick={() => setConfirm('complete')} data-testid="stocktake-complete">
                    完成盘点
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={actionBusy}
                    onClick={() => setConfirm('cancel')}
                    data-testid="stocktake-cancel"
                  >
                    作废
                  </Button>
                </>
              )}
            </div>
          </div>

          {formError && (
            <p className="mb-3 text-sm text-red-600" data-testid="stocktake-form-error">
              {formError}
            </p>
          )}

          {detailError && (
            <ListLoadError
              testId="stocktake-detail-error"
              message={detailError}
              onRetry={() => void loadDetail(selectedId)}
              retrying={detailLoading}
            />
          )}

          {detailLoading ? (
            <div className="py-8 text-center text-sm text-neutral-500">加载明细...</div>
          ) : detailError ? null : (
            <>
              <p className="mb-3 text-sm text-neutral-600" data-testid="stocktake-total-diff">
                {detail && detail.items.length === 0
                  ? '这次盘点没有可盘的批次（出任务时该仓没有库存）。'
                  : total === null
                    ? `待录入${uncounted > 0 ? `（还有 ${uncounted} 个批次没数）` : ''}`
                    : `差异合计 ${total > 0 ? '+' : ''}${formatStockQuantity(total)}`}
                {total !== null && total !== 0 && (
                  <span className="ml-2 text-xs text-amber-700">完成前需要一张已通过的「盘点差异」审批</span>
                )}
              </p>

              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="stocktake-lines">
                  <thead>
                    <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                      <th className="py-2 whitespace-nowrap">批次号</th>
                      <th className="py-2 whitespace-nowrap">SKU</th>
                      <th className="py-2 whitespace-nowrap">账面剩余</th>
                      <th className="py-2 whitespace-nowrap">实盘量</th>
                      <th className="py-2 whitespace-nowrap">差异</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail?.items ?? []).map((line) => (
                      <tr key={line.batchId} className="border-b border-neutral-100" data-testid={`stocktake-line-${line.batchId}`}>
                        <td className="py-2 font-medium text-neutral-900">{line.batchNo || '—'}</td>
                        <td className="py-2 text-neutral-600">{line.skuCode || '—'}</td>
                        <td className="py-2 text-neutral-600">{qtyText(line.bookQty)}</td>
                        <td className="py-2">
                          {canWrite && isCounting ? (
                            <input
                              data-testid={`stocktake-count-input-${line.batchId}`}
                              value={counts[line.batchId] ?? ''}
                              onChange={(e) =>
                                setCounts((prev) => ({ ...prev, [line.batchId]: e.target.value }))
                              }
                              placeholder="未数"
                              inputMode="decimal"
                              className="w-24 px-2 py-1 text-sm rounded-lg border border-neutral-300 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                          ) : (
                            <span className="text-neutral-600" data-testid={`stocktake-counted-${line.batchId}`}>
                              {qtyText(line.countedQty)}
                            </span>
                          )}
                        </td>
                        <td className="py-2" data-testid={`stocktake-diff-${line.batchId}`}>
                          {line.countedQty === null || line.countedQty === undefined
                            ? '未数'
                            : `${(line.diffQty ?? 0) > 0 ? '+' : ''}${formatStockQuantity(line.diffQty)}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="mt-3 text-xs text-neutral-400" data-testid="stocktake-book-basis">
                「账面剩余」= 入库米数 − 已派工消耗（出任务当刻的快照）—— 与「库存明细 ▸ 批次余量」是同一个数。
                已经用完的批次不会出现在这张单里。
              </p>
            </>
          )}
        </PageCard>
      )}

      {/* 出任务：仓 + 备注（仓是必填，且只能从**已有仓**里选，不许手打 id） */}
      <Modal
        open={openForm}
        onClose={() => setOpenForm(false)}
        title="出盘点任务"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOpenForm(false)}>
              取消
            </Button>
            <Button loading={actionBusy} onClick={() => void submitOpen()} data-testid="stocktake-open-submit">
              出任务
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-neutral-600">
            账面数取**出任务那一刻的剩余米数**（入库米数 − 已派工消耗）；之后入库的变化不会算进这张单。
          </p>
          <label className="block text-sm font-medium text-neutral-700">
            仓库
            <select
              data-testid="stocktake-form-warehouse"
              value={formWarehouseId}
              onChange={(e) => setFormWarehouseId(e.target.value)}
              className={`mt-1.5 w-full ${SELECT_CONTROL_FIELD}`}
            >
              <option value="">选择仓库</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
          <Input
            label="备注"
            data-testid="stocktake-form-note"
            value={formNote}
            onChange={(e) => setFormNote(e.target.value)}
            placeholder="例如：月末全仓盘点"
          />
          {formError && (
            <p className="text-sm text-red-600" data-testid="stocktake-open-error">
              {formError}
            </p>
          )}
        </div>
      </Modal>

      {/* 完成 / 作废 的一步确认（不可逆的是库存调整，而它被服务端审批闸门挡着） */}
      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === 'complete' ? '完成盘点' : '作废盘点'}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              variant={confirm === 'complete' ? 'primary' : 'danger'}
              loading={actionBusy}
              onClick={() => void runConfirm()}
              data-testid="stocktake-confirm-submit"
            >
              {confirm === 'complete' ? '确认完成' : '确认作废'}
            </Button>
          </div>
        }
      >
        <p className="text-sm text-neutral-600" data-testid="stocktake-confirm-text">
          {confirm === 'complete'
            ? total === null
              ? '还有批次没数完 —— 完成前请先录实盘量。'
              : total === 0
                ? '账实相符，完成后不会有库存调整。'
                : `差异合计 ${total > 0 ? '+' : ''}${formatStockQuantity(total)}；完成会按差异调整批次数量，且需要一张已通过的「盘点差异」审批。`
            : '作废后这张盘点单不能再改（库存不受影响）。'}
        </p>
      </Modal>

      {/* 盘点差异审批（issue #7374 段 3）：ref = 盘点单号，金额预填差异合计 */}
      <RequestApprovalModal
        open={approvalDraft !== null}
        onClose={() => setApprovalDraft(null)}
        draft={approvalDraft}
      />
    </div>
  )

}
