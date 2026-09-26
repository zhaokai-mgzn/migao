/**
 * 售后处理（管理面 · 手机端）—— issue #5654 项③
 *
 * 端点（全部既有，`AfterSalesController`）：
 *   `GET /api/admin/after-sales?page&size&status&keyword`  列表（分页）
 *   `GET /api/admin/after-sales/{id}`                      详情（含 statusHistory）
 *   `PUT /api/admin/after-sales/{id}/status`               `{status, remark?}` 处理动作
 *
 * 手机端交互：状态筛选 chip 行 + 工单卡片（工单号 / 客户 / 类型 / 状态 / 金额 / 描述）→
 * 点卡展开详情（含状态历史）→ **只出「能走的下一步」按钮**（状态机镜像见
 * `src/utils/afterSalesFlow.ts`，与后端 `STATUS_TRANSITIONS` 逐值比对）→ 二次确认 → 提交。
 *
 * 🔴 为什么不把所有状态都摆出来：那会造出 4 个必然失败的按钮（服务端会回
 * 「工单状态不允许从 [待处理] 变更为 [已完成]」）—— 让管理员先点错再读报错是浪费一次动作。
 * 🔴 写码是 `order:refund`（**≠** 读码 `after_sales:view`，issue #5246 的读写拆码口径）：
 * 只有读权的人**看得见工单、点得动入口**，但处理动作会给出「无「售后处理」处理权限
 * （需要权限码 order:refund）」的显式文案 —— 不静默、不假装成功。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import { canWriteAdminSurface, missingPermissionText } from '../../../utils/adminPermission'
import { confirmAdminAction } from '../../../utils/adminConfirm'
import { useAdminPermissions } from '../../../components/admin/useAdminPermissions'
import { SurfaceLoginRequired, SurfaceState } from '../../../components/admin/SurfaceState'
import {
  afterSalesActionConfirmText,
  afterSalesStatusLabel,
  allowedAfterSalesTargets,
} from '../../../utils/afterSalesFlow'
import {
  formatYuanAmount,
  getAfterSalesTicket,
  listAfterSales,
  updateAfterSalesStatus,
  type AdminOpsResult,
  type AfterSalesPage,
  type AfterSalesTicket,
} from '../../../services/adminOpsService'
import '../../../styles/admin-surfaces.scss'

const SURFACE = 'after-sales'

/** 状态筛选（枚举值域 + 中文取后端 `TICKET_STATUS_LABELS`，见 afterSalesFlow.ts） */
const FILTERS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'pending', label: afterSalesStatusLabel('pending') },
  { key: 'processing', label: afterSalesStatusLabel('processing') },
  { key: 'resolved', label: afterSalesStatusLabel('resolved') },
  { key: 'rejected', label: afterSalesStatusLabel('rejected') },
  { key: 'closed', label: afterSalesStatusLabel('closed') },
]

