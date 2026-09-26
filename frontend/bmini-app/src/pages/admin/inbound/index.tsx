/**
 * 入库过账（管理面 · 手机端）—— issue #5654 项②
 *
 * 端点（全部既有，`InboundOrderController`）：
 *   `GET   /api/admin/inbound-orders?keyword=&status=`  列表
 *   `GET   /api/admin/inbound-orders/{id}`              详情（id 可为 UUID / 单号 / 单号前缀）
 *   `PATCH /api/admin/inbound-orders/{id}`              `{action:'post'}` 过账
 *
 * 🔴 与 #5648 / #5052 的边界（issue 明写）：**工人拍照入库**走 `/api/worker/inbound/**`
 * （那是工人在现场的录入），本页是**管理员在手机上对入库单的管理**（看单 → 过账）。
 * 两者**不互相顶替**、也不共用端点。
 *
 * 手机端交互：列表卡片（单号 + 状态 + 供应商 + 金额 + 行数）→ **点卡展开详情并拉一次详情端点**
 * → 草稿单才出「过账」按钮（金描边 + 二次确认）。不把 PC 的宽表格搬过来：
 * 明细在手机上按「货号 · 颜色 · 门幅 / 数量 / 批次」逐行两列排布，**无横向滚动**。
 *
 * 🔴 过账是**不可逆**动作（服务端：加库存 + 生成批次号 + 落台账）⇒ 二次确认必须说清后果；
 * 失败/无权限**必须上屏**（不静默）。作废（cancel）不在本单（用户点名的 4 项是「过账」）。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import { canWriteAdminSurface, missingPermissionText } from '../../../utils/adminPermission'
import { confirmAdminAction } from '../../../utils/adminConfirm'
import { useAdminPermissions } from '../../../components/admin/useAdminPermissions'
import { SurfaceLoginRequired, SurfaceState } from '../../../components/admin/SurfaceState'
import {
  formatYuanAmount,
  getInboundOrder,
  inboundStatusLabel,
  listInboundOrders,
  postInboundOrder,
  type AdminOpsResult,
  type InboundOrder,
  type InboundOrderLine,
} from '../../../services/adminOpsService'
import '../../../styles/admin-surfaces.scss'

const SURFACE = 'inbound'

/** 状态筛选（服务端枚举 draft/posted/cancelled；空串 = 全部） */
const FILTERS: { key: string; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'draft', label: '草稿' },
  { key: 'posted', label: '已过账' },
  { key: 'cancelled', label: '已作废' },
]

