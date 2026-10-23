'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button, EmptyState, Input, Modal, PageCard, PageHeader } from '@/components/ui'
import { SELECT_CONTROL_FIELD } from '@/components/ui/Select'
import { displayEnum } from '@/lib/enum-display'
// 五类对象显示名的唯一真值源（issue #7593）：顶栏待办入口 `ApprovalBell` 共用同一份，
// 避免「新增一类审批」时一处显示人话、另一处漏出内部码（§31 P3）。
import { APPROVAL_TYPE_LABEL as TYPE_LABEL } from '@/lib/approval-request'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { approvalApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { useAuthStore } from '@/store/auth'
import type { ApprovalItem, ApprovalStatus } from '@/types/approval'

/**
 * 审批中心 `/approvals`（issue #7374，P1-2 的商家面）。
 *
 * ## 它是什么
 *
 * 五类业务闸门（**改价 / 超授信 / 退款 / 采购超量 / 盘点差异**）共用的裁决屏：
 * 业务侧提交申请 → 这里通过 / 驳回 / 撤回 → 通过后业务侧「用一次就该失效」。
 *
 * ## 🔴 三条纪律（与后端判据一一对应）
 *
 * 1. **批一次用一次**：通过后再被业务用掉，这条审批就不再能被重复使用 —— 页面把「已使用」
 *    单独标出来（`consumedAt` 非空），不让「已通过」被读成「还能再批一次」；
 * 2. **裁决只发生在待审上**：已通过 / 已驳回 / 已撤回的行**不给**通过/驳回按钮
 *    （服务端 CAS 也会拒，但让能点的都失败是坏界面）；
 * 3. **服务端拒绝原话上屏**：自批、已裁决过、非本人撤回 —— 都是服务端的判定，页面照实显示。
 *
 * ## 权限
 *
 * 读 `finance:view`（＝菜单节点码 ＝ 路由守卫码 ＝ 本页第一屏读端点码），写 `finance:create`
 * （与后端 `ApprovalController` 的类级码 / 方法级码逐字同码，零授权 delta）。
 *
 * ## 边界（照实登记）
 *
 * - 本页**不发起**申请（发起在各自的业务页：改价 / 退款 / 采购 / 盘点差异）；
 * - 不展示 `payload` 原文（内部 JSON，商家读不懂，§31 不摆内部标识）；
 * - 不做审批流配置（谁有权批哪类由 `finance:create` 统一决定，具名到人是后续段）。
 */

const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: '待审',
  approved: '已通过',
  rejected: '已驳回',
  withdrawn: '已撤回',
}

const STATUS_BADGE: Record<ApprovalStatus, string> = {
  pending: 'bg-amber-50 text-amber-700',
  approved: 'bg-emerald-50 text-emerald-700',
  rejected: 'bg-red-50 text-red-700',
  withdrawn: 'bg-neutral-100 text-neutral-500',
}

/** 状态筛选的顺序（待审永远第一：那是要人动手的一档）。 */
const STATUS_ORDER: ApprovalStatus[] = ['pending', 'approved', 'rejected', 'withdrawn']

/** 金额上屏：`null` ⇒ 「—」（不是 ¥0.00 —— 没有金额约束 ≠ 金额为零）。 */
function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmt(value: string | null | undefined): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

/**
 * 这一行能给哪些动作（**判据与按钮共用一处**，免得出现「有按钮但点不动」）。
 *
 * @param status      审批状态
 * @param canDecide   是否有写权（`finance:create`）
 * @param isRequester 当前登录人是否就是申请人（撤回只对本人）
 * @param consumedAt  非空 ⇒ 已被业务用掉
 */
export function actionsFor(
  status: ApprovalStatus | string,
  canDecide: boolean,
  isRequester: boolean,
  consumedAt: string | null,
): ('approve' | 'reject' | 'withdraw')[] {
  if (status !== 'pending') return []
  const actions: ('approve' | 'reject' | 'withdraw')[] = []
  if (canDecide && !consumedAt) {
    actions.push('approve', 'reject')
  }
  if (isRequester) {
    actions.push('withdraw')
  }
  return actions
}

