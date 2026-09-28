import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import {
  getDashboardStats,
  getPendingTasks,
  getProductionTodoOverview,
  formatYuan,
  formatPercent,
  productionTodoTargetUrl,
  OPERATION_STATE_LABELS,
  thresholdSourceLabel,
  type DashboardStats,
  type PendingTask,
  type ProductionTodo,
  type ProductionTodoResult,
} from '../../../services/dashboardService'
import './index.scss'

/**
 * 数据一屏（米宝商家端，issue #2977）+ **生产概览（待办优先，issue #5641）**
 *
 * 版面顺序即口径：**第一屏先答「今天要处理的 N 件事」**（生产待办，每件可点即办），
 * 经营数字退到第二屏。
 *
 * 🔴 三条纪律（issue #5641）：
 * ① **不编数字**：所有待办、计数、阈值、文案都来自服务端规则引擎
 *    （`GET /api/admin/production/todo-overview`，字段名见 `dashboardService` 的
 *    `ProductionTodoOverview`）；本页**不重算**任何数、不做生成式归因。
 * ② **说不清的就不说**：拿不到数据的行/块**不渲染**（不出现 `undefined 米 / ¥NaN` 这种占位）。
 * ③ **三种空态互不混淆**：`ok + 0 条` ⇒「今天没有待处理」；`forbidden` ⇒「无权限」；
 *    `error` ⇒「加载失败」。把 403 渲染成「没有待处理」= 把「看不到」说成「没有」。
 */
