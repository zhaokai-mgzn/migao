/**
 * 计件工资报表（管理面 · 手机端）—— issue #5654 项④
 *
 * 端点（既有，`ProductionController#pieceworkSummary`）：
 *   `GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]`
 *
 * 🔴 **与 PC 端同源**：手机端与 `/production/piecework` 读的是**同一个端点、同一份服务端聚合**
 * ⇒ 同刻同数据下两处数字必然一致。页面**不重算**：`total` 用服务端值，
 * **不**把 `per_worker` 求和来「验证」（那是第二份会漂的口径，且一旦漂了没人知道谁对）。
 *
 * 手机端交互：期间只在「本月 / 上月」两个按钮之间切（不引入日期 Picker 的平台差异）→
 * 三个块：① 汇总卡（总额 + 人数）② 未定价提醒（**有就置顶**：干了活但没定价 = 一分钱没有）
 * ③ 按工人（工资口径）+ 按工序明细。**无宽表格、无横向滚动**：一行卡片两列（名字 / 金额 + 数量）。
 *
 * 缺值不渲染假数据：`total` 非数 ⇒ `-`；`unpriced` 块缺失 ⇒ 整块不出现（不写「未定价 0 件」）。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import { SurfaceLoginRequired, SurfaceState } from '../../../components/admin/SurfaceState'
import { operationDisplayName } from '../../../utils/operationDisplayName'
import {
  formatYuanAmount,
  getPieceworkReport,
  periodOf,
  previousPeriodOf,
  type AdminOpsResult,
  type PieceworkReport,
} from '../../../services/adminOpsService'
import '../../../styles/admin-surfaces.scss'

export default function AdminPieceworkPage() {
  const { isLoggedIn } = useAuthStore()
  const now = new Date()
  const currentPeriod = periodOf(now)
  const previousPeriod = previousPeriodOf(now)
  const [period, setPeriod] = useState(currentPeriod)
  const [report, setReport] = useState<AdminOpsResult<PieceworkReport> | null>(null)

  const load = useCallback(async (nextPeriod: string) => {
    setReport(null)
    setReport(await getPieceworkReport({ period: nextPeriod }))
  }, [])

  useEffect(() => {
    if (!isLoggedIn) return
    load(period)
  }, [isLoggedIn, period, load])

  if (!isLoggedIn) return <SurfaceLoginRequired />

  const data = report?.status === 'ok' ? report.data : null
  const workers = data?.per_worker ?? []
  const operations = data?.per_operation ?? []
  const unpricedRows = data?.unpriced?.operations ?? []

  return (
    <ScrollView scrollY className='admin-surface' data-testid='admin-piecework-page'>
      <View className='admin-surface__header'>
        <Text className='admin-surface__title'>计件工资报表</Text>
        <Text className='admin-surface__subtitle' data-testid='piecework-period'>
          期间 {data?.period ?? period}
        </Text>
      </View>

      <View className='admin-surface__body'>
        <View className='admin-filters'>
          <View
            className={`admin-filter${period === previousPeriod ? ' admin-filter--active' : ''}`}
            data-testid='piecework-period-prev'
            onClick={() => setPeriod(previousPeriod)}
          >
            <Text>上月（{previousPeriod}）</Text>
          </View>
          <View
            className={`admin-filter${period === currentPeriod ? ' admin-filter--active' : ''}`}
            data-testid='piecework-period-current'
            onClick={() => setPeriod(currentPeriod)}
          >
            <Text>本月（{currentPeriod}）</Text>
          </View>
        </View>

        {report === null && <SurfaceState kind='loading' message='正在加载计件报表…' />}
        {report?.status === 'forbidden' && <SurfaceState kind='forbidden' message={report.message} />}
        {report?.status === 'error' && <SurfaceState kind='error' message={report.message} />}

        {data && (
          <View>
            {/* ① 汇总（服务端 total，**不重算**） */}
            <View className='admin-card'>
              <Text className='admin-card__title'>本期间计件总额</Text>
              <Text className='admin-card__amount' data-testid='piecework-total'>
                {formatYuanAmount(data.total)}
              </Text>
              <Text className='admin-card__note'>
                共 {workers.length} 人 · 与电脑端「计件工资」读同一份服务端聚合
              </Text>
            </View>

            {/* ② 未定价（有就置顶：未定价的报工不进 total ⇒ 不列出来就是静默吞掉一笔钱） */}
            {unpricedRows.length > 0 && (
              <View className='admin-notice' data-testid='piecework-unpriced'>
                <Text className='admin-notice__text'>
                  {data.unpriced?.qty ?? 0} 件已报工但「未定价」（不计入上面的金额）
                </Text>
                {data.unpriced?.hint ? (
                  <Text className='admin-notice__text'>{data.unpriced.hint}</Text>
                ) : null}
                {unpricedRows.map((row, index) => (
                  <Text
                    key={`unpriced-${index}`}
                    className='admin-notice__text'
                    data-testid={`piecework-unpriced-${index}`}
                  >
                    {operationDisplayName(row)} · {row.qty} 件
                  </Text>
                ))}
              </View>
            )}

            {/* ③ 按工人（工资口径） */}
            <Text className='admin-section-title'>按工人</Text>
            {workers.length === 0 ? (
              <SurfaceState kind='empty' message='该期间没有计件报工' />
            ) : (
              workers.map((worker, index) => (
                <View
                  key={worker.worker_name}
                  className='admin-card'
                  data-testid={`piecework-worker-${index}`}
                >
                  <View className='admin-card__row'>
                    <Text className='admin-card__title'>{worker.worker_name}</Text>
                    <Text className='admin-card__amount'>
                      {formatYuanAmount(worker.amount)}
                    </Text>
                  </View>
                  <Text className='admin-card__note'>合格 {worker.qty} 件</Text>
                </View>
              ))
            )}

            {/* ④ 按工序明细（显示名走 operationDisplayName：#4621/#4630 口径） */}
            {operations.length > 0 && (
              <View>
                <Text className='admin-section-title'>按工序</Text>
                {operations.map((row, index) => (
                  <View
                    key={`${row.operation}-${index}`}
                    className='admin-card'
                    data-testid={`piecework-operation-${index}`}
                  >
                    <View className='admin-card__row'>
                      <Text className='admin-card__title'>{operationDisplayName(row)}</Text>
                      <Text className='admin-card__amount'>{formatYuanAmount(row.amount)}</Text>
                    </View>
                    <Text className='admin-card__note'>合格 {row.qty} 件</Text>
                  </View>
                ))}
              </View>
            )}

            {workers.length > 0 && (
              <Text className='admin-hint'>
                金额 = Σ(合格数量 × 报工当时的单价快照)，返工/报废不计入；单位：元
              </Text>
            )}
          </View>
        )}
      </View>
    </ScrollView>
  )
}
