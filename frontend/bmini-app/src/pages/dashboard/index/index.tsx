import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
// 底栏（issue #6574）：按岗位权限裁剪，端侧自绘 + 收起原生条
import MerchantTabBar from '../../../components/MerchantTabBar'
import {
  getDashboardStats,
  getPendingTasks,
  getProductionTodoOverview,
  formatYuan,
  formatPercent,
  DASHBOARD_EMPTY_VALUE,
  productionTodoTargetUrl,
  OPERATION_STATE_LABELS,
  thresholdSourceLabel,
  type ProductionTodo,
  type ProductionTodoResult,
  type DashboardStatsResult,
  type PendingTasksResult,
} from '../../../services/dashboardService'
// 时间口径单一真值（issue #6666 判据 8）
import { formatMessageTime } from '../../../utils/datetime'
// 手机端菜单（issue #6570）：生产待办块的开关在**服务端**（`mobileSurfaces` 的 `production-todos`）
import { useMobileMenu } from '../../../components/admin/useMobileMenu'
// 商家面身份护栏（issue #6567）：纯工人设备打开本页 ⇒ 送回工人工作台
import { useMerchantSurfaceGuard } from '../../../utils/roleGuard'
import './index.scss'

/**
 * 数据一屏（黄金策商家端，issue #2977）+ **生产概览（待办优先，issue #5641）**
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
  useMerchantSurfaceGuard()
  const { user } = useAuthStore()
  const [statsResult, setStatsResult] = useState<DashboardStatsResult | null>(null)
  const [tasksResult, setTasksResult] = useState<PendingTasksResult | null>(null)
  const [todoResult, setTodoResult] = useState<ProductionTodoResult | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const [s, t, todo] = await Promise.all([
      getDashboardStats(),
      getPendingTasks(),
      getProductionTodoOverview(),
    ])
    setStatsResult(s)
    setTasksResult(t)
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

  // 数字卡片（issue #6685）：`unit` 只在**真有读数**时才挂 —— 占位 `--` 后面不许再跟「元」
  // （`--元` 与 `NaN元` 同族：都是把「没有这个数」装成一个读数）
  const MetricCard = ({ label, value, change, sign, unit, testId }: {
    label: string
    value: string
    change?: string
    sign?: string
    unit?: string
    /** 给「读数本身」一个稳定锚（判据要读的是值，不是整张卡的文字） */
    testId?: string
  }) => (
    <View className='metric-card'>
      <Text className='metric-card__label'>{label}</Text>
      <View className='metric-card__value-row'>
        <Text className='metric-card__value' data-testid={testId}>{value}</Text>
        {unit && value !== DASHBOARD_EMPTY_VALUE && <Text className='metric-card__unit'>{unit}</Text>}
      </View>
      {change && (
        <Text className={`metric-card__change ${sign === '+' ? 'metric-card__change--up' : sign === '-' ? 'metric-card__change--down' : ''}`}>
          {change}
        </Text>
      )}
    </View>
  )

  // 三态消费（issue #6666 判据 6）：`ok` 才拿数据；`forbidden` / `error` 各自有话说（不摆一排 `--`）
  const stats = statsResult?.status === 'ok' ? statsResult.data : null
  const tasks = tasksResult?.status === 'ok' ? tasksResult.data : []

  // `200 + 空 data`（`{}` / 缺键）时 `stats` 是**真值但一个字段都没有** ⇒ 走格式化层的占位
  // （issue #6685）：旧形态把 `undefined` 送进算钱路径 ⇒ 商家屏印出 `NaN元`（涉钱面，不许出）
  const totalSalesYuan = stats ? formatYuan(stats.todaySales) : ''
  /** 数字卡：缺值 / 坏值一律落 `--`（不印 `NaN` / `undefined`），真 `0` 照印 */
  const cardValue = (value: unknown): string =>
    typeof value === 'number' && Number.isFinite(value) ? String(value) : DASHBOARD_EMPTY_VALUE
  /** 涨跌幅：`undefined` 也落到 `--`（旧形态的 `?? 0` 把「没有这个数」说成「持平」） */
  const cardChange = (value: unknown): { text: string; sign: string } => {
    const text = formatPercent(value as number)
    return { text, sign: text.startsWith('+') ? '+' : text.startsWith('-') ? '-' : '' }
  }

  const renderLoading = () => (
    <View className='dashboard-loading'>
      <Text>加载经营数据中...</Text>
      {/* 底栏（issue #6574）：加载态也要有 —— 否则首屏那一下底栏整条消失 */}
      <MerchantTabBar current='dashboard' />
    </View>
  )

  // ── 生产待办（第一屏）：条数取**真正渲染出来的那些**，与服务端口径一致 ──
  const overview = todoResult?.status === 'ok' ? todoResult.data : null
  const prodTodos = Array.isArray(overview?.todos) ? overview!.todos : []
  const todoStats = overview?.stats
  const byType = todoStats?.by_type ?? {}
  const operations = todoStats?.operations ?? {}
  const numeric = (value: unknown): number | null => (typeof value === 'number' ? value : null)

  // 🔴 生产待办块的**开关在服务端**（issue #6570）：`/me` 的 `mobileSurfaces` 里没有 `production-todos`
  // （= 本岗位没有 `production:view`）⇒ 整块不渲染（不再摆一块「无权限查看生产待办」的噪音）。
  // 三态处置：`loading` ⇒ 先不渲染（避免闪一块注定要消失的内容）；`ok` ⇒ 按服务端清单；
  // `error`（菜单没拿到）⇒ **照渲染**，让本块自己的状态机去说（宁可不隐藏数据，也不静默吞掉待办）。
  const menu = useMobileMenu()
  const showProductionTodos =
    menu.state === 'error' || (menu.state === 'ok' && menu.surfaces.some((s) => s.key === 'production-todos'))

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

  if (loading && !statsResult) return renderLoading()

  return (
    <>
    <ScrollView scrollY className='dashboard-page'>
        {/* 头部问候 */}
        <View className='dashboard-header'>
          <Text className='dashboard-header__greet'>
            {user?.nickname ? `${user.nickname}，` : ''}
            {todoResult?.status === 'ok' && prodTodos.length > 0
              ? `今天要处理的 ${prodTodos.length} 件事`
              : '今日生产概览'}
          </Text>
          <Text className='dashboard-header__sub'>数据来自黄金策 · 每 30 分钟自动刷新</Text>
        </View>

        {/* ═══════════ 第一屏：生产待办（每件可点即办） ═══════════ */}
        {showProductionTodos && (
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
        )}

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
        {/* 三态（issue #6666 判据 6）：拿不到就说拿不到 —— 不摆一排 `--` 把「看不到」说成「没有」 */}
        {statsResult?.status === 'ok' ? (
        <>
        <View className='metric-grid'>
          <MetricCard
            label='今日销售额'
            value={totalSalesYuan}
            unit='元'
            testId='dashboard-metric-today-sales'
            change={cardChange(stats?.todaySalesChange).text}
            sign={cardChange(stats?.todaySalesChange).sign}
          />
          <MetricCard
            label='今日订单'
            value={cardValue(stats?.todayOrders)}
            change={cardChange(stats?.todayOrdersChange).text}
            sign={cardChange(stats?.todayOrdersChange).sign}
          />
          <MetricCard
            label='本月营收'
            value={stats ? formatYuan(stats.monthRevenue) : DASHBOARD_EMPTY_VALUE}
            unit='元'
            testId='dashboard-metric-month-revenue'
            change={cardChange(stats?.monthRevenueChange).text}
            sign={cardChange(stats?.monthRevenueChange).sign}
          />
          <MetricCard
            label='AI 接管率'
            value={typeof stats?.aiSessionRate === 'number' && Number.isFinite(stats.aiSessionRate)
              ? `${stats.aiSessionRate}%`
              : DASHBOARD_EMPTY_VALUE}
          />
          <MetricCard
            label='活跃会话'
            value={cardValue(stats?.activeSessions)}
          />
        </View>

        {/* 第二行：客户/商品/售后 */}
        <View className='metric-grid metric-grid--secondary'>
          <MetricCard label='客户总数' value={cardValue(stats?.totalCustomers)} />
          <MetricCard label='今日新增客户' value={cardValue(stats?.newCustomersToday)} />
          <MetricCard label='在售商品' value={cardValue(stats?.totalProducts)} />
          <MetricCard label='待处理售后' value={cardValue(stats?.totalTickets)} />
          <MetricCard label='待发货' value={cardValue(stats?.pendingShipOrders)} />
        </View>
        </>
        ) : (
          <View className='dashboard-section'>
            <Text className='dashboard-section__title'>经营数据</Text>
            <View className='dashboard-empty'>
              <Text
                data-testid={statsResult?.status === 'forbidden' ? 'dashboard-stats-forbidden' : 'dashboard-stats-error'}
                onClick={statsResult?.status === 'error' ? load : undefined}
              >
                {statsResult?.status === 'forbidden'
                  ? '无权限查看经营数据（需数据看板权限）'
                  : '经营数据加载失败，点此重试'}
              </Text>
            </View>
          </View>
        )}

        {/* 经营待办（数字 → 一个动作） */}
        <View className='dashboard-section'>
          <Text className='dashboard-section__title'>待办事项</Text>
          {tasksResult?.status !== 'ok' ? (
            <View className='dashboard-empty'>
              <Text
                data-testid={tasksResult?.status === 'forbidden' ? 'dashboard-tasks-forbidden' : 'dashboard-tasks-error'}
                onClick={tasksResult?.status === 'error' ? load : undefined}
              >
                {tasksResult?.status === 'forbidden'
                  ? '无权限查看待办（需订单 / 售后权限）'
                  : '待办加载失败，点此重试'}
              </Text>
            </View>
          ) : tasks.length === 0 ? (
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
                  <Text className='task-item__time'>{formatMessageTime(task.createdAt)}</Text>
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
      {/* 底栏（issue #6574）：按岗位权限裁剪（服务端下发 `mobileTabs`），原生的静态 4 项被收起 */}
      <MerchantTabBar current='dashboard' />
    </>
  )
}