export default function DashboardPage() {
  const { user } = useAuthStore()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [tasks, setTasks] = useState<PendingTask[]>([])
  const [todoResult, setTodoResult] = useState<ProductionTodoResult | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const [s, t, todo] = await Promise.all([
      getDashboardStats(),
      getPendingTasks(),
      getProductionTodoOverview(),
    ])
    setStats(s)
    setTasks(t)
    setTodoResult(todo)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 下拉刷新（页面配置 enablePullDownRefresh 触发 onPullDownRefresh）
  usePullDownRefresh(async () => {
    await load()
    Taro.stopPullDownRefresh()
  })

  // 数字卡片
  const MetricCard = ({ label, value, change, sign, unit }: {
    label: string
    value: string
    change?: string
    sign?: string
    unit?: string
  }) => (
    <View className='metric-card'>
      <Text className='metric-card__label'>{label}</Text>
      <View className='metric-card__value-row'>
        <Text className='metric-card__value'>{value}</Text>
        {unit && <Text className='metric-card__unit'>{unit}</Text>}
      </View>
      {change && (
        <Text className={`metric-card__change ${sign === '+' ? 'metric-card__change--up' : sign === '-' ? 'metric-card__change--down' : ''}`}>
          {change}
        </Text>
      )}
    </View>
  )

  const totalSalesYuan = stats ? formatYuan(stats.todaySales) : '--'

  const renderLoading = () => (
    <View className='dashboard-loading'>
      <Text>加载经营数据中...</Text>
    </View>
  )

  // ── 生产待办（第一屏）：条数取**真正渲染出来的那些**，与服务端口径一致 ──
  const overview = todoResult?.status === 'ok' ? todoResult.data : null
  const prodTodos = Array.isArray(overview?.todos) ? overview!.todos : []
  const todoStats = overview?.stats
  const byType = todoStats?.by_type ?? {}
  const operations = todoStats?.operations ?? {}
  const numeric = (value: unknown): number | null => (typeof value === 'number' ? value : null)

  /** 可点即办：URL 由服务端给；拿不到合法路由 ⇒ 不可点（不给死链） */
  const openTodo = (todo: ProductionTodo) => {
    const url = productionTodoTargetUrl(todo)
    if (!url) return
    Taro.navigateTo({ url })
  }

  const emptyText =
    todoResult?.status === 'forbidden'
      ? '无权限查看生产待办（需生产看板权限）'
      : todoResult?.status === 'error'
        ? '生产待办加载失败，请下拉刷新重试'
        : todoResult?.status === 'ok'
          ? '今天没有待处理'
          : '正在加载…'

  if (loading && !stats) return renderLoading()

  return (
    <ScrollView scrollY className='dashboard-page'>
        {/* 头部问候 */}
        <View className='dashboard-header'>
          <Text className='dashboard-header__greet'>
            {user?.nickname ? `${user.nickname}，` : ''}
            {todoResult?.status === 'ok' && prodTodos.length > 0
              ? `今天要处理的 ${prodTodos.length} 件事`
              : '今日生产概览'}
          </Text>
          <Text className='dashboard-header__sub'>数据来自米宝 · 每 30 分钟自动刷新</Text>
        </View>

        {/* ═══════════ 第一屏：生产待办（每件可点即办） ═══════════ */}
        <View className='dashboard-section' data-testid='production-todos'>
          <Text className='dashboard-section__title'>今天要处理的事</Text>
          {prodTodos.length === 0 ? (
            <View className='dashboard-empty'>
              <Text data-testid='production-todos-empty'>{emptyText}</Text>
            </View>
          ) : (
            prodTodos.map(todo => {
              const url = productionTodoTargetUrl(todo)
              return (
                <View
                  key={todo.id}
                  className='task-item'
                  data-testid={`production-todo-${todo.type}`}
                  onClick={() => openTodo(todo)}
                >
                  <View className='task-item__tag'>
                    <Text className={`task-item__tag-text task-item__tag-text--${todo.type}`}>
                      {todo.type_label}
                    </Text>
                  </View>
                  <View className='task-item__body'>
                    <Text className='task-item__title'>{todo.title}</Text>
                    <Text className='task-item__time'>{todo.reason}</Text>
                  </View>
                  {todo.priority === 'high' && (
                    <View className='task-item__urgent'>
                      <Text className='task-item__urgent-text'>紧急</Text>
                    </View>
                  )}
                  {url && <Text className='task-item__arrow'>›</Text>}
                </View>
              )
            })
          )}
        </View>

        {/* ═══════════ 第二屏：在制工序进度（三态，非告警） ═══════════ */}
        {todoStats && (
          <View className='dashboard-section' data-testid='production-progress'>
            <Text className='dashboard-section__title'>在制工序进度</Text>
            {numeric(todoStats.todo_total) !== null && (
              <Text className='dashboard-section__sub' data-testid='production-todo-total'>
                今天要处理的 {todoStats.todo_total} 件：待排产 {byType.to_schedule ?? 0} ·
                卡在哪 {byType.stuck ?? 0} · 待发货 {byType.to_ship ?? 0}
              </Text>
            )}
            <View className='production-progress'>
              {Object.keys(OPERATION_STATE_LABELS)
                .filter(key => numeric(operations[key]) !== null)
                .map(key => (
                  <Text key={key} className='production-progress__item'>
                    {OPERATION_STATE_LABELS[key]} {operations[key]}
                  </Text>
                ))}
            </View>
            <Text className='dashboard-section__note'>
              「做了一半」只作进度提示，不作催办（无可靠完工信号，拿它当卡点会误报正在干的活）
            </Text>
            {numeric(todoStats.stuck_threshold_hours) !== null && (
              <Text className='dashboard-section__note'>
                卡在哪判据：上道做完后等待超过 {todoStats.stuck_threshold_hours} 小时
                （阈值来源：{thresholdSourceLabel(todoStats.threshold_source)}）
              </Text>
            )}
          </View>
        )}

        {/* ═══════════ 第二屏：经营数字 ═══════════ */}
        <View className='metric-grid'>
          <MetricCard
            label='今日销售额'
            value={totalSalesYuan}
            unit='元'
            change={formatPercent(stats?.todaySalesChange ?? 0)}
            sign={(stats?.todaySalesChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='今日订单'
            value={String(stats?.todayOrders ?? '--')}
            change={formatPercent(stats?.todayOrdersChange ?? 0)}
            sign={(stats?.todayOrdersChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='本月营收'
            value={stats ? formatYuan(stats.monthRevenue) : '--'}
            unit='元'
            change={formatPercent(stats?.monthRevenueChange ?? 0)}
            sign={(stats?.monthRevenueChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='AI 接管率'
            value={`${stats?.aiSessionRate ?? '--'}%`}
          />
          <MetricCard
            label='活跃会话'
            value={String(stats?.activeSessions ?? '--')}
          />
        </View>

        {/* 第二行：客户/商品/售后 */}
        <View className='metric-grid metric-grid--secondary'>
          <MetricCard label='客户总数' value={String(stats?.totalCustomers ?? '--')} />
          <MetricCard label='今日新增客户' value={String(stats?.newCustomersToday ?? '--')} />
          <MetricCard label='在售商品' value={String(stats?.totalProducts ?? '--')} />
          <MetricCard label='待处理售后' value={String(stats?.totalTickets ?? '--')} />
          <MetricCard label='待发货' value={String(stats?.pendingShipOrders ?? '--')} />
        </View>

        {/* 经营待办（数字 → 一个动作） */}
        <View className='dashboard-section'>
          <Text className='dashboard-section__title'>待办事项</Text>
          {tasks.length === 0 ? (
            <View className='dashboard-empty'>
              <Text>暂无待办，AI 正在处理中</Text>
            </View>
          ) : (
            tasks.slice(0, 5).map(task => (
              <View key={`${task.type}-${task.id}`} className='task-item'>
                <View className='task-item__tag'>
                  <Text className={`task-item__tag-text task-item__tag-text--${task.type}`}>
                    {task.type === 'order' ? '订单' : '售后'}
                  </Text>
                </View>
                <View className='task-item__body'>
                  <Text className='task-item__title'>{task.title}</Text>
                  <Text className='task-item__time'>{task.createdAt ? task.createdAt.slice(0, 16).replace('T', ' ') : ''}</Text>
                </View>
                {task.priority === 'high' && (
                  <View className='task-item__urgent'>
                    <Text className='task-item__urgent-text'>紧急</Text>
                  </View>
                )}
              </View>
            ))
          )}
        </View>
      </ScrollView>
  )
}