export default function AdminAfterSalesPage() {
  const { isLoggedIn } = useAuthStore()
  const permissions = useAdminPermissions()
  const [status, setStatus] = useState('')
  const [list, setList] = useState<AdminOpsResult<AfterSalesPage> | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AdminOpsResult<AfterSalesTicket> | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (nextStatus: string) => {
    setList(await listAfterSales(nextStatus ? { status: nextStatus } : undefined))
  }, [])

  useEffect(() => {
    if (!isLoggedIn) return
    load(status)
  }, [isLoggedIn, status, load])

  if (!isLoggedIn) return <SurfaceLoginRequired />

  const tickets = list?.status === 'ok' ? list.data.items ?? [] : []

  const openDetail = async (id: string) => {
    setNotice('')
    if (expandedId === id) {
      setExpandedId(null)
      setDetail(null)
      return
    }
    setExpandedId(id)
    setDetail(null)
    setDetail(await getAfterSalesTicket(id))
  }

  const onUpdateStatus = async (ticket: AfterSalesTicket, nextStatus: string) => {
    setNotice('')
    if (!canWriteAdminSurface(permissions, SURFACE)) {
      setNotice(missingPermissionText(SURFACE, 'write'))
      return
    }
    const ok = await confirmAdminAction(
      '确认处理',
      afterSalesActionConfirmText(ticket.ticketNo || ticket.id, nextStatus),
    )
    if (!ok) return
    setBusy(true)
    const res = await updateAfterSalesStatus(ticket.id, nextStatus)
    setBusy(false)
    if (res.status !== 'ok') {
      setNotice(res.message)
      return
    }
    await load(status)
    setDetail(await getAfterSalesTicket(ticket.id))
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='admin-after-sales-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>售后处理</Text>
        <Text className='admin-surface__subtitle'>
          {list?.status === 'ok' ? `共 ${list.data.total ?? tickets.length} 张工单` : '售后工单 · 处理动作会流转状态'}
        </Text>
      </View>

      <View className='admin-surface__body'>
        <View className='admin-filters'>
          {FILTERS.map((filter) => (
            <View
              key={filter.key || 'all'}
              className={`admin-filter${status === filter.key ? ' admin-filter--active' : ''}`}
              data-testid={`as-filter-${filter.key || 'all'}`}
              onClick={() => {
                setExpandedId(null)
                setDetail(null)
                setStatus(filter.key)
              }}
            >
              <Text>{filter.label}</Text>
            </View>
          ))}
        </View>

        {notice !== '' && (
          <View className='admin-notice' data-testid='as-notice'>
            <Text className='admin-notice__text'>{notice}</Text>
          </View>
        )}

        {list === null && <SurfaceState kind='loading' message='正在加载售后工单…' />}
        {list?.status === 'forbidden' && <SurfaceState kind='forbidden' message={list.message} />}
        {list?.status === 'error' && <SurfaceState kind='error' message={list.message} />}
        {list?.status === 'ok' && tickets.length === 0 && (
          <SurfaceState kind='empty' message='这个筛选下没有售后工单' />
        )}

        {tickets.map((ticket) => (
          <View key={ticket.id} className='admin-card' data-testid={`as-row-${ticket.id}`}>
            <View className='admin-card__row' onClick={() => openDetail(ticket.id)}>
              <Text className='admin-card__title'>{ticket.ticketNo || ticket.id}</Text>
              <Text
                className={`admin-chip admin-chip--${ticket.status}`}
                data-testid={`as-status-${ticket.id}`}
              >
                {afterSalesStatusLabel(ticket.status)}
              </Text>
            </View>
            <Text className='admin-card__meta' onClick={() => openDetail(ticket.id)}>
              {ticket.customerName || '未填客户'} · {ticket.ticketType || '未填类型'}
              {ticket.orderNo ? ` · 订单 ${ticket.orderNo}` : ''}
            </Text>
            <Text className='admin-card__amount'>{formatYuanAmount(ticket.refundAmount)}</Text>

            {expandedId === ticket.id && (
              <View data-testid={`as-detail-${ticket.id}`}>
                {detail === null && <SurfaceState kind='loading' message='正在加载工单详情…' />}
                {detail?.status === 'forbidden' && (
                  <SurfaceState kind='forbidden' message={detail.message} />
                )}
                {detail?.status === 'error' && (
                  <SurfaceState kind='error' message={detail.message} />
                )}
                {detail?.status === 'ok' && (
                  <View>
                    {detail.data.description ? (
                      <Text className='admin-card__meta' data-testid={`as-description-${ticket.id}`}>
                        {detail.data.description}
                      </Text>
                    ) : null}
                    {detail.data.handlerName ? (
                      <Text className='admin-card__note'>处理人 {detail.data.handlerName}</Text>
                    ) : null}
                    {(detail.data.statusHistory ?? []).map((history, index) => (
                      <Text
                        key={`${ticket.id}-history-${index}`}
                        className='admin-card__note'
                        data-testid={`as-history-${ticket.id}-${index}`}
                      >
                        {afterSalesStatusLabel(history.status || '')} · {history.time || '—'}
                        {history.operator ? ` · ${history.operator}` : ''}
                        {history.remark ? ` · ${history.remark}` : ''}
                      </Text>
                    ))}

                    {/* 处理动作：**只出状态机允许的下一步**（终态 ⇒ 一个按钮都不出） */}
                    {allowedAfterSalesTargets(detail.data.status).map((target) => (
                      <View
                        key={`${ticket.id}-${target}`}
                        className={`admin-action admin-action--ghost admin-action--inline${busy ? ' admin-action--disabled' : ''}`}
                        data-testid={`as-status-btn-${ticket.id}-${target}`}
                        onClick={() => onUpdateStatus(ticket, target)}
                      >
                        <Text>{afterSalesStatusLabel(target)}</Text>
                      </View>
                    ))}
                    {allowedAfterSalesTargets(detail.data.status).length === 0 && (
                      <Text className='admin-card__note' data-testid={`as-terminal-${ticket.id}`}>
                        {afterSalesStatusLabel(detail.data.status)}是终态，不能再流转
                      </Text>
                    )}
                  </View>
                )}
              </View>
            )}
          </View>
        ))}
      </View>
    </ScrollView>
  )
}
