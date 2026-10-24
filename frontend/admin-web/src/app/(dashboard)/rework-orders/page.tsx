'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button, EmptyState, Input, Modal, PageCard, PageHeader } from '@/components/ui'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { displayEnum } from '@/lib/enum-display'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { reworkOrderApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import type { ReworkOrder, ReworkStatus } from '@/types/rework'

/**
 * 返工单 `/rework-orders`（issue #7377，P1-5 质量闭环的商家面）。
 *
 * ## 它是什么
 *
 * 一张返工单挂在**售后单**上：售后判定要返工 ⇒ 开单 → 开工 → 完工；
 * 完工时**服务端**回写售后状态（售后单当前是「处理中」才推进到「已解决」）。
 * 同一张售后单不许同时有两张未完结的返工单，已闭环/已驳回的售后单也不许再开 ——
 * 这两条都是**服务端**拒的，本页把它的原话显示出来，不吞成「操作失败」。
 *
 * ## 🔴 钱在哪：本页**没有金额**
 *
 * 返工的成本 = **返工报工**（`work_type='rework'`）的计件金额，由报表中心的「质量成本」汇总；
 * 返工单本身不产生金额。所以这里宁可空着也不写 ¥0.00 —— 写了会让商家以为「建了单就在算钱」。
 *
 * ## 权限
 *
 * 读 `after_sales:view`（菜单节点码 ＝ 路由守卫码 ＝ 本页第一屏读端点码），写 `order:refund`
 * —— 与售后工单同域复用既有码，零授权 delta（新造 `rework:*` 今天没人持有，页面会对所有人不可见）。
 *
 * ## 边界（照实登记）
 *
 * - 不在这里改售后单（售后状态机归售后工单页；本页只触发「完工回写」）；
 * - 不做返工工时/成本录入（成本口径 = 计件报工，另一条动线）；
 * - 没有「删除」：开错了就取消（`cancelled` 留痕，不物理删）。
 */

const STATUS_LABEL: Record<ReworkStatus, string> = {
  draft: '待开工',
  in_progress: '返工中',
  done: '已完成',
  cancelled: '已取消',
}

const STATUS_BADGE: Record<ReworkStatus, string> = {
  draft: 'bg-neutral-100 text-neutral-600',
  in_progress: 'bg-amber-50 text-amber-700',
  done: 'bg-emerald-50 text-emerald-700',
  cancelled: 'bg-neutral-100 text-neutral-400',
}

const STATUS_ORDER: ReworkStatus[] = ['draft', 'in_progress', 'done', 'cancelled']

/** 时间是**服务端给的时刻**，本页只格式化，不做时区换算（+08 由后端 `BusinessClock` 定）。 */
function fmt(value: string | null | undefined): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

/** 未完结 = 还在路上（待开工 / 返工中）；页面计数与「已闭环但还在做」这条验收口径同源。 */
export function isOpen(row: ReworkOrder): boolean {
  return row.status === 'draft' || row.status === 'in_progress'
}

/** 一张未完结单有哪些动作（按钮与判据共用一处，免得出现「有按钮但点不动」）。 */
export function actionsFor(status: ReworkStatus): ('start' | 'complete' | 'cancel')[] {
  if (status === 'draft') return ['start', 'cancel']
  if (status === 'in_progress') return ['complete', 'cancel']
  return []
}

