/**
 * 智能派单（管理面 · 手机端）—— issue #5654 项①
 *
 * 端点（全部既有，`ProductionPoolController`）：
 *   `GET  /api/admin/production/pool`            待派池（物料分组 + 加急插队区 + 超时告警）
 *   `POST /api/admin/production/pool/preview`    成批预览（只读，服务端算米数）
 *   `POST /api/admin/production/pool/dispatch`   派单（成批 `pooled:true`；加急 = 单订单 + `pooled:false`）
 *
 * 手机端交互**重新设计**（不是把 `/production/pool` 的表格搬进小屏）：
 * **卡片 + 关键数字 + 一步动作** —— 加急区每张卡一个「立刻单派」；成批区勾选 → 预览 → 确认派单。
 * 管理员在车间、单手、可能戴手套 ⇒ 每屏一个主行动，危险动作用金色描边 + 二次确认。
 *
 * 🔴 三条口径（与 admin-web 同源，一处都不许在端侧重算）：
 * ① **不重排**：`urgentLines` / `groups[].lines` 顺序即服务端口径；
 * ② **不算米数**：预览五个数全部原样渲染（前端相减 = 第二份会漂的口径）；
 * ③ **不静默**：403 ⇒ 「无「智能派单」查看权限（需要权限码 processing:view）」；
 *    派单逐单失败 ⇒ 每一行都上屏（整批拒绝由服务端保证，不静默少派）。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import {
  canWriteAdminSurface,
  missingPermissionText,
} from '../../../utils/adminPermission'
import { confirmAdminAction } from '../../../utils/adminConfirm'
import { useAdminPermissions } from '../../../components/admin/useAdminPermissions'
import { SurfaceLoginRequired, SurfaceState } from '../../../components/admin/SurfaceState'
import {
  dispatchPoolOrders,
  formatMeters,
  formatWaitHours,
  getProductionPool,
  previewPoolDispatch,
  type AdminOpsResult,
  type PoolBoard,
  type PoolDispatchResult,
  type PoolPreview,
} from '../../../services/adminOpsService'
import '../../../styles/admin-surfaces.scss'

const SURFACE = 'pool'

/** 预览五个米数的展示行（label 与服务端键一一对应，**不派生**） */
function previewRows(preview: PoolPreview): { key: string; label: string; value: string }[] {
  return [
    { key: 'formula', label: '逐单公式米数（对照基线）', value: formatMeters(preview.formulaMeters) },
    { key: 'pooled', label: '合并后预计领料', value: formatMeters(preview.pooledPlannedMeters) },
    { key: 'saved', label: '预计节省', value: formatMeters(preview.savedMeters) },
    { key: 'per_order', label: '对照·逐单派应领', value: formatMeters(preview.perOrderPlannedMeters) },
    { key: 'gain', label: '合并新增收益', value: formatMeters(preview.poolingGainMeters) },
  ]
}