export default function ApprovalsPage() {
  const { has } = usePermission()
  const canDecide = has('finance:create')
  const currentUserId = useAuthStore((s) => s.user?.id)

  const [rows, setRows] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | ''>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [decide, setDecide] = useState<{ item: ApprovalItem; approve: boolean } | null>(null)
  const [decideNote, setDecideNote] = useState('')
  const [decideError, setDecideError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await approvalApi.list()
      setRows((res.data?.data ?? []) as ApprovalItem[])
    } catch (error) {
      console.error('加载审批失败:', error)
      setLoadError(loadErrorMessage(error, '审批列表加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const counts = useMemo(() => {
    const base: Record<ApprovalStatus, number> = { pending: 0, approved: 0, rejected: 0, withdrawn: 0 }
    for (const row of rows) {
      const key = row.status as ApprovalStatus
      if (key in base) base[key] += 1
    }
    return base
  }, [rows])

  const visible = useMemo(
    () =>
      rows.filter(
        (row) =>
          (!statusFilter || row.status === statusFilter) && (!typeFilter || row.objectType === typeFilter),
      ),
    [rows, statusFilter, typeFilter],
  )

  async function runDecide() {
    if (!decide) return
    setDecideError('')
    const note = decideNote.trim()
    if (!decide.approve && !note) {
      // 驳回要留一句为什么：只写「驳回」的审批单等于把申请人晾在原地
      setDecideError('驳回要写一句为什么（申请人会看到这句）')
      return
    }
    setBusy(true)
    try {
      if (decide.approve) await approvalApi.approve(decide.item.id, note || undefined)
      else await approvalApi.reject(decide.item.id, note)
      toast.success(decide.approve ? '已通过' : '已驳回')
      setDecide(null)
      setDecideNote('')
      await load()
    } catch (e) {
      // 🔴 自批 / 已裁决过 —— 服务端判定，原话上屏
      setDecideError(loadErrorMessage(e, decide.approve ? '通过审批' : '驳回审批'))
    } finally {
      setBusy(false)
    }
  }

  async function runWithdraw(item: ApprovalItem) {
    setActionError('')
    setBusy(true)
    try {
      await approvalApi.withdraw(item.id)
      toast.success('已撤回')
      await load()
    } catch (e) {
      setActionError(loadErrorMessage(e, '撤回审批'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-6">
      <PageHeader
        title="审批中心"
        subtitle="改价、超授信、退款、采购超量、盘点差异都在这裁决；通过后业务用一次就失效，不会重复放行。"
      />

      <PageCard className="mt-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-neutral-600" data-testid="approvals-counts">
            待审 {counts.pending} 条 · 已通过 {counts.approved} 条 · 已驳回 {counts.rejected} 条 · 已撤回{' '}
            {counts.withdrawn} 条
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-neutral-600">
              类型
              <select
                data-testid="approvals-filter-type"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className={`w-32 ${SELECT_CONTROL_FIELD}`}
              >
                <option value="">全部</option>
                {Object.entries(TYPE_LABEL).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-neutral-600">
              状态
              <select
                data-testid="approvals-filter-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as ApprovalStatus | '')}
                className={`w-32 ${SELECT_CONTROL_FIELD}`}
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
        </div>

        {actionError && (
          <p className="mb-3 text-sm text-red-600" data-testid="approvals-action-error">
            {actionError}
          </p>
        )}

        {loadError && (
          <ListLoadError
            testId="approvals-load-error"
            message={loadError}
            onRetry={() => void load()}
            retrying={loading}
          />
        )}

        {loading ? (
          <div className="py-10 text-center text-sm text-neutral-500">加载中...</div>
        ) : loadError ? null : visible.length === 0 ? (
          <EmptyState
            testId="approvals-empty"
            icon="file"
            title={statusFilter || typeFilter ? '这个筛选下没有审批单' : '还没有审批单'}
            description={
              statusFilter === 'pending'
                ? '没有待你裁决的申请。'
                : '业务侧提交申请后会出现在这里（改价 / 超授信 / 退款 / 采购超量 / 盘点差异）。'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="approvals-table">
              <thead>
                <tr className="text-left text-xs text-neutral-500 border-b border-neutral-200">
                  <th className="py-2 pr-4 whitespace-nowrap">类型</th>
                  <th className="py-2 pr-4 whitespace-nowrap">对象</th>
                  <th className="py-2 pr-4 whitespace-nowrap">金额</th>
                  <th className="py-2 pr-4 whitespace-nowrap">申请人</th>
                  <th className="py-2 pr-4 whitespace-nowrap">申请时间</th>
                  <th className="py-2 pr-4 whitespace-nowrap">状态</th>
                  <th className="py-2 pr-4 whitespace-nowrap">裁决</th>
                  <th className="py-2 text-right whitespace-nowrap sticky right-0 bg-white">操作</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => {
                  const isRequester = !!currentUserId && row.requestedBy === currentUserId
                  const acts = actionsFor(row.status, canDecide, isRequester, row.consumedAt)
                  return (
                    <tr key={row.id} data-testid={`approval-row-${row.id}`} className="border-b border-neutral-100">
                      <td className="py-2 pr-4 whitespace-nowrap text-neutral-700">
                        {TYPE_LABEL[row.objectType] ?? '其他'}
                      </td>
                      <td className="py-2 pr-4 max-w-[280px]">
                        <div className="truncate text-neutral-800" title={row.objectLabel || row.objectRef}>
                          {row.objectLabel || row.objectRef}
                        </div>
                        {row.reason && (
                          <div className="truncate text-xs text-neutral-500" title={row.reason}>
                            {row.reason}
                          </div>
                        )}
                      </td>
                      <td className="py-2 pr-4 whitespace-nowrap text-neutral-700">{money(row.amount)}</td>
                      <td className="py-2 pr-4 whitespace-nowrap text-neutral-600">{row.requestedByName || '—'}</td>
                      <td className="py-2 pr-4 whitespace-nowrap text-neutral-600">{fmt(row.requestedAt)}</td>
                      <td className="py-2 pr-4 whitespace-nowrap">
                        <span
                          data-testid={`approval-status-${row.id}`}
                          className={`whitespace-nowrap text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[row.status as ApprovalStatus] ?? 'bg-neutral-100 text-neutral-500'}`}
                        >
                          {displayEnum(STATUS_LABEL, row.status)}
                        </span>
                        {row.consumedAt && (
                          <span
                            className="ml-1 whitespace-nowrap text-xs px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-500"
                            data-testid={`approval-consumed-${row.id}`}
                          >
                            已使用
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4 max-w-[220px] text-neutral-600">
                        {row.decidedByName ? (
                          <div>
                            {/* 裁决人 + 时间一行；说明另起一行截断 —— 挤在一行时说明会被整段切掉（实测截图） */}
                            {/* 裁决时间省略年份（`10-22 16:10`）：整串带年份时会被列宽切掉分钟（实测截图） */}
                            <div className="whitespace-nowrap" title={fmt(row.decidedAt)}>
                              {row.decidedByName} · {fmt(row.decidedAt).slice(5)}
                            </div>
                            {row.decisionNote && (
                              <div className="truncate text-xs text-neutral-500" title={row.decisionNote}>
                                {row.decisionNote}
                              </div>
                            )}
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="py-2 text-right sticky right-0 bg-white">
                        <div className="flex justify-end gap-2">
                          {acts.includes('approve') && (
                            <Button
                              size="sm"
                              disabled={busy}
                              onClick={() => {
                                setDecideError('')
                                setDecideNote('')
                                setDecide({ item: row, approve: true })
                              }}
                              data-testid={`approval-approve-${row.id}`}
                            >
                              通过
                            </Button>
                          )}
                          {acts.includes('reject') && (
                            <Button
                              variant="danger"
                              size="sm"
                              disabled={busy}
                              onClick={() => {
                                setDecideError('')
                                setDecideNote('')
                                setDecide({ item: row, approve: false })
                              }}
                              data-testid={`approval-reject-${row.id}`}
                            >
                              驳回
                            </Button>
                          )}
                          {acts.includes('withdraw') && (
                            <Button
                              variant="secondary"
                              size="sm"
                              disabled={busy}
                              onClick={() => void runWithdraw(row)}
                              data-testid={`approval-withdraw-${row.id}`}
                            >
                              撤回
                            </Button>
                          )}
                          {acts.length === 0 && <span className="text-xs text-neutral-400">—</span>}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </PageCard>

      {/* 裁决：通过可不写说明；驳回必须写（申请人会看到这句） */}
      <Modal
        open={decide !== null}
        onClose={() => setDecide(null)}
        title={decide?.approve ? '通过审批' : '驳回审批'}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setDecide(null)}>
              取消
            </Button>
            <Button
              variant={decide?.approve ? 'primary' : 'danger'}
              loading={busy}
              onClick={() => void runDecide()}
              data-testid="approval-decide-submit"
            >
              {decide?.approve ? '确认通过' : '确认驳回'}
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-neutral-600">
            {decide ? `${TYPE_LABEL[decide.item.objectType] ?? '其他'} · ${decide.item.objectLabel || decide.item.objectRef} · ${money(decide.item.amount)}` : ''}
          </p>
          <p className="text-xs text-neutral-500">
            通过后业务用一次就失效（再想放行要重新申请）；不能给自己的申请裁决。
          </p>
          <Input
            label={decide?.approve ? '说明（可留空）' : '驳回原因（必填）'}
            data-testid="approval-decide-note"
            value={decideNote}
            onChange={(e) => setDecideNote(e.target.value)}
            placeholder={decide?.approve ? '例如：与客户确认后可让 3%' : '例如：超出本月折扣权限，等月底再谈'}
          />
          {decideError && (
            <p className="text-sm text-red-600" data-testid="approval-decide-error">
              {decideError}
            </p>
          )}
        </div>
      </Modal>
    </div>
  )
}