export default function ReworkOrdersPage() {
  const { has } = usePermission()
  const canWrite = has('order:refund')
  const [rows, setRows] = useState<ReworkOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<ReworkStatus | ''>('')
  const [createOpen, setCreateOpen] = useState(false)
  const [formTicket, setFormTicket] = useState('')
  const [formReason, setFormReason] = useState('')
  const [formProcessing, setFormProcessing] = useState('')
  const [formError, setFormError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await reworkOrderApi.list()
      setRows((res.data?.data ?? []) as ReworkOrder[])
    } catch (error) {
      console.error('加载返工单失败:', error)
      setLoadError(loadErrorMessage(error, '返工单加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const counts = useMemo(() => {
    const base: Record<ReworkStatus, number> = { draft: 0, in_progress: 0, done: 0, cancelled: 0 }
    for (const row of rows) base[row.status] = (base[row.status] ?? 0) + 1
    return base
  }, [rows])

  const visible = useMemo(
    () => (statusFilter ? rows.filter((row) => row.status === statusFilter) : rows),
    [rows, statusFilter],
  )

  async function submitCreate() {
    setFormError('')
    const ticket = formTicket.trim()
    if (!ticket) {
      setFormError('先填售后单号 —— 返工是挂在售后单上的')
      return
    }
    setBusy(true)
    try {
      await reworkOrderApi.create({
        afterSalesTicketId: ticket,
        reason: formReason.trim() || undefined,
        processingOrderId: formProcessing.trim() || undefined,
      })
      toast.success('返工单已开')
      setCreateOpen(false)
      setFormTicket('')
      setFormReason('')
      setFormProcessing('')
      await load()
    } catch (e) {
      // 🔴 「已闭环/已驳回的售后单不许开」「已有未完结返工单」是**服务端**判定 —— 原话上屏
      setFormError(loadErrorMessage(e, '开返工单'))
    } finally {
      setBusy(false)
    }
  }

  async function runAction(kind: 'start' | 'complete' | 'cancel', row: ReworkOrder) {
    setActionError('')
    setBusy(true)
    try {
      if (kind === 'start') await reworkOrderApi.start(row.id)
      else if (kind === 'complete') await reworkOrderApi.complete(row.id)
      else await reworkOrderApi.cancel(row.id)
      toast.success(
        kind === 'start' ? '已开工' : kind === 'complete' ? '返工已完成，售后状态已按规则回写' : '返工单已取消',
      )
      await load()
    } catch (e) {
      setActionError(loadErrorMessage(e, kind === 'start' ? '开工' : kind === 'complete' ? '完工' : '取消返工单'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="返工单"
        subtitle="售后判定要返工的活在这里跟到完工：完工后售后状态才跟着推进，花的钱按返工报工计入质量成本。"
        actions={
          canWrite ? (
            <Button icon={<Plus className="w-4 h-4" />} onClick={() => setCreateOpen(true)} data-testid="rework-create">
              开返工单
            </Button>
          ) : null
        }
      />

      <PageCard className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-neutral-600" data-testid="rework-counts">
            未完结 {counts.draft + counts.in_progress} 张（待开工 {counts.draft} · 返工中 {counts.in_progress}）·
            已完成 {counts.done} 张 · 已取消 {counts.cancelled} 张
          </p>
          <label className="flex items-center gap-2 text-sm text-neutral-600">
            状态
            <select
              data-testid="rework-filter-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ReworkStatus | '')}
              className={`w-36 ${SELECT_CONTROL_FIELD}`}
            >
              <option value="">全部</option>
              {STATUS_ORDER.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABEL[status]}
                </option>
              ))}
            </select>
          </label>
        </div>

        <p className="mb-3 text-xs text-neutral-500">
          返工成本按「返工报工」的计件金额计入质量成本，本页不产生金额；
          <Link href="/reports" className="ml-1 text-primary-600 hover:underline">
            去报表中心看质量成本
          </Link>
        </p>

        {actionError && (
          <p className="mb-3 text-sm text-red-600" data-testid="rework-action-error">
            {actionError}
          </p>
        )}

        {loadError && (
          <ListLoadError
            testId="rework-orders-load-error"
            message={loadError}
            onRetry={() => void load()}
            retrying={loading}
          />
        )}

        {loading ? (
          <div className="py-10 text-center text-sm text-neutral-500">加载中...</div>
        ) : loadError ? null : visible.length === 0 ? (
          <EmptyState
            testId="rework-orders-empty"
            icon="file"
            title={statusFilter ? '这个状态下没有返工单' : '还没有返工单'}
            description={
              canWrite
                ? '售后单判定要返工时，点右上角「开返工单」填上售后单号。'
                : '售后判定要返工后，返工单会出现在这里。'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="rework-orders-table">
              <thead>
                <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                  <th className="py-2 whitespace-nowrap">返工单号</th>
                  <th className="py-2 whitespace-nowrap">关联售后单</th>
                  <th className="py-2 whitespace-nowrap">关联加工单</th>
                  <th className="py-2 whitespace-nowrap">原因</th>
                  <th className="py-2 whitespace-nowrap">状态</th>
                  <th className="py-2 whitespace-nowrap">建单人</th>
                  <th className="py-2 whitespace-nowrap">开工</th>
                  <th className="py-2 whitespace-nowrap">完工</th>
                  <th className="py-2 text-right whitespace-nowrap sticky right-0 bg-white">操作</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <tr key={row.id} data-testid={`rework-row-${row.id}`} className="border-b border-neutral-100">
                    <td className="py-2 font-medium text-neutral-900">{row.reworkNo}</td>
                    <td className="py-2 text-neutral-600">{row.afterSalesTicketId}</td>
                    <td className="py-2 text-neutral-600">{row.processingOrderId || '—'}</td>
                    <td className="py-2 text-neutral-600">{row.reason || '—'}</td>
                    <td className="py-2">
                      <span
                        data-testid={`rework-status-${row.id}`}
                        className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[row.status] ?? 'bg-neutral-100 text-neutral-500'}`}
                      >
                        {displayEnum(STATUS_LABEL, row.status)}
                      </span>
                    </td>
                    <td className="py-2 text-neutral-600">{row.createdByName || '—'}</td>
                    <td className="py-2 text-neutral-600">{fmt(row.startedAt)}</td>
                    <td className="py-2 text-neutral-600">{fmt(row.completedAt)}</td>
                    <td className="py-2 text-right sticky right-0 bg-white">
                      <div className="flex justify-end gap-2">
                        {canWrite && actionsFor(row.status).includes('start') && (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={busy}
                            onClick={() => void runAction('start', row)}
                            data-testid={`rework-start-${row.id}`}
                          >
                            开工
                          </Button>
                        )}
                        {canWrite && actionsFor(row.status).includes('complete') && (
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() => void runAction('complete', row)}
                            data-testid={`rework-complete-${row.id}`}
                          >
                            完工
                          </Button>
                        )}
                        {canWrite && actionsFor(row.status).includes('cancel') && (
                          <Button
                            variant="danger"
                            size="sm"
                            disabled={busy}
                            onClick={() => void runAction('cancel', row)}
                            data-testid={`rework-cancel-${row.id}`}
                          >
                            取消
                          </Button>
                        )}
                        {(!canWrite || actionsFor(row.status).length === 0) && (
                          <span className="text-xs text-neutral-400">{isOpen(row) ? '—' : '已闭环'}</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageCard>

      {/* 开单：售后单号必填（返工挂在售后单上），加工单号可选（知道是哪张加工单就填） */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="开返工单"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button loading={busy} onClick={() => void submitCreate()} data-testid="rework-create-submit">
              开单
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-neutral-600">
            已闭环或已驳回的售后单不能再开返工；同一张售后单同时只能有一张未完结的返工单。
          </p>
          <Input
            label="售后单号"
            data-testid="rework-form-ticket"
            value={formTicket}
            onChange={(e) => setFormTicket(e.target.value)}
            placeholder="例如：SH-20261023-0001"
          />
          <Input
            label="返工原因"
            data-testid="rework-form-reason"
            value={formReason}
            onChange={(e) => setFormReason(e.target.value)}
            placeholder="例如：客户反馈帘头褶皱不齐"
          />
          <Input
            label="关联加工单号（可留空）"
            data-testid="rework-form-processing"
            value={formProcessing}
            onChange={(e) => setFormProcessing(e.target.value)}
            placeholder="例如：JG-20261023-0008"
          />
          {formError && (
            <p className="text-sm text-red-600" data-testid="rework-form-error">
              {formError}
            </p>
          )}
        </div>
      </Modal>
    </div>
  )
}