export default function AdminPoolPage() {
  const { isLoggedIn } = useAuthStore()
  const permissions = useAdminPermissions()
  const [board, setBoard] = useState<AdminOpsResult<PoolBoard> | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<PoolPreview | null>(null)
  const [results, setResults] = useState<PoolDispatchResult[] | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBoard(await getProductionPool())
  }, [])

  useEffect(() => {
    if (!isLoggedIn) return
    load()
  }, [isLoggedIn, load])

  if (!isLoggedIn) return <SurfaceLoginRequired />

  const data = board?.status === 'ok' ? board.data : null
  const urgentLines = data?.urgentLines ?? []
  const groups = data?.groups ?? []
  const warnings = data?.warnings ?? []

  // 单号映射（**纯展示映射**：派单结果回显的是入参 `orderRef`，服务端没有单号键）
  const orderNoById: Record<string, string> = {}
  ;[...urgentLines, ...groups.flatMap((group) => group.lines ?? [])].forEach((line) => {
    if (line?.orderId && line?.orderNo) orderNoById[line.orderId] = line.orderNo
  })

  const toggle = (orderId: string) => {
    setPreview(null)
    setResults(null)
    setNotice('')
    setSelected((prev) =>
      prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId],
    )
  }

  /** 写动作前置：权限不足 ⇒ **显式文案且不发请求**（既有的必然 403 不值得让管理员白等一次往返） */
  const blockedByPermission = (): boolean => {
    if (canWriteAdminSurface(permissions, SURFACE)) return false
    setNotice(missingPermissionText(SURFACE, 'write'))
    return true
  }

  const onPreview = async () => {
    setNotice('')
    setResults(null)
    setPreview(null)
    if (selected.length === 0) {
      setNotice('先勾选要合并派单的加工单')
      return
    }
    if (blockedByPermission()) return
    setBusy(true)
    const res = await previewPoolDispatch(selected)
    setBusy(false)
    if (res.status !== 'ok') {
      setNotice(res.message)
      return
    }
    setPreview(res.data)
  }

  const onDispatch = async () => {
    setNotice('')
    if (selected.length === 0) {
      setNotice('先勾选要合并派单的加工单')
      return
    }
    if (blockedByPermission()) return
    const ok = await confirmAdminAction(
      '确认派单',
      `将把已选的 ${selected.length} 张单合并排料并生成加工单，生成后不可撤销`,
    )
    if (!ok) return
    setBusy(true)
    const res = await dispatchPoolOrders(selected, true)
    setBusy(false)
    if (res.status !== 'ok') {
      setNotice(res.message)
      return
    }
    setResults(res.data)
    setSelected([])
    setPreview(null)
    await load()
  }

  /** 加急插队：**同一个端点 + 单订单 + `pooled:false`**（这些单不进池，勾进成批会被整批拒绝） */
  const onUrgentDispatch = async (orderId: string, orderNo: string) => {
    setNotice('')
    setResults(null)
    if (blockedByPermission()) return
    const ok = await confirmAdminAction('确认加急单派', `订单 ${orderNo} 将立即单派（不进池、不合并）`)
    if (!ok) return
    setBusy(true)
    const res = await dispatchPoolOrders([orderId], false)
    setBusy(false)
    if (res.status !== 'ok') {
      setNotice(res.message)
      return
    }
    setResults(res.data)
    await load()
  }

  return (
    <ScrollView scrollY className='admin-surface' data-testid='admin-pool-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>智能派单</Text>
        <Text className='admin-surface__subtitle'>
          {data
            ? `待派 ${data.orderCount} 单 / ${data.lineCount} 行 · 加急 ${data.urgentCount} 单 · 滞留上限 ${formatWaitHours(data.maxWaitHours)}`
            : '待派池 · 加急单不合并、立刻单派'}
        </Text>
      </View>

      {board === null && <SurfaceState kind='loading' message='正在加载待派池…' />}
      {board?.status === 'forbidden' && (
        <SurfaceState kind='forbidden' message={board.message} />
      )}
      {board?.status === 'error' && <SurfaceState kind='error' message={board.message} />}

      {data && (
        <View className='admin-surface__body'>
          {/* 池化开关：池「看得见」≠「已开启」—— 两件事分开说 */}
          <Text className='admin-hint' data-testid='pool-pooling-state'>
            {data.poolingEnabled
              ? '池化派单已开启：多单可合并排料'
              : '池化派单未开启：派单按逐单排料（合并需先在电脑端开启池化）'}
          </Text>

          {/* 超时告警（不得静默压单）—— 文案由服务端给（谁、等了多久、该做什么） */}
          {data.overdueCount > 0 && (
            <View className='admin-notice' data-testid='pool-overdue'>
              <Text className='admin-notice__text'>
                {data.overdueCount} 张单已超过滞留上限
              </Text>
              {warnings.map((warning) => (
                <Text key={warning.orderId} className='admin-notice__text'>
                  {warning.message}
                </Text>
              ))}
            </View>
          )}

          {notice !== '' && (
            <View className='admin-notice' data-testid='pool-notice'>
              <Text className='admin-notice__text'>{notice}</Text>
            </View>
          )}

          {/* ═══ 加急插队区：不进池、立刻单派 ═══ */}
          {urgentLines.length > 0 && (
            <View data-testid='pool-urgent-section'>
              <Text className='admin-section-title'>加急插队（{data.urgentCount} 单）</Text>
              <Text className='admin-hint'>这些单不进池、不参与合并 —— 立刻单派</Text>
              {urgentLines.map((line) => (
                <View
                  key={`urgent-${line.orderId}-${line.itemId}`}
                  className='admin-card'
                  data-testid={`pool-urgent-${line.orderId}`}
                >
                  <View className='admin-card__row'>
                    <Text className='admin-card__title'>{line.orderNo}</Text>
                    <Text className='admin-chip admin-chip--urgent'>加急</Text>
                  </View>
                  <Text className='admin-card__meta'>
                    {line.productName} · {line.skuCode} · 需求 {formatMeters(line.requiredMeters)} 米
                  </Text>
                  <Text className='admin-card__note'>
                    已等待 {formatWaitHours(line.waitHours)}
                    {line.deliveryDaysLeft != null ? ` · 到货${line.deliveryDaysLeft < 0 ? '已逾期' : `剩 ${line.deliveryDaysLeft} 天`}` : ''}
                  </Text>
                  <View
                    className='admin-action admin-action--gold'
                    data-testid={`pool-urgent-dispatch-${line.orderId}`}
                    onClick={() => onUrgentDispatch(line.orderId, line.orderNo)}
                  >
                    <Text>立刻单派</Text>
                  </View>
                </View>
              ))}
            </View>
          )}

          {/* ═══ 成批区：按物料分组，勾选 → 预览 → 派单 ═══ */}
          {groups.length === 0 ? (
            <View data-testid='pool-empty'>
              <SurfaceState kind='empty' message='待派池里没有可合并的订单' />
            </View>
          ) : (
            <View data-testid='pool-groups-section'>
              <Text className='admin-section-title'>可合并派单（按物料分组）</Text>
              {groups.map((group) => (
                <View key={group.materialKey} data-testid={`pool-group-${group.materialKey}`}>
                  <Text className='admin-hint'>
                    {group.skuCode} · {group.orderCount} 单 · 需求合计{' '}
                    {formatMeters(group.requiredMeters)} 米
                  </Text>
                  {(group.lines ?? []).map((line) => {
                    const active = selected.includes(line.orderId)
                    return (
                      <View
                        key={`${group.materialKey}-${line.orderId}-${line.itemId}`}
                        className={`admin-card admin-card--selectable${active ? ' admin-card--selected' : ''}`}
                        data-testid={`pool-line-${line.orderId}`}
                        onClick={() => toggle(line.orderId)}
                      >
                        <View className='admin-card__row'>
                          <Text className='admin-card__title'>{line.orderNo}</Text>
                          <Text className='admin-chip admin-chip--processing'>
                            {active ? '已选' : '点选'}
                          </Text>
                        </View>
                        <Text className='admin-card__meta'>
                          {line.productName} · 需求 {formatMeters(line.requiredMeters)} 米
                        </Text>
                        <Text className='admin-card__note'>
                          已等待 {formatWaitHours(line.waitHours)}
                          {line.overdue ? ' · 超上限' : ''}
                          {line.deliveryDaysLeft != null
                            ? ` · 到货${line.deliveryDaysLeft < 0 ? '已逾期' : `剩 ${line.deliveryDaysLeft} 天`}`
                            : ''}
                        </Text>
                      </View>
                    )
                  })}
                </View>
              ))}
            </View>
          )}

          {/* ═══ 预览结果（服务端五个数，原样渲染） ═══ */}
          {preview && (
            <View className='admin-card' data-testid='pool-preview'>
              <Text className='admin-card__title'>派单预览（{preview.orderCount} 单）</Text>
              <View className='admin-metrics'>
                {previewRows(preview).map((row) => (
                  <View
                    key={row.key}
                    className='admin-metric'
                    data-testid={`pool-preview-${row.key}`}
                  >
                    <Text className='admin-metric__label'>{row.label}</Text>
                    <Text className='admin-metric__value'>{row.value}</Text>
                  </View>
                ))}
              </View>
              <Text className='admin-card__note'>
                米数全部由服务端求解（与派单落账同一条路径），本页不重算
              </Text>
            </View>
          )}

          {/* ═══ 派单结果（逐单上屏：失败也必须看得见） ═══ */}
          {results && (
            <View className='admin-card' data-testid='pool-dispatch-result'>
              <Text className='admin-card__title'>派单结果</Text>
              {results.map((result) => (
                <Text
                  key={result.orderRef}
                  className='admin-card__meta'
                  data-testid={`pool-result-${result.orderRef}`}
                >
                  {orderNoById[result.orderRef] ?? result.orderRef}：
                  {result.success
                    ? `已生成加工单 ${result.processingOrderNo ?? ''}`
                    : `失败 ${result.message ?? ''}`}
                </Text>
              ))}
            </View>
          )}
        </View>
      )}

      {/* ═══ 底部操作条：唯一落脚点（勾选 → 预览 → 派单） ═══ */}
      {data && groups.length > 0 && (
        <View className='admin-bottombar'>
          <Text className='admin-bottombar__count' data-testid='pool-selected-count'>
            已选 {selected.length} 单
          </Text>
          <View
            className={`admin-action${busy || selected.length === 0 ? ' admin-action--disabled' : ''}`}
            data-testid='pool-preview-btn'
            onClick={onPreview}
          >
            <Text>预览合并方案</Text>
          </View>
          <View
            className={`admin-action admin-action--gold${busy || selected.length === 0 ? ' admin-action--disabled' : ''}`}
            data-testid='pool-dispatch-btn'
            onClick={onDispatch}
          >
            <Text>确认派单</Text>
          </View>
        </View>
      )}
    </ScrollView>
  )
}