export default function AdminInboundPage() {
  const { isLoggedIn } = useAuthStore()
  const permissions = useAdminPermissions()
  const [status, setStatus] = useState('')
  const [list, setList] = useState<AdminOpsResult<InboundOrderLine[]> | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AdminOpsResult<InboundOrder> | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (nextStatus: string) => {
    setList(await listInboundOrders(nextStatus ? { status: nextStatus } : undefined))
  }, [])

  useEffect(() => {
    if (!isLoggedIn) return
    load(status)
  }, [isLoggedIn, status, load])

  if (!isLoggedIn) return <SurfaceLoginRequired />

  const rows = list?.status === 'ok' ? list.data : []

  const openDetail = async (id: string) => {
    setNotice('')
    if (expandedId === id) {
      setExpandedId(null)
      setDetail(null)
      return
    }
    setExpandedId(id)
    setDetail(null)
    setDetail(await getInboundOrder(id))
  }

  const onPost = async (order: InboundOrderLine) => {
    setNotice('')
    if (!canWriteAdminSurface(permissions, SURFACE)) {
      setNotice(missingPermissionText(SURFACE, 'write'))
      return
    }
    const ok = await confirmAdminAction(
      '确认过账',
      `入库单 ${order.inboundNo} 过账后将加库存、生成批次号并按移动加权平均算成本，且不可撤销`,
    )
    if (!ok) return
    setBusy(true)
    const res = await postInboundOrder(order.id)
    setBusy(false)
    if (res.status !== 'ok') {
      setNotice(res.message)
      return
    }
    setDetail(res)
    await load(status)
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='admin-inbound-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>入库过账</Text>
        <Text className='admin-surface__subtitle'>
          {list?.status === 'ok' ? `共 ${rows.length} 张入库单` : '入库单 · 过账后加库存并生成批次号'}
        </Text>
      </View>

      <View className='admin-surface__body'>
        <View className='admin-filters'>
          {FILTERS.map((filter) => (
            <View
              key={filter.key || 'all'}
              className={`admin-filter${status === filter.key ? ' admin-filter--active' : ''}`}
              data-testid={`inbound-filter-${filter.key || 'all'}`}
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
          <View className='admin-notice' data-testid='inbound-notice'>
            <Text className='admin-notice__text'>{notice}</Text>
          </View>
        )}

        {list === null && <SurfaceState kind='loading' message='正在加载入库单…' />}
        {list?.status === 'forbidden' && <SurfaceState kind='forbidden' message={list.message} />}
        {list?.status === 'error' && <SurfaceState kind='error' message={list.message} />}
        {list?.status === 'ok' && rows.length === 0 && (
          <SurfaceState kind='empty' message='这个筛选下没有入库单' />
        )}

        {rows.map((row) => (
          <View key={row.id} className='admin-card' data-testid={`inbound-row-${row.id}`}>
            <View className='admin-card__row' onClick={() => openDetail(row.id)}>
              <Text className='admin-card__title'>{row.inboundNo}</Text>
              <Text
                className={`admin-chip admin-chip--${row.status}`}
                data-testid={`inbound-status-${row.id}`}
              >
                {inboundStatusLabel(row.status)}
              </Text>
            </View>
            <Text className='admin-card__meta' onClick={() => openDetail(row.id)}>
              {row.supplier || '未填供应商'} · {row.inboundDate || '未填日期'} ·{' '}
              {row.itemCount ?? 0} 行 / {row.totalQuantity ?? 0} 件
            </Text>
            <Text className='admin-card__amount'>{formatYuanAmount(row.totalAmount)}</Text>

            {/* 展开区：详情懒加载（点一次拉一次，不在列表里预取全部详情） */}
            {expandedId === row.id && (
              <View data-testid={`inbound-detail-${row.id}`}>
                {detail === null && <SurfaceState kind='loading' message='正在加载单据明细…' />}
                {detail?.status === 'forbidden' && (
                  <SurfaceState kind='forbidden' message={detail.message} />
                )}
                {detail?.status === 'error' && (
                  <SurfaceState kind='error' message={detail.message} />
                )}
                {detail?.status === 'ok' && (
                  <View>
                    {(detail.data.items ?? []).map((item, index) => (
                      <View
                        key={`${row.id}-item-${item.id ?? index}`}
                        className='admin-card__note'
                        data-testid={`inbound-item-${row.id}-${index}`}
                      >
                        <Text className='admin-card__meta'>
                          {item.skuCode || '未填货号'} · {item.colorName || '未填颜色'} ·{' '}
                          {item.doorWidth || '未填门幅'}
                        </Text>
                        <Text className='admin-card__note'>
                          数量 {item.quantity ?? '-'} · 单价 {formatYuanAmount(item.unitCost)} ·
                          金额 {formatYuanAmount(item.amount)} ·
                          {item.batchNo ? ` 批次 ${item.batchNo}` : ' 过账后生成批次号'}
                        </Text>
                      </View>
                    ))}
                    {/* 过账按钮只对草稿出现（服务端幂等闸：仅草稿可过账） */}
                    {detail.data.status === 'draft' && (
                      <View
                        className={`admin-action admin-action--gold${busy ? ' admin-action--disabled' : ''}`}
                        data-testid={`inbound-post-btn-${row.id}`}
                        onClick={() => onPost(row)}
                      >
                        <Text>过账（加库存 · 生成批次号）</Text>
                      </View>
                    )}
                    {detail.data.status === 'posted' && (
                      <Text className='admin-card__note' data-testid={`inbound-posted-${row.id}`}>
                        已于 {detail.data.postedAt || '—'} 由 {detail.data.postedBy || '—'} 过账
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
